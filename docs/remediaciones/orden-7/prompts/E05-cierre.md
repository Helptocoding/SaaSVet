# E05 — Cierre: ADR, documentación, corrida amplia y expediente

Primero lee y aplica `docs/remediaciones/orden-7/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Registrar la decisión de M01 en un ADR, actualizar los documentos operativos, comprobar el conjunto con la corrida amplia de backend y la suite de frontend, y cerrar el expediente. No se toca código.

## Precondición

`git log --oneline bb5a070..HEAD` muestra siete commits: los dos de E00, uno por cada entrega E01–E04 y el ajuste de prompts previo a E05 (`docs(order7): adjust test commands and record commit hashes before E05`). En `MATRIZ.md`, M01 y M03 están en `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. Si no, `BLOQUEADA`.

## Archivos permitidos

- `CONTEXTO_ACTUAL_PROYECTO.md`
- `docs/decisions/2026-11-04-p63-admin-explicit-grants.md`
- `docs/decisions/2026-11-12-p64-cedula-profesional-firmante.md`
- `docs/system-module-operations.md`
- Expediente del orden 7 (`README.md`, `MATRIZ.md`, `EVIDENCIA.md`)

## Paso 1. Documentos

Aplica estos cambios en orden.

### Cambio 1 — `docs/decisions/2026-11-12-p64-cedula-profesional-firmante.md`

Archivo nuevo. Créalo con este contenido exacto:

````markdown
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
````

### Cambio 2 — `docs/decisions/2026-11-04-p63-admin-explicit-grants.md`

Texto actual:

````markdown
- **Derivar la lista de los grupos de clasificación:** clasificar volvería a conceder.
````

Texto nuevo:

````markdown
- **Derivar la lista de los grupos de clasificación:** clasificar volvería a conceder.

## Addendum — orden 7 (12-11-2026)

Se añade `staff.update` (sensible): editar especialidad y cédula profesional de un miembro de Equipo. Entra en la lista literal del ADMIN; ningún otro rol lo recibe. Motivo y alcance en [ADR p64](2026-11-12-p64-cedula-profesional-firmante.md).
````

### Cambio 3 — `docs/system-module-operations.md`

Texto actual:

````markdown
- Un usuario `ADMIN` autenticado y perteneciente a la organización.
- Contraseña de al menos 8 caracteres, con al menos 1 mayúscula y 1 número.
````

Texto nuevo:

````markdown
- Un usuario `ADMIN` autenticado y perteneciente a la organización.
- Contraseña de al menos 8 caracteres, con al menos 1 mayúscula y 1 número.
- Si el rol es `VET`, cédula profesional: solo dígitos, de 5 a 10 (orden 7, ADR p64).
````

### Cambio 4 — `docs/system-module-operations.md`

Texto actual:

````markdown
- `treatment` no vacío (excepto cuando `consultation_type=vaccine`).
- El VET asignado (o un ADMIN).

**Resultado** (atómico, ADR p30)
````

Texto nuevo:

````markdown
- `treatment` no vacío (excepto cuando `consultation_type=vaccine`).
- El VET asignado (o un ADMIN).
- Cédula profesional del veterinario de la consulta, que la firma, aunque cierre un ADMIN (orden 7, ADR p64). Se congela en `vet_license_at_close`.

**Resultado** (atómico, ADR p30)
````

### Cambio 5 — `docs/system-module-operations.md`

Texto actual:

````markdown
- Consulta en `open` y sin receta previa (relación OneToOneField).
````

Texto nuevo:

````markdown
- Consulta en `open` y sin receta previa (relación OneToOneField).
- Cédula profesional de quien la emite, que es su firmante (orden 7, ADR p64).
````

### Cambio 6 — `CONTEXTO_ACTUAL_PROYECTO.md`

Texto actual:

````markdown
| `MedicalRecord.weight` → migrar a solo `VitalSigns` (data migration) | Media | — |
````

