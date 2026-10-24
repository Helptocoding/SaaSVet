"""Update current checkpoints after local migration/build; preserve older cuts."""
import json
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
assert json.loads((out/'migration-local.json').read_text())['state']=='PASS'
assert json.loads((out/'landing-build.json').read_text())['state']=='PASS'
p = root/'docs/compliance/cierre-b2-whatsapp-2026-10-22.md'
text = p.read_text(encoding='utf-8')
start = text.index('- [ ] **2. Validación técnica')
end = text.index('- [ ] **3. Publicación — sincronizar', start)
text = text[:start]+'''- [ ] **2. Validación técnica — almacenamiento, autorización y eliminación.**
  Evidencia de fase 3 conservada; los controles nuevos se registran en
  [el expediente de política](../evals/inbox-media-policy-2026-10-23/README.md).
  La comparación de 16 hashes correspondía al corte del 22: parte del código
  ahora cambió de forma autorizada para cumplir esta decisión. 0018 ya aplicada
  a desarrollo local con respaldo. Falta proveedor real, capacidad/cron, custodia
  del ledger y restore con inventario de objetos/versiones del servicio real.
  El simulacro local no sustituye esas pruebas ni reabre tráfico.
- [ ] **3. Publicación — revisar y publicar el aviso.**
  [Aviso completo y parche vigentes](inbox-privacy-review-2026-10-23/README.md):
  180 días y máximo operativo verificado de siete días, con límites de copias.
  **Build íntegro de revisión PASS, 18 páginas**, en
  [landing-build.json](../evals/inbox-media-policy-2026-10-23/landing-build.json).
  Original de la landing intacto. Faltan revisión final, fecha efectiva, release
  y comprobación del contenido público por HTTPS.
'''+text[end:]
text = text.replace('Confirmar B2, Meta/recepción, contratos/aviso, responsables de mantenimiento,\n  alertas, restauración y demás requisitos aplicables.',
    'Confirmar B2, Meta/recepción, contratos/aviso, mantenimiento,\n  restauración y demás requisitos aplicables. Responsable/canal de avisos quedan\n  como deuda no bloqueante aceptada; no se exigen como gate por sí solos.')
p.write_text(text, encoding='utf-8')
p = root/'docs/CIERRE-INBOX-WHATSAPP.md'
text = p.read_text(encoding='utf-8')
needle = 'El nuevo [aviso preparado](compliance/inbox-privacy-review-2026-10-23/README.md)'
text = text.replace(needle, '''La migración aditiva **channels.0018** ya está aplicada en desarrollo local,
con dump privado verificado y conteos conservados; preview/producción sin tocar.
Django check y ausencia de drift: PASS. El build del aviso actualizado también
es **PASS en 18 páginas** en la copia de revisión.
El nuevo [aviso preparado](compliance/inbox-privacy-review-2026-10-23/README.md)''',1)
p.write_text(text,encoding='utf-8')
p = root/'docs/runbooks/inbox-media.md'
text = p.read_text(encoding='utf-8')
text = text.replace('Requiere migración `channels.0018_media_retention_policy`. `MediaPurgeIncident`',
    'Migración `channels.0018_media_retention_policy` aplicada a desarrollo local\ncon respaldo verificado el 23-10; preview/producción pendientes de release.\n`MediaPurgeIncident`')
text = text.replace('sale con error ante fallos de la ejecución o incidentes de cumplimiento abiertos.',
    'sale con error ante fallos de la ejecución, purgas sin resolver, incidentes de\ncumplimiento abiertos o backlog elegible restante al agotar lotes. `--alerts-only`\nno considera capacidad de purga porque deliberadamente no borra objetos.')
text = text.replace('rtk proxy python manage.py inbox_media_ops status\n',
    'rtk proxy python manage.py inbox_media_ops status --organization 1 --limit 100\n',1)
text = text.replace('Rollback: apagar procesamiento detiene nuevas descargas/jobs, pero no borra',
    'Rollback: para bloquear acceso y nuevas descargas manteniendo la purga, usar\n`INBOX_MEDIA_ACCESS_HOLD=True` y conservar el mantenimiento habilitado. Apagar\nprocesamiento detiene también sus jobs, pero no borra')
p.write_text(text,encoding='utf-8')
print('Current checkpoints synchronized without closing real-provider gates')
