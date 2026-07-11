# Diseño definitivo — Protocolos clínicos de SaaSlyVet (v2.2)

**Fecha**: 2026-07-09
**Estado**: 🧊 **CONGELADO** (2026-07-09). Dominio cerrado; no seguir refinando. Cambios futuros solo por evidencia de implementación, vía ADR. Plan de ejecución: [`plan-implementacion-protocolos-clinicos-2026-07-09.md`](plan-implementacion-protocolos-clinicos-2026-07-09.md).
**Tipo**: Diseño de dominio (propuesta final única). **NO** es implementación, no es código, no es migración.
**Base**: estudio `docs/analisis-arquitectura-protocolos-clinicos-2026-07-09.md` + ADR p50 (Vacuna) + conclusiones clínicas + revisiones de producto (v2, v2.1, v2.2).
**Alcance**: modelo definitivo de **General, Vacuna, Cirugía, Urgencia**, listo para plan de implementación.

> **v2.2 (refinamientos sobre v2.1)**: (a) **Sesgo value-first**: se prioriza *"¿qué campos cambian el valor del expediente?"* sobre *"¿qué sería ideal guardar?"* — cada protocolo declara su **captura mínima real** (el camino del 90%). (b) **Capítulo de Principios UX** (§3, no negociables) — SaaSlyVet compite por experiencia, no por arquitectura. (c) **Versionado de protocolo** (`protocol_version`, §7). (d) Precisión conceptual: encuentro → **intención clínica** → (opcional) registro legal derivado; `VaccineRecord` es **consecuencia legal**, no un segundo acto (§2, §11). (e) Cirugía: **tipo de cirugía** (electiva/programada/urgencia/emergencia). (f) Vacuna: **evento adverso inmediato**. (g) Urgencia: UI **"Evaluación rápida"** que guarda A/B/C por detrás. (h) **`ExamGrid` primero** en el roadmap.
> **v2.1**: definición de `MedicalRecord`=encuentro; `GeneralExam`→`ConsultationAssessment`; `VaccinationAssessment`; estado al egreso; clasificación de herida; motivo≠historia.

---

## 1. Principios de dominio (leer primero)

1. **Un protocolo representa un acto médico.** No una pantalla, ni un formulario, ni un tipo de consulta.
2. **Cada protocolo registra solo lo necesario para documentar ese acto.** Ni de más ni de menos.
3. **Componentes compartidos evitan duplicar implementación; NO implican mismo significado clínico.** *Reutilizar UI ≠ reutilizar modelo.*
4. **`MedicalRecord` es el ENCUENTRO; los registros especializados son los ACTOS.** (§2.)
5. **El acto define el flujo; el flujo define los campos.**
6. **El expediente vale por lo que se USA, no por lo que se podría llenar.** ⭐ (v2.2) Antes de agregar un campo: *¿cambia el valor del expediente, o solo "sería ideal"?* Un veterinario ocupado escribe una línea por concepto (`Vómito / hace 2 días / dolor abdominal / gastroenteritis / omeprazol`). El diseño optimiza **ese** camino (la mayoría), no el exhaustivo (la excepción). Todo lo que no es el mínimo real es **recomendado u opcional**, nunca fricción obligatoria.

---

## 2. ¿Qué es un `MedicalRecord`? (definición explícita)

**`MedicalRecord` = un ENCUENTRO CLÍNICO (una atención)**: una interacción documentada paciente↔clínica, con **una intención clínica principal** (`consultation_type`), **un** cierre, **un** ancla (`closed_at`), a lo sumo **una** cita y **una** factura.

Cadena conceptual (v2.2):
```
Un encuentro (MedicalRecord)
   → una intención clínica (el acto: valorar / vacunar / operar / estabilizar)
       documentada en su registro: ConsultationAssessment / VaccinationAssessment /
       SurgeryRecord / EmergencyRecord
   → (opcional) un registro LEGAL DERIVADO (VaccineRecord)
```

**Precisión (v2.2)**: `VaccineRecord` **no es un segundo acto médico** dentro del encuentro. Es la **consecuencia legal** de la intención "vacunar" cuando efectivamente se aplica el biológico. Un encuentro = una intención clínica; el registro legal es su derivado, no otro acto.

