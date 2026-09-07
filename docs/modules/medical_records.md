# Módulo: Historial clínico

**Última actualización**: 2026-09-07

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

El modulo de historial clinico registra el acto medico realizado sobre una mascota y conserva la trazabilidad minima necesaria para auditoria clinica.

Una consulta medica puede incluir:
- mascota
- veterinario responsable
- cita asociada (opcional)
- tipo de consulta (`consultation_type`)
- diagnostico
- tratamiento
- notas
- peso (campo heredado; historial detallado en `VitalSigns`)
- signos vitales (modelo `VitalSigns`, append-only)
- productos usados
- servicios usados
- receta medica asociada (opcional)

## Flujo general

### 1. Creacion de consulta

La consulta se crea en estado `open` con `consultation_type = general` por defecto.

**Frontera clínica/comercial**: crear o editar la consulta no crea Invoice.
Servicios y productos facturables producen evidencia de cargos clínicos. Al
cerrar, el sistema congela esa evidencia y materializa o adopta un
`Checkout primary_consultation`. La Invoice nace únicamente al postear el
Checkout.

Reglas:
- pertenece a una sola organizacion
- el veterinario asignado debe pertenecer a la misma organizacion (validado en serializer)
- la mascota debe pertenecer a la misma organizacion (validado en serializer)
- si existe cita asociada, debe pertenecer a la misma organizacion (validado en serializer)

### 2. Modificaciones mientras esta abierta

Mientras `status = open`, la consulta puede:
- editarse
- agregar o quitar productos usados
- agregar o quitar servicios usados
- crear receta medica asociada

Reglas de acceso:
- `ADMIN`: permitido
- `VET`: solo si es el veterinario asignado a la consulta
- siempre se valida tenant explicito

### Cierre y analytics anchor (`closed_at`)

Al cerrar via `close_medical_record` view (POST `/api/medical-records/<uuid>/close/`):
- `status` pasa a `closed`
- `closed_at` se setea con `timezone.now()` en el mismo `transaction.atomic()`
- `closed_at_source = 'service'` (provenance — ver ADR `2026-05-09-p9`)
- `closed_by` registra al user
- **garantiza el Checkout (ADR p62)**: llama
  `get_or_create_primary_checkout_for_medical_record()` dentro del mismo
  `atomic()`. Finalizar siempre deja la consulta visible en Cobros, incluso si
  suma $0; no crea Invoice.
- **completa la cita vinculada (ADR p34)**: llama
  `apps.appointments.services.complete_appointment_on_record_close(medical_record.appointment, request.user)`
  dentro del mismo `atomic()`. Transiciona la cita `in_progress → done` (cierre clínico
  = fin de la atención operativa). Es idempotente y no-op si no hay cita asociada o si
  la cita no está en `in_progress`. Usa un UPDATE condicional (gateado por
  `status='in_progress'`), **sin** `select_for_update` sobre el Appointment, para no
  introducir un orden de locks Appointment↔MR que choque con `assign_patient` (ABBA).
  **NO toca Invoice ni pagos**: `done` significa "atención terminada", no "pagado".

`closed_at` es `editable=False`. Defenses:
1. **Model `save()` guard**: si `status='closed' AND closed_at is None` →
   raise `ValidationError`. Bloquea bypasses tipo `mr.status='closed'; mr.save()`.
2. **CHECK constraint DB** `medicalrecord_closed_status_requires_closed_at`:
   bloquea `queryset.update()`, `bulk_update`, raw SQL.

`closed_at_source` choices:
- `service` — escrito por close view (default para nuevos)
- `fallback` — backfilled desde `updated_at` (migration 0014)
- `legacy` — preexistente al provenance tracking (mark via migration 0015)

