# ADR p48 — Login por correo o usuario (email como identidad global única)

**Fecha:** 2026-06-28
**Estado:** ✅ **Aceptado** (2026-06-28, Felipe). Implementación por fases (§5),
con verificación de regresiones por etapa antes de avanzar a la siguiente.
**Branch:** `develop`
**Origen:** Incidente de onboarding — el SPA muestra el campo de login como
"Correo electrónico" pero el backend autentica por `username`. Un admin de
clínica provisionado como `ines_diaz` / `inesdiaz@gmail.com` escribió su correo
→ 401 "credenciales incorrectas". Curl con `username=ines_diaz` → 200, lo que
confirmó que el problema es de **identidad de login**, no de credenciales.
**Decisión de producto (Felipe, 2026-06-28):** un usuario pertenece a una sola
clínica; **no** se soportará una cuenta única con acceso a múltiples
organizaciones. El correo identifica a un único usuario en toda la plataforma.

---

## 1. Decisión

Permitir **login por correo electrónico O por username**, sobre una identidad de
**correo electrónico obligatorio, normalizado a minúsculas y único globalmente**
(case-insensitive). `username` se conserva como identidad interna estable para
auditoría, throttle y logs — **NO** se cambia `USERNAME_FIELD`.

Reglas que se vuelven invariantes del sistema:

- **El correo de un `User` con correo no vacío es único case-insensitive en toda
  la plataforma** (`Lower(email)` único).
- **El correo es obligatorio en toda ruta de alta de usuario de aplicación**
  (provisioning de org + alta de staff). Las cuentas de sistema bootstrap
  (superuser por CLI, demo, seeds) quedan exentas y conviven vía índice parcial
  (ver §4 y trade-off T-3).
- **Un usuario no puede existir en dos clínicas con el mismo correo.** Si una
  persona trabaja para otra clínica, usará **otra cuenta con otro correo**. El
  caso multi-clínica queda **explícitamente fuera de alcance** del producto.
- **El login acepta correo o username.** Si el identificador contiene `@`, se
  resuelve a **exactamente un** usuario activo por correo (garantizado ≤1 por el
  constraint) o se devuelve **401 genérico** — nunca elige entre varios, nunca
  confirma existencia.

Esta decisión sigue la ruta **A2** del análisis de alternativas (§2).

### Por qué A2 encaja el modelo existente

`User.organization` es FK **único** (un usuario = una clínica) y `username` ya es
único global (`AbstractUser`). Hacer el correo único global **no introduce una
filosofía nueva**: suma el correo como segundo identificador global junto a
username. La decisión de producto "un usuario = una clínica" elimina la única
tensión real (el caso del veterinario suplente en varias clínicas), que era el
argumento a favor de C (§2).

---

## 2. Alternativas evaluadas y por qué se descartaron

Evaluadas con dos agentes (`backend-architect` + `api-security-audit`), ambos
verificando cada hallazgo contra el código.

| Opción | Qué es | Veredicto |
|---|---|---|
| **A2** ✅ | Email obligatorio + único global normalizado + resolver email-o-username; `username` se conserva | **ELEGIDA** |
| A1 | Resolver "exactamente-uno-activo, si no 401" SIN cambio de schema | **Descartada** |
| B | `email` pasa a ser `USERNAME_FIELD` global | **Descartada (crítico)** |
| C | Email único **per-tenant** + contexto de org en login | **Descartada por decisión de producto** |
| D | Mantener username; arreglar solo el label del SPA | **Adoptada como Fase 0** de A2, no como solución final |

### A1 — descartada (riesgo ALTO)
La seguridad multi-tenant descansa en **un check de código (`count == 1`) sobre
datos no-únicos, sin constraint DB detrás**. Un refactor futuro a
`.filter(...).first()`, un cambio de orden del ORM, o una carrera que deje
exactamente uno de un par activo, voltea silenciosamente "rechazar" →
"autenticar al tenant equivocado": un atacante con la contraseña del vet de
Org A recibe un token cuyo `user_id` resuelve (vía `authentication.py`) a la
fila de **Org B**. La protección es de una línea de profundidad, no de
invariante. Además agrega oráculo de enumeración + timing y deja sin arreglar el
bug latente de correos duplicados. Viola el invariante "cross-tenant = 404,
aislamiento estructural".

