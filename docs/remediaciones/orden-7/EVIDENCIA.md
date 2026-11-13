# Evidencia del orden 7

Cada entrega añade su sección con comandos reales y resultados. No se resume lo que no se ejecutó. Lo que no se pudo comprobar se declara como límite.

## Medición previa (12-11-2026, `bb5a070`)

Tomada al preparar el plan, en el cluster aislado del orden 7, que se creó para ello.

| Comprobación | Resultado |
|---|---|
| `initdb` (proveedor `builtin`, `C.UTF-8`) + `init-db` + `check` | OK, sin problemas |
| Corrida amplia inicial (`apps.core apps.users apps.organizations apps.medical_records apps.prescriptions apps.billing` + T8 de analítica) | 729 OK (skipped=7), 403 s, más unos 200 s para crear la base de pruebas |
| Validación en seco: E01–E05 aplicados en un worktree desechable | Pruebas dirigidas por entrega: E01 79, E02 226 y E03 195, todas OK. La corrida amplia de las reglas comunes dio 852 OK (skipped=7) en 456 s. `makemigrations --check`: sin cambios. |
| Validación en seco, frontend | Con `VITE_API_URL` ficticio: 79 archivos y 851 pruebas OK; `lint`, `build` y `smoke:urls` OK. |
| Fallas que la validación encontró y los prompts ya corrigen | El candado de firma rompía 44 pruebas en 9 archivos y el alta de `VET` 4 en 3, todas por fixtures sin cédula; la cédula en una variable nueva hacía fallar `test_pdf_markup_injection`; el mock de `useAuth` con un `user` inestable desmontaba el modal de Equipo. |
| Reaplicación desde los prompts | Los 96 bloques de E01–E05 se aplicaron sobre los 42 archivos de `bb5a070`, exigiendo que cada texto actual aparezca una vez y empiece y termine en límite de línea. El resultado coincide con el worktree validado en los 42 archivos. |
| Limpieza | Worktree desechable borrado. Bases del cluster borradas para que E00 parta de cero; cluster detenido y no borrado. |

Plantilla por entrega:

```markdown
## E0X — título (fecha, commit)

| Comando | Resultado |
|---|---|
| ... | ... |

Límites: ...
Observaciones sin cambio: ...
```

## E00 — Línea base (12-11-2026, sobre `bb5a070`; commit de docs `2fcd62d`)

Rama `fix/orden-7-clinica` creada. El cluster `orden7_pg18_20261112` ya existía (no se creó en esta entrega); estaba detenido y se arrancó con el bloque de reglas comunes §4 (`status exit=0`).

| Comando | Resultado |
|---|---|
| `git rev-parse --short HEAD` / rama / status previos | `bb5a070`; rama inexistente; solo las rutas permitidas |
| `init-db` | `Base orden7_iso_20261112 lista.` |
| `check` | `System check identified no issues (0 silenced).` |
| `migrate --noinput` | OK, última `users.0011_user_is_service_account_alter_user_role` |
| `makemigrations --check --dry-run` | `No changes detected` |
| Prueba corta `apps.users.tests.test_email_identity_constraint --keepdb` | `Ran 4 tests` / `OK` |
| Corrida amplia backend (reglas comunes §5) | `Ran 825 tests in 790.762s` / `OK (skipped=7)` |
| Frontend `pnpm run test` | 78 archivos, 846 pruebas pasadas |
| `lint` / `build` | `exit=0` / `exit=0` |
| `smoke:urls` | `url_construction.cjs — OK (5/5 gates verde, 0 matches)` |

Límites: la corrida amplia superó los 600 s de la herramienta y pasó a segundo plano; terminó con exit 0.
Observaciones sin cambio: la primera corrida completa de frontend falló 1 prueba (`src/pages/inbox/index.test.jsx > Inbox — aislamiento del borrador > aplica el cap global de 20 intentos entre sesiones`, 845/846). Ese archivo solo pasó 93/93 y una segunda corrida completa dio 846/846: prueba inestable bajo carga, sin cambios en el código. Vigilar en E05.

## E01 — M03: VitalSigns como única fuente del peso (12-11-2026)

| Comando | Resultado |
|---|---|
| `py_compile` de los 7 archivos Python tocados | `compilado`, sin FAIL |
| `grep MinValueValidator\|MaxValueValidator\|force_weight` en serializers | Sin validadores; `force_weight` solo en líneas 27–110, antes de `class MedicalRecordSerializer` (línea 128) |
| `makemigrations --check --dry-run` | `No changes detected` |
| `migrate --noinput` | `Applying medical_records.0030_backfill_vitals_weight_from_record... OK` |
| `test test_weight_single_source test_vitals test_pdf test_close test_hybrid_permission_nested --keepdb` | `Ran 79 tests` / `OK` |

