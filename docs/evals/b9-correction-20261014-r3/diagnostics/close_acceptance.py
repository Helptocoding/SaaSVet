"""Report the classified fixed campaign from retained receipts, after cleanup."""
import hashlib
import json
from pathlib import Path
from collections import Counter

HERE=Path(__file__).resolve().parents[1]
REPO=HERE.parents[2]

def read(name):return json.loads((HERE/name).read_text(encoding='utf-8'))
def digest(data):return hashlib.sha256(data).hexdigest()
def save(name,data):
    assert not (HERE/name).exists(),name
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    classification=read('final-classification.json')
    assert classification['decision'] in ('PASS','FAIL','PENDING')
    assert read('cleanup.json')['state']=='PASS'
    assert read('clock-restoration.json')['state']=='PASS'
    assert read('resource-observer-closure.json')['state']=='PASS'
    awake=read('awake-request/closure.json')
    assert awake['state']=='PASS_API_REQUEST_AND_RESTORATION' and awake['matches_original_thread_state']
    candidate=read('candidate.json')
    prior=read('prior-evidence-before.json')
    drift=[n for n,h in prior.items() if not (REPO/n).is_file() or digest((REPO/n).read_bytes())!=h]
    original=read('checkout-before.json')['unrelated']
    current={n:{'exists':(REPO/n).exists(),'sha256':digest((REPO/n).read_bytes()) if (REPO/n).exists() else None} for n in original}
    assert not drift and current==original
    save('preservation-of-prior-work.json',{'prior_campaign_files_checked':len(prior),
        'prior_campaign_mismatches':drift,'unrelated_unchanged':True,'unrelated':current})
    integrity=[];integrity_mismatches={}
    for pattern in ('integrity-*.json','dependency-check-*.json','seal-check-*.json'):
        for file in HERE.glob(pattern):
            receipt=read(file.name)
            if receipt['mismatches']:integrity_mismatches[file.name]=receipt['mismatches']
            integrity.append(file.name)
    if integrity_mismatches:assert classification['decision']=='PENDING'
    save('integrity-summary.json',{'state':'PENDING' if integrity_mismatches else 'PASS',
        'receipts':integrity,'mismatches':integrity_mismatches})
    statuses={}
    suite_observations=[];partial_journals={};partial_observations=[]
    for label in ['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5','full',
        'frontend-build','frontend-test','frontend-lint','frontend-smoke-urls','security','pip-audit','pnpm-audit',
        'profile-base','profile-blocked_llm','profile-meta_slow','profile-duplicate','profile-saturation']:
        cmd=HERE/'blocks'/(label+'.command.json');gate=HERE/'blocks'/(label+'.gate.json')
        if cmd.exists():
            c=json.loads(cmd.read_text());assert c['state']=='COMPLETED'
            statuses[label]={'state':json.loads(gate.read_text())['state'] if gate.exists() else 'INCOMPLETE',
                'exit_code':c['exit_code'],'seconds':c['seconds'],'formal_runs':1,
                'invalidating_incident':c['invalidating_incident']}
            if c['invalidating_incident']:statuses[label]['state']='PENDING_ENVIRONMENT_INTERRUPTION'
            if label=='full' and (HERE/'failure-classification.json').exists():
                statuses[label]['state']='PENDING_HARNESS_INCOMPATIBILITY'
                statuses[label]['classification_receipt']='failure-classification.json'
                statuses[label]['manual_stop_receipt']='manual-stop-request.json'
            result=HERE/'blocks'/(label+'.results.json')
            if result.exists():
                r=json.loads(result.read_text());statuses[label]['tests']=r['tests']
                statuses[label]['outcomes']={k:r.get(k) for k in ('failures','errors','skips','xfail','xpass')}
                statuses[label]['failed_ids']=r.get('failed_ids',[])
                suite_observations+=r['test_ids']
            journal=HERE/'blocks'/(label+'.ids.jsonl')
            if journal.exists() and not result.exists():
                entries=[json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
                partial_observations.extend(row['id'] for row in entries)
                partial_journals[label]={'path':'blocks/'+journal.name,'observations':len(entries),
                    'outcomes':dict(Counter(row['outcome'] for row in entries)),
                    'unique_ids':len({row['id'] for row in entries}),
                    'selected_ids':len(read(label+'-selected.json')),
                    'missing_ids':sorted(set(read(label+'-selected.json'))-{row['id'] for row in entries}),
                    'complete_suite_receipt':False,'accepted_as_complete_gate':False}
                statuses[label]['partial_journal']=partial_journals[label]
        else:statuses[label]={'state':'NOT_EXECUTED','formal_runs':0}
    save('block-status.json',statuses)
    save('execution-summary.json',{'candidate_tree':candidate['candidate_tree'],'formal_controller_invocations':1,
        'formal_command_blocks':len(list((HERE/'blocks').glob('*.command.json'))),
        'formal_reruns':0,'backend_id_observations_in_complete_receipts':len(suite_observations),
        'backend_unique_ids_in_complete_receipts':len(set(suite_observations)),
        'duplicate_observations_in_complete_receipts':len(suite_observations)-len(set(suite_observations)),
        'backend_id_observations_including_partial_journals':len(suite_observations)+len(partial_observations),
        'backend_unique_observed_ids_including_partial_journals':len(set(suite_observations+partial_observations)),
        'duplicate_observations_including_partial_journals':len(suite_observations)+len(partial_observations)-len(set(suite_observations+partial_observations)),
        'incomplete_suite_journals':partial_journals,
        'focused_development_verification_separate':read('prior-focused-verification.json'),
        'profile_variants_executed':sum(statuses['profile-'+s]['formal_runs'] for s in ['base','blocked_llm','meta_slow','duplicate','saturation']),
        'historical_results_transferred':False})
    monitors={}
    for label in statuses:
        file=HERE/('monitor-'+label+'.json')
        if not file.exists():continue
        rows=read(file.name)
        if rows:monitors[label]={'samples':len(rows),
            'min_host_bytes':min(r['host']['physical_available'] for r in rows),
            'min_guest_bytes':min(r['guest']['physical_available'] for r in rows),
            'min_disk_bytes':min(r['guest']['disk_available'] for r in rows),
            'max_clock_skew_seconds':max(abs(r['wall_minus_monotonic_seconds']) for r in rows)}
    save('monitor-summary.json',monitors)
    complete=classification['decision']=='PASS'
    if complete:assert read('technical-completion.json')['state']=='PASS'
    directed=statuses['directed']['state']=='PASS'
    scenario_names=['base','blocked_llm','meta_slow','duplicate','saturation']
    profiles={s:read('blocks/profile-'+s+'.json') for s in scenario_names if (HERE/('blocks/profile-'+s+'.json')).exists()}
    temporal_states={s:statuses['profile-'+s]['state'] for s in scenario_names}
    all_temporal=all(s=='PASS' for s in temporal_states.values())
    R={f'R{i:02}':('PASS_TECHNICAL_INTEGRAL' if complete else 'PENDING_INTEGRAL') for i in range(1,16)}
    if directed:
        for i in [2,3,4,5,10,12,13]:R[f'R{i:02}']='PASS_DIRECTED_SCOPE; integral decision '+classification['decision']
    R['R08']='DECISION_AND_LIMITS_DOCUMENTED'
    blocking=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5',
        'full','frontend-build','frontend-test','frontend-smoke-urls','security']
    R['R06']='PASS_LOCAL_BLOCKING_CHECKS; remote CI and real promotion separate' if all(statuses[n]['state']=='PASS' for n in blocking) else 'PENDING_LOCAL_BLOCKING_CHECKS'
    R['R07']='PASS_FIXED_PROFILE' if all_temporal else 'FAIL_APPLICABLE_PROFILE_GATE' if 'FAIL' in temporal_states.values() else 'PENDING_PROFILE_INCOMPLETE'
    R['R09']='PASS_ALL_FIVE_TEMPORAL_RECEIPTS' if len(profiles)==5 and all(statuses['profile-'+s].get('invalidating_incident') is None for s in scenario_names) else 'PENDING_TEMPORAL_COVERAGE; see profile-results-index.json'
    R['R11']='PASS_SCHEMA_AND_DIRECTED_COST_SCOPE' if directed and all(statuses[n]['state']=='PASS' for n in ['migration-drift','migrate','billing-schema']) else 'PENDING_SCHEMA_AND_COST_SCOPE'
    R['R14']='EXACT_CORRECTED_TREE_AND_METHOD_DOCUMENTED'
    R['R15']='DECISION_AND_RECOVERY_DOCUMENTED; operational privacy separate'
    I={f'I{i:02}':('PASS_TECHNICAL_INTEGRAL' if complete else 'PASS_DIRECTED_SCOPE; integral decision '+classification['decision'] if directed else 'PENDING_NO_COMPLETE_DIRECTED_GATE') for i in range(1,15)}
    if not all_temporal:
        I['I08']=('PASS_DIRECTED_SCOPE; ' if directed else '')+'PENDING_FULL_TEMPORAL_SAFETY_COVERAGE'
    if temporal_states['meta_slow']!='PASS':
        I['I11']=('PASS_DIRECTED_SCOPE; ' if directed else '')+'PENDING_META_SLOW_TEMPORAL_COVERAGE'
    save('candidate-decision.json',{'candidate_tree':candidate['candidate_tree'],'base_commit':candidate['base_commit'],
        'decision':classification['decision'],'cause':classification['cause'],'R01_R15':R,'I01_I14':I,
        'temporal_variant_states':temporal_states,
        'activation':'PENDING_ACTIVATION_REQUIREMENTS','R1-04':'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
        'E_P_UX':'SEPARATE_UNCHANGED_SCOPES','operational_requirements':{
            'R06_real_promotion_eval':'PENDING_SEPARATE','R13_release_readiness':'PENDING_SEPARATE','R15_P_A_P_B':'PENDING_SEPARATE'},
        'production_runtime_changed':False,'locks_changed':False,'test_changes':candidate['changed_paths'],
        'commits_created':0,'pushes_performed':0,'production_activation_or_deployment':False})
    rows='\n'.join('| '+label+' | '+s['state']+' | '+str(s.get('tests',str(s['partial_journal']['observations'])+'/'+str(s['partial_journal']['selected_ids'])+' parciales' if 'partial_journal' in s else '—'))+' | '+str(s.get('exit_code','—'))+' |' for label,s in statuses.items())
    metrics=['window_utc','inbound_count','outbound_count','healthy_claim','safety_dispatch','outbox_dispatch',
        'max_active_per_org_observed','max_pending_inbound_observed','max_outbound_attempts','generator_events',
        'turnwork_status','outbound_status','llm_calls','llm_call_count','provider_calls']
    save('profile-results-index.json',{'variants':{s:{'path':'blocks/profile-'+s+'.json','technical_pass':r.get('technical_pass'),'gates':r.get('gates'),
        'measurements':{k:r[k] for k in metrics if k in r}} for s,r in profiles.items()},
        'not_executed':[s for s in scenario_names if statuses['profile-'+s]['state']=='NOT_EXECUTED'],
        'without_complete_receipt':[s for s in scenario_names if s not in profiles],
        'historical_metrics_transferred':False})
    profile_rows=[]
    for s in scenario_names:
        r=profiles.get(s,{})
        for metric in ['healthy_claim','safety_dispatch','outbox_dispatch']:
            m=r.get(metric,{})
            profile_rows.append('| '+s+' | '+metric+' | '+str(m.get('count','—'))+' | '+str(m.get('missing','no field' if m else '—'))+' | '+str(m.get('p95_seconds','—'))+' | '+str(m.get('max_seconds','—'))+' |')
    profile_table='\n'.join(profile_rows)
    integrity_statement='PASS en todas las comparaciones registradas' if not integrity_mismatches else 'PENDING: diferencias registradas en integrity-summary.json'
    report=f'''# B9: aceptación del árbol corregido, campaña r3 — {classification['decision']}

**Decisión técnica: {classification['decision']}.** {classification['cause']}

Base `{candidate['base_commit']}`; árbol evaluado **`{candidate['candidate_tree']}`**.
Es un árbol Git reproducible con el [diff de dos archivos de tests](correction.diff),
sin commit nuevo. Runtime productivo, locks, cargas, tiempos y gates originales
se conservaron. El resultado corresponde a ese árbol, no se atribuye al commit
base sin las correcciones ni sustituye los resultados históricos de r9.

## Correcciones y verificación

F2 era un componente legacy explícito: sus argumentos del stub no aportaban
provenance B6. Su helper de turnos ahora evita crear accidentalmente un binding
en fixtures sin versión; los bindings existentes conservan el resolver real.
Se mantienen las aserciones de autorización/confirmación, vencimiento, carrera,
efecto único y ausencia de mutaciones indebidas. La oferta tras cancelar se
comprueba por su contenido y ausencia de una reserva nueva.

La prueba de precio exige servicio, precio y moneda del catálogo validado y
rechaza el precio/moneda contradictorios del modelo. No se acepta prosa sensible
no respaldada. No se cambió código productivo.

Verificación enfocada de la campaña anterior, sin repetición actual: **155 PASS, cero fallos/errores y un skip histórico
identificado**, de 156 IDs. Los 11 resultados problemáticos anteriores pasaron.
La primera iteración con un fallo de literal y la preparación rechazada por
hashes pertenecen al expediente anterior. Esta campaña no repite esa verificación
ni transfiere su resultado a los gates integrales actuales.
[Referencia conservada](prior-focused-verification.json).

Los 11 IDs problemáticos anteriores también registraron PASS en esta ejecución
de `full`. [Recibo actual por ID](diagnostics/full-original-11-progress.json).
Los dos skips actuales ya existían en el candidato original y no pertenecen
al inventario crítico. [Aplicabilidad](diagnostics/full-skip-applicability.json).

## Campaña de alcance fijo

| Bloque | Estado | IDs | Exit |
|---|---|---:|---:|
{rows}

Cada bloque/variante formal se ejecutó como máximo una vez. Los solapes entre
corpus, runners y full están deduplicados en [execution-summary.json](execution-summary.json).
Los skips/advisories conservan su aplicabilidad; no cubren requisitos críticos.
La orquestación local usa suites secuenciales, preservando los procesos internos
de los tests. No se afirma ejecución de CI remoto.

Los journals incompletos y sus IDs faltantes figuran en el resumen. Sus
observaciones no sustituyen un recibo completo ni acreditan un gate aprobado.

Los [recibos PROFILE](profile-results-index.json) conservan denominadores,
faltantes, latencias, máximos, colas, errores y gates de cada variante. No se
promedian percentiles entre organizaciones ni se transfieren métricas históricas.
Cuando una variante está NOT_EXECUTED, no existe evidencia temporal actual de ella.

| Variante | Frontera | Muestras | Faltantes | p95 s | Máximo s |
|---|---|---:|---:|---:|---:|
{profile_table}

`no field` conserva la ausencia del campo en el recibo; no se interpreta como
cero faltantes. Los gates, errores, estados durables y máximos de cola se
publican en el índice; las muestras originales permanecen en cada recibo.

## Conservación y cierre

Fuentes del árbol, dependencias y evaluador: **{integrity_statement}**.
Los [monitores por bloque](monitor-summary.json) conservan mínimos
de recursos y desviación de reloj. No se rebajaron las reservas autorizadas de
2 GiB de RAM, 1 GiB de disco ni el guard de reloj de 1 s.

Cleanup, restauración de sincronización WSL, cierre del observador y liberación
de la solicitud propia de actividad: **PASS**. W32Time y políticas globales de
energía/pantalla intactos. Se verificaron **{len(prior)} archivos históricos** y
los tres cambios ajenos sin diferencias. [Preservación](preservation-of-prior-work.json).

[Matriz R01–R15/I01–I14](candidate-decision.json), con activación
**PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y requisitos
operativos/privacidad separados. Sin commits, push, despliegue ni activación.

[Recuperación y selección de evidencia](README.md). La aprobación técnica, si
corresponde, se limita al árbol y contrato fijo evaluados; no acredita capacidad
comercial, carga máxima, estabilidad de cola o fairness fuerte.
'''
    if not profiles:
        start=report.index('Los [recibos PROFILE]')
        end=report.index('## Conservación y cierre',start)
        report=report[:start]+'''Las cinco variantes PROFILE permanecen **NOT_EXECUTED** según el
[índice de cobertura temporal](profile-results-index.json). No existen métricas
temporales actuales ni se transfieren métricas históricas.

'''+report[end:]
    report=report.replace('## Conservación y cierre', '''## Incompatibilidad y remediación acotada

`full` usó `test_b9i_full`. Siete workers B8B rechazaron ese nombre antes de
READY; el octavo FAIL bruto apareció durante la parada propia y se conserva
separado. [Clasificación](failure-classification.json). La terminación propia
SIGTERM/SIGKILL no acredita OOM ni un defecto del producto. El STOP automático
registra la ausencia del recibo completo; la causa previa queda en los trazas
y en [la solicitud de parada](manual-stop-request.json).

B8B/B8C/B8D/B8E exigen cuatro prefijos incompatibles entre sí. La
[especificación del siguiente ensamblaje](next-assembly-remediation.json)
particiona los mismos 3.331 IDs en cinco grupos: 3.213 generales y 21/41/27/29
de procesos B8B/B8C/B8D/B8E. La unión es exacta, sin omisiones ni duplicados.
Es una especificación estática: no se ejecutó otra campaña ni se cambiaron
producto, tests, guards, locks, cargas, tiempos o umbrales.

## Conservación y cierre''')
    report=report.replace('Los [monitores por bloque](monitor-summary.json) conservan mínimos',
        '''La [validación de muestras de recursos](resource-observation-validation.json)
revisó los intervalos de los diez comandos formales: no observó una reserva
de RAM agotada durante ellos (mínimo Windows: 2,151 GiB). Las bajas transitorias
de preparación y posteriores a la ejecución se conservan separadas y no se
presentan como valores de ejecución. Los [monitores por bloque](monitor-summary.json) conservan mínimos''')
    (HERE/'REPORT.md').write_text(report,encoding='utf-8',newline='\n')
    (HERE/'README.md').write_text('''# Conservación B9 corregido

[Reporte](REPORT.md) · [Decisión](candidate-decision.json) · [Bloques](block-status.json) ·
[Índice](artifact-index.json) · [Manifest](preservation-manifest.json) ·
[Prueba de recuperación](preservation-verification.json) · [Entrega](delivery-verification.json).

El paquete conserva logs originales y el diff sobre la base. Recuperar en una
carpeta ausente o vacía desde este expediente:

```powershell
rtk proxy python -B restore_wsl.py --destination C:/ruta/nueva/b9-recuperado
```

Se validan SHA-256 de partes, archivo y miembros. El empaquetador verifica
una recuperación interna y otra por CLI. No inicia pruebas ni PostgreSQL.
Las dos correcciones staged coinciden con el árbol evaluado según
[code-selection.json](code-selection.json); los paths de evidencia son explícitos.
Los logs se conservan dentro del ZIP sin normalización Git. No hay commit o push.
''',encoding='utf-8',newline='\n')
    acta=REPO/'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before=acta.read_bytes();assert b'B9 corregido r3 196aceb' not in before
    addition=f'''\n\n## B9 corregido r3 196aceb — {classification['date_local']} — aceptación {classification['decision']}

Base 1947726 y árbol {candidate['candidate_tree']}, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada anterior, sin repetición actual: 155 PASS y un skip histórico, 11 IDs previos PASS. Campaña formal de alcance fijo, sin reruns: **{classification['decision']}**. {classification['cause']} Cleanup y restauraciones PASS; {len(prior)} archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261014-r3/REPORT.md), [matriz](../b9-correction-20261014-r3/candidate-decision.json).\n'''.encode()
    acta.write_bytes(before+addition);assert acta.read_bytes()[:len(before)]==before
    save('acta-update.json',{'state':'PASS','append_only':True,'prior_prefix_bytes':len(before),
        'prior_prefix_sha256':digest(before),'appended_sha256':digest(addition),'final_sha256':digest(acta.read_bytes())})
    save('closure-reporting.json',{'state':'PASS','decision':classification['decision'],
        'sealed_evaluator_changed':False,'reporting_script_sha256':digest(Path(__file__).read_bytes())})
    print('ACCEPTANCE_REPORTING_PASS')

if __name__=='__main__':main()
