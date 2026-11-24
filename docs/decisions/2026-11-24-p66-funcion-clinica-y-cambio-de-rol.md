# ADR p66 — Función clínica separada del rol, cambio de rol y auditoría de accesos

**Fecha:** 2026-11-24
**Estado:** ACEPTADO (decisiones del PO del 2026-11-24, Fase 2 de
[`auditoria-modulo-equipo-2026-11-23.md`](../auditoria-modulo-equipo-2026-11-23.md))
**Enmienda a:** ADR p63 (lista explícita de ADMIN: nuevo código `staff.change_role`), ADR p64
(la cédula la exige quien atiende, no solo `VET`), plan Equipo II.3.1 (INV-J: segundo escritor
que reduce ADMIN activos) y los contratos del agente que elegían veterinario por `role='VET'`.

## Contexto

El rol hacía dos trabajos: definir **permisos** y decidir **quién atiende pacientes**. Los
consumidores lo resolvían distinto:

| Sitio | Criterio previo |
|---|---|
| Agenda (`pages/appointments.jsx`) | `VET` o `ADMIN` |
| Agente: candidatos a huecos (`agent/tools.py::_candidate_vets`) | solo `VET` |
| Agente: alta de cita (`appointments/creation.py`, `require_schedule`) | solo `VET` |
| Agente: reagendar (`appointments/mutations.py`) | solo `VET` |
| Agente: ejecución autorizada (`agent/operation_execution.py`) | solo `VET` |
| Cédula obligatoria en Equipo (`users/professional.py`) | solo `VET` |

El caso típico de clínica pequeña —el dueño veterinario con rol `ADMIN`— aparecía en la agenda,
podía firmar, pero el agente nunca le ofrecía huecos (`no_vet` si era el único) y Equipo no le
pedía cédula. Además, el rol era inmutable: ascender a una asistente era imposible (el correo
único impedía recrearla).

## Decisiones

1. **Función clínica = predicado único** `apps.users.professional.is_clinician(user)` /
   `clinician_q()`: atiende quien es `VET`, o `ADMIN` con `attends_patients=True`. `ASSISTANT`
   nunca atiende. Todos los sitios de la tabla usan ese predicado. Campo nuevo
   `User.attends_patients` (booleano, `db_default=False`); para `VET` y `ASSISTANT` lo fija el
   servicio (True/False) y solo es editable en `ADMIN`.
2. **Backfill (PO):** `VET` → True; `ADMIN` con cédula → True; el resto, False. Un `ADMIN` sin
   cédula deja de listarse como veterinario en la agenda hasta que se marque; sus citas
   existentes no se tocan.
3. **Cédula obligatoria para quien atiende** (`VET` o `ADMIN` que atiende), en el alta, la
   edición y el cambio de rol. La firma clínica (`require_signer_license`) no cambia.
4. **Cambio de rol**: `POST /api/staff/<uuid>/role/`, permiso nuevo **`staff.change_role`**
   (sensible, solo ADMIN). Servicio `change_staff_role`: no a sí mismo, mismo alcance 404-as-403
   que el resto, cuentas semilla de la demo protegidas, bloqueo ordenado por `pk` con todos los
   ADMIN activos cuando el objetivo deja de serlo (**INV-J**: `409 last_active_admin`), cédula
   si el nuevo rol atiende, `User.role` + `UserRole` de sistema sustituidos en la misma
   transacción. Repetir el mismo rol es idempotente.
5. **El cambio de rol no cierra sesiones (PO).** Los permisos se leen de la base en cada
   petición (`UserRole`), no viajan en el token: el cambio aplica en la siguiente petición. No
   se incrementa la versión de sesión (ADR p65 queda para credenciales y estado de la cuenta).
6. **Impacto antes de desactivar**: `GET /api/staff/<uuid>/impact/` (quien gestiona personal)
   devuelve citas próximas, consultas abiertas y caja abierta, cada conteo desde su dominio
   (`appointments`, `medical_records`, `cash`). **Caja abierta bloquea la desactivación (PO)**:
   `409 open_cash_session`, se cierra antes desde Caja (cierre administrativo existente). Citas
   y consultas solo se advierten; la reasignación masiva queda para la Fase 3 (hecha en
   [ADR p67](2026-11-24-p67-ausencias-reasignacion-y-ficha.md)).
7. **Auditoría persistente de accesos**: modelo de solo inserción `StaffAccessEvent`
   (organización, integrante, actor, tipo, cambios, fecha, request_id). Lo escriben en la misma
   transacción las operaciones de Equipo: alta, edición, cambio de rol, desactivación,
   reactivación y restablecimiento. Guarda nombres de campo y roles, **nunca** contraseñas,
   correos ni otros valores personales. Lectura: `GET /api/staff/<uuid>/history/`.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Rol nuevo «VET_ADMIN» | Duplica permisos y rompe ADR p63 (listas explícitas por rol de sistema) |
| Multirrol vía `UserRole` | `User.role` está en todo el código; la función clínica no es un permiso |
| Derivar «atiende» de tener cédula | Mezcla un dato profesional con una decisión operativa; un ADMIN puede tener cédula y no atender |
| Cerrar sesiones al cambiar el rol | Sin beneficio de seguridad (permisos por petición) y corta una consulta en curso |
| Solo `deactivated_at/by` en `User` | No cubre rol, reactivación ni restablecimiento |

## Consecuencias

- El agente puede ofrecer huecos de un `ADMIN` que atiende. Ninguna clínica real tiene el
  agente activo (activación PENDING_ACTIVATION_REQUIREMENTS); los adapters B8 siguen apagados.
- El camino de staff para crear citas sigue aceptando cualquier usuario activo de la clínica
  como veterinario (no se endurece aquí: la agenda solo ofrece clínicos). Pendiente aparte.
- INV-J tiene dos escritores que reducen ADMIN activos: `deactivate_staff` y
  `change_staff_role`; el gate de escritores los enumera.
- Migraciones aditivas: `users.0014` (campo + backfill) y `users.0015` (tabla de eventos).
