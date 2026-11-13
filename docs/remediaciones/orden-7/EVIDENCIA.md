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