**Episodio de atención** = agrupación de **varios encuentros** por un mismo proceso (`urgencia → cirugía → hospitalización`). **NO es un `MedicalRecord`**: vive *encima* (`originated_from` hoy → `ClinicalEpisode` futuro, §8).

**Por qué esta definición**: la estructura actual (un `consultation_type`, un cierre, un `closed_at`, una cita, una factura — `models.py:9-130`) **ya es** un encuentro. Meterle varios actos rompería el type único, el cierre por-protocolo y los anchors. Proceso multi-acto = varios encuentros enlazados, no un registro gigante.

---

## 3. Principios UX (no negociables) ⭐ v2.2

> El documento es sólido en arquitectura. Pero **SaaSlyVet compite por experiencia, no por arquitectura.** Estos principios pesan tanto como el modelo.

1. **Un clic siempre mejor que escribir.** Enums, toggles, chips antes que texto libre.
2. **No pedir la misma información dos veces.** Vitales capturados alimentan la exploración; el motivo de la cita pre-llena el motivo de la consulta.
3. **Mostrar primero lo crítico; esconder lo raro.** Lo obligatorio arriba y visible; lo excepcional detrás de "más opciones".
4. **Todo el acto capturable en < 2 minutos.** Si el camino mínimo tarda más, el diseño falló.
5. **El protocolo nunca interrumpe la atención.** Autosave (existe); nada bloquea hasta el cierre; el vet documenta *mientras* atiende, no *después*.
6. **El formulario se siente como el acto, no como el esquema.** SOAP no son cuatro cajas; urgencia no es un formulario clínico frío (§17).

Estos principios se aplican en el diseño de interacción de cada protocolo (§17) y anteceden a cualquier decisión de campos.

---

## 4. Arquitectura de dos capas

```
┌───────────────────────────────────────────────────────────────────┐
│  NÚCLEO TRANSVERSAL  (mismo SIGNIFICADO en los 4)                   │
│  Identidad · VitalSigns · Cargos · Receta · Adjuntos* · Notas       │
└───────────────────────────────────────────────────────────────────┘
                              │  registry.protocolFor(consultation_type)
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│  ACTO ESPECÍFICO  (modelo propio — NO compartido)                   │
│  General  → ConsultationAssessment                                  │
│  Vacuna   → VaccinationAssessment → (si se aplica) VaccineRecord      │
│  Cirugía  → SurgeryRecord   (Preoperatorio · Procedimiento · Recuperación)│
│  Urgencia → EmergencyRecord (Triage · ABC · Tiempos · Estado al egreso)│
└───────────────────────────────────────────────────────────────────┘
*  = NUEVO.
```

**Transversal de verdad**: identidad, vitales crudos, cargos, receta, adjuntos, notas.
**NO transversal**: exploración/valoración y seguimiento → viven en el acto.

---

## 5. Núcleo transversal

| Componente | Hoy | Fuente de verdad |
|---|---|---|
| Identidad paciente | Existe | `Pet`/`Owner` |
| **VitalSigns** | Existe (`models.py:169`) | `VitalSigns` (append-only) |
| Cargos (productos+servicios) | Existe | `MedicalRecordProduct`/`Service` → `InvoiceItem` |
| Receta | Existe | `Prescription` |
| **Adjuntos** ⭑ | No existe | `MedicalRecordAttachment` (1:N) |
| Notas | Existe | `MedicalRecord.notes` |

La **medición cruda** de vitales es transversal; la **interpretación** por sistemas NO (va en el acto, §6).

---

## 6. UI compartida ≠ modelo compartido

Exploración: mismo componente visual, esquemas distintos.

| Acto | Valoración | Qué evalúa |
|---|---|---|
| General (familia diagnóstica) | `ConsultationAssessment` | exploración por sistemas (SOAP·O) |
| Vacuna | `VaccinationAssessment` | apto/no apto |
| Cirugía | grupo PreOp de `SurgeryRecord` | evaluación preoperatoria + ASA |
| Urgencia | grupo ABC de `EmergencyRecord` | triage + ABC |

Un **`ExamGrid`** compartido (filas por sistema, arranca "normal", solo lo alterado pide texto), parametrizado por acto. Cero `PhysicalExam` universal.

