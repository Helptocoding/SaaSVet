"""Record human decisions; prepare an unpublished, versioned privacy draft."""
import difflib
import hashlib
import json
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
receipt = out / 'preparation.json'
assert not receipt.exists(), 'Do not overwrite evidence'

def append_once(path, marker, text):
    p = root / path
    value = p.read_text(encoding='utf-8')
    if marker not in value:
        p.write_text(value.rstrip()+'\n'+text+'\n', encoding='utf-8')

append_once('.gitignore', '/docs/evals/inbox-media-policy-2026-10-23/runtime/',
    '\n# Retention policy evidence: private local runtime and independent deny ledger\n/docs/evals/inbox-media-policy-2026-10-23/runtime/\n**/inbox-media-revocations/')
append_once('backend/.dockerignore', 'inbox-media-revocations/', '\n**/inbox-media-revocations/')
append_once('scripts/crontab.example', '--alerts-only', '''
# Inbox: observar/escalar sin I/O binario ni reintentos de purga, mismo cron.
# Umbral 24h, detección en el siguiente tick (<=15 min si cron funciona).
# Responsable/canal pendientes NO BLOQUEANTES: decisión del usuario 23-10-2026.
*/15 * * * *  cd $COMPOSE_DIR && docker compose -f $COMPOSE_FILE --env-file $ENV_FILE run --rm backend python manage.py maintain_inbox_media --alerts-only --batch 500 --max-batches 1 >> /var/log/vet-inbox-media.log 2>&1''')

# The existing B2 test must model the NEW post-delete listing rather than return
# the pre-delete object forever. The behavior test remains the same.
p = root / 'backend/apps/channels/tests/test_media_pipeline.py'
text = p.read_text(encoding='utf-8')
before = "client.get_paginator.return_value.paginate.return_value = [\n            dict(Versions=[dict(Key=key, VersionId='v1')"
after = "client.get_paginator.return_value.paginate.side_effect = [[\n            dict(Versions=[dict(Key=key, VersionId='v1')"
if before in text:
    text = text.replace(before, after, 1)
    text = text.replace("Versions=[dict(Key=key, VersionId='v2')])]", "Versions=[dict(Key=key, VersionId='v2')])], []]", 1)
    p.write_text(text, encoding='utf-8')

source = Path('C:/Users/LAP/.codex/attachments/a5720a19-dbbe-4e12-9d6f-a6ee8b5f11a7/Texto pegado.txt')
raw = source.read_bytes()
policy = root / 'docs/decisions/2026-10-22-inbox-media-retention-policy.md'
assert not policy.exists()
policy.write_text(raw.decode('utf-8-sig').replace('\r\n', '\n')+'''

---
Registro de incorporación al proyecto: **23-10-2026**, por instrucción directa
del usuario que declara que estas son sus decisiones. Se conservan arriba los
campos pendientes del documento original: no se inventan nombre, firma ni
aceptación contractual. La decisión de parámetros queda registrada como definida;
su cumplimiento operativo sigue pendiente. Excepción posterior: responsable y
canal de alertas pendientes operativos **no bloqueantes**, según la decisión del
23-10 enlazada abajo.

[Excepción operativa de alertas](2026-10-23-inbox-media-alert-ops-deferred.md).
''', encoding='utf-8')
exception = root / 'docs/decisions/2026-10-23-inbox-media-alert-ops-deferred.md'
assert not exception.exists()
exception.write_text('''# Responsable y canal de alertas de purga: pendiente no bloqueante

Fecha: **23-10-2026**. Estado: **ACCEPTED_DEBT_NON_BLOCKING**.

El usuario respondió a la consulta de quién atenderá las alertas y por qué canal:
«dejalo como pendiente operativo y que no es bloqueante».

Se aplaza la designación del responsable y canal; no bloquea el cierre del plan
por sí sola. La aplicación conserva incidentes, umbrales, recibos y la ausencia
de configuración visible. No se registra entrega o atención humana como PASS,
ni se inventan destinatarios, claves o envíos. El transporte existente de ops
queda preparado y solo podrá usarse con configuración válida.

Esta excepción no elimina los plazos de expiración/purga, no cierra incidentes
por superar siete días, no acepta contratos ni publica el aviso. La activación
de WhatsApp continúa sin autorización en la decisión de política adjunta.
''', encoding='utf-8')

