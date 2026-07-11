# ADR: Vacuna estructurada — `consultation_draft` + materialización atómica en el cierre

**Fecha**: 2026-07-08
**Estado**: Implementado

## Alcance (leer primero)

Este ADR documenta **solo la decisión consolidada y ya implementada**: capturar la vacuna
de forma estructurada dentro de la consulta y crear el `VaccineRecord` al finalizar. Es el
**primer protocolo clínico**.

**NO** es el ADR del "sistema de protocolos clínicos" generalizado (cirugía, hospitalización,
desparasitación, odontología…). Ese patrón se documentará **después** de tener 2-3
implementaciones reales que prueben que el contrato aguanta — hoy sería arquitectura
imaginada, no una decisión consolidada. Ver §Diferido.

## Contexto

`consultation_type` (`general`/`vaccine`/`surgery`/`emergency`) existía pero solo se usaba
para **saltar** el requisito de tratamiento en vacunas (ADR p4). Una consulta de vacuna no
capturaba nada estructurado: el dato quedaba como texto libre en `diagnosis`, y el modelo
`VaccineRecord` (que ya existía con endpoints y valor legal NOM-007/046, ADR p16) quedaba
huérfano en otra pantalla — nunca se creaba desde la consulta. La ficha de mascota incluso
derivaba "última vacuna" con un regex `/vacun/i` sobre el texto de las consultas.

## Problema

1. Doble captura / dato no confiable: la vacuna no alimentaba `VaccineRecord` ni el dashboard.
2. Si se creara el `VaccineRecord` como un POST separado del frontend tras cerrar la consulta,
   un fallo entre `close` (200) y `createVaccine` dejaría **consulta cerrada sin registro de
   vacuna** → historial inconsistente.
3. El borrador de la vacuna debía **sobrevivir a una recarga** antes de finalizar, sin crear
   prematuramente el registro legal (append-only).

## Decisión

### 1. `MedicalRecord.consultation_draft` — scratchpad de UI (NO fuente de verdad)

`JSONField(default=dict, blank=True)`. Borrador de las secciones clínicas en progreso, para
que sobrevivan a una recarga. **Reusa el autosave existente** del `MedicalRecord` (mismo
PATCH/POST lazy) — no se inventó otro autosave, no se usó `localStorage`.

Invariante (comentario en el modelo, binding): **nunca es fuente de verdad**; jamás leer para
analytics, reportes, historial clínico ni registros legales. Forma: `{"vaccine": {...}}`.

Validación de **estructura, no de contenido** en `MedicalRecordSerializer.validate_consultation_draft`:
whitelist `ALLOWED_CONSULTATION_DRAFT_KEYS = {"vaccine"}` (se amplía 1 clave por protocolo
nuevo) + tope ~16 KB. Rechaza claves ajenas y payloads gigantes (evita que el campo se vuelva
un cajón de sastre).

### 2. Materialización atómica en el cierre (backend, único responsable)

`services.apply_consultation_draft_on_close(medical_record, request)` se invoca **dentro del
`transaction.atomic()` de `close_medical_record`**, junto al invoice-guard (ADR p30) y a la
completación de la cita (ADR p34). Finalizar es **una sola operación**: o se cierra la consulta
Y se crea el registro legal, o nada (rollback). **El frontend NO hace un POST aparte.**

- Gate: solo materializa si `consultation_type == 'vaccine'` y el draft trae `vaccine_name`.
  Finalizar como otro tipo no materializa (el draft puede sobrevivir sin volverse registro legal).
- **Reusa `VaccineRecordSerializer`** para validar (nombre, `application_date` no futura,
  `next_due_date > application_date`); `applied_by`/`organization` server-side.
- Idempotente: solo corre en la rama "estaba `open` → se cierra" → un `VaccineRecord` por consulta.
- Draft inválido → `ValidationError` → rollback del cierre (400). Defensa en profundidad (el
  frontend valida antes de finalizar). Log `VACCINE_RECORD_MATERIALIZED_ON_CLOSE` (INFO).

### 3. Principio de arquitectura (binding) — un protocolo no muta `MedicalRecord`

