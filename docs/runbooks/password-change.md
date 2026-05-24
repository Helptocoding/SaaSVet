# Runbook: Cambio de contraseña + admin reset

**Audiencia:** ops + soporte + tech lead.
**Endpoints:**
- `POST /api/users/change-password/` — self-service (ADR p20).
- `POST /api/staff/<public_id>/reset-password/` — admin-initiated (ADR p21).

## Flujo UI (usuario final)

1. Login a la app (cualquier rol: ADMIN, VET, ASSISTANT).
2. **Configuración** → sección **Mi cuenta**.
3. Llenar form: contraseña actual, nueva, confirmar.
4. Submit → toast verde "Contraseña actualizada".
5. **Sesión actual continúa**. El usuario sigue trabajando sin re-login.

## Comportamiento de tokens post-cambio

| Token | Comportamiento |
|---|---|
| **Refresh tokens viejos** (todos los anteriores del user) | **Invalidados al instante** (entran a BlacklistedToken). Cualquier intento de `/token/refresh/` con un refresh viejo → 401. |
| **Refresh token nuevo** (recién emitido por la operación) | Válido. El frontend lo guarda automáticamente vía `useAuth().login()`. |
| **Access token viejo** (que ya tenía el cliente al hacer el cambio) | **Sigue válido hasta su exp natural (15 min)**. NO es bug — JWT stateless. Ver ADR p20 sección "Comportamiento del access token actual". |
| **Access token nuevo** (en el response 200) | Válido. El frontend lo usa para requests subsecuentes. |

**Si soporte recibe un ticket "después de cambiar password me sigue funcionando el viejo token":** es comportamiento esperado para el access token, max 15 min. El refresh token sí está invalidado.

**Persistencia del nuevo token (frontend):** el nuevo refresh+access se guardan en el store que el usuario eligió originalmente al hacer login (sessionStorage si `Recordarme=false`, localStorage si `true`). `useAuth().login()` delega en `auth/tokenStorage.js:setAccessToken/setUser` que escriben en el `activeStore()` actual sin forzar cambio de store. Ver ADR p22 para detalles del módulo + invariantes.

## Eventos de log a monitorear

Logger: `users.events`. Eventos:

| Evento | Nivel | Significado |
|---|---|---|
| `USER_PASSWORD_CHANGED` | INFO | Cambio exitoso. Campos: `actor_id`, `actor_username`, `actor_email`, `organization_id`, `client_ip`, `user_agent`, `request_id`, `duration_ms`, `blacklisted_refresh_count`. |
| `USER_PASSWORD_CHANGE_FAILED` | WARNING | current_password incorrecto. Campos: `reason='wrong_current_password'`, `actor_id`, `actor_username`, `organization_id`, `client_ip`, `user_agent`, `request_id`. |

### Queries útiles en agregador

```
event=USER_PASSWORD_CHANGE_FAILED AND actor_id=<X>
```
→ Detectar brute-force contra un usuario específico. Si > 5 hits en 1 hora,
investigar. Throttle (`10/hour`) ya lo limita pero alerta visible es útil.

```
event=USER_PASSWORD_CHANGE_FAILED AND client_ip=<X>
```
→ Detectar IP de origen sospechoso intentando contra múltiples usuarios.

```
event=USER_PASSWORD_CHANGED AND duration_ms > 1000
```
→ Latencia anómala. Causa probable: tablas blacklist crecidas (ver
"Mantenimiento" abajo).

## Mantenimiento — `flushexpiredtokens`

### Problema sin mantenimiento

Cada `/token/refresh/` con `ROTATE_REFRESH_TOKENS=True` crea:
- 1 nuevo `OutstandingToken` row.
- 1 nuevo `BlacklistedToken` row (el refresh viejo entra a blacklist).

Cada cambio de password blacklistea N filas (N = sesiones activas del user).

Con 100 usuarios activos haciendo refresh cada 5 días (default REFRESH_TOKEN_LIFETIME=7d):
- ~100 nuevos `BlacklistedToken` rows por día por refresh natural.
- Tras 1 año sin cleanup: ~36,000 rows. Queries con `JOIN` empiezan a degradarse.

### Solución

