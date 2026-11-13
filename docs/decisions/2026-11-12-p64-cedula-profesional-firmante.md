# ADR p64 — Cédula profesional de quien firma

**Fecha**: 2026-11-12
**Estado**: **ACEPTADO** (decisiones del usuario, 12-11-2026). Implementado localmente en el orden 7 ([expediente](../remediaciones/orden-7/README.md)); sin despliegue.
**Pendiente**: M01 ([inventario](../pendientes-documentados-2026-10-27.md), [plan del orden 7](../plan-remediacion-orden-7-2026-11-12.md)).

## Contexto

La receta y el PDF de consulta llevaban el nombre y la especialidad del veterinario, pero no su cédula profesional. `User` no tenía dónde guardarla. ADR p36 la dejó para su Fase 2 como `User.license_number`.

`MedicalRecord.veterinarian` y `Prescription.veterinarian` toman el valor de `request.user`, así que un ADMIN que atiende también abre consultas y emite recetas, y aparece como su firmante.

## Decisión

1. **Campo.** `User.license_number`: vacío o solo dígitos, de 5 a 10. No se verifica contra el registro de la SEP. Un CHECK en base de datos (`user_license_number_digits`) rechaza otro formato.
2. **La exige quien firma, sea cual sea su rol.** Cerrar una consulta exige cédula al veterinario de la consulta, no a quien pulsa cerrar. Emitir una receta (`POST /api/prescriptions/`) se la exige a quien la emite. Sin ella, `400` con `errors.license_number`.
3. **Obligatoria para todo `VET`** en el alta de Equipo y en su edición. Para los demás roles es opcional, pero un ADMIN sin cédula no puede firmar.
4. **Se congela al cierre** en `MedicalRecord.vet_license_at_close`, junto al nombre y la especialidad (snapshot del orden 2). Los PDF de documentos cerrados la leen de ahí; los abiertos, del usuario vivo.
5. **Captura.** El alta de Equipo la acepta. Para los usuarios existentes hay un `PATCH /api/staff/<public_id>/` nuevo, con el permiso `staff.update` (sensible, solo ADMIN, añadido a la lista explícita de ADR p63). Solo acepta `specialty` y `license_number`; cualquier otra clave es `400`.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| Exigirla solo al rol `VET` | Las recetas y consultas firmadas por un ADMIN que atiende saldrían sin cédula. |
| Opcional | No cambia nada de lo que falta en los documentos. |
| Leerla siempre del usuario vivo | Una receta ya emitida cambiaría al editar la cédula. |
| Autoservicio en `/api/me/` | El ADMIN no podría corregir la de otro, y habría dos caminos de escritura. |
| Validar 7 u 8 dígitos | Rechazaría cédulas antiguas más cortas. |

## Consecuencias

- Los usuarios existentes que firman quedan bloqueados para cerrar y recetar hasta que un ADMIN capture su cédula. Al decidirlo no había datos reales.
- La demo siembra números de demostración (`00000001` para el ADMIN, `00000002` para el VET), que no son cédulas reales.
- Editar una receta existente (PATCH) no exige cédula: el candado está en emitirla.
- **Límite:** el sistema no afirma cumplimiento de ninguna norma. No se revisó formalmente qué exige la regulación aplicable a recetas veterinarias; el formato y la obligatoriedad son decisión de producto.
