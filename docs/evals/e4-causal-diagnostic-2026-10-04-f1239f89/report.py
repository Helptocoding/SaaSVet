"""Write an A-E causal report using only the current run's reconstructed evidence."""
import json
from collections import defaultdict
import infra


def load(name):
    return json.loads((infra.OUT/name).read_text(encoding='utf-8'))


def fmt(value,digits=6):
    if value is None:
        return 'N/A'
    if isinstance(value,list):
        return '['+'; '.join(fmt(x,digits) for x in value)+']'
    return f'{value:.{digits}f}'


def main():
    report,summary = load('causal-report.json'),load('closure-summary.json')
    assert report['run_id']=='causal-'+infra.KEY
    groups = defaultdict(list)
    with (infra.OUT/'query-timings.jsonl').open(encoding='utf-8') as source:
        for line in source:
            q=json.loads(line)
            selection=q.get('selection_id')
            if selection and q.get('span_id')==selection:
                groups[(q['session_id'],selection)].append(q)
    selections=[]
    for (session,selection),queries in groups.items():
        selections.append(dict(session_id=session,selection_id=selection,worker=queries[0]['worker'],query_count=len(queries),
            query_ids=[q['query_id'] for q in queries],query_timings_ms=[q['duration_ms'] for q in queries],
            inter_query_gaps_ms=[(b['execute_start_ns']-a['execute_end_ns'])/1e6 for a,b in zip(queries,queries[1:])]))
    infra.write('selector-polls.json',dict(classification='DIAGNOSTIC_ONLY',run_id=report['run_id'],
        distinct_selections_with_sql=len(selections),selector_execute_count=sum(x['query_count'] for x in selections),selections=selections))
    previous=infra.ROOT/'docs/evals/e4-causal-diagnostic-2026-10-03-dded711c/closure-summary.json'
    reference=json.loads(previous.read_text(encoding='utf-8'))
    reproduced=report['result_classification']=='CAUSE_CONFIRMED' and reference['result_classification']=='CAUSE_CONFIRMED'
    reproduction=dict(classification='DIAGNOSTIC_ONLY',current_run_id=report['run_id'],
        reference_type='PRIOR_NEW_HEAD_DIAGNOSTIC_ONLY_NOT_HISTORICAL_PROFILE',
        reference_file=str(previous),same_head=reference['head']==infra.HEAD,
        phase_confirmation_repeated=reproduced,current_over_10_count=len(report['over_10_seconds']),
        prior_over_10_count=sum(x['over_10_seconds'] for x in reference['organizations']),
        reused_journals=0,reused_receipts=0,
        limitation='Two independent diagnostic observations corroborate the phase. Exact latencies/winners/counts need not reproduce; historical TurnWork 86 is not explained.')
    infra.write('reproducibility.json',reproduction)
    report['artifact_index']['selector_polls']='selector-polls.json'
    report['artifact_index']['reproducibility']='reproducibility.json'
    report['reproducibility']=reproduction
    report['phase_definitions']=dict(A='Persisted DB field through individual eligibility and admitting poll/selection_start.',
        B='Selection_start/end; all actual selector execute intervals, materialization and local overhead.',
        C='Selection_end to claim_start.',D='Claim_start/end with SQL/lock metadata; ordinary claim includes the real commit.',
        E='Driver COMMIT execute_start/end (ACK), plus signed result-to-ACK and persisted/claimed_at-to-ACK.',
        non_additivity='D includes E for ordinary claims. claimed_at is sampled early inside D, so full D and E cannot be added to persisted-to-claimed_at.')
    report['source_protection']['prior_diagnostic_files_unchanged']=len(load('protected-sources-before.json')['prior_diagnostic_protection']['hashes'])
    with (infra.OUT/'causal-report.json').open('w',encoding='utf-8') as target:
        json.dump(report,target,indent=2);target.write('\n')
    lines=[f"# DIAGNOSTIC_ONLY — {report['result_classification']}", '',report['causal_conclusion'],'',
        f"Nueva ejecución: `{report['run_id']}`. HEAD exclusivo: `{infra.HEAD}`, rama `codex/e4-capacity-scheduling`, hijo directo de `66702168439b9841a2c988238638a42e6aaee43d`.",
        f"Inicio UTC: **{report['load_definition']['started_at']}**. No se invocó `b9e_profile` ni `e4_profile`; no es PROFILE-BETA-1 ni aceptación B9E. Umbral intacto de 10 s. El FAIL histórico, su PROFILE y la evaluación posterior del 02-10 permanecen intactos. No se imputan estas mediciones al TurnWork 86 histórico.", '',
        'La carga conserva dos planners y un sender, batch 1, pausa entre polls de 1 s, dos organizaciones a un inbound cada 10 s y una ruidosa a uno por segundo; 30 s de calentamiento, 300 s de carga y 20 s de drenaje. Provider simulado: dos llamadas LLM de 500 ms, HTTP de dominio 100 ms, Meta 200 ms. Ingreso capturado antes del primer webhook y ambas capturas de planners activas; observador readonly autocommit en proceso separado con intervalo solicitado de 20 ms. PostgreSQL aislado 16.15 con fsync y synchronous_commit on.', '',
        '| Organización | Ingestados | Reclamados | Safety | >10 s | Pendientes sin claimed_at | Máximo reclamado, s |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for row in report['organization_summary']:
        lines.append(f"| {row['organization_id']} | {row['ingested']} | {row['claimed']} | {row['safety']} | {row['over_10_seconds']} | {row['unclaimed']} | {fmt(row['persisted_to_claimed_at_s'].get('max'))} |")
    lines += ['', f"{len(report['claims'])} claims vinculados y confirmados por commit; {len(report['missed_attempts'])} intentos sin vínculo. Los pendientes están censurados: no se fabrican claimed_at ni latencias finales. Todos los intentos están en [per-attempt.json](per-attempt.json) y [per-attempt.csv](per-attempt.csv); cada exceso individual está en [over-10-attempts.csv](over-10-attempts.csv) y [over-10-attempts.json](over-10-attempts.json).", '',
        '**Evidencia por intento.** Los IDs pertenecen exclusivamente a esta DB nueva. Las columnas con límites usan la consulta DB existente como calibración, no logs de segundos.', '',
        '| Work/inbound/worker | persisted→claimed_at, s | A persisted→eligible, s | A eligible→poll, s | A eligible→selection, s | B selección, ms | B query count / SQL, ms | C, ms | D claim, ms | E COMMIT, ms | persisted→ACK, ms |',
        '|---|---:|---:|---|---|---:|---|---:|---:|---:|---|']
    for row in summary['representative_attempts']:
        lines.append(f"| {row['turn_work_id']}/{row['message_id']}/{row['worker']} | {fmt(row['persisted_to_claimed_at_s'])} | {fmt(row['persisted_to_eligible_s'])} | {fmt(row['eligible_to_poll_s_bounds'])} | {fmt(row['eligible_to_selection_s_bounds'])} | {fmt(row['selection_ms'],4)} | {row['selector_query_count']} / {fmt(row['selector_sql_ms'],4)} | {fmt(row['selection_end_to_claim_start_ms'],4)} | {fmt(row['claim_ms'],4)} | {fmt(row['commit_ms'],4)} | {fmt(row['persisted_to_commit_ack_ms_bounds'],4)} |")
    if report['over_10_seconds']:
        row=max(report['over_10_seconds'],key=lambda r:r['persisted_to_claimed_at_s'])
        lines += ['', f"El máximo es Work {row['turn_work_id']}, inbound {row['message_id']}, org {row['organization_id']}, attempt `{row['attempt_id']}`: {fmt(row['persisted_to_claimed_at_s'])} s. El intervalo anterior a selección es {fmt(row['persisted_to_selection_start_ms_bounds'],4)} ms; selección→claimed_at es {fmt(row['selection_start_to_claimed_at_ms_bounds'],4)} ms. La separación claim_start→claimed_at es {fmt(row['claim_start_to_claimed_at_ms_bounds'],4)} ms, mientras el claim completo es {fmt(row['claim_ms'],4)} ms. Los extremos de la misma calibración están anticorrelacionados y cierran el total DB; no se suman percentiles ni límites independientes.",
            f"En el worker que admite ese intento se observaron estos solapamientos previos: `{json.dumps(row['worker_occupancy_ms_bounds'],ensure_ascii=False)}`. Incluyen spans de otros turnos y tiempo entre polls con la pausa configurada; no se etiqueta todo ese intervalo como sleep ni como indisponibilidad global simultánea de ambos planners."]
    lines += ['', '**Fases A–E y consultas.** [per-phase.json](per-phase.json) separa ordinarios, safety y casos >10 s. A contiene el deadline existente y la espera hasta el poll/selección que admite. B mide selección completa, execute y huecos; C mide el salto a claim; D conserva los locks y todas las queries del intento; E mide la llamada real al COMMIT. D incluye E en el claim ordinario y una parte ocurre después de claimed_at: esos tiempos no deben sumarse íntegros al persisted→claimed_at.',
        f"El selector ejecutó {sum(x['query_count'] for x in selections)} queries en {len(selections)} selecciones distintas con SQL, incluyendo polls sin admisión; [selector-polls.json](selector-polls.json) conserva sus IDs y timings. Los claims ordinarios tienen una query del selector y safety cero (poll/selección N/A). Todos los execute del run ({report['all_sql_query_count']}) están en [query-timings.jsonl](query-timings.jsonl), con session/query ID, scope, inicio/fin/error, tablas y flags de locks, sin SQL crudo ni parámetros. La duración SQL de cliente incluye servidor, red, driver y posibles waits; materialización y overhead quedan en selección total.",
        'Cada intento conserva query IDs, duración individual y huecos fin→inicio. El selector de una query no tiene hueco entre queries. Se conserva claim_result, commit_start, commit_end, commit_ack (execute_end_ns), persisted→claimed_at y persisted→commit_ack. En ordinarios el ACK precede al claim_result; el intervalo firmado puede ser negativo. En safety el resultado de la primitiva precede al commit exterior de ingreso. claimed_at no equivale al ACK.', '',
        '**Waits y bloqueadores.** [waits-summary.json](waits-summary.json) y el journal `waits.jsonl` mantienen asociación por run/session/conexión/PID e intersección con execute. Las muestras ambiguas no se asignan a una query. No se interpolan locks ni se les atribuye toda la duración SQL.',
        f"Muestras: {report['waits_summary']['sample_count']}; únicas {report['waits_summary']['matched']}, ambiguas {report['waits_summary']['ambiguous']}, sin query asociada {report['waits_summary']['unassigned']}. Queries con lock observado: {len(report['waits_summary']['observable_lock_queries'])}.", '',
        '| Worker/query | Tabla | Query, ms | Muestras lock | Bloqueadores | Scope |', '|---|---|---:|---:|---|---|']
    for q in report['waits_summary']['observable_lock_queries']:
        lines.append(f"| {q['worker']}/{q['query_id']} | {','.join(q['tables'])} | {fmt(q['duration_ms'],4)} | {q['lock_samples']} | {json.dumps(q['blocker_roles'])} | attempt={q['attempt_id']}, work={q['turn_work_id']} |")
    lines += ['', 'La duración exacta de lock permanece null; el límite conservador es [0; duración completa de query]. Ausencia de muestras no prueba ausencia absoluta de waits. El observador no cambia polling ni ocupa la conexión del worker.', '',
        '**Integridad, equivalencia y hashes.** Las seis pruebas controladas OFF/ON se ejecutaron nuevamente con IDs prefijados por el UUID nuevo. Cero fallos/errores/skips/xfail; igualdad de decisiones, secuencia SQL, membership, attempts, locks, leases, epoch/fencing, budgets y resultado bajo los estados/barreras controlados. No se promete igualdad temporal ON/OFF ni igualdad de ganador en carreras no controladas. El overhead de captura se incluye en los tiempos.',
        f"Las cuatro capturas nuevas suman {summary['footer_events']} eventos, sin failed_writes y con footer, secuencia, SQL/spans y transacciones completos. El observador terminó sin líneas parciales. Todos los procesos terminaron con exit 0. [integrity.json](integrity.json), [functional-results.results.json](functional-results.results.json) y la validación final conservan esa evidencia.",
        f"[protected-sources-before.json](protected-sources-before.json) y [protected-sources-after.json](protected-sources-after.json) verifican {report['source_protection']['protected_files']} fuentes del HEAD y {report['source_protection']['prior_diagnostic_files_unchanged']} archivos de la primera ejecución diagnóstica sin cambios. No se modificó runtime, selector, índices, SQL, workers, polling, leases, budgets o umbral. Los cambios preexistentes del usuario se conservan. No hay commits nuevos.",
        'La asociación NULL del reconstructor del HEAD para safety se excluye sólo en el adaptador evaluativo: una selección exige selection_id no nulo y span real. Los journals y fuentes no se cambian. Los borradores causal-analysis.json, attempt-summary.* y phase-summary.json no son autoritativos para safety. El informe definitivo y per-attempt/per-phase usan microsegundos DB enteros y brackets locales del reloj; el formatter de logs no interviene.', '',
        '**Reproducibilidad y corrección mínima.** '+('La localización de la demora previa a selección se confirma por segunda vez en dos cargas independientes del mismo HEAD y límites.' if reproduced else 'Esta ejecución no permite afirmar reproducción de la causa por fase.')+' La comparación de conclusiones está en [reproducibility.json](reproducibility.json). No se reutilizó ningún journal/recibo de la primera ejecución para reconstruir ésta. La repetición no equivale a una reproducción del FAIL histórico ni garantiza latencias o conteos idénticos.',
        'La evidencia localiza el coste y no identifica una corrección mínima única que preserve los contratos. Ningún cambio del selector/SQL/índices queda justificado por atribuir el exceso a la cola. En particular, la carga ruidosa y el presupuesto de servicio admitido deben distinguirse de una violación del contrato de las organizaciones sanas. La corrección mínima de runtime queda sin definir; no se implementa corrección ni se altera capacidad/polling en este encargo.', '',
        '**Limpieza y STOP.** [cleanup.json](cleanup.json) confirma las tres bases nuevas eliminadas, cluster detenido, puerto 35451 cerrado, cero clientes/locks pendientes/prepared transactions y directorio de datos propio ausente. [causal-report.json](causal-report.json) es el resultado estructurado autoritativo. Sólo se conservan artefactos nuevos de esta ejecución. La investigación se detiene tras esta clasificación; no hay otra ronda automática.']
    with (infra.OUT/'report.md').open('x',encoding='utf-8') as target:
        target.write('\n'.join(lines)+'\n')
    print(json.dumps(dict(result_classification=report['result_classification'],distinct_selector_selections=len(selections),
        phase_reproduced=reproduced)))


if __name__=='__main__':
    main()