Cron diario: `python manage.py flushexpiredtokens`.

El comando elimina **OutstandingToken + BlacklistedToken cuyo
`expires_at < now()`**. Tokens NO expirados (válidos o blacklisteados pero
aún en su ventana de 7 días) se preservan — son necesarios para que la
validación de blacklist funcione.

### Setup en Railway

1. Railway dashboard → tu proyecto backend → **Settings** → **Cron Jobs**.
2. Crear nuevo cron:
   - **Schedule:** `0 3 * * *` (3:00 AM UTC diariamente — fuera de pico).
   - **Command:** `python manage.py flushexpiredtokens`.
3. Verificar en logs del cron run que la salida sea limpia (no exceptions).

### Setup alternativo (si no hay Railway scheduler)

- Script bash en un servidor con acceso a la DB de producción + crontab.
- O endpoint protegido `/internal/flush-expired-tokens/` con `IsPlatformOperator`
  + tarea manual ad-hoc. Menos ideal pero válido.

### Verificación post-setup

```bash
# Después del primer run del cron, verificar que las tablas no crecen
# indefinidamente:
python manage.py shell -c "
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
print('Outstanding:', OutstandingToken.objects.count())
print('Blacklisted:', BlacklistedToken.objects.count())
"
```

Counts esperados después de 1 mes de operación normal: < 5000 cada uno
(asumiendo ~100 usuarios activos). Counts > 50,000 sugieren cron no
corriendo o frecuencia insuficiente.

## Troubleshooting

### Issue: "Cambié mi contraseña pero todavía puedo usar mi token viejo"

Verificar qué token: refresh o access.

- **Refresh token viejo funciona** post-cambio → BUG. Algo en
  `change_password` service falló sin levantar excepción, o `BLACKLIST_AFTER_ROTATION`
  está apagado, o las migraciones de `token_blacklist` no corrieron.
  Verificar:
  ```python
  from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
  BlacklistedToken.objects.filter(token__user_id=<X>).count()
  ```
  Si 0, hay bug. Investigar logs del request específico vía `request_id`.

- **Access token viejo funciona** post-cambio (max 15 min) → COMPORTAMIENTO ESPERADO. No es bug. Ver ADR p20.

### Issue: "Cuando intento cambiar password me da 429"

Throttle scope `change_password` = `10/hour` por user. Brute-force contra
current_password se limita aquí. Si el usuario legítimamente se equivocó
varias veces, esperar 1h o ADMIN_SAAS hace reset desde Django admin
(escape hatch operativo).

### Issue: "Las tablas blacklist están enormes"

Cron `flushexpiredtokens` no está corriendo o frecuencia insuficiente.
Verificar:
1. Railway dashboard → cron logs últimas 24h.
2. Si el cron NO existe, configurarlo (ver "Setup en Railway").
3. Si existe pero falla, leer error en logs.
4. Ejecutar manualmente una vez: `python manage.py flushexpiredtokens`
   para drenar el backlog.

### Issue: "Pre-existing Django admin session se cierra al cambiar password"

NO debería pasar — el service llama `update_session_auth_hash(request, actor)`
después de `set_password`. Si pasa:
1. Verificar que `SessionAuthentication` está en `DEFAULT_AUTHENTICATION_CLASSES`.
2. Verificar que el request al endpoint llega con session cookie (el frontend
   axios cliente no envía cookies por default — esto sólo aplica a flujo
   admin Django).
3. No es escenario crítico — el usuario re-loguea a admin si pasa.

## Configuración relacionada

`config/settings.py`:

```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['change_password'] = '10/hour'
```

Cambiar `ACCESS_TOKEN_LIFETIME` afecta toda la app — no solo el cambio
de password. Discutir antes de modificar.

---

## Admin reset (ADR p21)

Cubre el caso de **usuario que olvida su contraseña**. ADMIN de la
organización emite una contraseña temporal que el usuario debe cambiar
en su próximo login.

### Flujo operativo (admin)

