"""Build an isolated full landing copy with the prepared privacy notice. No publish."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = Path('C:/Users/LAP/Desktop/LandingSaaS/frontend')
WORK = OUT/'runtime/landing-review'
DRAFT = ROOT/'docs/compliance/inbox-privacy-review-2026-10-22/aviso-de-privacidad.astro'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not (OUT/'landing-build.json').exists() and not WORK.exists()
    assert shutil.disk_usage(ROOT).free > 4*1024**3
    preparation = json.loads((DRAFT.parent/'preparation.json').read_text())
    original_notice = SOURCE/'src/pages/aviso-de-privacidad.astro'
    assert digest(original_notice) == preparation['source_sha256'], 'Landing source changed since patch preparation'
    ignored = shutil.ignore_patterns('node_modules','dist','build','.astro','.git','__pycache__','.env','.env.*')
    WORK.mkdir(parents=True)
    frontend = WORK/'frontend'
    print('COPY_FULL_LANDING_SOURCE',flush=True)
    shutil.copytree(SOURCE,frontend,ignore=ignored)
    input_files = [p for p in frontend.rglob('*') if p.is_file()]
    inputs = [dict(path=p.relative_to(frontend).as_posix(),digest=digest(p)) for p in input_files]
    print('COPY_EXISTING_DEPENDENCIES_NO_INSTALL',flush=True)
    shutil.copytree(SOURCE/'node_modules',frontend/'node_modules')
    shutil.copy2(DRAFT,frontend/'src/pages/aviso-de-privacidad.astro')
    package = json.loads((frontend/'package.json').read_text())
    assert package['scripts']['build'] == 'astro build'
    node = shutil.which('node')
    env = {k:v for k,v in os.environ.items() if k.upper() in
           {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC'}}
    env.update(ASTRO_TELEMETRY_DISABLED='1',CI='true',NODE_ENV='production')
    args = [shutil.which('rtk'),'proxy',node,str(frontend/'node_modules/astro/astro.js'),'build']
    print('BUILD_START',flush=True)
    start = time.monotonic()
    with (OUT/'landing-build.log').open('wb') as log:
        process = subprocess.run(args,cwd=frontend,env=env,stdout=log,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=300)
    html = frontend/'dist/aviso-de-privacidad/index.html'
    if not html.exists():
        html = frontend/'dist/aviso-de-privacidad.html'
    rendered = re.sub('<[^>]+>',' ',html.read_text(encoding='utf-8')) if html.exists() else ''
    clauses = {value:value in rendered for value in ('180','22 de octubre de 2026','Backblaze',
               'eliminación física','usuarios autenticados','video','stickers')}
    unchanged = digest(original_notice) == preparation['source_sha256']
    result = dict(state='PASS' if process.returncode == 0 and all(clauses.values()) and unchanged else 'FAIL',
        exit_code=process.returncode,seconds=time.monotonic()-start,argv=args,
        build='full static Astro site, npm run build equivalent, prepared privacy draft applied in copy only',
        clauses=clauses,original_landing_notice_unchanged=unchanged,
        original_landing_written=False,dependencies_installed=False,
        built_pages=sorted(p.relative_to(frontend/'dist').as_posix() for p in (frontend/'dist').rglob('*.html')),
        original_source_snapshot=inputs,draft_digest=digest(DRAFT),published=False,
        public_https_verified=False,legal_version_promoted=False)
    (OUT/'landing-build.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('argv','original_source_snapshot','built_pages')}),flush=True)
    raise SystemExit(0 if result['state'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
