"""Seal local policy evidence and verify immutable earlier receipts."""
import hashlib
import json
from pathlib import Path
import re

out = Path(__file__).resolve().parent
root = out.parents[2]
assert not (out/'MANIFEST.json').exists()
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
history = {}
for path in (root/'docs/evals/inbox-readiness-2026-10-22/MANIFEST.json',
             root/'docs/evals/inbox-b2-guarantees-2026-10-22/MANIFEST.json'):
    data = json.loads(path.read_text(encoding='utf-8'))['files']
    entries = data if isinstance(data,list) else [dict(path=k,**v) for k,v in data.items()]
    for entry in entries:
        name = entry['path']
        if name.startswith(('docs/evals/', 'docs/compliance/inbox-privacy-review-2026-10-22/')):
            expected = entry.get('sha256',entry.get('digest'))
            assert digest(root/name) == expected, 'Historical artifact changed: '+name
            history[name] = expected

tests = {}
latest_cases = {}
for path in sorted(out.glob('test-*.json')):
    receipt = json.loads(path.read_text(encoding='utf-8'))
    assert receipt['test_database_remains'] is False
    log = path.with_suffix('.log').read_text(encoding='utf-8')
    ran = re.search(r'Ran (\d+) tests?',log)
    assert ran, 'Missing complete test summary: '+path.name
    errors = set(re.findall(r'^(?:ERROR|FAIL): \S+ \(([^)]+)\)',log,re.M))
    cases = re.findall(r'^test_\S+ \(([^)]+)\) \.\.\.',log,re.M)
    assert len(cases) == int(ran.group(1)), 'Incomplete method list: '+path.name
    if path.name == 'test-policy-first.json':
        expected = 'apps.channels.tests.test_media_integration.MediaEntrypointTests.test_nightly_job_is_bounded_and_disabled_is_inert'
        assert receipt['exit_code'] == 1 and errors == {expected}, 'Unexpected initial failure'
        assert "KeyError: 'attempted'" in log
    else:
        assert receipt['exit_code'] == 0 and not errors and re.search(r'^OK\s*$',log,re.M)
    for case in cases:
        # Prefer the explicit later targeted verification; filenames are not time.
        if case not in latest_cases or path.name == 'test-operations-final.json':
            latest_cases[case] = dict(passed=case not in errors, receipt=path.name)
    # Verbosity 2 gives a unique method name for each result; RBAC logs can be
    # interleaved, so totals come from unittest's authoritative completion line.
    tests[path.name] = dict(tests=int(ran.group(1)), errors=len(errors), skipped=bool(re.search(r'\bskipped\b',log)),
        database_removed=True, exit_code=receipt['exit_code'])
    assert not tests[path.name]['skipped'], 'A skipped restore drill is not evidence'
assert 'test-policy-first.json' in tests and 'test-operations-final.json' in tests
assert all(case['passed'] for case in latest_cases.values()), 'Unresolved test failure'
build = json.loads((out/'landing-build.json').read_text(encoding='utf-8'))
assert build['state'] == 'PASS' and len(build['built_pages']) == 18 and not build['published']
migration = json.loads((out/'migration-local.json').read_text(encoding='utf-8'))
assert migration['state']=='PASS' and not migration['production_touched']
check = json.loads((out/'check-final.json').read_text(encoding='utf-8'))
assert check['exit_code'] == 0
drill_log = (out/'test-operations-final.log').read_text(encoding='utf-8')
drill = re.search(r'RESTORE_DUMP_DRILL (\{[^\n]+\})',drill_log)
assert drill, 'Actual dump/restore receipt required'
drill = json.loads(drill.group(1))
(out/'restore-drill.json').write_text(json.dumps(drill,ensure_ascii=False,indent=2),encoding='utf-8')
summary = dict(state='PASS_LOCAL_ONLY', policy='180d availability / 7d verified operational purge',
    tests=tests, unique_tests_passed=len(latest_cases), initial_failure='one outdated maintenance-report mock; corrected and targeted rerun',
    restore_drill='real pg_dump/pg_restore, isolated disposable PostgreSQL, synthetic local objects',
    landing_pages=18, local_migration='channels.0018_media_retention_policy',
    historical_immutable_artifacts_verified=len(history), ops_recipient_channel='ACCEPTED_DEBT_NON_BLOCKING',
    b9='ACCEPTED_DEBT_NON_BLOCKING; no rerun', provider_b2_real='PENDING', meta_reception='DEFERRED_TO_USER',
    privacy_published=False, legal_seed_executed=False, whatsapp_activated=False)
