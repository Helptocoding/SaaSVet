# Plan de implementación — Item 2

**Fecha**: 2026-08-08
**Estado**: PLAN — no se escribió código ni se modificó ningún archivo de
producción. Este documento ordena el trabajo que
[`item-2-decision.md`](item-2-decision.md) aprobó; **no reabre decisiones**.
**Decisión de origen**: [`item-2-decision.md`](item-2-decision.md) — invariantes
INV-A (precondición atómica como garantía de dominio), INV-B (el teléfono
localiza, no autoriza) y FLUJO-C (caso de verificación de identidad).

> Toda referencia `§n` remite a `item-2-decision.md`.

---

## 1. Principios que ordenan las fases

1. **La garantía antes que su consumidor.** El dominio debe poder rechazar una
   escritura obsoleta *antes* de que el agente empiece a restaurar propuestas.
   Invertir el orden significa tener durante días exactamente el bug que la
   revisión de seguridad rechazó.
2. **Cada fase deja el sistema mejor que antes, y es mergeable sola.** Ninguna
   depende de que la siguiente exista para ser correcta.
3. **Ninguna fase introduce una regresión en `/appointments` ni en la bandeja.**
   La precondición es opt-in hasta la Fase 5 (§1.2); `require_new_owner` solo lo
   envía el agente.
4. **Los tests de la fase se escriben en la fase**, no al final. Los P0 de §8
   son gate de merge de su fase, no del Item completo.

---

## 2. Mapa de fases

| Fase | Qué entrega | Depende de | Cierra |
|---|---|---|---|
| **F0** | Precondición atómica en `appointments` (INV-A, Fase 1 del rollout) | — | P0-4, P0-7, P0-9, P1-14, P2-4 |
| **F1** | `require_new_owner` en `create-with-patient` (INV-B, lado dominio) | — (paralelizable con F0) | P0-6ᵃ, P0-9ᵇ, P2-5 |
| **F2** | El agente consume ambas: snapshot con precondición + revalidación de identidad en el commit | F0, F1 | P0-2, P0-3, P0-5, P0-6ᵇ, P0-8, P1-11, P1-12, P1-13, P2-6, P2-7 |
| **F3** | Servicio de release: restaurar/descartar con lock e idempotencia | F2 (para que el «sí» posterior sea seguro) | P0-1, P1-1…P1-10, P2-1, P2-2, P2-3 |
| **F4** | Caso de verificación de identidad: backend + Inbox (FLUJO-C) | F2 (el `409 owner_exists` ya existe) | P0-10…P0-14, P1-15…P1-18, P2-8, P2-9, P2-10 |
| **F5** | Frontend envía la precondición; después, obligatoria para todos | F0 | §9.9 (decisión de producto pendiente) |

**F0 y F1 son paralelizables** (tocan el mismo módulo pero distintas funciones:
`AppointmentDetailView`/`update_status` vs. `create_with_patient`). **F3 no debe
mergear antes que F2**: restaurar propuestas sin la precondición activa es
precisamente el escenario que el dictamen de seguridad bloqueó.

**F5 no es parte de Item 2**; se lista porque INV-A no queda completo sin ella y
alguien tiene que agendarla (§9.9).

```
F0 ─┐
    ├─► F2 ─► F3
F1 ─┘     └─► F4
F0 ─────────► F5   (fuera de Item 2)
```

---

## 3. F0 — Precondición atómica en `appointments`

**Objetivo**: ningún actor sobrescribe una cita cuyo estado cambió desde que se
confirmó la intención (§3.2). Sin tocar al agente.

