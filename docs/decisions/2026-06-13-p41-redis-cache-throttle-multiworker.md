# ADR p41: Redis como cache + store de throttling multi-worker (P1-1)

**Fecha**: 2026-06-13
**Estado**: Aceptado — implementado (FASE 1, pre-beta)
**Documentos relacionados**:
- `DEPLOY_VPS_PLAN.md` (stack Docker Compose en VPS único) — esto agrega un servicio
- `docs/decisions/2026-06-12-p40-backup-offsite-disaster-recovery.md` (mismo patrón fail-loud en prod)
- `docs/system-reference.md` §3 (invariantes: idempotencia en DB, append-only ledger)
- Código: `backend/config/settings.py` (`CACHES`), `backend/apps/core/throttling.py`,
  `docker-compose.prod.yml` (servicio `redis`), `.env.prod.example`

## Contexto

El stack corre `gunicorn --workers=3 --threads=2` (`docker-compose.prod.yml`,
`Procfile`). No había bloque `CACHES` en `settings.py` → Django usaba el default
**`LocMemCache`**, que es un dict en memoria **por proceso**. Con 3 workers =
**3 caches aislados**, y `--max-requests=1000` recicla cada worker borrando su
cache periódicamente.

Dos consecuencias, una de ellas de seguridad:

1. **Throttle de login diluido ×N_workers (crítico).** DRF persiste los
   contadores de rate-limit en `caches['default']`. Con `LocMemCache` el límite
   `login = 5/15min` (`LoginRateThrottle` por IP + `LoginUserRateThrottle` por
   IP+username) era **por worker** → un atacante reparte ~5 intentos por worker
   y obtiene ~`5×N` antes del bloqueo; además el reciclado de workers **resetea**
   el contador mid-window. La protección brute-force estaba materialmente
   debilitada. Mismo efecto sobre `change_password`, `staff_password_reset`,
   `platform_org_create`, `vitals` y los globales `user`/`anon`.

2. **Dashboard inconsistente entre workers (medio).** `dashboard_summary`
   cachea su payload 30s por `org` (`dash:summary:{org_id}`). Con caches
   aislados, dos requests del mismo admin podían ver snapshots distintos y una
   invalidación por signal en un worker no tocaba la copia de otro. Ventana ≤30s.

Restricción de esta fase: **simplicidad > arquitectura enterprise**. Diseñar
para las primeras 10–50 clínicas en un VPS único, no para millones de usuarios.

## Decisión

Introducir **Redis** como backend de cache compartido entre workers, usado
**exclusivamente** para:

1. **Django cache backend** — cache del dashboard summary (cross-worker).
2. **Store de throttling DRF** — contadores de login/brute-force compartidos.

### 1. Redis NO almacena nada crítico (es infra, no una segunda base de datos)

Lo único que vive en Redis es **derivable y reconstruible**: la cache del
dashboard (TTL 30s, ≤4 queries para recalcular) y los contadores de throttle
(se reconstruyen solos en la siguiente ventana). Un wipe total de Redis pierde,
como máximo, esa cache de 30s + los contadores en vuelo.

Permanecen en su fuente de verdad actual, **fuera de Redis**:

| Dato | Dónde sigue | Por qué NO en Redis |
|---|---|---|
| JWT access/refresh | stateless / blacklist en DB (`token_blacklist`) | El auth no debe depender de un store efímero |
| Sesiones Django | DB (solo `/admin`) | Pocas, durables; mover a Redis no aporta |
| Idempotency keys de pago (`X-Idempotency-Key`) | DB, unique `(org, key)` | Durabilidad-crítico anti doble-cobro (ADR p27) |
| Ledger financiero, historiales clínicos, stock | PostgreSQL | Fuente de verdad; Redis es efímero por diseño |

Postgres permanece como única fuente de verdad. Redis es una capa de
aceleración + coordinación, descartable.

### 2. Redis efímero (sin persistencia)

`redis:7-alpine` con `--save "" --appendonly no` (sin RDB ni AOF, sin volumen).
Como nada en Redis es autoritativo, persistir a disco solo agrega I/O y
complejidad sin ganancia de correctitud. `--maxmemory 256mb
--maxmemory-policy noeviction`: a esta escala el footprint es trivial; si la
memoria se llenara, preferimos que las escrituras fallen ruidosamente a que se
**eviten silenciosamente los contadores de throttle** (lo que debilitaría la
protección brute-force sin aviso). `--requirepass` obligatorio (defensa en
profundidad en la red interna, aunque el puerto nunca se publica). Sin `ports:`.

### 3. Fail-open vs fail-closed — dos cache aliases