draft_dir = root / 'docs/compliance/inbox-privacy-review-2026-10-23'
draft_dir.mkdir(exist_ok=False)
old = (root / 'docs/compliance/inbox-privacy-review-2026-10-22/aviso-de-privacidad.astro').read_text(encoding='utf-8')
needle = 'días</strong> desde que se guardan en el almacenamiento operativo. Al vencer ese plazo dejan de estar disponibles y se inicia su eliminación física mediante el proceso periódico de mantenimiento. Si ocurre una incidencia de borrado, el acceso permanece bloqueado mientras se resuelve; el texto del mensaje, su caption y los metadatos'
replacement = '''días naturales</strong> desde que se completa correctamente su almacenamiento operativo.
      Al vencer ese plazo dejan de estar disponibles para consulta y descarga. Su purga operativa,
      incluidas las versiones y marcadores de borrado pertinentes, debe completarse y verificarse
      dentro de los <strong>siete días naturales siguientes</strong>. Si ocurre una incidencia,
      el acceso permanece bloqueado durante los reintentos y la atención del incidente. Este
      límite corresponde al proceso gestionado por SaaslyVet; no afirma el momento exacto de
      eliminación de todos los bloques físicos internos del proveedor. Las copias descargadas
      por la Clínica, los originales que conserve Meta y los respaldos independientes se rigen
      por sus propios controles; una restauración no debe restablecer accesos expirados o revocados.
      El texto del mensaje, su caption y los metadatos'''
assert needle in old
draft = old.replace(needle, replacement).replace('2026-10-22', '2026-10-23').replace('22 de octubre de 2026', '23 de octubre de 2026')
target = draft_dir / 'aviso-de-privacidad.astro'
target.write_text(draft, encoding='utf-8')
original = Path('C:/Users/LAP/Desktop/LandingSaaS/frontend/src/pages/aviso-de-privacidad.astro')
original_raw = original.read_bytes()
assert hashlib.sha256(original_raw).hexdigest() == 'c0e1db8fd05da8f63b9ac181dbc7c6df085631d6080e2437bb437357f0e7c236'
(draft_dir / 'aviso-de-privacidad.patch').write_text(''.join(difflib.unified_diff(
    original_raw.decode('utf-8-sig').splitlines(True), draft.splitlines(True),
    fromfile='a/frontend/src/pages/aviso-de-privacidad.astro', tofile='b/frontend/src/pages/aviso-de-privacidad.astro')), encoding='utf-8')
(draft_dir / 'README.md').write_text('''# Aviso preparado según la política del 22 de octubre

Actualización de revisión: **23-10-2026**. **NO PUBLICADO**.

El archivo completo y su parche incorporan 180 días naturales desde persistencia,
bloqueo al vencer, máximo operativo de siete días y verificación de versiones,
incidentes, límites respecto a bloques físicos y copias independientes, y restore
sin reactivación. La sección permanece condicional a la futura habilitación.
No presenta como probada la operación real ni promete entrega de alertas.

La fecha del borrador es candidata: usar la fecha efectiva al publicar. Aplicar
el parche solo después de revisión final; verificar el sitio público por HTTPS,
y después promover esa versión con seed_legal_documents y probar reaceptación.
No se modificó la landing original, no se publicó ni se ejecutó el seed.

El expediente del 22 de octubre conserva ficha DPA, fuentes y build anteriores.
La región real de B2 y el instrumento contractual siguen pendientes.
''', encoding='utf-8')

