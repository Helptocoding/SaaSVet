# Reglas comunes del orden 6

Aplican a todas las entregas. Léelas completas antes de tocar nada.

## 1. Contexto

- Repositorio: `C:/Users/LAP/Desktop/VeterinariaSaaS`. Backend en `backend/`: Django 6, DRF, PostgreSQL. Python 3.13 global (no hay venv).
- Rama de trabajo: `fix/orden-6-arquitectura-backend` (la crea E00). Comprueba `git branch --show-current` antes de empezar.
- Contrato: `docs/plan-remediacion-orden-6-2026-11-11.md`. El prompt de tu entrega trae lo necesario; acude al plan solo ante una duda.
- Las decisiones del plan ya las tomó el usuario: no las reabras ni pidas confirmarlas.
- Shell: usa la herramienta Bash (Git Bash). Los comandos de este expediente están escritos para ella.

## 2. Método obligatorio

1. Lee cada archivo antes de editarlo.
2. Los números de línea corresponden a `a7dbdaf` y se desplazan. Localiza por símbolo o por el texto citado.
3. Haz exactamente los pasos de tu entrega, en orden. No mejores nada que no esté pedido.
4. Tras editar un archivo Python, ejecuta `python -m py_compile <archivo>` desde `backend/`.
5. **Si un texto citado no existe, o el código significa otra cosa que lo que dice el prompt, detente.** No adivines: repórtalo con estado `BLOQUEADA`.
6. Si el mismo error persiste tras dos intentos, detente y repórtalo.
7. Usa el grafo `codebase-memory-mcp` si está disponible. Si falla, usa Grep y Read; no es motivo de bloqueo.

## 3. Prohibido

- Conectarte a la base habitual (`localhost:5432`, base `veterinaria_saas`) o a cualquier servidor remoto. **Nunca te conectes a `159.69.178.136`.** Toda prueba va por `scripts/orden6_isolated.py`.
- Crear, editar o borrar archivos bajo `migrations/`. Ninguna entrega cambia modelos.
- `git push`, PR, merge, rebase o despliegue. `--no-verify` o saltar hooks. `git add .` o `git add -A`.
- Instalar o actualizar dependencias, o tocar `requirements*.txt` / `requirements.lock`.
- Tocar `frontend/`, Docker, `docker-compose*.yml` o `scripts/release.sh`.
- Editar archivos que tu entrega no lista. La única excepción es un import roto por tu propio cambio, y debes declararlo.
- Borrar pruebas, añadir `skip`, debilitar aserciones o subir timeouts. Las únicas excepciones las nombra tu prompt.
- Ejecutar comandos en segundo plano (`run_in_background`). Todo en primer plano.
- Usar `date.today()` o `datetime.now()` sin zona en código nuevo (gate `test_calendar_rule_audit`).
- Reformatear, renombrar símbolos no pedidos o reordenar código que no tocas.

## 4. Base de datos aislada

Cluster exclusivo del orden 6: `~/AppData/Local/Temp/opencode/orden6_pg18_20261111`, loopback `127.0.0.1:49936`, usuario `orden6_runner`, base `orden6_iso_20261111` y base de pruebas `test_orden6_iso_20261111`. El runner `backend/scripts/orden6_isolated.py` verifica directorio, puerto y dirección de escucha antes de ejecutar nada, y se niega si no coinciden.

**Arrancarlo** (si `status` no dice que está en ejecución):

```bash
PG="/c/Program Files/PostgreSQL/18/bin"
DIR="$HOME/AppData/Local/Temp/opencode/orden6_pg18_20261111"
"$PG/pg_ctl.exe" -D "$DIR" status > /dev/null 2>&1 && echo corriendo || \
  "$PG/pg_ctl.exe" -D "$DIR" -o "-p 49936 -c listen_addresses=127.0.0.1" \
  -l "$HOME/AppData/Local/Temp/opencode/orden6_pg18.log" -w start > /dev/null 2>&1
"$PG/pg_ctl.exe" -D "$DIR" status > /dev/null 2>&1; echo "status exit=$?"
```

`status exit=0` significa en ejecución. **Nunca encadenes la salida de `pg_ctl start` a un pipe** (`| tail`, `| head`): postgres hereda la salida y el comando no termina.

**Si `pg_ctl status` dice que corre pero el runner falla al conectar** (`server closed the connection` o `connection timeout`): detenlo con `"$PG/pg_ctl.exe" -D "$DIR" -m fast -w stop > /dev/null 2>&1` y arráncalo otra vez con el bloque anterior. Si vuelve a fallar, `BLOQUEADA`.

## 5. Comandos

Desde `backend/`, siempre en primer plano y con `timeout` de la herramienta en 600000 ms. El prefijo `rtk proxy` evita que la salida se recorte. **Cada llamada a la herramienta Bash abre un shell nuevo:** empieza cada llamada con `cd /c/Users/LAP/Desktop/VeterinariaSaaS/backend && R="rtk proxy python scripts/orden6_isolated.py"`, o `$R` estará vacío.

```bash
R="rtk proxy python scripts/orden6_isolated.py"

# Pruebas dirigidas (la base de pruebas se conserva entre corridas)
$R test <etiquetas> --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30

# Detalle de un fallo
$R test <etiqueta.del.test> --keepdb --noinput 2>&1 | tail -60

# Comprobaciones de proyecto
$R check 2>&1 | tail -3
$R makemigrations --check --dry-run 2>&1 | tail -3

# Sintaxis de un archivo Python
python -m py_compile apps/ruta/archivo.py && echo "py_compile OK"
```

Las etiquetas de prueba van con ruta completa (`apps.core.tests.test_x`). Nunca uses la etiqueta suelta `apps.platform`: choca con el módulo `platform` de la librería estándar (deuda C7).

**Corrida amplia de referencia** (E00 y E06): `apps.core apps.users apps.organizations apps.prescriptions apps.billing`. El 11-11 sobre `a7dbdaf` dio **586 pruebas, OK (skipped=7)** en unos 4 minutos.

## 6. Cierre de cada entrega

1. Ejecuta la verificación de tu prompt y conserva la salida real.
2. Actualiza `docs/remediaciones/orden-6/MATRIZ.md` (fila de tu entrega; estado del ID solo si la entrega lo cierra) y añade tu sección al final de `docs/remediaciones/orden-6/EVIDENCIA.md`, con la plantilla que ese archivo trae.
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
