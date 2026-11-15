# Estado de los ocho IDs

Se actualiza al cerrar cada entrega. Estado permitido: `PENDIENTE`, `EN_CURSO` o `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`.

| ID | Entregas | Estado | Commit(s) | Evidencia |
|---|---|---|---|---|
| F01 | E00, E05–E08, E12 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 553382f, 05ede6b, 6ee4f30, cfd87d8, 57a5248, 9e11989 | EVIDENCIA.md §E00, §E05–§E08, §E12 |
| C5 | E02 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 92c4b96 | EVIDENCIA.md §E02 |
| C4 | E02, E03 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 92c4b96, 6071d75 | EVIDENCIA.md §E02, §E03 |
| C3 | E04 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 9a456d2 | EVIDENCIA.md §E04 |
| C6 | E01 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 1af05d9 | EVIDENCIA.md §E01 |
| F04 | E01 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 1af05d9 | EVIDENCIA.md §E01 |
| F03 | E09, E09b, E10 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 1998485, ebdfb4c, 7f4e796 | EVIDENCIA.md §E09, §E09b, §E10 |
| F02 | E11 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | d40bdae | EVIDENCIA.md §E11 |

Integrado en `develop` por el [PR #3](https://github.com/Helptocoding/SaaSVet/pull/3) (`a7dbdaf`), con CI real en verde el 11-11 ([integración](EVIDENCIA.md#integración-en-develop-y-ci-11-11-2026)). Los estados no cambian porque nada se desplegó. Los hashes sustituyen el 15-11 a los marcadores «ver commit EXX»; salen de `git log a7dbdaf^1..a7dbdaf^2`.

## Avance de lint

| Entrega | Errores esperados | Errores reales | Commit |
|---|---|---|---|
| E00 | 61 | 61 | 553382f |
| E01 | 61 | 61 | 1af05d9 |
| E02 | 61 | 61 | 92c4b96 |
| E03 | 61 | 61 | 6071d75 |
| E04 | 59 | 59 | 9a456d2 |
| E05 | 50 | 50 | 05ede6b |
| E06 | 34 | 34 | 6ee4f30 |
| E07 | 18 | 18 | cfd87d8 |
| E08 | 0 | 0 | 57a5248 |
| E09 | 0 | 0 | 1998485 |
| E09b | 0 | 0 | ebdfb4c |
| E10 | 0 | 0 | 7f4e796 |
| E11 | 0 | 0 | d40bdae |
| E12 | 0 | 0 | 9e11989 |
