"""Render the Spanish report from measured numbers, without executing workloads."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'docs/evals/e4-claim'
REPORT = ROOT/'docs/diagnostico-e4-eligible-claim-2026-09-30.md'


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def table(headings, rows):
    return '\n'.join(['| '+' | '.join(headings)+' |','| '+' | '.join(['---']*len(headings))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n'


def main():
    summary = read('summary.json')
    measurements = summary['measurements']
    b=measurements['postfix-final-base']; x=measurements['postfix-final-blocked']
    green=summary['performance_state']=='DIAGNOSTIC_GATE_GREEN'
    sections = []
    def add(text):
        sections.append(text.strip()+'\n')

    add(f'''# E4 — diagnóstico y mejora acotada de eligible→claim · 2026-09-30

ROOT_CAUSE_CONFIRMED. Una sola mejora E4 implementada en el selector advisory.
Estado de rendimiento: {summary['performance_state']}. Diagnóstico final base
{b['healthy_claim']['p95_seconds']:.6f} s y blocked {x['healthy_claim']['p95_seconds']:.6f} s;
márgenes {b['margin']:+.6f} s y {x['margin']:+.6f} s.
Esto {'habilita considerar un candidato después de verificar regresiones' if green else 'obliga a PERFORMANCE_STOP sin otro fix ni rerun formal'};
no declara PASS integral de PROFILE-BETA-1. No se ejecutó su rerun
formal en este encargo. B9 sigue IN_PROGRESS; B9E y PROFILE histórico siguen FAIL.
STOP después de esta mejora; no segundo tuning, deploy ni activación.

Baseline exacto verificado antes de comenzar:
`f051c27002986193772ced0fb1e00e19822d26ef`. Cambios preexistentes en documentos de
deploy, skills-lock y dos documentos de auditoría se excluyen de ambos commits.
La raíz [e4-claim](evals/e4-claim/) conserva recibos, journals, SQL plans,
inventario por ID, fuentes y hashes. [summary.json](evals/e4-claim/summary.json)
consolida los números; las mediciones crudas permanecen separadas.

## Causa y autoridad

El generador persiste org 0 antes de org 1. Sus deadlines son ligeramente
anteriores. KEEP ordena por último claim durable de la organización, actividad e
ID: la org 0 recibe normalmente el primer planner disponible y vuelve a tener un
claim anterior al de org 1. Ambos planners sirven ambas organizaciones; no hay
afinidad fija por tenant. Cuando el otro planner ya inició noisy poco antes de
READY, su servicio real de aproximadamente dos segundos, seguido de la pausa
externa de aproximadamente un segundo y batch=1, deja a org 1 esperando su
siguiente oportunidad. La consulta ya puede haber observado org 1 junto con org
0: observar no equivale a disponer de otro planner libre.

El gate [root-cause-gate.json](evals/e4-claim/root-cause-gate.json) se escribió
antes del cambio runtime. Se consultó E4 canónico §7/E4, contratos e implementación
B3/B9B/B9C, worker/planner/command, metodología y runner v1, evidencia monotonic
y diagnóstico/capacidad anteriores. La coordinación y selección están en E4;
la autoridad sigue siendo el claim B3 con exclusión B9C en PostgreSQL. No se
cambió contrato, quiet window 8 s, hard cap 25 s, persistencia ni metodología.

## Método y límites de los timestamps

Cada diagnóstico relevante usa 30 s warmup, 300 s medición y 20 s drain; dos
procesos planner y uno sender, batch=1, poll/pausa=1 s, intervalos 10/10/1 s.
LLM fake 0.5 s por llamada, READ HTTP 0.1 s y Meta 0.2 s. La ruta READ ejecuta
las **dos llamadas reales**; no se reemplaza run_turn ni se simula un solo call.
PostgreSQL 16.15 local, fsync=on y synchronous_commit=on. Las regresiones corren
después de terminar las mediciones, en otras bases.

El runner original invoca `call_command(run_agent_worker, once=True, role=...,
batch=1, poll=1)` y después `time.sleep(1)` incondicional externo. Por eso
start→start incluye servicio más pausa; poll no aporta exactamente 1 s de
eligible→claim en cada muestra. Se conservan originales runner, v1 y metodología,
con hashes iguales al baseline en [validation.json](evals/e4-claim/validation.json).
El driver de este estudio reutiliza el harness diagnóstico, sin modificar el
runner formal ni hacer acceptance con ablations.

T0 es Message.created_at, timestamp durable de persistencia contractual, no una
medición independiente del retorno COMMIT del webhook. T1=max(T0, available_at),
NULL→T0; usar max evita deltas negativos cuando un inbound se une a READY previo.
T2 es el siguiente inicio global de planner relevante; se conserva también
winning_planner_start y si una selección ya estaba en curso al llegar T1.
T3 es la primera observación de esa conversación; T4 la selección del intento
ganador. Si el mensaje llegó después de una observación de su READY, se marca
joined_after_candidate_observation, sin inventar un nuevo evento por mensaje.
T6 mide retorno de Atomic.__enter__, inicio del contexto de transacción Django;
no es una captura wire de BEGIN PostgreSQL. T5 es la petición SQL del lock de
Organization y ocurre después de T6. T7 es TurnWork.claimed_at durable. T8 es el
retorno del claim después del bloque atomic, incluidos callbacks/logging: cota
superior del retorno commit, no latencia pura de COMMIT.

Cada analysis.json incluye las **60 timelines sanas**: 40 ordinarias con T0–T8 e
identidad de planner y 20 safety de recepción con T0/T1/T7. Para safety, los
campos de planner/selección T2–T4 no aplican y T5/T6/T8 están en null: el driver
no instrumenta los locks ni la transacción del proceso receptor. Es una
limitación explícita de cobertura de trazas, no timestamps estimados ni ausencia
de transacción safety. Los p95 son higher: índice ceil(.95×(n−1)). El gate global
incluye las 60 muestras contractuales; los desgloses ordinarios usan 20 por org.
No se suman percentiles de componentes para reconstruir el p95 global.

Un primer baseline-base terminó la carga pero falló al cerrar el collector:
QuerySet.explain produjo EXPLAIN anidado en la query Window de Django. No tiene
recibo ni resultado de gate. Se conservan logs/journals y attempts.json; se
corrigió solamente el collector para explicar SELECT compilado con parámetros
y se ejecutó baseline-base-v2 en otra base. No fue una repetición para buscar un
resultado favorable.

Los primeros post-fix (postfix-base/postfix-blocked, 9.456556/9.322675 s)
midieron el prototipo sin exención de safety. No son los resultados finales.
La regresión inicial ejecutó 774 IDs: 773 PASS y YIELD08 FAIL por flag B5
deshabilitado en la fixture. Corregida la fixture, el nuevo YIELD09 expuso un
defecto real: W1 termina deferred_to_new_input y la safety pendiente de W2
queda retenida por el forecast. Se conservan ambos probes fallidos y el probe
posterior PASS. La misma política E4 se acotó eximiendo conversaciones con
safety pendiente; B3/B5 y elegibilidad no se editaron. Esta corrección justifica
dos nuevas mediciones completas (postfix-final-base/postfix-final-blocked) y
la revalidación afectada. No se repiten para escoger un percentil favorable.
[refinement.json](evals/e4-claim/refinement.json) conserva alcance y hashes.''')

    add('## Timelines reales por organización\n\nSegundos relativos a T0; selección de la muestra con mayor eligible→claim de cada org y escenario.')
    timeline_rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        for org in measurements[label]['organizations']:
            t=org['example']
            timeline_rows.append([label,org['org'],t['message'],t['work'],f"{t['planner']}/{t['poll']}"]+
                [f"{t['T'+str(i)]-t['T0']:.6f}" for i in range(9)])
    add(table(['Escenario','Org','Message','Work','Planner/poll']+[f'T{i}' for i in range(9)],timeline_rows))
    add('''Ejemplo causal blocked antes del fix, org 1 / Message 421 / Work 131:
T1=7.943504; planner-1 está en pausa externa, arranca T1+0.436566,
observa org 0 y org 1 y toma org 0. Planner-2 está sirviendo noisy hasta
T1+1.598483 y después pausa 1.003681: arranca T1+2.602164. Selecciona
org 1 en 10.570163 y claimed_at=10.588053. Su tramo final T4→T7 es
17.890 ms. Org 1 fue observada antes, pero no había otro planner disponible.
No hubo candidate miss de org 1 en ese ejemplo.

Los intervalos de su espera 2.644549 s se particionan, sin doble conteo:
external_pause+service 0.967515; selection+service 0.100215;
service+service 1.061702; external_pause+external_pause 0.472732;
external_pause+selection 0.042385. Suman 2.644549 s. No equivalen a sumar
percentiles marginales ni separan causalmente todo coste CPU/DB.

Ejemplo base antes del fix, org 1 / Message 523 / Work 169: planner-2
observa ambas healthy en T1+0.505183 y toma org 0; planner-1 acaba noisy
en T1+1.637225, espera 1.014091 y arranca T1+2.651316. Claim de org 1
T1+2.780967. Nuevamente el coste grande está antes de la selección ganadora.
Las tablas incluyen también org 0 y las muestras posteriores, y los journals
conservan todas las oportunidades y fases por mensaje.''')
    add('''El mayor EC final blocked corresponde a Message351/Work104, org1:
T1=7.921937; planner2/poll122 inicia T1+0.357968, observa ambas healthy y
reclama org0. Planner1/poll112 inicia T1+1.604657, observa [org1,noisy],
intenta org1 a T0+9.826194 y retorna miss a T0+9.857030. Su SQL con lock
Organization tarda 3.104 ms y Conversation 4.522 ms, ambos SKIP LOCKED;
no llega a un SQL con lock TurnWork en ese intento. Inmediatamente hace
fallback a noisy. Planner2 termina org0 y pausa 1.024526 s, vuelve en
T0+11.585924 y reclama org1 en T0+11.996844 (EC=4.074907 s).

Message367 se incorpora a la misma conversación en T0+9.920549 y conserva
exactamente el deadline anterior. La cercanía al miss es compatible con el
lock de ingestión; **el holder no se instrumentó**, por lo que no se afirma
como causa demostrada. No había otro work PROCESSING de org1 en los intervalos
durables reconstruidos. La evidencia sí demuestra miss, fallback y servicio+
pausa posteriores: no una espera SQL de cuatro segundos, no abandono de un
Y sano disponible, ni reextensión del deadline. La query más cara y esta cola
residual son riesgos; no se añade una segunda corrección ni se declara que
todo tail por organización mejoró.''')

    add('## Planners, cadencia y oportunidades\n\nClaims y tiempo dentro de ciclos cubren warmup/medición/drain; las latencias sanas cubren solo el cohort de ingreso de medición. Busy aquí es tiempo dentro de un ciclo, incluida selección, no solo LLM. Idle es intervalo entre ciclos.')
    rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        for p in measurements[label]['planners']:
            counts=p['claims_by_org']
            rows.append([label,p['role'],p['cycles'],'/'.join(str(counts.get(str(i),0)) for i in range(3)),
                f"{p['busy_seconds']:.3f}",f"{p['idle_seconds']:.3f}",f"{p['start_to_start']['p95']:.6f}",
                f"{p['completion_to_next_start']['p95']:.6f}",f"{p['eligible_to_next_opportunity']['p95']:.6f}",p['misses']])
    add(table(['Run','Planner','Ciclos','Claims org0/1/2','Busy s','Idle s','Start→start p95 s','Completion→next p95 s','T1→siguiente inicio propio p95 s','Misses'],rows))
    add('Los PIDs OS y backend PostgreSQL están en cada recibo. Las oportunidades propias de cada planner son su siguiente inicio estricto tras T1. La oportunidad global permite 0 si ya había una selección en curso capaz de observar esa conversación.')
    rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        for o in measurements[label]['organizations']:
            m=o['metrics']
            rows.append([label,o['org']]+[f"{m[f]['p95']:.6f}" for f in ('eligible_to_next_opportunity',
                'eligible_to_candidate','candidate_to_claim','selected_to_claim')]+[o['both_busy']])
    add(table(['Run','Org','T1→oportunidad global p95','T1→T3 p95','T3→T7 p95','T4→T7 p95','Ambos busy en T1 /20'],rows))
    add('''No existe un coste fijo “poll=1 cuesta 1 s”. En base previo org 1 tuvo
12/20 muestras con dos inicios globales antes de claim; org 0 tuvo 19/20 con
uno. Ambos busy exactamente en T1: base 0/20 y blocked 1/20 para org 1;
no explica solo toda la asimetría. Sí hay periodos con ambos sirviendo después
de que la primera healthy tome un planner, como los 1.061702 s del ejemplo.
El bloqueo inyectado produce un ciclo de 11.524455 s antes del fix y
11.245110 s en el prototipo posterior; no se eliminó ni acortó el timeout real.''')

    add('## Selector, duplicación e hipótesis\n\nKEEP ya excluye busy antes de limit, toma una conversación por org, ordena recencia durable y devuelve hasta tres candidatos. El loop ya reintenta un miss dentro del mismo poll; batch=1 limita trabajos exitosos, no intentos. Los snapshots completos con orden/selecciones/READY/PROCESSING están en candidate_cases/cycles de cada analysis.json.')
    rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        v=measurements[label]
        rows.append([label,v['both_healthy_ready_snapshots'],v['noisy_first_with_healthy_ready'],v['misses'],
            v['misses_with_subsequent_claim'],v['near_ready_noisy_applicable'],v['near_ready_noisy_applicable_claims']])
    add(table(['Run','Ambas healthy READY snapshots','Noisy primero con healthy READY','Misses','Miss→claim mismo ciclo','Noisy near-ready aplicable','De éstos con claim noisy'],rows))
    add('''En baseline base, dos misses de healthy org 0 terminan tomando org 1 en
el mismo ciclo; los otros 17 misses son noisy sin Y sano disponible. En blocked
previo los siete misses son noisy. Se descarta el patrón “pierde X, ignora Y
ya observado y desperdicia un ciclo”. No se añadió el retry que ya existía.
Tampoco hay noisy primero cuando healthy ya es READY; el residual es iniciar
noisy poco **antes** del deadline sano. Busy elimina una org PROCESSING del
snapshot, y una carrera posterior se revalida bajo claim; snapshot no reserva.

La detección near-ready usa el inicio de petición SQL, persistencia, deadline
≤1 s, org futura idle y recencia menor/null frente a la org seleccionada. Esa
hora es una aproximación cliente al snapshot PostgreSQL, no su timestamp wire.
En el prototipo hubo cero selecciones aplicables. En postfix-base quedó un intento noisy
con deadline a menos de un segundo de T4, pero el SQL tardó 0.251370 s: al
iniciar SQL el deadline estaba fuera del horizonte. Además fue miss, no claim.
No se confunde esa observación tardía con una violación del mecanismo. La
semántica exacta de la query se prueba con relojes controlados en PostgreSQL.''')
    hypotheses=[
        ['H1 cadence','Pausa externa p95 ≈1.02 s; timeline suma servicio+pausa','T1→siguiente oportunidad varía; no cuesta 1 s fijo','Amplificador directo del tail; confirmado'],
        ['H2 duplicación','19/7 misses baseline base/blocked; snapshots simultáneos','KEEP hace fallback; 2 healthy misses toman la otra org en mismo poll','Existe carrera pero ciclo perdido con Y disponible descartado'],
        ['H3 batch=1','Un éxito termina ciclo; segunda org requiere otro planner/oportunidad','Ablation batch3 ayuda pero no es acceptance; batch no limita retries','Restricción/topología contribuye; se conserva'],
        ['H4 noisy HOL residual','3/9 claims noisy justo antes de READY aplicables; no-noisy reduce EC','0 noisy primero con healthy ya READY','Preocupación de capacidad previa a READY confirmada; mecanismo elegido'],
        ['H5 ambos busy','Ejemplo 1.061702 s de servicio+servicio tras claim org0','En T1 casi nunca ambos busy; no explica solo la asimetría','Estado dinámico de disponibilidad confirmado'],
        ['H6 orden','Org0 primero por recencia y fase de llegada; ambas org servidas por ambos PIDs','No afinidad fija ni IDs de healthy/noisy en runtime','Recencia+fase contribuye; se conserva orden al vencer deadline'],
        ['H7 locks','SQL lock p95 de pocos ms; SKIP LOCKED y claims válidos','Final blocked tiene miss tras SQL Conversation y fallback; holder no capturado','Sin cola SQL de segundos demostrada; un miss sí amplifica cadencia; no tuning de locks'],
        ['H8 query','Selector previo 19–27 ms p95; EXPLAIN 2.355/4.741 ms','Prototipo creció a 163/268 ms; coste final íntegro en tabla posterior','Descartada como causa principal previa; riesgo posterior explícito, sin índice']]
    add(table(['Hipótesis','Evidencia','Contraevidencia/límite','Contribución y veredicto'],hypotheses))

    add('## Ablations DIAGNOSTIC_ONLY\n\nCada control usa 30/120/20 s y cambia solo el override indicado; 24 healthy, 16 ordinarias. Son ventanas secuenciales, sin paired randomization: las diferencias de p95 no son efectos aditivos universales. El campo heredado profile_conditions en el subrecibo monotonic no anula e4_overrides ni convierte ablations en v1/acceptance.')
    rows=[]
    for label in ('ablation-no-noisy','ablation-no-pause','ablation-batch-three','ablation-fast-provider','candidate-bounded-yield'):
        v=measurements[label]
        rows.append([label,str(v['e4_overrides']),f"{v['healthy_claim']['p95_seconds']:.6f}"]+
            [f"{o['metrics']['eligible_to_claim']['p95']:.6f}" for o in v['organizations']])
    add(table(['Control','Override explícito','Global persisted→claim p95 s','Org0 EC p95 s','Org1 EC p95 s'],rows))

    add('''## Única mejora y fronteras

worker._pending_conversation_candidates añade una observación readonly de
mensajes ordinarios pending de otra org idle, con deadline dentro de la próxima
pausa existente de un segundo y último claim menor/null. En ese caso excluye
temporalmente el candidato de una org ya servida. Nunca excluye por esta regla
a una org nunca reclamada. Al llegar el deadline se restablece la selección
original por recencia. Conversaciones con safety pendiente están exentas de
esa retención, también después de que W1 difiera a nuevo input. Conserva
candidato máximo 3, fallback, batch=1, poll=1,
N=1 y PostgreSQL como autoridad. No reserva planner, TurnWork, capacity, tokens
ni admission. La forecast no adelanta ni escribe available_at. Los retry/due
works mantienen sus rutas originales; safety conserva su disponibilidad
original en el selector y su fastpath receptor. No se añade otra mejora.

El lookahead se limita a un segundo por observación; no garantiza un límite
global de starvation bajo cualquier workload con forecasts sucesivos. No es
fairness fuerte ni un scheduler general. Tampoco promete rendimiento para
topologías/rates que no se midieron. B3 sigue validando ownership, lease,
epoch/token, membership/context, anchor/cursor y fencing bajo la transacción.
Candidate miss no crea admission ni devuelve budget. B9B conserva 30 calls,
18k reserved, output600, request64KiB y timeout10; no cambios de política.
B5 safety/human y sender B4 conservan precedencia e independencia. El test
nuevo READY une inbound después de vencido y verifica deadline inmutable.

No cambios de schema, índices, broker ni servicios nuevos. Solamente 18 líneas
runtime adicionales, más pruebas específicas y tooling/evidencia separados del runtime.''')

    add('## Coste SQL y locks\n\nDuraciones de SELECT/UPDATE con lock son cotas superiores, que incluyen transporte, ejecución y posible espera; no se publican como lock-wait puro. EXPLAIN ANALYZE se ejecuta al cerrar cada carga y no equivale a la distribución de SQL durante la carga. Los pg_stat_activity waits se muestrean cada 5 s; no prueban ausencia de todo wait transitorio.')
    rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        v=measurements[label]
        rows.append([label,f"{v['selector_sql']['p95']*1000:.3f}",f"{v['selector_sql']['maximum']*1000:.3f}",
            f"{v['selector_explain_execution_ms']:.3f}"]+
            [f"{v['locks_sql_upper_bounds'][name]['p95']*1000:.3f}" for name in
             ('organizations_organization','agent_conversation','agent_turnwork','channels_message')])
    add(table(['Run','Selector p95 ms','Selector max ms','EXPLAIN execution ms','Org SQL p95 ms','Conv SQL p95 ms','Work SQL p95 ms','Message SQL p95 ms'],rows))
    add(f'''El crecimiento de la query es material: de 27.261→{b['selector_sql']['p95']*1000:.3f} ms base y
19.282→{x['selector_sql']['p95']*1000:.3f} ms blocked. Máximo final blocked
{x['selector_sql']['maximum']*1000:.3f} ms. El cierre EXPLAIN base pasa de 2.355 a
{b['selector_explain_execution_ms']:.3f} ms. No se oculta esta regresión de coste;
el gate healthy final y su margen se muestran íntegros. No se crea índice ni
se encadena un segundo fix. Antes de una promoción hace falta validar el candidato
con el PROFILE integral original y revisar margen/coste bajo su proceso formal.''')

    add('## Latencias posteriores y denominadores\n\nLos componentes son p95 por cohorte ordinaria (20 por org), medidos separadamente. El gate global contractual (60, incluyendo 20 safety) se muestra aparte.')
    rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        for o in measurements[label]['monotonic_diagnostic']['organizations'][:2]:
            rows.append([label,o['organization']]+[f"{o[f]['p95_seconds']:.6f}" for f in
                ('persisted_to_eligible','eligible_to_claim','persisted_to_claim')]+[o['joined_ready_inbounds']])
    add(table(['Run','Org','Persisted→eligible p95 s','Eligible→claim p95 s','Persisted→claim p95 s','Joined READY'],rows))
    rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        v=measurements[label]; g=v['healthy_claim']
        rows.append([label,g['count'],f"{g['p95_seconds']:.6f}",f"{g['max_seconds']:.6f}",g['missing'],
            f"{v['margin']:.6f}",v['safety_dispatch']['p95_seconds'],v['outbox_dispatch']['p95_seconds']])
    add(table(['Run','Healthy n','PC p95 s','Max s','Missing','10−p95 s','Safety p95 s','Outbox p95 s'],rows))
    add(f"La desaparición del forecast aplicable no elimina toda la asimetría. En base final, EC org0/org1 es {b['monotonic_diagnostic']['organizations'][0]['eligible_to_claim']['p95_seconds']:.6f}/{b['monotonic_diagnostic']['organizations'][1]['eligible_to_claim']['p95_seconds']:.6f} s. El p95 ordinario org1={b['monotonic_diagnostic']['organizations'][1]['persisted_to_claim']['p95_seconds']:.6f} s puede superar 10 s aunque el gate global contractual de 60 muestras cumpla. No se sustituye el denominador ni se inventa un gate nuevo por org. Blocked final se conserva con su resultado original, sin una segunda mejora.")
    add('''Base baseline registra 359 inbound por frontera temporal (60 healthy +
299 noisy); las otras cargas relevantes 360. No se cambiaron tasas ni ventana
para corregir ese borde. Los gates safety/outbox medidos constan en summary.json. Blocked no tiene gate
canónico equivalente de outbox. Cumplir estos gates diagnósticos no prueba las
cinco variantes y corpus/COST/SCALE necesarios para PROFILE integral.''')

    add('## Calls, deferrals y backlog\n\nCohorte de works con context_at dentro de ventana, distinta de la cohorte de inbound creada dentro de ventana. Deferrals cuenta exactamente outcome_code=deferred_to_new_input según el collector original, no mensajes perdidos ni reextensión de READY.')
    rows=[]
    for label in ('baseline-base-v2','baseline-blocked','postfix-final-base','postfix-final-blocked'):
        for o in measurements[label]['monotonic_diagnostic']['organizations']:
            rows.append([label,o['organization'],o['works'],o['calls'],f"{o['calls_per_work']:.6f}",
                f"{o['calls_per_dialogue']:.6f}",o['deferrals'],o['missing_claim']])
    add(table(['Run','Org','Works','Calls','Calls/work','Calls/dialogue','Deferrals','Inbound sin claim al cierre'],rows))
    add('''READ completo sigue requiriendo dos calls reales; safety cero. La media
healthy mezcla works safety de cero calls y works READ de dos. Cuando una
cohorte contiene 10 safety y 20 READ resulta 1.333333; las otras medias y
denominadores exactos se muestran en la tabla y en el recibo. La
inyección bloqueada conserva timeout/retry; algún trabajo completo fuera de
la cohorte puede admitir tres calls y otro trabajo observado antes de retry
admite uno. No se deduce “todos los works exactamente dos” de una media.
El backlog final por organización y los missing healthy constan en la tabla.
No se declara drenaje completo ni capacidad
para sostener 1 inbound noisy/s. Máximos de cola son observados cada 5 s.''')

    reg=summary.get('regression')
    add('## Regresión, checks, infraestructura y privacidad')
    if reg:
        add(f"Cobertura acumulada: **{reg['passed']}/{reg['selected']} IDs con recibo PASS**, sin IDs faltantes ni fallos pendientes. Primera ejecución: 773/774 PASS, con un FAIL de fixture conservado. La versión final revalidó **{reg['final_source_revalidated']} IDs**, todos PASS; {reg['prototype_only_passed']} IDs históricos tienen recibo del prototipo. No se afirma que los 775 se ejecutaran sobre el mismo hash final. Hubo {reg['executed']} ejecuciones de regresión, más tres probes separados. regression-summary.json conserva coverage_by_id con recibo y hash; regression-final-inventory.json enumera la unión exacta. Las once pruebas nuevas se limitan al mecanismo:")
        add('\n'.join('- `'+identifier+'`' for identifier in reg['new_ids']))
        inventory=read('regression-final-inventory.json')
        groups=[('B3',('test_b3_',)),('B5',('test_b5_',)),('B9A',('test_b9a_',)),
                ('B9B',('test_b9b_',)),('B9C',('test_b9c_',)),('E4',('test_e4_',)),
                ('Monotonic',('test_w1_mono','test_w1_monotonic')),('Worker',('test_worker.',)),
                ('Planner',('test_planner.',)),('Sender B4',('test_b4_sender.','test_b4_processes.'))]
        add(table(['Frontera','IDs ejecutados'],[(name,sum(any(pattern in identifier for pattern in patterns)
            for identifier in inventory)) for name,patterns in groups]))
    else:
        add('Regresión en curso; este documento debe regenerarse una vez publicados los tres recibos finales.')
    add('''Las pruebas nuevas cubren forecast sin claim/capacity/budget, deadline,
horizonte, busy, never-claimed, recencia, READY join, fastpath safety y safety
pendiente después de W1. Dos OS planners
con conexiones PostgreSQL distintas prueban ambos forecasts sin reserva,
colisión y fallback hacia otra org, candidato descartado tras observación y
último slot revalidado. Reloj controlado solo para elegibilidad de la fixture;
claims, locks, leases, ownership y exclusión son PostgreSQL reales. Se pausa
run_turn para coordinar/finalizar la fixture, no para medir performance.
Las suites históricas incluidas aportan takeover/stale witnesses, candidatos
no elegibles, B3/B5/B9A/B9B/B9C, E4 KEEP, worker/planner, monotonic y sender
independence. No reemplazan ni editan pruebas históricas; no skips/xfail nuevos.

Checks: migrate, system check, makemigrations --check y migrate --check pasan;
cero migraciones nuevas. No se modificó la configuración productiva. La
instancia local propia puerto35443 y prefijo test_b8b_e4claim_ usa fuentes
bloqueadas Python3.13/Django6.0.5/PG16.15 y no credenciales productivas.
Cleanup se ejecuta solo cuando no quedan clientes externos, locks en espera ni
prepared transactions; verifica data_directory absoluto, elimina exclusivamente
bases con prefijo propio, detiene cluster y comprueba puerto cerrado antes de
retirar su directorio/log. Binarios y otros clusters/entornos preexistentes quedan
intactos. El recibo cleanup.json conserva conteos y hash del log retirado.

Trazas contienen eventos cerrados y timestamps/IDs técnicos locales, sin payload,
phones, prompts, responses ni secretos. Los nombres response en el vocabulario
de eventos no incluyen contenido. Instrumentación solo en tests; cero labels
productivos nuevos. validation.json documenta scan de sentinels y hashes; no se
presenta una búsqueda regex como prueba universal contra toda PII. Los bytes de
evidencia se conservan por .gitattributes y manifest.sha256.json. No hay consultas
a una DB productiva ni IO externo real. B0 cerrado, B7B=False, flags={}, grants=[],
0 clínicas activadas y PENDING_ACTIVATION_REQUIREMENTS son el estado conservado,
no una activación validada contra producción.''')
    cleanup=OUT/'cleanup.json'
    if cleanup.exists():
        c=read('cleanup.json')
        add(f"Cleanup verificado: {c['status']}; clientes restantes {len(c['other_clients'])}, locks en espera {c['waiting_locks']}, prepared {c['prepared_transactions']}; puerto cerrado={c['port_closed']}, directorio ausente={c['data_directory_absent']}, log ausente={c['log_absent']}.")

    add('## Los 58 campos solicitados\n\nEsta tabla referencia el detalle anterior y los recibos locales. El hash del segundo commit/HEAD final se entrega en la respuesta de cierre, porque un documento no puede incorporar su propio hash Git sin modificarlo.')
    b=measurements['postfix-final-base']; x=measurements['postfix-final-blocked']
    def pair_metric(m,field):
        return '/'.join(f"{o[field]['p95_seconds']:.6f}" for o in m['monotonic_diagnostic']['organizations'][:2])+' s (org0/org1; ordinarios)'
    commitpath=OUT/'runtime-commit.json'
    commit=read('runtime-commit.json')['commit'] if commitpath.exists() else 'Pendiente del commit runtime'
    entries=[
        ('Estado','Una mejora E4; ROOT_CAUSE_CONFIRMED; '+summary['performance_state']+'; STOP al tuning'),
        ('Baseline',summary['baseline']),('Commits',commit+' runtime/tests; segundo docs/evidencia, hash en cierre'),
        ('HEAD final','Commit docs/evidencia de este informe; hash exacto en respuesta final'),
        ('Root cause','Recencia/fase favorece org0; servicio noisy iniciado antes de READY + pausa externa + batch1 deja esperar a org1'),
        ('Timeline org0','Tabla T0–T8 y todas las muestras en analysis.json; no p95 usado como timeline'),
        ('Timeline org1','Message421/Work131: T1=7.943504, T3=8.401996, T4=10.570163, T7=10.588053 relativo a T0'),
        ('Planner identities','Ambos planners reclaman ambas orgs; PIDs OS/PG en los recibos; sin afinidad fija'),
        ('Planner cadence','Servicio+pausa real; tablas por planner; completion→next p95≈1.0–1.02 s'),
        ('Eligible→next opportunity','Tabla p95 global y propio por planner; se registra selección ya en curso'),
        ('Candidate selection','Hasta3, uno/org, busy excluido, recencia intacta al vencer; snapshot advisory'),
        ('Duplicated planner effort','Carreras existen; descarta abandono de Y observado: fallback mismo poll ya existe'),
        ('batch=1 impact','Un éxito por ciclo; otro claim espera otro planner; sin cambiar batch'),
        ('noisy impact','0 HOL con healthy READY; 3/9 claims previos near-ready aplicables →0/0 posteriores'),
        ('both-planners-busy impact','Raro exactamente en T1; intervalos posteriores con ambos ocupados explican parte de EC'),
        ('locks','SQL con locks p95 ms; cotas superiores, no lock-wait puro; sin tuning'),
        ('query cost',f"Selector p95 27.261→{b['selector_sql']['p95']*1000:.3f} ms base, 19.282→{x['selector_sql']['p95']*1000:.3f} ms blocked; sin índice"),
        ('Ablations','No-noisy/no-pause/batch3/provider≈0 y candidato; DIAGNOSTIC_ONLY 30/120/20'),
        ('Cambio elegido','Yield advisory ante otra org idle menos recientemente servida cuyo deadline llega en ≤1s'),
        ('Por qué pertenece E4','Coordina selección/utilización; no autoridad, persistencia ni contrato nuevo'),
        ('B3 preserved','Claim, contexto, membership, anchor/cursor, lease/epoch/token, fencing sin editar'),
        ('B5 preserved','Safety/human conservados; B5 histórico revalidado + YIELD08/09; defecto del prototipo corregido'),
        ('B9B preserved','Admission solo tras claim; candidate observation/miss no reserva ni devuelve budget'),
        ('B9C preserved','Org SKIP LOCKED + revalidación; N1 probado en PostgreSQL/procesos'),
        ('monotonic READY preserved','8/25 y available_at intactos; YIELD07 y suite monotonic'),
        ('Multiprocess','Dos nuevos tests OS/PG: forecast→colisión/fallback y stale/discard→último slot'),
        ('max PROCESSING/org','1 en estados durables observables; intervalos ordinarios, snapshots y pruebas B9C; safety finaliza atómicamente'),
        ('candidate misses',f"Final base {b['misses']} y blocked {x['misses']}; advisory, sin admission, fallback donde exista Y"),
        ('lost work',f"Healthy missing base/blocked {b['healthy_claim']['missing']}/{x['healthy_claim']['missing']}; backlog noisy {b['monotonic_diagnostic']['organizations'][2]['missing_claim']}/{x['monotonic_diagnostic']['organizations'][2]['missing_claim']} durable; no drained/lost ficticio"),
        ('cross-tenant','0 desajustes org/conversación membership en collector; regresión fencing/scopes'),
        ('stale progress','Revalidación/fencing intactos, tests históricos takeover + nueva observación descartada'),
        ('persisted→eligible base',pair_metric(b,'persisted_to_eligible')),
        ('eligible→claim base',pair_metric(b,'eligible_to_claim')),
        ('persisted→claim base',pair_metric(b,'persisted_to_claim')+f"; global {b['healthy_claim']['p95_seconds']:.6f} s, n60"),
        ('persisted→eligible blocked',pair_metric(x,'persisted_to_eligible')),
        ('eligible→claim blocked',pair_metric(x,'eligible_to_claim')),
        ('persisted→claim blocked',pair_metric(x,'persisted_to_claim')+f"; global {x['healthy_claim']['p95_seconds']:.6f} s, n60"),
        ('margen base',f"{b['margin']:+.6f} s"),('margen blocked',f"{x['margin']:+.6f} s"),
        ('Calls/work',f"Healthy base org0/1={b['monotonic_diagnostic']['organizations'][0]['calls_per_work']:.6f}/{b['monotonic_diagnostic']['organizations'][1]['calls_per_work']:.6f}; blocked={x['monotonic_diagnostic']['organizations'][0]['calls_per_work']:.6f}/{x['monotonic_diagnostic']['organizations'][1]['calls_per_work']:.6f}; READ real2, safety0; distribuciones arriba"),
        ('Deferrals',f"Base org0/1={b['monotonic_diagnostic']['organizations'][0]['deferrals']}/{b['monotonic_diagnostic']['organizations'][1]['deferrals']}; blocked={x['monotonic_diagnostic']['organizations'][0]['deferrals']}/{x['monotonic_diagnostic']['organizations'][1]['deferrals']}; no cambiar calls/READY"),
        ('PROFILE rerun sí/no','No; '+('opcional habilitado por gates diagnósticos y regresión' if green else 'prohibido por PERFORMANCE_STOP')+'; evaluación integral posterior'),
        ('PROFILE result si aplica','NOT_RUN; diagnósticos no son PROFILE integral PASS'),
        ('Regression',f"{reg['passed']}/{reg['selected']} PASS" if reg else 'Pendiente'),
        ('IDs','Inventario exacto + coverage_by_id/recibos por shard; once nuevos IDs listados'),
        ('skips/xfail','0 requeridos; resultado exacto en recibos finales'),
        ('Checks','migrate/check/makemigrations --check/migrate --check PASS, diff --check'),
        ('Migrations','0; sin tabla, índice ni persistencia nueva'),
        ('Infra cleanup','Recibo cleanup.json, solo cluster/bases propios; clientes/locks/prepared0'),
        ('Privacy','Eventos cerrados e IDs locales, sin payload/phones/prompts/responses ni nuevos labels runtime'),
        ('Risks','SQL más caro, margen limitado, backlog noisy, forecasts sucesivos sin fairness fuerte; muestra local única; T5/T6/T8 receptor safety no capturados'),
        ('Production gates','B0 cerrado; B7B=False; flags={}; release grants=[]; PENDING_ACTIVATION_REQUIREMENTS'),
        ('Active clinics','0'),('Deploy','No'),('B9','IN_PROGRESS'),('B9E','FAIL histórico'),
        ('PROFILE histórico','FAIL'),('Próximo paso',('Revisión del candidato y evaluación PROFILE v1 integral posterior' if green else 'PERFORMANCE_STOP: revisión de resultados; sin rerun formal ni otro fix en este encargo')+'; sin alterar contratos ni activar producción')]
    assert len(entries)==58
    add(table(['#','Campo','Resultado'],[(i+1,k,v) for i,(k,v) in enumerate(entries)]))
    REPORT.write_text('\n'.join(sections),encoding='utf-8',newline='\n')
    print(REPORT)


if __name__=='__main__':
    main()
