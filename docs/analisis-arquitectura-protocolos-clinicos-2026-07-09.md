# Estudio de arquitectura — Protocolos clínicos por tipo de consulta

> [!NOTE]
> **Corte histórico de arquitectura (2026-07-09).** Se conserva como evidencia
> de las decisiones disponibles en esa fecha. Cualquier referencia a la
> creación lazy de Invoice o al lifecycle anterior de Billing fue sustituida
> por `MedicalRecord → Checkout → Invoice posted → Payment`; consulte
> [Billing](modules/billing.md) y el
> [ADR p62](decisions/2026-08-30-p62-billing-checkout-lifecycle.md).

**Fecha**: 2026-07-09
**Tipo**: Investigación (read-only). **NO** propone implementación, migración ni cambios de modelo.
**Audiencia**: quien vaya a diseñar la evolución hacia protocolos clínicos independientes.
**Método**: cada afirmación está respaldada por `archivo:línea` verificado leyendo el código. Donde algo **no existe**, se declara explícitamente.

---

## 0. Hallazgo principal (leer primero)

La premisa de la solicitud —"`consultation_type` es solo una etiqueta que cambia validaciones menores"— **era cierta hasta el 2026-07-08**. El día anterior a este estudio se implementó **ADR p50** (`docs/decisions/2026-07-08-p50-vaccine-protocol-consultation-draft.md`), que introdujo el **primer protocolo clínico real (Vacuna)** con:

- un **scratchpad** persistente (`MedicalRecord.consultation_draft`, `models.py:46`),
- un **registry de protocolos** en frontend (`features/consultation/protocols/registry.js`),
- un **contrato mínimo** `{ label, Section, initDraft, validate }` (`vaccine/vaccineProtocol.js:17`),
- **materialización atómica** de un registro de dominio (`VaccineRecord`) en el cierre (`services.py:15`),
- y un **principio de arquitectura binding**: *un protocolo NUNCA modifica `MedicalRecord`; solo crea/actualiza sus propios registros de dominio* (`services.py:20-22`, ADR p50 §3).

**Conclusión anticipada**: la arquitectura **NO parte de cero**. Ya existe el andamiaje (patrón, contrato, punto de extensión, principio de aislamiento) probado con un protocolo real. La pregunta ya no es *"¿se puede evolucionar?"* sino *"¿el contrato de un solo protocolo aguanta 2-3 más sin reescribirse?"*. El propio ADR p50 lo dejó **deliberadamente sin generalizar** (§Diferido) esperando esa evidencia. Este documento evalúa qué tan lejos llega el andamiaje actual y dónde se rompe.

---

## 1. Resumen ejecutivo

| Dimensión | Estado actual | Preparación |
|---|---|---|
| Punto de extensión frontend | `registry.js` + carpeta-por-protocolo | **Alta** — copiar carpeta + 1 línea |
| Contrato de protocolo | `{ label, Section, initDraft, validate }` | **Media** — sin `hydrate`/`isDirty`/persistencia declarada; validación por-toast, no inline |
| Persistencia de borrador | `consultation_draft` JSON + whitelist + autosave reusado | **Alta** — sobrevive recarga, no ensucia el modelo |
| Materialización backend | `apply_consultation_draft_on_close`, 1 `if consultation_type=='vaccine'` hardcodeado | **Media-baja** — no hay registry backend; el 2º protocolo agrega otro `if` |
| Aislamiento del modelo central | Principio binding "un protocolo no muta MedicalRecord" | **Alta** — escrito y respetado desde el 1º |
| Cirugía | **No existe** estructura. Solo etiqueta + `treatment` requerido | **Nula** (texto libre) |
| Urgencia | **No existe** flujo distinto. Solo etiqueta + `treatment` requerido | **Nula** (texto libre) |
| Migración de datos | Aditiva pura hasta hoy; consultas viejas conviven sin tocar | **Alta** — sin riesgo de pérdida |
| Cobertura de pruebas | Vacuna bien cubierta; General/Surgery/Emergency solo cubren skip de treatment | **Media** — protocolos futuros nacen sin red |

**Veredicto**: arquitectura **moderadamente preparada**. El frontend está listo para replicar el patrón. El backend tiene un acoplamiento puntual (`if` hardcodeado, sin registry) que debe abstraerse al 2º-3er protocolo, exactamente como anticipó ADR p50 §Diferido. Los tipos `surgery`/`emergency` hoy son cascarones: evolucionarlos es *green-field* dentro de un andamiaje existente, no un refactor de algo acoplado.

---

## 2. Mapa del flujo actual — "Nueva consulta" hasta la BD

### 2.1 Diagrama de flujo (consulta con protocolo Vacuna)

