"""Publish the local closure only after composing a completely passing result."""
import json
from pathlib import Path
import subprocess
import sys

out = Path(__file__).resolve().parent
root = out.parents[2]
result = subprocess.run(['rtk', 'proxy', sys.executable, '-X', 'utf8', str(out / 'verify_evidence.py')],
    capture_output=True, text=True, encoding='utf-8', check=True)
stats = json.loads(result.stdout)
assert stats['status'] == 'PASS', stats
counts = f"{stats['backend_unique']} pruebas PostgreSQL y {stats['frontend_unique']} frontend únicas PASS"


def replace_once(text, old, new):
    assert text.count(old) == 1, old[:120]
    return text.replace(old, new, 1)


def update(name, change):
    path = root / name
    old = path.read_text(encoding='utf-8')
    new = change(old)
    assert old != new
    path.write_text(new, encoding='utf-8')
    print(name)


def guide(text):
    line = next(line for line in text.splitlines() if line.startswith('| RPL-01..07, MED-01..05 |'))
    text = replace_once(text, line, '| RPL-01..07, MED-01..05 | Replies y media entrante completos, permisos, expiración y estados de error | **Fase 3 obligatoria implementada y verificada localmente (22-10).** RPL-01..06 conservadas; RPL-07 conecta `context.message_id` tras admisión B4 y verifica su matriz. MED-01..05: M4, captura atómica, storage privado local/B2, worker acotado/reintentos, purga/reconciliación, proxy por clínica y previews/controles. ' + counts + '; build, lint, drift y Chromium escritorio/móvil PASS con servicios simulados. [Evidencia fase 3](evals/inbox-phase3-2026-10-22/README.md). M2/M3/M4 sin aplicar a bases habitual/preview; procesamiento apagado por defecto. Gates B2/privacidad/lifecycle y recepción/Meta reales pendientes; MED-06 opcional. |')
    text = replace_once(text,
        '**Pendiente de implementación confirmado:** `sender.dispatch_claim` y\n`MetaWhatsAppProvider.send_text` aún despachan solo texto. Añadir el contexto de\ncita al proveedor antes de acreditar replies end-to-end (prerrequisito de RPL-07),\nconservando la admisión/uncertainty B4. Esto es distinto de la validación Meta real\npospuesta; no se presenta como implementado ni aprobado por tener la FK/API.',
        '**Prerrequisito resuelto localmente (22-10, RPL-07):** sender y adaptador\nMeta incorporan `context.message_id` scoped con wamid utilizable, después de la\nadmisión B4. Sin evidencia externa se conserva la cita interna; resultados\nambiguos siguen uncertain sin resend. La validación Meta real continúa pospuesta.')
    text = replace_once(text,
        '**Siguiente tarea: WA-RPL-07**, conectar el contexto de cita nativo al proveedor y\nacreditar la matriz final de edge cases. Recepción/Meta reales siguen pospuestos.',
        '**Fase 3 obligatoria completada localmente (22-10): RPL-07 y MED-01..05.**\n' + counts + ', build, lint, drift y Chromium escritorio/móvil\nPASS. [Expediente compuesto](evals/inbox-phase3-2026-10-22/README.md) y\n[operación media](runbooks/inbox-media.md). Sin aplicar M2/M3/M4 a bases\nhabitual/preview, despliegue ni activación. Recepción/Meta reales y gates de\nprivacidad/B2/lifecycle pendientes; MED-06 opcional. Fase 4 ya cubierta por\nPERF-03 con SSE NO-GO; fase 5 requiere evidencia y priorización, no se inicia aquí.')
    return text