> **Deuda técnica:** `close_medical_record` actualmente escribe `closed_at` desde la **view**, no desde un service. Viola ADR p9 (single authoritative writer en `services.py`). El `_source='service'` es técnicamente falso. Migración planificada — ver [deuda A3](../deuda/fase2-prioridad-alta.md#a3---closed_at-writer-fuera-de-service-medical_recordsviewspy432).

### Late-arrival observability (ADR p17 — Día 5)

Después de setear `closed_at`, la view invoca el helper module-level
`_warn_if_late_closed_at(organization, closed_at)` (en el mismo `transaction.atomic()`).

El helper emite `ANCHOR_LATE_ARRIVAL` (WARNING) en el logger `analytics.events`
si `closed_at` cae en un bucket ya frozen para el metric_class `clinical`
(threshold T+2 días). Side-effect free si el bucket está abierto.

Estructura del log (contrato operacional — ver `docs/modules/analytics.md`):

```python
extra = {
    'event': 'ANCHOR_LATE_ARRIVAL',
    'anchor_field': 'closed_at',
    'anchor_value_iso': '<iso8601>',
    'bucket_date_local_iso': '<YYYY-MM-DD>',
    'frozen_threshold_days': 2,
    'age_days': <int>,
    'organization_id': <int>,
    'writer': 'close_medical_record',
    'metric_class': 'clinical',
}
```

Día 5 = warn-only. Hard reject (`LateAnchorError`) queda para Día 7+.

El helper vive temporalmente en `views.py` por consistencia con la deuda A3
(no existe `services.py::close_medical_record_service` todavía). Migrará junto
con el writer cuando esa deuda se cierre.

## Recetas medicas

La receta medica es un documento clinico independiente de la factura.

Reglas de negocio:
- la receta contiene los medicamentos que el veterinario indica clinicamente
- la receta por si sola NO descuenta stock ni crea items financieros
- una consulta `closed` no admite receta nueva ni modificacion de receta existente

Flujo en cobros (ver [Billing](billing.md)):

- el Checkout de consulta muestra snapshots de servicios/cargos clínicos;
- los recetados no se agregan automáticamente: se exponen como
  `prescription_suggestions` con remanente clínico, stock y máximo
  seleccionable resueltos por backend;
- recepción acepta o rechaza la selección; aceptar agrega un `CheckoutItem`
  retail ligado al `PrescriptionItem`;
- al postear se crean juntos `InvoiceItem`, allocations, salida de stock y
  `PrescriptionFulfillmentEvent`. Rechazar no altera la receta.

Regla de frontend:
- la creacion de receta se inicia desde `Historial clinico`
- la consulta y la mascota llegan preseleccionadas y bloqueadas en el modal
- si la creacion falla, el modal permanece abierto y conserva los datos capturados
- al guardar correctamente, el `prescription_id` se actualiza tanto en el detalle abierto como en la lista local de consultas
- el historial muestra el detalle de la receta asociada directamente en la consulta

Validaciones backend:
- `dose` es obligatorio y no puede estar vacio
- `quantity` debe ser mayor a 0
- la receta debe tener al menos un medicamento
- solo se permite una receta por consulta (OneToOneField)
- los productos agregados a una receta deben tener `requires_prescription = true`
- **tenant validation (ADR p14 — Día 3):** `PrescriptionItemSerializer.validate_product` y `PrescriptionItemWriteSerializer.validate_product` rechazan productos de otra organización con `400 'Acceso inválido.'`. El endpoint `/items/` además exige `requires_prescription=True` **después** del tenant check (no revelar atributos de productos cross-org). Antes de Día 3 no había tenant check → leak en el PDF de receta. Helper local `_validate_same_org` emite `TENANT_VALIDATION_REJECTED` (WARNING). Migración a mixin centralizado planificada — ver [deuda A1](../deuda/fase2-prioridad-alta.md#a1).

La ruta `/prescriptions` se conserva como visor secundario para consulta, reimpresion y mantenimiento historico, pero el flujo principal de prescripcion es desde historial clinico.

## Documentos PDF (ADR p36)

| Endpoint | Permiso | Documento |
|---|---|---|
| `GET /api/medical-records/<uuid>/pdf/` | `medicalrecord.retrieve` | Resumen de consulta |
| `GET /api/prescriptions/<uuid>/pdf/` | `prescription.retrieve` | Receta médica |

Ambos se generan con la capa compartida `apps/core/pdf/` (tema verde bosque, membrete
por página, "Página N de M"). Reglas:

- **Contenido**: el view del dominio arma los flowables (QUÉ); `core/pdf` solo aporta
  presentación (CÓMO). No agregar queries dentro del tema — el N+1 guard del PDF de
  consulta lo detecta.
- **Receta pagina correctamente** (rewrite platypus, ADR p36). Antes usaba canvas crudo
  sin salto de página: recetas largas perdían contenido. Test de regresión: 40 ítems →
  2+ páginas con el último medicamento presente.
- **Fechas** en timezone de la organización (`utc_to_local`), no UTC.
- **Nombre de descarga**: `consulta_<id>_<mascota>_<YYYY-MM-DD>.pdf` /
  `receta_<id>_<mascota>_<YYYY-MM-DD>.pdf` vía `pdf_filename()` (fecha local de
  creación). Requiere `CORS_EXPOSE_HEADERS=['content-disposition']` en settings para
  que el frontend pueda leer el nombre (test de contrato en core).
- La receta incluye bloque de firma del veterinario (nombre + especialidad). La cédula
  profesional llega en Fase 2 (`User.license_number`, pendiente).

Distincion funcional importante:
- receta medica: medicamentos prescritos para administracion posterior o entrega al cliente
- productos consumidos en consulta: stock interno usado durante la atencion clinica

## Seleccion de mascota en el frontend

La pantalla de Historial clínico (`medicalRecords/index.jsx`, orquestador) lista las
mascotas en el sidebar izquierdo (`PetSidebar`) sobre el array `pets` ya cargado (sin
llamada extra mientras `getPets()` no ha resuelto). Al elegir una mascota se abre su
Timeline; "+ Nueva Consulta" monta `ConsultationForm` (single-screen). Ver
`docs/modules/frontend.md` §estructura de `pages/medicalRecords/`.

## Productos usados en consulta

Los productos agregados desde consulta son parte del contexto clinico y tambien del financiero.

Reglas actuales:
- se guardan como `MedicalRecordProduct`
- ajustan stock con `select_for_update` para evitar race conditions
- registran el delta comercial en
  `ClinicalChargeEntry`/`ClinicalChargeQuantityEvent`;
- si se elimina el producto antes del cierre, se revierte stock y se registra el
  delta compensatorio; no existe `InvoiceItem` todavía;
- productos con `requires_prescription = true` requieren que exista una receta activa para la consulta antes de poderse agregar
- toda la operación está en `transaction.atomic()`: si falla el registro del
  delta clínico/comercial, también se revierte el movimiento de producto;

Permiso usado:
- lectura: `medicalrecord.retrieve`
- mutacion: `medicalrecord.update`

No se usa `inventory.create` para este flujo porque el acto que se protege es clinico, no de alta general de inventario.

### Orden de locks (ADR p12)

Para operaciones concurrentes de productos en consulta, se respeta el orden global:

```
MedicalRecord → Presentation → MedicalRecordProduct → ClinicalChargeEntry
```

**En `MedicalRecordProductListCreateView.perform_create()`:**
1. Lock de `MedicalRecord`
2. Lock de `Presentation`
3. Create/update de `MedicalRecordProduct` con `locked_presentation` y
   `previous_quantity`
4. Registro de `record_clinical_charge_delta`; no crea Invoice

**En `MedicalRecordProductDeleteView.perform_destroy()`:**
1. Lock de `MedicalRecord`
2. Lock de `Presentation` y del consumo vigente
3. Reversión del stock físico
4. Delta clínico/comercial compensatorio
5. Eliminación del vínculo

Ver ADRs `2026-05-16-p12-concurrency-lock-order-hardening.md` (orden global) y `2026-05-16-p13-day12-concurrency-remediation.md` (helper F() + asserts).

## Servicios usados en consulta

Los servicios agregados desde consulta forman parte del contexto clinico y financiero de la atencion.

Reglas actuales:
- se guardan como `MedicalRecordService`
- registran el delta en
  `ClinicalChargeEntry`/`ClinicalChargeQuantityEvent`;
- si se elimina antes del cierre, se registra el delta compensatorio; no se
  mutan documentos financieros;
- toda la operacion esta envuelta en `transaction.atomic()`

Permiso usado:
- lectura: `medicalrecord.retrieve`
- mutacion: `medicalrecord.update`

### Orden de locks (ADR p12)

Para operaciones concurrentes de servicios en consulta, se respeta el orden global:

```
MedicalRecord → MedicalRecordService → ClinicalChargeEntry
```

**En `MedicalRecordServiceListCreateView.perform_create()` (ADR p13 — orden corregido):**
1. Lock de `MedicalRecord` con `select_for_update()`
2. Validar tenant del `service` (`serializer.validated_data`)
3. Create/update de `MedicalRecordService`
4. Registro de `record_clinical_charge_delta`

No se crea ni se bloquea una Invoice: el cargo comercial se materializa en el
Checkout al cerrar la consulta.

**En `MedicalRecordServiceDeleteView.perform_destroy()`:**
1. Lock de `MedicalRecord`
2. Lock de `MedicalRecordService`
3. Registro del delta compensatorio
4. Eliminación del vínculo

Ver ADRs `2026-05-16-p12-concurrency-lock-order-hardening.md` (orden global) y `2026-05-16-p13-day12-concurrency-remediation.md` (MRS create reorder + helper F()).

Endpoints:
- `GET /api/medical-records/<id>/services/`
- `POST /api/medical-records/<id>/services/`
- `DELETE /api/medical-records/<id>/services/<service_id>/`

## Tipo de consulta

El campo `consultation_type` clasifica el acto medico para facilitar el flujo clinico y las validaciones en cierre.

Valores validos:
- `general` — consulta de rutina (default)
- `vaccine` — vacunacion
- `surgery` — cirugia
- `emergency` — emergencia

Reglas:
- editable mientras la consulta esta en `open`
- `treatment` requerido en el cierre para todos los tipos **excepto** `vaccine` (GENERAL, SURGERY y EMERGENCY requieren tratamiento no vacío)

## Protocolos clínicos (`consultation_draft` + materialización)

> **ADR**: [`decisions/2026-07-08-p50-vaccine-protocol-consultation-draft.md`](../decisions/2026-07-08-p50-vaccine-protocol-consultation-draft.md).
> El ADR cubre **solo** la decisión consolidada de Vacuna; el patrón generalizado
> (cirugía/hospitalización/…) está **diferido** hasta tener 2-3 implementaciones reales.

Algunos `consultation_type` activan una **sección clínica especializada** ("protocolo")
que captura datos estructurados. Primer protocolo: **Vacuna** (`consultation_type=vaccine`).

### Principio de arquitectura (binding)

**Un protocolo NUNCA modifica directamente `MedicalRecord`** (no agrega campos como
`next_deworming`, no escribe en `diagnosis`/`treatment`). Solo puede **crear o actualizar
sus propios registros de dominio** (`VaccineRecord`, futuros `SurgeryRecord`/`DewormingRecord`…)
durante el cierre. `MedicalRecord` permanece agnóstico a los protocolos; el único
acoplamiento permitido es el scratchpad `consultation_draft`.

### `MedicalRecord.consultation_draft` (scratchpad de UI — NO fuente de verdad)

`JSONField(default=dict)`. Borrador de UI de las secciones en progreso, para que
**sobrevivan a una recarga** antes de finalizar. Viaja en el mismo autosave/PATCH del
`MedicalRecord` (no hay otro canal, no localStorage).

- **NUNCA** leer para analytics, reportes, historial clínico ni registros legales.
- El serializer valida **estructura, no contenido**: whitelist `ALLOWED_CONSULTATION_DRAFT_KEYS`
  (hoy `{"vaccine"}`, se amplía 1 clave por protocolo nuevo) + tope de tamaño ~16 KB.
  Rechaza claves ajenas y payloads gigantes (evita cajón de sastre). Forma: `{"vaccine": {...}}`.

### Materialización atómica en el cierre

`services.apply_consultation_draft_on_close(medical_record, request)` se invoca
**dentro del `transaction.atomic()` de `close_medical_record`**, junto a la
materialización del Checkout y la completación de la cita. Finalizar es una sola
operación: o se cierra la consulta, se crea el registro legal y se prepara el
Checkout, o nada (rollback). El frontend no hace un POST aparte de vacuna.

- **Registry de materializadores** (`services._MATERIALIZERS = {type: fn}`, extraído en la 2ª
  repetición — Cirugía, A3): `apply_consultation_draft_on_close` despacha por
  `consultation_type`. Protocolos hoy: `general` (`ConsultationAssessment`), `vaccine`
  (`VaccineRecord`), `surgery` (`SurgeryRecord`). Agregar protocolo = 1 entrada + su clave en
  `ALLOWED_CONSULTATION_DRAFT_KEYS` + su serializer. Cada materializador gatea si su slice del
  draft trae contenido; si no, el tipo se finaliza sin registro (fallback, como una consulta
  clásica). Protocolos hoy: `general`, `vaccine`, `surgery`, `emergency`.
- **Cirugía** (`SurgeryRecord`, A3): grupos PreOp·Proc·Recup (`surgery_type`, `asa_class`,
  `anesthesia_type`, `procedure`, `wound_class`, `complications`, `postop_instructions`,
  `suture_removal_date`; `surgeon` server-side).
- **Urgencia** (`EmergencyRecord`, A3): tiempos (`arrived_at` anchor, `triage_at`,
  `stabilized_at`, `discharged_at`), `triage_level` (5 niveles), ABC "evaluación rápida"
  (`airway/breathing/circulation_status`), `chief_complaint`, `stabilization_actions`,
  `discharge_status` (alta/hospitalización/referido/fallecido), `reassessment_date`;
  `attended_by` server-side.
- **Cierre delega la validación al protocolo** (diseño A3): Cirugía, Vacuna y Urgencia **no**
  exigen `MedicalRecord.treatment`; **Urgencia** además **no** exige `diagnosis` (presuntivo
  permitido). Cada serializer valida su mínimo obligatorio → draft inválido = rollback del cierre.

#### Superficies de los registros (A3)

- `MedicalRecordSerializer` expone `consultation_assessment`, `surgery_record`, `emergency_record`
  (último de cada tipo, prefetch anti-N+1) con campos `*_display` para labels. El **Timeline**
  (`TimelineCard`) los renderiza (resumen en la card + detalle expandido: informe quirúrgico /
  informe de urgencia).
- **PDF** (`medical_record_pdf`): además del SOAP de General, secciones **Informe quirúrgico**
  (tipo/ASA/anestesia/herida/procedimiento/complicaciones/postop) e **Informe de urgencia**
  (triage/tiempos/ABC/acciones/egreso).
- **`MedicalRecord.originated_from`** (self-FK, SET_NULL): cadena de episodio
  (urgencia→cirugía→hospitalización). Único campo estructural nuevo en el central; expuesto como
  `originated_from_public_id` (read-only). **Sin UI aún** (solo el enlace de datos, diseño A3 §9).
- **Analítica por protocolo** (tiempos de urgencia, tasa de complicaciones/ISQ de cirugía,
  outcomes por estado al egreso) — **pendiente** (proyecto de dominio `analytics` aparte).
- Reusa `VaccineRecordSerializer` para validar (nombre, `application_date` no futura,
  `next_due_date > application_date`); `applied_by`/`organization` server-side. Draft
  inválido → `ValidationError` → rollback del cierre (400). Defensa en profundidad (el
  frontend valida antes de finalizar).
- Idempotente: solo corre en la rama "estaba `open` → se cierra" (cierre ya cerrado retorna
  antes) → un solo `VaccineRecord` por consulta.
- Emite log `VACCINE_RECORD_MATERIALIZED_ON_CLOSE` (INFO).

#### A2 — Vacuna ligada a inventario (trazabilidad por lote)

Si el draft de vacuna liga un `product_id` de inventario:
- Se **consume 1 dosis del lote** vía el auto-alta de `MedicalRecordProduct` (qty=1, `lot`=el
  elegido), usando la **fuente única** `services.add_medical_record_product(...)` — la misma que
  la view de Cargos (extraída al aparecer el 2º caller). El modo (`charge`/`included`) se toma de
  `Product.default_cost_behavior`; el usuario lo ajusta luego en Cobros.
- El `VaccineRecord` guarda `product` + `lot` + **snapshot** (`lot_number`, `lot_expiry`,
  `manufacturer`) — inmutable aunque el lote se corrija/borre.
- Si el vet ya agregó ese producto en Cargos, se **reusa** su MRP/lote (no doble consumo).
- Lote obligatorio si el producto tiene `tracks_lots`; sin lote válido → `ValidationError` →
  rollback del cierre. Sin `product_id` → vacuna de **texto libre** (fallback, sin consumo).
- Frontend: `VaccineSection` con picker de producto (opcional) + lote FEFO.

Frontend: ver `docs/modules/frontend.md` §`features/consultation/protocols/`.

## Signos vitales (VitalSigns)

Los signos vitales se registran como un historial append-only vinculado a la consulta.

Campos:
- `weight` — peso en kg (0.01–200)
- `temperature` — temperatura en °C (30.0–45.0)
- `heart_rate` — frecuencia cardiaca en bpm (20–300)
- `respiratory_rate` — frecuencia respiratoria en rpm (5–120)
- `recorded_by` — usuario que registro los vitales
- `recorded_at` — momento clinico real (editable, no el de ingreso al sistema)

Reglas:
- al menos un campo debe estar presente
- temperatura >= 42.0 °C con FC < 40 bpm es inconsistente clinicamente (error de validacion)
- no hay PATCH ni DELETE: cada registro es inmutable
- bloqueado si la consulta esta `closed`
- la `organization` se asigna automaticamente desde el `medical_record` (incluso si se llama directamente a `.create()`)
- `recorded_at` no puede ser futuro ni mayor a 10 anos en el pasado

El campo `weight` de `MedicalRecord` se mantiene por compatibilidad. Los helpers centrales priorizan `VitalSigns`:
- `_get_last_weight(pet)`: busca el ultimo peso del paciente en `VitalSigns` primero, luego en `MedicalRecord`. Usado para detectar cambios bruscos de peso.
- `get_current_weight(record)`: peso a mostrar en el panel lateral de una consulta. Usa el ultimo vital con `weight != None`, sino cae al campo del registro.

Endpoints:

| Metodo | URL | Descripcion |
|--------|-----|-------------|
| `GET`  | `/api/medical-records/<pk>/vitals/` | Listar vitales de la consulta (paginado) |
| `POST` | `/api/medical-records/<pk>/vitals/` | Registrar nuevos vitales |

Permisos:
- lectura: `medicalrecord.vitals.list` (VET + ASSISTANT)
- creacion: `medicalrecord.vitals.create` (VET solo)

## Panel lateral — Summary

Endpoint de lectura que agrega todos los datos relevantes de una consulta para el panel lateral de la UI. Evita multiples requests independientes.

Endpoint:
- `GET /api/medical-records/<pk>/summary/`

Respuesta:

```json
{
  "patient": { "name", "species", "breed", "birth_date" },
  "last_vitals": {
    "weight", "temperature", "heart_rate", "respiratory_rate",
    "recorded_at", "has_vitals"
  },
  "diagnosis": "...",
  "consultation_type": "general",
  "status": "open",
  "totals": { "subtotal", "tax_amount", "total", "status" },
  "next_vaccine_date": "2026-08-01"
}
```

Notas:
- `last_vitals.weight`: usa `get_current_weight(record)` — prioriza `VitalSigns.weight`, sino cae a `MedicalRecord.weight`
- `totals`: usa Invoice si ya fue posteada; de lo contrario usa el Checkout
  primario si existe; es `null` antes de ambos
- `next_vaccine_date`: proxima vacuna futura de la mascota (de cualquier consulta, no solo esta)
- el endpoint hace una sola query por entidad con `select_related`/`prefetch_related`

Permiso: `medicalrecord.summary.retrieve` (VET + ASSISTANT)

## Cierre de consulta

El cierre de consulta es explícito.

Endpoint:
- `POST /api/medical-records/<id>/close/`

Comportamiento:
- si está abierta, se valida y se cierra
- si ya estaba cerrada, responde `200` sin cambios (idempotente — no re-valida campos)
- al cerrar, **garantiza el Checkout** (ADR p62) y completa la cita vinculada si
  está en `in_progress` (ADR p34 — `in_progress → done`, idempotente)

Validaciones en cierre (solo para consultas que no están ya cerradas):
- `diagnosis` no puede estar vacío (todos los tipos)
- `treatment` no puede estar vacío **excepto** si `consultation_type = vaccine`

**Excepción para vacunación**: Las consultas de tipo `vaccine` pueden cerrarse sin tratamiento documentado, ya que en muchos flujos reales una vacunación no requiere tratamiento adicional.

Si la validación falla, retorna `400` con el campo afectado en formato estandarizado:

```json
{
  "code": "validation_error",
  "errors": {
    "treatment": ["El tratamiento es obligatorio."]
  }
}
```

El frontend (pantalla `ConsultationForm`, **single-screen**) mapea estos errores a la
sección donde vive el campo, vía `FIELD_SECTION`, y hace scroll a esa sección al fallar
el cierre:

```javascript
const FIELD_SECTION = {
  consultation_type: "eval",
  diagnosis: "eval",
  notes: "eval",
  treatment: "treat",
};
```

> Histórico: la consulta usaba un stepper de 4 pasos (`FIELD_TO_STEP`). Hoy es **una
> sola pantalla** con secciones (Evaluación / Tratamiento / Cargos) + modal de vitales.
> Ver `docs/modules/frontend.md` §`pages/medicalRecords/` (fuente canónica del frontend).

Auditoría:
- `status = closed`
- `closed_at`
- `closed_by`

Logging:
- `MEDICAL_RECORD_CLOSE_VALIDATION_FAILED` (WARNING) — emitido cuando falla validación de `diagnosis` o `treatment`. Incluye `record_id`, `field`, `user_id`, `organization_id` para auditoría.

## Reglas de negocio principales

### Consulta cerrada es inmutable

En `closed` solo se permite lectura.

No se permite para ningun rol, incluido `ADMIN`:
- editar consulta
- eliminar consulta
- agregar productos
- quitar productos
- agregar servicios
- quitar servicios
- registrar nuevos signos vitales

### Consulta con evidencia financiera no puede eliminarse

Si existe una factura vinculada a la consulta, la eliminacion retorna `403`:

```
Invoice.objects.filter(medical_record=instance).exists()
```

Esto previene que el historial financiero quede huerfano.
La consulta puede cerrarse pero no eliminarse.

Una Invoice emitida no se elimina para habilitar el borrado clínico. Los errores
financieros se corrigen con void/replacement o contra-asientos; el
`MedicalRecord` cerrado permanece como evidencia.

## Validacion de peso

El campo `weight` tiene las siguientes validaciones en el serializer:

- Minimo: `0.01 kg`, maximo: `200.00 kg`
- Cambio brusco: si el peso nuevo difiere mas del 150% respecto al ultimo peso registrado para esa mascota, el sistema retorna error. El ultimo peso se busca con `_get_last_weight(pet)`, que prioriza `VitalSigns` sobre `MedicalRecord`.

  ```
  Cambio brusco de peso: último registro 5.00 kg → nuevo 80.00 kg. Envía force_weight=true para confirmar.
  ```

- Se puede forzar enviando `force_weight: true` en el body (campo declarado explicitamente en el serializer — aparece en el schema OpenAPI)
- La validacion de cambio brusco aplica tanto en actualizaciones de `MedicalRecord` como al registrar nuevos `VitalSigns`
- La funcion `_validate_weight_change(pet, new_weight, force)` es compartida entre `MedicalRecordSerializer` y `VitalSignsSerializer`

**Helper de conversion segura** (frontend): El stepper usa `toNumberOrNull(v)` para convertir valores de input:

```javascript
const toNumberOrNull = (v) => {
    if (v === "" || v == null) return null;
    const n = Number(v);
    return Number.isNaN(n) ? null : n;
};
```

Esto maneja casos edge como `" "` (espacios) → `null`, `"0"` → `0` (válido).

## Captura de signos vitales (pantalla single-screen)

La consulta es **una sola pantalla** (`ConsultationForm`), no un stepper. Los signos
vitales se muestran como chips siempre visibles en `ConsultationPatientBanner` (solo
lectura) y se editan en `VitalsModal` (progressive disclosure). Ver
`docs/modules/frontend.md` §`pages/medicalRecords/` (fuente canónica del frontend).

**Autosave**: el formulario autoguarda el borrador ~1s después de la última edición
(`persistDraft({ silent: true })` con debounce), con indicador visible en el footer
(Guardando… / Cambios guardados / No se pudo guardar). El borrador persiste server-side
como `MedicalRecord` en estado `open` → **recuperable** al reabrir la consulta. El
primer autosave **crea** el `MedicalRecord` (lazy, ligado a la cita si vino de "Atender
ahora"); los siguientes hacen `PATCH` parcial.

**Orden de escritura por guardado** (mismo contrato de consistencia que antes):
1. Primero se crea/actualiza el `MedicalRecord` (`POST` lazy la primera vez, luego `PATCH`).
2. Luego se crean los `VitalSigns` si cambiaron (hash normalizado) y hay al menos un
   campo no-vacío (`POST /medical-records/{id}/vitals/`; el peso **no** va en el PATCH
   del MR — vive en `VitalSigns`).
3. Luego la receta si cambió (hash).

Si el paso 1 falla, los vitales no se guardan (consistencia por orden, no por transacción DB).
El hash evita duplicar registros idénticos de vitales en autosaves sucesivos.

**Doble fuente de peso**:
- `MedicalRecord.weight` — campo legacy, se mantiene por compatibilidad con datos históricos
- `VitalSigns.weight` — fuente de verdad para signos vitales
- Solo se envía `weight` a `createVitals()`, nunca a `updateMedicalRecord()`

**Edición de consulta existente**: al editar, `ConsultationForm` precarga los vitales
desde `initialRecord.latest_vitals`, con fallback a `initialRecord.weight` si no hay
vitales registrados.

## Registro de vacunas

El modulo incluye el modelo `VaccineRecord` para registrar el historial de vacunacion de una mascota.

Ver seccion completa abajo.

## Relación con facturación

El dominio clínico se completa antes del financiero:

```text
MedicalRecord closed → Checkout primary_consultation → Invoice posted → Payment
```

El cierre no depende del pago y completa la cita vinculada cuando corresponde.
El Checkout puede resolverse como `no_charge` sin Invoice, postearse y pagarse
de inmediato, o generar una Invoice `posted` para pago posterior autorizado.
La relación financiera conserva trazabilidad al `MedicalRecord`, pero no lo
vuelve editable.

## Seguridad y control de acceso

El modulo usa dos capas:

### 1. Aislamiento multitenant

Toda operacion se limita a `request.user.organization`.

### 2. RBAC + policy de dominio

RBAC determina si el usuario tiene permiso sobre el recurso.
La policy de dominio (`apps/medical_records/policies.py`) agrega reglas no expresables solo con permisos atomicos:
- ownership del veterinario
- bloqueo por estado `closed`

Funciones de policy:
- `can_modify_medical_record_charges(user, medical_record)`: ADMIN siempre, VET solo si es el asignado
- `can_close_medical_record(user, medical_record)`: ADMIN siempre, VET solo si es el asignado
- `assert_can_modify_charges(user, medical_record, request)`: gate **billing** — productos y servicios. Lanza `PermissionDenied` + emite log.
- `assert_can_modify_medical_record(user, medical_record, request)`: gate **clinico** — signos vitales y datos no-factura. Valida org + estado `closed`. Semanticamente distinto del anterior.

Importante: no usar `assert_can_modify_charges` para vitales. Son dominios distintos aunque comparten el bloqueo por `closed`.

## Vacunas (VaccineRecord)

El estado de vacunacion de una mascota era anteriormente hardcodeado en el frontend mediante una expresion regular sobre el texto del diagnostico (`/vacun/i`). Esto fue eliminado.

Ahora existe el modelo `VaccineRecord` con datos reales.

### Modelo

Campos:
- `pet` — FK a Pet (**PROTECT** desde PR-4B / ADR p16 — antes CASCADE; justificacion NOM-007/046 retencion vacunal)
- `vaccine_name` — nombre de la vacuna (requerido, no puede estar vacio)
- `application_date` — fecha de aplicacion (no puede ser futura)
- `next_due_date` — fecha de proximo refuerzo (opcional; si se envia, debe ser posterior a `application_date`)
- `applied_by` — FK a User (SET_NULL, opcional)
- `notes` — texto libre
- `medical_record` — FK opcional a la consulta donde se aplico (SET_NULL)

### Estado derivado

El estado no se almacena en DB. Se calcula como propiedad:

| Estado          | Condicion                               |
|-----------------|-----------------------------------------|
| `current`       | `next_due_date` existe y es fecha futura |
| `overdue`       | `next_due_date` existe y ya paso        |
| `no_scheduled`  | sin `next_due_date` (puede ser intencional o no capturado) |

### Validaciones

- `vaccine_name` no puede ser vacio o solo espacios
- `application_date` no puede ser en el futuro
- `next_due_date` debe ser posterior a `application_date` si se envia
- `pet` debe pertenecer a la misma organizacion del usuario autenticado (validado en serializer)
- `medical_record` si se envia, debe pertenecer a la misma organizacion (validado en serializer)

### Endpoints

| Metodo   | URL                                | Descripcion                                |
|----------|------------------------------------|--------------------------------------------|
| `GET`    | `/api/vaccines/`                   | Listar vacunas (filtrar por `?pet=<uuid>`) |
| `POST`   | `/api/vaccines/`                   | Registrar vacuna                           |
| `GET`    | `/api/vaccines/<public_id>/`       | Detalle                                    |
| `PATCH`  | `/api/vaccines/<public_id>/`       | Editar                                     |

**Día 6 (ADR p18):** `VaccineRecord` promovido a modelo público — heredó `PublicIdMixin`. URLs ahora usan `<str:pk>` con UUID v4. Pre-Día-6 usaba `<int:pk>` (enumeration cross-org). Filter `?pet=` resuelve via `resolve_public_id`.

**DELETE removido en PR-4B / ADR p16**: el registro vacunal es documento legal (NOM-007/046) — bloquear borrado directo es consistente con la motivacion del flip `VaccineRecord.pet` → PROTECT. `DELETE /api/vaccines/<id>/` ahora responde **405**. Para anular un registro creado por error, usar `PATCH` (campo `notes`); soft-delete real es deuda Fase 2 A5.

### Indice

Se usa `Index(fields=['pet', 'vaccine_name'])` para optimizar queries frecuentes de historial de vacunacion por mascota.
El ordenamiento es `-application_date, -id` para desambiguar registros con la misma fecha.

## Cascade lockdown (PR-4B / ADR p16)

| FK | Estado | Motivo |
|----|--------|--------|
| `MedicalRecord.pet` | **PROTECT** (era CASCADE) | NOM-046 retencion 5 anos de expediente clinico |
| `VaccineRecord.pet` | **PROTECT** (era CASCADE) | NOM-007/046 retencion vacunal |
| `MedicalRecord.veterinarian` | SET_NULL (sin cambio) | Permite borrado de usuarios; snapshot `vet_name_at_close` es deuda Fase 2 A7 |
| `MedicalRecord.appointment` | SET_NULL (sin cambio) | Cita puede purgarse; expediente sobrevive |
| `MedicalRecordProduct.medical_record` | CASCADE (sin cambio) | Producto consumido pertenece a la consulta — sin MR pierde semantica |
| `MedicalRecordService.medical_record` | CASCADE (sin cambio) | Igual que producto |
| `VitalSigns.medical_record` | CASCADE (sin cambio) | Subrecurso del MR — append-only pero vida atada al padre |

Comportamiento DELETE actual:
- `DELETE /api/medical-records/<uuid>/` con prescriptions/invoices/vitales asociadas → bloqueado por guard `medical_record_has_clinical_content` (403 antes de tocar PROTECT) o **409 Conflict** del handler global si PROTECT dispara.
- `DELETE /api/vaccines/<id>/` → **405 Method Not Allowed** (removido en PR-4B).

## Frontend — patron de submit

El formulario de nueva/editar consulta usa `saving` state para bloquear el boton durante la operacion. Ver ADR `2026-05-02-p2-frontend-ux-hardening.md` para el patron estandar.

## Observabilidad

Eventos relevantes en logs (`medical_records.events`):
- `MEDICAL_RECORD_CLOSED`
- `MEDICAL_RECORD_CLOSE_IDEMPOTENT`
- `MEDICAL_RECORD_OWNERSHIP_DENIED`
- `MEDICAL_RECORD_CLOSED_DENIED`
- `VITAL_SIGNS_CREATED` (INFO) — emitido por `VitalSignsListCreateView.perform_create`

Eventos analytics (logger separado `analytics.events`):
- `ANCHOR_LATE_ARRIVAL` (WARNING) — emitido por `_warn_if_late_closed_at` cuando `closed_at` cae en un bucket frozen (ADR p17 — Día 5)

Estos eventos permiten auditar intentos de mutacion sobre consultas fuera de policy y el registro de vitales.
