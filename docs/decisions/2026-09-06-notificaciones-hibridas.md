# ADR — Centro de notificaciones híbrido (Modelo B + receipts server-side)

Fecha: 2026-09-06. Estado: aceptada (Fase 0).

## Decisión

Arquitectura híbrida: `Notification` (evento de la organización) + `NotificationReceipt`
(`user + seen_at`, server-side) + builders temporales derivados en `GET feed/`.
Sin Celery/Beat, sin WebSocket/SSE, sin localStorage semántico.

## Contexto

Polling existente (dashboard 30s, inbox 20s/10s), cron externo vía host crontab,
Gunicorn sync (SSE no-go), RBAC híbrido por capacidad, writers autorizados en `services.py`.

## Alternativas descartadas

- Notificaciones solo derivadas: sin historial ni `seen` multi-dispositivo.
- Fan-out `Notification` por usuario: N filas por evento, lectura pegada al evento.
- `post_save` para crear: side effects implícitos incompatibles con idempotencia/`CommandReceipt`.
- Celery/WS en beta: sobrearquitectura.

## Consecuencias

- `INV-N1`, receipts dual (persistida eagar/derivada sparse), clases CONDITION/EVENT.
- `on_commit` best-effort: el dominio precede; Dashboard conserva la verdad operacional.
- Thresholds centralizados en `notifications/policies.py` (valores beta = pruebas).
- Retención mensual vía `prune_notifications`.
