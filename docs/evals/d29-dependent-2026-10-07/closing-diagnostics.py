"""Append final raw-capture diagnosis without changing any sealed attempt."""
import json
import runpy
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
read,sha,write=lab['read'],lab['sha'],lab['write']


def lines(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def main():
    original_index=read(HERE/'artifact-index.json')
    mismatches=[name for name,value in original_index.items() if sha(HERE/name)!=value['sha256']]
    if mismatches:
        raise RuntimeError('Previously sealed artifact changed: '+str(mismatches))
    directory=HERE/'matrix-existing/matrix-existing-R209-uncertainmeta'
    job=read(directory/'participant-plan.json')
    report=read(directory/'job-result.json')
    wire_paths=list(directory.glob('*-wire.jsonl'))
    wire=[r for p in wire_paths for r in lines(p)]
    affected=job['organization_ids'][0]
    misplaced=[r for r in wire if r['event']=='result' and r['boundary']=='llm'
               and r['organization_id']==affected and r['result']=='UNCERTAIN']
    witnessed={r['turn_work_id'] for r in wire if r['event']=='dispatch' and r['boundary']=='llm'}
    missing=[dict(work_id=e['turn_work_id'],organization_id=e['organization_id'],
                  conversation_id=e['conversation_id'],member_ids=e['member_ids'])
             for e in report['episodes'] if e['turn_work_id'] not in witnessed]
    source=HERE/'frozen-sources/backend/apps/agent/tests/scheduling_characterization/execution.py'
    source_lines=source.read_text(encoding='utf-8').splitlines()
    statement=next((i+1,line) for i,line in enumerate(source_lines) if "result_kind = 'UNCERTAIN'" in line)
    if not misplaced or "event['boundary']" in statement[1]:
        raise RuntimeError('Expected physical fault-boundary diagnosis not supported')
    diagnosis=dict(scenario='R2-09',variant='uncertain_meta',status='NOT_ACCREDITED',
        classification='EVALUATION_PROVIDER_IMPLEMENTATION_DEFECT',
        cause='UNCERTAIN_META_BRANCH_DOES_NOT_FILTER_META_BOUNDARY_AND_ALSO_INJECTS_LLM_TIMEOUTS',
        source=dict(path=str(source.relative_to(HERE)),sha256=sha(source),line=statement[0],statement=statement[1].strip()),
        actual_uncertain_llm_results=misplaced,claimed_works_without_llm_witness=missing,
        actual_wire_result_counts=dict(Counter(r['boundary']+':'+r['result'] for r in wire if r['event']=='result')),
        evidence={str(p.relative_to(HERE)):sha(p) for p in wire_paths+[directory/'job-result.json',directory/'independent-verification.json']},
        inference_limit='Missing service witness is not proof of a runtime invariant violation; the injected scenario already violates its declared fault scope.',
        repair_needed='Evaluation-only contained provider must target Meta exclusively; retain this invalid attempt and use new run IDs after approval of the next closure phase.',
        runtime_changed=False,old_receipts_changed=False,new_execution_performed=False)
    integrity=lab['integrity']()
    final=read(HERE/'final-receipt.json')
    value=dict(schema='d29-closure-delivery-diagnostic-v1',global_status=final['global_status'],
        final_receipt=dict(path='final-receipt.json',sha256=sha(HERE/'final-receipt.json')),
        preserved_index=dict(path='artifact-index.json',sha256=sha(HERE/'artifact-index.json'),
                             checked_artifacts=len(original_index),mismatches=mismatches),
        final_integrity_intact=integrity['intact'],diagnosis=diagnosis,
        classification_or_result_changed=False,new_load_runs=0,commits=0)
    write(HERE/'closing-diagnostics.json',value)
    text='''# D29: entrega y diagnóstico de cierre

Estado: **CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY**.
La matriz intentó los 17 escenarios y sus 36 variantes. La evaluación final
acredita 30 variantes y 11 escenarios completos. Los 25 probes físicos finitos
de los ocho adaptadores previamente aceptados pasaron y conservan ese alcance.

| Frontera dependiente | Resultado de esta fase |
| --- | --- |
| R1-03 | El intento individual pasó; la repetición final no acredita tiempos por contradicción de clock. Se conserva el evento de sincronización del reloj del host. |
| R1-04 | 24 episodios resueltos; 629 selecciones con testigos. No se observó la secuencia causal completa de forecast/miss/yield/nueva elegibilidad. |
| R1-05 | Ambas variantes acreditadas: 32 aceptaciones/episodios en simultánea y 28 en concentrada; retorno y drain verificados. El primer intento fallido se conserva. |
| R1-06 | Rechazo de preparación: requiere 4 conversaciones por organización y la base aceptada fija 3. No se ejecutó backlog ni se amplió la población. |

La matriz también conserva pendientes R2-02 (24 inputs forman 23 episodios,
carga distinta de la declarada), R2-04 (reclaim finito acreditado, sin carga
base concurrente) y R2-09 (detalles siguientes).

En R2-09 Meta lento, el verificador original pasó sus checks, pero ninguna de
las 12 llamadas afectadas tiene intersección temporal demostrable con cola
READY sin claim. El chequeo suplementario conserva la condición completa
NOT_ACCREDITED; progreso ordinario posterior no acredita esa concurrencia.

En R2-09 Meta incierto se identificó un **defecto del provider de evaluación**:
la rama UNCERTAIN no filtra la frontera Meta y también inyecta timeouts LLM.
Los wire journals registran 9 resultados LLM UNCERTAIN. Hay 9 trabajos
reclamados sin testigo LLM y el verificador conserva
CLAIMED_WORK_WITHOUT_SERVICE_WITNESS. No se presenta esa ausencia como una
violación demostrada del runtime; la inyección ya incumple el alcance
declarado. La admisión/resultado/no-reenvío observados son subfronteras, no
acreditación del escenario completo. No se modificó ni repitió esta corrida.

La regresión D29 final pasó **78/78**, sin omitidos. La regresión de aplicación
existente pasó **231/231**. Se comprobaron los 41 receipts de limpieza de
intentos, se eliminó el laboratorio privado y sus credenciales y se cerró su
puerto. Baseline, 3409 fuentes protegidas y 2766 artefactos históricos intactos.
Cero commits, sin cambios en runtime/B8/B9/E4, contratos o CONFIRMED_BASE.
Los cambios de esta fase están exclusivamente en este directorio de evaluación.

Las siguientes decisiones quedan para revisión del usuario; no se ejecutan:

| Pendiente | Siguiente alcance concreto recomendado |
| --- | --- |
| R1-03 | Resolver la discontinuidad temporal del entorno antes de repetir con la misma base; conservar el fallo, sin relajar el gate de clock. |
| R1-04 | Definir y autorizar una receta causal concurrente que preserve el pacing y la edad; si necesita modificar las condiciones aceptadas, aprobar primero esa diferencia. |
| R1-06 / R2-02 | Decidir una fixture/población que produzca los episodios exigidos y su relación explícita con la base; no atribuir una población ampliada a la base actual. |
| R2-04 | Autorizar el adapter de reclaim con oferta base concurrente y expiración natural. |
| R2-09 | Corregir el aislamiento de la inyección Meta en evaluación y definir la condición concurrente de cola que debe acreditarse antes de nuevas ejecuciones. |

No se inicia otra fase, caracterización, búsqueda de máximo ni cálculo de E.

Este anexo no reescribe el informe ni los receipts sellados:
[informe de la matriz](report.md), [receipt final](final-receipt.json),
[diagnóstico verificable](closing-diagnostics.json),
[índice original conservado](artifact-index.json),
[índice de entrega](delivery-index.json).
'''
    with (HERE/'delivery-report.md').open('x',encoding='utf-8') as stream:
        stream.write(text)
    index={p.relative_to(HERE).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))
           for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='delivery-index.json'}
    write(HERE/'delivery-index.json',dict(schema='d29-delivery-index-v1',
        original_index_sha256=sha(HERE/'artifact-index.json'),artifacts=index))
    print(json.dumps(dict(original_artifacts_intact=len(original_index),delivery_artifacts=len(index),
                          misplaced_llm_timeouts=len(misplaced),missing_service_works=len(missing),
                          integrity_intact=integrity['intact'],new_load_runs=0)),flush=True)


if __name__=='__main__':
    main()