```
USUARIO: "Atender ahora" (appointments.jsx) o "+ Nueva Consulta" (medicalRecords/index.jsx)
   │
   ▼
medicalRecords/index.jsx  (orquestador)
   │  - lee location.state.appointmentId (flujo cita) — index.jsx:97
   │  - carga catálogo de productos — index.jsx:131
   │  - monta <ConsultationForm pet products appointmentId /> — index.jsx:324-332
   ▼
ConsultationForm.jsx  (container: estado + API + autosave)
   │  draft = { consultation_type, diagnosis, treatment, notes, weight... } — CF:116-140
   │  protocolDraft = { vaccine: {...} }  (sembrado por initDraft) — CF:177-179
   │  proto = protocolFor(draft.consultation_type)  → registry.js:17 — CF:229
   │
   ├─ EvaluationSection: elige consultation_type (typeCard) — EvaluationSection:43
   ├─ proto.Section (VaccineSection) si proto ≠ null — CF:929-941
   ├─ TreatmentSection: treatmentRequired = type!=='vaccine' — TreatmentSection:27
   └─ ChargesSection: productos + servicios (efecto de stock/factura)
   │
   ▼ (autosave debounced ~1s — CF:566-570)
persistDraft({silent}) — CF:397
   │  mrPayload = { consultation_type, diagnosis, treatment, notes,
   │               consultation_draft: protocolDraft }  — CF:414-420
   │  POST  /api/medical-records/           (lazy, 1ª vez) — createMedicalRecord
   │  PATCH /api/medical-records/<pk>/       (siguientes)   — updateMedicalRecord
   │  + POST vitals (si cambió) / prescription (si cambió)
   ▼
BACKEND: MedicalRecordListCreateView / MedicalRecordDetailView — views.py:83 / :116
   │  MedicalRecordSerializer valida:
   │    - validate_consultation_draft: whitelist + 16KB — serializers.py:249
   │    - sanitize diagnosis/treatment/notes — serializers.py:215-222
   │    - tenant guards (pet/vet/appointment misma org) — serializers.py:244-273
   │  perform_create: organization + veterinarian server-side — views.py:109-113
   ▼
DB: MedicalRecord (status='open', consultation_draft={"vaccine":{...}})

────────────────────────────  FINALIZAR  ────────────────────────────

USUARIO: "Finalizar y enviar a Cobros" (ConsultationFooter)
   ▼
handleFinalize — CF:610
   │  errors = validateForClose(draft) ∪ proto.validate(protoSlice) — CF:611-614
   │  persistDraft() (guarda todo)  →  closeRecord()
   ▼
POST /api/medical-records/<pk>/close/  → close_medical_record (view) — views.py:429
   │  transaction.atomic():
   │    1. select_for_update del MR — views.py:433
   │    2. can_close_medical_record (policy/ownership) — views.py:440
   │    3. idempotencia: si ya closed → return — views.py:444
   │    4. valida diagnosis obligatorio — views.py:458-469
   │    5. valida treatment obligatorio SI type != vaccine — views.py:471-483
   │    6. status=closed, closed_at=now, closed_by — views.py:485-491
   │    7. get_or_create_invoice_for_medical_record (ADR p30) — views.py:499-500
   │    8. complete_appointment_on_record_close (ADR p34) — views.py:506-507
   │    9. apply_consultation_draft_on_close (ADR p50) — views.py:515-516
   │       └─ services.py:15
   │          - gate: type==VACCINE y draft.vaccine.vaccine_name — services.py:34-43
   │          - VaccineRecordSerializer(payload).save(applied_by, org) — services.py:56-62
   │          - log VACCINE_RECORD_MATERIALIZED_ON_CLOSE — services.py:64
   │   10. _warn_if_late_closed_at (analytics observability) — views.py:521
   ▼
DB: MedicalRecord(status=closed) + VaccineRecord(nuevo) + Invoice(draft) — TODO o NADA (atomic)
```

### 2.2 Puntos de autoridad (quién escribe qué)

- **`consultation_type`**: escrito por el cliente vía `MedicalRecordSerializer` (campo writable, `serializers.py:188`). No es read-only. Editable mientras la consulta esté `open`.
- **`consultation_draft`**: escrito por el cliente (writable, `serializers.py:167`), validado solo en estructura (`serializers.py:249`). **Nunca** es fuente de verdad (`models.py:36-46`).
- **`closed_at` / `status=closed`**: único writer es la view `close_medical_record` (`views.py:485-491`), protegido por CHECK constraint DB (`models.py:126-129`) y por `save()` guard (`models.py:78-82`).
- **`VaccineRecord`**: DOS caminos de escritura (ver §7.2) — (a) materialización en cierre (`services.py:58`), (b) endpoint directo `POST /api/vaccines/` (`views.py:554-558`).

---

## 3. Inventario de archivos

### 3.1 Backend — dominio `medical_records`

| Archivo | Responsabilidad | Relevancia protocolos |
|---|---|---|
| `models.py:9-130` | `MedicalRecord` (estado, consultation_type, consultation_draft, closed_at, invariantes) | **Núcleo** |
| `models.py:14-18` | enum `ConsultationType` (general/vaccine/surgery/emergency) | **Núcleo** |
| `models.py:46` | campo `consultation_draft` (scratchpad, whitelisteado) | **Núcleo** |
| `models.py:133-166` | `VaccineRecord` (registro legal append-only, NOM-007/046) | **Núcleo** (protocolo Vacuna) |
| `models.py:169-197` | `VitalSigns` (append-only, transversal a todo tipo) | Transversal |
| `models.py:200-229` | `MedicalRecordService` (servicios aplicados) | Transversal |
| `services.py:15-73` | `apply_consultation_draft_on_close` — materializador único (hoy solo Vacuna) | **Núcleo** |
| `views.py:429-533` | `close_medical_record` — orquesta todos los efectos de cierre | **Núcleo** |
| `views.py:471-483` | skip de `treatment` para vaccine | Regla por-tipo |
| `views.py:83-165` | List/Create/Detail de MedicalRecord | Soporte |
| `views.py:536-579` | `VaccineRecord` List/Create/Detail (sin DELETE) | Protocolo Vacuna |
| `views.py:586-768` | `medical_record_pdf` (usa `_MR_TYPE_LABEL`, `views.py:583`) | Exportación |
| `serializers.py:126-343` | `MedicalRecordSerializer` (+ Detail) | **Núcleo** |
| `serializers.py:17` | `ALLOWED_CONSULTATION_DRAFT_KEYS = {"vaccine"}` | **Núcleo** (whitelist) |
| `serializers.py:249-263` | `validate_consultation_draft` (estructura, no contenido) | **Núcleo** |
| `serializers.py:370-435` | `VaccineRecordSerializer` (reusado por el materializador) | Protocolo Vacuna |
| `policies.py` (no leído en detalle) | ownership/close guards (`can_close_medical_record`, `assert_can_modify_charges`) | Soporte |
| `urls.py:16-28` | rutas (incluye `/close/`, `/vaccines/`) | Soporte |
| `migrations/0012_add_consultation_type.py` | añade `consultation_type` (default general, db_index) | Historia |
| `migrations/0019_medicalrecord_consultation_draft.py` | añade `consultation_draft` JSON (2026-07-08) | Historia |