### Archivos previstos

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/appointments/serializers.py` | Campo **declarado** `expected_state` (write-only, `required=False`) en `AppointmentSerializer`; validación de forma (`status`, `date`, `start_time`) y comparación contra `self.instance`. **Declararlo es el punto**: si no se declara, DRF lo ignora en silencio y la precondición no existe (§3.2, exigencia 1) |
| `backend/apps/appointments/views.py` | `AppointmentDetailView.update()` envuelto en `transaction.atomic()` con la fila tomada por `select_for_update()`; `update_status()` **mueve la lectura de la cita dentro** de su `atomic()` existente (hoy lee en `views.py:145-148`, fuera) y la lockea; ambos devuelven `409 appointment_changed` con `current` |
| `backend/apps/appointments/tests/test_preconditions.py` *(nuevo)* | P0-4, P0-7, P0-9ᵃ, P1-14, P2-4 |
| `docs/decisions/2026-08-XX-p57-*.md` *(nuevo)* | ADR de dominio: precondición atómica + autorización de escritura sobre `Owner` existente (§1.1) |
| `docs/modules/appointments.md` | Contrato de `expected_state` y del 409 |

### Verificación de la fase

- P0-4 falla si alguien borra la declaración del campo (el fail-open invisible).
- P1-14 (`TransactionTestCase`, PostgreSQL) prueba que hay **lock**, no solo
  comparación: dos escrituras concurrentes con el mismo `expected_state` → una
  escribe, la otra recibe 409.
- P2-4 protege al frontend actual: sin `expected_state`, comportamiento idéntico.

### Riesgos de la fase

- Envolver `update()` en una transacción con lock cambia el perfil de
  concurrencia de un endpoint que usa el frontend. Mitigación: el lock es de una
  fila y de duración de request; medir si la agenda tiene picos de escritura
  concurrente sobre la misma cita (no debería).
- `update_status` mueve una lectura dentro del `atomic()`: revisar que los
  toggles (`auto_create_medical_record`) y el `AppointmentStatusChange` sigan en
  el mismo orden. Hay tests existentes de estado que deben quedar en verde.

---

## 4. F1 — `require_new_owner` en `create-with-patient`

**Objetivo**: que el dominio pueda **negarse** a reutilizar un `Owner` por
teléfono, en vez de que el llamador lo descubra después (§4.3, control C5).

### Archivos previstos

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/appointments/views.py` | `create_with_patient`: acepta `require_new_owner` (bool, default `False`); dentro del `atomic()` existente, si el `Owner` ya existía por teléfono → `409 owner_exists` sin crear nada. Sin el flag, comportamiento actual intacto |
| `backend/apps/appointments/tests/test_preconditions.py` | P0-6ᵃ, P0-9ᵇ, P2-5 |
| `docs/modules/appointments.md` | Contrato del flag y del 409 |
| `docs/modules/patients.md` | Nota: la reutilización de `Owner` por teléfono deja de ser universal |

### Notas de diseño (ya decididas, no reabrir)

- El flag es **opt-in**: recepción y el registro rápido siguen reutilizando el
  expediente, y es correcto — el staff está verificado por su sesión (§4.4).
- La comprobación vive dentro de la transacción a propósito: una pre-consulta
  desde el llamador sería TOCTOU, y por `?search` sería además `icontains`
  acotado a 20 filas (`patients/views.py:193-205`).

---

## 5. F2 — El agente consume las garantías

**Objetivo**: que toda escritura del agente viaje con su precondición y que el
alta revalide identidad (§3.2, §4.3).

### Archivos previstos

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/agent/tools.py` | **Staging**: `create_appointment` añade `pet_public_id` al staged; `cancel_appointment` añade `expected_status`/`expected_date`/`expected_start_time`; `reschedule_appointment` añade `from_date`/`from_start_time`/`expected_status` (§6.1). **Commits**: `commit_cancel_*` y `commit_reschedule_*` envían `expected_state` y mapean `409` → `appointment_changed` / `already_done` en vez de caer en `tool_failure`; `commit_register_*` aplica C1–C5 (re-lectura fresca de `ContactIdentity`, `owner_id`, `is_ambiguous`, teléfono recomputado, `require_new_owner`) |
| `backend/apps/agent/planner.py` | Ramas nuevas en `_commit_pending` para `appointment_changed`, `already_done`, `identity_changed`, `owner_exists`, cada una con su plantilla; **y el requisito de orden de §5.5.4**: la rama de `owner_exists` suspende la intención antes de escalar, porque `clear_pending` ya corrió (`planner.py:627-629`) |
| `backend/apps/agent/confirmations.py` | Posible helper para suspender/re-stagear la intención sin duplicar lógica en `planner.py` |
| `backend/apps/agent/tests/test_write_tools.py` | P0-2, P0-3, P0-5, P0-6ᵇ, P0-8, P1-12, P1-13, P2-6 |
| `backend/apps/agent/tests/test_planner.py` | P1-11, P2-7 |
| `docs/modules/agent.md` | Los `client_error` nuevos y su comportamiento |

### Orden interno sugerido

1. Snapshot (staging) — sin efecto observable todavía, seguro de mergear.
2. Commits de `cancel`/`reschedule` con precondición + mapeo del 409.
3. Commit de `register` con C1–C5.
4. Ramas del planner + plantillas (§9.8 puede cambiar los textos; el
   comportamiento no).

### Riesgo específico

El `already_done` de cancelación depende de que el dominio distinga «ya está
como querías» de «conflicto». Si F0 no lo expone con claridad, el agente
volverá a escalar por nada — que es el bug que P0-3 cubre. Validar el contrato
del 409 con F0 antes de escribir la rama.

---

## 6. F3 — Servicio de release

**Objetivo**: retomar la propuesta suspendida sin perder nada, sin pisar al
worker y sin ejecutar nada por un «sí» viejo (§2, §5, §7).

### Archivos previstos

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/agent/policy.py` | `escalate_to_human` escribe `suspension_id`, `suspended_at` y `handoff_reason` en `flow['suspended']` (§6.1). `nudge_abandoned_flows` reclama el derecho a enviar bajo lock, en vez de leer-y-enviar (§0-G) |
| `backend/apps/agent/services.py` *(o `views.py`)* | Servicio de release: tx#1 con `select_for_update` + respeto del lease `processing_until` (409 `turn_in_progress`), chequeo de dominio **fuera** del lock vía `ToolExecutor` de la org de la conversación, tx#2 que aplica el veredicto solo si `suspension_id` no cambió. Validación de forma del `suspended` (legacy vs. corrupto, §7) |
| `backend/apps/agent/views.py` | `release_conversation` delega en el servicio; conserva la resolución del `HumanHandoff` y el compromiso de identidad actuales (`views.py:392-420`) |
| `backend/apps/agent/tests/test_inbox_api.py` | P0-1, P1-2, P1-5, P1-8, P1-9, P2-1, P2-2, P2-3 |
| `backend/apps/agent/tests/test_policy.py` | P1-10 (matriz por tool), P1-4 |
| `backend/apps/agent/tests/test_release_concurrency.py` *(nuevo, `TransactionTestCase`)* | P1-6, P1-7 — **PostgreSQL, no SQLite** |
| `docs/modules/agent.md` | Ciclo de vida de `flow['suspended']` y del release |
| `docs/system-module-operations.md` | Sección de la bandeja: liberar tiene ahora precondiciones y efectos |

