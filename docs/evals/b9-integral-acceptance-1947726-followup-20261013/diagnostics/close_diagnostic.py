"""Classify retained diagnostic observations and package reporting inputs."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
SHA = '194772677ca4e9fe1a1dec7f4dafa48396a6c583'


def read(name):
    return json.loads((HERE/name).read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    p = HERE/name
    assert not p.exists(), name
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def main():
    result, command = read('diagnostic.results.json'), read('diagnostic.command.json')
    rows = [json.loads(line) for line in (HERE/'diagnostic.ids.jsonl').read_text().splitlines()]
    assert result['tests'] == len(rows) == 11
    assert set(r['id'] for r in rows) == set(read('diagnostic-selected.json'))
    assert Counter(r['outcome'] for r in rows) == {'FAIL': 10, 'ERROR': 1}
    assert all(r['traceback'] for r in rows)
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 1
    assert command['test_invocations'] == 1 and command['invalidating_incident'] is None
    assert not (HERE/'diagnostic-STOP.json').exists()
    for label in ['after-export', 'prepared', 'before-test', 'after-test', 'final-before-cleanup']:
        assert not read('integrity-'+label+'.json')['mismatches']
    for label in ['before-test', 'after-test']:
        for kind in ['dependency-files', 'diagnostic-seal']:
            assert not read(kind+'-check-'+label+'.json')['mismatches']
    assert read('cleanup.json')['state'] == 'PASS'
    assert read('resource-observer-closure.json')['state'] == 'PASS'
    awake = read('awake-request/closure.json')
    assert awake['state'] == 'PASS_API_REQUEST_AND_RESTORATION' and awake['matches_original_thread_state']
    assert awake['explicit_stop_requested'] and read('resource-observer-closure.json')['explicit_stop_requested']
    for label in ['before', 'after']:
        clock = read('clock-state-'+label+'.json')
        assert clock['exit_code'] == 0 and not clock['configuration_changed']
        assert all(s in clock['stdout'] for s in ['ActiveState=active', 'SubState=running', 'UnitFileState=enabled'])
    monitor = [json.loads(line) for line in (HERE/'diagnostic.monitor.jsonl').read_text().splitlines()]
    stats = {'samples': len(monitor),
             'minimum_host_available_bytes': min(r['host']['physical_available'] for r in monitor),
             'minimum_guest_available_bytes': min(r['guest']['physical_available'] for r in monitor),
             'minimum_backing_disk_available_bytes': min(r['guest']['disk_available'] for r in monitor),
             'maximum_absolute_clock_skew_seconds': max(abs(r['wall_minus_monotonic_seconds']) for r in monitor),
             'maximum_host_sample_age_seconds': max(r['host_age'] for r in monitor),
             'maximum_awake_sample_age_seconds': max(r['awake_age'] for r in monitor)}
    assert stats['minimum_host_available_bytes'] >= 2*1024**3
    assert stats['minimum_guest_available_bytes'] >= 2*1024**3
    assert stats['minimum_backing_disk_available_bytes'] >= 1024**3
    assert stats['maximum_absolute_clock_skew_seconds'] <= 1
    save('monitor-summary.json', dict(stats, state='VALID_DIAGNOSTIC_OBSERVATION', invalidating_incidents=[]))
    prior = read('prior-evidence-before.json')
    drift = [n for n,h in prior.items() if not (REPO/n).is_file() or digest((REPO/n).read_bytes()) != h]
    original = read('checkout-before.json')['unrelated']
    unrelated = {n: {'exists': (REPO/n).exists(), 'sha256': digest((REPO/n).read_bytes()) if (REPO/n).exists() else None} for n in original}
    assert not drift and unrelated == original
    save('preservation-of-prior-work.json', {'prior_campaign_files_checked': len(prior),
         'prior_campaign_mismatches': drift, 'unrelated_unchanged': True, 'unrelated': unrelated,
         'r9_decision_and_raw_receipts_unchanged': True, 'ACTA_unchanged': True})
    save('final-environment.json', {'state': 'PASS', 'private_resources_retired': True,
         'resource_observer_closed': True, 'awake_original_thread_state_restored': True,
         'clock_configuration_unchanged': True, 'WSL_timesyncd': 'active/running/enabled',
         'Windows_W32Time_changed': False, 'global_power_policy_changed': False})
    # Read-only Git blob excerpts explain contract differences without executing code.
    wanted = {
        'backend/apps/agent/tests/harness.py': ['legacy_write_component'],
        'backend/apps/agent/tests/test_regression_f2.py': ['test_20_01_offer_then_create', 'test_20_06_expired_confirmation_never_executes', 'test_20_09_b6_fixed_vet_used'],
        'backend/apps/agent/tests/test_regression_suite.py': ['test_int11_price_flow'],
        'backend/apps/agent/goals.py': ['capture'],
        'backend/apps/agent/tools.py': ['_goal_gate'],
        'backend/apps/agent/result_renderers.py': ['render_read'],
        'backend/apps/agent/tests/test_b2_results.py': ['test_price_uses_field_not_coincident_id', 'test_currency_and_multiple_services_stay_associated'],
        'backend/apps/agent/tests/test_b0_containment.py': ['test_read_result_does_not_prove_write_or_price'],
    }
    excerpts = []
    for name, functions in wanted.items():
        blob = subprocess.run(['rtk', 'proxy', 'git', 'show', SHA+':'+name], cwd=REPO,
                              capture_output=True, check=True).stdout
        source = blob.decode(); lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name in functions:
                excerpts.append({'path': name, 'function': node.name, 'start_line': node.lineno,
                     'end_line': node.end_lineno, 'candidate_blob_sha256': digest(blob),
                     'source': '\n'.join(lines[node.lineno-1:node.end_lineno])})
    save('source-evidence.json', {'candidate_sha': SHA, 'read_only': True, 'excerpts': excerpts})
    price = next(r for r in rows if r['id'].endswith('test_int11_price_flow'))
    write = [r for r in rows if r != price]
    observations = []
    for row in rows:
        trace = row['traceback']
        if row == price:
            category = 'STATIC_CONTRACT_CONFLICT_PRICE_RENDERING'
            finding = 'El test espera T0_GUARD_BLOCKED y ausencia del precio; el candidato devuelve Consulta general: $350.00 MXN. El renderer actual y los tests B2 exigen precios del catálogo validados y asociados a su moneda. Esta aserción legacy contradice ese contrato.'
            certainty = 'Observed assertion and static contract conflict; no product correction performed'
        elif row['outcome'] == 'ERROR':
            category = 'APPOINTMENT_CREATION_PRECONDITION_NOT_MET'
            finding = 'Appointment.objects.get() lanza DoesNotExist después de proponer y responder sí; no se llega a comprobar el veterinario. La causa interna anterior no queda demostrada por esta excepción.'
            certainty = 'Observed missing fixture/effect precondition; internal cause unresolved'
        elif 'awaiting_confirmation' in trace:
            category = 'PROPOSAL_STATE_EXPECTATION_NOT_MET'
            finding = 'Se esperaba awaiting_confirmation; se obtuvo planner_reply o reply. No se alcanzó el estado de propuesta esperado por este guion.'
            certainty = 'Observed decision mismatch; fixture-versus-product root cause unresolved'
        elif 'confirm_expired' in trace:
            category = 'EXPIRY_BRANCH_NOT_REACHED_AS_EXPECTED'
            finding = 'Se esperaba confirm_expired; se obtuvo reply. Este resultado no demuestra ejecución de una confirmación vencida; falla la llegada al branch que el test pretendía verificar.'
            certainty = 'Observed branch mismatch; no unsafe mutation proven'
        else:
            category = 'SLOT_RACE_COMMIT_BRANCH_NOT_REACHED_AS_EXPECTED'
            finding = 'Se esperaba commit_slot_taken; se obtuvo reply después del guion de propuesta/afirmativa. No se valida el escenario de carrera en la frontera esperada.'
            certainty = 'Observed branch mismatch; internal cause unresolved'
        observations.append({'id': row['id'], 'outcome': row['outcome'], 'category': category,
             'finding': finding, 'certainty': certainty, 'traceback_source': 'diagnostic.ids.jsonl'})
    save('diagnostic-classification.json', {'state': 'VALID_DIAGNOSTIC_NONPASS', 'date_local': '2026-10-13',
         'candidate_sha': SHA, 'reproduced': {'FAIL': 10, 'ERROR': 1}, 'test_invocations': 1,
         'environment_invalidating_incidents': [], 'findings': observations,
         'WRITE_root_cause_status': 'UNRESOLVED_FIXTURE_VERSUS_PRODUCT',
         'WRITE_static_hypothesis': 'F2 uses legacy_write_component and supplies parameters through a scripted tool call. The wrapper patches confirmation boundaries, while goals.capture with B6 metadata accepts only parameters already supported by binding evidence. A fixture/contract mismatch is plausible; the exact returned internal error was not captured, so this is not a proven causal trace.',
         'PRICE_root_cause_status': 'STATIC_ASSERTION_CONFLICT_WITH_CURRENT_VALIDATED_CATALOG_RENDERER',
         'disk_exhaustion_required_to_reproduce': False, 'suite_order_contamination_required_to_reproduce': False,
         'universal_product_defect_proven': False, 'product_tests_or_harness_modified': False,
         'original_r9_decision': 'PENDING_UNCHANGED', 'integral_acceptance_reclassified': False})
    write_report(rows, stats, observations, len(prior))
    save('closure-reporting.json', {'state': 'PASS', 'diagnostic_completed': True,
         'classification_completed_with_explicit_limits': True, 'test_invocations': 1,
         'formal_acceptance_campaigns_started': 0, 'source_changes': False, 'commits_created': 0,
         'reporting_script_sha256': digest(Path(__file__).read_bytes())})
    print('DIAGNOSTIC_REPORTING_PASS', len(prior))


def write_report(rows, stats, observations, prior_count):
    def short(row):
        return row['id'].split('.tests.', 1)[1]
    table = '\n'.join('| '+short(r)+' | '+r['outcome']+' | '+r['category']+' |' for r in observations)
    report = f'''# Diagnóstico acotado de r9 — 13-10-2026

**Los 11 resultados problemáticos se reproducen: 10 FAIL y 1 ERROR.**
Se ejecutó una única suite de 11 IDs sobre el candidato
`{SHA}`, con Python 3.13.2, Django 6.0.5, PostgreSQL 16.15 privado y el lock original.
No hubo incidente invalidante de recursos o reloj. Este diagnóstico identifica
problemas reproducibles con margen suficiente; la caída de disco de r9 no es
necesaria para reproducirlos.

No es una nueva campaña integral ni sustituye sus gates. r9 conserva PENDING,
sus recibos dañados y todos sus resultados originales. Frontend, seguridad y
PROFILE no se ejecutaron aquí. No se cambió producto, tests, fixtures o umbrales.

## Qué se observó

| Test | Resultado | Clasificación observable |
|---|---|---|
{table}

Seis tests WRITE no llegan a `awaiting_confirmation`: cinco devuelven
`planner_reply` y uno `reply`. Otros dos esperan `commit_slot_taken` y reciben
`reply`; el de vencimiento espera `confirm_expired` y recibe `reply`. El décimo
caso WRITE lanza `Appointment.DoesNotExist` antes de verificar el veterinario.
Estas trazas muestran fallos de las expectativas de la regresión; no prueban
por sí solas una escritura indebida, una carrera mal resuelta ni la ejecución
de una confirmación vencida.

La hipótesis de incompatibilidad del fixture F2 con B6 tiene apoyo estático:
`legacy_write_component` sustituye fronteras de confirmación, pero
`goals.capture` conserva la exigencia de evidencia de binding para los parámetros.
El guion legacy aporta parte de ellos mediante una llamada de herramienta
scripted. Faltan valores internos de la llamada que falla para cerrar la causa
exacta; no se declara que todos los casos WRITE sean tests obsoletos ni un defecto
de producto. El siguiente trabajo debe distinguir esos dos casos con cambios
explícitos y comprobables, sin rebajar las garantías de B6.

En precio hay una discrepancia concreta de contrato: el test pide
`T0_GUARD_BLOCKED` y ausencia de `350`, mientras la respuesta real es
**`Consulta general: $350.00 MXN.`**. El código actual reemplaza la prosa libre
del modelo por un render de datos READ validados. Los tests B2 del mismo candidato
exigen precio y moneda del catálogo; B0 bloquea precios no respaldados por esa
lectura. Por eso esta aserción legacy contradice el renderer vigente. Corregirla
requiere conservar la prueba de que la prosa sensible del LLM no se emite y de
que el precio corresponde al servicio/moneda; no basta con quitar el assert.

[Clasificación por ID y límites](diagnostic-classification.json) ·
[Tracebacks persistidos por ID](diagnostic.ids.jsonl) ·
[Recibo de la suite](diagnostic.results.json) ·
[Recibo del proceso](diagnostic.command.json) ·
[Fuentes exactas usadas para la clasificación](source-evidence.json).

El valor `exit_code: 11` del recibo de suite conserva el retorno de
`DiscoverRunner.suite_result` (10 fallos + 1 error). El proceso de tests terminó
con **exit 1**. El controlador/capturador terminó con **exit 0** al haber guardado
correctamente ese resultado; ese cero no significa tests aprobados.

## Validez y cierre

El proceso monitorizado tardó **{read('diagnostic.command.json')['seconds']:.3f} s**, incluida
la creación/migración/destrucción de la base. unittest reportó 11 tests en
21,280 s; el recibo del runner cubre un intervalo más amplio.
En {stats['samples']} muestras, el mínimo de RAM libre fue
**{stats['minimum_host_available_bytes']/1024**3:.3f} GiB en Windows** y
**{stats['minimum_guest_available_bytes']/1024**3:.3f} GiB en WSL**; C: mantuvo al menos
**{stats['minimum_backing_disk_available_bytes']/1024**3:.3f} GiB**. Desviación máxima de reloj:
**{stats['maximum_absolute_clock_skew_seconds']:.9f} s**. Se conservaron los umbrales de
2 GiB de RAM, 1 GiB de disco y 1 s de reloj. Los tracebacks se guardaron y
sincronizaron al disco al producirse cada fallo.

Las **3.332 fuentes**, **13.508 dependencias** y **18 archivos de sello** pasaron
las comparaciones antes y después. El scope fue exactamente los 11 IDs
autorizados: sin omisiones, skips, xfail o pruebas adicionales.

Cleanup PASS: Django retiró la base de tests al terminar; se guardó el inventario
SQL y se retiró la base de control, PostgreSQL, el puerto 35480 y el workspace
propio. El observador cerró y la solicitud temporal de actividad restauró el
estado original de su thread. systemd-timesyncd permaneció active/running/enabled;
no se pausó sincronización ni se cambió W32Time o una política global de energía.
Se comprobaron **{prior_count} archivos anteriores**, incluidos los de r9, sin cambios,
además de los tres cambios ajenos del checkout. El acta anterior sigue intacta.

## Qué hace falta para avanzar

Reconciliar las expectativas legacy con el contrato actual: confirmar y resolver
el origen de los casos WRITE sin debilitar B6, y actualizar la prueba de precio
para distinguir datos validados de prosa no respaldada. Eso constituye un encargo
de corrección separado y produce un candidato nuevo si cambian tests o producto.
Una nueva aceptación integral se decide después de esas correcciones y de su
verificación; el espacio recuperado por sí solo no elimina estos fallos.

No hubo commits, push, despliegue o activación. R1-04 y los requisitos de
activación/operación/privacidad siguen como estaban. La evidencia nueva se
conserva en un paquete propio con recuperación verificada y selección Git
explícita: [índice de recuperación](RECOVERY.md).
'''
    (HERE/'REPORT.md').write_text(report, encoding='utf-8', newline='\n')
    (HERE/'RECOVERY.md').write_text('''# Conservación del diagnóstico

[Reporte](REPORT.md) · [Inventario](artifact-index.json) ·
[Manifest del paquete](preservation-manifest.json) · [Recuperación comprobada](preservation-verification.json) ·
[Entrega Git](delivery-verification.json).

Los logs originales están dentro del ZIP sin normalización. Para recuperar en
una carpeta ausente o vacía, desde este expediente:

```powershell
rtk proxy python -B restore_wsl.py --destination C:/ruta/nueva/diagnostico-recuperado
```

Se verifican hashes de partes, archivo y miembros, y una recuperación interna
más otra mediante el CLI real. El índice Git contiene únicamente los paths
explícitos del diagnóstico y las dos reglas compartidas de entrega; no se cambia
el acta ni la decisión de r9. No se crea commit ni se hace push.
''', encoding='utf-8', newline='\n')
    with (HERE/'README.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n## Ejecución autorizada y cierre\n\nEl usuario respondió «si» y autorizó el diagnóstico propuesto. Terminó una única\nejecución con 10 FAIL y 1 ERROR; cleanup e integridad PASS. El texto previo se\nconserva como propuesta anterior. Véanse el [reporte final](REPORT.md) y la\n[conservación independiente](RECOVERY.md).\n')


if __name__ == '__main__':
    main()
