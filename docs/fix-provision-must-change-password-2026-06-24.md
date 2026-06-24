# Corrección: admin provisionado debe forzar cambio de contraseña

**Fecha**: 2026-06-24
**Tipo**: Análisis de impacto previo a implementación. **No se modificó código.**
**Origen**: discrepancia detectada en `docs/investigacion-legal-acceptance-gate-2026-06-24.md` §2/§11.
**Objetivo**: que todo admin creado por SaaslyVet vía `provision_organization` use una contraseña temporal y esté obligado a cambiarla en el primer acceso.

---

## 1. La discrepancia (causa raíz)

`provision_organization` crea el admin inicial **sin** `password_must_change=True`:

```python
# apps/platform/services/provision_organization.py:105-116
admin = User.objects.create_user(
    username=d['admin_username'],
    email=d['admin_email'],
    password=d['admin_password'],
    first_name=d['admin_first_name'],
    last_name=d['admin_last_name'],
    role='ADMIN',
    organization=org,
    is_staff=False,
    is_superuser=False,
    is_active=True,
)   # ← NO setea password_must_change → default False (apps/users/models.py:40)
```

Consecuencia: el admin de la clínica entra **directo al dashboard**, sin pasar por `MustChangePasswordGate`. Solo los flujos de *reset* (`reset_password_for_staff:286`, `platform_reset_password`) setean `password_must_change=True`.

**Inconsistencia adicional (UI vs backend)**: la pantalla del operador **ya llama a este campo "Contraseña temporal"** y promete que el admin debe cambiarla:
- `frontend/src/pages/platform/createOrganization.jsx:218` label "Contraseña temporal".
- `:331` SuccessCard: "⚠ Anota o copia la contraseña ahora… Envíasela al administrador por canal seguro."

→ El frontend **ya comunica semántica de contraseña temporal**, pero el backend no la fuerza. El fix alinea backend ↔ UI existente.

---

## 2. Corrección propuesta (Opción A — mínima)

**Setear `password_must_change=True` en el admin provisionado, SIN `password_temp_issued_at`** (dejarlo `None`).

```
# Conceptual — NO implementar aún:
User.objects.create_user(..., is_active=True)
admin.password_must_change = True
# password_temp_issued_at se deja en None (ver §3 — decisión de expiración)
admin.save(update_fields=['password_must_change'])
```

- Se conserva la contraseña que el operador escribe (sigue siendo de un solo uso: el admin la cambia al entrar).
- **No** requiere migración (`password_must_change` ya existe, migración `0008`).
- **No** requiere cambio de frontend (la UI ya dice "temporal").

### Decisión clave: ¿setear `password_temp_issued_at` (expiración 24h)?
| | Sin `temp_issued_at` (recomendado) | Con `temp_issued_at=now()` |
|---|---|---|
| Comportamiento | Fuerza cambio, **sin caducidad** | Fuerza cambio + caduca a 24h |
| `is_temp_password_expired` | Devuelve `False` (`services.py:346-347`: `temp_issued_at is None` → no expira) | Tras 24h, login → 403 `temp_password_expired` |
| Riesgo de lockout | Ninguno | **Alto**: el provisioning y la entrega de credenciales pueden tardar >24h → admin bloqueado, requiere reset de plataforma |
| Por qué difiere del reset | El reset lo genera el admin y lo entrega de inmediato (ventana corta esperada) | El provisioning tiene handoff largo/impredecible |

**Recomendación**: NO setear `temp_issued_at` en provisioning. El flag `password_must_change` solo ya cumple "obligado a cambiar en primer acceso" sin riesgo de lockout. La expiración 24h es apropiada para *resets*, no para provisioning.

---

## 3. Impacto en tests existentes

**Resultado: cero tests rotos** con la Opción A. Verificado uno por uno:

| Test | Qué hace | ¿Rompe? | Por qué |
|---|---|---|---|
| `test_provision_service.py::test_creates_org_admin_userrole_atomically` (:68) | Asserts role/org/is_staff/is_active/public_ids | **No** | No asserta `password_must_change` en ningún sentido |
| `test_provision_service.py` (signals, rollback, race, logging) | Side effects + atomicidad | **No** | No tocan el campo |
| `test_view_integration.py::test_provisioned_admin_can_login_via_token_endpoint` (:57) | Login → assert 200 + access/refresh | **No** | `must_change` NO bloquea la emisión de token; `is_temp_password_expired` es `False` (sin `temp_issued_at`) → login 200 ✓ |
| `test_view_integration.py::test_provisioned_admin_has_full_tenant_permissions` (:75) | `build_permissions_list(admin)` directo | **No** | No pasa por el gate (cálculo directo) |
| `test_view_integration.py::test_provisioned_admin_can_call_me_endpoint` (:92) | Login → GET `/api/me/` → 200 | **No** | `MeView` usa `permission_classes=[IsAuthenticated]` (override del default) y `/me/` está en `_MUST_CHANGE_WHITELIST` → accesible con `must_change=True` |
| `test_view_integration.py::test_response_no_password_field` (:135) | Password no en respuesta | **No** | Opción A no devuelve la contraseña |
| Throttle tests | 201/429 | **No** | Sin relación |

