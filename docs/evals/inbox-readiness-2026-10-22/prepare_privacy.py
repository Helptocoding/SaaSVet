"""Prepare review copies only; do not publish, sign a DPA or promote LegalDocument."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
TARGET = ROOT / 'docs/compliance/inbox-privacy-review-2026-10-22'
SOURCE = Path('C:/Users/LAP/Desktop/LandingSaaS/frontend/src/pages/aviso-de-privacidad.astro')


def main():
    assert not (TARGET / 'preparation.json').exists(), 'Already prepared'
    TARGET.mkdir(exist_ok=True)
    original = SOURCE.read_text(encoding='utf-8')
    draft = original.replace('lastUpdated="22 de agosto de 2026"', 'lastUpdated="22 de octubre de 2026"')
    draft = draft.replace('Archivos intercambiados por el canal (imágenes, audio o documentos)',
                          'Archivos recibidos por el canal (imágenes, audio, video, documentos y stickers)')
    draft = draft.replace('días</strong> y después son eliminados; el texto del mensaje, su caption y los metadatos',
        'días</strong> desde que se guardan en el almacenamiento operativo. Al vencer ese plazo dejan de estar disponibles y se inicia su eliminación física mediante el proceso periódico de mantenimiento. Si ocurre una incidencia de borrado, el acceso permanece bloqueado mientras se resuelve; el texto del mensaje, su caption y los metadatos')
    draft = draft.replace('proveedor, con acceso controlado del servicio.',
        'proveedor, con acceso controlado del servicio. Este almacenamiento operativo no utiliza el esquema de cifrado de las copias de seguridad: Backblaze administra las claves de cifrado en reposo. Los adjuntos solo se entregan a usuarios autenticados y autorizados de la Clínica, sin enlaces públicos.')
    draft = draft.replace('contados desde que recibimos la solicitud completa', 'contados desde que recibimos la solicitud')
    draft = draft.replace('se conservarán 180 días una vez\n      habilitada esa función;', 'estarán disponibles durante 180 días desde su almacenamiento operativo, una vez\n      habilitada esa función, con el proceso de eliminación descrito en la sección 3.5;')
    assert draft != original and '22 de octubre de 2026' in draft
    (TARGET / 'aviso-de-privacidad.astro').write_text(draft, encoding='utf-8', newline='\n')
    (TARGET / 'aviso-de-privacidad.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), draft.splitlines(True),
        fromfile='a/frontend/src/pages/aviso-de-privacidad.astro',
        tofile='b/frontend/src/pages/aviso-de-privacidad.astro')), encoding='utf-8', newline='\n')
    sources = []
    private = OUT / 'runtime/legal-sources'
    private.mkdir(parents=True, exist_ok=True)
    for name, url in [
        ('public-notice.html', 'https://www.saaslyvet.com/aviso-de-privacidad/'),
        ('backblaze-dpa.html', 'https://www.backblaze.com/company/policy/dpa-for-eea-eu-residents'),
        ('backblaze-lifecycle.html', 'https://www.backblaze.com/docs/en/cloud-storage-lifecycle-rules'),
        ('lfpdppp.pdf', 'https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf')]:
        req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'SaaslyVet-legal-review/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                content = response.read()
                info = dict(url=url, retrieved_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            http_status=response.status, sha256=hashlib.sha256(content).hexdigest(), bytes=len(content),
                            etag=response.headers.get('ETag'), last_modified=response.headers.get('Last-Modified'))
        except Exception as exc:
            sources.append(dict(url=url, state='DIRECT_RETRIEVAL_UNAVAILABLE', error_type=type(exc).__name__,
                                fallback='Official source consulted through web tool; live publication date unverified'))
            continue
        (private / name).write_bytes(content)
        if name == 'public-notice.html':
            html = content.decode('utf-8')
            plain = re.sub('<[^>]+>', ' ', html)
            info['observed_dates'] = sorted(set(re.findall(r'\d{1,2} de \w+ de 2026', plain)))
            info['has_180_days'] = bool(re.search(r'180\s+d[ií]as', plain))
            info['has_whatsapp'] = 'WhatsApp' in plain
        sources.append(info)
    result = dict(state='DRAFT_FOR_REVIEW', source_file=str(SOURCE),
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        draft_sha256=hashlib.sha256((TARGET/'aviso-de-privacidad.astro').read_bytes()).hexdigest(),
        proposed_version='2026-10-22', actual_release_date_must_match_publication=True,
        published=False, dpa_accepted=False, legal_document_promoted=False, sources=sources)
    (TARGET / 'preparation.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
