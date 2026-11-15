# E03 — Cierre: corrida de referencia, IDs fuera de alcance y expediente

Primero lee y aplica `docs/remediaciones/orden-8/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Comprobar el conjunto con la corrida de referencia, registrar los IDs que el usuario dejó fuera y cerrar el expediente. No se toca código ni documentación del sistema.

## Precondición

`git log --oneline c71c0ed..HEAD` muestra cuatro commits: los dos de E00 y uno por cada entrega E01 y E02. En `MATRIZ.md`, G07 y G09 están en `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. Si no, `BLOQUEADA`.

## Archivos permitidos

- Expediente del orden 8 (`README.md`, `MATRIZ.md`, `EVIDENCIA.md`)

## Paso 1. Verificación final

Desde `backend/`, conservando cada salida:

```bash
R="rtk proxy python scripts/orden8_isolated.py"
$R check 2>&1 | tail -2
$R makemigrations --check --dry-run 2>&1 | tail -2
```

Después, la corrida de referencia de las reglas comunes, §5, en sus dos llamadas. Esperado: `No changes detected`, **A = 107** `OK` y **B = 246** `OK (skipped=1)`: la línea base (103 y 242) más 4 pruebas de E01 en A y 4 de E02 en B. Anota en evidencia el `Ran` de cada llamada. Si un número difiere pero todo pasa, explica la diferencia en evidencia. Si algo falla, aplica primero la limpieza de §5 y repite; si sigue fallando, `BLOQUEADA`.

Desde la raíz:

```bash
git diff c71c0ed --name-only -- '*/migrations/*'
git diff c71c0ed --name-only -- backend/apps ':(exclude)*/tests/*' ':(exclude)*/migrations/*'
git diff c71c0ed --stat -- backend/apps/agent/tools.py frontend backend/apps/analytics scripts/release.sh
```

Debe salir exactamente:

- Migraciones: `backend/apps/agent/migrations/0030_turndecision_verdict_choices.py`.
- Código de producción: `backend/apps/agent/models.py` y `backend/apps/agent/planner.py`.
- `tools.py`, frontend, analítica y `release.sh`: nada.

Al terminar, detén el cluster sin borrarlo:

```bash
"/c/Program Files/PostgreSQL/18/bin/pg_ctl.exe" -D "$HOME/AppData/Local/Temp/opencode/orden8_pg18_20261114" -m fast -w stop > /dev/null 2>&1; echo "stop exit=$?"
```

## Paso 2. Expediente

- `MATRIZ.md`: los siete IDs restantes pasan a `FUERA_DE_ALCANCE`, todos con entrega E03 y `EVIDENCIA.md §E03`. Completa la fila E03 del avance.
- `EVIDENCIA.md`: sección E03 con la salida de los comandos del paso 1 y una tabla con el motivo de cada ID fuera de alcance:

  | ID | Motivo |
  |---|---|
  | G01 | Decisión del usuario (14-11). El transcript de origen (06-08) es anterior a p58/p59, que rehicieron la verificación; reproducirlo exige un eval contra el modelo real, que no se autorizó. La obediencia del modelo a la conducta de p58 sigue sin evidencia con proveedor real. |
  | G08 | Decisión del usuario (14-11). Es diseño previo a ampliar las capacidades del agente, que sigue sin activarse. |
  | G02, G03, G04, G05, G10 | Decisión del usuario (14-11). Extensiones de producto fuera de la beta inicial. |

  Y estos límites:
  - La suite global de backend (más de 4.000 pruebas, incluidas las de `apps.agent` y `apps.channels` completas y las suites de procesos B3/B8/B9) solo queda probada en CI cuando el usuario suba la rama.
  - Sin despliegue ni activación del agente. La migración `agent.0030` no genera SQL y no se aplicó a ninguna base real.
  - El agente sigue ofreciendo solo citas de 30 min en la rejilla (G09).
  - Las filas de `TurnDecision` anteriores a É-F5 Fase 4 conservan su texto libre (G07).
  - El cluster aislado quedó detenido y no se borró.
- `README.md`: cambia el estado a `implementado localmente, pendiente de revisión y subida por el usuario`.

## Cierre

Commit con el expediente: `docs(order8): close order 8`.

En «Para revisar»: subir la rama y confirmar CI; la conducta de G01 sigue sin evidencia con el modelo real.
