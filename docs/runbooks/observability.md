# Runbook — Observability (Capa 7)

Capa 7 de [DEPLOY_VPS_PLAN.md](../../DEPLOY_VPS_PLAN.md). Cubre lo mínimo para enterarte de fallas antes que el cliente: error tracking, uptime probe externo, disk usage alert. NO Grafana / Loki / Prometheus — overkill para beta cerrada single-VPS.

**Stack final**:
- **Sentry** — backend + frontend errors + performance traces. Tier free hasta 5K events/mes.
- **UptimeRobot O Healthchecks.io** — uptime probe externo. Tier free.
- **disk-alert.sh** — cron hourly, POST a webhook (Slack/Discord) si >80%.
- **Docker logs** — captura nativa stdout, rotación configurada en Capa 5.

---

## 1. Sentry — backend

### Setup inicial

1. Crear cuenta en https://sentry.io (free).
2. Crear proyecto tipo **Django**. Nombre sugerido: `vet-backend`.
3. Copiar el DSN (formato `https://<key>@<orgID>.ingest.us.sentry.io/<projectID>`).
4. Setear en `.env.prod`:

```bash
SENTRY_DSN=https://...@sentry.io/...
SENTRY_TRACES_SAMPLE_RATE=0.05    # 5% (default sano para prod)
SENTRY_RELEASE=                   # vacío OK, mejor setear con git SHA en deploy
```

### Por qué `SENTRY_TRACES_SAMPLE_RATE=0.05`

Cada trace consume cuota Sentry. Free tier = ~10K transacciones/mes. Con 5% sampling y 100 req/min sostenidas:
- 100 req/min × 60 × 24 × 30 = 4.3M req/mes
- 4.3M × 0.05 = 216K traces/mes → excede tier free 22x

Si proyectas >50K req/mes:
- Bajar a 0.02 (2%) o 0.01 (1%)
- O upgrade Team tier ($26/mes)

Para beta cerrada con <1K req/día: `0.05` es seguro.

### Tag de environment

Settings auto-pasa `environment=ENVIRONMENT` al `sentry_sdk.init`. En Sentry UI filtra por `environment:production` para excluir dev/staging.

### Release tag (recomendado para detectar regresiones)

Setear `SENTRY_RELEASE=<sha-corto>` antes del deploy:

```bash
# Wrapper deploy.sh
cd /opt/vet/app
git pull
SENTRY_RELEASE=$(git rev-parse --short HEAD)
sed -i "s/^SENTRY_RELEASE=.*/SENTRY_RELEASE=$SENTRY_RELEASE/" .env.prod
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

Sentry agrupa issues por release. Si una regresión aparece exclusivamente en release `abc1234`, sabes qué commit revisar.

**P1-5 A5**: `release` cae a `GIT_SHA` si `SENTRY_RELEASE` está vacío
(`release=SENTRY_RELEASE or GIT_SHA or None` en settings). Setear `GIT_SHA` en el
deploy basta para alinear el release de Sentry con `/api/version/` (ver abajo).

### Privacidad — scrubbing de PII (P1-5 A2)

`sentry_sdk.init` pasa `before_send=apps.core.observability.before_send` además de
`send_default_pii=False`. **Invariante**: a Sentry NUNCA debe salir información
clínica/financiera/PII. El hook (defensa en profundidad sobre `send_default_pii`):

- **dropea el body del request** (`request.data`) y `cookies` — pueden contener
  notas clínicas, montos, teléfonos.
- **filtra headers sensibles** a `[Filtered]`: `Authorization`, `Cookie`,
  `X-Idempotency-Key`, `X-CSRFToken`, `X-Api-Key`, `Proxy-Authorization`.
- **strip de PII del bloque `user`** (`email`, `username`, `ip_address`, `name`,
  `phone`) — solo se conserva `id` (interno, no PII).
- **fail-closed**: ante un evento con shape inesperado, descarta el evento antes
  que arriesgar una fuga.

Se taggea `organization_id` + `user.id` (ids internos) en
`TenantJWTAuthentication` → en Sentry filtrás por `organization_id:<n>` para saber
**qué clínica** fue afectada sin exponer su nombre. El frontend tiene un scrub
espejo (`src/utils/sentryScrub.js`, ver §2).

### Correlación request_id end-to-end (P1-5 A1)

`RequestIDMiddleware` (outermost) acuña/propaga un `X-Request-ID` por request. El
**mismo** id viaja: Frontend (`api/client.js` lo manda) → header → logs backend
(`req=<id>` en cada línea) → logs RBAC → tag Sentry → cuerpo del 500
(`{code:server_error, request_id}`) → header `X-Request-ID` de la respuesta. Si el
cliente manda basura en el header, se ignora y se genera uno nuevo (blindaje
anti log-injection: solo se acepta un UUID).

Cuando una clínica reporta un error con su "código", buscás ese id en una sola
pasada: `docker compose ... logs backend | grep <request_id>`.

### Versión desplegada — `/api/version/` (P1-5 A5)

`GET /api/version/` (público, sin DB, como `healthz`) responde
`{version, commit, environment}`. Sirve para responder **qué versión estaba
corriendo** cuando una clínica reporta un error. Setear en el deploy:

```bash
GIT_SHA=$(git rev-parse --short HEAD)   # → commit + release Sentry + /api/version/
```

Si `GIT_SHA` queda vacío, `/api/version/` reporta `version="dev"` y `commit=null`.

### Validar que llega un evento

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend \
  python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('hello from VPS')"
```

