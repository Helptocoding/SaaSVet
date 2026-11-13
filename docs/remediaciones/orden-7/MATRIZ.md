# Estado de los IDs del orden 7

Se actualiza al cerrar cada entrega. Estados permitidos: `PENDIENTE`, `EN_CURSO`, `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `APLAZADO` y `FUERA_DE_ALCANCE`.

| ID | Entregas | Estado | Commit(s) | Evidencia |
|---|---|---|---|---|
| M03 | E01 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | `b15f242` | EVIDENCIA.md §E01 |
| M01 | E02–E04 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | `1e411c2`, `4c988ae`, `ff4fcc7` | EVIDENCIA.md §E02–E04 |
| M02 | E05 | PENDIENTE | | |
| M04 | E05 | PENDIENTE | | |
| M05 | E05 | PENDIENTE | | |

## Avance

| Entrega | Pruebas (Ran / resultado) | Commit |
|---|---|---|
| E00 | Backend Ran 825 / OK (skipped=7); frontend 78 archivos, 846 pruebas OK | `2fcd62d`, `d3a00c3` |
| E01 | Ran 79 / OK | `b15f242` |
| E02 | Ran 226 / OK | `1e411c2` |
| E03 | Ran 195 / OK | `4c988ae` |
| E04 | Frontend 79 archivos, 851 pruebas OK (con --maxWorkers=2) | `ff4fcc7` |
| E05 | | |
