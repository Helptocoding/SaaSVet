# ADR p47 — Auth session hardening (robo/reutilización de sesión)

**Fecha:** 2026-06-27
**Estado:** ✅ Aceptado e implementado (alcance acotado) — resto diferido POST-BETA
**Branch:** `develop`
**Origen:** Auditoría de seguridad de autenticación (modelo de amenaza:
atacante con acceso al navegador / a un token; DevTools, Postman, proxy).

## Contexto

Auditoría sobre el flujo de sesión JWT (login → access 15 min → refresh
rotation 7 días, ADR p20/p21/p22). Catorce hallazgos (H-01..H-14). Se
clasificaron en tres cubetas:

1. **Vulnerabilidad real con buen beneficio/riesgo** → se arregla ahora.
2. **Mejora arquitectónica grande** (cambia el modelo de transporte de la
   credencial o el contrato de sesión) → ADR futuro, fuera de alcance
   mientras estabilizamos beta.
3. **Limitación inherente al modelo Bearer/JWT** → riesgo aceptado y
   documentado.

Principio rector: **no introducir cambios de arquitectura de auth durante
la estabilización del producto.** Este ADR sólo cubre fixes locales,
reversibles y de bajo riesgo.

## Decisión — alcance IMPLEMENTADO

### H-06 — Desactivar usuario corta acceso de inmediato

**Antes:** `StaffDeactivateView` sólo hacía `is_active=False`. El refresh
token emitido antes de la baja seguía vivo hasta `REFRESH_TOKEN_LIFETIME`
(7 días); un empleado dado de baja podía seguir renovando sesión.

**Matiz encontrado en la auditoría:** simplejwt YA rechaza el *access
token* de un usuario inactivo en `get_user()` porque `CHECK_USER_IS_ACTIVE`
es `True` por default (no lo sobrescribimos). El gap real era el **refresh
token**, que el `TokenRefreshSerializer` nunca valida contra `is_active`.

**Fix (dos capas):**
- **Revocación de sesión al desactivar** — la lógica pasa al service
  `apps.users.services.deactivate_staff`, que blacklistea TODOS los
  `OutstandingToken` del target (mismo patrón snapshot+blacklist que
  `reset_password_for_staff`, ADR p21) dentro de `transaction.atomic`, y
  emite el log de auditoría `STAFF_DEACTIVATED`. El refresh endpoint pasa a
  rechazar el token (401) inmediatamente. La view queda delgada (resuelve
  `public_id` + tenant scope, delega al service). El guard de
  self-deactivation (lockout, F13) y los gates tenant/ADMIN_SAAS viven en
  el service como defensa-en-profundidad.
- **Gate `is_active` explícito en `TenantJWTAuthentication`** — re-valida
  sobre la instancia re-cargada (la que setea el contexto de audit). Es
  redundante con el default de simplejwt **a propósito**: hace la garantía
  "desactivar = cortar acceso" local e independiente de un flag de librería
  que un upgrade/override podría apagar en silencio.

### H-07 / H-08 — Fugas de credencial por `console.*`

`console.log(err)` / `console.error(err)` sobre un error de Axios exponen
`err.config.headers.Authorization = "Bearer <JWT>"` en la consola del
navegador (e historial). `console.error(..., err.response.data)` vuelca el
cuerpo HTTP completo.

**Fix:** todos los `console.*(err)` y el log de `response.data` se
reemplazan por `console.error(apiError(err))` — `apiError` sólo extrae un
string legible del body, nunca toca `config.headers`. Gate de regresión:
`frontend/src/test/noConsoleTokenLeak.test.js` escanea `src/` y falla si
reaparece cualquiera de los dos anti-patrones (estilo grep-gate, como el
ban de `public_id || id`).

### H-09 — `Cache-Control: no-store` en endpoints de auth

Login, refresh y change-password devuelven material de credencial. Sin
`no-store`, un proxy intermediario mal configurado podría cachearlos por
URL. **Fix:** `NoStoreResponseMixin` (`apps/core/mixins.py`) fuerza el
header vía `finalize_response` (cubre éxito, error y throttle 429). Aplicado
a `ThrottledTokenObtainPairView`, `PublicTokenRefreshView`,
`ChangeMyPasswordView`.

### Tests de regresión

- `apps/users/tests/test_deactivate_revokes_session.py` — el access token
  previo deja de funcionar (401) y el refresh token previo es rechazado
  (401) tras desactivar; blacklist de todos los outstanding; contrato 204 /
  self-deactivation 400 preservado; log de auditoría.
- `apps/core/tests/test_auth_no_store.py` — `Cache-Control: no-store` en
  login (éxito + fallo), refresh y change-password.
- `frontend/src/test/noConsoleTokenLeak.test.js` — gate anti-fuga consola.

## Decisión — DIFERIDO (ADR futuro, POST-BETA)

No se tocan mientras estabilizamos. Cada uno cambia el modelo de transporte
de la credencial o el contrato de sesión y requiere su propio ADR:

| Hallazgo | Mejora diferida | Por qué fuera de alcance |
|---|---|---|
| H-01 / H-04 / H-05 | **Refresh token en cookie HttpOnly** | Cambia todo el transporte de credencial; impacta CORS, CSRF, login, refresh, logout. Es el fix estructural de "token robable desde storage", pero es un proyecto, no un parche. |
| H-04 | Device/IP binding del refresh | Falsos positivos con móvil/VPN; necesita diseño + telemetría. |
| H-13 | Gestión de sesiones concurrentes ("cerrar otras sesiones") | Feature nueva sobre `OutstandingToken`, no un fix. |
| H-14 | Expiración por inactividad (sliding) | Tradeoff UX (forzar re-login); knob a calibrar. |
| H-10 | `atomic`+`select_for_update` en refresh rotation | Override de internals de simplejwt; ventana ~50ms, rotation+blacklist ya activos. |
| H-11 | `CHECK_REVOKE_TOKEN=True` | Invalida access tokens al cambiar password (cierra ventana de 15 min). Ya hacemos DB-fetch por request, así que el costo es marginal — pero la ventana de 15 min está documentada como aceptada en ADR p20; reabrir esa decisión amerita su propio ADR. |

## Riesgo aceptado (inherente al modelo Bearer/JWT)

- **H-03** — el header `Authorization: Bearer <JWT>` es visible en el
  Network tab de DevTools en TODO sistema basado en Bearer. Sin mitigación
  práctica; la defensa real es proteger el acceso al navegador.
- **H-12** — `POST /api/token/refresh/` es público por diseño (el refresh
  token ES la credencial). Throttleado (`LoginRateThrottle`, ADR p41).

## Archivos afectados

- `backend/apps/core/authentication.py` — gate `is_active`.
- `backend/apps/users/services.py` — `deactivate_staff`.
- `backend/apps/users/views.py` — `StaffDeactivateView` delega al service;
  `ChangeMyPasswordView` usa `NoStoreResponseMixin`.
- `backend/apps/core/mixins.py` — `NoStoreResponseMixin` (nuevo).
- `backend/config/urls.py` — mixin en login + refresh views.
- `frontend/src/pages/{config,staff,appointments,pets,petDetail,inventory}.jsx`
  — `console.error(apiError(err))`.
- Tests: ver arriba.

## Invariante nuevo

**Desactivar un usuario (`is_active=False`) revoca todas sus sesiones en el
acto**: el access token previo se rechaza (gate `is_active`) y el refresh
token previo queda blacklisteado (no puede mintear nuevos). No depende del
default `CHECK_USER_IS_ACTIVE` de simplejwt.