def plan(text):
    text = replace_once(text, 'Estado de partida (verificado): el webhook guarda solo',
        'Estado anterior a MED (histórico): el webhook guardaba solo')
    anchor = '9. Webhook duplicado del inbound-reply → sin duplicar relación.'
    text = replace_once(text, anchor, anchor + '\n\n**Acceptance local (22-10)**: [x] Contexto nativo tras admisión y matriz\ncompleta, conservando guards B4 y evidencias RPL-01..06. ' + counts + '.\n[Evidencia fase 3](evals/inbox-phase3-2026-10-22/README.md). Meta real aplazada.')
    text = replace_once(text, '**Acceptance**: [ ] ADR p60 mergeado. [ ] Migración additive aplicable.',
        '**Acceptance local**: [x] Storage conforme al ADR p60 aceptado. [x] M4\naditiva generada y aplicada en PostgreSQL temporal. No aplicada a base habitual;\nprivacidad/B2/lifecycle reales pendientes. [Evidencia](evals/inbox-phase3-2026-10-22/README.md).')
    text = replace_once(text, '**Acceptance**: [ ] Un audio recibido hoy YA no es irrecuperable: existe fila con provider_media_id pendiente.',
        '**Acceptance local**: [x] Los cinco tipos conservan referencia pending,\ncaption y raw completo; dedup y carreras verificadas. Sin HTTP en webhook.\n[Evidencia](evals/inbox-phase3-2026-10-22/README.md).')
    text = replace_once(text, '**Acceptance**: [ ] Binario persistido en B2 y checksum verificado; cero persistencia canónica en VPS; fallos visibles con estado explícito.',
        '**Acceptance local**: [x] Descarga/checksum, SDK B2 simulado, reintentos,\nleases, spool, purga de versiones y drift verificados. [ ] Persistencia y\nlifecycle en B2 real (gate previo a producción). Backend local solo dev/CI.\n[Evidencia](evals/inbox-phase3-2026-10-22/README.md).')
    text = replace_once(text, '**Acceptance**: [ ] Prueba manual de fuga cross-org falla; staff descarga su media correctamente.',
        '**Acceptance local**: [x] Matriz API 403/404/409/410/503 y streaming\nautenticado, sin lectura cross-org ni URL pública. [ ] Prueba con staff y\nproveedor reales. [Evidencia](evals/inbox-phase3-2026-10-22/README.md).')
    text = replace_once(text, '**Acceptance**: [ ] Cliente manda foto de una herida → recepción la VE en ≤ un ciclo de poll tras descargar el worker.',
        '**Acceptance local**: [x] Tipos/caption/previews, lightbox, carga manual\ny lifecycle de blobs verificados con Vitest y Chromium escritorio/móvil.\n[ ] Cliente real manda foto y recepción la ve tras el poll (validación pospuesta).\n[Evidencia](evals/inbox-phase3-2026-10-22/README.md).')
    text = replace_once(text, 'El siguiente pendiente del roadmap es WA-ASN-01; los demás pendientes y su evidencia están en la guía de cierre.',
        'Fase 3 obligatoria implementada y verificada localmente el 22-10 (RPL-07, MED-01..05); M2/M3/M4 sin aplicar a bases habitual/preview. MED-06 opcional y fase 5 siguen fuera de este cierre; gates reales y evidencia en la guía de cierre.')
    return text


def frontend(text):
    anchor = '### WhatsApp Inbox: citas y salto al original (WA-RPL-06 + WA-RPL-04)'
    section = '''### WhatsApp Inbox: media entrante privada (MED-01..05 / RPL-07, 22-10)

`Message.media` añade UUID, status, MIME, tamaño, filename, expires_at y dimensiones/
duración opcionales. No expone keys ni IDs de Meta. `getInboxMedia` usa el cliente
autenticado con responseType blob y AbortSignal. `useMediaUrl` comparte URLs por
usuario/clínica/UUID con refcount, abort y revoke; respuestas tardías no cambian
el hilo actual. Los deltas detectan cambios de media sin tocar el Message.

`MediaBubble` carga imagen/sticker al aproximarse al viewport, abre lightbox
nativo con Escape y retorno de foco, y conserva su blob durante la interacción.
Audio/video/documento e imágenes grandes requieren clic y muestran peso; sin
autoplay. Descarga documental por blob, caption una vez, y estados de recepción,
fallo, retry explícito y expiración 410 sin bucle. La lista usa tipo/filename para
archivos sin caption. No cambia composer ni autorización de envío.

''' + counts + ''' en evidencia compuesta; build, lint y Chromium
escritorio/móvil PASS. [Expediente](../evals/inbox-phase3-2026-10-22/README.md).
Native replies conectadas al proveedor tras admisión B4; Meta/recepción reales
siguen aplazados. M2/M3/M4 pendientes de aplicar a base habitual/preview y media
apagada por defecto; ver [runbook](../runbooks/inbox-media.md).

'''
    text = replace_once(text, anchor, section + anchor)
    text = replace_once(text, 'La cita nativa en el proveedor y la matriz final continúan en RPL-07; recepción/\nMeta reales siguen pospuestos. No se aplicaron M2/M3 ni cambios backend.',
        'Corte histórico RPL-06/04: sin cambios backend/M2/M3 en ese corte. RPL-07\ny MED se completaron después, según la sección anterior; Meta real sigue aplazada.')
    text = replace_once(text, 'cita. La validación definitiva sigue en la API de RPL-03. El payload nativo Meta\ntodavía requiere la conexión registrada como prerrequisito de RPL-07.',
        'cita. La validación definitiva sigue en la API de RPL-03. RPL-07 ya conecta\nel contexto nativo Meta, conservando los guards B4; falta validación real.')
    return text