Revisar Sentry UI → Issues → debe aparecer "hello from VPS" en <30s.

### Dashboards a configurar (recomendado)

| Dashboard | Métrica | Use |
|-----------|---------|-----|
| **Issues** (default) | error count + frequency | Triage diario |
| **Performance** | p95 transacción `/api/*` | Detectar degradación API |
| **Releases** | issues por release | Vincular regresiones a deploys |
| **Alerts** | nuevo issue P1 → email/Slack | Mismo `ALERT_WEBHOOK` que disk-alert |

Configurar alert: Sentry → Alerts → New Alert Rule:
- Condition: "An issue is first seen"
- Filter: `environment:production` + `level:error`
- Action: Send email + Slack webhook

---

## 2. Sentry — frontend

DSN distinto del backend (proyecto Sentry separado). Setear:

```bash
VITE_SENTRY_DSN=https://<key>@<orgID>.ingest.us.sentry.io/<projectID-frontend>
```

Build args en `frontend/Dockerfile` ya leen `VITE_SENTRY_DSN`. Cambiar el DSN requiere `docker compose build frontend` para re-bake el bundle (build-time, no runtime).

Validación: abrir DevTools en `https://app.tu-dominio.com`, inducir un error JS (`throw new Error('test')` en consola), revisar Sentry UI frontend project.

### P1-5 A3/A4 — hardening frontend

- **`environment` + `release`** (`main.jsx`): `VITE_SENTRY_ENVIRONMENT` (default =
  modo Vite) y `VITE_SENTRY_RELEASE` (= SHA del build). Build args en el Dockerfile.
- **`beforeSend` scrub** (`src/utils/sentryScrub.js`): espejo del backend — dropea
  `request.data`/`cookies`, filtra headers sensibles, strip PII del `user`.
- **ErrorBoundary reporta a Sentry**: `componentDidCatch` llama
  `Sentry.captureException` con el `componentStack` y muestra el **`event_id`** al
  usuario ("Código de error: … compártelo con soporte"). Antes solo evitaba la
  pantalla blanca; ahora el crash es visible para ops.
- **Source maps** (ver §6): `vite.config.js` emite source maps `hidden` y
  `@sentry/vite-plugin` los sube cuando hay credenciales de upload, luego los borra.
  El Dockerfile además hace `find dist -name '*.map' -delete` como safeguard → ningún
  `.map` llega a nginx. Build args nuevos: `VITE_SENTRY_ENVIRONMENT`,
  `VITE_SENTRY_RELEASE`, y (secreto build-time) `SENTRY_AUTH_TOKEN` / `SENTRY_ORG` /
  `SENTRY_PROJECT`.

---

## 3. Uptime probe externo

