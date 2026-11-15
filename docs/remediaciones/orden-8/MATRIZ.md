# Estado de los IDs del orden 8

Se actualiza al cerrar cada entrega. Estados permitidos: `PENDIENTE`, `EN_CURSO`, `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `APLAZADO` y `FUERA_DE_ALCANCE`.

| ID | Entregas | Estado | Commit(s) | Evidencia |
|---|---|---|---|---|
| G07 | E01 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | fb224bc | EVIDENCIA.md §E01 |
| G09 | E02 | IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE | 4540073 | EVIDENCIA.md §E02 |
| G01 | E03 | FUERA_DE_ALCANCE | — | EVIDENCIA.md §E03 |
| G02 | E03 | FUERA_DE_ALCANCE | — | EVIDENCIA.md §E03 |
| G03 | E03 | FUERA_DE_ALCANCE | — | EVIDENCIA.md §E03 |
| G04 | E03 | FUERA_DE_ALCANCE | — | EVIDENCIA.md §E03 |
| G05 | E03 | FUERA_DE_ALCANCE | — | EVIDENCIA.md §E03 |
| G08 | E03 | FUERA_DE_ALCANCE | — | EVIDENCIA.md §E03 |
| G10 | E03 | FUERA_DE_ALCANCE | — | EVIDENCIA.md §E03 |

Integrado en `develop` por el [PR #7](https://github.com/Helptocoding/SaaSVet/pull/7) (`14e0ca2`), con CI real en verde el 15-11: suite global de 4.058 pruebas OK en las dos corridas ([integración](EVIDENCIA.md#integración-en-develop-y-ci-15-11-2026)). Los estados no cambian porque nada se desplegó.

## Avance

| Entrega | Pruebas (Ran / resultado) | Commit |
|---|---|---|
| E00 | A Ran 103 / OK; B Ran 242 / OK (skipped=1) | 26e1ab7 |
| E01 | Ran 84 / OK | fb224bc |
| E02 | Ran 12 / OK | 4540073 |
| E03 | A Ran 107 / OK; B Ran 246 / OK (skipped=1) | a465142 |