### 3.2 Frontend — protocolos y consulta

| Archivo | Responsabilidad | Relevancia |
|---|---|---|
| `features/consultation/protocols/registry.js` | `protocolFor(type)` → protocolo o null | **Punto de extensión** |
| `features/consultation/protocols/vaccine/vaccineProtocol.js` | contrato `{label, Section, initDraft, validate}` | **Contrato de referencia** |
| `features/consultation/protocols/vaccine/VaccineSection.jsx` | UI presentacional de la vacuna | Protocolo Vacuna |
| `features/consultation/protocols/vaccine/vaccinePresets.js` | catálogo estático + `computeNextDue`/`todayISO` | Protocolo Vacuna |
| `features/consultation/protocols/vaccine/index.js` | barrel | Soporte |
| `pages/medicalRecords/ConsultationForm.jsx` | **container**: estado, autosave, finalize, monta `proto.Section` | **Núcleo** |
| `pages/medicalRecords/index.jsx` | orquestador de página, filtros por tipo (`TYPE_FILTERS:27`) | Soporte |
| `pages/medicalRecords/EvaluationSection.jsx` | selector de `consultation_type` (typeCards) | **Núcleo** |
| `pages/medicalRecords/TreatmentSection.jsx` | tratamiento + receta; `treatmentRequired` por tipo (`:27`) | Regla por-tipo |
| `pages/medicalRecords/ChargesSection.jsx` | productos + servicios (stock/factura) | Transversal |
| `pages/medicalRecords/SidePanel.jsx:260` | badge de tipo (`CONSULTATION_TYPE_LABELS`) | Display |
| `pages/medicalRecords/Timeline.jsx:70` | `TYPE_META` por tipo (icono/color) | Display |
| `api/vaccines.js` | `getVaccines({pet})` — **solo lectura** | Protocolo Vacuna |
| `api/medicalRecords.js` | CRUD + close (no leído en detalle, referenciado por CF) | Soporte |

### 3.3 Tests

| Archivo | Cubre |
|---|---|
| `medical_records/tests/test_consultation_draft.py` | whitelist/estructura (`:39-103`) + materialización Vacuna (`:106-203`) |
| `medical_records/tests/test_close.py:210-320` | skip de treatment por tipo (surgery/emergency requieren; vaccine no) |
| `features/consultation/protocols/vaccine/*.test.{js,jsx}` | protocolo/presets/section (frontend) |
| `medical_records/tests/test_pdf.py`, `test_vitals.py` | usan `consultation_type` como dato, no como lógica |

---

## 4. Modelo de datos

### 4.1 Diagrama ER simplificado (contexto consulta)

```
              Organization
                   │ (org scoping en TODO modelo)
    ┌──────────────┼───────────────┬──────────────┐
   Pet          Owner            User          Service
    │  PROTECT      │ PROTECT       │ SET_NULL      │ PROTECT
    │               │               │               │
    ▼               │               ▼               │
 MedicalRecord ◄────┘         (veterinarian,        │
    │  - consultation_type          closed_by,       │
    │  - consultation_draft {json}  applied_by)      │
    │  - status open/closed                          │
    │  - closed_at (editable=False, CHECK)           │
    │  - diagnosis/treatment/notes/weight            │
    │                                                │
    ├─1:1─► Prescription  (OneToOne, receta)         │
    ├─1:N─► VitalSigns    (append-only)              │
    ├─1:N─► MedicalRecordService ───────────────────►┘ (sync a InvoiceItem vía view)
    ├─1:N─► MedicalRecordProduct (inventory) ──► Presentation (stock)
    ├─1:N─► VaccineRecord (SET_NULL, materializado en cierre) ◄── PROTOCOLO VACUNA
    └─0:1─► Invoice (billing, lazy/garantizada al cerrar)
                │
           Appointment ──1:N──► MedicalRecord (SET_NULL, ligado por "Atender ahora")
```

### 4.2 Entidades clave

**`MedicalRecord`** (`models.py:9-130`)
- **Propósito**: el acto clínico. Cabecera única de una consulta.
- **FKs**: `pet` PROTECT (`:20`), `veterinarian` SET_NULL (`:21`), `appointment` SET_NULL (`:22`).
- **Campos de tipo**: `consultation_type` CharField(20), choices, default `general`, `db_index=True` (`:28-33`).
- **Scratchpad**: `consultation_draft` JSONField default dict (`:46`). Comentario binding "nunca fuente de verdad" (`:36-45`).
- **Anchor analítico**: `closed_at` `editable=False` (`:50`), `closed_at_source` (`:56`).
- **Restricciones**: `CheckConstraint` `status=closed ⇒ closed_at not null` (`:126-129`); `save()` refuerza el mismo invariante (`:78-82`); `clean()` valida tenant de pet/vet/appointment (`:63-70`).
- **Índices**: `(org, pet, -created_at)`, `(org, status, -closed_at)`, `(org, appointment)`, `(org, status, -created_at)` (`:109-120`). Ninguno indexa `consultation_type` compuesto (solo el `db_index` simple del campo).