def agent(text):
    first = text.splitlines()[0]
    return replace_once(text, first, first + '\n\n> **Inbox, fase 3 local — 22-10-2026:** RPL-07 y MED-01..05 implementadas;\n> ' + counts + '. M4 temporal, proxy por clínica y worker\n> privado con expiración a 180 días. [Evidencia](../evals/inbox-phase3-2026-10-22/README.md)\n> y [contrato/operación](../runbooks/inbox-media.md). Producción y gates reales\n> pendientes; no cambia el FAIL B9 ni habilita WRITE. Los cortes inferiores son históricos.')


def changelog(text):
    text = replace_once(text, '## 2026-10-22\n', '## 2026-10-22\n\n- Inbox, cierre local de fase 3: RPL-07 conecta citas nativas tras admisión B4;\n  MED-01..05 incorporan captura atómica, almacenamiento privado local/B2,\n  descarga durable, expiración/reconciliación, proxy por clínica y controles de\n  archivos/captions/previews. ' + counts + ', build, lint,\n  drift y Chromium escritorio/móvil PASS. M2/M3/M4 sin aplicar a bases habitual/\n  preview; banderas apagadas y gates reales pendientes. Evidencia:\n  `docs/evals/inbox-phase3-2026-10-22/README.md`. MED-06 saliente opcional.\n')
    return replace_once(text, '  Pendientes el contexto nativo del proveedor y la matriz final RPL-07.',
        '  El contexto nativo y la matriz RPL-07 se cerraron en el corte anterior de esta fecha; Meta real sigue pendiente.')


update('docs/CIERRE-INBOX-WHATSAPP.md', guide)
update('docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', plan)
update('docs/modules/frontend.md', frontend)
update('docs/modules/agent.md', agent)
update('CHANGELOG.md', changelog)
update('docs/decisions/2026-08-22-p60-whatsapp-inbox-decisions.md', lambda text: text + '''

## Implementación local de D-1/D-2 — 22-10-2026

MED-01..05 implementan MessageMedia (M4 aditiva), interfaz local/B2 mediante
boto3, claves opacas por clínica/UUID/claim, cifrado B2 AES256 y proxy autenticado
como único contrato. El worker existente incorpora descarga con spool acotado;
el job nocturno existente ejecuta purga de todas las versiones/markers, reintentos,
reconciliación y scavenger. Límites conservadores: imagen 5 MiB, sticker 500 KiB,
audio/video 16 MiB y documento 25 MiB. Retención inalterada: 180 días.

[Evidencia local](../evals/inbox-phase3-2026-10-22/README.md) y
[runbook](../runbooks/inbox-media.md). Procesamiento apagado por defecto, local
restringido a dev/CI y B2 bloqueado hasta aprobar gates. M2/M3/M4 no aplicadas a
bases habitual/preview. No acredita bucket/key/lifecycle/DPA/aviso/ARCO reales,
merge, despliegue, activación ni validación con recepción/Meta. P40, NO-GO SSE y
fronteras B4/B5 permanecen vigentes.
''')
update('docs/evals/inbox-phase3-2026-10-22/PLAN.md', lambda text: text.replace(
    '## Estado de implementación (en curso, todavía sin aceptación)',
    '## Estado final: implementación y validación local completadas') + '\n\nCierre: ' + counts + '. Ver README.md, summary.json y cases.json.\nLos puntos «falta» anteriores son el registro de preparación y quedan resueltos\nen el expediente final; los gates reales descritos siguen pendientes.\n')