Seguimiento — mismo widget, significados distintos: revisión (`ConsultationAssessment.recheck_date`) · refuerzo (`VaccineRecord.next_due_date`) · retiro de puntos (`SurgeryRecord.suture_removal_date`) · revaloración (`EmergencyRecord.reassessment_date`). Un motor de Recordatorios futuro los lee; no requiere objeto único.

---

## 7. Versionado de protocolo ⭐ v2.2

**Problema a 5 años**: si dentro de dos años cambia el esquema de Cirugía, ¿cómo se interpretan las cirugías viejas?

**Decisión**: cada registro de acto lleva **`protocol_version`** (entero, default 1). Congela con qué versión del protocolo se capturó el registro.

- Se agrega **desde el día 1** de cada registro (`ConsultationAssessment`, `VaccinationAssessment`, `SurgeryRecord`, `EmergencyRecord`, `VaccineRecord`). Retro-agregarlo es **imposible**: los registros viejos no sabrían su versión.
- Costo hoy: una columna. Valor a 5 años: enorme.
- PDF y analítica pueden ramificar por versión cuando el esquema evolucione (un informe quirúrgico v1 no muestra campos que no existían).
- **No** se necesita hoy funcionalmente; se agrega por previsión — como los anchors `*_source` ya existentes en el proyecto.

---

## 8. Relación entre encuentros — episodio

`Urgencia → Cirugía → Hospitalización` = proceso con varios actos. Cada acto = **un `MedicalRecord`**. Se relacionan con FK autorreferencial **nullable** `MedicalRecord.originated_from` (`SET_NULL`): el encuentro de cirugía apunta al de la urgencia.

Se **define ahora** (nullable, sin uso obligatorio); la UI de cadena se implementa después. Futuro: `ClinicalEpisode` si las cadenas se alargan. **Único campo nuevo en el modelo central, estructural.**

---

## 9. Patrón de materialización (actos con registro propio)

```
Captura (sección del acto) → consultation_draft[type]  (scratchpad, whitelist)
        ▼  autosave reusado
Cierre (close_medical_record, UN transaction.atomic())
        1. valida el draft con el serializer del protocolo
        2. materializa {Acto}Record (actor + org + protocol_version, server-side)
        3. draft inválido → ValidationError → rollback
        ▼
{Acto}Record  (fuente de verdad, con anchor + protocol_version)
```

Habilitante (al 2º protocolo): registry backend de materializadores (reemplaza el `if consultation_type=='vaccine'`, `services.py:34`); ampliar `ALLOWED_CONSULTATION_DRAFT_KEYS` a `{"general","vaccine","surgery","emergency"}` (`serializers.py:17`).

---

## 10. Protocolo GENERAL (familia diagnóstica — SOAP)

### 10.1 Objetivo
Llegar a un diagnóstico y definir un plan.

### 10.2 Captura mínima real (el 90%) ⭐
**Motivo (1 línea) → Diagnóstico → Tratamiento.** Nada más es obligatorio. Ejemplo real: *"Vómito / Gastroenteritis / Omeprazol"*. Historia, exploración, diferenciales, revisión = **recomendados u opcionales**, colapsados por defecto. El vet ocupado cierra en < 30s; el que quiere detallar, puede.

### 10.3 Flujo y campos

| Campo | Clasif. | Estructura | Home |
|---|---|---|---|
| **Motivo principal** (chief complaint) | **Obligatorio** | Texto 1 línea (indexable) | `ConsultationAssessment.chief_complaint` |
| Historia / anamnesis | Opcional | Texto | `ConsultationAssessment.history` |
| Signos vitales | Recomendado | Estructurado | `VitalSigns` |
| Exploración por sistemas | Opcional | `ExamGrid` | `ConsultationAssessment.exam` |
| **Diagnóstico** | **Obligatorio** al cerrar | Texto (+ `presuntivo`/`definitivo` opc.) | `MedicalRecord.diagnosis` |
| Diferenciales | Opcional | Texto | `ConsultationAssessment.differentials` |
| **Plan / tratamiento** | **Obligatorio** al cerrar | Texto | `MedicalRecord.treatment` |
| Receta / cargos | Opcional | Estructurado | Núcleo |
| Próxima revisión | Opcional | Fecha | `ConsultationAssessment.recheck_date` |