**Por qué no rompe nada**: ningún test existente loguea como el admin provisionado y luego golpea un endpoint **gateado** (p. ej. `POST /api/pets/`) esperando 200/201. Solo tocan `/api/token/` y `/api/me/`, ambos permitidos bajo must-change.

### Tests NUEVOS necesarios
- `provision_organization` deja `admin.password_must_change == True` y `password_temp_issued_at is None`.
- Admin provisionado: login 200 + `must_change_password=True` en la respuesta del token (`urls.py:115`).
- Admin provisionado **bloqueado** (403) en un endpoint gateado hasta cambiar contraseña; `change_password` libera el gate.
- Demo seed: el admin demo queda `password_must_change == False` (ver §4).

---

## 4. Impacto en flujos

| Flujo | Efecto | Acción |
|---|---|---|
| **Login del admin** (`ThrottledTokenObtainPairView`, `urls.py:53`) | 200; setea `must_change_password=True` en la respuesta (`urls.py:115`) | OK, sin cambios |
| **Gate backend** (`HybridPermission` embebido, `permissions.py:329`) | Bloquea endpoints no whitelisted hasta cambiar | Comportamiento deseado |
| **Gate frontend** (`MustChangePasswordGate`, `App.jsx:41`) | Redirige a `/change-password` | Ya existe, sin cambios |
| **`change_password`** (`services.py:144-151`) | Limpia `password_must_change` y `password_temp_issued_at` | Ya lo hace, sin cambios |
| **Frontend createOrganization** | Ya dice "Contraseña temporal" + muestra una vez | Sin cambios (alineado) |
| **🔴 Demo seed** (`seed_demo_clinic._ensure_org`, `:155`) | El admin demo quedaría gateado → rompe el demo de login compartido | **Requiere opt-out** |

### Mitigación demo seed (única acción extra requerida)
`seed_demo_clinic` provisiona el admin demo vía `provision_organization` (`:155-167`) y luego imprime la contraseña compartida (`_report:627`). Forzar must-change rompería el demo (el primer tester que la cambie deja fuera a los demás; o todos chocan con la pantalla de cambio). Los usuarios VET/recepción demo se crean con `create_user` directo (`:182`), **no** se afectan.

**Propuesta**: parámetro `require_password_change: bool = True` en `provision_organization` (seguro por defecto), y `seed_demo_clinic` lo pasa `False`. Alternativa más simple: el seed limpia el flag tras provisionar. Preferible el parámetro (explícito, sin segunda escritura).

### Otros callers
- `PlatformOrgCreateView` (API real): es el caso objetivo → recibe must-change=True. ✓
- No hay otros callers de `provision_organization` (verificado: solo views.py, seed_demo_clinic, y la mención en docstring de `users/services.py`).

---

## 5. Alternativas evaluadas

| Alternativa | Descripción | Veredicto |
|---|---|---|
| **A. Flag must-change, conservar password del operador, sin expiración** | El operador escribe la temporal, admin la cambia al entrar | ✅ **Recomendada** — mínima, cero tests rotos, alinea con UI, sin lockout |
| **B. Generar temp server-side + devolverla una vez** | El backend genera la temporal (como el reset), la devuelve en el 201, must-change=True | ❌ Mayor alcance: cambia contrato API (quita/ignora `admin_password`), **rompe `test_response_no_password_field`**, revierte la decisión "password nunca se devuelve", exige cambio de frontend. Considerar como hardening P1 (handoff ciego: el operador nunca conoce la credencial) |
| **C. A + `temp_issued_at=now()` (expiración 24h)** | Como A pero con caducidad | ❌ Riesgo de lockout por handoff >24h (ver §2). La caducidad es para resets, no provisioning |
| **D. No cambiar provisioning; forzar el gate por otra vía** | — | ❌ No existe otra vía; el gate depende de `password_must_change` |

---

## 6. Clasificación de riesgo + plan de pruebas

| Cambio | Riesgo | Nota |
|---|---|---|
| Setear `password_must_change=True` en `provision_organization` | **BAJO-MEDIO** | Toca el servicio de provisioning (privilegiado) pero es un campo aditivo; cero migración; cero tests rotos |
| Parámetro `require_password_change` + opt-out en demo seed | **BAJO** | Aditivo, default seguro |
| (Si se elige B) generar temp + devolver + frontend | **MEDIO-ALTO** | Contrato API + UI; descartado por ahora |

