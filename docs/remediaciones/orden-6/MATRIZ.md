# Estado de los IDs del orden 6

Se actualiza al cerrar cada entrega. Estados permitidos: `PENDIENTE`, `EN_CURSO`, `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `CERRADO_PREVIAMENTE`, `APLAZADO` y `FUERA_DE_ALCANCE`.

| ID | Entregas | Estado | Commit(s) | Evidencia |
|---|---|---|---|---|
| B2 | E01 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | ver commit E01 | EVIDENCIA.md §E01 |
| C2 | E02 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | ver commit E02 | EVIDENCIA.md §E02 |
| B5 | E03 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | ver commit E03 | EVIDENCIA.md §E03 |
| B6 | E04 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | ver commit E04 | EVIDENCIA.md §E04 |
| D2 | E05 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | ver commit E05 | EVIDENCIA.md §E05 |
| A1 + B4 | E06 | PENDIENTE | | |
| B3 | E06 | PENDIENTE | | |
| C1 | E06 | PENDIENTE | | |
| C7 | E06 | PENDIENTE | | |

## Avance

| Entrega | Pruebas (Ran / resultado) | Commit |
|---|---|---|
| E00 | Ran 586 / OK (skipped=7) | 9da1b8b (docs); línea base sin cambios de código |
| E01 | Ran 19 / OK (apps.prescriptions); 31 / OK con test_tenant_validation | ver commit E01 |
| E02 | Ran 76 / OK (apps.billing); 93 / OK con auditorías core | ver commit E02 |
| E03 | Ran 17 / OK (test_bootstrap); 189 / OK (apps.users apps.organizations) | ver commit E03 |
| E04 | Ran 7 / OK (test_seed_permissions_prune); 65 / OK con grants, agent_identity y ReleaseScriptTests | ver commit E04 |
| E05 | Ran 48 / OK (apps.organizations + test_url_audit); 83 / OK con test_admin_explicit_grants | ver commit E05 |
| E06 | | |