**Por qué externo**: si el VPS está caído, los crons internos no corren para alertar. Probe externo (ping desde otro DC) detecta caídas reales.

### Opción A — UptimeRobot (recomendado)

Tier free: 50 monitors, ping cada 5min, alerta email/SMS/Slack.

1. Crear cuenta en https://uptimerobot.com.
2. Add New Monitor:
   - Type: **HTTPS**
   - URL: `https://app.tu-dominio.com/api/healthz/`
   - Interval: 5 min
   - Keyword (optional): `ok` (verifica que el body contenga "ok" — no solo 200)
3. Configurar contacts (email primario + Slack webhook recomendado).
4. Probar: ejecutar `docker stop vet-backend-1` en VPS, esperar 6-10min, debe llegar alerta.

### Opción B — Healthchecks.io

Sirve doble propósito: deadman switch para crons (Capa 6) + uptime probe.

Para uptime probe HTTP: configurar como **HTTP Probe** en el dashboard (no "ping" tradicional). Tier free es generoso.

### Probe `/api/healthz/` vs `/api/readyz/`

- `healthz` = proceso vivo, NO toca DB. Probe externo debe usar este.
- `readyz` = DB reachable. Usar para alertas internas (Caddy healthcheck) o monitoreo separado.

Si pones `readyz` en uptime externo: cualquier blip de DB dispara false alarm. Mejor: 2 monitors, uno por endpoint, severidades distintas.

---

## 4. Disk usage alert

Script `scripts/disk-alert.sh` ya integrado al `crontab.example` (cada hora, minuto 15). Monitorea por default:
- `/` (raíz)
- `/var/lib/docker` (containers + images + volumes)
- `/var/backups/vet` (dumps locales)

Para activar alertas, setear `ALERT_WEBHOOK` en el crontab:

```bash
crontab -e
# Cambiar:
15 * * * *  ALERT_THRESHOLD=80 /opt/vet/app/scripts/disk-alert.sh ...
# Por:
15 * * * *  ALERT_THRESHOLD=80 ALERT_WEBHOOK=https://hooks.slack.com/services/... /opt/vet/app/scripts/disk-alert.sh ...
```

Webhook formats soportados:
- **Slack**: `https://hooks.slack.com/services/T.../B.../...` (incoming webhook)
- **Discord**: usar webhook URL con `/slack` sufijo: `https://discord.com/api/webhooks/.../slack`
- **Healthchecks.io fail URL**: `https://hc-ping.com/<uuid>/fail`

Exit codes:
- 0 = todo OK bajo threshold
- 1 = alerta disparada (incluye webhook empty → solo log)
- 2 = webhook POST falló (problema de red o URL malformado)

---

## 5. Docker logs — captura + búsqueda

Rotación configurada en Capa 5 (`/etc/docker/daemon.json` → `max-size: 10m, max-file: 5`). Sin esto los logs llenan disco en días.

### Ver logs en vivo

```bash
docker compose -f /opt/vet/app/docker-compose.prod.yml --env-file /opt/vet/app/.env.prod logs -f --tail=100 backend
docker compose -f /opt/vet/app/docker-compose.prod.yml --env-file /opt/vet/app/.env.prod logs -f --tail=100 caddy
docker compose -f /opt/vet/app/docker-compose.prod.yml --env-file /opt/vet/app/.env.prod logs -f --tail=100 postgres
```

### Grep eventos críticos

Los loggers RBAC y tenant validation emiten JSON estructurado a stdout. Para filtrar:

```bash
# Decisiones RBAC denegadas
docker compose ... logs backend | grep RBAC_DENIED

# Tentativas cross-tenant (Issue de seguridad — investigar TODAS)
docker compose ... logs backend | grep TENANT_MISMATCH_DETECTED

# Failed logins
docker compose ... logs backend | grep LOGIN_FAILED

# Password reset events
docker compose ... logs backend | grep ADMIN_PASSWORD_RESET_ISSUED

# Backup script
tail -100 /var/log/vet-backup.log
```

### Correlación por request_id (P1-5 A1)

Cada línea de log lleva `req=<request_id>` (formato verbose) y los eventos JSON
incluyen el campo `request_id`. Es el **mismo** `X-Request-ID` de la respuesta. Para
reconstruir todo lo que pasó en un request reportado por el cliente:

```bash
docker compose ... logs backend | grep <request_id>
```

Fuera de un request (crons, management commands) el id sale como `req=-`.

### Cuándo upgradear a log shipping

Stack actual = `docker logs` + grep manual. Suficiente para 1-5 servicios.

Considerar Loki + Promtail (autohosted) o Logflare/Logtail (managed) cuando:
- Tengas >3 servicios de los que grepear
- Necesites búsqueda full-text histórica (>7 días back)
- Quieras alertas basadas en log patterns (ej. "más de 10 TENANT_MISMATCH_DETECTED en 5min")

Para beta = innecesario.

---

## 6. Source maps frontend (P1-5 A4 — ya cableado)

Los stack traces minificados son inútiles en Sentry. P1-5 A4 ya integra el upload
de source maps vía `@sentry/vite-plugin` (devDependency):

- `vite.config.js`: `build.sourcemap: 'hidden'` (emite `.map` sin el comentario
  `sourceMappingURL` → el navegador no los descarga). El plugin se carga **solo**
  cuando están las 3 credenciales de upload; con token sube los `.map` a Sentry y
  los borra del `dist` (`filesToDeleteAfterUpload`).
- `frontend/Dockerfile`: safeguard `find dist -name '*.map' -delete` post-build →
  ningún `.map` llega a nginx aunque el upload no haya corrido (no exponer el código).