**Motivo ≠ Historia**: motivo = 1 frase **buscable**; historia = narrativa. Separarlos acelera la búsqueda posterior.

### 10.4 UX — no se ve como SOAP ⭐
El formulario **no** son cuatro bloques enormes rotulados S/O/A/P. Se siente como **una conversación**: una línea de motivo, y el resto aparece según se escribe. SOAP es la *estructura de datos*, no la *interfaz*. (Ver §17.)

### 10.5 Cierre / registro / PDF / analítica
- Cierre: `diagnosis` + `treatment` (mantiene reglas actuales).
- Registro: **`ConsultationAssessment`** (NUEVO) — `medical_record` (SET_NULL), `pet`, `org`, `assessed_by`, `chief_complaint`, `history`, `exam`, `differentials`, `recheck_date`, `protocol_version`. **Solo la familia diagnóstica** (general + futuros control/revisión/dermatología comparten este modelo; el nombre no se ata al examen físico).
- PDF: "Resumen de consulta" SOAP (enriquece `views.py:586`).
- Analítica: consultas por periodo; **motivos frecuentes** (chief complaint indexado); cumplimiento de revisión. Anchor `MedicalRecord.closed_at`.

---

## 11. Protocolo VACUNA (procedimiento preventivo)

### 11.1 Objetivo
Decidir aptitud y, de aplicar, dejar el registro legal. **Decidir NO vacunar también es un acto** que debe registrarse.

### 11.2 Captura mínima real ⭐
**Apto=sí → vacuna + lote + fecha.** Eso cierra. (El mínimo es también el mínimo **legal**.) Fabricante, zona, refuerzo, recomendaciones = recomendados/opcionales.

### 11.3 Intención clínica y derivado legal
- **`VaccinationAssessment`** = la **intención clínica** (apto/no apto + valoración). Se materializa **SIEMPRE**.
- **`VaccineRecord`** = **consecuencia legal derivada** (no un segundo acto). Solo si `apto=true` y se aplicó.
- Caso que hoy se pierde: *cachorro con fiebre → no se vacuna* → queda `VaccinationAssessment(apto=false, motivo="fiebre 39.8")`, sin `VaccineRecord`.

### 11.4 Campos

| Campo | Clasif. | Estructura | Objeto |
|---|---|---|---|
| Apto para vacunar | **Obligatorio** | Booleano | `VaccinationAssessment` |
| Motivo si NO apto | **Obligatorio si no apto** | Texto | `VaccinationAssessment` |
| Vacuna (nombre) | **Obligatorio si apto** | Enum catálogo + "Otra" | `VaccineRecord` |
| Lote / batch | **Obligatorio si apto** (legal) | Campo propio | `VaccineRecord` |
| Fecha de aplicación | **Obligatorio si apto** | Fecha (no futura) | `VaccineRecord` |
| Veterinario | **Obligatorio si apto** | FK User server-side | `VaccineRecord` (`applied_by`) |
| Vía de administración | Recomendado | Enum (`SC`/`IM`/`intranasal`/`oral`) | `VaccineRecord` |
| Fabricante / laboratorio | Recomendado | Texto (o FK) | `VaccineRecord` |
| Zona anatómica | Recomendado | Enum | `VaccineRecord` (trazabilidad sarcoma felino) |
| **Evento adverso inmediato** ⭐ | Recomendado | Enum (`ninguno`/`dolor`/`inflamación`/`anafilaxia`/`otro`+texto) | `VaccineRecord` |
| Refuerzo | Recomendado | Fecha (`>` aplicación) | `VaccineRecord` (`next_due_date`) |
| Recomendaciones | Opcional | Texto | `VaccineRecord` |

**Evento adverso inmediato (v2.2)**: no porque sea frecuente — porque **legalmente puede ser útil** y habilita farmacovigilancia (evento × vacuna × lote).

### 11.5 Cierre — ⚠️ cambio
NO exigir `diagnosis`/`treatment` (hoy `diagnosis` obligatorio, `views.py:458`). Exigir decisión de aptitud; si apto → vacuna válida; si no apto → motivo. Materializa `VaccinationAssessment` siempre, `VaccineRecord` condicional.

