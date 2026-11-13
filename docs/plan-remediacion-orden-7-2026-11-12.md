# Orden 7 — Clínica y analítica

Fecha: **12 de noviembre de 2026**. Estado: **PLAN ACORDADO PARA IMPLEMENTACIÓN LOCAL**. Prepara el trabajo de otro agente; no acredita remediación ni despliegue.

Base: [priorización, §7](plan-remediacion-priorizado-2026-10-28.md), [inventario](pendientes-documentados-2026-10-27.md) y decisiones del usuario del 12-11. Ejecución: [expediente y prompts por entrega](remediaciones/orden-7/README.md).

## 1. Decisiones vinculantes

| Tema | Decisión |
|---|---|
| Ejecutor | Claude Sonnet, un prompt autocontenido por entrega y sesión limpia. El usuario revisa entre entregas, igual que en el orden 6. |
| Alcance | Se implementan **M01** (cédula profesional) y **M03** (peso solo en `VitalSigns`). **M02** y **M04** quedan fuera: el usuario excluyó la analítica de la primera versión para clínicas piloto y no se toca ese módulo. **M05** no se seleccionó; su hallazgo queda registrado (§3). |
| Git | Rama nueva `fix/orden-7-clinica` desde `bb5a070` (`develop` tras el orden 6). Un commit por entrega, sin push, PR, merge ni despliegue. |
| Base de datos | Cluster PostgreSQL 18 propio y desechable: `%LOCALAPPDATA%/Temp/opencode/orden7_pg18_20261112`, loopback `127.0.0.1:49937`, mediante `backend/scripts/orden7_isolated.py`. Nunca la base habitual (`localhost:5432`) ni el VPS. |
| Migraciones | Se permiten exactamente tres, escritas en los prompts: `medical_records.0030` (datos), `medical_records.0031` y `users.0012`. Ninguna borra columnas. |
| Frontend | Un cambio acotado en E04: la pantalla de Equipo (`staff.jsx`, `api/staff.js`) y su prueba. |
| M03 | `VitalSigns` pasa a ser la única fuente del peso. Una migración de datos copia `MedicalRecord.weight` donde no hay ningún vital con peso. Nadie lee ni escribe ya la columna; el API sigue publicando `weight`, de solo lectura y derivado de `VitalSigns`. **El `RemoveField` es una entrega posterior** (fase contract), por decisión del usuario. |
| M01, regla | La cédula es **obligatoria para quien firma**, sea cual sea su rol: el veterinario de la consulta al cerrarla, aunque cierre un ADMIN, y quien emite una receta. Obligatoria también para todo `VET` en Equipo. |
| M01, formato | Vacía o solo dígitos, de 5 a 10. No se verifica contra la SEP. CHECK en base de datos. |
| M01, captura | Alta de Equipo y un `PATCH /api/staff/<public_id>/` nuevo, con permiso `staff.update` (sensible, solo ADMIN, en la lista explícita de ADR p63), que solo acepta `specialty` y `license_number`. Sin autoservicio en `/me`. |
| M01, documentos | Se congela al cierre en `MedicalRecord.vet_license_at_close`, junto al nombre y la especialidad. Sale en el PDF de consulta y en la firma de la receta. |
| ADR | Uno nuevo, **p64** (cédula de quien firma), y un addendum a p63 por `staff.update`. M03 se documenta en el módulo, sin ADR. |
| Fuera de alcance | Analítica, el `RemoveField` de `weight`, el PATCH de recetas existentes, la verificación ante la SEP, la base habitual, el VPS, el despliegue y cualquier limpieza no listada. |

## 2. Cobertura de los pendientes

| ID | Prioridad | Entrega | Cierre |
|---|---|---|---|
| M03 | P2 | E01 | Backfill idempotente, lectores y escritores retirados, API de solo lectura. |
| M01 | P2 | E02–E04 | Campo y CHECK, Equipo con alta y edición, firmante con cédula al cerrar y recetar, snapshot y PDF, captura en frontend. |
| M02, M04 | P3 | E05 | Registrados fuera de alcance: analítica excluida del piloto. |
| M05 | P3 | E05 | Registrado fuera de alcance, con el hallazgo de §3. |

## 3. Evidencia de partida

Medido el 12-11-2026 sobre `bb5a070`.

