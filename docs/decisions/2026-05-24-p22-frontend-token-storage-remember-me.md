# ADR p22 — Frontend token storage + "Recordarme" + logout/refresh race

**Fecha:** 2026-05-24
**Estado:** ✅ Aceptado e implementado
**Branch:** `develop`
**Issues cerrados:**
- Bug: credenciales incorrectas en login provocaban full page reload
  antes de mostrar el toast de error.
- Feature: checkbox "Recordarme" del login no tenía efecto (state existía
  sin consumir).
- Hardening: race condition logout vs refresh callback en vuelo podía
  resucitar una sesión recién terminada.

## Contexto

El frontend persistía JWT (`access_token`, `refresh_token`, `user`)
exclusivamente en `localStorage`. Accesos dispersos en 3+ módulos
(`auth/authContext.jsx`, `api/client.js`, hipotéticos futuros). Tres
problemas concretos:

### 1. Reload silencioso en login fallido

`api/client.js` tenía un response interceptor global que en 401:
1. Limpiaba `localStorage`.
2. Hacía `window.location.href = "/login"`.

En el flujo de login, el endpoint `POST /api/token/` devuelve 401 con
credenciales malas. El interceptor disparaba reload antes de que
`useLoginForm` renderizara el toast. Síntoma UX: la página parecía
"recargarse sola" sin explicar el error.

### 2. "Recordarme" sin implementar

`useLoginForm.js` exponía `remember`/`setRemember` y el componente
`LoginForm.jsx` los conectaba al checkbox, pero `login(access, refresh)`
en `authContext.jsx` siempre escribía a `localStorage`. El estado del
checkbox se ignoraba.

### 3. Race logout vs refresh

`scheduleTokenRefresh` programa un `setTimeout` que dispara
`fetch('/api/token/refresh/')` 5 minutos antes del `exp`. Si el usuario
hacía logout **mientras** la fetch estaba en vuelo:

```
T1: timer dispara → fetch refresh inicia
T2: user click logout → clearTokens() + setToken(null)
T3: refresh fetch resuelve 200
T4: callback escribe localStorage + setToken(data.access)  ← zombie
```

Resultado: sesión "resucitada" que el usuario creía terminada. Bug
reproducible bajo carga y especialmente peligroso en kioscos clínicos
compartidos.

## Decisión

**Centralizar todo el acceso a auth storage en un módulo único
(`auth/tokenStorage.js`)** con invariante explícito + flag de logout +
prioridad de lectura `sessionStorage > localStorage`. **"Recordarme"
controla el store target** en login. **El response interceptor 401
bypassa redirect para requests al endpoint de login.**

### Componentes

#### `auth/tokenStorage.js` (nuevo)

API pública:
- `getItem(key)` — lee preferentemente `sessionStorage`, fallback
  `localStorage`.
- `setTokens({ access, refresh, remember })` — escribe al store target
  (`localStorage` si `remember=true`, `sessionStorage` si `false`) y
  **wipea el otro store** para preservar el invariante.
- `setAccessToken(access)` / `setUser(user)` — actualizan en el
  `activeStore()` (el que actualmente contiene `access_token`).
- `clearTokens()` — borra ambos stores + levanta `loggingOut=true`.
- `isLoggingOut()` — predicado para async callbacks.

Constantes internas:
- `KEYS = ["access_token", "refresh_token", "user"]`
- `PERSIST_FLAG = "auth_persist"` — **metadata only**, nunca leído como
  autoridad de routing.

#### Invariantes documentados en el docstring del módulo

1. **No coexistencia**: tokens válidos NUNCA en ambos stores
   simultáneamente. Caller que escriba raw storage viola el invariante.
2. **Read priority `session > local`**: sesión temporal de tab debe
   ganar sobre persistente vieja. Reversa filtra identidades.
3. **Source of truth = presencia del token**, NO el `PERSIST_FLAG`. El
   flag puede desincronizarse (browser crash, devtools edit, extensión).
4. **Logout flag**: `clearTokens()` levanta `loggingOut`. `setTokens()`
   lo limpia (fresh login cancela lockout). Cualquier `refreshPromise`
   singleton futuro debe ser nulleado dentro de `clearTokens()`.

#### `auth/authContext.jsx` (modificado)

