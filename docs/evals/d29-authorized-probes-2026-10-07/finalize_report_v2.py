"""Build final inventory after probes, regression and owned cleanup complete."""
import hashlib
import json
from collections import Counter
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
BASE='825db75df68bf076929fa787e77beefe96803350'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def lines(p):return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,indent=2,ensure_ascii=False)

def main():
    cleanup=read(OUT/'lab-cleanup-v2.json')
    integrity=read(OUT/'integrity-audit-v4.json')
    final_integrity=read(OUT/'final-integrity-v5.json')
    closure_integrity=read(OUT/'closure-integrity-v6.json')
    source_audit=read(OUT/'probe-source-audit.json')
    pacing=read(OUT/'pacing-audit.json')
    if not cleanup['all_owned_labs_removed']:raise RuntimeError('Owned labs still present')
    if closure_integrity['status']!='PASS':raise RuntimeError('Closure integrity not PASS')
    specs=[
        ('R1-03','authorized-r103-unequal-20261007-0002','evidence-audit-v2.json'),
        ('R1-06','authorized-r106-2x4-20261007-0002','authorized-verification-v2.json'),
        ('R2-02','authorized-r202-blocked-20261007-0002','evidence-audit-v2.json'),
        ('R2-04','authorized-r204-postcommit-base-20261007-0004','authorized-verification-v2.json'),
        ('R2-09','authorized-r209-uncertain-meta-20261007-0002','evidence-audit-v2.json')]
    summaries=[]
    for case,run,file in specs:
        d=OUT/case.lower()/run;r=read(d/file)
        journals=[(p,lines(p)) for p in [d/(role+'.jsonl') for role in ('ingress','planner_1','planner_2','sender','crash')] if p.exists()]
        offers=lines(d/'offers.jsonl');scheduled=lines(d/'schedule-offers.jsonl')
        snapshot=next((s for s in reversed(lines(d/'snapshots.jsonl')) if s['stage']=='final'),None)
        if (d/'observed-window.json').exists():snapshot=read(d/'observed-window.json')['final_cut']
        if snapshot is None and (d/'db-000-committed-before-crash.json').exists():snapshot=read(d/'db-000-committed-before-crash.json')
        raw=read(d/'job-result.json') if (d/'job-result.json').exists() else read(d/'reconstructed-cohort-v2.json') if (d/'reconstructed-cohort-v2.json').exists() else None
        successful=Counter()
        claims=Counter()
        for p,rows in journals:
            successful[p.stem]=sum(x['event']=='commit_end' and not x['error_class'] for x in rows)
            claims[p.stem]=sum(x['event']=='claim_bound' for x in rows)
        summary=dict(case_id=case,run_id=run,status=r['status'],errors=r.get('errors',[]),
            receipt_path=str((d/file).relative_to(OUT)),receipt_sha256=sha(d/file),
            accepted_inputs=sum(o['outcome']=='ACCEPTED_DURABLE' for o in offers),
            ordinary_inputs=sum(o['phase']=='ORDINARY' and o['outcome']=='ACCEPTED_DURABLE' for o in scheduled),
            backlog_inputs=sum(o['phase']=='BACKLOG' and o['outcome']=='ACCEPTED_DURABLE' for o in scheduled),
            episodes=len(raw['episodes']) if raw else None,
            works=len(snapshot['works']) if snapshot else None,
            claim_bound_events_by_role=dict(claims),successful_outer_commits_by_role=dict(successful),
            successful_outer_commits_total=sum(successful.values()),
            population_by_org=raw['organization_counts'] if raw else None,
            base_receipt_sha256='71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56',
            base_changed=False,database_cleanup=read(d.parent/(run+'-database-cleanup.json')) if (d.parent/(run+'-database-cleanup.json')).exists() else None)
        if case=='R1-06':summary['physical_frontier']=read(d/'backlog-frontier-audit-v2.json')['physical_frontier']
        if case=='R1-03' and summary['database_cleanup'] is None:
            summary['database_cleanup']=read(OUT/'r1-03-database-cleanup.json')
            summary['database_cleanup_provenance']='Shared cleanup receipt from the last R1-03 run; first setup cleanup was not separately retained.'
        summary['pacing_observation']=next(x for x in pacing['results'] if x['case']==case)
        summary['captured_source_integrity']=next(x for x in source_audit['results'] if x['case']==case)
        summary['evidence_separation']=dict(
            physical_evidence=summary['receipt_path'],synthetic_or_replay_used_for_accreditation=False,
            confirmed_base=dict(state='CONFIRMED_BASE_ESTABLISHED',receipt='../d29-r102-base-2026-10-07/confirmed-base-receipt.json',
                sha256=summary['base_receipt_sha256'],changed=False),
            physical_frontier='PASS' if case in ('R1-03','R2-02') else 'BACKLOG_FRONTIER_PASS' if case=='R1-06' else 'PRELUDE_ONLY_INVALID_CLOCK' if case=='R2-04' else 'META_ISOLATION_OBSERVED_READY_OVERLAP_ABSENT',
            complete_load_condition='PASS' if case in ('R1-03','R2-02') else 'NOT_ACCREDITED' if case in ('R1-06','R2-09') else 'INVALID_RUN',
            pending_requirement=None if case in ('R1-03','R2-02') else 'Prospective R1-06 input/episode and deferred response gate reconciliation' if case=='R1-06' else 'Clock-continuous individual run of the same recipe' if case=='R2-04' else 'Natural ordinary READY overlap during affected Meta service')
        if case=='R2-09':summary['natural_overlap']=dict(definite=len(r['definite_ready_overlap']),possible=len(r['possible_ready_overlap']))
        if case=='R2-04':
            summary['clock_incident']=read(d/'clock-incident-analysis.json')
            summary['counts_scope']='Prelude observations only; no ordinary offer window, expiry/reclaim or full followup accredited.'
        summaries.append(summary)
    failures=[]
    for case in ('r1-03','r1-06','r2-02','r2-04','r2-09'):
        for d in sorted((OUT/case).iterdir()):
            if d.is_dir() and not d.name.endswith('-clock'):
                failures.append(dict(case_id=case.upper(),run_id=d.name,path=str(d.relative_to(OUT)),files=sum(p.is_file() for p in d.iterdir())))
    result=dict(state='CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY',base_state='CONFIRMED_BASE_ESTABLISHED',
        baseline=BASE,commits_created=0,full_matrix_executed=False,characterization=False,maximum_search=False,
        E=None,commercial_capacity=None,scenarios=summaries,attempt_inventory=failures,
        integrity_receipt=dict(path='integrity-audit-v4.json',sha256=sha(OUT/'integrity-audit-v4.json')),
        final_integrity_receipt=dict(path='final-integrity-v5.json',sha256=sha(OUT/'final-integrity-v5.json'),status=final_integrity['status']),
        closure_integrity_receipt=dict(path='closure-integrity-v6.json',sha256=sha(OUT/'closure-integrity-v6.json'),status=closure_integrity['status']),
        cleanup_receipt=dict(path='lab-cleanup-v2.json',sha256=sha(OUT/'lab-cleanup-v2.json')),
        regression=dict(d29=read(OUT/'d29-regression-complete.json'),application=read(OUT/'application-regression.json')),
        provenance_limitations='See INCIDENTES-Y-ALCANCE.md. Earlier orchestration pre-seal is empty; recovered files are closure evidence, not reconstructed prior seals.',
        deferred=['R1-04: no authorization for 17-conversation proposal','R2-09 slow_meta: not authorized','Complete 17-scenario matrix: not authorized'])
    write(OUT/'final-phase-receipt.json',result)
    markdown=['# Cierre de probes individuales D29','',
        'Entrega final: 8 de octubre de 2026. La carpeta conserva la fecha de apertura de esta fase.','',
        '`CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`',
        '`CONFIRMED_BASE_ESTABLISHED` conservada. No se ejecutó matriz completa ni se creó un commit.','',
        '| Probe | Resultado | Inputs | Episodios | Works | Claims observados | Commits outer exitosos |',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in summaries:
        eps=r['episodes'] if r['episodes'] is not None else 'No acreditable'
        markdown.append(f"| {r['case_id']} | {r['status']} | {r['accepted_inputs']} | {eps} | {r['works']} | {sum(r['claim_bound_events_by_role'].values())} | {r['successful_outer_commits_total']} |")
    markdown += ['', 'Los commits de esta tabla son los eventos outer `commit_end` exitosos de todos los journals. Los receipts de reconstrucción también cuentan por separado los commits con efectos de población (ingreso/claim); no son el mismo denominador.', '',
        '## Condición ejecutada y evidencia', '',
        '- **R1-03:** población 2×3, 2:1 sobre los mismos instantes de la cadencia global de la base; 16/8 aceptaciones reales, 24 episodios/works. Dos planners concurrentes y un sender; clocks originales y cortes System pasan.',
        '- **R1-06:** ocho inputs de backlog, cuatro conversaciones/org, READY natural antes del primer claim; después 24 inputs ordinarios con rotación de tres slots. La cuarta no recibe oferta ordinaria. La frontera de backlog/origen/edad/drain pasa; el gate completo queda pendiente por coalescing (32→31) y por la conciliación de una salida suprimida mediante `deferred_to_new_input` ante input posterior. No se extiende automáticamente la excepción aprobada sólo para R2-02.',
        '- **R2-02:** 2×3, pacing base, hold LLM de 120 s, 24 inputs→23 episodios/works con partición causal completa. La agrupación ocurre en la organización afectada; el peer recibe ofertas y progresa durante el hold. Intersecciones de clock válidas. No hubo captura System prospectiva en ese intento.',
        '- **R2-04:** intento 0004 **INVALID_RUN**. El preámbulo tuvo commit/crash real y lease intacto de 900 s; el calendario quedó fijado S=L−P (P≈30,600523019 s). Antes de abrir oferta, Windows ajustó la hora +2,1357499 s (Kernel-General, RecordId 317254), seguido de +0,0005084 s. Ingress detectó intersección imposible en seq 11081; System también registra Time-Service. El monitor detuvo la corrida. **No hubo oferta base, reclaim acreditado ni los 240 s de seguimiento**. El único input/work de la tabla es del preámbulo; no se presenta como prueba de carga. No se corrige ni segmenta el reloj y no se cambia la hora del host.',
        '- **R2-09 uncertain_meta:** 2×3, 24 inputs/episodios/works. Los 12 faults afectan sólo a Meta en la organización objetivo; todos los works tienen dos llamadas LLM completas. No se observa intersección READY–Meta afectada, ni siquiera como intervalo posible. No se añade cola ni retraso para forzarla. No hubo captura System prospectiva en ese intento.', '',
        'Las tasas son las referencias físicas del receipt aceptado, no una afirmación de capacidad: base [1,9607508002652434; 1,9607508002652434] inputs/min; R1-03 reasigna el calendario global 2:1 sin recalibración. Se conservan costes de servicio, dos planners, un sender, batch/poll, y ventanas. El detalle de pacing usa emisiones/aceptaciones físicas por slot, nunca replay como evidencia.', '',
        '## Receipts y hashes', '']
    for r in summaries:
        markdown.append(f"- [{r['case_id']} — {r['run_id']}]({r['receipt_path']}): `{r['receipt_sha256']}`. Errores: {', '.join(r['errors']) or 'ninguno' }.")
    markdown += ['', 'Los manifests capturados de los cinco probes incluyen los mismos 809 archivos backend esperados (789 del baseline y 20 de infraestructura de evaluación); ningún hash difiere. R1-06 0002 y R2-04 0004 incluyen además el sello prospectivo de los scripts de revision2, verificado sin cambios. Los límites del sello vacío previo permanecen documentados.', '',
        'Pacing real por intento, commits de aceptación y lateness respecto al slot: [pacing-audit.json](pacing-audit.json). Inventarios de fuentes y hashes: [probe-source-audit.json](probe-source-audit.json). Un PASS de pacing o fuentes no constituye PASS del escenario completo.']
    markdown += ['', '## Integridad, regresión y cleanup', '',
        f"Integridad de runtime/históricos: {integrity['runtime_and_history_intact']}. Los 789 Python del archivo ejecutado son idénticos al baseline; el checkout conserva sus diferencias previas de finales de línea. La base mantiene SHA-256 `{result['scenarios'][0]['base_receipt_sha256']}`.",
        f"Regresión D29: {result['regression']['d29']['status']}, {result['regression']['d29']['distinct_tests_executed']} tests distintos ejecutados, {result['regression']['d29']['remaining_skips']} omisiones restantes. El primer run omitió 9; la segunda ejecución completó esos 9 con receipts preservados. Aplicación: **{result['regression']['application']['status']}**. B3 pasó 39 tests; el sender reportó 42 tests y 53 errores operacionales/setup/teardown después de `psycopg.errors.OutOfMemory`. W1 quedó interrumpida y las otras cinco suites no corrieron. No se demostró la regresión completa de aplicación. El intento monolítico previo quedó incompleto y se conserva.",
        'Los dos laboratorios privados se cerraron; puertos, directorios de cluster, todas sus bases y credenciales fueron retirados. Tras OutOfMemory no se pudo inventariar las bases de regresión por SQL: la prueba de cleanup es la parada del servidor, puerto cerrado y eliminación verificada del cluster privado completo. Los DROP individuales ya registrados se conservan. Se preservan los logs y fuentes recuperables sin copiar credenciales. Los cambios de documentos/skills ajenos a esta fase se dejaron intactos.', '',
        f"Comprobación final posterior a regresión: {final_integrity['status']}; [final-integrity-v5.json](final-integrity-v5.json).", '',
        f"Comprobación posterior al cleanup: {closure_integrity['status']}; [closure-integrity-v6.json](closure-integrity-v6.json). La verificación de fuentes ejecutadas se conserva del corte previo al cleanup; los históricos, fuentes protegidas, base, HEAD, ausencia de procesos y puertos se vuelven a comprobar después.", '',
        'Los límites de procedencia, la preparación inicial fallida, los errores de conductores y todos los intentos anteriores están documentados en [INCIDENTES-Y-ALCANCE.md](INCIDENTES-Y-ALCANCE.md). El intento R2-04 0003 no es PASS válido aunque su conductor lo hubiera declarado así.', '',
        '## Decisiones antes de otra fase', '',
        '1. R1-06: revisar prospectivamente la conciliación input→episodio y las obligaciones de respuesta cuando `deferred_to_new_input` suprime una salida obsoleta. La evidencia física no muestra pérdida de inputs ni drain pendiente; el gate de carga actual no pasa.',
        '2. R2-09: decidir si se conserva pendiente la condición de solapamiento natural o se autoriza una propuesta metodológica distinta. No se aumenta delay, backlog ni retención de planners en esta fase.',
        '3. R2-04: autorizar previamente un procedimiento de continuidad del reloj para el host de evaluación y después una repetición individual con la misma receta. El guard contra suspensión no impide que el servicio de hora ajuste el reloj. Se conserva el gate original y no se cambia runtime ni configuración de producción.',
        '4. Completar las siete suites de aplicación que no tienen PASS en un entorno de evaluación con recursos disponibles. El error OutOfMemory y el cierre de conexión son evidencia de infraestructura; no permiten atribuir ni descartar una regresión del runtime. No se modificaron tests, durabilidad o configuración para facilitar el resultado.',
        '5. R1-04 y slow_meta permanecen fuera del alcance autorizado. No se ejecutará la matriz completa sin revisión del resultado.', '',
        'La carpeta de esta fase contiene únicamente infraestructura de evaluación, evidencia y documentación. No se editaron contratos D29/B8/B9/E4 ni runtime de producción. Los archivos nuevos/modificados de esta continuación se enumeran en el índice de artefactos; el estado general del repositorio incluye además trabajo previo no perteneciente a esta fase.']
    (OUT/'ENTREGA.md').write_text('\n'.join(markdown)+'\n',encoding='utf-8')
    index={p.relative_to(OUT).as_posix():dict(sha256=sha(p),bytes=p.stat().st_size) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='artifact-index-v2.json' and '__pycache__' not in p.parts}
    write(OUT/'artifact-index-v2.json',index)
    print(json.dumps(dict(state=result['state'],scenarios=[dict(case_id=r['case_id'],status=r['status']) for r in summaries],artifacts=len(index))))

if __name__=='__main__':main()