### 11.6 Registros / PDF / analítica
- `VaccinationAssessment` (NUEVO, `protocol_version`). `VaccineRecord` (extender: `batch_number`, `manufacturer`, `route`, `anatomical_site`, `immediate_adverse_event`, `vaccine_catalog_id` FK opc., FK opc. a assessment, `protocol_version`; **append-only**).
- PDF: **Certificado de vacunación** (solo si se aplicó).
- Analítica: vacunas aplicadas; **tasa de diferimiento + motivos**; **eventos adversos**; cobertura; refuerzos vencidos; ventana de próximos. Anchors `application_date`, `assessed_at`.

---

## 12. Protocolo CIRUGÍA

### 12.1 Objetivo
Ejecutar y documentar un procedimiento con trazabilidad de riesgo, hallazgos, complicaciones y postoperatorio.

### 12.2 Captura mínima real ⭐
**Dx prequirúrgico + procedimiento + tipo de cirugía + ASA + complicaciones + indicaciones postop.** El resto (anestesia detallada, tiempos, herida) recomendado.

### 12.3 Flujo — grupos (una tabla)
```
PREOPERATORIO  Dx prequir → tipo de cirugía → ASA → ayuno → valoración preop
PROCEDIMIENTO  anestesia → cirujano → tiempos → procedimiento → clase de herida → hallazgos → complicaciones
RECUPERACIÓN   estado → indicaciones postop → retiro de puntos
```

### 12.4 Campos

| Grupo | Campo | Clasif. | Estructura |
|---|---|---|---|
| PreOp | Diagnóstico prequirúrgico | **Obligatorio** | Texto |
| PreOp | **Tipo de cirugía** ⭐ | **Obligatorio** | Enum (`electiva`/`programada`/`urgencia`/`emergencia`) |
| PreOp | Clasificación ASA | **Obligatorio** | Enum ASA I–V (+E) |
| PreOp | Peso | **Obligatorio** | Numérico (`VitalSigns`) |
| PreOp | Ayuno / laboratoriales | Recomendado/Opc. | Booleano+horas / adjunto |
| PreOp | Valoración preoperatoria | Recomendado | `ExamGrid` |
| Proc | Tipo de anestesia | **Obligatorio** | Enum (`general`/`locorregional`/`sedación`/`local`) |
| Proc | Procedimiento realizado | **Obligatorio** | Texto (o FK catálogo) |
| Proc | Cirujano | **Obligatorio** | FK User server-side |
| Proc | Fármacos+dosis / ayudante / tiempos | Recomendado/Opc. | Estructurado/texto/timestamps |
| Proc | **Clasificación de herida** | Recomendado | Enum (`limpia`/`limpia-contaminada`/`contaminada`/`sucia`) |
| Proc | Hallazgos | Recomendado | Texto |
| Proc | Complicaciones | **Obligatorio** (aunque "ninguna") | Enum + texto |
| Recup | Estado de recuperación | Recomendado | Enum |
| Recup | **Indicaciones postoperatorias** | **Obligatorio** | Texto (+ receta) |
| Recup | Retiro de puntos / consentimiento | Recomendado | Fecha / adjunto |

**Tipo de cirugía (v2.2)**: electiva vs emergencia tienen outcomes y riesgos distintos → **eje de analytics y de reportes**.

### 12.5 Cierre / registro / PDF / analítica
- Cierre: prequir + tipo + ASA + anestesia + procedimiento + complicaciones + postop.
- Registro: **`SurgeryRecord`** (NUEVO, una tabla PreOp·Proc·Recup, `surgery_type`, `wound_class`, `protocol_version`; **append-only**).
- PDF: **Informe quirúrgico**.
- Analítica: cirugías por tipo/procedimiento; **tasa de complicaciones**; **ISQ por clase de herida**; ASA; tiempo de quirófano; mortalidad; por cirujano. Anchor `started_at`.

---

## 13. Protocolo URGENCIA

### 13.1 Objetivo
**Estabilizar**. Gira alrededor del **tiempo** y del **outcome**.

### 13.2 Captura mínima real ⭐
**Llegada + triage + evaluación rápida + acciones + estado al egreso.** Diagnóstico puede quedar presuntivo.