1. Usuario reporta olvido — vía teléfono / mensaje / soporte tickets.
2. Admin entra a `/staff` (frontend).
3. Localiza al usuario en la tabla.
4. Click botón **🔄 Resetear contraseña** (Icon.Refresh).
5. Confirmation dialog: "Se generará una contraseña temporal..."
6. Click "Resetear contraseña".
7. Modal muestra:
   - Username del target.
   - **Contraseña temporal** (mono, mostrada UNA sola vez).
   - "Válida 24 horas".
   - Botón "Copiar credenciales".
8. Admin transmite las credenciales al usuario por canal seguro (NO
   Slack/WhatsApp/SMS — email cifrado, secure share, en persona).
9. Click "Listo" cierra el modal — credenciales ya no son recuperables.

### Flujo operativo (target)

1. Recibe credenciales del admin.
2. Login con username + temp password.
3. Backend valida temp password + verifica que `password_temp_issued_at + 24h > now()`.
4. Si válido → 200 OK con `must_change_password: true`.
5. Frontend redirige automático a `/change-password`.
6. **Cualquier otra ruta queda bloqueada** por `MustChangePasswordGate`.
7. Llena form: current=temp password, new=nueva, confirm=nueva.
8. Submit → 200 OK con tokens nuevos. Backend limpia `must_change=False`,
   `password_temp_issued_at=None`. Sidebar y resto de app desbloqueados.

### Comportamientos a documentar para soporte

| Caso | Comportamiento |
|---|---|
| Target intenta usar temp después de 24h | Login retorna **403** con `code='temp_password_expired'`. Frontend muestra "Tu contraseña temporal expiró. Pídele a tu administrador un nuevo reset." |
| Target con must_change=True hace GET /api/staff/ vía curl | **403** con `code='must_change_password'`. Gate enforce server-side. |
| Admin pierde la temp password (cerró modal sin copiar) | Nuevo reset es la única opción. Genera nueva temp (la anterior queda inválida — set_password sobreescribe). |
| Admin intenta resetear su propia cuenta | **403** "Usa el cambio de contraseña personal para tu propia cuenta." Self-reset NO está soportado en p21. Pedir a otro admin o (si no hay) escalar a ADMIN_SAAS. |
| Admin intenta resetear ADMIN_SAAS | **403**. Clinic admin NO puede afectar platform operators. |
| Admin intenta resetear user de otra org | **404** (404-as-403 convention). |
| VET/ASSISTANT intenta usar el endpoint | **403** (sin permission `staff.reset_password`). |
| 6º reset en una hora desde el mismo admin | **429**. Throttle scope `staff_password_reset = 5/hour`. |

### Eventos de log

| Evento | Nivel | Cuándo |
|---|---|---|
| `ADMIN_PASSWORD_RESET_ISSUED` | INFO | Admin emite reset exitoso. Fields: `actor_id`, `target_user_id`, `target_role`, `organization_id`, `revoked_refresh_count`, `client_ip`, `user_agent`, `request_id`, `duration_ms`. **NUNCA contiene `temp_password`** (test invariant). |
| `MUST_CHANGE_PASSWORD_BLOCKED` | WARNING | Usuario con must_change=True intentó endpoint fuera de whitelist. Fields: `actor_id`, `actor_username`, `path`, `method`. |
| `TEMP_PASSWORD_EXPIRED` | WARNING | Target intentó login con temp password después de 24h. |
| `USER_PASSWORD_CHANGED` | INFO | Target completó el change-password tras reset. Limpia `must_change=False`. |

### Queries útiles en agregador

```
event=ADMIN_PASSWORD_RESET_ISSUED AND organization_id=<X>
```
→ Auditoría: todos los resets en una org. Útil para reviews post-incidente.

```
event=ADMIN_PASSWORD_RESET_ISSUED AND actor_id=<X>
```
→ Detectar admin que resetea masivamente — posible compromise interno.

```
event=MUST_CHANGE_PASSWORD_BLOCKED
```
→ Targets con temp pending que están tratando de saltarse el gate.
Normal en frontend (redirect handle), preocupante si vía curl.

```
event=TEMP_PASSWORD_EXPIRED AND user_id=<X>
```
→ Target dejó pasar 24h sin usar el temp. Probablemente necesita un
nuevo reset.

### Infrastructure gotchas

**`X-Request-ID` debe estar en `CORS_ALLOW_HEADERS`.**

