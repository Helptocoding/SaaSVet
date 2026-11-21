# ADR p21 — Admin-initiated password reset + must_change gate

**Fecha:** 2026-05-22
**Estado:** ✅ Aceptado e implementado
**Branch:** `develop`
**Issues cerrados:** Gap operativo post-ADR p20.

## Contexto

Post-ADR p20 (self-service change password) quedaba un gap: ¿qué pasa
si el usuario **olvida** su password? p20 cubre el flujo asumiendo que
el user conoce su current_password.

Estado pre-p21:
- **ADMIN_SAAS** podía mitigar manualmente vía `python manage.py
  changepassword`. No escalable.
- **ADMIN de clínica** no tenía forma de ayudar a sus usuarios.
- **VET / ASSISTANT** olvido → contactar a ADMIN_SAAS por out-of-band
  → escalado operativo no sostenible.
- Sin `password_must_change` flag → imposible forzar cambio de
  contraseñas temporales o de onboarding.
- Sin gate global → si se introducía temp password, el user podía
  ignorarla vía API directa con curl.

User propuso flujo completo: forgot-password vía email + admin reset
con temp password. Forgot-password vía email **diferido** (Phase 2)
porque requiere SMTP infra. Este ADR cubre el **admin reset** (Phase 1).

## Decisión

Implementar **admin reset como flujo Phase 1 del credential recovery**.
Forgot-password via email (Phase 2) y TOTP 2FA (Phase 3) quedan
diferidos pero arquitectónicamente posibilitados por las primitivas
introducidas aquí.

### Tres flujos credential separados

| Flujo | Estado | Implementado en |
|---|---|---|
| **Self-change** (user autenticado cambia su password) | ✅ ADR p20 |
| **Admin reset** (ADMIN de la org resetea password de staff) | ✅ ADR p21 |
| **Forgot-password** (recovery por email, sin auth) | ❌ Diferido — Phase 2 POST-BETA |
| **TOTP 2FA** | ❌ Diferido — Phase 3 POST-BETA |

### Endpoint

```
POST /api/staff/<public_id>/reset-password/
Authorization: Bearer <JWT de ADMIN>
X-Request-ID: <opcional, uuid v4>

(body vacío — el server genera la temp password)
```

Response 201:
```json
{
  "detail": "Contraseña temporal generada.",
  "request_id": "...",
  "duration_ms": 87,
  "temp_password": "K9p_RxA2zVtwQ1f8hQwa3Q",
  "expires_in_seconds": 86400,
  "must_change_on_first_login": true
}
```

**El `temp_password` se retorna UNA SOLA VEZ.** Si el admin lo pierde,
debe hacer otro reset. Nunca se persiste en logs ni en DB en plain text.

### Modelo — fields nuevos en User

```python
password_must_change = models.BooleanField(default=False)
password_temp_issued_at = models.DateTimeField(null=True, blank=True)
```

**Justificación arquitectónica:** `password_must_change` no es solo
útil para admin reset. Sirve futuro para:
- Onboarding forzado (forced change post-provisioning).
- Security policy incidents (forzar cambio masivo tras leak).
- Compromised credentials (rotación reactive).
- First-login enforcement.

Es un primitivo del lifecycle de credenciales que justifica el espacio
en DB (1 byte por user).

### Service contract

```python
@transaction.atomic
def reset_password_for_staff(*, admin, target_user, request_id,
                              client_ip, user_agent):
    # Authorization gates (defence in depth — view también verifica):
    # - admin.role == 'ADMIN' (no VET/ASSISTANT)
    # - target_user != admin (self-reset usa change-password)
    # - target_user.role != 'ADMIN_SAAS'
    # - target_user.organization == admin.organization

    # Side effects atómicos:
    # 1. Generar temp password = secrets.token_urlsafe(16) → ~22 chars
    # 2. set_password(temp)
    # 3. password_must_change=True, password_temp_issued_at=now()
    # 4. Blacklist TODOS los OutstandingToken del target
    # 5. Log ADMIN_PASSWORD_RESET_ISSUED (sin temp_password en log)
    # 6. Return temp_password UNA VEZ
```

