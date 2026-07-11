# Plan de implementación — Protocolos clínicos de SaaSlyVet (v2)

**Fecha**: 2026-07-09
**Deriva de**: [`diseno-protocolos-clinicos-2026-07-09.md`](diseno-protocolos-clinicos-2026-07-09.md) (🧊 CONGELADO, v2.2).
**Tipo**: plan técnico de ejecución. **NO** contiene código.
**Regla de oro**: cada slice deja la suite **verde** y `manage.py check` limpio. El usuario corre los tests (no lanzar suites en background).

> **v2 (revisión aprobada)**: (1) **Orden por valor de producto, no por estado del código** → `F0 → General → Vacuna → Cirugía → Urgencia`. (2) **Fase 0 reducida al mínimo** (solo `protocol_version`). **`ExamGrid` NO se construye primero** — se hace **inline en General** y se **extrae en la 2ª repetición** (misma filosofía que el registry backend: no abstraer antes de tiempo; hoy no se sabe qué necesitan Cirugía/Urgencia). (3) **Observabilidad** como capa de cada slice. (4) **Fuera de alcance**: rollback de release, feature flags, compatibilidad temporal de UX. (5) **Estructura por verticales completas** (protocolo terminado = 100% funcional). (6) Énfasis en el **riesgo real**: se toca el corazón (`MedicalRecord`) → mapa de dependencias con checklist por módulo.

---

## 1. Estrategia: verticales completas, empezando por el workhorse

**Se ejecuta protocolo por protocolo (vertical completa), no capa por capa.** Al terminar cada slice hay algo **100% funcional**, no un sistema a medio construir.

```
F0 (mínima)  →  GENERAL  →  VACUNA  →  CIRUGÍA  →  URGENCIA
                (modelo·serializer·materialización·UI·PDF·observabilidad·tests
                 + checklist de módulos adaptados)
```

### Por qué **General primero** (cambio vs v1)
El orden v1 (`Vacuna → …`) estaba sesgado por *"Vacuna ya está a medias"* — estado del código, no valor del producto. Pero **General es el 80-90% del uso diario**. Empezar por General valida de golpe, sobre el flujo real: **UX**, **autosave**, **`ExamGrid`**, el **patrón Assessment**, el **PDF** y el **flujo de cierre completo**. Los demás protocolos **heredan** esas decisiones ya probadas. Vacuna, aunque esté a medias, valida un caso pequeño; General valida el sistema.

Trade-off aceptado: General es también el flujo de **mayor blast-radius** (el más usado). Se mitiga con el mapa de dependencias (§3) y tests. Mejor descubrir los problemas de integración/UX en el camino principal ahora que después de construir 3 protocolos de nicho.

### Punto de extracción de la abstracción (sin cambios)
La generalización backend (**registry de materializadores** + **`close_medical_record_service`** + validación de cierre delegada) se **extrae en Cirugía** — la **3ª** implementación real (Vacuna existente + General + Cirugía), respetando ADR p50. General y Vacuna usan `if/elif` incremental; **no** se abstrae antes de tiempo.

---

## 2. Fuera de alcance (se QUITA del plan)

No hay usuarios en producción de esta feature → se elimina complejidad que resuelve problemas inexistentes:

| ❌ Quitado | Por qué |
|---|---|
| **Rollback de release** / plan de reversión | Siempre se puede volver al commit anterior. No se planifica reversión de despliegue. |
| **Feature flags** para esconder protocolos | No hay usuarios a quienes ocultar nada. Se mergea cuando está listo. |
| **Compatibilidad temporal de UX** (dos `ConsultationForm`, dos caminos de cierre) | No existe UX previa que preservar. Se **reemplaza** la interfaz, no se convive. |

**⚠️ Distinción importante — lo que NO se quita**: el **rollback transaccional atómico** del cierre (draft inválido → `ValidationError` → deshace el cierre completo, `test_consultation_draft.py:173`) es **correctness** (append-only, ADR p50), no reversión de release. **Se conserva siempre.**

**Lo que SÍ se conserva pese a no haber usuarios**: **migraciones aditivas bien hechas**. Ya hay consultas demo, fixtures, tests y datos de prueba (`seed_demo_clinic.py`, `_demo_data.py`). Hacerlas aditivas (campos nullable, tablas nuevas, sin backfill destructivo) no cuesta nada y evita romper esos datos.