El frontend envía `X-Request-ID: <uuid>` en cada llamada a:
- `POST /api/users/change-password/` (p20)
- `POST /api/staff/<id>/reset-password/` (p21)
- `POST /api/platform/organizations/` (p19)

Si `x-request-id` NO está en `CORS_ALLOW_HEADERS` en `config/settings.py`,
el browser hace OPTIONS preflight → server retorna 200 sin el header en
`Access-Control-Allow-Headers` → browser **rechaza el POST silenciosamente
sin enviarlo**. Síntoma: en Network DevTools se ve OPTIONS 200 sin POST
después, y el frontend recibe ningún response (timeout) o error genérico.

Config correcta:
```python
CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization', 'content-type',
    'dnt', 'origin', 'user-agent', 'x-csrftoken', 'x-requested-with',
    'baggage', 'sentry-trace',
    'x-request-id',   # CRÍTICO — sin esto OPTIONS pasa pero POST no se envía
]
```

Si se agregan nuevos headers custom al frontend (ej. `X-Trace-Context`,
`X-Idempotency-Key` cuando se implemente POST-BETA-005), actualizar
`CORS_ALLOW_HEADERS` simultáneamente o el endpoint queda inaccesible
desde browser.

### Troubleshooting admin reset

**"Le di la temp password al usuario pero no le funciona."**
1. Verificar que no pasaron 24h desde el reset:
   ```python
   from apps.users.models import User
   from django.utils import timezone
   u = User.objects.get(username='<x>')
   age = timezone.now() - u.password_temp_issued_at
   print(age, '— expired' if age.total_seconds() > 86400 else '— OK')
   ```
2. Si expiró → admin emite nuevo reset.
3. Si no expiró pero falla login → posible bug de transcripción. Hacer
   nuevo reset y copiar credenciales con el botón (no manualmente).

**"El usuario cambió su password pero sigue bloqueado en /change-password."**
- Verificar que el cambio fue exitoso (debe limpiar `must_change=False`):
  ```python
  u = User.objects.get(username='<x>')
  print(u.password_must_change, u.password_temp_issued_at)
  # Debe ser False, None
  ```
- Si sigue True → bug en `change_password` service. Investigar logs por
  `USER_PASSWORD_CHANGE_FAILED` o errores de DB.
- Workaround temporal: ADMIN_SAAS limpia flags manualmente:
  ```python
  u.password_must_change = False
  u.password_temp_issued_at = None
  u.save(update_fields=['password_must_change', 'password_temp_issued_at'])
  ```

**"Un admin no aparece como opción de reset target."**
- ADMIN no puede resetear a otro ADMIN sin doble confirmación (p21 NO
  implementa esto — current state es que ADMIN NO puede resetear ADMIN
  vía endpoint). Si hay 2 admins en la org y uno olvida, el otro NO
  puede ayudarlo — debe escalar a ADMIN_SAAS.
- Workaround: ADMIN_SAAS abre Django admin y resetea password. Phase 2
  (forgot password via email) cubre este caso.

### Throttle setup

```python
# config/settings.py — DEFAULT_THROTTLE_RATES
'staff_password_reset': '5/hour'
```

Aplicado por user (admin que llama). 5 resets/hora deja margen amplio
para operación normal pero limita abuso (admin compromised resetando
masivamente).

Si en operación normal un admin necesita resetear más de 5/hora con
frecuencia, ajustar el rate y agregar Sentry alert para detectar abuse.

---

## Refs

- ADR p20 (self-change): `docs/decisions/2026-05-22-p20-credential-lifecycle-self-change.md`
- ADR p21 (admin reset): `docs/decisions/2026-05-22-p21-admin-password-reset.md`
- Endpoint self-change: `apps/users/views.py:ChangeMyPasswordView`
- Endpoint admin reset: `apps/users/views.py:StaffResetPasswordView`
- Services: `apps/users/services.py:change_password`, `reset_password_for_staff`
- Gate: `apps/core/permissions.py:MustChangePasswordGate` + `HybridPermission` embedded check
- Tests self-change: `apps/users/tests/test_change_password.py` (22 tests)
- Tests admin reset: `apps/users/tests/test_reset_password.py` (25 tests)
