# Evidencia del orden 8

Cada entrega añade su sección con comandos reales y resultados. No se resume lo que no se ejecutó. Lo que no se pudo comprobar se declara como límite.

## Medición previa (14-11-2026, `c71c0ed`)

Tomada al preparar el plan, en el cluster aislado del orden 8, que se creó para ello.

| Comprobación | Resultado |
|---|---|
| `initdb` (proveedor `builtin`, `C.UTF-8`) + `init-db` + `check` + `migrate` | OK, sin problemas; `migrate` en 2 min 33 s; `makemigrations --check`: sin cambios |
| `apps.channels` completo | `Ran 158 tests` en 724 s, `FAILED (errors=1)`: `test_media_restore_drill` exige una base `test_ci_*` (`Recognized isolated loopback PostgreSQL required`). Error de entorno, no del código |
| Corrida de referencia, llamada A | `Ran 103 tests`, `OK`, 2 min 39 s |
| Corrida de referencia, llamada B | `Ran 242 tests`, `OK (skipped=1)`, 2 min 57 s |
| Validación en seco: E01 y E02 aplicados en un worktree desechable | A = 107 OK; B = 246 OK (skipped=1); pruebas dirigidas de E01 84 OK y de E02 12 OK; `sqlmigrate agent 0030` → `-- (no-op)`. La llamada B tardó 232 min de reloj porque el equipo quedó suspendido: el log de postgres no tiene actividad entre 15:38 y 19:30 |
| Mutación de G09 | Con `_vet_free` cambiado a la regla antigua (inicio exacto), 3 de las 4 pruebas nuevas de `test_slots.py` fallan; la cuarta fija el límite de la rejilla. `tools.py` restaurado |
| Base de pruebas sucia | Una corrida detenida por el sistema a mitad de un `TransactionTestCase` dejó filas; la siguiente dio 11 `ERROR` y 9 `FAIL` en `B3LocalIntegrationTests`. `test_b3_durable` solo pasó 40/40 y la corrida repetida, 84/84 |
| Reaplicación desde los prompts | Los 13 bloques de E01–E02 se aplicaron sobre los archivos de `c71c0ed`, exigiendo que cada texto actual aparezca una vez y empiece y termine en límite de línea. El resultado coincide con el worktree validado en los 7 archivos |
| Limpieza | Worktree desechable borrado. Bases del cluster borradas para que E00 parta de cero; cluster detenido y no borrado |

Plantilla por entrega:

```markdown
## E0X — título (fecha, commit)

| Comando | Resultado |
|---|---|
| ... | ... |

Límites: ...
Observaciones sin cambio: ...
```

## E00 — línea base (14-11-2026, `26e1ab7` sobre `c71c0ed`)

| Comando | Resultado |
|---|---|
| Precondición: `develop` = `c71c0ed`; rama `fix/orden-8-agente` inexistente; `git status` solo con runner, plan y `orden-8/` | OK |
| `git switch -c fix/orden-8-agente develop` + commit de documentos | HEAD `c71c0ed` antes del commit; commit `26e1ab7` (10 archivos) |
| Cluster `orden8_pg18_20261114` | Ya existía (`PG_VERSION` presente); no se creó en esta entrega. Arrancado con `pg_ctl`, `status exit=0` |
| `init-db` | `Base orden8_iso_20261114 lista.` |
| `check` | `System check identified no issues (0 silenced).` |
| `migrate --noinput` | OK; última aplicada vista: `users.0012_user_license_number` |
| `makemigrations --check --dry-run` | `No changes detected` |
| `test test_turn_decision test_slots --keepdb` (crea base de pruebas) | `Ran 19 tests`, `OK` |
| Corrida de referencia A | `Ran 103 tests in 156.236s`, `OK` |
| Corrida de referencia B | `Ran 242 tests in 193.226s`, `OK (skipped=1)` |

Límites: no se listó explícitamente `agent.0029_inbox_read_state` en la salida de `migrate` (solo se vio el `tail`); `makemigrations --check` confirma que no hay migraciones pendientes.
Observaciones sin cambio: `docs/hector.py` no existe en la copia de trabajo; no se tocó.

## E01 — G07: `TurnDecision.verdict` con vocabulario cerrado (14-11-2026, `fb224bc`)

| Comando | Resultado |
|---|---|
| `py_compile` de los 5 archivos Python | `compilado`, sin `FAIL` |
| `grep -n "result.get('decision', '')" planner.py` | 2 líneas: 245 (`produced['salida'] = ...`, esperada) y 319 (`decision = result.get('decision', '')`, preexistente, ajena al cambio) |
| `makemigrations --check --dry-run` | `No changes detected` |
| `sqlmigrate agent 0030` | `-- (no-op)` |
| `migrate --noinput` | `Applying agent.0030_turndecision_verdict_choices... OK` |
| `test_turn_decision test_contracts test_arbiter test_b3_durable --keepdb` | `Ran 84 tests in 122.454s`, `OK` |

Límites: las filas anteriores a É-F5 Fase 4 conservan su texto libre (append-only); la validación vive en `full_clean()`, no en un `CHECK` de base de datos, así que un `bulk_create` o un `save(validate=False)` la saltan, igual que cualquier otro campo con `choices`.
Observaciones sin cambio: el `grep` del prompt esperaba una sola línea; la línea 319 ya existía y no es parte de G07.