### 13.3 UX — "Evaluación rápida", ABC por detrás ⭐ v2.2
Muchos veterinarios pequeños **no documentan en ABC formal**. La UI muestra una **"Evaluación rápida"** amable (semáforos/estado general) y **guarda por detrás** `airway_status` / `breathing_status` / `circulation_status`. El clínico avanzado ve ABC; el generalista ve "¿cómo llega el paciente?". Mismo dato estructurado, dos idiomas.

### 13.4 Campos

| Campo | Clasif. | Estructura |
|---|---|---|
| **Hora de llegada** | **Obligatorio** | Timestamp |
| **Hora de triage** | **Obligatorio** | Timestamp |
| Hora 1ª atención / estabilización / egreso | Recomendado | Timestamps |
| Nivel de triage | **Obligatorio** | Enum 5 niveles (colores) |
| Evaluación rápida → A / B / C | **Obligatorio** | Enums (guardados como A/B/C) + FR/FC/TLLC/mucosas (reusa `VitalSigns`) |
| Problema principal | **Obligatorio** | Texto |
| Acciones de estabilización | **Obligatorio** | Checklist (O2/fluidos/RCP/hemostasia/analgesia…) + texto |
| Respuesta | Recomendado | Enum |
| Diagnóstico | Recomendado (presuntivo/pendiente OK) | Texto + flag |
| Tratamiento definitivo | Recomendado | Texto + receta |
| **Estado al egreso** | **Obligatorio** | Enum (`alta`/`hospitalización`/`referido`/`fallecido`) |
| Revaloración | Opcional | Fecha |

### 13.5 Cierre / registro / PDF / analítica
- Cierre ⚠️: `arrived_at` + `triage_level` + evaluación (ABC) + acciones + **estado al egreso**. `diagnosis` presuntivo permitido.
- Registro: **`EmergencyRecord`** (NUEVO, timestamps, triage, A/B/C, acciones, `discharge_status`, `reassessment_date`, `protocol_version`; **append-only**). `discharge_status=hospitalización` → encadena con Hospitalización futura vía `originated_from`.
- PDF: **Informe de urgencia**.
- Analítica: volumen por hora; distribución de triage; **puerta→triage / puerta→médico / tiempo a estabilizar / estancia**; **outcomes por estado al egreso** (mortalidad, hospitalización, referencia, alta). Anchor `arrived_at`.

---

## 14. Reglas de cierre — comparativa

| Tipo | Hoy | Propuesto |
|---|---|---|
| General | diagnosis + treatment | Igual (+ motivo; exploración opcional) |
| Vacuna | diagnosis req; treatment NO | dx/tx **NO**; decisión de aptitud (+ vacuna si apto) |
| Cirugía | diagnosis + treatment | prequir + tipo + ASA + anestesia + procedimiento + complicaciones + postop |
| Urgencia | diagnosis + treatment | dx **presuntivo OK**; llegada+triage+ABC+acciones+estado al egreso |

⚠️ Vacuna y Urgencia dejan de exigir `diagnosis`. `close_medical_record` **delega la validación al protocolo activo**. Sin pérdida de datos.

---

## 15. Impacto en el modelo central

**NO se toca**: sin campos de acto. Conserva `consultation_type`, `consultation_draft`, `diagnosis`, `treatment`, `notes`, `weight`, `status`, `closed_at`.

**Fuera del central**: `MedicalRecordAttachment`; registros de acto (`ConsultationAssessment`, `VaccinationAssessment`, `SurgeryRecord`, `EmergencyRecord`) + `VaccineRecord` extendido — **todos con `protocol_version`**; enlace `MedicalRecord.originated_from` (**único campo nuevo en el central, estructural**); whitelist scratchpad → 4 claves; registry backend de materializadores.

---

## 16. Hospitalización — fuera de alcance
NO forma parte de Urgencia. Protocolo **independiente futuro**. No se diseña aquí. Gancho preparado: `originated_from` (`discharge_status=hospitalización` enlazará al registro futuro).

---

## 17. Experiencia de captura — qué VE el veterinario

