# E00 — Línea base

Primero lee y aplica `docs/remediaciones/orden-7/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Crear la rama, guardar el expediente y el runner aislado, dejar el cluster PostgreSQL del orden 7 migrado y en marcha, y registrar la línea base de backend y frontend. No se toca código de producción.

## Precondición

Desde la raíz del repositorio:

1. `git rev-parse --short HEAD` debe dar `bb5a070`.
2. `git branch --list fix/orden-7-clinica` debe salir vacío.
3. `git status --short` solo puede listar:
   - `backend/scripts/orden7_isolated.py`
   - `docs/plan-remediacion-orden-7-2026-11-12.md`
   - `docs/plan-remediacion-priorizado-2026-10-28.md`
   - `docs/remediaciones/orden-7/`

Si algo no coincide, detente con `BLOQUEADA`.

## Pasos

1. Crea la rama: `git switch -c fix/orden-7-clinica`.
2. Commit de documentos y runner, con solo esas cuatro rutas:

   ```bash
   git add backend/scripts/orden7_isolated.py docs/plan-remediacion-orden-7-2026-11-12.md \
     docs/plan-remediacion-priorizado-2026-10-28.md docs/remediaciones/orden-7
   ```

   Mensaje: `docs(order7): add plan, per-delivery prompts and isolated test runner`.

3. Comprueba si existe el directorio del cluster:

   ```bash
   ls "$HOME/AppData/Local/Temp/opencode/orden7_pg18_20261112/PG_VERSION"
   ```

   - Si existe, ve al paso 4. Es lo esperado: se creó al preparar el plan.
   - Si no existe, créalo. Primero comprueba que el puerto está libre: `netstat -ano | grep ":49937 "` no debe imprimir nada; si imprime algo, `BLOQUEADA`. Luego:

     ```bash
     "/c/Program Files/PostgreSQL/18/bin/initdb.exe" \
       -D "$HOME/AppData/Local/Temp/opencode/orden7_pg18_20261112" \
       -U orden7_runner -A trust -E UTF8 \
       --locale-provider=builtin --builtin-locale=C.UTF-8 > /dev/null 2>&1; echo "initdb exit=$?"
     ```

     Debe dar `initdb exit=0`. Anótalo en evidencia: el cluster se creó en esta entrega.

4. Arranca el cluster con el bloque de las reglas comunes, §4, hasta ver `status exit=0`.
5. Desde `backend/`, con `R="rtk proxy python scripts/orden7_isolated.py"`:
   1. `$R init-db 2>&1 | tail -2` debe terminar en `Base orden7_iso_20261112 lista.`
   2. `$R check 2>&1 | tail -3` debe decir `System check identified no issues (0 silenced).`
   3. `$R migrate --noinput 2>&1 | tail -3`. Con la base nueva tarda unos 2 minutos.
   4. `$R makemigrations --check --dry-run 2>&1 | tail -3` debe decir `No changes detected`.
6. Crea la base de pruebas con una corrida corta (tarda unos 4 minutos la primera vez; sin este paso la corrida amplia supera el timeout):

   ```bash
   $R test apps.users.tests.test_email_identity_constraint --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"
   ```

7. Corrida amplia de backend: el bloque de las reglas comunes, §5. La referencia es `Ran 825 tests` y `OK (skipped=7)`. Si el número difiere pero todo pasa, anótalo y continúa. **Si hay algún `FAIL` o `ERROR`, detente con `BLOQUEADA`** y lista las pruebas que fallan: la línea base debe estar en verde antes de cambiar nada.
8. Línea base de frontend: los cuatro comandos de las reglas comunes, §6. Referencia: `78 passed` archivos, `846 passed` pruebas, `lint exit=0`, `build exit=0` y `url_construction.cjs — OK`. Cualquier fallo es `BLOQUEADA`.

## Verificación

- Salida de cada comando de los pasos 5 a 8.
- `git log --oneline -2` muestra el commit de documentos encima de `bb5a070`.

## Cierre

En `MATRIZ.md` completa solo la fila E00 de la tabla de avance (`Ran N / OK`, backend y frontend). En `EVIDENCIA.md` añade la sección E00 con los comandos y resultados, y di si el cluster ya existía o lo creaste.

Commit con `MATRIZ.md` y `EVIDENCIA.md`: `chore(order7): record isolated baseline (order 7)`.

No marques ningún ID como cerrado.
