# E00 — Línea base

Primero lee y aplica `docs/remediaciones/orden-8/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Crear la rama, guardar el expediente y el runner aislado, dejar el cluster PostgreSQL del orden 8 migrado y en marcha, y registrar la corrida de referencia del agente. No se toca código de producción.

## Precondición

Desde la raíz del repositorio:

1. `git rev-parse --short develop` debe dar `c71c0ed`.
2. `git branch --list fix/orden-8-agente` debe salir vacío.
3. `git status --short` solo puede listar:
   - `backend/scripts/orden8_isolated.py`
   - `docs/hector.py` (del usuario; no se toca)
   - `docs/plan-remediacion-orden-8-2026-11-14.md`
   - `docs/remediaciones/orden-8/`

Si algo no coincide, detente con `BLOQUEADA`.

## Pasos

1. Crea la rama desde `develop`: `git switch -c fix/orden-8-agente develop`. La copia de trabajo puede estar en otra rama; los archivos no rastreados viajan con el cambio. Comprueba después que `git rev-parse --short HEAD` da `c71c0ed`.
2. Commit de documentos y runner, con solo esas tres rutas:

   ```bash
   git add backend/scripts/orden8_isolated.py docs/plan-remediacion-orden-8-2026-11-14.md \
     docs/remediaciones/orden-8
   ```

   Mensaje: `docs(order8): add plan, per-delivery prompts and isolated test runner`.

3. Comprueba si existe el directorio del cluster:

   ```bash
   ls "$HOME/AppData/Local/Temp/opencode/orden8_pg18_20261114/PG_VERSION"
   ```

   - Si existe, ve al paso 4. Es lo esperado: se creó al preparar el plan.
   - Si no existe, créalo. Primero comprueba que el puerto está libre: `netstat -ano | grep ":49938 "` no debe imprimir nada; si imprime algo, `BLOQUEADA`. Luego:

     ```bash
     "/c/Program Files/PostgreSQL/18/bin/initdb.exe" \
       -D "$HOME/AppData/Local/Temp/opencode/orden8_pg18_20261114" \
       -U orden8_runner -A trust -E UTF8 \
       --locale-provider=builtin --builtin-locale=C.UTF-8 > /dev/null 2>&1; echo "initdb exit=$?"
     ```

     Debe dar `initdb exit=0`. Anótalo en evidencia: el cluster se creó en esta entrega.

4. Arranca el cluster con el bloque de las reglas comunes, §4, hasta ver `status exit=0`.
5. Desde `backend/`, con `R="rtk proxy python scripts/orden8_isolated.py"`:
   1. `$R init-db 2>&1 | tail -2` debe terminar en `Base orden8_iso_20261114 lista.`
   2. `$R check 2>&1 | tail -3` debe decir `System check identified no issues (0 silenced).`
   3. `$R migrate --noinput 2>&1 | tail -3`. Con la base nueva tarda unos 3 minutos. La última migración del agente es `agent.0029_inbox_read_state`.
   4. `$R makemigrations --check --dry-run 2>&1 | tail -3` debe decir `No changes detected`.
6. Crea la base de pruebas con una corrida corta (tarda unos 4 minutos la primera vez):

   ```bash
   $R test apps.agent.tests.test_turn_decision apps.agent.tests.test_slots --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"
   ```

   Referencia: `Ran 19 tests` y `OK`.

7. Corrida de referencia: las dos llamadas de las reglas comunes, §5. Referencia: **A = 103** `OK` y **B = 242** `OK (skipped=1)`. Si un número difiere pero todo pasa, anótalo y continúa. **Si hay algún `FAIL` o `ERROR`, aplica primero la limpieza de las reglas comunes, §5, y repite la llamada; si sigue fallando, detente con `BLOQUEADA`** y lista las pruebas que fallan: la línea base debe estar en verde antes de cambiar nada.

## Verificación

- Salida de cada comando de los pasos 5 a 7.
- `git log --oneline -2` muestra el commit de documentos encima de `c71c0ed`.

## Cierre

En `MATRIZ.md` completa solo la fila E00 de la tabla de avance (`A Ran N / OK; B Ran N / OK`). En `EVIDENCIA.md` añade la sección E00 con los comandos y resultados, y di si el cluster ya existía o lo creaste.

Commit con `MATRIZ.md` y `EVIDENCIA.md`: `chore(order8): record isolated baseline (order 8)`.

No marques ningún ID como cerrado.
