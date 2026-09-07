# Centro de notificaciones

Contrato del dominio. Fuente: `docs/auditoria-centro-notificaciones-2026-09-06.md` (Rev.5),
plan `docs/plan-implementacion-centro-notificaciones-2026-09-06.md`.

## Principio

- Dashboard = estado actual. Toast (Sonner) = feedback de mi acción. Notificación = novedad/evento que merece conocimiento.
- Notification refleja eventos del dominio, nunca posee sus estados.

## Tipos P0

| ID | Naturaleza | Persistencia | Identidad | Destinatarios |
|---|---|---|---|---|
| `appointment_upcoming` | CONDITION | derivada | cita + `start_iso` UTC | asignado o `appointment.list` |
| `appointment_delayed` | CONDITION | derivada | cita + `start_iso` UTC | mismo |
| `stock_low_entered` | EVENT | Notification | `stock_low:{product}:{movement}` | capacidad `inventory.view` |
| `stock_out` | EVENT | Notification | `stock_out:{product}:{movement}` | capacidad `inventory.view` |
| `cash_difference` | EVENT | Notification | `cashsession:{public_id}` | capacidad `cashsession.close` |

Ventanas beta (solo pruebas, en `notifications/policies.py`): upcoming 15m, delayed 20m,
caja `abs(difference) >= $50`.

## Reglas binding

- Exclusividad stock: `prev>0 and new==0 → out`; `prev>min and new<=min and new>0 → low`; resto ninguno.
- Receipts dual: persistida crea `Receipt(seen_at=NULL)` por destinatario; derivada no crea
  receipts en el feed (ausencia = unseen; `POST seen` crea receipt sparse).
- INV-N1: `Receipt.notification != NULL ⇒ key == Notification.dedup_key`.
- Escritura explícita en writers (`apply_stock_movement`, `close_cash_session`) + `on_commit`
  best-effort: nunca falla la operación de dominio; pérdida ante crash aceptada (sin Outbox).
- Tiempo: comparaciones aware UTC vs UTC; tz de org solo presentación.
- API MVP: `GET v1/notifications/feed/?limit=20`, `POST v1/notifications/:key/seen/`,
  `POST v1/notifications/seen-all/` (todo lo aplicable). CTA mapeado en frontend
  (`notificationActions.js`); DB guarda `type + entity + payload`, nunca `href`.
- Permisos: `notification.list/retrieve/seen`. Retención: `prune_notifications` mensual.