Límites: la columna `MedicalRecord.weight` sigue en la base hasta su `RemoveField`; la reversa de la migración no borra las filas copiadas.
Observaciones sin cambio: ninguna.

## E02 — M01: cédula profesional en el usuario y en Equipo (12-11-2026)

| Comando | Resultado |
|---|---|
| `py_compile` de los 14 archivos Python | `compilado`, sin FAIL |
| `grep StaffDeactivateView` fuera de tests y services.py | sin salida |
| `makemigrations --check --dry-run` | `No changes detected` |
| `migrate --noinput` | `medical_records.0031_medicalrecord_vet_license_at_close... OK`, `users.0012_user_license_number... OK` |
| `test apps.users` + 6 módulos de `apps.core.tests` (`--keepdb`) | `Ran 226 tests` / `OK` |

Límites: los cierres de consulta y las recetas aún no exigen la cédula (E03).
Observaciones sin cambio: ninguna.

## E03 — M01: quien firma necesita cédula (12-11-2026)

| Comando | Resultado |
|---|---|
| `py_compile` de los 7 archivos Python principales | `compilado`, sin FAIL |
| `makemigrations --check --dry-run` | `No changes detected` |
| `test apps.medical_records apps.prescriptions test_pdf_markup_injection test_demo_reset test_late_arrival_observability test_physical_deletion --keepdb` | `Ran 195 tests` / `OK` |
| `git diff --stat HEAD -- backend/apps/analytics` | solo `test_late_arrival_observability.py`, 1 línea añadida |

Límites: el sistema no verifica la cédula contra la SEP; editar una receta existente (PATCH) no la exige.
Observaciones sin cambio: ninguna.

## E04 — M01: capturar la cédula en Equipo (12-11-2026)

| Comando | Resultado |
|---|---|
| `vitest run src/pages/staff.test.jsx` | `Tests  5 passed (5)` |
| `pnpm run test` (paralelismo por defecto), 4 corridas | `1 failed` / `2 failed` / `1 failed` / `3 failed`, todos `Test timed out in 5000ms` en `src/pages/inbox/index.test.jsx` (corridas de ~310 s) |
| `vitest run src/pages/inbox/index.test.jsx` solo | `Tests  93 passed (93)` |
| `vitest run --maxWorkers=2` (suite completa) | `Test Files  79 passed (79)` / `Tests  851 passed (851)` |
| `lint` / `build` | `exit=0` / `exit=0` |
| `smoke:urls` | `url_construction.cjs — OK (5/5 gates verde, 0 matches)` |

Límites: sin prueba manual en navegador; la cubren las pruebas de Vitest con el cliente HTTP sustituido.
Observaciones sin cambio: las pruebas de `inbox/index.test.jsx` (no tocadas) agotan 5 s con el paralelismo por defecto en este equipo cargado; ya falló una en E00 y la archivo solo pasa 93/93. No se subió ningún timeout. Con `--maxWorkers=2` pasa todo. Vigilar en E05.

## Ajuste previo a E05 (12-11-2026, revisión entre entregas)

Sin cambios de código. Antes de E05 cambian los prompts y la matriz:

- **Corrida amplia de backend:** pasa a tres llamadas en primer plano (reglas comunes, §5). En una sola llamada, la de E00 tardó 790 s, superó el límite de 600 s de la herramienta y esta la pasó a segundo plano.
- **Suite de frontend:** se corre con `--maxWorkers=2` (reglas comunes, §6). Con el paralelismo por defecto, `src/pages/inbox/index.test.jsx` agotó su timeout una vez en E00 y en 4 de 4 corridas en E04. Ninguna entrega toca ese archivo. CI no cambia.
- **Precondición de E05:** cuenta este commit; el prompt decía siete commits cuando las entregas solo producen seis.
- **`MATRIZ.md`:** los marcadores «(commit E0X)» se sustituyen por los hashes reales.

Revisión de E01–E04: cada prompt se reaplicó sobre el estado anterior y el código de cada commit resultó idéntico al del prompt (E01 24 cambios, E02 28, E03 26, E04 12).

## E05 — Cierre (12-11-2026)

