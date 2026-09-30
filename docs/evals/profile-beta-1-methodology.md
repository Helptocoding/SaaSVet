# B9E — metodología del ensayo temporal

Contrato congelado: `profile-beta-1-v1.json` (autoridad §7:721–725). Runner: `backend/apps/agent/tests/b9e_profile.py`. PostgreSQL 16.15 local aislado, `fsync=on`, `synchronous_commit=on` y nombre `test_*`. Cada variante usa una base clonada de una plantilla migrada sin organizaciones. `seed_domain` B9A crea solo fixtures test; el webhook firmado crea cada conversación y mensaje. El ingreso conserva el debounce real de 8 s; el runner no adelanta `available_at` para la carga temporal.

Tres procesos Python/DB independientes ejecutan ciclos reales de `run_agent_worker --once`: dos `planner` y un `sender`, `batch=1`, pausa/poll de 1 s. Ninguna herramienta de negocio, sender ni guard se sustituye. Se intercepta exclusivamente `requests.Session.request` para LLM/Meta `.invalid` y loopback Django Client de la API interna. Cada llamada LLM dura 0,5 s; la petición READ HTTP interna suma 0,1 s; cada aceptación Meta base 0,2 s. El fake devuelve usage determinista y falla ante cualquier otro destino o IO externo bajo transacción. La aplicación real hace dos llamadas LLM por la READ pública; se conserva ese hecho como desviación, no se esconde en la medición.

La emisión usa tiempo monotónico: 30 s de calentamiento, después 300 s de ventana. Cada organización sana recibe un inbound cada 10 s; la ruidosa uno cada segundo a contactos/conversaciones distintos. En base/bloqueado/Meta/duplicado, cada tercer inbound sano es guidance detectable en recepción; en la variante saturación lo son todos. El bloqueo LLM se activa una vez en la organización ruidosa, tras comenzar la medición, dura 10 s y produce `requests.Timeout`. Meta lento tarda 2 s por aceptación. El duplicado repite cada vigésimo webhook ruidoso con el mismo wamid/HMAC. La variante saturación conserva la tasa ruidosa mientras prioriza guidance en los sanos. Todas las variantes terminan con 20 s de observación/drenaje; ese tiempo no añade nuevas muestras de ingreso.

Los p95 se calculan sobre deltas de timestamps durables PostgreSQL: `Message(IN).created_at → TurnWork.claimed_at`, `Message(OUT safety).created_at → send_admitted_at`, y `Message(OUT).created_at → send_admitted_at`. El percentil usa el valor ordenado en índice `ceil(0,95 × (n−1))` (método *higher*); se publican denominadores, máximos y faltantes. Un inbound sano sin claim o outbound sin admission al cerrar la observación no pasa el gate aplicable. Safety se identifica por `semantic_type`, no por texto de respuesta. Las colas pending y capacidad por organización se muestrean cada 5 s; sus máximos son **observados**, no picos entre muestras. B9C conserva la prueba PostgreSQL de exclusión en procesos independientes.

Gates canónicos: base y LLM bloqueado, p95 sano ≤10 s y safety ≤5 s; solo base, outbox ≤5 s. Meta lento exige durabilidad, concurrencia acotada y ausencia de retry ciego, sin SLO de latencia equivalente. Duplicado y saturación comprueban su invariante propia. `technical_pass` de un recibo temporal es el resultado **de esa variante**, no de PROFILE-BETA-1 integral. El perfil integral exige además corpus sin violaciones, READ/WRITE, COST/SCALE, checks y regresiones exactas; nunca se infiere PASS por un subconjunto.

El ensayo no incluye sockets de Meta reales, TLS/proxy, modelo comercial ni cargas mayores o lenguaje clínico arbitrario. La salida `sent` prueba aceptación simulada, no delivered/read. La evaluación real de modelo al promover autonomía es un artefacto posterior con responsable; el componente histórico `agent_eval` planner-only que puede hacer skip no sirve como gate. El perfil no define fairness fuerte ni precio monetario. Los recibos no contienen mensajes, teléfonos, prompts, responses ni secretos.

## Repetición desde el candidato documentado

