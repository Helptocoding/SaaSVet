# ADR p45 — Platform-operator cross-tenant password reset

**Fecha:** 2026-06-23
**Estado:** ✅ Aceptado e implementado
**Branch:** `develop`

## Contexto

ADR p21 implementó el reset de contraseña iniciado por el ADMIN de la clínica
(`POST /api/staff/<public_id>/reset-password/`). El ADR documentó explícitamente:

> "Self-reset por admin — debe pasar por forgot-password (Phase 2) o ADMIN_SAAS
> escala. El único workaround: ADMIN_SAAS ejecuta `python manage.py
> changepassword` desde shell. **No escalable.**"

Esta brecha operativa requería acceso SSH al servidor cada vez que un
ADMIN de clínica olvidaba su contraseña. El flujo "forgot-password por email"
(Phase 2) sigue diferido — requiere SMTP infra. Este ADR cubre la brecha
inmediata sin SMTP.

**Restricción de diseño adicional identificada en 2026-06-23:**
El bypass `is_superuser → True` en `HybridPermission` (RBAC) es temporal —
existe mientras clínicas testers operan y será eliminado. Cualquier feature
apoyada en ese bypass se rompería silenciosamente al quitarlo. Por eso se
construyó sobre `IsPlatformOperator` (clase independiente en
`apps/platform/permissions.py`) que no depende del bypass.

## Decisión

Implementar endpoint dedicado en el namespace de plataforma:

```
POST /api/platform/staff/<public_id>/reset-password/
Authorization: Bearer <JWT de ADMIN_SAAS>
```

Mismo mecanismo de ADR p21 (temp password, must_change, revocación de tokens),
pero sin restricción de mismo-tenant.

### Por qué namespace `/api/platform/` y no extender `/api/staff/`

- `/api/staff/` usa `make_permission('staff.reset_password')` — permiso RBAC
  de clínica. ADMIN_SAAS no tiene `UserRole` en ninguna clínica.
- Mezclar dos contextos de autorización en un endpoint (clinic-RBAC OR
  platform-role) crea un permiso compuesto frágil.
- `apps/platform/` ya tiene el patrón establecido: `IsPlatformOperator` +
  servicio propio + tests. `provision_organization` sigue exactamente este
  patrón.
- Cuando el bypass de RBAC se elimine, este endpoint no se ve afectado.

### Endpoint

```
POST /api/platform/staff/<public_id>/reset-password/
Authorization: Bearer <JWT ADMIN_SAAS>

(body vacío — server genera temp password)
```

Response 201:
```json
{
  "detail": "Contraseña temporal generada.",
  "request_id": "...",
  "duration_ms": 42,
  "temp_password": "K9p_RxA2zVtwQ1f8hQwa3Q",
  "expires_in_seconds": 86400,
  "must_change_on_first_login": true
}
```

### Authorization contract

| Check | Enforcement |
|---|---|
| Actor es ADMIN_SAAS | `IsPlatformOperator` (view) + service gate (defense-in-depth) |
| Target no es ADMIN_SAAS | Queryset `.exclude(role='ADMIN_SAAS')` → 404 |
| Actor no resetea a sí mismo | Queryset excluye todo ADMIN_SAAS → 404 (incluye self) |

El uso de 404 para targets ADMIN_SAAS (incluyendo self) sigue la convención
"404-as-403" del sistema: nunca confirmar la existencia de un recurso que no
puede ser manipulado.

### Service: `apps/platform/services/platform_reset_password.py`

Service propio, no reutiliza `reset_password_for_staff`. Razones:
- Gates de autorización distintos (plataforma vs mismo-org).
- Audit log diferente: `PLATFORM_PASSWORD_RESET_ISSUED` con campos
  `target_organization_id` y `target_organization_name` — críticos para
  trazabilidad cross-tenant.
- Permite que el service de clínica (`reset_password_for_staff`) evolucione
  sin afectar el flujo de plataforma.

Side effects (dentro de `transaction.atomic`):
1. `secrets.token_urlsafe(16)` → temp password (~22 chars).
2. `set_password(temp)` en target.
3. `password_must_change=True`, `password_temp_issued_at=now()`.
4. Blacklist de **todos** los `OutstandingToken` del target.
5. Log `PLATFORM_PASSWORD_RESET_ISSUED` (temp_password NUNCA en logs).
6. Return temp_password UNA SOLA VEZ.

### Throttle

```python
'platform_password_reset': '20/hour'
```

Más holgado que `staff_password_reset` (5/h) porque ADMIN_SAAS puede
atender múltiples clínicas en una misma sesión de soporte. Sigue siendo
limitante para prevenir uso automatizado abusivo.

### Audit log

