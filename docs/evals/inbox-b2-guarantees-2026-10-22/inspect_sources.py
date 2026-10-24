"""Read-only evidence inventory. No credentials, provider calls or test reruns."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
LANDING = Path('C:/Users/LAP/Desktop/LandingSaaS')


def record(path, label):
    content = path.read_bytes()
    return dict(path=str(path), label=label, digest=hashlib.sha256(content).hexdigest(), bytes=len(content))


def main():
    target = OUT/'source-inventory.json'
    assert not target.exists()
    selected = [
        'backend/apps/channels/media_worker.py', 'backend/apps/channels/media_storage.py',
        'backend/apps/channels/media_transfer.py', 'backend/apps/channels/media_ingest.py',
        'backend/apps/channels/models.py', 'backend/apps/channels/management/commands/maintain_inbox_media.py',
        'backend/apps/agent/inbox_media.py', 'backend/apps/agent/tests/test_inbox_media.py',
        'backend/apps/channels/tests/test_media_pipeline.py', 'backend/apps/channels/tests/test_media_integration.py',
        'frontend/src/pages/inbox/MediaBubble.jsx', 'frontend/src/pages/inbox/useMediaUrl.js',
        'frontend/src/pages/inbox/MediaBubble.test.jsx', 'backend/config/settings.py',
        'backend/Procfile', 'scripts/crontab.example', 'infra/Caddyfile',
        'scripts/pg-backup.sh', 'scripts/pg-restore.sh', 'docs/compliance/vendors.md',
        'docs/compliance/arco.md', 'docs/decisions/2026-08-22-p60-whatsapp-inbox-decisions.md']
    records = [record(ROOT/name, 'implementation/configuration/documentation') for name in selected]
    records += [record(LANDING/name, 'landing-read-only') for name in (
        'CLAUDE.md','frontend/package.json','frontend/astro.config.mjs',
        'frontend/src/pages/aviso-de-privacidad.astro')]
    prior = json.loads((ROOT/'docs/evals/inbox-phase3-2026-10-22/manifest.json').read_text())
    # The old manifest is a list; compare exact bytes only for relevant program,
    # test and fixed job inputs, not live tracking documents changed afterward.
    by_path = {r['path']:r for r in prior}
    compared = [p for p in selected if p in by_path and not p.startswith('docs/')]
    mismatches = [p for p in compared if hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != by_path[p]['sha256']]
    settings = (ROOT/'backend/.env').read_text(encoding='utf-8') if (ROOT/'backend/.env').exists() else ''
    configured = {}
    for key in ('MEDIA_B2_ENDPOINT_URL','MEDIA_B2_REGION_NAME','MEDIA_B2_BUCKET',
                'MEDIA_B2_ACCESS_KEY_ID','MEDIA_B2_SECRET_ACCESS_KEY'):
        # Presence only. Never output any configured credential or env contents.
        configured[key] = any(line.strip().startswith(key+'=') and line.split('=',1)[1].strip().strip('"\'')
                              for line in settings.splitlines() if not line.lstrip().startswith('#'))
    result = dict(state='READ_ONLY_INSPECTION', files=records,
        retained_phase3_source_comparison=dict(checked=len(compared),mismatches=mismatches,
             applicable_prior_results=not mismatches,new_test_runs=0),
        local_media_configuration_presence=configured,
        local_private_media_exists=(ROOT/'backend/private-media').exists(),
        landing_country_declared='United States', media_bucket_region_proven=False,
        provider_tests_executed=False, b9_runs=0)
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'files'}), flush=True)


if __name__ == '__main__':
    main()