Aplicación por acto de los principios UX (§3):
- **General** se captura como **conversación**, no como SOAP en cuatro cajas: motivo (1 línea) → el resto aparece si hace falta.
- **Vacuna** abre en "¿es apto?" + bloque de aplicación; nunca un diagnóstico que no aplica.
- **Urgencia** muestra cronómetro/triage arriba y **"Evaluación rápida"** (semáforos), ABC por detrás; acciones como checklist de un toque (se captura con una mano).
- **Cirugía** se lee como parte quirúrgico (PreOp→Proc→Recup).
- **Valoración por sistemas** (`ExamGrid`) de un toque: arranca "normal", solo lo alterado pide texto.

**Recomendación**: antes de programar, una pasada de diseño de interacción por protocolo respondiendo *"¿qué ve y toca el veterinario en cada segundo?"* — el modelo soporta cualquier interacción; la interacción se diseña aquí, no en el esquema.

---

## 18. Matriz resumen

| Protocolo | Registro de acto | Captura mínima | ¿Legal? | PDF | Anchor |
|---|---|---|---|---|---|
| General | `ConsultationAssessment` ⭑ | motivo+dx+tx | No | Resumen SOAP | `closed_at` |
| Vacuna | `VaccinationAssessment` ⭑ → `VaccineRecord` (ext.) | apto+vacuna+lote+fecha | Sí (si aplica) | Certificado | `application_date` |
| Cirugía | `SurgeryRecord` ⭑ | prequir+tipo+ASA+proc+complic+postop | Sí | Informe quirúrgico | `started_at` |
| Urgencia | `EmergencyRecord` ⭑ | llegada+triage+eval+acciones+egreso | Sí | Informe de urgencia | `arrived_at` |

Todos los registros: `protocol_version`. Transversales: identidad · VitalSigns · Cargos · Receta · Adjuntos⭑ · Notas. Encuentro=`MedicalRecord` (§2); episodio=`originated_from` (§8).

---

## 19. Orden de dominio recomendado

0. **`ExamGrid` primero** ⭐ — componente visual compartido de exploración por sistemas. Lo reutilizan **los cuatro** protocolos; construirlo antes ahorra muchísimo código y unifica la UX de valoración desde el inicio.
1. **Vacuna+** — `VaccinationAssessment` + extender `VaccineRecord` (lote/fabricante/vía/zona/evento adverso/catálogo) + certificado + relajar cierre. Ya a medias; captura el "no apto".
2. **Cirugía** — 2º protocolo. Aquí se **extrae el registry backend** + `close_medical_record_service` (deuda A4). Introduce `surgery_type` + clase de herida.
3. **Urgencia** — 3º. Timestamps + estado al egreso + "Evaluación rápida".
4. **General (SOAP)** — `ConsultationAssessment`; reusa `ExamGrid`.
5. **Transversales de soporte** (`Adjuntos`, Recordatorios, UI de episodio).
6. **Hospitalización** — protocolo futuro.

---

## 20. Decisiones abiertas (input de negocio)
1. Catálogo de vacunas persistente (Rec.: tabla+FK).
2. Motor de recordatorios (Rec.: capturar fechas ahora).
3. Adjuntos: storage v1 o diferir (Rec.: diferir salvo consentimiento).
4. Escala de triage: confirmar 5 niveles con piloto.
5. Catálogo de procedimientos (Rec.: texto libre v1).
6. Enlace de episodio: `originated_from` v1 (Rec.: sí).

---

## 21. Conclusión

Una sola arquitectura para cuatro actos: núcleo transversal + acto específico con su propio modelo, valoración, seguimiento, PDF, anchor y **`protocol_version`** — porque *reutilizar UI no es reutilizar significado*. La raíz quedó explícita: **`MedicalRecord` = encuentro** (una atención); dentro, **una intención clínica**; de ella, **opcionalmente**, un **registro legal derivado** (`VaccineRecord` no es un segundo acto). El episodio agrupa encuentros por encima. Pero el diseño ya no se mide solo por el modelo: se mide por **cuánto puede capturar un veterinario sin odiar el sistema**. Por eso cada protocolo declara su **captura mínima real** (una línea por concepto en General), los **Principios UX** pesan tanto como el esquema, y `ExamGrid` va primero. SaaSlyVet compite por experiencia — el modelo la habilita, no la reemplaza.