### Nota de secuencia

F3 es la fase que *usa* todo lo anterior. Si por planificación tuviera que
adelantarse a F2, **no debe mergearse**: restaurar propuestas sin precondición
en el commit reintroduce el P0 de la revisión de seguridad.

---

## 7. F4 — Caso de verificación de identidad (FLUJO-C)

**Objetivo**: que el `409 owner_exists` tenga salida dentro del sistema, con
verificación humana, RBAC y auditoría (§5.5).

### Backend

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/agent/models.py` | Modelo nuevo `ContactIdentityVerification` (append-only): `organization`, `contact`, `owner_candidate`, `conversation`, `decision`, `evidence_kind`, `evidence_note`, `actor`, `created_at` (§5.5.3) |
| `backend/apps/agent/migrations/0015_contact_identity_verification.py` *(nuevo)* | Migración aditiva; sin backfill (no hay datos previos que interpretar) |
| `backend/apps/agent/identity.py` | `link_staff_verified(contact, owner, actor)` — cuarta y única vía nueva que eleva a `staff_verified`, fija `linked_via='staff'` y limpia `auto_rematch_blocked` |
| `backend/apps/agent/views.py` | Dos endpoints: registrar verificación (aprobada/rechazada) y autorizar el vínculo. Ambos con `agentinbox.identity_verify` y `_get_conversation` (tenant). El de vínculo lockea `ContactIdentity` y exige verificación positiva vigente en el caso abierto |
| `backend/apps/agent/urls.py` | Dos rutas nuevas bajo `/api/inbox/conversations/<pk>/` |
| `backend/apps/agent/serializers.py` | Serializer del registro de verificación; la conversación expone el caso abierto y **qué pidió el cliente** (staged proyectado, sin volcar el `flow` crudo) |
| `backend/apps/core/permissions_codes.py` | Código nuevo `agentinbox.identity_verify` + concesión a ADMIN (§5.5.2) |
| `backend/apps/agent/tests/test_inbox_api.py` | P0-11, P0-12, P0-13, P0-14, P1-18, P2-8, P2-9 |
| `backend/apps/agent/tests/test_write_tools.py` | P0-10 (el caso se crea y la intención se preserva) |
| `backend/apps/agent/tests/test_identity.py` | P1-15, P2-10 |
| `backend/apps/agent/tests/test_release_concurrency.py` | P1-16 (dos autorizaciones simultáneas) |

### Frontend (Inbox)

| Archivo | Cambio previsto |
|---|---|
| `frontend/src/api/inbox.js` | Dos funciones nuevas (verificar, autorizar), siguiendo el patrón existente de `resetContactIdentity`/`unlinkFamily` |
| `frontend/src/pages/inbox/index.jsx` | Banner del caso con lo que pidió el cliente; modal de verificación (tipo de evidencia + nota) y acción de autorizar/rechazar. `useConfirm` para autorizar (transición con peso operativo), `handleFormError`, `apiError`, doble-submit bloqueado — convenciones de `docs/modules/frontend.md` |
| `frontend/src/pages/inbox/inbox.module.css` | Estilos del banner/modal, solo tokens |
| `frontend/src/pages/inbox/*.test.jsx` *(nuevo)* | El CTA no se muestra sin `can('agentinbox.identity_verify')`; el flujo verificar→autorizar deshabilita botones mientras corre; el rechazo no ofrece autorizar |
| `docs/modules/frontend.md` | El código de error nuevo y las acciones de la bandeja |
| `docs/modules/agent.md` | El caso, sus estados y quién puede actuar |

### Reglas de esta fase (no negociables, vienen de §5.5)

- Verificar y autorizar son **dos acciones distintas**; no unificarlas en un
  endpoint con booleano.
- La evidencia es **externa al teléfono**: el enum de `evidence_kind` no ofrece
  ninguna opción basada en el número.
- El sistema **registra** el juicio humano; no lo valida ni lo puntúa.
- **Nada de automatización de la verificación** (§5.5.6). P2-10 es el gate.
- El permiso es **nuevo**, no se reutiliza `agentinbox.config`; `seed_permissions`
  lo propaga en el deploy.

---

## 8. F5 — Cierre de INV-A (fuera de Item 2)

Depende de la decisión de producto §9.9 (calendario). Se lista para que no se
pierda: sin ella, INV-A solo protege al agente.

| Paso | Archivos previstos |
|---|---|
| El frontend envía la precondición | `frontend/src/api/appointments.js`, `frontend/src/pages/appointments.jsx`, `frontend/src/components/dashboard/AppointmentQuickModal.jsx` |
| La UI maneja el 409 (recargar + volver a preguntar, nunca reintentar) | los mismos + `frontend/src/utils/apiError.js` si hace falta afinar el mensaje |
| La precondición pasa a **obligatoria** (`400 precondition_required`) | `backend/apps/appointments/serializers.py`, `views.py` + ventana de deprecación (Sunset RFC 8594) y entrada en el ADR p57 |

---

## 9. Trabajo transversal

### Migraciones

| Fase | Migración | Naturaleza |
|---|---|---|
| F4 | `agent/0015_contact_identity_verification` | Aditiva, tabla nueva, sin backfill. No bloquea escrituras existentes |

Ninguna otra fase toca el esquema: `expected_state` y `require_new_owner` viajan
en el request y no se persisten (§6.2).

### Permisos

`agentinbox.identity_verify` se añade en F4 a `PERMISSION_CODES` y al rol ADMIN.
`seed_permissions` corre en cada deploy, así que no hace falta paso manual —
pero sí verificar en staging que un ADMIN existente lo recibe sin recrear roles.

### Documentación (regla de `docs/CLAUDE.md`: cambian contratos)

| Documento | Fase |
|---|---|
| ADR p57 (nuevo) | F0 (se crea), F1/F4 (se amplía) |
| `docs/modules/appointments.md` | F0, F1 |
| `docs/modules/agent.md` | F2, F3, F4 |
| `docs/modules/frontend.md` | F4, F5 |
| `docs/modules/patients.md` | F1 |
| `docs/system-module-operations.md` §3 y bandeja | F0, F3, F4 |
| `docs/system-reference.md` §1 (diagnóstico), §3 (invariantes) | F0, F4 |
| `docs/whatsapp-agent-identity-context-fixes-plan.md` (Item 1) | F4 — corregir «las tres únicas funciones» → cuatro (§4.4, nota de coordinación) |

### Entorno de pruebas

La revisión de seguridad no pudo ejecutar la suite en este worktree
(`ModuleNotFoundError: No module named 'django'`). **Antes de F0**: dejar el
entorno operativo y correr la línea base en verde. Las pruebas de concurrencia
(P1-6, P1-7, P1-14, P1-16) exigen PostgreSQL; no valen en SQLite.

---

## 10. Definition of done por fase

Una fase está terminada cuando, además de su código:

1. Sus pruebas P0 pasan y son **bloqueantes** en CI.
2. La suite completa de `agent/` y `appointments/` queda en verde.
3. La documentación de la tabla de §9 está actualizada **en el mismo PR** — un
   contrato que cambia sin su documento es deuda desde el minuto uno.
4. Ningún test existente se borró ni se debilitó para pasar (regla del proyecto).
5. Las regresiones marcadas *iron rule* (P2-3, P2-4, P2-5, P2-6) siguen verdes.

---

## 11. Lo que este plan NO incluye

- **Cualquier automatización de la verificación de identidad** (§5.5.6): no es
  una fase futura de este plan; sería un diseño nuevo con su propio ADR.
- Tope duro de antigüedad de la suspensión (§9.4).
- Mensaje proactivo al descartar por «ya resuelto» (§9.5).
- Tool de alta de mascota para cliente conocido (§9.10).
- Visibilidad de la propuesta congelada en hand-offs que no son de identidad
  (§9.11).
- Claves de idempotencia para los PATCH de cancelar/reprogramar: la precondición
  cubre el caso (§6.3).