| Comando | Resultado |
|---|---|
| `check` | `System check identified no issues (0 silenced).` |
| `makemigrations --check --dry-run` | `No changes detected` |
| Corrida amplia, llamada 1 (`apps.core`) | `Ran 322 tests` / `OK (skipped=7)` |
| Corrida amplia, llamada 2 (users, organizations, legal, 4 módulos de platform/patients/inventory) | `Ran 294 tests` / `OK` |
| Corrida amplia, llamada 3 (medical_records, prescriptions, billing, T8 de analítica) | `Ran 236 tests` / `OK` |
| Suma de las tres | **852** pruebas, `OK`, 7 `skipped` (825 de la línea base + 5 E01 + 15 E02 + 7 E03) |
| Frontend `vitest run --maxWorkers=2` | `Test Files 79 passed (79)` / `Tests 851 passed (851)` |
| `lint` / `build` | `exit=0` / `exit=0` |
| `smoke:urls` | `url_construction.cjs — OK (5/5 gates verde, 0 matches)` |
| `git diff bb5a070 --name-only -- '*/migrations/*'` | `medical_records/0030`, `medical_records/0031`, `users/0012` |
| `git diff bb5a070 --name-only -- frontend` | `src/api/staff.js`, `src/pages/staff.jsx`, `src/pages/staff.test.jsx` |
| `git diff bb5a070 --name-only -- backend/apps/analytics` | solo `test_late_arrival_observability.py` |
| `git diff bb5a070 --stat -- scripts/release.sh` | sin cambios |
| Cluster aislado | `stop exit=0` (detenido, no borrado) |

Límites:
- La suite global de backend (más de 4.000 pruebas) solo queda probada en CI cuando el usuario suba la rama.
- Sin despliegue. Las migraciones no se aplicaron a ninguna base real; el `seed_permissions` del próximo despliegue dará `staff.update` a los ADMIN.
- `MedicalRecord.weight` sigue en la base: su `RemoveField` es una entrega posterior.
- Los VET y ADMIN existentes que firman no podrán cerrar ni recetar hasta que un ADMIN capture su cédula.
- El frontend se verificó con `--maxWorkers=2`; con el paralelismo por defecto las pruebas de `inbox/index.test.jsx` agotan 5000 ms en este equipo (CI conserva `pnpm run test`).
- M02, M04 (analítica excluida de la primera versión) y M05 (no seleccionado; su TODO contradice el CHECK `invoiceitem_exactly_one_source`, ver plan §3) quedan `FUERA_DE_ALCANCE`.

## Integración en develop y CI (12-11-2026)

Por petición del usuario, la rama se subió y se abrió el [PR #6](https://github.com/Helptocoding/SaaSVet/pull/6) contra `develop`. El usuario lo mergeó: `ea21232`, con padres `bb5a070` (`develop`) y `80fc42f` (la rama). `develop` no se movió mientras el PR estuvo abierto y `git diff 80fc42f ea21232` no imprime nada, así que las dos corridas probaron el mismo árbol.

| Corrida | Evento | Commit probado | Resultado |
|---|---|---|---|
| [43359001376](https://github.com/Helptocoding/SaaSVet/actions/runs/43359001376) | `pull_request` | merge provisional de `80fc42f` sobre `bb5a070` | 4 jobs OK |
| [43371486161](https://github.com/Helptocoding/SaaSVet/actions/runs/43371486161) | `push` a `develop` | `ea21232` | 4 jobs OK |

En las dos:

- Backend: migraciones y los corpus B0, B3, B4 y B5 (17, 43, 70 y 37 pruebas). Suite global: `Ran 4050 tests` / `OK (skipped=20)`. Son 27 más que las 4.023 del orden 6, las mismas que sumaron E01–E03 (5 + 15 + 7).
- Frontend, images y security (gitleaks bloqueante): OK. En la corrida del PR, `pnpm run test` con el paralelismo por defecto dio 79 archivos y 851 pruebas: las de `inbox/index.test.jsx` no agotaron su límite en CI.

Con esto se cierran el primer límite de E05 y el del frontend con `--maxWorkers=2`. Siguen vigentes:

- Sin despliegue. Las migraciones `users/0012`, `medical_records/0030` y `0031` no se aplicaron a ninguna base real; el próximo `seed_permissions` dará `staff.update` a los ADMIN.
- Tras desplegar, un ADMIN debe capturar las cédulas de quienes firman antes de que la clínica cierre consultas o emita recetas.
- `MedicalRecord.weight` sigue en la base: su `RemoveField` es una entrega posterior.
- El cluster aislado sigue detenido y sin borrar.