La tensión: los throttles globales corren en **cada** request contra
`caches['default']`. Si esa cache fuera dependencia dura (fail-closed), un blip
de Redis tiraría **toda** la API. Si fuera fail-open, un Redis caído
**desactivaría** el throttle de login (brute-force libre). No hay opción gratis
con una sola cache. Se resuelve con **dos aliases** sobre el mismo Redis:

| Alias | `IGNORE_EXCEPTIONS` | Lo usa | Redis caído ⇒ |
|---|---|---|---|
| `default` | `True` (fail-open) | dashboard cache + throttles generales | API sigue arriba; dashboard recalcula de DB; throttles generales abren |
| `throttle_login` | `False` (fail-closed) | `LoginRateThrottle`, `LoginUserRateThrottle` | el **login** falla cerrado (outage breve) en vez de abrir una ventana brute-force |

Es decir: ante un Redis caído elegimos **disponibilidad** para la API general y
**seguridad** para el único endpoint pre-auth que es objetivo de brute-force.
Los throttles de login resuelven su cache vía `@property` (`caches['throttle_login']`)
para respetar `@override_settings` en tests. `DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS=True`
hace que los errores tragados por `default` igual aparezcan en logs/Sentry.

### 4. Fallback local + fail-loud en producción

```
REDIS_URL set                                   → Redis (default + throttle_login)
REDIS_URL vacío + dev/staging                   → LocMemCache (sin Redis local)
REDIS_URL vacío + production                    → REFUSE TO BOOT (RuntimeError)
REDIS_URL vacío + production + break-glass flag  → LocMemCache per-worker + RuntimeWarning
```

El fail-loud en prod replica el patrón de CORS y del backup (p40): arrancar en
producción sin cache compartida re-rompe silenciosamente la garantía del
throttle multi-worker. `ALLOW_LOCAL_CACHE_EMERGENCY` (default `False`) es el
**break-glass**: si Redis está caído de raíz y hay que arrancar igual, este flag
permite el fallback a `LocMemCache` per-worker — **degradado a propósito**
(re-diluye el throttle). Es una emergencia de **máximo 24h**: restaurar Redis y
volver el flag a `False`. Emite `RuntimeWarning` en cada boot mientras esté activo.

## Alternativas evaluadas

- **`RedisCache` nativo de Django 6.0** (en vez de `django-redis`): rechazado.
  El backend nativo **no** implementa `delete_pattern`, que `dashboard/signals.py`
  ya invoca (hoy es no-op bajo `try/except AttributeError` con LocMem). `django-redis`
  lo provee de verdad + pooling + `IGNORE_EXCEPTIONS` granular (clave para los
  dos aliases). Una dep extra bien justificada.
- **Una sola cache fail-closed** (Redis = dependencia dura): rechazado. Un blip
  de Redis tiraría toda la API porque los throttles globales corren en cada
  request. Inaceptable para un SaaS en producción.
- **Una sola cache fail-open**: rechazado como única medida. Deja el login sin
  throttle si Redis cae. El alias `throttle_login` fail-closed cierra ese hueco.
- **Rate-limit en Caddy (`rate_limit`) como backstop de `/api/token/*`**:
  diferido. La directiva `rate_limit` **no** existe en el build estándar
  `caddy:2-alpine`; requiere una imagen custom vía `xcaddy` con el módulo
  third-party `mholt/caddy-ratelimit`. Eso agrega infra de build + una dep
  externa de madurez variable. El alias `throttle_login` fail-closed entrega la
  misma protección brute-force **dentro de Django** (principio del proyecto:
  "el cambio vive dentro de Django"), sin imagen custom. La directiva Caddy
  queda como capa adicional opcional a futuro si se justifica.
- **Persistencia AOF/RDB**: rechazada. Nada en Redis es fuente de verdad;
  persistir solo agrega I/O y un volumen que mantener.
- **Redis para sesiones / Celery broker / cache agresivo adicional**: fuera de
  scope (ver abajo).

## Riesgos aceptados

