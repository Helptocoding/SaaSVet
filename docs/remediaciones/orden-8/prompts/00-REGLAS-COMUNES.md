# Reglas comunes del orden 8

Aplican a todas las entregas. Léelas completas antes de tocar nada.

## 1. Contexto

- Repositorio: `C:/Users/LAP/Desktop/VeterinariaSaaS`. Backend en `backend/` (Django 6, DRF, PostgreSQL; Python 3.13 global, sin venv).
- Rama de trabajo: `fix/orden-8-agente` (la crea E00). Comprueba `git branch --show-current` antes de empezar.
- Contrato: `docs/plan-remediacion-orden-8-2026-11-14.md`. El prompt de tu entrega trae lo necesario; acude al plan solo ante una duda.
- Las decisiones del plan ya las tomó el usuario: no las reabras ni pidas confirmarlas.
- Shell: usa la herramienta Bash (Git Bash). Los comandos de este expediente están escritos para ella.
- `docs/hector.py` es un archivo del usuario, ajeno al orden: puede aparecer como no rastreado. No lo añadas, no lo muevas y no lo borres.

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

- Conectarte a la base habitual (`localhost:5432`, base `veterinaria_saas`) o a cualquier servidor remoto. **Nunca te conectes a `159.69.178.136`.** Toda prueba de backend va por `scripts/orden8_isolated.py`.
- Hablar con un proveedor LLM real. El runner vacía `AGENT_LLM_*`; las pruebas usan `StubLLMClient` o no llegan al modelo.
- Crear migraciones que tu prompt no trae, o ejecutar `makemigrations` sin `--check --dry-run`. La única migración del orden viene escrita en E01.
- `git push`, PR, merge, rebase o despliegue. `--no-verify` o saltar hooks. `git add .` o `git add -A`.
- Instalar o actualizar dependencias (`pnpm install`, `pip install`), o tocar `requirements*.txt`, `requirements.lock`, `package.json` o `pnpm-lock.yaml`.
- Tocar `frontend/`, Docker, `docker-compose*.yml`, `scripts/release.sh` o el módulo de analítica.
- Editar archivos que tu entrega no lista. La única excepción es un import roto por tu propio cambio, y debes declararlo.
- Borrar pruebas, añadir `skip`, debilitar aserciones o subir timeouts. Las únicas excepciones las nombra tu prompt.
- Ejecutar comandos en segundo plano (`run_in_background`). Todo en primer plano.
- Usar `date.today()` o `datetime.now()` sin zona en código nuevo (gate `test_calendar_rule_audit`).
- Reformatear, renombrar símbolos no pedidos o reordenar código que no tocas.

## 4. Base de datos aislada

Cluster exclusivo del orden 8: `~/AppData/Local/Temp/opencode/orden8_pg18_20261114`, loopback `127.0.0.1:49938`, usuario `orden8_runner`, base `orden8_iso_20261114` y base de pruebas `test_orden8_iso_20261114`. El runner `backend/scripts/orden8_isolated.py` verifica directorio, puerto y dirección de escucha antes de ejecutar nada, y se niega si no coinciden.

**Arrancarlo** (si `status` no dice que está en ejecución):

```bash
PG="/c/Program Files/PostgreSQL/18/bin"
DIR="$HOME/AppData/Local/Temp/opencode/orden8_pg18_20261114"
"$PG/pg_ctl.exe" -D "$DIR" status > /dev/null 2>&1 && echo corriendo || \
  "$PG/pg_ctl.exe" -D "$DIR" -o "-p 49938 -c listen_addresses=127.0.0.1" \
  -l "$HOME/AppData/Local/Temp/opencode/orden8_pg18.log" -w start > /dev/null 2>&1
"$PG/pg_ctl.exe" -D "$DIR" status > /dev/null 2>&1; echo "status exit=$?"
```

`status exit=0` significa en ejecución. **Nunca encadenes la salida de `pg_ctl start` a un pipe** (`| tail`, `| head`): postgres hereda la salida y el comando no termina.