| Fuente | Observación | Implicación |
|---|---|---|
| `medical_records/models.py`, `views.py` | `MedicalRecord.weight` lo leen tres sitios como respaldo: `_get_last_weight`, `get_current_weight` y el PDF de consulta. | M03 retira los tres respaldos. |
| `ConsultationForm.jsx` | El peso se envía solo a `createVitals`, nunca en el PATCH de la consulta. | La columna no tiene escritor en la UI. |
| `pets.jsx`, `petDetail.jsx` | Muestran `rec.weight`, que hoy sale de la columna legacy y está vacía en consultas creadas desde la UI. | Con el campo derivado de `VitalSigns`, el historial muestra el peso real sin tocar el frontend. |
| `seed_demo_clinic` | Es el único escritor de `MedicalRecord.weight`, y ya crea un `VitalSigns` con el mismo valor. | Se quita la línea. |
| `users/models.py` | `User` tiene `specialty`, sin campo para la cédula. ADR p36 la dejó para su Fase 2. | M01 añade `license_number`. |
| `medical_records/services.py` | El cierre ya congela UUID, nombre y especialidad del veterinario (orden 2). | La cédula se congela en el mismo sitio. |
| `Prescription.veterinarian`, `MedicalRecord.veterinarian` | Ambos toman `request.user`, así que un ADMIN también abre consultas y emite recetas. | El firmante, no el rol, es quien necesita la cédula. |
| `users/views.py`, `config/urls.py` | Equipo no tiene edición: solo alta, desactivación y reset de contraseña. `StaffDeactivateView` solo acepta DELETE. | Sin un camino de edición, los usuarios existentes quedarían bloqueados. |
| `billing/models.py`, M05 | El TODO pide `presentation` obligatorio, pero el CHECK `invoiceitem_exactly_one_source` ya exige servicio **o** presentación. Una línea de servicio tiene `presentation` nulo por diseño. Además, `InvoiceItem.service` es `SET_NULL` mientras `CheckoutItem.service` y `MedicalRecordService.service` son `PROTECT`; la protección de estos impide hoy que se llegue a violar el CHECK. | El TODO está obsoleto. No se toca en este orden. |
| `docs/modules/analytics.md`, M02 y M04 | Los dos exigen ADR, ventana dual de 30 días y aprobación del PO. | Excluidos por decisión del usuario. |
| Validación en seco (12-11) | Las cinco entregas aplicadas en un worktree desechable con el código de los propios prompts. Backend: corrida amplia de 852 pruebas OK (skipped=7), frente a 825 en la línea base. Frontend: 851 pruebas OK, lint, build y smoke de URLs. Los bloques se reaplicaron desde los prompts sobre un worktree limpio y dieron el mismo árbol. | Los prompts producen código que compila y pasa. |

## 4. Trampas que los prompts cubren

- `pg_ctl start` con la salida en un pipe no termina nunca: postgres hereda la salida.
- La primera corrida de pruebas crea la base de pruebas (unos 4 minutos). Sin un calentamiento previo, la corrida amplia supera el timeout de 10 minutos.
- Las columnas nuevas en tablas existentes llevan `db_default`, o los ensayos de migración con modelos históricos reciben `NotNullViolation`.
- Las migraciones vienen escritas; `makemigrations --check` debe confirmar que coinciden con los modelos.
- `StaffCreateView` devuelve `serializer.errors` sin el sobre `{code, errors}`; el PATCH nuevo sí lo trae.
- `test_pdf_markup_injection` solo admite ciertos nombres en un `Paragraph`. La cédula entra dentro de `spec`, no en una variable nueva, y no se toca ese gate.
- El candado de firma rompe nueve archivos de pruebas existentes que cierran o recetan con un firmante sin cédula, y el alta de `VET` rompe tres. Solo se les da cédula al firmante: ninguna aserción cambia.
- Uno de esos nueve es de analítica (`test_late_arrival_observability`). Es el único archivo de ese módulo que se toca, y solo en un argumento.
- El frontend necesita `VITE_API_URL` para importar el cliente HTTP, igual que en CI.
- En la prueba de Equipo, el mock de `useAuth` debe devolver un `user` estable: la página recarga en un `useEffect` que depende de él.
- Los archivos de la copia de trabajo usan CRLF. Los bloques se aplican con Edit, sin reescribir archivos enteros.

## 5. Entregas

| Entrega | Contenido |
|---|---|
| E00 | Rama, commit de documentos, cluster aislado, línea base de backend y frontend |
| E01 | M03: `VitalSigns` como única fuente del peso |
| E02 | M01: campo, CHECK, snapshot vacío, Equipo (alta y PATCH), permiso `staff.update` |
| E03 | M01: firmante con cédula al cerrar y recetar, snapshot, PDF, demo |
| E04 | M01: captura en la pantalla de Equipo |
| E05 | ADR p64, addendum p63, documentos operativos, corrida amplia, cierre |

Las entregas van en serie: E03 depende del campo de E02, y E04 del PATCH de E02.

## 6. Verificación y límites

- Cada entrega: pruebas dirigidas en el cluster aislado, `py_compile` de los archivos Python tocados y `makemigrations --check`. Comandos exactos en las [reglas comunes](remediaciones/orden-7/prompts/00-REGLAS-COMUNES.md).
- E00 y E05 ejecutan además la corrida amplia de backend (825 y 852 pruebas) y la suite completa de frontend con lint, build y smoke (846 y 851 pruebas).
- La suite global de backend (más de 4.000 pruebas) solo se acredita en CI cuando el usuario suba la rama.
- Sin datos reales en juego. Los usuarios existentes que firman quedarán bloqueados hasta capturar su cédula; es la consecuencia aceptada de hacerla obligatoria.

## 7. Estado final esperado

M01 y M03 podrán declararse **IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE** con la evidencia de `docs/remediaciones/orden-7/EVIDENCIA.md`. M02, M04 y M05 quedan **FUERA_DE_ALCANCE**. El `RemoveField` de `MedicalRecord.weight` queda pendiente. Nada de esto acredita despliegue.

## 8. Revisión entre entregas

1. El reporte trae `COMPLETA`, un hash de commit y la salida real de las pruebas.
2. `git show --stat HEAD` solo contiene archivos que el prompt autoriza.
3. Ninguna prueba se borró ni debilitó, salvo las dos de `test_vitals.py` que fijaban el respaldo retirado en E01.
4. Bajo `migrations/` solo aparecen las tres migraciones del orden, cada una en su entrega.