- `@sentry/cli` (dep transitiva, trae el binario de upload) tiene su build script
  aprobado en `frontend/package.json` → `pnpm.onlyBuiltDependencies: ["@sentry/cli"]`.
  En CI/Docker su postinstall corre durante `pnpm install`. (Antes vivía en un
  `frontend/pnpm-workspace.yaml` con un campo `allowBuilds` inexistente — pnpm lo
  ignoraba y, sin `packages:`, pnpm 9 fallaba el install con "packages field missing
  or empty". Se movió al campo real soportado por pnpm 9/10/11.)

Pasar al build del frontend (build-time, **secretos solo en CI** — idealmente
BuildKit `--secret`; nunca llegan al bundle ni al image runtime):

```bash
SENTRY_AUTH_TOKEN=...   SENTRY_ORG=...   SENTRY_PROJECT=...
VITE_SENTRY_RELEASE=$(git rev-parse --short HEAD)   # debe igualar el release del backend
```

Sin esas credenciales el build funciona igual (plugin no se carga); solo se pierde
la de-minificación de stack traces hasta configurarlas.

Para vincular issues a commits exactos (post-beta) también podés usar `sentry-cli
releases set-commits --auto` en el deploy con las mismas credenciales.

---

## 7. Checklist Capa 7 pre-launch

```
[ ] SENTRY_DSN backend configurado en .env.prod
[ ] VITE_SENTRY_DSN frontend configurado en .env.prod (DSN distinto)
[ ] SENTRY_TRACES_SAMPLE_RATE=0.05 (ajustar según volumen esperado)
[ ] GIT_SHA seteado en el deploy (→ release Sentry + /api/version/)
[ ] SENTRY_AUTH_TOKEN/ORG/PROJECT en el build del frontend (source maps) — P1-5 A4
[ ] Verificado: /api/version/ reporta el commit correcto (no "dev")
[ ] Verificado: ErrorBoundary muestra event_id ante un crash JS — P1-5 A3
[ ] Sentry alert rule: nuevo issue P1 en production → email/Slack
[ ] Test event capturado (sentry_sdk.capture_message("hello"))
[ ] UptimeRobot monitor creado contra /api/healthz/ cada 5min
[ ] Slack/Discord/email contact agregado al monitor
[ ] disk-alert.sh ejecuta sin error (smoke)
[ ] ALERT_WEBHOOK en crontab apuntando a Slack/Discord
[ ] (opcional) Healthchecks.io deadman para los 4 crons (Capa 6)
[ ] Verificado: docker logs backend muestra eventos RBAC structured
[ ] Verificado: log rotation funcional (docker info | grep "Logging Driver")
```

---

## 8. Troubleshooting

| Síntoma | Causa probable | Fix |
|---------|----------------|-----|
| Sentry no recibe events | DSN mal pegado / SENTRY_DSN vacío | `docker compose ... exec backend python -c "from django.conf import settings; import sys; sys.exit(0 if settings else 1)"` y verificar |
| Sentry quota exceeded | TRACES_SAMPLE_RATE muy alto | Bajar a 0.01 o upgrade tier |
| Sentry recibe events pero stack traces frontend minificados | Build sin credenciales de upload → el `@sentry/vite-plugin` no se cargó (P1-5 A4) | Pasar `SENTRY_AUTH_TOKEN`/`SENTRY_ORG`/`SENTRY_PROJECT` + `VITE_SENTRY_RELEASE` al `docker compose build frontend` (§6). Verificar que el release del bundle iguala el del evento |
| UptimeRobot reporta DOWN constantemente | Probe respeta TLS — certificado Caddy aún emitiéndose (ACME challenge falla por DNS no propagado) | `curl -v https://app.tu-dominio.com/` desde tu laptop. Si falla, revisar A record + UFW :80 (ACME HTTP-01) |
| disk-alert dispara con `/var/lib/docker` >80% | Container images viejas + volumes huérfanos | `docker system prune -a --volumes` (CUIDADO: borra unused — confirmar primero con `--dry-run`) |
| backend logs muestran tracebacks repetidos sin que Sentry los agrupe | release tag faltante | Verificar `SENTRY_RELEASE` en `.env.prod` y rebootear backend |

---

## Siguiente

Capa 8 — pre-launch security review (auditoría completa antes de invitar usuarios reales). NO requiere VPS, todo se valida contra compose local + bundle build.

## B9: evidencia operativa LLM

Eventos cerrados llm_budget_admitted, llm_budget_rejected, llm_budget_exhausted,
llm_usage_recorded y llm_usage_unavailable; único atributo agregado purpose
(planner/operation_authorizer/operation_verifier). No etiquetas de tenant,
conversación, teléfono o contenido. Una caída inmediatamente después del commit
puede omitir el log: la autoridad es TurnWork/LLMCall, no el evento de logging.

metrics.compute_llm_usage exige organización y admite filtro TurnWork. Expone
roles, retries, errores, admitted_calls y unknown_usage_calls; los subtotales
conocidos están separados del total desconocido. Coste permanece desconocido.
El inspector readonly detecta admisiones sin observación y discrepancias de
contadores. Responsable: operador técnico del agente; acción: investigar la
evidencia y retirar capacidad si procede, sin reponer cupo ni borrar filas.
Esto aporta evidencia COST de componente; no PASS de PROFILE-BETA-1/EVAL/SCALE.

## B9C — Observación de capacidad

`compute_concurrency(org)` consulta, sin escribir, límite de release, trabajos
activos con lease/epoch válidos, saturación, trabajos PENDING e inbound pendiente
sin TurnWork. Cada valor es una observación, no autorización ni lectura atómica
de toda la cola. El tenant es argumento de consulta para operadores autorizados,
no label de series. No se persiste nuevo contenido conversacional.

Eventos de vocabulario cerrado: `AGENT_CONCURRENCY_ADMITTED`,
`AGENT_CONCURRENCY_SATURATED`, `AGENT_CONCURRENCY_DEFERRED`; scope organization y
limit 1. No UUID/phone/user/prompt como labels. Se emiten después del commit y
pueden faltar por crash; TurnWork sigue siendo autoridad. B3 aporta completed,
failed, lease_expired, reclaimed y fencing_reject; no segundo contador de release.

Acción del operador técnico: ante saturación persistente, revisar cola y leases
del tenant autorizado, causa de retry/provider y fencing; retirar capacidad o
reducir carga según runbook, nunca resetear tokens/contadores. No nuevas alertas
sin responsable ni thresholds de rendimiento. El corpus registra snapshots en
claim/wire y journals PID/backend independientes; sus métricas de invariantes
no sustituyen colas/p95/muestras de PROFILE-BETA-1. Ver
[acta B9C](../implementacion-b9c-agente-whatsapp-2026-09-27.md).