Un protocolo **NUNCA** modifica directamente `MedicalRecord` (no agrega campos como
`next_deworming`, no escribe `diagnosis`/`treatment`). Solo puede **crear o actualizar sus
propios registros de dominio** (`VaccineRecord`) durante el cierre. `MedicalRecord` queda
agnóstico a los protocolos; el único acoplamiento permitido es el scratchpad `consultation_draft`.
Esta regla, escrita desde el primer protocolo, evita que los futuros ensucien el modelo central.

### 4. Frontend — registry + contrato mínimo (sin persistencia en el cliente)

`features/consultation/protocols/`: `registry.js` (`protocolFor(type)`) + carpeta-por-protocolo
`vaccine/` (`VaccineSection.jsx`, `vaccineProtocol.js`, `vaccinePresets.js`, `index.js`).
Contrato mínimo **`{ label, Section, initDraft, validate }`** — sin método de persistencia,
porque la materialización vive en el backend. `initDraft` apareció por un requisito real
(reload-survival), no por anticipación. Agregar un protocolo = copiar la carpeta + 1 entrada en
el registry. `vaccinePresets.js` es estático pero con forma extensible a catálogo por-org.

### 5. Fix derivado

La ficha de mascota (`pets.jsx`) ahora lee `VaccineRecord` real (`GET /api/vaccines/?pet=`) en
vez del regex `/vacun/i` sobre el texto de consultas.

## Alternativas consideradas

- **A — Frontend crea el `VaccineRecord` tras `close`**: *rechazado por atomicidad*. `close` 200
  seguido de un `createVaccine` que falla deja historial inconsistente. Finalizar es una sola
  operación conceptual → un solo `atomic()` en backend.
- **B — Motor genérico de plantillas (schema-driven JSON)**: *rechazado*. Los campos clínicos
  tienen efectos/validaciones reales (registro append-only legal, cálculo de protocolo de
  refuerzo) que un renderer de JSON no expresa con seguridad. Un protocolo = módulo de código.
- **C — `localStorage` para el borrador**: *rechazado*. Mecanismo paralelo (contradice reusar el
  autosave), no sincroniza entre dispositivos, deja PII clínica en disco.
- **D — Crear `VaccineRecord` lazy durante el borrador (como la receta)**: *rechazado*. Dejaría
  registros legales de vacunas no confirmadas si la consulta se abandona sin finalizar.

## Diferido (NO decidido en este ADR)

- ADR del **patrón de protocolos generalizado** (esperar 2-3 implementaciones reales).
- Cirugía / desparasitación / hospitalización / odontología (sin stubs).
- Registro de materializadores backend / helper `createProtocolDraft()` (extraer cuando el
  patrón se repita, ~4-5 protocolos; hoy un solo `if consultation_type=='vaccine'` + 1 clave).
- Métodos de contrato `hydrate`/`isDirty` (agregar cuando un protocolo real los exija).
- Campo `batch_number` dedicado en `VaccineRecord` (v1 usa `notes` para lote).

## Relación con otros ADRs

- **p4** (CREATE borrador vs CLOSE): este ADR **extiende los efectos del cierre** con un nuevo
  efecto de dominio, dentro del mismo `atomic()`.
- **p30** (cierre garantiza factura): la materialización de vacuna vive en el mismo `atomic()`.
- **p34** (cierre completa la cita): mismo patrón de efecto-de-cierre cross-domain vía service.
- **p16** (`VaccineRecord` PROTECT + append-only, NOM-007/046): el registro materializado es ese
  documento legal.
- **p9** (anchors de analytics con único writer): `consultation_draft` **no** es un anchor ni
  entra a analytics — es explícitamente lo opuesto (scratchpad efímero).

## Deuda técnica

- El writer de `closed_at` y ahora `apply_consultation_draft_on_close` se invocan desde la
  **view** (`close_medical_record`), no desde un `close_medical_record_service` (deuda A3
  preexistente). El materializador ya vive en `services.py`; migrará junto con el writer cuando
  se cierre A3.
- El error de `proto.validate` (refuerzo programado sin fecha) se muestra por toast + scroll a
  Evaluación, no inline en la sección de vacuna. Aceptable v1.