**`VaccineRecord`** (`models.py:133-166`)
- **Propósito**: documento legal de vacunación (NOM-007/046), append-only (DELETE removido, `views.py:561-574`).
- **FKs**: `pet` PROTECT (`:138`), `applied_by` SET_NULL (`:142`), `medical_record` SET_NULL (`:146`) — el FK a la consulta es **opcional y débil** (SET_NULL): un VaccineRecord puede existir sin consulta.
- **Campos**: `vaccine_name` (str libre, `:139`), `application_date`, `next_due_date` (nullable), `notes` (lote va aquí, ADR p50 §Diferido).
- **`status` derivado** (property, `:150-155`): current/overdue/no_scheduled según `next_due_date`.
- **Índices analytics**: `(org, application_date)`, `(org, next_due_date)` (`:162-165`).

**`VitalSigns`** (`models.py:169-197`), **`MedicalRecordService`** (`models.py:200-229`): transversales a cualquier tipo de consulta; no dependen de `consultation_type`.

### 4.3 Observación de diseño

El único enlace estructural entre `MedicalRecord` y un protocolo es:
1. `consultation_type` (discriminador, `models.py:28`), y
2. `consultation_draft` (scratchpad efímero, `models.py:46`).

El registro **autoritativo** del protocolo (`VaccineRecord`) vive **fuera** de `MedicalRecord` y lo referencia con FK débil (`SET_NULL`). Esto es exactamente el principio binding: el modelo central no crece por protocolo. Un `SurgeryRecord` futuro seguiría el mismo molde (tabla propia, FK SET_NULL a `MedicalRecord`).

---

## 5. Relación con otros módulos

Qué consume información de una consulta y qué pasaría si cambia su estructura:

| Módulo | Qué consume | Cómo | Impacto si cambia la estructura |
|---|---|---|---|
| **Billing** (`billing`) | La consulta **garantiza** una `Invoice` draft al cerrar; servicios/productos sincronizan `InvoiceItem` | `get_or_create_invoice_for_medical_record` en `views.py:500`, `:237` | **Alto acoplamiento operativo, pero estable**: billing no lee `consultation_type` ni `consultation_draft`. Añadir protocolos no lo toca mientras el cierre siga garantizando factura. |
| **Appointments** (`appointments`) | Cierre de consulta completa la cita (`in_progress→done`) | `complete_appointment_on_record_close` en `views.py:507` | Bajo: cross-domain por service; agnóstico al tipo. |
| **Inventory** (`inventory`) | Productos consumidos descuentan stock | `MedicalRecordProduct` + view de charges | Bajo: agnóstico al tipo. |
| **VaccineRecord / Historial vacunal** | Se materializa en el cierre de consultas vaccine | `services.py:58` | **Este ES el protocolo**. Es el patrón a replicar, no un consumidor pasivo. |
| **Ficha de mascota** (`pets.jsx`) | Lee vacunas reales `GET /api/vaccines/?pet=` (ya no regex `/vacun/i`) | `api/vaccines.js`, fix ADR p50 §5 | Positivo: ya desacoplado del texto libre. |
| **Analytics** (`analytics`) | `medical_records_closed` (via `closed_at`); vacunas via índices `(org, application_date/next_due_date)` | `models.py:114`, `:162-165` | **Sensible**: analytics ancla en `closed_at`, NO en `consultation_draft` (ADR p50 §p9). Un protocolo que quisiera métricas debe materializar un registro con su propio anchor (como VaccineRecord), nunca leer el scratchpad. |
| **Dashboard** | `OperationalFeed` muestra tipo (`REC_TYPE`), summary devuelve `consultation_type` | `OperationalFeed.jsx:57-58`, `views.py:416` | Bajo/display: agregar un tipo requiere sumar su label en los mapas de display. |
| **PDF / Exportaciones** | Resumen clínico imprime `Tipo:` via `_MR_TYPE_LABEL` | `views.py:583`, `:627` | Bajo/display: nuevo tipo → nueva entrada de label. **El PDF NO imprime datos del protocolo** (solo dx/treatment/vitales/servicios/productos/receta). Un protocolo con datos propios necesitaría render dedicado en el PDF. |
| **Auditoría / Logs** | `MEDICAL_RECORD_CLOSED`, `VACCINE_RECORD_MATERIALIZED_ON_CLOSE` | `views.py:523`, `services.py:64` | Bajo: cada protocolo emite su log al materializar. |
| **Timeline / SidePanel** (display) | Icono/color/badge por tipo | `Timeline.jsx:70`, `SidePanel.jsx:260` | Bajo/display: mapas `TYPE_META`/`CONSULTATION_TYPE_LABELS`. |

**Módulos que NO existen** (declarado explícitamente): **Hospitalización, Cirugías (registro), Recordatorios automáticos, Automatizaciones, API pública, Reportes específicos por tipo**. No hay código de ninguno.

---

## 6. `consultation_type` — auditoría completa

39 archivos mencionan `consultation_type` (grep). Clasificados por uso real:

### 6.1 Escritura
- `MedicalRecordSerializer.Meta.fields` incluye `consultation_type` writable (`serializers.py:188`).
- Frontend: `EvaluationSection.jsx:43` (`onChange({consultation_type})`), enviado en `persistDraft` (`ConsultationForm.jsx:415`).
- Default `general` en creación (`models.py:31`, `ConsultationForm.jsx:131`).

### 6.2 Lógica de negocio (dónde el valor **cambia comportamiento**)
Solo **dos** puntos de lógica real, ambos el mismo condicional (`!= vaccine`):
1. **Backend, skip de treatment en cierre**: `views.py:471` — `if consultation_type != VACCINE:` exige `treatment`.
2. **Frontend, activación de protocolo**: `ConsultationForm.jsx:229` — `protocolFor(draft.consultation_type)` → registry.
3. **Backend, gate del materializador**: `services.py:34` — `if consultation_type != VACCINE: return None`.
4. **Frontend, espejo del skip**: `TreatmentSection.jsx:27` y `validateForClose` (`ConsultationForm.jsx:78`).

