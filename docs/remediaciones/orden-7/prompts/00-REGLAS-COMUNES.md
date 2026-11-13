# Reglas comunes del orden 7

Aplican a todas las entregas. Léelas completas antes de tocar nada.

## 1. Contexto

- Repositorio: `C:/Users/LAP/Desktop/VeterinariaSaaS`. Backend en `backend/` (Django 6, DRF, PostgreSQL; Python 3.13 global, sin venv). Frontend en `frontend/` (React 19, Vite, Vitest, pnpm; `node_modules` ya instalado).
- Rama de trabajo: `fix/orden-7-clinica` (la crea E00). Comprueba `git branch --show-current` antes de empezar.
- Contrato: `docs/plan-remediacion-orden-7-2026-11-12.md`. El prompt de tu entrega trae lo necesario; acude al plan solo ante una duda.
- Las decisiones del plan ya las tomó el usuario: no las reabras ni pidas confirmarlas.
- Shell: usa la herramienta Bash (Git Bash). Los comandos de este expediente están escritos para ella.

## 2. Método obligatorio

1. Lee cada archivo antes de editarlo.
2. Cada cambio de tu prompt trae un **texto actual** y un **texto nuevo**, o un archivo nuevo completo. Aplícalos en el orden en que aparecen, con la herramienta Edit (o Write para archivos nuevos). Cada texto actual aparece exactamente una vez en su archivo.
3. Copia los bloques tal cual: sangría, comillas, acentos y saltos de línea incluidos. Los archivos del repositorio usan CRLF en la copia de trabajo; la herramienta Edit lo resuelve, así que no reescribas archivos enteros para "normalizar".
4. No mejores nada que no esté pedido.
5. Tras editar un archivo Python, ejecuta `python -m py_compile <archivo>` desde `backend/`.
6. **Si un texto actual no existe, aparece más de una vez o el código significa otra cosa que lo que dice el prompt, detente.** No adivines: repórtalo con estado `BLOQUEADA`.
7. Si el mismo error persiste tras dos intentos, detente y repórtalo.
8. Usa el grafo `codebase-memory-mcp` si está disponible. Si falla, usa Grep y Read; no es motivo de bloqueo.

## 3. Prohibido

- Conectarte a la base habitual (`localhost:5432`, base `veterinaria_saas`) o a cualquier servidor remoto. **Nunca te conectes a `159.69.178.136`.** Toda prueba de backend va por `scripts/orden7_isolated.py`.
- Crear migraciones que tu prompt no trae, o ejecutar `makemigrations` sin `--check --dry-run`. Las tres migraciones del orden vienen escritas en los prompts.
- `git push`, PR, merge, rebase o despliegue. `--no-verify` o saltar hooks. `git add .` o `git add -A`.
- Instalar o actualizar dependencias (`pnpm install`, `pip install`), o tocar `requirements*.txt`, `requirements.lock`, `package.json` o `pnpm-lock.yaml`.
- Tocar `frontend/` fuera de E04 (E00 y E05 solo ejecutan sus pruebas), Docker, `docker-compose*.yml` o `scripts/release.sh`.
- Tocar el módulo de analítica. La única excepción es un argumento de un fixture de prueba en E03, que el prompt da escrito.
- Editar archivos que tu entrega no lista. La única excepción es un import roto por tu propio cambio, y debes declararlo.
- Borrar pruebas, añadir `skip`, debilitar aserciones o subir timeouts. Las únicas excepciones las nombra tu prompt.
- Ejecutar comandos en segundo plano (`run_in_background`). Todo en primer plano.
- Usar `date.today()` o `datetime.now()` sin zona en código nuevo (gate `test_calendar_rule_audit`).
- Reformatear, renombrar símbolos no pedidos o reordenar código que no tocas.

## 4. Base de datos aislada

Cluster exclusivo del orden 7: `~/AppData/Local/Temp/opencode/orden7_pg18_20261112`, loopback `127.0.0.1:49937`, usuario `orden7_runner`, base `orden7_iso_20261112` y base de pruebas `test_orden7_iso_20261112`. El runner `backend/scripts/orden7_isolated.py` verifica directorio, puerto y dirección de escucha antes de ejecutar nada, y se niega si no coinciden.

**Arrancarlo** (si `status` no dice que está en ejecución):

```bash
PG="/c/Program Files/PostgreSQL/18/bin"
DIR="$HOME/AppData/Local/Temp/opencode/orden7_pg18_20261112"
"$PG/pg_ctl.exe" -D "$DIR" status > /dev/null 2>&1 && echo corriendo || \
  "$PG/pg_ctl.exe" -D "$DIR" -o "-p 49937 -c listen_addresses=127.0.0.1" \
  -l "$HOME/AppData/Local/Temp/opencode/orden7_pg18.log" -w start > /dev/null 2>&1
"$PG/pg_ctl.exe" -D "$DIR" status > /dev/null 2>&1; echo "status exit=$?"
```

`status exit=0` significa en ejecución. **Nunca encadenes la salida de `pg_ctl start` a un pipe** (`| tail`, `| head`): postgres hereda la salida y el comando no termina.

