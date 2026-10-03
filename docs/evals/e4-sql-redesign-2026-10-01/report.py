"""Generate the final Spanish report from verified receipts, without runtime edits."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def table(kind):
    rows = read('matrix-post-' + kind + '.json')
    lines = ['| Cardinalidad | OLD p50 | NEW p50 | OLD p95 | NEW p95 | OLD p99 | NEW p99 | OLD max | NEW max |',
             '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for i in range(0, len(rows), 2):
        old, new = rows[i:i+2]
        values = [f"{r['execution_ms'][key]:.3f}" for key in ('p50','p95','p99','max') for r in (old,new)]
        lines.append('| ' + str(old['x']) + ' | ' + ' | '.join(values) + ' |')
    return '\n'.join(lines)


def main():
    verification = read('verification-summary.json')
    assert verification['status'] == 'OPTIMIZATION_VERIFIED'
    cleanup = read('cleanup.json')
    assert cleanup['stopped'] and cleanup['data_directory_absent']
    commits = read('commits.json')
    metrics = read('metrics-summary.json')
    stress = next(p for p in metrics['points'] if p['kind']=='conversations' and p['x']==1000)
    old, new = metrics['stress_old'], metrics['stress_new']
    before = max(old['message_nodes'], key=lambda n:n['loops'])
    future = next(n for n in new['message_nodes'] if n['removed_per_loop']==1603)
    residual = max((n for n in new['nodes'] if n['relation']=='organizations_organization'),
                   key=lambda n:n['total_time_times_loops'])
    fields = [
        ('Estado', '**OPTIMIZATION_VERIFIED**; una única optimización de consulta.'),
        ('Baseline', '`' + verification['baseline'] + '`; HEAD verificado antes del diseño y sin mezclar cambios previos.'),
        ('Runtime anterior', '`' + verification['old_runtime'] + '`; selector congelado en el oracle de tests.'),
        ('Commits', 'Runtime/tests: `' + commits['runtime_tests'] + '`. Docs/evidencia: commit que contiene este informe; SHA exacto en el cierre del chat.'),
        ('HEAD final', 'El commit de documentación que contiene este informe. Resolver con `git rev-parse HEAD`; se informa el SHA exacto en el chat para evitar una referencia circular.'),
        ('Alternativas', 'A: relación no correlacionada de orgs futuras en una sentencia. B: materialización previa en Python, dos sentencias. CTE materializado, forecast sobre <=3 candidatos e índice específico también considerados, con STOP documentado.'),
        ('SQL OLD', '[SQL congelado](sql-old.json); [SQL OLD de la comparación final](sql-post-old.json). Parámetros separados.'),
        ('SQL candidatos', '[A](sql-A.json), [B, dos sentencias](sql-B.json), [NEW final](sql-post-new.json).'),
        ('Query count OLD', '1 statement por invocación; sin N+1 de Django.'),
        ('Query count NEW', '1 statement por invocación; alternativa B evaluada con 2.'),
        ('Índices actuales', '42 índices inventariados en las tres tablas; [DDL](indexes.json) idéntico al [post-fix](indexes-post.json). Message: direction/status, org/conversation/created, conversation/semantic/created y FKs. TurnWork: org/conversation, lease/retry y unicidad. Conversation: org/state/activity, FKs y PK.'),
        ('Índice nuevo', 'NO; 0.'),
        ('Persistencia nueva', 'NO; sin estado derivado ni counters.'),
        ('DESIGN_DECISION', '[Decisión previa al cambio de runtime](DESIGN_DECISION.md).'),
        ('Elegida', 'A, preagregar organizaciones con ordinary pending Message en `(clock, clock+1s]` y correlacionar los predicados de org.'),
        ('Por qué', 'Elimina los scans repetidos, mantiene la QuerySet lazy y una sola instantánea SQL; A/B con mejora material comparable. B agrega una lista proporcional a orgs futuras y una segunda instantánea.'),
        ('Oracle states', 'Diseño: 320 estados, 640 evaluaciones A/B. Post-fix inicial: 320. Cierre con no-eligible explícito: 321 estados (21 manuales + 300 generados).'),
        ('Generated states', '300 por ejecución de oracle, seed 20261001; mismas combinaciones comparables. Otros 160 estados en el test unitario de NULL, límites, retries, leases y exclusiones.'),
        ('Decision mismatches', '**0** en diseño, post-fix y cierre; igualdad de IDs de conversaciones/orgs en orden y yield/no-yield.'),
        ('OLD loops', 'Conversations 10/25/50/100/250/500/1000: máximo Message 13/28/53/103/253/503/1003.'),
        ('NEW loops', 'Máximo Message = **1 en los 14 puntos**. Tres scans de Message, cada uno una vez. Continúan correlaciones sobre org/claims pequeños.'),
        ('OLD buffers', 'Stress: raíz 215477 shared hits; Message forecast 214332; shared reads 0; temp read/write 0.'),
        ('NEW buffers', 'Stress: raíz 7867 shared hits; tres scans Message de 39 hits cada uno; shared reads 0; temp read/write 0.'),
        ('Matrix Messages OLD', '[Matriz paired completa](matrix-post-messages.json); tabla Messages debajo.'),
        ('Matrix Messages NEW', '[Misma matriz/dataset](matrix-post-messages.json); 8 conversaciones controladas.'),
        ('Matrix Conversations OLD', '[Matriz paired completa](matrix-post-conversations.json); tabla Conversations debajo. Evidencia histórica anterior preservada.'),
        ('Matrix Conversations NEW', '[Misma matriz/dataset](matrix-post-conversations.json); 2000 pending Messages controlados.'),
        ('p50 before/after', f"Stress: {stress['old']['p50']:.3f} → {stress['new']['p50']:.3f} ms."),
        ('p95 before/after', f"Stress: {stress['old']['p95']:.3f} → {stress['new']['p95']:.3f} ms; {stress['p95_ratio']:.2f}x."),
        ('p99 before/after', f"Stress: {stress['old']['p99']:.3f} → {stress['new']['p99']:.3f} ms."),
        ('max before/after', f"Stress: {stress['old']['max']:.3f} → {stress['new']['max']:.3f} ms."),
        ('EXPLAIN before', f"[Plan JSON OLD](explain/post/OLD-conversations-1000.json): ejecución representativa {old['execution_ms']:.3f} ms; planning {old['planning_ms']:.3f} ms."),
        ('EXPLAIN after', f"[Plan JSON NEW](explain/post/NEW-conversations-1000.json): ejecución representativa {new['execution_ms']:.3f} ms; planning {new['planning_ms']:.3f} ms."),
        ('Nodo dominante before', f"Causa: Seq Scan channels_message forecast, {before['loops']} loops, tiempo inclusivo × loops {before['total_time_times_loops']:.3f} ms, {before['removed_per_loop']} filas removidas/loop (promedio redondeado PG)."),
        ('Nodo dominante after', f"Trabajo residual forecast: Seq Scan organizations_organization, {residual['loops']} loops sobre 3 orgs, {residual['total_time_times_loops']:.3f} ms inclusivos. Scan Message futuro: 1 loop, {future['total_time_times_loops']:.3f} ms, 1603 filas removidas."),
        ('Scaling before', 'Trabajo grande de Message repetido aproximadamente por Conversation: crecimiento multiplicativo; hay una sentencia SQL, pero correlación patológica.'),
        ('Scaling after', 'Trabajo sobre Message independiente de Conversations en las matrices. Org/recencia/ranking aún escalan con Conversations; no se afirma coste total constante ni escalabilidad universal.'),
        ('Safety', 'PASS: bypass explícito de forecast y safety después de W1; suites históricas B5/planner/worker conservadas.'),
        ('Monotonic READY', 'PASS: ordinary inbound preclaim hereda el deadline READY y ambos Messages entran en membership; suites W1 monotonic intactas.'),
        ('B3', 'PASS; claim, anchor, cursor, membership, lease/epoch/token/fencing sin cambios.'),
        ('B9B', 'PASS; observation/miss con 0 admission; forecast 0 reservation; el presupuesto conserva su autoridad existente tras claim válido.'),
        ('B9C', 'PASS; máximo PROCESSING/org observado = 1, sin capacidad/counters derivados del forecast.'),
        ('Multiprocess', '5 tests nuevos PASS con OS PIDs y PostgreSQL backend PIDs distintos; mismos candidatos, miss/fallback, slot ocupado, desaparición, deadline, safety y ordinary join. [Journal](repair-processes.results.b9c-processes.jsonl).'),
        ('Regression', '**775 históricos + 3 nuevos de selector + 5 nuevos de procesos = 783 IDs únicos PASS**. Expectativas históricas sin editar; B3/B5/B6/B7/B8/B9A/B9B/B9C, E4, W1, planner, worker, B4 sender y módulos afectados incluidos.'),
        ('IDs', '[Inventario único aprobado](passed-ids.json); históricos: [659 aprobados retenidos](regression-partial.json) + [continuación 0](regression-resume-0.results.json)/[continuación 1](regression-resume-1.results.json); unitarios [journal](new-final.results.passed.jsonl), procesos [recibo](repair-processes.results.json).'),
        ('skips/xfail', '0 skips, 0 xfail; 0 fallos y 0 errores en los gates finales.'),
        ('Checks', 'PASS: migrate, check, makemigrations --check --dry-run y migrate --check. [Recibo](checks.exit.json).'),
        ('Migrations', '0 nuevas; esquema y DDL de índices iguales.'),
        ('Rollback', 'Revertir únicamente el commit runtime/tests indicado en campo 4 mediante git revert. Sin migración inversa ni transformación de datos; selector OLD disponible como referencia de tests. No se ejecutó rollback.'),
        ('Privacy', 'Datos sintéticos aislados; artefactos SQL/oracle/plans guardan estados/IDs/tiempos, sin cuerpos, prompts/responses, phones o names reales. Logs funcionales crudos descartados después de extraer recibos; [registro con hashes](privacy.json). Sin instrumentación productiva.'),
        ('Infra cleanup', 'PASS: bases propias eliminadas, PG del experimento detenido y directorio de datos ausente; binarios/venv compartidos preservados. [Recibo](cleanup.json).'),
        ('PROFILE run', 'NO; no se ejecutó PROFILE-BETA-1.'),
        ('B9E run', 'NO; sin ejecutar una suite B9E formal ni modificar sus umbrales.'),
        ('PROFILE histórico', 'FAIL / PRODUCT_FAILURE, runtime 83ee3b2, B9E-LOAD-01-CLAIM p95=10.015949 s contra 10 s. No actualizado por estos resultados SQL.'),
        ('B9E status', 'FAIL histórico, intacto.'),
        ('B9', 'IN_PROGRESS.'),
        ('Production gates', 'B0 cerrado; B7B=False; flags={}; release grants=[]; PENDING_ACTIVATION_REQUIREMENTS. Configuración/contratos del repo conservados; no hubo consulta ni operación sobre un servicio de producción.'),
        ('Active clinics', '0 activadas por este encargo; estado documental requerido = 0.'),
        ('Deploy', 'NO.'),
        ('Próximo paso', 'STOP tras una optimización verificada. PROFILE-BETA-1 será un encargo separado sobre el runtime congelado. Sin segundo tuning ni cambios de quiet/hard cap/N/batch/poll/LLM calls.')]
    assert len(fields) == 60
    lines = ['# E4 — Rediseño estructural SQL: cierre', '',
        'Fecha de inicio: 2026-10-01. Cierre: 2026-10-02 (America/Mexico_City).', '',
        '## Resultado', '',
        '**OPTIMIZATION_VERIFIED**. Se eliminó la repetición del scan de Message por Conversation con una sola reescritura ORM, sin esquema ni persistencia nueva. Los recibos finales validan equivalencia, planes, regresión y concurrencia.', '',
        '## Reporte solicitado — 60 campos', '',
        '| # | Campo | Resultado / evidencia |', '|---:|---|---|']
    lines.extend(f'| {i} | {name} | {value} |' for i,(name,value) in enumerate(fields,1))
    lines.extend(['', '## Método y límites', '',
        'PostgreSQL 16.15 real aislado, fsync=on y synchronous_commit=on. Una base recién clonada del template migrado por punto; OLD y NEW se ejecutaron sobre exactamente el mismo dataset, con cinco warmups independientes y 30 repeticiones por variante. Métrica: Execution Time de EXPLAIN ANALYZE en ms, excluye planning y red. No se vació la caché del SO. OLD se ejecutó primero. Proporción pending READY/future=80/20, tres organizaciones controladas y tres Conversations históricas adicionales para recencia.', '',
        'Los percentiles usan el índice `ceil(q/100*(n-1))` del vector ordenado, fijado en benchmark.py. Son mediciones sintéticas con ruido de scheduling del host; no crean un SLO SQL. En Messages=10 hay ocho READY y dos future, con ocho Conversations controladas; las tres históricas se reportan aparte. La cardinalidad de organizaciones y el historial durable no se escalaron independientemente.', '',
        'Los tiempos y buffers de un nodo EXPLAIN son inclusivos de sus subplanes; no deben sumarse para inferir tiempo propio. El Index Scan externo de Conversation domina el tiempo inclusivo en ambos planes: 5550.628 ms OLD y 109.217 ms NEW. El diagnóstico causal es el forecast Message repetido dentro de ese nodo. La sustitución deja un scan de la pequeña relación de organizaciones por Conversation. Ranking y recencia siguen teniendo trabajo proporcional a Conversations.', '',
        'La auditoría congelada tenía p95=5336.076 ms para C=1000. La comparación paired adicional midió OLD=7113.485 ms; se conservan ambos recibos y no se reemplaza la evidencia histórica por la nueva.', '',
        '## Matriz Messages — 8 Conversations controladas', '', table('messages'), '',
        '## Matriz Conversations — 2000 pending Messages', '', table('conversations'), '',
        '## Diseño medido antes de implementar', '',
        'Matrices A/B completas: [Messages](matrix-full-messages.json) y [Conversations](matrix-full-conversations.json). Incluyen query count, p50/p95/p99/max, planning, nodos, loops, shared hit/read, filas removidas, temp buffers y sorts. B suma Execution Time/planning de sus dos statements. [Planes completos](explain/full/). A fue elegida antes de editar worker.py; el registro de decisión conserva sus STOPs y límites.', '',
        'En el stress final todos los temp buffers son cero; sorts quicksort de 25 KB. Los JSON de planes conservan las métricas por nodo para todos los puntos. Ningún índice fue añadido para obtener esta mejora.', '',
        '## Cobertura de estados y procesos', '',
        '[Oracle final](oracle-final.json) y [clasificación explícita de yield](oracle-classified.json): healthy READY, dos healthy, noisy/near/far, busy current/upcoming, never-claimed, recencia menor/mayor/igual, safety/W1, READY join, candidato desaparecido/busy, deadline crossed, múltiples Conversations/org, múltiples orgs, stale observation y no eligible. Los estados de observación se comparan en orden con OLD; las transiciones de claim y membership se verifican además con procesos reales. La clasificación adicional repite los mismos 321 estados, sin contarlos como cobertura independiente. Distingue una selección vacía de un yield comparando contra el mismo selector con una relación futura vacía; no-eligible tiene yield=False. Los recibos anteriores conservan su bandera histórica de vacío/no-vacío.', '',
        'Los procesos observan ambos antes del primer claim y permanecen vivos para observar el efecto del segundo claim/miss. Los PIDs independientes constan en el journal. El clock controlado permite cruzar el límite de deadline de manera determinista; no representa una medición temporal del poll productivo. El claim transaccional no fue modificado.', '',
        'Los generadores combinan el estado observado por el selector sobre fixtures sintéticos con FKs y ámbitos consistentes. No cambian las FKs ni los campos de anchor/cursor/context; conservan unicidad, completed/outcome y los requisitos de token/lease/attempts para PROCESSING. PostgreSQL aplica los constraints durante las mutaciones. No son un replay completo de cada historia durable: ese contrato se prueba por separado con claims reales y las suites B3/B9C.', '',
        '## Incidentes del harness', '',
        'Se conservan los recibos de intentos anteriores como diagnósticos, fuera del conjunto de aprobación final: descubrimiento inicial de clases importadas duplicó selección (35 frente a 8) y se detuvo solo ese árbol de procesos; imports convertidos a aliases de módulo. Después, cuatro failures y un error de procesos se debieron al keyword erróneo now en el harness nuevo. Se corrigió a eligible_at sin cambiar durable.claim_turn; los cinco procesos se repitieron y aprobaron. Los tres unitarios ya aprobados se aceptan por IDs y hashes de fuentes finales, sin contar los fallos históricos como éxitos.', '',
        'La interrupción inicial del host ocurrió después de migraciones y antes de recibos de matrices. Se recuperó el template aislado. Una colisión de nombres SQL por el filesystem Windows ocurrió antes de medir el primer punto post-fix: se cambiaron los nombres a sql-post-old/new y se recreó solo el punto incompleto. Ningún recibo exitoso de benchmark fue sobrescrito. [Registro de incidentes](incidents.json).', '',
        'Una segunda interrupción dejó las dos tandas históricas sin recibo final, después de 659 éxitos por ID escritos al journal. Se verificaron todos los hashes de fuentes y la ausencia de fallos en sus logs; se retuvieron solo los IDs con status=ok y se ejecutaron los 116 pendientes en bases nuevas clonadas del mismo template. El inventario final prueba 775 IDs históricos únicos, sin duplicar ni declarar completo el run interrumpido. [Recuperación](environment-regression-resume.json).', '',
        '## Reproducción y trazabilidad', '',
        'Scripts locales: benchmark.py (pilot/full/resume/post), candidates.py, oracle.py, verify.py, recover.py, analyze.py, cleanup.py, sanitize.py y report.py. La reproducción requiere los binarios PG16 y el entorno Python de aceptación existentes; sus rutas están en environment-*.json. Los guards de HEAD del driver conservan la baseline histórica: una nueva reproducción debe fijar explícitamente su SHA auditado y usar un directorio de salida nuevo. benchmark.py rechaza sobrescribir recibos exitosos. Este run utilizó full interrumpido, resume con template retenido y después post; una corrida full normal limpia su cluster al terminar y debe preparar de nuevo un template aislado antes de post.', '',
        '[Resumen de verificación](verification-summary.json), [resumen de métricas](metrics-summary.json), [hashes de fuentes](regression-0.results.sources.json) y [manifest de artefactos](artifact-manifest.json). Los hashes de fuentes/recibos son de bytes del working tree auditado en Windows; el manifest incluye además SHA256 normalizado a LF para verificar artefactos tras otro checkout Git. Commit docs identificado por pertenencia para evitar hashes autorreferenciales.', ''])
    target = OUT / 'README.md'
    assert not target.exists()
    target.write_text('\n'.join(lines), encoding='utf-8')
    print('REPORT_WRITTEN_60_FIELDS')


if __name__ == '__main__':
    main()
