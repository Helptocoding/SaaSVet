# Checkpoint Inbox/WhatsApp y cambios acumulados — 23-10-2026

Commit solicitado por el usuario para guardar el estado actual del proyecto,
incluidos sus otros cambios. La autoría no se deduce a partir de Git; no se
consideran incorrectos ni se revierten los cambios adicionales.

Base: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`. Rama: `codex/e4-capacity-scheduling`.

Inventario inicial: **11,525 archivos**, unos **1.31 GB** sin comprimir;
más este informe y el inventario JSON. El volumen corresponde principalmente
a evidencias B9 acumuladas; Git puede deduplicar su contenido.

## Contenido conservado

| Área | Archivos iniciales |
|---|---:|
| root_or_tooling | 8 |
| backend | 69 |
| documentation | 21 |
| historical_b9_evidence | 10439 |
| frontend | 48 |
| inbox_evidence | 940 |

Incluye implementación, migraciones, tests, UI, documentación y evidencias
del Inbox; política 180 días / purga operativa de siete días, incidentes y
revocaciones independientes del dump. B9 BASE y responsable/canal de avisos
conservan sus decisiones de deuda no bloqueante. No implica activación,
publicación, despliegue, contratación ni validación real de B2/Meta/recepción.

## Cambios adicionales expresamente conservados

- `backend/apps/core/models.py` y sus pruebas de aislamiento.
- Pruebas de `backend/apps/notifications/` y regresiones del agente.
- `skills-lock.json`, `CHANGELOG.md`, dependencias y configuración actuales.
- Eliminaciones de `DEPLOY_VPS_PLAN.md` y `DEPLOY_VPS_STATUS.md`.
- Cambios ya staged y cambios posteriores en `.gitignore` y `index.test.jsx`:
  se guarda la versión actual completa solicitada por el usuario.

Las reglas nuevas de `.gitattributes` preservan bytes de evidencias recién
añadidas, sin reescribir los recibos ni atribuirles otra validación.

## Validación y límites

Los 53 archivos del último manifiesto sellado estaban intactos al inventariar.
Se conserva la evidencia previa de 49 pruebas únicas aprobadas, simulacro
local real pg_dump/pg_restore, migración 0018 local y build del aviso de
18 páginas. No se repitió B9 ni se presenta todo el checkpoint como probado
por esas 49 pruebas; los cambios adicionales conservan su estado actual.
La comprobación del índice/secretos del commit se registra en su mensaje.
Backups locales, credenciales, runtime y ledger privado siguen fuera de Git.

## Archivos de producto, configuración y documentación

El JSON adjunto contiene también todas las rutas de evidencias. Estados de
esta lista: estado Git observado antes de preparar el checkpoint.

| Estado inicial | Ruta |
|---|---|
| `M ` | `.gitattributes` |
| `MM` | `.gitignore` |
| ` M` | `CHANGELOG.md` |
| ` D` | `DEPLOY_VPS_PLAN.md` |
| ` D` | `DEPLOY_VPS_STATUS.md` |
| ` M` | `backend/.dockerignore` |
| ` M` | `backend/.env.example` |
| ` M` | `backend/Procfile` |
| ` M` | `backend/apps/agent/management/commands/run_agent_worker.py` |
| ` M` | `backend/apps/agent/models.py` |
| ` M` | `backend/apps/agent/sender.py` |
| ` M` | `backend/apps/agent/serializers.py` |
| ` M` | `backend/apps/agent/services.py` |
| `M ` | `backend/apps/agent/tests/test_contracts.py` |
| ` M` | `backend/apps/agent/tests/test_inbox_threads.py` |
| `M ` | `backend/apps/agent/tests/test_regression_f2.py` |
| `M ` | `backend/apps/agent/tests/test_regression_suite.py` |
| ` M` | `backend/apps/agent/urls.py` |
| ` M` | `backend/apps/agent/views.py` |
| ` M` | `backend/apps/channels/events.py` |
| ` M` | `backend/apps/channels/models.py` |
| ` M` | `backend/apps/channels/providers.py` |
| ` M` | `backend/apps/channels/tests/test_webhook.py` |
| ` M` | `backend/apps/channels/views.py` |
| ` M` | `backend/apps/core/models.py` |
| `M ` | `backend/apps/core/tests/test_tenant_scoping_audit.py` |
| `M ` | `backend/apps/notifications/tests/test_notifications.py` |
| ` M` | `backend/config/settings.py` |
| ` M` | `backend/requirements.lock` |
| ` M` | `backend/requirements.txt` |
| ` M` | `docs/compliance/arco.md` |
| ` M` | `docs/decisions/2026-08-22-p60-whatsapp-inbox-decisions.md` |
| ` M` | `docs/modules/agent.md` |
| ` M` | `docs/modules/frontend.md` |
| ` M` | `docs/plan-implementacion-whatsapp-inbox-2026-08-22.md` |
| ` M` | `docs/runbooks/RUNBOOK-RESTORE.md` |
| ` M` | `frontend/src/api/inbox.js` |
| ` M` | `frontend/src/api/inbox.test.js` |
| ` M` | `frontend/src/pages/inbox/inbox.module.css` |
| ` M` | `frontend/src/pages/inbox/index.jsx` |
| `MM` | `frontend/src/pages/inbox/index.test.jsx` |
| ` M` | `scripts/crontab.example` |
| ` M` | `skills-lock.json` |
| `??` | `.gitleaksignore` |
| `??` | `backend/apps/agent/inbox_assignment.py` |
| `??` | `backend/apps/agent/inbox_context.py` |
| `??` | `backend/apps/agent/inbox_media.py` |
| `??` | `backend/apps/agent/inbox_read.py` |
| `??` | `backend/apps/agent/inbox_retry.py` |
| `??` | `backend/apps/agent/inbox_sync.py` |
| `??` | `backend/apps/agent/migrations/0029_inbox_read_state.py` |
| `??` | `backend/apps/agent/tests/fixtures/inbox_threads_perf01.json` |
| `??` | `backend/apps/agent/tests/test_inbox_assignment.py` |
| `??` | `backend/apps/agent/tests/test_inbox_context.py` |
| `??` | `backend/apps/agent/tests/test_inbox_filters.py` |
| `??` | `backend/apps/agent/tests/test_inbox_media.py` |
| `??` | `backend/apps/agent/tests/test_inbox_message_author.py` |
| `??` | `backend/apps/agent/tests/test_inbox_read_projection.py` |
| `??` | `backend/apps/agent/tests/test_inbox_read_state.py` |
| `??` | `backend/apps/agent/tests/test_inbox_replies.py` |
| `??` | `backend/apps/agent/tests/test_inbox_retry.py` |
| `??` | `backend/apps/agent/tests/test_inbox_search.py` |
| `??` | `backend/apps/agent/tests/test_inbox_session_window.py` |
| `??` | `backend/apps/agent/tests/test_inbox_sync.py` |
| `??` | `backend/apps/agent/tests/test_inbox_thread_around.py` |
| `??` | `backend/apps/agent/tests/test_inbox_thread_pagination.py` |
| `??` | `backend/apps/agent/tests/test_inbox_thread_performance.py` |
| `??` | `backend/apps/channels/management/commands/inbox_media_ops.py` |
| `??` | `backend/apps/channels/management/commands/maintain_inbox_media.py` |
| `??` | `backend/apps/channels/media_clock.py` |
| `??` | `backend/apps/channels/media_incidents.py` |
| `??` | `backend/apps/channels/media_ingest.py` |
| `??` | `backend/apps/channels/media_policy.py` |
| `??` | `backend/apps/channels/media_revocations.py` |
| `??` | `backend/apps/channels/media_storage.py` |
| `??` | `backend/apps/channels/media_transfer.py` |
| `??` | `backend/apps/channels/media_worker.py` |
| `??` | `backend/apps/channels/migrations/0016_message_reply_to.py` |
| `??` | `backend/apps/channels/migrations/0017_message_media.py` |
| `??` | `backend/apps/channels/migrations/0018_media_retention_policy.py` |
| `??` | `backend/apps/channels/replies.py` |
| `??` | `backend/apps/channels/tests/test_media_integration.py` |
| `??` | `backend/apps/channels/tests/test_media_pipeline.py` |
| `??` | `backend/apps/channels/tests/test_media_restore_drill.py` |
| `??` | `backend/apps/channels/tests/test_media_retention_policy.py` |
| `??` | `backend/apps/channels/tests/test_replies_migration.py` |
| `??` | `backend/apps/channels/tests/test_replies_model.py` |
| `??` | `backend/apps/channels/tests/test_replies_webhook.py` |
| `??` | `docs/CIERRE-INBOX-WHATSAPP.md` |
| `??` | `docs/compliance/cierre-b2-whatsapp-2026-10-22.md` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-22/README.md` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-22/aviso-de-privacidad.astro` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-22/aviso-de-privacidad.patch` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-22/b2-preparacion.md` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-22/preparation.json` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-23/README.md` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-23/aviso-de-privacidad.astro` |
| `??` | `docs/compliance/inbox-privacy-review-2026-10-23/aviso-de-privacidad.patch` |
| `??` | `docs/decisions/2026-10-21-p60-perf03-cursors.md` |
| `??` | `docs/decisions/2026-10-22-b9-base-latency-accepted-debt.md` |
| `??` | `docs/decisions/2026-10-22-inbox-media-retention-policy.md` |
| `??` | `docs/decisions/2026-10-23-inbox-media-alert-ops-deferred.md` |
| `??` | `docs/runbooks/inbox-media.md` |
| `??` | `frontend/src/hooks/usePollingWhenVisible.js` |
| `??` | `frontend/src/hooks/usePollingWhenVisible.test.jsx` |
| `??` | `frontend/src/pages/inbox/ContactVerificationBadge.jsx` |
| `??` | `frontend/src/pages/inbox/ContactVerificationBadge.test.jsx` |
| `??` | `frontend/src/pages/inbox/FailedMessageRetry.jsx` |
| `??` | `frontend/src/pages/inbox/InboxLoadState.jsx` |
| `??` | `frontend/src/pages/inbox/MediaBubble.jsx` |
| `??` | `frontend/src/pages/inbox/MediaBubble.test.jsx` |
| `??` | `frontend/src/pages/inbox/MessageBody.jsx` |
| `??` | `frontend/src/pages/inbox/ReplyQuote.jsx` |
| `??` | `frontend/src/pages/inbox/ReplyQuote.test.jsx` |
| `??` | `frontend/src/pages/inbox/SessionWindowNotice.jsx` |
| `??` | `frontend/src/pages/inbox/ThreadAssignment.jsx` |
| `??` | `frontend/src/pages/inbox/ThreadAssignment.test.jsx` |
| `??` | `frontend/src/pages/inbox/ThreadContextPanel.jsx` |
| `??` | `frontend/src/pages/inbox/ThreadViewport.jsx` |
| `??` | `frontend/src/pages/inbox/ThreadViewport.test.jsx` |
| `??` | `frontend/src/pages/inbox/inboxSync.js` |
| `??` | `frontend/src/pages/inbox/inboxSync.test.js` |
| `??` | `frontend/src/pages/inbox/index.assignment.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.context.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.filters.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.jump.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.replies.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.retry.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.search.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.sync.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.unread.test.jsx` |
| `??` | `frontend/src/pages/inbox/index.window.test.jsx` |
| `??` | `frontend/src/pages/inbox/messageGroups.js` |
| `??` | `frontend/src/pages/inbox/messageGroups.test.js` |
| `??` | `frontend/src/pages/inbox/messageText.js` |
| `??` | `frontend/src/pages/inbox/messageText.test.js` |
| `??` | `frontend/src/pages/inbox/sessionWindow.js` |
| `??` | `frontend/src/pages/inbox/threadMessages.js` |
| `??` | `frontend/src/pages/inbox/useInboxTitle.js` |
| `??` | `frontend/src/pages/inbox/useInboxTitle.test.jsx` |
| `??` | `frontend/src/pages/inbox/useMediaUrl.js` |
| `??` | `frontend/src/pages/inbox/useThreadHistory.js` |
| `??` | `frontend/src/pages/inbox/useThreadHistory.jump.test.jsx` |
| `??` | `frontend/src/pages/inbox/useThreadHistory.test.jsx` |
| `??` | `frontend/src/pages/inbox/useThreadRead.js` |
| `??` | `frontend/src/pages/inbox/useThreadRead.test.jsx` |