Evento `PLATFORM_PASSWORD_RESET_ISSUED` en logger `platform.events`:

```json
{
  "event": "PLATFORM_PASSWORD_RESET_ISSUED",
  "actor_id": 1,
  "actor_username": "admin_saas",
  "actor_role": "ADMIN_SAAS",
  "target_user_id": 42,
  "target_username": "clinic_admin",
  "target_public_id": "uuid...",
  "target_role": "ADMIN",
  "target_organization_id": 7,
  "target_organization_name": "Clinica X",
  "revoked_refresh_count": 2,
  "client_ip": "...",
  "duration_ms": 42
}
```

`target_organization_*` son campos extra vs ADR p21 — permiten saber qué
clínica fue afectada sin lookup adicional.

## Tests (21 tests, 100% pass)

`apps/platform/tests/test_platform_reset_password.py`:

**Auth (8):**
- `test_admin_saas_can_reset_vet_own_org_201`
- `test_admin_saas_can_reset_admin_other_org_201` ← core cross-tenant
- `test_admin_saas_cannot_reset_self_404`
- `test_admin_saas_cannot_reset_peer_admin_saas_404`
- `test_clinic_admin_rejected_403`
- `test_vet_rejected_403`
- `test_assistant_rejected_403`
- `test_unauthenticated_401`

**Behavior (8):**
- `test_target_password_changed_to_temp`
- `test_password_must_change_flag_set_true`
- `test_password_temp_issued_at_set`
- `test_temp_password_random_url_safe_min_22_chars`
- `test_temp_passwords_unique_per_call`
- `test_existing_tokens_blacklisted`
- `test_response_includes_expires_in_seconds`
- `test_cross_tenant_reset_works`

**Audit (2):**
- `test_audit_log_emitted_without_temp_password`
- `test_audit_log_includes_target_org_for_cross_tenant`

**Lifecycle (2):**
- `test_target_can_login_with_temp_password`
- `test_old_password_no_longer_works`

**Throttle (1):**
- `test_throttle_blocks_after_budget`

## Componentes acoplados

```
apps/platform/
├── services/platform_reset_password.py   ← service nuevo
├── views.py:PlatformStaffResetPasswordView ← view nueva
├── urls.py                                ← path nuevo
└── permissions.py:IsPlatformOperator      ← sin cambios

config/
└── settings.py:DEFAULT_THROTTLE_RATES    ← 'platform_password_reset': '20/hour'
```

No se tocan:
- `apps/users/services.py:reset_password_for_staff` — sin cambios
- `apps/users/views.py:StaffResetPasswordView` — sin cambios
- `apps/core/permissions.py` — sin cambios
- Ningún dominio de negocio (billing, medical_records, etc.)

## Trade-offs aceptados

| Trade-off | Justificación |
|---|---|
| Service duplica ~30 líneas de `reset_password_for_staff` | Separación deliberada: gates distintos, audit distinto, evolución independiente. DRY aquí crearía acoplamiento entre flujo de clínica y flujo de plataforma. |
| 404 para self-reset en lugar de 403 | Consistente con convención "404-as-403": no confirmar existencia de targets ADMIN_SAAS. |
| Sin frontend todavía | ADMIN_SAAS opera vía API directa (curl/Postman) hasta que se construya la UI de soporte en `/platform/`. |
| Throttle 20/h no tiene IP-rate-limit dedicado | Igual que `platform_org_create`. Hardening Fase 2 pendiente. |

## Lo que NO incluye p45

- **UI frontend** para ADMIN_SAAS — usará la API directa hasta que se construya
  la sección de soporte en `/platform/`.
- **Forgot-password por email** — Phase 2 POST-BETA, requiere SMTP.
- **Notificación al target** — Phase 2 (requiere email).
- **Reset de ADMIN_SAAS por otro ADMIN_SAAS** — explícitamente bloqueado.

## Refs

- ADR p20: `2026-05-22-p20-credential-lifecycle-self-change.md`
- ADR p21: `2026-05-22-p21-admin-password-reset.md`
- `apps/platform/permissions.py:IsPlatformOperator`
- Endpoint: `POST /api/platform/staff/<public_id>/reset-password/`

## Addendum 2026-11-21 — `no-store` y versión de sesión

- La respuesta lleva `Cache-Control: no-store` (`NoStoreResponseMixin`), igual que el
  restablecimiento de clínica y la reactivación (plan Equipo, D11). Antes de esta fecha no lo
  tenía. Cubre también las respuestas de error.
- Desde ADR p65 el restablecimiento incrementa la versión de sesión del usuario: también dejan de
  servir sus access tokens, no solo los refresh. Las cuentas de servicio responden 404 (D13).
