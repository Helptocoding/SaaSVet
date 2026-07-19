# ADR p52 — Idempotencia en creación de citas (A2-1)

**Fecha**: 2026-07-19
**Estado**: ACEPTADO (implementado en É-F2 PR-14)
**Contexto de producto**: prerrequisito de la escritura de agenda del agente WhatsApp (`docs/whatsapp-agent-epics.md` É-F2), con beneficio propio para el frontend actual.

---

## Contexto

El agente conversacional (É-F2) agenda citas invocando `POST /api/appointments/`
y `POST /api/appointments/create-with-patient/` vía loopback. Un timeout del
Tool Executor que dispara un reintento — o un doble-click del frontend actual —
crearía **dos citas idénticas** (R5/R6 del doc de arquitectura). Hasta hoy el
único dedup de citas era la ventana de 10 s del walk-in (ADR p12), que no cubre
la creación normal.

El proyecto ya resolvió este problema en su dominio más crítico: `Payment`
(`unique(organization, idempotency_key)`, ADR p27). A2-1 replica ese patrón
probado en `appointments`.

## Decisión

`POST /api/appointments/` y `POST /api/appointments/create-with-patient/`
aceptan un header **`X-Idempotency-Key` opcional**:

- **`Appointment.idempotency_key`** `CharField(max_length=64, null=True)` con
  `UniqueConstraint(fields=['organization', 'idempotency_key'],
  condition=Q(idempotency_key__isnull=False))`. Múltiples NULL permitidos →
  las creaciones sin key mantienen el comportamiento actual intacto.
- **Replay**: si ya existe una cita con esa `(org, key)`, el endpoint devuelve
  la **original** con `200 OK` (no crea otra, no error).
- **Carrera**: dos requests concurrentes con la misma key → el `UniqueConstraint`
  deja pasar uno; el otro recibe `IntegrityError` en el INSERT, se captura, y
  se devuelve la cita ganadora con `200 OK`. En `create-with-patient` el
  `IntegrityError` revierte el `transaction.atomic()` completo (owner + pet +
  cita) → **sin huérfanos**.
- El header es **opcional**: sin él, todo funciona como antes (la key queda
  `NULL`).

Convención de status: **201** creación nueva, **200** replay/carrera (el
recurso ya existía). `X-Idempotency-Key` ya está en `CORS_ALLOW_HEADERS`
(ADR p27), así que no requiere cambio de CORS.

## Cambio colateral incluido (mismo PR)

El guard "no crear citas en el pasado" del `AppointmentSerializer.validate`
solo corría en **creación** (`if not instance`). Un `PATCH` (reagendado)
podía mover una cita al **pasado**. Se corrige: el guard aplica también en
update cuando el payload **cambia** `date`/`start_time`/`end_time`. Un update
que no toca la fecha (p.ej. solo `reason`) no se ve afectado. Beneficia a
staff y agente por igual (el guard de Policy del agente era redundante).

## Alternativas descartadas

1. **Soft-lock de horario (reserva temporal)**: reservar el slot X minutos al
   ofrecerlo. Descartado en v1 — añade una tabla de reservas con expiración +
   cleanup y puede bloquear reservas reales. Al volumen actual, la
   revalidación al confirmar + compensación (INT-20 B5) basta. Trigger para
   revisar: tasa de colisión medida en el piloto.
2. **Dedup por (vet, datetime) sin key**: frágil — dos citas legítimas de
   distintos clientes al mismo vet en horarios solapados ya las bloquea el
   check de solape; pero un reintento del MISMO cliente no se distingue de una
   segunda intención sin una key explícita. La key es la señal correcta.
3. **Idempotencia obligatoria**: rompería clientes existentes que no envían el
   header. Opcional preserva compatibilidad.

## Consecuencias

- (+) El agente (É-F2) crea citas sin riesgo de duplicado por reintento.
- (+) El frontend actual queda protegido contra doble-click sin cambiarlo.
- (+) Patrón idéntico a Payment → mantenibilidad (una sola forma de hacer
  idempotencia en el proyecto).
- (−) Un campo más en `Appointment` (aceptado; nullable, sin migración de datos).
- El TOCTOU del check de solape (dos clientes distintos al mismo slot) NO lo
  resuelve la idempotencia — eso se maneja con revalidación + compensación, y
  NO se toca el orden global de locks (ADR p12) desde este cambio.