Texto nuevo:

````markdown
| `MedicalRecord.weight`: `RemoveField` (fase contract). Backfill y corte de lectores hechos en el orden 7 (M03) | Media | — |
````


## Paso 2. Verificación final

Desde `backend/`, conservando cada salida:

```bash
R="rtk proxy python scripts/orden7_isolated.py"
$R check 2>&1 | tail -2
$R makemigrations --check --dry-run 2>&1 | tail -2
```

Después, la corrida amplia de las reglas comunes, §5, en sus tres llamadas. Esperado: `No changes detected` y que los tres `Ran` sumen **852**, todos con `OK` y 7 `skipped` en total: las 825 de la línea base más 5 de E01, 15 de E02 y 7 de E03. Anota en evidencia el `Ran` de cada llamada y la suma. Si la suma difiere pero todo pasa, explica la diferencia en evidencia. Si algo falla, `BLOQUEADA`.

Frontend: los cuatro comandos de las reglas comunes, §6. Esperado: **79 archivos y 851 pruebas**, `lint exit=0`, `build exit=0` y `url_construction.cjs — OK`.

Desde la raíz:

```bash
git diff bb5a070 --name-only -- '*/migrations/*'
git diff bb5a070 --name-only -- frontend
git diff bb5a070 --name-only -- backend/apps/analytics
git diff bb5a070 --stat -- scripts/release.sh
```

Debe salir exactamente:

- Migraciones: `backend/apps/medical_records/migrations/0030_backfill_vitals_weight_from_record.py`, `backend/apps/medical_records/migrations/0031_medicalrecord_vet_license_at_close.py` y `backend/apps/users/migrations/0012_user_license_number.py`.
- Frontend: `frontend/src/api/staff.js`, `frontend/src/pages/staff.jsx` y `frontend/src/pages/staff.test.jsx`.
- Analítica: solo `backend/apps/analytics/tests/test_late_arrival_observability.py`.
- `release.sh`: nada.

Al terminar, detén el cluster sin borrarlo:

```bash
"/c/Program Files/PostgreSQL/18/bin/pg_ctl.exe" -D "$HOME/AppData/Local/Temp/opencode/orden7_pg18_20261112" -m fast -w stop > /dev/null 2>&1; echo "stop exit=$?"
```

## Paso 3. Expediente

- `MATRIZ.md`: M02 y M04 en `FUERA_DE_ALCANCE` (el usuario excluyó la analítica de la primera versión para clínicas piloto); M05 en `FUERA_DE_ALCANCE` (no seleccionado; el hallazgo de que su TODO contradice el CHECK `invoiceitem_exactly_one_source` queda en el plan, §3). Los tres con entrega E05. Completa la fila E05 del avance.
- `EVIDENCIA.md`: sección E05 con la salida de los comandos del paso 2 y estos límites:
  - La suite global de backend (más de 4.000 pruebas) solo queda probada en CI cuando el usuario suba la rama.
  - Sin despliegue. Las migraciones no se aplicaron a ninguna base real; el `seed_permissions` del próximo despliegue dará `staff.update` a los ADMIN.
  - `MedicalRecord.weight` sigue en la base: su `RemoveField` es una entrega posterior.
  - Los VET y ADMIN existentes que firman no podrán cerrar ni recetar hasta que un ADMIN capture su cédula.
  - El cluster aislado quedó detenido y no se borró.
- `README.md`: cambia el estado a `implementado localmente, pendiente de revisión y subida por el usuario`.

## Cierre

Commit con el ADR p64, el addendum de p63, `docs/system-module-operations.md`, `CONTEXTO_ACTUAL_PROYECTO.md` y el expediente: `docs(order7): add ADR p64 and close order 7`.

En «Para revisar»: subir la rama y confirmar CI; capturar las cédulas de los usuarios que firman antes de usar el sistema; el `RemoveField` de `MedicalRecord.weight` queda pendiente.