| Riesgo | Mitigación / por qué se acepta |
|---|---|
| Redis caído ⇒ login outage breve (fail-closed) | Redis es local + `restart: unless-stopped` + healthcheck; el outage es el restart (segundos). Preferible a abrir brute-force. |
| Redis caído ⇒ throttles **post-auth** abren (fail-open): `change_password` (10/h), `staff_password_reset` (5/h), `platform_org_create` (20/h) + globales `user`/`anon` | Aceptado FASE 1: todos son post-auth (el actor ya tiene credenciales válidas; `change_password` además llavea por actor, no por víctima). Ventana = restart de segundos; visible en Sentry vía `DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS`. Solo el **login** (pre-auth, objetivo brute-force real) va fail-closed en `throttle_login`. Endurecer `change_password`/`staff_password_reset` a fail-closed es un follow-up barato si se requiere. |
| Restart de Redis ⇒ se pierden contadores de throttle | No peor que hoy: el reciclado de workers ya los reseteaba. Ventana de segundos. |
| `--requirepass` visible vía `docker inspect` / env | Mismo trust-level que `.env.prod` (chmod 600) y `POSTGRES_PASSWORD`; requiere root del host. Puerto nunca publicado. |
| Break-glass deja la prod degradada | Default `False`, exige set explícito, emite `RuntimeWarning` en cada boot, documentado como máx 24h. |
| `delete_pattern` pasa de no-op a real con django-redis | Inofensivo: hoy no se cachean series (no hay `cache.set` con `SERIES_CACHE_PREFIX`); empieza a funcionar correctamente cuando se cacheen. |
| `noeviction` ⇒ escrituras fallan si se llena la memoria | A 10–50 clínicas el footprint es trivial; preferimos fallo ruidoso a evicción silenciosa de contadores de seguridad. `maxmemory 256mb` con límite de container 320M. |
| Los dos aliases comparten un único presupuesto de memoria (`noeviction`) | Failure domain compartido: una OOM por flood de claves de throttle (muchos pares IP/username) podría impedir escrituras también en `throttle_login`. Muy improbable a esta escala; las claves de throttle expiran con su ventana; `DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS` lo expone en Sentry. |
| `REDIS_URL` lleva el password embebido → posible fuga en logs de error de conexión (Sentry, con `DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS=True`) | redis-py normalmente no incluye credenciales en el repr de `ConnectionError` (solo host:port). Si se confirma fuga: mover el password a `OPTIONS['PASSWORD']` con `LOCATION` sin credenciales, o scrub en Sentry `before_send`. Observado/aceptado en FASE 1. |

## Rollback

Diseñado para que **`REDIS_URL` vacío ⇒ fallback automático** sin redeploy de código:

1. **Blip de Redis**: sin acción — `restart: unless-stopped` lo levanta; el
   `default` fail-open mantiene la API arriba.
2. **Redis roto de raíz, hay que arrancar ya**: setear
   `ALLOW_LOCAL_CACHE_EMERGENCY=True` (+ `REDIS_URL` vacío) y reiniciar `backend`
   → `LocMemCache` per-worker = **exactamente el estado pre-P1-1** (degradado,
   máx 24h).
3. **Revertir del todo**: quitar el servicio `redis` del compose + revertir el
   bloque `CACHES`. Cero migraciones, cero cambios de datos → rollback limpio.

## Consecuencias

- ✅ Throttle de login compartido entre workers → la protección brute-force deja
  de diluirse ×N_workers (objetivo de seguridad de P1-1).
- ✅ Dashboard consistente entre workers; invalidación por signal efectiva global.
- ✅ Redis es infra descartable: ningún dato crítico se mueve fuera de Postgres/DB.
- ✅ Fail-loud en prod + fallback dev por una variable; rollback trivial.
- ✅ Costo trivial (un container `redis:7-alpine`, ~efímero, ≤320M).
- ⚠️ Nueva dependencia operativa: un servicio más que monitorear (healthcheck +
  Sentry cubren el aviso).
- ⚠️ `REDIS_PASSWORD` nuevo secreto en `.env.prod`.

## Criterio de terminado (FASE 1)

1. `CACHES` con `default` (fail-open) + `throttle_login` (fail-closed) sobre Redis.
2. Login throttles usan `throttle_login`; el resto usa `default`.
3. Servicio `redis` efímero, con password, sin puerto, healthcheck autenticado.
4. Fail-loud en prod sin `REDIS_URL`; break-glass `ALLOW_LOCAL_CACHE_EMERGENCY`.
5. `requirements.lock` regenerado (`django-redis==7.0.0`, `redis==8.0.0`).
6. Pruebas (siguiente ciclo con Docker): throttle cross-worker (3 workers → el
   6º login da 429), dashboard cache compartida, invalidación por signal, Redis
   apagado (default degrada / login falla cerrado), suite Django existente.

## Fuera de scope (NO en esta fase)

Explícitamente **no** se implementa (evitar overengineering pre-beta):
**Celery**, **Redis Cluster**, **Redis Sentinel**, **sesiones en Redis**,
**cache agresivo adicional**, y la directiva **`rate_limit` de Caddy** (capa
opcional futura, requiere imagen `xcaddy` custom). Si el negocio los requiere
después (jobs async, HA de Redis, multi-instancia), se decidirán en su propio ADR.