### B — descartada (riesgo CRÍTICO)
Django **exige** que `USERNAME_FIELD` sea único. Sobre el `email` no-único
confirmado, `ModelBackend.get_by_natural_key` → `get(email=value)` →
`MultipleObjectsReturned` (login 500 / DoS) o, con un backend `.first()`,
**autenticación cross-tenant arbitraria**. Aun con constraint único, B cambia la
clave natural, **rompe todos los logins por username existentes** (lockout
masivo), y obliga a tocar `createsuperuser`, la key del throttle, el re-fetch del
gate temp-password, y toda la auditoría `*_username`. Máximo blast radius, cero
beneficio sobre A2.

### C — descartada por decisión de producto (era el óptimo técnico de largo plazo)
C (email único **per-tenant** + contexto de org en login vía subdominio/slug/
selector) es la única opción que respeta el invariante estructural multi-tenant
**y** permite legítimamente el mismo correo en dos clínicas sin filtrar
existencia cross-tenant. Era el target técnico de largo plazo. **Se descarta
porque el producto decidió explícitamente NO soportar usuarios multi-clínica.**
Sin ese caso de uso, C solo agrega costo (contexto de org antes de autenticar:
DNS wildcard/TLS o un selector cuyo lookup pre-auth "qué clínicas tienen este
correo" es en sí una superficie de enumeración cross-tenant) sin beneficio. La
decisión de producto vuelve a C innecesariamente complejo.

### D — adoptada como Fase 0, no como solución final
D (mantener username, arreglar solo el label del SPA) resuelve el **incidente
reportado** (un bug de etiqueta) con cero superficie nueva de ataque, pero **no
entrega login por correo**, que es la dirección de producto. Se incorpora como
**Fase 0** (hotfix inmediato del label) dentro del plan de A2.

---

## 3. Trade-offs aceptados

- **T-1 — No se soportan usuarios multi-clínica.** Una persona que trabaje en dos
  clínicas necesita **dos cuentas con dos correos distintos**. Decisión de
  producto explícita. Consecuencia: el correo es identidad global, no per-tenant.
- **T-2 — Leak de existencia cross-tenant en el alta de staff.** Al exigir correo
  único global, `CreateEmployeeSerializer.validate_email` debe rechazar
  duplicados → un ADMIN de clínica que intenta crear un usuario con un correo ya
  usado en **otra** org recibe "correo no disponible", revelando que ese correo
  existe en la plataforma. **Aceptado** porque (a) el path de provisioning ya
  tiene exactamente este leak hoy (`platform/serializers.py`), (b) el alta de
  staff es ADMIN-only y throttleada, (c) se mitiga con mensaje genérico ("Este
  correo no está disponible") sin confirmar la organización.
- **T-3 — Cuentas de sistema sin correo. ⚠️ DECISIÓN ABIERTA (Felipe revisará).**
  El superuser creado por `createsuperuser` (CLI), la cuenta demo y los seeds
  pueden no tener correo (`email=''`). Hay dos formas de codificar la
  obligatoriedad:

  **Evidencia medida (2026-06-28, sobre `backend/apps`, sin venv):**
  - **127** sitios crean usuarios (`create_user`/`create_superuser`).
  - **~84 de 127 lo hacen SIN `email`** (solo ~43 pasan correo: provisioning,
    reset, algunos tests).
  - **122 de los 127 están en tests**, repartidos en **61 archivos**.
  - El modelo no overridea `REQUIRED_FIELDS` → `create_user(username, password)`
    deja `email=''`.

  **Opción T-3a — Índice único PARCIAL `WHERE email <> ''` (recomendada).**
  El correo obligatorio se enforcea en la **capa de aplicación** (los dos
  serializers de alta: provisioning + staff). El índice DB garantiza unicidad
  para todos los correos no vacíos (los reales). Las cuentas de sistema/tests
  conviven con `email=''`. Costo: bajo. Churn de tests: **nulo**. Garantía de
  producción: completa (todo usuario de clínica tiene correo único — lo dan los
  serializers).

  **Opción T-3b — `email` `NOT NULL` + único TOTAL a nivel DB (preferencia
  inicial de Felipe: "una sola regla para todo el sistema").**
  Una única regla en DB para todas las cuentas. Costo real medido:
  - Reescribir ~**84 fixtures** que crean usuarios sin correo; como el constraint
    es único global, **cada fixture necesita un correo distinto** (o un
    helper/factory `make_user()` que genere correos únicos) → churn en ~61
    archivos de test + riesgo de regresión durante la estabilización de beta.
  - Backfill de las cuentas de sistema (superuser CLI, demo, seeds) con correos
    sintéticos únicos (p.ej. `superadmin@sistema.local`).
  - Forzar correo en el manager `create_user` / `REQUIRED_FIELDS`.
  - **Beneficio en producción sobre T-3a: ninguno** — los usuarios reales ya
    obtienen correo único vía serializers; lo único que cambia es que las cuentas
    que **no son de clínica** (sistema/tests) también llevarían correo.

  **✅ DECISIÓN (2026-06-28, Felipe): T-3a (índice parcial).** La regla de negocio
  ("todo usuario funcional tiene correo obligatorio y único global") queda
  **completa** a nivel semántico vía serializers; el índice parcial solo exime
  cuentas que no son del dominio. T-3b se descarta por churn alto de tests +
  backfill de cuentas sintéticas sin beneficio de producción en beta.

  **Declaraciones explícitas que este ADR fija (condición de la aprobación):**
  1. La excepción de correo vacío aplica **únicamente** a cuentas técnicas:
     bootstrap (`createsuperuser` CLI), demo, seeds y fixtures de test.
  2. **Ningún flujo normal de negocio puede crear un usuario sin correo.** Toda
     ruta de alta de aplicación (provisioning de org + alta de staff) exige
     correo (`required`), lo normaliza a minúsculas y lo valida único global.
  3. **Todo usuario creado desde la aplicación tendrá email obligatorio,
     normalizado (lowercase) y único globalmente.** El índice parcial DB respalda
     la unicidad de todos los correos no vacíos; los serializers respaldan la
     obligatoriedad y normalización en las rutas de negocio.
- **T-4 — `username` sigue existiendo y es derivado.** No se elimina `username`
  (lo usan auditoría, throttle, logs, `MustChangePasswordGate`). El provisioning
  seguirá derivando un username; el usuario simplemente ya no necesita conocerlo
  para entrar.
- **T-5 — Split de bucket de throttle.** Sin normalizar la key, el mismo usuario
  es alcanzable por dos strings (correo y username) → dos buckets
  `login_by_user` → 2× presupuesto de fuerza bruta por cuenta para un atacante
  multi-IP. Se **mitiga** normalizando la key al username canónico resuelto (§6);
  el cap por IP (`LoginRateThrottle`, 5/15min) acota de todos modos.

---

## 4. Cambios necesarios (backend, frontend, auth, migraciones, pruebas)

> Referencias de código verificadas por ambos agentes. Líneas aproximadas.

### Modelo / persistencia
- `backend/apps/users/models.py` — `Meta.constraints`:
  `UniqueConstraint(Lower('email'), name='user_email_ci_unique', condition=~Q(email=''))`.
  Constraint **funcional** (case-insensitive vía `Lower`) y **parcial** (excluye
  correo vacío, T-3). NO se cambia `USERNAME_FIELD`; NO se cambia
  `email` a `null=False` a nivel DB (la obligatoriedad va por serializer).

### Migraciones (dos, en orden)
1. `users/migrations/0009_dedup_user_email.py` (**data migration**) — escanea
   `User` por correos NO vacíos duplicados case-insensitive; **falla ruidosamente**
   listando colisiones (NO auto-mergea cuentas — no son fusionables con
   seguridad). A escala beta (1 org, pocos usuarios) la resolución es manual y
   trivial. Sin default destructivo → reversible (es report).
2. `users/migrations/0010_user_email_ci_unique.py` — `AddConstraint(...)` del §
   Modelo. Postgres lo construye tras garantizar 0 duplicados. Aditivo,
   zero-downtime. Revertible con `RemoveConstraint`.

### Serializers (enforce obligatorio + único + normalizado)
- `backend/apps/users/serializers.py` — `CreateEmployeeSerializer.validate_email`
  (nuevo): `value = value.strip().lower()`; rechaza vacío; rechaza
  `User.objects.filter(email__iexact=value).exists()` con mensaje genérico
  (T-2), shape `{code:'validation_error', errors:{email:[...]}}` (ADR p16).
- `backend/apps/platform/serializers.py` — `validate_admin_email` ya valida
  unicidad global (`email__iexact`); se le añade normalización `.strip().lower()`
  para consistencia.

### Autenticación (resolver de login)
- Nuevo `EmailOrUsernameTokenObtainPairSerializer` (en
  `apps/users/serializers.py` o `apps/core/auth_serializers.py`) que sobrescribe
  `validate`: si el identificador contiene `@` → normaliza a minúsculas →
  `User.objects.filter(email__iexact=identifier, is_active=True)`; si hay
  exactamente uno (garantizado ≤1 por el constraint), sustituye
  `attrs[username_field]` por su `username` canónico antes de `super().validate`;
  si no, deja el valor tal cual (→ simplejwt 401 genérico). **Constant-time:** en
  la rama sin match se debe correr un hash dummy (el resolver corre ANTES de
  `ModelBackend`, que normalmente aporta esa mitigación) para no abrir oráculo de
  timing. Se cablea vía `serializer_class` en `ThrottledTokenObtainPairView`
  (`config/urls.py`). `User` está excluido del ratchet AST
  (`test_tenant_scoping_audit.py:48`) → el lookup no rompe CI ni requiere
  `for_organization`.

### Fix del gate temp-password (`config/urls.py:~87`)
- Hoy la vista re-busca `User.objects.get(username=raw_username)` tras el 200 para
  (a) el 403 `temp_password_expired` y (b) el flag `must_change_password`. Con
  login por correo, `raw_username` sería el correo → `DoesNotExist` → se salta el
  **403 de expiración** (único chokepoint de expiración, vive solo aquí;
  `MustChangePasswordGate` valida el flag pero NO la expiración). **Fix:** resolver
  por el `user_id` del access token recién emitido
  (`AccessToken(response.data['access'])['user_id']` → `User.objects.get(pk=...)`),
  volviendo el gate **agnóstico al identificador**. Mantener el guard
  `DoesNotExist` por la carrera de borrado.
  - *Corrección a la auditoría previa:* el redirect a cambiar contraseña NO se
    pierde (dispara vía `/me/` → `MeView.must_change_password`); lo que se perdía
    era el 403 de expiración. Este fix lo restaura para el path por correo.

### Throttle (`apps/core/throttling.py`)
- `LoginUserRateThrottle.get_cache_key` keya por `ip + identificador.lower()`.
  **Mitigación T-5:** resolver el correo → username canónico también para la key,
  de modo que correo y username compartan bucket. El cap por IP
  (`LoginRateThrottle`, 5/15min, key solo IP) se mantiene como backstop.

### Frontend
- **Fase 0 (hotfix inmediato):** `frontend/src/components/LoginForm.jsx` — label
  "Correo electrónico" → "Correo o usuario", placeholder neutro. El valor se sigue
  enviando como `username` a `POST /api/token/` (sin cambio de contrato; el
  resolver del backend lo maneja). `autoComplete` puede quedar `username`.
- **Final:** confirmar que `useLoginForm`/`auth/login.js` no requieren cambios (la
  clave `username` se preserva). Opcional cosmético: renombrar el estado interno
  `username` → `identifier`.

### Pruebas (deben existir y pasar antes de merge)
Backend (nuevas, p.ej. `apps/users/tests/test_login_by_email.py` +
`test_email_identity_constraint.py`):
- **2 orgs, mismo correo activo → 401, ningún token emitido** (resolución a
  NINGÚN tenant) + el constraint **impide crear** la colisión (IntegrityError).
- **Aserción cross-tenant del JWT:** decodificar el token y verificar que
  `user_id` → `organization_id` == la org de las credenciales usadas, nunca la
  otra.
- **Paridad de enumeración:** no-match vs contraseña-incorrecta producen cuerpos/
  status 401 byte-idénticos; latencia dentro de tolerancia (hash dummy presente).
- **Expiración temp por correo:** temp password admin + reloj >24h + login por
  correo → 403 `temp_password_expired` (prueba el fix de `urls.py:87`).
- **`must_change_password` por correo:** usuario con flag + login por correo →
  respuesta marcada.
- **Throttle sin split:** fallos por correo + intentos por el username de la misma
  cuenta comparten un bucket.
- **Interacción `is_active`:** usuario desactivado (refresh blacklisteado por
  `deactivate_staff`) no entra por correo ni por username.
- **Normalización:** `Foo@X.com` y `foo@x.com` no coexisten y resuelven igual.
- **Serializers:** alta de staff y provisioning rechazan correo duplicado
  (cross-org y misma-org) con mensaje genérico.

Frontend:
- `LoginForm.test.jsx` — label/placeholder "Correo o usuario".

---

## 5. Plan de migración por fases (zero-downtime)

Orden: schema → backfill/dedup → enforce → resolver + fix gate → frontend →
cierre. Cada fase es independientemente desplegable y reversible.

| Fase | Contenido | Reversibilidad |
|---|---|---|
| **0 — Hotfix label (frontend)** | Relabel "Correo o usuario" en `LoginForm.jsx`. Desbloquea el incidente YA. Sin cambio de contrato (sigue enviando `username`). | Revertir el string. |
| **1 — Dedup (data migration)** | `0009_dedup_user_email.py`: detecta correos no-vacíos duplicados CI; **falla listando colisiones** (no auto-mergea). Resolver manual a escala beta. | Es report; no destructivo. |
| **2 — Constraint (schema)** | `0010_user_email_ci_unique.py`: `AddConstraint(UniqueConstraint(Lower('email'), condition=~Q(email='')))`. Aditivo. | `RemoveConstraint`. |
| **3 — Enforce serializers** | `validate_email` en `CreateEmployeeSerializer` (obligatorio+único+lower) + normalización en `platform/serializers.py`. | Quitar `validate_email`. |
| **4 — Resolver + fix gate + throttle** | `EmailOrUsernameTokenObtainPairSerializer` + fix `urls.py:~87` por `user_id` + normalización de la key del throttle + tests. | Revertir wiring del serializer y restaurar lookup por username (seguro: el constraint no es requerido para login por username). |
| **5 — Frontend final + docs** | Confirmar `useLoginForm`/`login.js`; actualizar `docs/modules/organizations.md` (modelo de identidad); marcar este ADR como Aceptado. | Cosmético. |

**Paso de mayor cuidado:** Fase 2 (constraint). Solo es riesgoso revertirlo si se
crearon correos duplicados **después** del constraint — lo cual el constraint
mismo previene. La Fase 1 garantiza que el `AddConstraint` aplica limpio.

---

## 6. Riesgos y mitigaciones

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Migración del constraint falla por correos duplicados existentes | Media (deploy) | Fase 1 dedup que falla ruidosamente ANTES del `AddConstraint`; a escala beta es resolución manual de pocos casos. |
| Muchos correos `''` en cuentas de sistema rompen un `unique` total | Media | Constraint **parcial** `WHERE email <> ''` (T-3); obligatoriedad enforced en serializers, no en DB. |
| Auth-bypass cross-tenant (elegir usuario equivocado) | Alta (si mal hecho) | Constraint único (≤1 match por construcción) + regla "exactamente uno, si no 401"; **nunca** `.first()`. Test cross-tenant del JWT obligatorio. |
| Bypass del 403 temp-password vía path por correo | Media | Fix `urls.py:~87` resolviendo por `user_id` del token; test de expiración por correo. |
| Oráculo de enumeración/timing en el resolver | Media | 401 genérico idéntico en todas las ramas + hash dummy en no-match (el resolver corre antes de `ModelBackend`). Test de paridad. |
| Leak de existencia cross-tenant en alta de staff | Baja (aceptada, T-2) | Mensaje genérico "correo no disponible"; alta ADMIN-only + throttle. |
| Split de bucket de throttle (2× fuerza bruta) | Baja | Normalizar la key al username canónico (T-5); cap por IP como backstop. |
| `MultipleObjectsReturned` si alguien usa `.get(email=)` sobre datos pre-constraint | Media | Resolver usa `.filter(...).count()/first()` con guard; el `.get` por correo solo se permite POST-constraint. |
| Normalización inconsistente (`Foo@` vs `foo@`) reintroduce ambigüedad | Media | Unicidad sobre `Lower(email)` + normalización a minúsculas en todos los paths de escritura y en el resolver. |

---

## 7. Invariante nuevo

> **El correo de un `User` con correo no vacío es único de forma
> case-insensitive en toda la plataforma** (`Lower(email)` único, parcial sobre
> `email <> ''`), obligatorio en toda ruta de alta de aplicación (provisioning +
> alta de staff). **Un usuario pertenece a una sola organización; no existe
> identidad multi-clínica.** **El login acepta correo o username; un correo
> resuelve a exactamente un usuario activo o devuelve 401 genérico** — nunca
> elige entre varios, nunca confirma existencia. `username` permanece como
> identidad interna de auditoría/throttle.

---

## Archivos afectados (resumen)

- `backend/apps/users/models.py` — constraint funcional parcial.
- `backend/apps/users/migrations/0009_dedup_user_email.py` (nuevo).
- `backend/apps/users/migrations/0010_user_email_ci_unique.py` (nuevo).
- `backend/apps/users/serializers.py` — `validate_email` + resolver (o módulo aparte).
- `backend/apps/platform/serializers.py` — normalización de `admin_email`.
- `backend/config/urls.py` — wiring del resolver + fix del gate por `user_id`.
- `backend/apps/core/throttling.py` — normalización de la key (T-5).
- `frontend/src/components/LoginForm.jsx` — relabel (Fase 0).
- Tests backend + frontend (§4).
- `docs/modules/organizations.md` — documentar el modelo de identidad.

## Referencias

- ADR p19 (provisioning de orgs), ADR p21 (credential lifecycle / gate
  temp-password), ADR p47 (auth session hardening: gate `is_active` + revocación
  de sesión).
- Análisis fuente: agentes `backend-architect` + `api-security-audit`
  (2026-06-28), verificados contra código.

---

## Aprobación

- [x] **Felipe** — aprobado 2026-06-28. Decisión A2 + T-2 + dedup + T-3a.

Aprobado. Implementación en curso siguiendo el plan por fases (§5), con
verificación de regresiones por etapa antes de avanzar.


## Addendum 2026-11-19 — El ADMIN puede editar el correo (plan Equipo A1, D10)

- `PATCH /api/staff/<public_id>/` acepta `email`. Se mantiene la unicidad global sin distinguir
  mayúsculas (incluidos inactivos) y el mensaje genérico «Este correo no está disponible.» (T-2). La
  carrera entre dos guardados la resuelve el índice `user_email_ci_unique`: quien pierde recibe `400` en el
  campo. Cambiar el correo no cierra sesiones (el JWT no lo contiene).
- **Condición para el futuro:** si algún día se agrega recuperación de contraseña por correo, que un ADMIN
  pueda cambiar el correo de otra persona se convierte en una vía de robo de cuentas. Debe revisarse antes
  de habilitar esa recuperación.
