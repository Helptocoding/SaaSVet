# E00 — Línea base

Primero lee y aplica `docs/remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Crear la rama, guardar el expediente y el runner aislado, dejar el cluster PostgreSQL del orden 6 en marcha y registrar la línea base de pruebas. No se toca código de producción.

## Precondición

Desde la raíz del repositorio:

1. `git rev-parse --short HEAD` debe dar `a7dbdaf`.
2. `git branch --list fix/orden-6-arquitectura-backend` debe salir vacío.
3. `git status --short` solo puede listar:
   - `backend/scripts/orden6_isolated.py`
   - `docs/plan-remediacion-orden-6-2026-11-11.md`
   - `docs/plan-remediacion-priorizado-2026-10-28.md`
   - `docs/remediaciones/orden-6/`

Si algo no coincide, detente con `BLOQUEADA`.

## Pasos

1. Crea la rama: `git switch -c fix/orden-6-arquitectura-backend`.
2. Commit de documentos y runner, con solo esas cuatro rutas:

   ```bash
   git add backend/scripts/orden6_isolated.py docs/plan-remediacion-orden-6-2026-11-11.md \
     docs/plan-remediacion-priorizado-2026-10-28.md docs/remediaciones/orden-6
   ```

   Mensaje: `docs(order6): add plan, per-delivery prompts and isolated test runner`.

3. Comprueba si existe el directorio del cluster:

   ```bash
   ls "$HOME/AppData/Local/Temp/opencode/orden6_pg18_20261111/PG_VERSION"
   ```

   - Si existe, ve al paso 4.
   - Si no existe, créalo. Primero comprueba que el puerto está libre: `netstat -ano | grep ":49936 "` no debe imprimir nada; si imprime algo, `BLOQUEADA`. Luego:

     ```bash
     "/c/Program Files/PostgreSQL/18/bin/initdb.exe" \
       -D "$HOME/AppData/Local/Temp/opencode/orden6_pg18_20261111" \
       -U orden6_runner -A trust -E UTF8 \
       --locale-provider=builtin --builtin-locale=C.UTF-8 > /dev/null 2>&1; echo "initdb exit=$?"
     ```

     Debe dar `initdb exit=0`. Anótalo en evidencia: el cluster se creó en esta entrega.

4. Arranca el cluster con el bloque de las reglas comunes, §4, hasta ver `status exit=0`.
5. Desde `backend/`, con `R="rtk proxy python scripts/orden6_isolated.py"`:
   1. `$R init-db 2>&1 | tail -2` debe terminar en `Base orden6_iso_20261111 lista.`
   2. `$R check 2>&1 | tail -3` debe decir `System check identified no issues (0 silenced).`
   3. `$R migrate --noinput 2>&1 | tail -3`. Si la base ya estaba migrada dirá `No migrations to apply.`; si era nueva, tarda unos 2 minutos.
   4. `$R makemigrations --check --dry-run 2>&1 | tail -3` debe decir `No changes detected`.
6. Corrida amplia, con timeout de 600000 ms:

   ```bash
   $R test apps.core apps.users apps.organizations apps.prescriptions apps.billing --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30
   ```

   La referencia es `Ran 586 tests` y `OK (skipped=7)`. Si el número difiere pero todo pasa, anótalo y continúa. **Si hay algún `FAIL` o `ERROR`, detente con `BLOQUEADA`** y lista las pruebas que fallan: la línea base debe estar en verde antes de cambiar nada.

## Verificación

- Salida de cada comando del paso 5.
- Resultado de la corrida amplia.
- `git log --oneline -2` muestra el commit de documentos encima de `a7dbdaf`.

## Cierre

En `MATRIZ.md` completa solo la fila E00 de la tabla de avance (`Ran N / OK`). En `EVIDENCIA.md` añade la sección E00 con los comandos y resultados, y di si el cluster ya existía o lo creaste.

Commit con `MATRIZ.md` y `EVIDENCIA.md`: `chore(order6): record isolated baseline (order 6)`.

No marques ningún ID como cerrado.