### 6.3 Filtros / consultas
- Filtro por tipo en historial: `index.jsx:152-158` (`TYPE_FILTER_MAP`, client-side sobre la página cargada).
- **No hay** query SQL que filtre por `consultation_type` en el backend (el filtro es client-side). El `db_index` de `models.py:32` está subutilizado hoy.

### 6.4 Display / etiquetas (sin lógica)
`apiError.js:6`, `AppointmentQuickModal.jsx:59`, `OperationalFeed.jsx:57`, `SidePanel.jsx:260`, `Timeline.jsx:70`, `views.py:416/627`, `index.jsx:27-40`, `ConsultationForm.jsx:35-40`.

### 6.5 Veredicto de la pregunta "¿protocolo o etiqueta?"
**Ambos, en transición.** Para `general/surgery/emergency` sigue siendo **etiqueta pura** (solo cambia si `treatment` es obligatorio y qué badge se pinta). Para `vaccine` ya es un **protocolo de verdad**: activa UI dedicada, valida, y materializa un registro legal. El discriminador es el mismo campo; lo que difiere es cuánta maquinaria hay detrás de cada valor. Hoy: 1 valor con maquinaria (vaccine), 3 sin ella.

---

## 7. `VaccineRecord` — análisis

### 7.1 Nivel de desacoplamiento
**Bien desacoplado del modelo central**: tabla propia, FK `SET_NULL` a `MedicalRecord` (`models.py:146`), serializer propio, endpoints propios (`urls.py:26-27`), índices analytics propios. `MedicalRecord` no tiene ni un campo de vacuna. Es el **modelo de referencia** de cómo debe verse el registro de un protocolo.

### 7.2 Información que duplica / caminos redundantes
- **Dos caminos de escritura**: (a) materialización en cierre (`services.py:58`, el camino "protocolo"); (b) endpoint directo `POST /api/vaccines/` (`views.py:554-558`). El frontend hoy solo usa el camino (a) (su `api/vaccines.js` es **solo lectura**), pero el POST directo sigue vivo y sin consumidor conocido. **Riesgo de doble fuente** si algún flujo futuro escribe por (b): habría vacunas creadas fuera de una consulta, con `medical_record=null`. No es un bug hoy, es una superficie a vigilar.
- `vaccine_name` es **texto libre** (`models.py:139`); el catálogo de presets (`vaccinePresets.js:17`) es **solo frontend y estático**. No hay tabla de catálogo de vacunas: dos clínicas escriben "Rabia"/"rabia"/"Antirrábica" y el `status`/historial no las agrupa. La agrupación en la ayuda contextual es por `.toLowerCase()` exacto (`VaccineSection.jsx:119-121`).

### 7.3 Información que falta
- **Lote/laboratorio estructurado**: hoy va en `notes` (ADR p50 §Diferido menciona `batch_number` diferido). Cumplimiento NOM real puede exigirlo tipado.
- **FK a catálogo de vacuna** (`vaccine_preset_id`): inexistente; el `preset.id` frontend (`vaccinePresets.js:18`) no se persiste.
- **Vía de administración / dosis / sitio anatómico**: inexistentes.

### 7.4 ¿Problemas de convertirlo en "el protocolo oficial de vacunación"?
Ya **es** el protocolo oficial (ADR p50). No hay conversión pendiente. Lo que falta es **profundizar el modelo** (lote/catálogo/vía) — trabajo aditivo, sin refactor. El único cuidado: si se añade FK a catálogo, decidir qué pasa con los `vaccine_name` de texto libre ya existentes (backfill o convivencia).

---

## 8. Cirugías — análisis

**No existe estructura alguna para procedimientos quirúrgicos.** Verificado:
- No hay modelo `SurgeryRecord` / `Procedure` / equivalente (grep de modelos: solo `MedicalRecord`, `VaccineRecord`, `VitalSigns`, `MedicalRecordService`).
- No hay carpeta `features/consultation/protocols/surgery/` (`registry.js:13` solo mapea `vaccine`).
- `consultation_type='surgery'` (`models.py:17`) hoy **solo** implica: badge/label propio + `treatment` obligatorio en el cierre (`views.py:471`, es `!= vaccine`).

**Todo se guarda como texto libre** en `diagnosis`/`treatment`/`notes` del `MedicalRecord`. **Sin reutilización, sin estructura, sin registro de dominio.** Limitaciones: no hay campos de procedimiento, anestesia, duración, complicaciones, insumos quirúrgicos estructurados, ni consentimiento. Evolucionar cirugía = crear el protocolo desde cero (carpeta frontend + `SurgeryRecord` backend + entrada en registry + `if` en el materializador), siguiendo el molde Vacuna.

---

## 9. Urgencias — análisis

**No existe flujo distinto para urgencias.** Verificado:
- `consultation_type='emergency'` (`models.py:18`) es tratado **idénticamente** a `general`/`surgery` en toda la lógica: `treatment` obligatorio (`views.py:471`, cae en `!= vaccine`), sin protocolo (`registry.js` no lo mapea), sin registro de dominio, sin priorización, sin triage.
- No hay lógica de negocio específica de emergencia en ningún archivo (grep `emergency`/`EMERGENCY`: solo el enum, tests de skip, y labels de display).

**Conclusión**: urgencia es hoy **puramente una etiqueta**. Cambia el badge y nada más. No hay diferencia operativa, temporal ni de captura frente a una consulta general.

---

## 10. Acoplamientos — clasificados