**Diferencia crítica vs `change_password` service:** ese preserva la
sesión del caller (snapshot + mint new + blacklist old). El admin
reset **revoca todas las sesiones del target** — el target no está
en el loop del request, no hay sesión que preservar.

### Lifecycle de la temp password

```
1. Admin pide reset → temp password generada, password_must_change=True,
   password_temp_issued_at=now()

2. (Tiempo pasa)

3. Target intenta login con temp password:
   a) Si dentro de 24h → 200 OK + response anota must_change_password=True
   b) Si > 24h → 403 con code='temp_password_expired'.
      Target debe pedir nuevo reset al admin.

4. Target post-login (must_change_password=True):
   a) MustChangePasswordGate bloquea TODO excepto whitelist:
      /api/users/change-password/, /api/me/, /api/token/refresh/, /api/token/
   b) Cualquier otro endpoint → 403 con code='must_change_password'
   c) Frontend redirige a /change-password forzosamente

5. Target llama POST /api/users/change-password/ con:
   current_password = temp, new_password = elegida
   - change_password service: limpia password_must_change=False,
     password_temp_issued_at=None
   - Blacklistea refresh viejos, mintea nuevos
   - Response con nuevos {access, refresh}

6. Target ya tiene credenciales normales — gate ya no bloquea.
```

### MustChangePasswordGate — el corazón del enforcement

Permission global en `apps/core/permissions.py:MustChangePasswordGate`.
Aplicada en `DEFAULT_PERMISSION_CLASSES` (después de `IsAuthenticated`).

**Whitelist hardcoded:**
- `/api/users/change-password/` — la puerta de salida.
- `/api/me/` — frontend necesita para render.
- `/api/token/refresh/` — keep alive durante el cambio.
- `/api/token/` — login.

**Cualquier otro endpoint → 403** con payload:
```json
{
  "code": "must_change_password",
  "detail": "Cambia tu contraseña antes de continuar.",
  "endpoint": "change-password"
}
```

Crítico: la enforcement es SERVER-SIDE. El frontend redirige por UX,
pero un cliente curl/Postman que ignore el redirect choca contra el
gate y se queda atrapado.

### Anti-patterns explícitos

❌ **NO permitir** que el admin escriba la temp password manualmente.
   Humanos eligen passwords débiles (nombres, fechas). Server genera
   con `secrets.token_urlsafe(16)`.

❌ **NO loggear el temp password** en plain text. El log estructurado
   incluye `actor_id`, `target_user_id`, `revoked_refresh_count`, pero
   NUNCA `temp_password`. Test explícito (`test_audit_log_emitted_without_temp_password`) verifica el invariante escaneando todos los log records.

❌ **NO permitir admin resetear ADMIN_SAAS** ni admins cross-tenant.
   Cross-tenant retorna 404 (404-as-403 convention — nunca confirmar
   existencia de usuario en otra org).

❌ **NO permitir self-reset por admin**. Si admin olvida SU password,
   debe pasar por forgot-password (Phase 2) o ADMIN_SAAS lo ayuda
   manualmente (workaround pre-Phase 2).

❌ **NO confiar en el frontend** para enforce must_change. El gate es
   server-side autoritativo.

### Ventanas de tiempo

| Ventana | Valor | Razón |
|---|---|---|
| Temp password válida (primer uso) | **24 horas** | Balance UX/security. El user puede no loguear inmediatamente — en clínica veterinaria con interrupciones, 10 min era irreal. |
| Cambio post-login | (sin límite hard) | Mientras `must_change=True`, gate bloquea todo excepto la exit door. User puede tomar el tiempo que necesite — gate sigue activo. |
| Refresh token TTL | 7 días | Sin cambios vs p20. |
| Access token TTL | 15 min | Sin cambios vs p20. |