Usar Python 3.13 con `backend/requirements.lock` y PostgreSQL 16.15. La ejecución
original utilizó `C:\Users\LAP\AppData\Local\Temp\vet-b8b-locked\Scripts\python.exe`;
su versión exacta y paquetes están en `profile-beta-1-final.json`. Crear una
instancia local nueva, usuario de test `b9e`, puerto 35439, sin acceso productivo,
con `fsync=on` y `synchronous_commit=on`. Migrar una plantilla vacía y clonar
una base distinta para cada fila siguiente antes de ejecutar. El runner rechaza
base que no sea PostgreSQL local `test_*` o durabilidad deshabilitada.

| Scenario | DB original | Receipt original |
| --- | --- | --- |
| base | test_b9e_profile | b9e-first-base.json |
| blocked_llm | test_b9e_blocked | b9e-first-blocked.json |
| meta_slow | test_b9e_meta | b9e-first-meta.json |
| duplicate | test_b9e_duplicate | b9e-first-duplicate.json |
| saturation | test_b9e_saturation | b9e-first-saturation.json |

Desde `backend`, con intérprete del entorno bloqueado, definir en la sesión de
test `DATABASE_URL=postgresql://b9e@127.0.0.1:35439/DB_DE_LA_FILA`,
`SECRET_KEY` desechable, `DEBUG=False`, `ENVIRONMENT=dev`,
`DISABLE_SENTRY=True`, y vacíos `SENTRY_DSN`, `REDIS_URL`,
`DISCORD_WEBHOOK_URL`. Los comandos ejecutados siguen estas formas (usar
**ruta absoluta nueva** para no sobrescribir recibos conservados):

```powershell
rtk proxy python -m apps.agent.tests.b9e_profile --scenario base --output RUTA_ABSOLUTA_NUEVA.json
rtk proxy python -m apps.agent.tests.b9e_profile --scenario blocked_llm --output RUTA_ABSOLUTA_NUEVA.json
rtk proxy python -m apps.agent.tests.b9e_profile --scenario meta_slow --output RUTA_ABSOLUTA_NUEVA.json
rtk proxy python -m apps.agent.tests.b9e_profile --scenario duplicate --output RUTA_ABSOLUTA_NUEVA.json
rtk proxy python -m apps.agent.tests.b9e_profile --scenario saturation --output RUTA_ABSOLUTA_NUEVA.json
rtk proxy python -m apps.agent.tests.run_b9a_acceptance --suite targeted --database test_b8b_b9e_corpus --ids-file RUTA_ABSOLUTA_b9e-corpus-selected.json --output PREFIJO_ABSOLUTO_NUEVO
rtk proxy python -m apps.agent.tests.run_b9a_acceptance --suite checks --database test_b8b_b9e_corpus --output PREFIJO_ABSOLUTO_NUEVO
```

El collector `b9e_collect` se ejecutó antes de retirar las DBs, desde el mismo
entorno, con `--repository` raíz absoluta, `--port 35439` y `--output` nuevo.
Lee las cinco bases y cruza LLMCall, TurnWork y Message, sin mutarlas. El corpus
primero usa `b9e-corpus-selected.json`; la recuperación utilizó solo los tres
IDs de `b9e-corpus-recovery-selected.json`, tras restablecer PostgreSQL. En una
repetición normal se ejecutan los 46 IDs completos. No usar `--smoke` como
aceptación: reduce 30/300 s a 2/10 s y el recibo marca `smoke_only=True`.

Conservar recibos nuevos, logs y hashes; comprobar conexiones/locks/prepared
transactions, eliminar solo las bases propias y detener/retirar la instancia
temporal. El informe actual declara la diferencia de dos llamadas reales y la
ausencia de copia byte a byte del runner anterior al primer run. Repetir la
fuente final permite evaluar la ruta documentada; no reconstruye una fuente
histórica perdida ni convierte el primer resultado en reproducción exacta del
modelo de una llamada.

Los logs crudos B9E conservan sus bytes originales, incluidos CRCRLF emitidos
por subprocesses Windows. `.gitattributes` conserva los bytes de los recibos
`docs/evals/b9e-*` y `profile-beta-1-*`, y marca los logs B9E `-diff`; Git no
normaliza su evidencia ni interpreta sus retornos de carro como whitespace de
código. Los hashes siempre cubren los bytes guardados. Los helpers B9E usan LF;
código, JSON y documentos mantienen el check normal de contenido. Los hashes
de fuentes existentes tienen además una proyección normalizada CRLF→LF para
comparación entre plataformas; los hashes originales de journals son locales.