**Si `pg_ctl status` dice que corre pero el runner falla al conectar** (`server closed the connection` o `connection timeout`): detenlo con `"$PG/pg_ctl.exe" -D "$DIR" -m fast -w stop > /dev/null 2>&1` y arráncalo otra vez con el bloque anterior. Si vuelve a fallar, `BLOQUEADA`.

## 5. Comandos de backend

Desde `backend/`, siempre en primer plano y con `timeout` de la herramienta en 600000 ms. El prefijo `rtk proxy` evita que la salida se recorte. **Cada llamada a la herramienta Bash abre un shell nuevo:** empieza cada llamada con `cd /c/Users/LAP/Desktop/VeterinariaSaaS/backend && R="rtk proxy python scripts/orden7_isolated.py"`, o `$R` estará vacío.

```bash
R="rtk proxy python scripts/orden7_isolated.py"

# Pruebas dirigidas (la base de pruebas se conserva entre corridas)
$R test <etiquetas> --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30

# Detalle de un fallo
$R test <etiqueta.del.test> --keepdb --noinput 2>&1 | tail -60

# Comprobaciones de proyecto
$R check 2>&1 | tail -3
$R makemigrations --check --dry-run 2>&1 | tail -3
$R migrate --noinput 2>&1 | tail -5

# Sintaxis de un archivo Python
python -m py_compile apps/ruta/archivo.py && echo "py_compile OK"
```

Las etiquetas de prueba van con ruta completa (`apps.core.tests.test_x`). Nunca uses la etiqueta suelta `apps.platform`: choca con el módulo `platform` de la librería estándar (deuda C7).

**Corrida amplia** (E00 y E05). En una sola llamada tardó 790 s en E00 y superó el límite de 600 s de la herramienta, que la pasó a segundo plano. Por eso va en **tres llamadas separadas**, cada una en primer plano, con su propio `cd` y `R=`:

```bash
# Llamada 1
$R test apps.core --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -40

# Llamada 2
$R test apps.users apps.organizations apps.legal apps.platform.tests.test_physical_deletion \
  apps.platform.tests.test_demo_purge_authorization apps.platform.tests.test_view_integration \
  apps.patients.tests.test_owner_phone_identity apps.inventory.tests.test_order4_alias_writers \
  --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -40

# Llamada 3
$R test apps.medical_records apps.prescriptions apps.billing \
  apps.analytics.tests.test_late_arrival_observability \
  --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -40
```

Las tres juntas cubren las mismas etiquetas que la corrida única de E00. El total es la **suma de los tres `Ran`**: dio **825 pruebas** sobre `bb5a070` y **852** con las cinco entregas aplicadas, siempre con `OK` (los `skipped` suman 7). Si la herramienta pasa alguna llamada a segundo plano pese a todo, espera a que termine, anota en evidencia cuál fue y no la marques `BLOQUEADA` por eso.

## 6. Comandos de frontend

Desde `frontend/`. `VITE_API_URL` es el mismo valor ficticio que usa CI: `src/api/client.js` lo exige al importarse.

```bash
cd /c/Users/LAP/Desktop/VeterinariaSaaS/frontend
VITE_API_URL=http://127.0.0.1:8000/api pnpm exec vitest run --maxWorkers=2 2>&1 | grep -E "Test Files|Tests  |FAIL" | head -20
pnpm run lint > /dev/null 2>&1; echo "lint exit=$?"
VITE_API_URL=http://127.0.0.1:8000/api pnpm run build > /dev/null 2>&1; echo "build exit=$?"
pnpm run smoke:urls 2>&1 | tail -2
```

En la validación en seco: 78 archivos y 846 pruebas sobre `bb5a070`; 79 y 851 con E04. `build` deja `frontend/dist/`, que git ignora.

`--maxWorkers=2` es deliberado. Con el paralelismo por defecto, en este equipo las pruebas de `src/pages/inbox/index.test.jsx` agotan su límite de 5000 ms: una vez en E00 y en 4 de 4 corridas en E04. Ninguna entrega del orden 7 toca ese archivo, y el código es el mismo que pasó en la validación en seco. CI conserva `pnpm run test`. No subas timeouts ni toques pruebas de Inbox.

## 7. Cierre de cada entrega

1. Ejecuta la verificación de tu prompt y conserva la salida real.
2. Actualiza `docs/remediaciones/orden-7/MATRIZ.md` (fila de tu entrega; estado del ID solo si la entrega lo cierra) y añade tu sección al final de `docs/remediaciones/orden-7/EVIDENCIA.md`, con la plantilla que ese archivo trae.
3. Comprueba `git status --short`: solo deben aparecer los archivos de tu entrega. Si aparece cualquier otro, no lo añadas y repórtalo.
4. Haz el commit con `git add <rutas explícitas>` y el mensaje de tu prompt. Añade al final las líneas de atribución que te indique tu entorno. Sin push.
5. Termina con este reporte y nada más:

```markdown
## Entrega E0X — COMPLETA | BLOQUEADA
Commit: <hash> | ninguno
Archivos: <lista>
Pruebas: <comando> → <Ran N / OK o fallos>
py_compile: <OK o no aplica>
Desviaciones: ninguna | <cuáles y por qué>
Para revisar: <lo que el usuario debe mirar, o "nada">
```

Si quedó `BLOQUEADA`, no hagas commit. Indica el paso, el texto o error exacto y qué hace falta para continuar.