(out/'test-cases.json').write_text(json.dumps(latest_cases,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'README.md').write_text('''# Retención y cierre Inbox — 23-10-2026

**PASS local**; decisión de parámetros registrada. Operación real no certificada.

Implementado: reloj PostgreSQL compartido, bloqueo por vencimiento/revocación,
verificación posterior de todas las versiones/markers, incidentes persistentes,
umbrales 24h/7d, reintentos diarios y resultados operativos visibles. Ledger
independiente del dump, hold de acceso y reconciliación sin reabrir tráfico.
Trabajos recuperados sin persistencia acreditada se congelan.

Validación: `summary.json` y `test-cases.json` recogen las ejecuciones dirigidas.
La primera conservó 45 PASS y un error por mock de reporte antiguo; se corrigió
ese mock y se repitió ese caso junto con los controles afectados por los ajustes
finales. No se repitieron los otros PASS, B9 ni suites completas.
`restore-drill.json` acredita pg_dump/pg_restore de
una DB desechable con referencias antiguas; ledger sobreviviente, acceso
revocado/expirado bloqueado, timestamps conservados y jobs cancelados. Los
binarios fueron sintéticos en almacenamiento privado local: **no es una prueba
de B2**, su volumen/custodia, clocks operativos, cron o inventario de réplicas.

El aviso nuevo compila en las **18 páginas** de la landing de revisión. El repo
original conserva su hash. No hubo publicación, seed legal ni activación.
0018 se aplicó solo a la base de desarrollo habitual tras dump privado verificado;
recibos migration-local*.json. Preview/producción sin tocar.

Responsable y canal de alertas pendientes **no bloqueantes**, por excepción
expresa del usuario. Los recibos HTTP simulados no prueban atención humana.
La plantilla observa umbrales cada 15min: no promete entrega exacta a las 24h.
Persisten pendientes B2 real/región/contrato, capacidad y operación del cron,
inventario de objetos posteriores al dump, publicación/seed/reaceptación y
Meta/recepción a cargo del usuario. La activación requiere sus gates y autorización.

Los manifiestos anteriores conservan sus recibos; fuentes vivas modificadas
por esta decisión se sellan aquí. `runtime/` y ledger se excluyen de Git/Docker.
MANIFEST.json registra los hashes de fuentes, documentos y recibos de esta entrega.
''',encoding='utf-8')

sources = '''.gitignore
backend/.dockerignore
backend/.env.example
backend/config/settings.py
backend/apps/agent/inbox_media.py
backend/apps/channels/models.py
backend/apps/channels/media_clock.py
backend/apps/channels/media_storage.py
backend/apps/channels/media_worker.py
backend/apps/channels/media_incidents.py
backend/apps/channels/media_revocations.py
backend/apps/channels/migrations/0018_media_retention_policy.py
backend/apps/channels/management/commands/maintain_inbox_media.py
backend/apps/channels/management/commands/inbox_media_ops.py
backend/apps/channels/tests/test_media_pipeline.py
backend/apps/channels/tests/test_media_integration.py
backend/apps/channels/tests/test_media_retention_policy.py
backend/apps/channels/tests/test_media_restore_drill.py
scripts/crontab.example
docs/CIERRE-INBOX-WHATSAPP.md
docs/compliance/cierre-b2-whatsapp-2026-10-22.md
docs/compliance/arco.md
docs/runbooks/inbox-media.md
docs/runbooks/RUNBOOK-RESTORE.md
docs/decisions/2026-10-22-inbox-media-retention-policy.md
docs/decisions/2026-10-23-inbox-media-alert-ops-deferred.md'''.splitlines()
paths = [root/name for name in sources]
paths += [p for p in out.glob('*') if p.is_file() and p.name != 'MANIFEST.json']
paths += list((root/'docs/compliance/inbox-privacy-review-2026-10-23').glob('*'))
manifest = dict(schema=1, private_runtime_excluded=True, previous_artifacts_verified=len(history),
    files=[dict(path=p.relative_to(root).as_posix(),sha256=digest(p),bytes=p.stat().st_size) for p in sorted(set(paths))])
(out/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
print('Sealed files:',len(manifest['files']))