| # | Acoplamiento | Ubicación | Nivel | Nota |
|---|---|---|---|---|
| A1 | Skip de `treatment` duplicado backend↔frontend | `views.py:471` ↔ `ConsultationForm.jsx:78` / `TreatmentSection.jsx:27` | **Medio** | Misma regla en 3 sitios (`!= vaccine` hardcodeado). El backend es autoritativo; el frontend lo espeja. Si un protocolo futuro también salta treatment, hay que tocar los 3. |
| A2 | Materializador con `if consultation_type=='vaccine'` hardcodeado | `services.py:34` | **Medio** | No hay registry backend análogo al frontend. El 2º protocolo agrega otro `if`/branch aquí. ADR p50 §Diferido lo anticipa (extraer a ~4-5 protocolos). |
| A3 | Whitelist de draft manual (`{"vaccine"}`) | `serializers.py:17` | **Bajo** | Se amplía 1 clave por protocolo. Explícito y barato, pero es un segundo lugar (junto a registry) donde "registrar" un protocolo. |
| A4 | Efectos de cierre viven en la **view**, no en un service | `views.py:429-533` | **Medio** (deuda preexistente A3 del propio ADR) | `close_medical_record` orquesta invoice + appointment + protocolo + analytics inline. Un `close_medical_record_service()` no existe. Cuanto más crezca por protocolos, más pesa. |
| A5 | `VaccineSection` importa CSS de la página de consulta | `VaccineSection.jsx:5` (`../../../../pages/medicalRecords/consultationForm.module.css`) | **Bajo-Medio** | El protocolo (feature) depende de estilos de la página. Rompe el aislamiento "carpeta-por-protocolo autocontenida". Copiar la carpeta para un protocolo nuevo arrastra este path frágil. |
| A6 | Dos caminos de escritura a `VaccineRecord` | `services.py:58` + `views.py:554-558` | **Bajo** (latente) | Ver §7.2. Sin consumidor del POST directo hoy; superficie a vigilar. |
| A7 | Contrato de protocolo sin `persistencia`/`hydrate`/`isDirty` | `vaccineProtocol.js:17` | **Bajo** (deliberado) | ADR p50 §Diferido: se agregan cuando un protocolo real los exija. Correcto no anticipar, pero el 2º protocolo probará si el contrato aguanta. |
| A8 | Validación de protocolo se muestra por toast + scroll, no inline | `ConsultationForm.jsx:613-620`, ADR p50 §Deuda | **Bajo** (UX) | `proto.validate` devuelve `{field:[msg]}` pero el error de vacuna se muestra global, no en la sección. |

**No se detectaron dependencias circulares** entre módulos (imports locales usados a propósito, p.ej. `services.py:46` importa el serializer dentro de la función para evitar acoplar import-time; `views.py` importa billing/appointments services localmente).

---

## 11. Riesgos y matriz de impacto

### 11.1 Riesgos por cambio previsible

| Cambio | Qué puede romperse | Módulos | Cómo detectarlo | Mitigación |
|---|---|---|---|---|
| Añadir 2º protocolo (p.ej. cirugía) | El `if` del materializador (`services.py:34`) crece a cadena; whitelist (`serializers.py:17`) desincronizada | medical_records | test de materialización por tipo (existe patrón en `test_consultation_draft.py:106`) | Extraer registry backend antes del 3º (ADR p50 §Diferido) |
| Protocolo que **necesita** métricas | Tentación de leer `consultation_draft` desde analytics → viola invariante ADR p50/p9 | analytics | code review; el scratchpad no tiene anchor | Materializar registro de dominio con su propio anchor (como VaccineRecord) |
| Protocolo que **muta** MedicalRecord (p.ej. campo `next_deworming`) | Viola principio binding (`services.py:20-22`) | núcleo | code review contra el principio | Prohibido por ADR; usar tabla propia |
| Copiar carpeta de protocolo para uno nuevo | Arrastra import CSS frágil (A5) y `maxSuggestions` hardcodeado | frontend | build/render | Extraer estilos compartidos del protocolo a su propio módulo |
| Cambiar shape de `consultation_draft` | Borradores en vuelo (consultas `open` con draft viejo) quedan con forma antigua | frontend/backend | `initDraft` rehidrata con `??` fallback (`vaccineProtocol.js:21`) | El campo es efímero por diseño (`models.py:37` "puede reshaparse sin migración"); tolerar ambas formas en `initDraft` |
| Endurecer `vaccine_name` a FK de catálogo | `vaccine_name` texto libre existente sin match | medical_records | backfill query | Convivencia: mantener texto + FK opcional |

### 11.2 Matriz de impacto (riesgo × severidad)

| Riesgo | Técnico | Funcional | Datos | UX |
|---|---|---|---|---|
| Registry backend inexistente (A2) | **Medio** | Bajo | Nulo | Nulo |
| Efectos de cierre en view (A4) | **Medio** | Bajo | Nulo | Nulo |
| Doble escritura VaccineRecord (A6) | Bajo | **Medio** | **Medio** (huérfanos `medical_record=null`) | Bajo |
| CSS acoplado del protocolo (A5) | Bajo | Nulo | Nulo | Bajo |
| Texto libre en `vaccine_name` | Bajo | **Medio** (historial no agrupa) | **Medio** | Medio |
| Cirugía/urgencia sin estructura | Bajo | **Alto** (dato clínico no capturado) | **Alto** (información se pierde en texto libre) | Medio |

---

## 12. Migración de datos — impacto (NO diseño)