**Si `pg_ctl status` dice que corre pero el runner falla al conectar** (`server closed the connection` o `connection timeout`): detenlo con `"$PG/pg_ctl.exe" -D "$DIR" -m fast -w stop > /dev/null 2>&1` y arráncalo otra vez con el bloque anterior. Si vuelve a fallar, `BLOQUEADA`.

## 5. Comandos de backend

Desde `backend/`, siempre en primer plano y con `timeout` de la herramienta en 600000 ms. El prefijo `rtk proxy` evita que la salida se recorte. **Cada llamada a la herramienta Bash abre un shell nuevo:** empieza cada llamada con `cd /c/Users/LAP/Desktop/VeterinariaSaaS/backend && R="rtk proxy python scripts/orden8_isolated.py"`, o `$R` estará vacío.

```bash
R="rtk proxy python scripts/orden8_isolated.py"

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

Las etiquetas de prueba van con ruta completa (`apps.agent.tests.test_x`). No corras `apps.agent` ni `apps.channels` completos: tardan mucho más que los 10 minutos de la herramienta, y sus suites de procesos (B3, B8, B9, el simulacro de restauración de media) exigen una base `test_ci_*` y configuración de CI, así que localmente fallan por diseño con `Recognized isolated loopback PostgreSQL required`. Las cubre CI.

**Corrida de referencia** (E00 y E03). Dos llamadas separadas, cada una en primer plano, con su propio `cd` y `R=`:

```bash
# Llamada A — TurnDecision, árbitro, B3 local y corpus de regresión
$R test apps.agent.tests.test_turn_decision apps.agent.tests.test_contracts \
  apps.agent.tests.test_arbiter apps.agent.tests.test_b3_durable \
  apps.agent.tests.test_regression_suite apps.agent.tests.test_corpus_conversacional \
  --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -40

# Llamada B — planner, regresiones, disponibilidad y resultados tipados
$R test apps.agent.tests.test_planner apps.agent.tests.test_regression_f2 \
  apps.agent.tests.test_w0_hardening apps.agent.tests.test_w1_experience \
  apps.agent.tests.test_slots apps.agent.tests.test_b2_results \
  apps.agent.tests.test_intake_capabilities apps.agent.tests.test_b6_binding \
  --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -40
```

Referencia sobre `c71c0ed`: **A = 103** pruebas `OK`, **B = 242** `OK (skipped=1)`. Con E01 aplicado, A = 107; con E02, B = 246. Si la herramienta pasa alguna llamada a segundo plano (el equipo está cargado y una llamada que tardó 3 minutos puede tardar más de 10), espera a que termine, anota en evidencia cuál fue y no la marques `BLOQUEADA` por eso.

**Si una corrida se interrumpe** (la herramienta o el sistema la detiene a medias), la base de pruebas queda con filas de un `TransactionTestCase` sin limpiar, y la siguiente corrida da decenas de `ERROR`/`FAIL` en `test_b3_durable.B3LocalIntegrationTests` que no tienen que ver con tu cambio. Límpiala antes de seguir, con un módulo cuyas pruebas vacían la base al terminar:

```bash
$R test apps.agent.tests.test_b3_durable.DurableTurnTests --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Después repite la corrida que falló. Si vuelve a fallar, es real: `BLOQUEADA`.

## 6. Cierre de cada entrega

1. Ejecuta la verificación de tu prompt y conserva la salida real.
2. Actualiza `docs/remediaciones/orden-8/MATRIZ.md` (fila de tu entrega; estado del ID solo si la entrega lo cierra) y añade tu sección al final de `docs/remediaciones/orden-8/EVIDENCIA.md`, con la plantilla que ese archivo trae.
3. Comprueba `git status --short`: solo deben aparecer los archivos de tu entrega (y `docs/hector.py`, que no se toca). Si aparece cualquier otro, no lo añadas y repórtalo.
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