**Plan de pruebas antes de merge**: los 4 tests nuevos de §3 + correr la suite de `apps/platform` y `apps/users` (gate + reset) + `seed_demo_clinic` en una DB de prueba para confirmar que el admin demo no queda gateado.

---

## 7. Recomendación y qué confirmar

**Implementar Opción A**: `password_must_change=True` en `provision_organization` (sin `temp_issued_at`) + parámetro `require_password_change=True` por defecto, con `seed_demo_clinic` pasando `False`. Sin migración, sin cambio de frontend.

---

## 8. Decisiones confirmadas (2026-06-24) y plan final

| # | Decisión | Elección |
|---|---|---|
| 1 | Handoff de credencial | **Opción A** — conservar la contraseña que escribe el operador (admin la cambia al primer login) |
| 2 | Expiración 24h en provisioning | **Sin expiración** (`password_temp_issued_at = None`) |
| 3 | Extender must-change a staff | **Sí** — staff creado por el ADMIN (`StaffCreateView`) también fuerza cambio |

### Impacto de la decisión 3 (staff) — verificado, cero tests rotos
- `test_day6_invariants.py::CreateStaffOrgImmutableTests` (`:177-206`): crea staff por el endpoint pero **solo inspecciona `organization`** del user creado; no se loguea como él → **no rompe**.
- `test_security.py` (`:329,402,475`): asertan que VET/ASSISTANT **no pueden** crear staff (403, no hay creación) → el flag nunca corre → **no rompe**.
- El resto de la suite crea sus usuarios de prueba con `User.objects.create_user(...)` directo en `setUp` (no por el endpoint) → no afectados.

### 🔑 Locus de implementación (no negociable)
Setear `password_must_change=True` **solo** en las rutas de creación manual:
- `apps/platform/services/provision_organization.py` (admin provisionado) — con parámetro `require_password_change: bool = True`.
- `apps/users/serializers.py::CreateEmployeeSerializer.create` (staff por ADMIN).

**NO** en `User.objects.create_user`, ni en el default del modelo, ni en un signal `post_save` — eso gatearía los usuarios de `setUp` de toda la suite, los usuarios demo (vet/recepción), y `createsuperuser` → ruptura masiva.

### Opt-outs necesarios
- `seed_demo_clinic._ensure_org` → llama `provision_organization(..., require_password_change=False)` (admin demo no gateado; vet/recepción ya usan `create_user` directo → sin cambio).

### Cambios de frontend (menores, no bloqueantes)
- `pages/staff.jsx` (form de alta, `:376`): copy informando que el empleado deberá cambiar la contraseña en su primer acceso (espejo del card de reset `:302`). El alta de admin (`createOrganization.jsx`) ya dice "Contraseña temporal" → sin cambio.

### Plan de pruebas antes de merge
- Nuevos: provisioning deja `must_change=True`/`temp_issued_at=None`; staff por endpoint deja `must_change=True`; admin/staff gateados (403) hasta cambiar; `change_password` libera; admin demo `must_change=False`.
- Correr suites `apps/platform`, `apps/users`, `apps/core` (day6 + security) + `seed_demo_clinic` en DB de prueba.

---

## 9. Estado: IMPLEMENTADO ✅ (2026-06-24)

Plan de §8 implementado y validado.

**Producción:**
- `apps/platform/services/provision_organization.py` — param `require_password_change=True`; admin → `password_must_change=True` (sin `password_temp_issued_at`).
- `apps/users/serializers.py::CreateEmployeeSerializer.create` — staff → `password_must_change=True`.
- `apps/core/management/commands/seed_demo_clinic.py` — provisiona con `require_password_change=False`.
- `frontend/src/pages/staff.jsx` — hint "contraseña temporal".

**Tests:** `test_provision_service.py` (+2), `test_view_integration.py` (+1 gated), `apps/users/tests/test_staff_create_must_change.py` (nuevo).

**Resultado:** módulos del cambio + throttle-fixed = **101 tests OK**; suite completa (`manage.py test apps`) = **428 corridos, 0 failures**. Los 2 `errors` son stubs espurios de discovery por la colisión `platform`/stdlib (ver `docs/deuda/fase4-prioridad-baja.md` C7) — no son fallas.

**Hallazgo lateral (pre-existente, corregido):** la suite completa destapó un bug de aislamiento — los `setUp` de los login-tests hacían `cache.clear()` (alias `default`) sin limpiar `throttle_login`, acumulando el throttle 5/15min → 429. Corregido en `test_reset_password.py`, `test_change_password.py`, `test_view_integration.py`, `test_platform_reset_password.py`.

**Docs alineadas:** `system-module-operations.md` §1, `runbooks/platform-org-provisioning.md`, `modules/platform.md`.