- **Consultas existentes**: 100% compatibles. `consultation_type` se añadió con default `general` (`0012`), `consultation_draft` con default `{}` (`0019`). Ninguna migración retroactiva tocó filas. Las consultas viejas simplemente son `general` con draft vacío.
- **¿Requieren migración?** No para el modelo actual. Un protocolo nuevo con tabla propia (patrón VaccineRecord) es **aditivo puro**: nueva tabla, sin backfill obligatorio. Las consultas históricas de tipo `surgery`/`emergency` que se cerraron con datos en texto libre **no se convertirían** automáticamente a estructura (quedarían como están — convivencia).
- **¿Conviven ambos modelos?** Sí, ya conviven: `general` sin protocolo y `vaccine` con protocolo coexisten hoy sin problema. El discriminador `consultation_type` + registry (`null` para tipos sin protocolo) es exactamente ese mecanismo de convivencia.
- **¿Pérdida de información?** Ninguna por evolucionar. La única "pérdida" conceptual ya ocurrió y es histórica: las cirugías/urgencias viejas guardaron su detalle en texto libre y ahí seguirán. No hay forma segura de estructurar retroactivamente texto libre sin intervención humana.

---

## 13. Cobertura de pruebas

### 13.1 Qué está cubierto
- **Scratchpad `consultation_draft`**: default vacío, roundtrip PATCH/GET, rechazo de claves fuera de whitelist, rechazo de no-dict, rechazo de payload >16KB (`test_consultation_draft.py:39-103`).
- **Materialización Vacuna**: crea VaccineRecord en el atomic (`:140`), general no materializa aunque tenga draft (`:154`), sin `vaccine_name` no materializa (`:164`), draft inválido → rollback del cierre completo (`:173`), sin refuerzo → `next_due_date` null (`:188`), idempotencia (doble close no duplica) (`:197`).
- **Skip de treatment por tipo**: surgery/emergency requieren, vaccine no, general requiere (`test_close.py:210-320`).
- **Frontend protocolo Vacuna**: `vaccineProtocol.test.js`, `vaccinePresets.test.js`, `VaccineSection.test.jsx`.

### 13.2 Qué queda desprotegido
- **`surgery`/`emergency` como protocolos**: no hay tests porque no hay protocolo. Cualquier estructura nueva nace **sin red**.
- **Doble camino de VaccineRecord** (§7.2): no hay test que verifique que el POST directo `/api/vaccines/` no crea inconsistencias / que esté deprecado o restringido.
- **Registro directo con `medical_record=null`**: sin cobertura del caso huérfano.
- **Concurrencia protocolo × cierre**: el materializador confía en el `select_for_update` del MR (`services.py:24-27`); no hay test explícito de carrera close/close simultáneos más allá de idempotencia secuencial.
- **PDF con datos de protocolo**: el PDF no imprime datos de vacuna (`views.py:586-768` no toca `consultation_draft` ni VaccineRecord); no hay test que lo exija.

---

## 14. Deuda técnica (más allá del formulario)

1. **Falta registry backend de protocolos** (espejo de `registry.js`). Hoy `services.py:34` es un `if` único; el materializador debe volverse tabla `{type: materializer}` cuando haya 2-3 protocolos (ADR p50 §Diferido lo dice).
2. **`close_medical_record` sin service** (deuda A3 preexistente, ADR p50 §Deuda, `views.py:429`): la orquestación de efectos de cierre (invoice + appointment + protocolo + analytics + writer de `closed_at`) vive en la view. Debería ser `close_medical_record_service()`. Cada protocolo nuevo la engorda.
3. **Regla `!= vaccine` triplicada** (A1): backend autoritativo + 2 espejos frontend. Si más de un tipo salta treatment, se vuelve frágil. Considerar una propiedad del protocolo (`requiresTreatment`) en el contrato.
4. **Acoplamiento CSS del protocolo a la página** (A5, `VaccineSection.jsx:5`): rompe la promesa de "carpeta autocontenida". Extraer estilos compartidos.
5. **`vaccine_name` texto libre sin catálogo persistente** (§7.2): presets solo-frontend estáticos; sin FK a catálogo → historial no agrupa sinónimos; migración futura a catálogo por-org anticipada pero no hecha (`vaccinePresets.js:1-16`).
6. **Segundo camino de escritura a VaccineRecord** (A6): decidir si el `POST /api/vaccines/` directo se restringe/deprecia o se documenta como flujo legítimo.
7. **Validación de protocolo no-inline** (A8): `proto.validate` retorna `{field:[msg]}` pero se muestra por toast global (ADR p50 §Deuda).
8. **`db_index` de `consultation_type` subutilizado** (`models.py:32`): el filtro por tipo es client-side (`index.jsx:152`); el índice no se aprovecha en queries server-side.

---

## 15. Posibles bloqueadores para la evolución

- **Ninguno estructural.** El andamiaje (registry, contrato, scratchpad, materializador atómico, principio binding) ya existe y está probado con un protocolo real.
- **Bloqueador de gobernanza (no técnico)**: ADR p50 **decidió deliberadamente NO generalizar** el patrón hasta tener 2-3 protocolos reales (§Alcance, §Diferido). Diseñar "el sistema de protocolos genérico" ahora contradice esa decisión explícita. El camino sancionado es: implementar el 2º protocolo copiando el molde Vacuna, **luego** extraer la abstracción cuando se repita el dolor.
- **Bloqueador de producto (decisión de negocio)**: para cirugía/urgencia hay que definir *qué datos clínicos* capturar (procedimiento, anestesia, triage…). Eso es diseño de dominio veterinario, no arquitectura. Sin ese input, no se puede modelar `SurgeryRecord`.
- **Rechazado explícitamente por ADR p50 (no reintentar)**: motor genérico schema-driven JSON (Alt. B), crear el registro legal en modo borrador/lazy (Alt. D), `localStorage` para el borrador (Alt. C), y que el frontend cree el registro con un POST separado tras el cierre (Alt. A, rompe atomicidad).