guide = root / 'docs/CIERRE-INBOX-WHATSAPP.md'
content = guide.read_text(encoding='utf-8')
section = '''## Actualización vigente del 23 de octubre: política recibida

El usuario definió [la política de retención y purga](decisions/2026-10-22-inbox-media-retention-policy.md):
180 días naturales desde persistencia, bloqueo al vencer, purga operativa verificada
en hasta siete días, reintentos diarios, alerta al primer fallo y escalamiento
tras 24 horas. Superar siete días abre incidente de cumplimiento; no se borra su
evidencia al recuperarse. Esta definición cierra la decisión de parámetros,
sin acreditar operación real ni firma/contrato.

Responsable y canal de alertas son [pendiente operativo no bloqueante](decisions/2026-10-23-inbox-media-alert-ops-deferred.md)
por instrucción posterior del usuario. B9 BASE conserva su excepción no bloqueante.
B2 real y Meta/recepción continúan aplazados; aviso, contrato, aceptación legal y
activación no se dan por realizados. El código y pruebas locales de esta entrega
se registran en [el expediente nuevo](evals/inbox-media-policy-2026-10-23/README.md).
El nuevo [aviso preparado](compliance/inbox-privacy-review-2026-10-23/README.md)
sustituye al borrador anterior para revisión; ninguno se ha publicado.

'''
assert '## Actualización vigente del 23 de octubre' not in content
content = content.replace('Fecha: **2026-10-22**.', 'Fecha: **2026-10-23**.', 1)
content = content.replace('## 0. Actualización autorizada del 22 de octubre', section+'## 0. Actualización autorizada del 22 de octubre', 1)
content = content.replace('Los seis cierres siguen pendientes\nde su evidencia final;', 'En ese corte los seis cierres seguían pendientes\nde su evidencia final;')
guide.write_text(content, encoding='utf-8')

checklist = root / 'docs/compliance/cierre-b2-whatsapp-2026-10-22.md'
content = checklist.read_text(encoding='utf-8')
content = content.replace('Fecha local: **2026-10-22**. Cierres completos: **0 de 6**.',
    'Actualización local: **2026-10-23**. Decisión de parámetros definida: **1 de 6**.\nLos otros cinco puntos conservan su evidencia final pendiente.')
content = content.replace('## Lista de cierre 0/6', '## Lista de cierre 1/6 (decisión de política definida; operación no certificada)')
start = content.index('- [ ] **1. Decisión jurídica — aprobar la política de retención.**')
end = content.index('- [ ] **2. Validación técnica', start)
content = content[:start]+'''- [x] **1. Decisión de producto/operación — parámetros de retención definidos.**
  [Documento del usuario incorporado](../decisions/2026-10-22-inbox-media-retention-policy.md):
  180 días naturales desde persistencia, purga operativa verificada en siete días,
  reintentos diarios, primer fallo con alerta, escalamiento a las 24 horas y restore
  sin reactivación. Esto cierra la elección de parámetros; firma nominal, revisión
  jurídica y cumplimiento operativo no se inventan y siguen registrados pendientes.
  Responsable/canal de avisos: [deuda no bloqueante aceptada](../decisions/2026-10-23-inbox-media-alert-ops-deferred.md).
'''+content[end:]
intro = '''
## Cambios posteriores del 23 de octubre

El expediente de esta entrega añade verificación posterior al borrado, incidentes
persistentes, umbrales de 24h/7d, resultado no exitoso ante purgas fallidas o
incidentes de cumplimiento abiertos, y ledger de revocaciones independiente del
dump. Los reintentos se programan con 23h de backoff para quedar elegibles al
siguiente cron diario. Los intentos fallidos consumen lote y no ocultan el resto.
Se prepara observación de umbrales cada 15min con el mismo cron: registra el
umbral al primer tick posterior, no garantiza entrega exactamente a las 24h.

Responsable y canal pendientes son **no bloqueantes por decisión expresa del
usuario**. No se exigen para cerrar el plan como deuda aceptada; la entrega y
atención no se convierten en PASS. Se conserva el gate por incumplimiento real de
purga. La tabla histórica inferior describe la inspección del 22; los cambios y
pruebas posteriores se detallan en el expediente nuevo y runbook vigente.

El [aviso de revisión vigente](inbox-privacy-review-2026-10-23/README.md) incorpora
el máximo operativo aprobado; el build anterior de 18 páginas no valida ese
nuevo texto. Publicación HTTPS, seed y reaceptación siguen pendientes.

'''
content = content.replace('## Garantías técnicas solicitadas', intro+'## Garantías técnicas solicitadas (corte histórico 22-10)')
checklist.write_text(content, encoding='utf-8')

result = dict(source_policy_sha256=hashlib.sha256(raw).hexdigest(), policy_document=str(policy.relative_to(root)),
    original_landing_sha256=hashlib.sha256(original_raw).hexdigest(), draft_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    landing_modified=False, published=False, legal_seed_executed=False,
    policy_parameters_defined=True, ops_recipient_channel='ACCEPTED_DEBT_NON_BLOCKING')
receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