---

## 3. El riesgo real: se toca el corazón (`MedicalRecord`)

**El riesgo del proyecto NO es la arquitectura, el backend ni React. Es que todo gira alrededor de `MedicalRecord`.** Tocarlo repercute — directa o indirectamente — en muchos módulos. El peligro es terminar con *"el formulario nuevo funciona, pero el Timeline / el PDF / el Dashboard siguen esperando el modelo viejo"*.

**Mapa de dependencias** (qué consume la consulta y qué revisar por protocolo):

```
MedicalRecord
├── Agenda/Appointments   cierre completa cita (complete_appointment_on_record_close, views.py:507)
├── Timeline (frontend)   badge por tipo (Timeline.jsx:70), busca diagnosis/treatment/notes
├── Billing               factura garantizada al cerrar (ADR p30) — agnóstico, VERIFICAR intacto
├── Analytics             anchor closed_at + nuevos (application_date, started_at, arrived_at)
├── Inventory             productos consumidos — agnóstico, VERIFICAR intacto
├── VaccineRecord         extendido (Vacuna)
├── PDF                   documento por protocolo (nuevo render cada uno)
├── Search/Historial      index.jsx busca dx/tx/notes → indexar chief_complaint (General)
├── Dashboard             summary devuelve consultation_type (views.py:416), OperationalFeed REC_TYPE
├── API/Serializers       public_id + *_public_id embeds en registros nuevos
└── Reports/Recordatorios futuros — dejar anchors/campos listos, no implementar
```

**Checklist de módulos adaptados** — se marca por cada slice de protocolo. Un slice **no está hecho** hasta que su fila está completa:

| Módulo | General | Vacuna | Cirugía | Urgencia |
|---|---|---|---|---|
| Timeline (badge + resumen) | ☐ | ☐ | ☐ | ☐ |
| PDF específico | ☐ | ☐ | ☐ | ☐ |
| Dashboard/summary labels | ☐ | ☐ | ☐ | ☐ |
| Search/historial | ☐ | ☐ | ☐ | ☐ |
| Analytics anchor/metric | ☐ | ☐ | ☐ | ☐ |
| API embeds (public_id) | ☐ | ☐ | ☐ | ☐ |
| Billing/Inventory intactos | ☐ | ☐ | ☐ | ☐ |
| Agenda (cierre→cita) | ☐ | ☐ | ☐ | ☐ |

Esto convierte el riesgo abstracto ("tocas todo") en una lista concreta que se tacha.

---

## 4. Fase 0 — Fundación mínima

**Regla**: F0 responde *solo* a "¿qué necesitan **absolutamente todos** los protocolos, y que no se pueda descubrir construyendo el primero?". Casi nada.

**Entregable (solo uno)**
1. **`protocol_version`** — convención: todo registro de acto lo lleva (int, default 1, `editable=False`) desde su primera migración. Es una decisión que **debe** existir antes del primer registro (retro-agregarlo es imposible), así que va en F0. Se aplica al crear el modelo de General.

**Movido FUERA de F0**:
- **`ExamGrid`** → **NO se construye primero**. Se hace **inline dentro de General** (que es el que de verdad lo estrena) y se **extrae** a componente compartido en la **2ª repetición** (probablemente el preop de Cirugía o el ABC de Urgencia). Construirlo antes = abstracción prematura sin saber qué necesitan Cirugía/Urgencia — el mismo error que evita el registry backend.
- **`originated_from`** → se agrega en el slice de **Urgencia** (primer uso real: urgencia→cirugía).
- **Wireframes/pasada UX** → actividad de diseño **dentro de cada slice** (§5).
- **Scaffolding** → el contrato frontend ya existe (`vaccineProtocol.js:17`); se sigue, no se "construye".

**F0 es tan pequeña que se pliega dentro del arranque de General** (la migración de `ConsultationAssessment` ya trae `protocol_version`). No es una fase de infraestructura.

---

## 5. Anatomía de un slice de protocolo (capas de cada vertical)

Cada protocolo recorre **estas capas** hasta quedar 100% funcional:

1. **Modelo + migración** (aditiva, nullable, `organization` scoping, FK `MedicalRecord` SET_NULL, append-only si es legal, `protocol_version`).
2. **Serializer** (valida entrada, `sanitize_text`, tenant guards; ampliar `ALLOWED_CONSULTATION_DRAFT_KEYS` 1 clave).
3. **Materialización** en el cierre, dentro del `atomic()` (patrón `apply_consultation_draft_on_close`); validación de cierre del protocolo.
4. **UI** — `Section` + contrato `{label, Section, initDraft, validate}` + entrada en `registry.js`; **captura mínima real** visible, resto colapsado; Principios UX (§3 diseño).
5. **PDF** específico.
6. **Observabilidad** (§9) — logs estructurados del cierre/materialización.
7. **Tests** (backend + frontend) + **checklist de módulos** (§3) tachado.

> En **Cirugía** (slice 3) la capa 3 incluye **extraer** el registry de materializadores + `close_medical_record_service` + escribir el **ADR de generalización** (el que ADR p50 dejó diferido).

---

## 6. Slice A — GENERAL (primero: valida el sistema)

**Objetivo de producto**: el flujo del 80-90% funcionando end-to-end, sirviendo de molde para los demás.

- **Modelo**: `ConsultationAssessment` (`chief_complaint`, `history`, `exam`, `differentials`, `recheck_date`, `protocol_version`). `MedicalRecord.diagnosis`/`treatment` se conservan.
- **Serializer**: `ConsultationAssessment` + clave `general` en whitelist.
- **Materialización**: rama `elif type=='general'` en `services.py` (aún `if/elif`, sin registry). Cierre **sin cambio de reglas** (dx+tx siguen obligatorios) → slice de menor riesgo en el backend de cierre.
- **UI**: `general/` en `features/consultation/protocols/`; se siente como **conversación**, no 4 cajas SOAP (§10.4 diseño); `chief_complaint` (1 línea) → resto progresivo. **Construye el componente de exploración por sistemas inline** aquí (candidato a extraerse como `ExamGrid` compartido en la 2ª repetición).
- **PDF**: enriquecer "Resumen de consulta" SOAP (`views.py:586`).
- **Módulos**: **Search** indexa `chief_complaint`; **Timeline** muestra motivo; verificar Billing/Agenda intactos.
- **Riesgo**: es el flujo más usado — validar autosave (`ConsultationForm.jsx:414`), draft-survives-reload, y que el Timeline/PDF ya consuman el modelo nuevo antes de cerrar el slice.

---

## 7. Slice B — VACUNA (completar lo de ADR p50)

- **Modelo**: `VaccinationAssessment` (nuevo) + extender `VaccineRecord` (`batch_number`, `manufacturer`, `route`, `anatomical_site`, `immediate_adverse_event`, `vaccine_catalog_id` FK opc., FK opc. a assessment, `protocol_version`) — todo nullable.
- **Serializer**: `VaccinationAssessment` + extender `VaccineRecordSerializer`.
- **Materialización**: `VaccinationAssessment` **siempre**; `VaccineRecord` **si apto**. ⚠️ **1er cambio de reglas de cierre**: Vacuna deja de exigir `diagnosis` — manejar como conditional acotado del protocolo (la delegación completa se extrae en Cirugía).
- **UI**: extender la sección vacuna existente (abre en "¿apto?"; evento adverso; historial).
- **PDF**: **Certificado de vacunación** (solo si se aplicó).
- **Módulos**: `pets.jsx` ya lee VaccineRecord real (ADR p50 §5); PDF certificado; analytics diferimientos/eventos adversos.
- **Nota**: reusa el patrón Assessment y el `ExamGrid` ya validados en General.

---

## 8. Slice C — CIRUGÍA (⭐ punto de extracción + ADR)

- **Modelo**: `SurgeryRecord` (una tabla, grupos PreOp·Proc·Recup; `surgery_type`, `wound_class`, `protocol_version`; append-only).
- **Serializer**: `SurgeryRecord` + clave `surgery`.
- **Materialización + REFACTOR**: **extraer registry backend** `{type: materializer}` (reemplaza `if/elif` de `services.py:34`) + **`close_medical_record_service()`** (deuda A4; view `views.py:429` queda delgada) + **validación de cierre delegada al protocolo** (reemplaza `if != vaccine`, `views.py:471`). **Escribir el ADR de generalización** (registry + close service + delegación + `protocol_version`).
- **UI**: `surgery/` — parte quirúrgico PreOp→Proc→Recup; `surgery_type`, clase de herida.
- **PDF**: **Informe quirúrgico**.
- **Riesgo alto**: el refactor toca el camino crítico del cierre (invoice p30 + appointment p34 + analytics). **Gate**: suites `billing`/`appointments`/`analytics` verdes; cierre sigue garantizando factura y completando cita.