**NO hay deadline de 30-60 min post-login.** Hubiera requerido tracking
`password_temp_first_used_at` adicional + middleware para forzar
logout. La gate ya enforce el cambio antes de hacer cualquier otra
operación útil — agregar deadline crea fricción sin beneficio claro.

### Throttling

```python
'staff_password_reset': '5/hour'  # por actor (admin)
```

Mitigación de **insider abuse**: ADMIN comprometido no puede resetear
masivamente a todos los users de su org. 5/hora deja amplio margen
para operación normal (es raro que un admin necesite resetear más de
5 passwords en una hora) pero bloquea automatización abusiva.

### Tests (24 tests, 100% pass)

`apps/users/tests/test_reset_password.py`:

**Auth/permissions (7):**
- `test_admin_can_reset_staff_of_own_org_201`
- `test_admin_cannot_reset_self_403`
- `test_admin_cannot_reset_admin_saas`
- `test_admin_cannot_reset_user_from_other_org_404`
- `test_vet_cannot_reset_403`
- `test_assistant_cannot_reset_403`
- `test_unauthenticated_401`

**Service behavior (7):**
- `test_target_password_changed_to_temp`
- `test_password_must_change_flag_set_true`
- `test_password_temp_issued_at_set`
- `test_temp_password_is_random_url_safe_min_22_chars`
- `test_temp_passwords_are_unique_per_call`
- `test_target_existing_refresh_tokens_blacklisted`
- `test_response_includes_expires_in_seconds`
- `test_audit_log_emitted_without_temp_password` (escaneo full log records)

**Lifecycle (4):**
- `test_target_can_login_with_temp_password`
- `test_old_password_no_longer_works`
- `test_temp_password_expired_24h_login_rejected_403`
- `test_change_password_with_temp_clears_must_change_flag`
- `test_new_password_works_for_subsequent_login`

**Gate (4):**
- `test_gate_blocks_normal_endpoint_403`
- `test_gate_allows_change_password_endpoint`
- `test_gate_allows_me_endpoint`
- `test_gate_does_not_affect_users_without_flag`

**Throttle (1):**
- `test_throttle_blocks_after_5_per_hour`

## Trade-offs aceptados

| Trade-off | Justificación |
|---|---|
| Admin compromise → resetea cualquier user de SU org | Sin alternativa práctica en SaaS multi-org. Mitigaciones: audit estructurado obligatorio, throttle 5/h, log notification a target en Phase 2. |
| Sin email notification al target post-reset | Requiere SMTP infra. Phase 2 cubre. Mientras tanto, admin notifica out-of-band. |
| Temp password en HTTP response (no email/SMS) | Sin SMTP infra. Admin recibe en su sesión autenticada, transmite out-of-band. Phase 2 puede enviar link recovery por email del target. |
| 24h validez | Más permisivo de lo recomendable (NIST sugiere 1h). Concesión a UX en clínica veterinaria. Mitigado por: revocación de sesiones al reset + must_change gate forzando cambio inmediato post-login. |
| No password history | Enterprise feature, no v1. |
| **CORS gotcha**: `X-Request-ID` debe estar en `CORS_ALLOW_HEADERS` | Sin esto, browser hace OPTIONS preflight 200 pero rechaza el POST silenciosamente. Ver runbook `password-change.md` § "Infrastructure gotchas". |

## Lo que NO incluye p21

- **Forgot-password con recovery via email** — Phase 2 POST-BETA, requiere SMTP.
- **TOTP 2FA** — Phase 3 POST-BETA.
- **Notification al target post-reset** — Phase 2 (requiere email).
- **Self-reset por admin** — debe pasar por forgot-password (Phase 2) o ADMIN_SAAS escala.
- **MFA en reset** — Phase 3.
- **Password history rejection** — enterprise feature.
- **Deadline 30-60 min post-login** — gate ya enforce cambio antes de operación útil. Deadline adicional crea fricción sin beneficio.
- **Reset por VET / ASSISTANT** — solo ADMIN (permission `staff.reset_password` único en wildcard).

## Componentes acoplados

