# ADR p34: El cierre de la consulta completa la cita (Appointment ↔ MedicalRecord)

**Fecha**: 2026-06-10
**Estado**: Implementado

## Contexto

Tras "Atender ahora", el flujo era:

```
Appointment scheduled/confirmed
  → in_progress
  → (se atiende y se crea el MedicalRecord)
  → MedicalRecord open → closed   (finalizar consulta)
```

Pero al finalizar la consulta la cita **se quedaba en `in_progress`**. El usuario tenía
que volver al módulo de Citas y pulsar manualmente "Completar consulta" para llevarla a
`done` — paso que casi nadie hacía. Resultado: citas zombie en `in_progress` y la métrica
`appointments_done` plana aunque hubiera consultas reales finalizadas (divergía de
`medical_records_closed`).

### Causa raíz (no estaba en el cierre)

El backend `close_medical_record` ya tenía un servicio que completaba la cita
(`complete_appointment_on_record_close`), pero recibía `appointment=None`. La falla estaba
en la **creación**, en el frontend:

1. `handleAttendNow` pre-creaba un `MedicalRecord` (**MR #1**) ligado a la cita
   (`appointment=<pk>`) y navegaba con `?record=<MR#1>`.
2. `medicalRecords/index.jsx` nunca pasaba ese registro al `ConsultationForm`
   (`editingRecord` quedaba `null`).
3. `ConsultationForm` montaba en modo "nuevo" y, al primer autosave, creaba un **MR #2**
   con `pet` solamente — **sin `appointment`**.
4. El usuario llenaba y cerraba **MR #2** → el servicio recibía `appointment=None` → no-op.
   La cita quedaba en `in_progress` y **MR #1** (vacío, ligado) quedaba huérfano abierto.

`appointment_id` era `null` en el registro cerrado: bug de **wiring de creación**, no de
cierre.

### Relación con ADR p8

ADR `2026-05-06-p8-post-done-manual-flow` decidió, por buenas razones (preservar la
terminalidad y la auditabilidad de `done`), que el flujo clínico posterior quedara
**explícitamente desacoplado** del cierre operativo de la cita, completándose con un CTA
manual. En la práctica ese desacople generó las citas zombie. Este ADR **enmienda esa
consecuencia**: cerrar la consulta médica **sí** completa la cita, manteniendo todo lo
demás de p8 (terminalidad de `done`, confirmación explícita en el camino manual, defaults
de auto-creación en `False`).

## Decisión

### 1. Backend — el cierre clínico completa la cita

`close_medical_record` invoca, dentro de su `transaction.atomic()` existente, el servicio
de dominio de citas:

```python
complete_appointment_on_record_close(medical_record.appointment, request.user)
```

Reglas del servicio (`apps/appointments/services.py`):

- `appointment is None` → no-op (consulta sin cita).
- `status != 'in_progress'` → no-op (cita ya `done`/`canceled`/etc.). **Idempotente**.
- `in_progress → done` vía **UPDATE condicional** (`filter(pk=..., status='in_progress').update(status='done')`),
  registrando `AppointmentStatusChange` (`from='in_progress'`, `to='done'`,
  `changed_by`=quien cerró, `reason='Auto-completada al cerrar la consulta médica'`).
- Respeta `ALLOWED_TRANSITIONS` (import diferido desde `views`, single source of truth).
- **No toca `Invoice` ni pagos.**

**Por qué UPDATE condicional y no `select_for_update`**: tomar un lock explícito de la fila
`Appointment` dentro del `atomic()` que ya posee el lock del `MedicalRecord` introduciría
un orden Appointment↔MR que puede chocar (ABBA) con `assign_patient` (que toca Appointment
y luego MR). `Appointment` **no** está en la cadena canónica de locks
(`CashSession → MR → Invoice → Presentation → InvoiceItem → MRP`). El UPDATE condicional es
atómico a nivel SQL, idempotente por el filtro de estado, y no adquiere lock explícito.

**Acoplamiento cross-domain**: unidireccional `medical_records → appointments.services`.
No se muta `Appointment` directamente desde `medical_records` (regla de boundaries).

### 2. Frontend — un único MedicalRecord ligado, sin duplicado

`handleAttendNow` **deja de pre-crear** el `MedicalRecord`. Solo transiciona la cita a
`in_progress` y navega pasando el **PK de la cita por router state**:

```js
navigate(`/medical-records?pet=${pet_public_id}&appointment=${public_id}`,
         { state: { appointmentId: current.id } });
```

(El PK viaja por state, no por URL: el body FK usa PK entero — ADR p18; la URL solo lleva
`public_id`.)

`medicalRecords/index.jsx` lee `location.state.appointmentId` y lo pasa al
`ConsultationForm` como prop `appointmentId`. El stepper crea el **único** `MedicalRecord`
(lazy, al primer autosave) incluyendo `appointment` en el payload de creación. Al
finalizar, el cierre completa la cita.

`appointmentId` se limpia (`null`) en "+ Nueva Consulta" manual, al editar desde el
Timeline y al cerrar el stepper (consulta manual = MR sin cita ligada).

## Separación de conceptos (preservada)

```
Appointment.done      = la atención médica terminó   (operativo / agenda)
MedicalRecord.closed  = el expediente está cerrado    (clínico, inmutable)
Invoice.paid          = se cobró                       (financiero)
```

`done` ≠ pagado. El cobro vive en facturación y es independiente del cierre clínico.
`done` sigue siendo terminal.

## Alternativas consideradas

### A. Editar el MR pre-creado (MR #1) en el stepper

Descartada. Abrir el stepper en modo "edición" sobre MR #1 lo enruta por
`ConsultationForm.checkNotStale`, que compara el `updated_at` de montaje contra el actual;
el propio autosave del usuario lo cambia → al finalizar, el guard detecta "modificado por
otro usuario" y aborta el cierre. Además dejaría el título "Editar consulta" para una
consulta nueva. La creación lazy en modo "nuevo" evita el guard (`initialUpdatedAt=null`).

### B. Incluir `appointment` en el create pero seguir pre-creando MR #1

Descartada. Seguiría existiendo el MR #2 duplicado (o el MR #1 huérfano). Una sola fuente
de creación (el stepper) elimina el duplicado.

### C. Completar la cita con `select_for_update` sobre Appointment

Descartada por el riesgo ABBA descrito arriba.

## Consecuencias

Positivas:
- Cerrar la consulta completa la cita: desaparecen las citas zombie en `in_progress`.
- `appointments_done` vuelve a converger con la actividad real (sin tocar analytics).
- Un solo `MedicalRecord` por atención, siempre ligado a su cita.
- Se preserva la terminalidad y auditabilidad de `done` (ADR p8) y la separación de
  dominios.

Costos / notas:
- El botón manual "Completar consulta" se conserva como **fallback** para citas sin
  consulta médica (atención trivial o cierre administrativo de un `in_progress`).
- **Idempotencia HTTP del endpoint de cierre**: cerrar dos veces devuelve 403 (no 200)
  porque `can_close_medical_record` rechaza un MR ya `closed` antes de la rama idempotente
  de la view. Es un asunto **pre-existente e independiente** de este ADR; la transición de
  la cita no se duplica de todas formas (el servicio es idempotente).
- Pueden existir `MedicalRecord` huérfanos vacíos creados por el flujo viejo (pre-p34). No
  se hace backfill en este cambio.

## Notas de implementación

- `backend/apps/appointments/services.py` — `complete_appointment_on_record_close(appointment, actor)`.
- `backend/apps/medical_records/views.py` — llamada dentro del `atomic()` de `close_medical_record`.
- `backend/apps/medical_records/tests/test_close.py` — `CloseSyncsAppointmentTests` (4 casos:
  cita `in_progress` → `done`; cierre sin cita; doble cierre sin duplicar transición; cita
  ya `done` → no-op).
- `frontend/src/pages/appointments.jsx` — `handleAttendNow` deja de pre-crear el MR; pasa
  `appointmentId` por router state (incluye los caminos `in_progress` "Continuar" sin MR).
- `frontend/src/pages/medicalRecords/index.jsx` — lee `location.state.appointmentId`;
  prop `appointmentId` al stepper; limpieza en open manual / edit / close.
- `frontend/src/pages/medicalRecords/ConsultationForm.jsx` — prop `appointmentId`; incluido
  en el payload de `createMedicalRecord` (omitido en consultas manuales).

## Relación con otros ADRs

- `2026-05-06-p8-post-done-manual-flow.md`: **enmendado** — el cierre de la consulta ahora
  completa la cita; el camino manual queda como fallback. Se preserva `done` terminal y los
  defaults de auto-creación en `False`.
- `2026-04-27-maquina-de-estados-citas.md`: se respeta `ALLOWED_TRANSITIONS`; `done` sigue
  terminal. Se agrega un **trigger** (cierre clínico) a la transición ya válida
  `in_progress → done`.
- `2026-04-25-cierre-consulta-explicito.md` y `2026-05-05-p4-create-close-separation.md`: el
  cierre sigue siendo explícito; ahora además sincroniza la agenda.
- `2026-05-16-p12-concurrency-lock-order-hardening.md`: `Appointment` no entra en la cadena
  canónica de locks; se usa UPDATE condicional para no romper el orden.
- `2026-05-20-p18-ids-en-superficies-externas.md`: el PK de la cita viaja por router state
  (body FK = PK), no por URL (`public_id`).
