# Estado de los IDs del orden 7

Se actualiza al cerrar cada entrega. Estados permitidos: `PENDIENTE`, `EN_CURSO`, `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `APLAZADO` y `FUERA_DE_ALCANCE`.

| ID | Entregas | Estado | Commit(s) | Evidencia |
|---|---|---|---|---|
| M03 | E01 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | feat(medical-records): make VitalSigns the only weight source (order 7, M03) | EVIDENCIA.md §E01 |
| M01 | E02–E04 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 1e411c2, 4c988ae, feat(frontend): capture professional license in staff page (order 7, M01) | EVIDENCIA.md §E02–E04 |
| M02 | E05 | PENDIENTE | | |
| M04 | E05 | PENDIENTE | | |
| M05 | E05 | PENDIENTE | | |

## Avance

| Entrega | Pruebas (Ran / resultado) | Commit |
|---|---|---|
| E00 | Backend Ran 825 / OK (skipped=7); frontend 78 archivos, 846 pruebas OK | (ver commit de cierre E00) |
| E01 | Ran 79 / OK | (commit E01) |
| E02 | Ran 226 / OK | (commit E02) |
| E03 | Ran 195 / OK | (commit E03) |
| E04 | Frontend 79 archivos, 851 pruebas OK (con --maxWorkers=2) | (commit E04) |
| E05 | | |