- `login(accessToken, refreshToken, remember = true)` — recibe flag,
  delega a `setTokens()`.
- `logout()` — delega a `clearTokens()` (que automáticamente levanta
  flag + wipea ambos stores).
- Refresh callback chequea `isLoggingOut()` en 2 puntos:
  - Después de `fetch` antes de aplicar el token → descarta response.
  - En `catch` antes de loggear/auto-logout → suprime ruido.

Default `remember=true` en `login()` preserva comportamiento previo
para callers que no pasen el flag (defensa contra regresiones).

#### `api/client.js` (modificado)

Request interceptor: lee token vía `getItem("access_token")` en lugar
de `localStorage.getItem` raw.

Response interceptor 401: bypassa redirect cuando
`error.config.url` termina en `token/` o `token`. Helper local
`isLoginAttempt(config)`. Para 401 en otros endpoints, sigue
limpiando vía `clearTokens()` + `window.location.href = "/login"`
(sesión expirada legítima).

Nota: `token/refresh/` NO matcha `isLoginAttempt` (termina en
`refresh/`) → un 401 de refresh sí dispara redirect, comportamiento
correcto.

#### `hooks/useLoginForm.js` (modificado)

`handleSubmit` ahora pasa `remember` al `login()` del context.

### Comportamiento "Recordarme" por valor

| `remember` | Store target | Vida útil de la sesión |
|---|---|---|
| `true` (default visual) | `localStorage` | Persiste hasta logout, expiración de refresh, o `clearTokens()`. Sobrevive cerrar/reabrir browser. |
| `false` | `sessionStorage` | Muere al cerrar la pestaña/browser. Otras pestañas del mismo origen NO comparten la sesión (sessionStorage es per-tab por diseño). |

## Alternativas consideradas

### A. Single store + flag de expiración manual

Mantener todo en `localStorage`, agregar `auth_expiry_ts` cuando
`remember=false`, y `getItem` chequea expiración antes de devolver.

**Rechazado**: requiere lógica de expiración propia que duplica la del
JWT, sufre del problema de "cerrar el browser != tiempo definido", y
no aprovecha la semántica per-tab nativa de `sessionStorage`. Más
código y más superficie de bug.

### B. HttpOnly cookies + session backend

Mover tokens a cookies HttpOnly emitidas por el backend, eliminar
storage frontend.

**Diferido (no rechazado)**: ventajas reales (XSS no roba token), pero
costo alto:
- Refactor de `apps/users/views.py` + SimpleJWT custom view.
- CSRF protection reintroduce (Django CSRF está deshabilitado para DRF
  JWT actualmente).
- Mobile/SDK futuro consume JWT más fácil que cookie session.
- CORS más delicado (`Access-Control-Allow-Credentials`).

Con sanitización backend rigurosa (`sanitize_text` + bleach) +
ausencia de `dangerouslySetInnerHTML`/`eval` en frontend (verificado en
grep audit de este ADR), el threat model justifica diferir.

### C. AbortController para fetch de refresh

Cancelar la fetch en vuelo desde `logout()` en lugar de chequear flag
en el callback.

**Rechazado para v1**: agrega complejidad sin beneficio funcional (el
flag check suprime el efecto observable). Reservado para cuando se
agregue `refreshPromise` singleton compartido entre requests
concurrentes (interceptor on-demand). Entonces sí amerita
AbortController + null de `refreshPromise` en `clearTokens()`.

## Trade-offs aceptados

| Trade-off | Justificación |
|---|---|
| `remember=false` no comparte sesión entre pestañas | Comportamiento nativo de `sessionStorage`. Documentado. Usuario que abre nueva pestaña con sesión temp debe re-loguearse — alineado con la intención de "no recordar". |
| Default `remember=true` en `login()` (cuando no se pasa flag) | Compatibilidad con callers existentes. El único caller productivo (`useLoginForm`) pasa el flag explícito. |
| Access token viejo sigue vivo hasta `exp` después de logout | JWT stateless. Mitigado por `ACCESS_TOKEN_LIFETIME=15min` (ADR p20). Sin cambio nuevo aquí. |
| Sin sincronización cross-tab de logout (con `remember=true`) | Diferido post-beta. Mitigación futura: `window.addEventListener('storage', ...)` para detectar `access_token` removido en otro tab. Hoy queda una breve ventana donde el otro tab usa un token aún válido pero hace 401 en el siguiente request y cae en el redirect normal. |
| `PERSIST_FLAG` puede desincronizarse de la realidad | Flag es metadata. `activeStore()` deriva del token, NO del flag. Desync no afecta routing. |