---

## 9. Slice D — URGENCIA

- **Modelo**: `EmergencyRecord` (timestamps, triage, A/B/C, acciones, `discharge_status`, `reassessment_date`, `protocol_version`) + **`MedicalRecord.originated_from`** (movido aquí desde F0: 1er uso real, urgencia→cirugía).
- **Serializer**: `EmergencyRecord` + clave `emergency`.
- **Materialización**: registra su materializador en el **registry ya extraído** en Cirugía. Cierre delegado (dx presuntivo permitido).
- **UI**: cronómetro/triage arriba; **"Evaluación rápida"** (semáforos) que guarda A/B/C por detrás (§13.3 diseño); acciones checklist de un toque.
- **PDF**: **Informe de urgencia**.
- **Módulos**: analytics de tiempos + outcomes por estado al egreso; `originated_from` sin UI aún (solo el enlace de datos).

---

## 10. Observabilidad (capa de cada slice) ⭐ nuevo

El proyecto ya tiene Sentry, logging estructurado JSON, scrubbing (ADR p47, `sentryScrub`). **Cómo saber que los protocolos funcionan en producción**:

**Eventos a emitir** (logger `medical_records.events`, patrón `VACCINE_RECORD_MATERIALIZED_ON_CLOSE`, `services.py:64`):
- `PROTOCOL_MATERIALIZED` — éxito (tipo, record id, duración del cierre).
- `PROTOCOL_VALIDATION_FAILED` — draft/campos inválidos al cerrar (tipo, campo).
- `PROTOCOL_CLOSE_DURATION` — tiempo del `atomic()` de cierre (detectar cierres lentos).
- Rollback de cierre (draft inválido) — ya observable vía el `ValidationError`; loguear el evento.

**Reglas**: nunca loguear PII clínica ni el objeto de error crudo (ADR p47); usar `extra={}` con ids, no contenido. Sentry hereda el scrubbing existente. Es poco código; a seis meses, salva la depuración.

---

## 11. Gates, ADRs y definición de "hecho"

**Gate por slice**: suite verde (`medical_records` + módulos tocados) + `pnpm test` (CI bloqueante) + `manage.py check` + **checklist de módulos (§3) tachado** + migración aditiva aplica sobre datos demo.

**ADRs**:
- **Cirugía**: ADR de generalización (registry + close service + delegación + `protocol_version`).
- **Cambio de negocio** (dropear `diagnosis` en vacuna/urgencia): tests obligatorios; documentar en el ADR de generalización o nota propia.

**Definición de "hecho" (por protocolo)**: modelo+migración · serializer+whitelist · materialización atómica con validación delegada · UI con captura mínima real + UX · PDF · **observabilidad** · tests backend+frontend · **checklist de módulos completo** · docs de dominio actualizados. Invariantes intactos: multi-tenant, append-only, cierre atómico, `MedicalRecord` sin campos de protocolo (salvo `originated_from`), `protocol_version` presente.

---

## 12. Después de los 4 protocolos (no en este ciclo)
- **Soporte**: `MedicalRecordAttachment`; motor de Recordatorios (lee los 4 seguimientos); UI de `originated_from` (cadena de episodio).
- **Hospitalización**: protocolo futuro independiente (fuera de alcance).
- **Reports**: cuando el negocio los pida; los anchors/campos ya quedaron listos.

---

## 13. Resumen de orden de ejecución

```
F0  protocol_version (mínima; se pliega en el arranque de General)
 │
 ├─ GENERAL   (valida sistema: UX·autosave·exploración inline·Assessment·PDF·cierre)  [if/elif]
 ├─ VACUNA    (completa ADR p50: VaccinationAssessment + VaccineRecord+)      [if/elif]
 ├─ CIRUGÍA   (⭐ extrae registry backend + close service + ADR)              [registry]
 └─ URGENCIA  (+ originated_from; usa registry ya extraído)                   [registry]
 │
 └─ soporte (Attachments/Recordatorios/episodio) → Hospitalización (futuro)
```
Cada flecha = un protocolo **100% funcional** (modelo→PDF→observabilidad→módulos adaptados), no un sistema a medio construir.