---

## 16. Oportunidades de refactorización (cuando se implemente el 2º protocolo)

Ordenadas por cuándo conviene tocarlas:

1. **Extraer registry backend** de materializadores: `{ 'vaccine': materialize_vaccine, 'surgery': materialize_surgery }`, iterado en `apply_consultation_draft_on_close`. Elimina el `if` creciente (A2).
2. **Mover efectos de cierre a `close_medical_record_service()`** (cierra deuda A4/A3): view delgada, service orquesta invoice+appointment+protocolo+analytics.
3. **Añadir `requiresTreatment` (o `closeValidation`) al contrato del protocolo**: elimina el `!= vaccine` triplicado (A1). El backend consulta la propiedad del protocolo en vez de hardcodear el tipo.
4. **Desacoplar estilos del protocolo** de la página de consulta (A5): CSS module propio en la carpeta del protocolo.
5. **Ampliar contrato con `hydrate`/`isDirty`** solo si el 2º protocolo lo exige (ADR p50 §Diferido — no anticipar).
6. **Consolidar validación de protocolo inline** en su sección (A8).
7. **Decidir catálogo de vacunas persistente** (tabla + FK) cuando se necesite reporting/agrupación fiable (§7.2).

**Regla de oro (del propio ADR p50)**: no construir la abstracción antes de la tercera repetición. Copiar la carpeta Vacuna + añadir el `if`/branch es aceptable para el 2º protocolo; extraer el registry backend y el service de cierre es el trabajo del 3º.

---

## 17. Conclusión — ¿qué tan preparada está la arquitectura?

**Moderadamente-alta preparación, mayor de lo que sugería la premisa inicial.**

La arquitectura **ya dio el primer paso** hacia protocolos independientes (ADR p50, 2026-07-08) y lo hizo bien:
- El punto de extensión existe (`registry.js`) y es trivial de usar.
- El principio de aislamiento del modelo central está escrito y respetado (`services.py:20-22`): un protocolo no ensucia `MedicalRecord`.
- El registro de dominio del protocolo vive fuera, con FK débil (VaccineRecord) — patrón replicable.
- La materialización es **atómica** (todo-o-nada en el cierre), evitando estados inconsistentes.
- El scratchpad resuelve el reload-survival sin volverse fuente de verdad ni tocar analytics.
- La migración de datos es aditiva pura, sin riesgo de pérdida.

**Lo que falta es profundidad, no cimientos:**
- Backend: no hay registry análogo al frontend; el materializador es un `if` puntual (deliberadamente, según ADR p50). Deuda contenida, no bloqueante.
- `surgery`/`emergency` son cascarones (etiqueta + treatment requerido). Evolucionarlos es green-field **dentro** del andamiaje, no refactor de código acoplado.
- Faltan definiciones de **producto/dominio** (qué capturar en cirugía/urgencia) antes de poder modelar.

**El terreno es firme.** Siguiendo la analogía de mecánica de suelos: el suelo ya soporta una estructura (Vacuna está construida y en pie). La cimentación (registry + contrato + principio binding + materialización atómica) es reutilizable. El riesgo no está en el suelo sino en **construir la abstracción genérica demasiado pronto** — exactamente lo que ADR p50 pidió evitar hasta tener 2-3 edificios levantados. La recomendación arquitectónica es respetar esa secuencia: **implementar el 2º protocolo copiando el molde, medir el dolor real, y solo entonces extraer la abstracción.**

---

## Apéndice A — Referencias de código (índice rápido)

| Concepto | Ubicación exacta |
|---|---|
| enum `ConsultationType` | `backend/apps/medical_records/models.py:14-18` |
| campo `consultation_type` | `models.py:28-33` |
| campo `consultation_draft` + invariante | `models.py:36-46` |
| CHECK `closed ⇒ closed_at` | `models.py:126-129` |
| `VaccineRecord` modelo | `models.py:133-166` |
| whitelist draft | `serializers.py:17` |
| `validate_consultation_draft` | `serializers.py:249-263` |
| `VaccineRecordSerializer` | `serializers.py:370-435` |
| materializador de protocolo | `services.py:15-73` |
| gate `type==vaccine` | `services.py:34` |
| `close_medical_record` (view) | `views.py:429-533` |
| skip treatment por tipo | `views.py:471-483` |
| invoice guard (ADR p30) | `views.py:499-500` |
| appointment complete (ADR p34) | `views.py:506-507` |
| protocolo materialize (ADR p50) | `views.py:515-516` |
| `VaccineRecord` endpoints (POST directo) | `views.py:536-558`, `urls.py:26-27` |
| registry frontend | `frontend/src/features/consultation/protocols/registry.js:13-17` |
| contrato de protocolo | `vaccine/vaccineProtocol.js:17-46` |
| `VaccineSection` (UI) | `vaccine/VaccineSection.jsx:25-235` |
| presets estáticos | `vaccine/vaccinePresets.js:17-64` |
| container: `proto`/`protoSlice` | `ConsultationForm.jsx:229-232` |
| container: monta `proto.Section` | `ConsultationForm.jsx:929-941` |
| container: `handleFinalize` + `proto.validate` | `ConsultationForm.jsx:610-625` |
| tests draft + materialización | `tests/test_consultation_draft.py:39-203` |
| tests skip treatment | `tests/test_close.py:210-320` |
| migración consultation_type | `migrations/0012_add_consultation_type.py` |
| migración consultation_draft | `migrations/0019_medicalrecord_consultation_draft.py` |
| ADR consolidado | `docs/decisions/2026-07-08-p50-vaccine-protocol-consultation-draft.md` |
| doc dominio (§Protocolos) | `docs/modules/medical_records.md:291-337` |