## Auditoría XSS de superficie (paralela)

Grep audit ejecutado en `frontend/src`:

| Pattern | Hits | Verdict |
|---|---|---|
| `dangerouslySetInnerHTML` | 0 | ✅ |
| `eval(` | 0 | ✅ |
| `new Function` | 0 | ✅ |
| `setTimeout('...')` (string callback) | 0 | ✅ — todos pasan función |
| `innerHTML` | 5 (todos en `VanillaDateRangePicker.js`) | ✅ — templates estáticos + SVG constantes, sin interpolación de user input |

Conclusión: superficie DOM-XSS actual = 0. Riesgo futuro vigilado:
si `VanillaDateRangePicker` agrega labels personalizables vía props,
forzar `textContent` para strings de usuario.

## Backlog post-beta (no bloquea v1)

| Item | Razón de diferir |
|---|---|
| **CSP headers backend** (`script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'`) | Próximo salto grande de hardening. Requiere validar que Vite HMR + librerías inline no rompan con CSP estricta. Sin `script-src 'unsafe-inline'` jamás. |
| **ESLint rule custom** prohibiendo `localStorage`/`sessionStorage` directos fuera de `auth/tokenStorage.js` | Evita drift del invariante en 6 meses. Hoy enforced manualmente vía grep audit. |
| **Cross-tab logout sync** vía `storage` event | Edge case real pero no crítico — la víctima cae en 401 en el siguiente request y entra al flujo de redirect normal. |
| **`refreshPromise` singleton** + AbortController | Solo necesario cuando se agregue interceptor on-demand que dispare refresh desde múltiples requests concurrentes. Hoy el refresh es timer-based, no contended. |
| **Cookies HttpOnly migration** | Cambio de modelo de auth. Revisitar si el threat model cambia (ej. extensiones browser, plugins de terceros). |

## Validación manual

1. Login con credenciales malas → toast "Usuario o contraseña
   incorrectos" aparece, **sin reload**.
2. Login OK con "Recordarme" ON → cerrar browser → reabrir → sigue
   logeado. DevTools → Application: token en `localStorage`,
   `sessionStorage` vacío.
3. Login OK con "Recordarme" OFF → cerrar tab → reabrir tab → pide
   login. DevTools: token en `sessionStorage`, `localStorage` vacío.
4. Login OK → logout → DevTools: ambos stores limpios para keys
   `access_token`, `refresh_token`, `user`, `auth_persist`.
5. Race logout/refresh: cuesta reproducir manualmente sin throttle.
   Cubierto por el flag check en el callback (auditable en code review).

## Anti-patterns explícitamente bloqueados

- ❌ `localStorage.getItem("access_token")` directo en cualquier
  archivo fuera de `auth/tokenStorage.js`.
- ❌ Leer `PERSIST_FLAG` para decidir dónde escribir tokens (autoridad
  es el token mismo).
- ❌ Reusar `setItem` con keys `access_token|refresh_token|user` sin
  pasar por `setTokens`/`setAccessToken`/`setUser` (rompe invariante).
- ❌ Bypass del flag `isLoggingOut` en callbacks async que mutan auth
  state.
- ❌ `dangerouslySetInnerHTML` con valores que provengan (directa o
  transitivamente) del backend o de input de usuario — incluso si
  vienen "sanitizados". Frontend siempre trata el texto como no
  confiable.

## Referencias

- `frontend/src/auth/tokenStorage.js` — módulo nuevo.
- `frontend/src/auth/authContext.jsx` — refresh callback con guard.
- `frontend/src/api/client.js` — interceptor 401 con bypass de login.
- `frontend/src/hooks/useLoginForm.js` — passthrough de `remember`.
- ADR p20 (`2026-05-22-p20-credential-lifecycle-self-change.md`) —
  comportamiento de JWT lifecycle al cambiar password.
- ADR p14 (`2026-05-17-p15-day4-cascade-lockdown.md`) — contexto de
  hardening backend paralelo.