```
apps/users/
├── services.py:reset_password_for_staff      ← service nuevo
├── services.py:is_temp_password_expired       ← helper compartido login
├── services.py:change_password                ← actualizado: limpia flags
├── views.py:StaffResetPasswordView            ← view nueva
├── views.py:MeView                            ← retorna must_change_password
└── models.py:User                             ← 2 fields nuevos

apps/core/
├── permissions.py:MustChangePasswordGate      ← permission global
└── permissions_codes.py:'staff.reset_password' ← código nuevo

config/
├── settings.py:DEFAULT_PERMISSION_CLASSES     ← agrega MustChangePasswordGate
├── settings.py:DEFAULT_THROTTLE_RATES         ← 'staff_password_reset': '5/hour'
└── urls.py:ThrottledTokenObtainPairView        ← chequeo expiry + tag must_change
```

Frontend:
```
src/api/staff.js:resetStaffPassword             ← function nueva
src/pages/staff.jsx                              ← botón + modal display
src/pages/changePassword.jsx                     ← page dedicada nueva
src/App.jsx:MustChangePasswordGate (UX mirror)   ← redirect frontend
src/hooks/useLoginForm.js                        ← detecta flag, redirect post-login
```

## Addendum (2026-06-24) — Onboarding forzado / first-login enforcement implementado

El uso anticipado en "Justificación arquitectónica" (*"Onboarding forzado
(forced change post-provisioning)"* + *"First-login enforcement"*) ya está
implementado. El mismo primitivo `password_must_change` + `MustChangePasswordGate`
ahora aplica a la **creación manual de usuarios por SaaslyVet**:

- **Provisioning** (`provision_organization`, ADR p19): el admin inicial se crea
  con `password_must_change=True` (param `require_password_change`, default True).
- **Alta de staff** (`CreateEmployeeSerializer.create`): VET/ASSISTANT/ADMIN
  creados por el ADMIN de la clínica también entran con `password_must_change=True`.

**Diferencias vs el admin reset de este ADR:**
- **Sin `password_temp_issued_at`** → la contraseña inicial **no caduca** a las
  24h. El handoff operador→clínica puede tardar más; el flag solo (sin caducidad)
  fuerza el cambio sin riesgo de lockout. La ventana de 24h sigue siendo exclusiva
  del flujo de *reset*.
- **Contraseña elegida por el humano** (operador/admin), no `secrets.token_urlsafe`.
  El anti-pattern "no permitir password manual" aplica al *reset* (server genera),
  no al alta (operador la define y el usuario la cambia al entrar).

**Locus de implementación (invariante):** el flag se setea SOLO en las rutas de
creación manual (`provision_organization`, `CreateEmployeeSerializer.create`),
**nunca** en `User.create_user`, el default del modelo, ni un signal `post_save`
— eso gatearía los usuarios de `setUp` de la suite, los seeds (demo) y
`createsuperuser`. Los seeds pasan `require_password_change=False`.

Ref: `docs/fix-provision-must-change-password-2026-06-24.md`.

## Refs

- CLAUDE.md ADR-18
- `docs/runbooks/password-change.md` (sección admin reset)
- ADR p20 (self-change, dependencia): `2026-05-22-p20-credential-lifecycle-self-change.md`


## Addendum 2026-11-19 — Reactivación y `no-store` (plan Equipo, D10/D11)

- **La reactivación forma parte del ciclo de credenciales.** `POST /api/staff/<public_id>/reactivate/`
  (`staff.reactivate`, solo ADMIN) reactiva la misma cuenta con una contraseña temporal de las mismas
  características que el reset de esta ADR (24 h, cambio obligatorio, nunca en logs) y revoca todas las
  sesiones. Comparte con el reset las funciones `_issue_temporary_password` y `_revoke_all_sessions`.
- **Toda respuesta con contraseña temporal lleva `Cache-Control: no-store`**: el restablecimiento de esta
  ADR (antes no lo tenía) y la reactivación.
- Desde ADR p65, restablecer y reactivar también invalidan los access tokens emitidos antes (versión de
  sesión), no solo los refresh tokens.
