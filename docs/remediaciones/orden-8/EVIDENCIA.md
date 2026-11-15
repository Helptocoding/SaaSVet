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
