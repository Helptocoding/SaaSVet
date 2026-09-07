# Mapa Operacional del Sistema

**Fecha**: 2026-09-07
**Estado**: vigente (incluye ADR p62 y el contrato Checkout/Billing)
**Audiencia**: nuevo desarrollador, QA, tester, soporte.

Este documento es el **índice general** de la arquitectura operacional del SaaS:
qué módulos existen, cómo se relacionan y dónde encontrar la información detallada.

La documentación detallada se ha dividido en archivos enfocados para mantener el
contexto de trabajo ligero y preciso:

| Documento | Contenido | Cuándo cargarlo |
|-----------|-----------|-----------------|
| [`system-module-operations.md`](system-module-operations.md) | Acciones por módulo: qué requiere cada operación, qué produce, qué desbloquea y qué bloquea (§1-10). | Implementar o revisar una acción específica de negocio. |
| [`system-flows.md`](system-flows.md) | Recorridos extremo a extremo (Flujos A-D), resumen de flujos válidos e inválidos (§11-13). | Entender cómo se conectan múltiples módulos en un escenario real. |
| [`system-reference.md`](system-reference.md) | Errores comunes con diagnóstico, dependencias críticas, invariantes del sistema y resumen ejecutivo (§14-17). | Debuggear un error, verificar reglas que no deben romperse, onboarding. |

---

## 0. Mapa de módulos

| Módulo | Responsabilidad |
|--------|-----------------|
| `platform` | Provisión cross-tenant: crear organizaciones nuevas y su admin inicial. SaaS-wide. |
| `organizations` | Tenant. Una clínica = una organización. Perfil, timezone, tax_rate. Tres agregados: `Organization` (identidad/contacto/ubicación), `OrganizationSettings` (reglas operativas, toggles), `OrganizationSchedule` (horario semanal, 7 filas por organización). Ver ADR p53. |
| `users` | Cuentas y roles (ADMIN_SAAS, ADMIN, VET, ASSISTANT). RBAC dinámico. |
| `patients` | Propietarios (Owner) + mascotas (Pet). Punto de entrada a todos los flujos clínicos. |
| `appointments` | Agenda. Estados, walk-in, asignación de paciente, registro rápido. Dueño de dos garantías de dominio (ADR p57): **INV-A** (precondición atómica de estado, `expected_state` → `409 appointment_changed`) e **INV-D** (no-solapamiento por veterinario, restricción de exclusión en PostgreSQL → `400 slot_taken`). |
| `medical_records` | Acto clínico: consulta, vitales, productos consumidos, servicios prestados, receta. |
| `inventory` | Catálogo (Product) + presentaciones (Presentation) + stock + movimientos. |
| `billing` | Preparación en Checkout, Invoice `posted/paid/voided`, ledger de pagos, notas de crédito, refunds, attestation Rx y dispensación. |
| `cash` | Turno de caja (CashSession) y cierre Z. Reconciliación física del efectivo. |
| `analytics` | Snapshots diarios + dashboards (operacional + financiero). Read-only sobre eventos. |
| `imports` | Migración CSV/Excel: alta por lote de Clientes + Mascotas desde el sistema anterior. Escribe `patients` vía `.save()` directo. ADR p43. Ver [`modules/imports.md`](modules/imports.md). |
| `logs` | Eventos estructurados JSON a stdout (RBAC, tenant, anchors, deprecation, integridad). |
| `channels` | **Frontera de mensajería**: `ChannelAccount` (un número = una organización, por constraint global) y `Message` (entrantes y salientes en una tabla). Los envíos humanos se deduplican por organización/clave y publican `client_message_id`; los mensajes internos nunca filtran esa correlación. Ningún módulo de dominio lo importa. Ver [`modules/agent.md`](modules/agent.md). |
| `agent` | Asistente de WhatsApp: identidad del contacto, conversación, compromisos, herramientas e Inbox agrupado por contacto/cuenta. **Escribe dominio solo por la API, con su propio rol `AGENT`** — nunca por ORM directo. ADRs p51-p60. |
| `backup` | **Infra/ops (host-level, no es app Django)**: backup nightly cifrado offsite + restore + drill DR. ADR p40. Ver [`modules/backup.md`](modules/backup.md). |

### Dependencias funcionales

```
platform → organizations → users
                ↓
       patients (Owner, Pet)
                ↓
      ┌────────────────────────┐
      ↓                        ↓
 appointments           inventory (Product/Presentation)
      ↓                        ↓
medical_records ──────► billing (Invoice/Payment/CreditNote)
                              ↓
                         cash (CashSession)
                              ↓
                       analytics (snapshots)
                              ↓
                            logs
```

Reglas de boundary:
- `platform` solo lee `organizations` / `users` / `core`.
- Dominios (`medical_records`, `billing`, `inventory`, `appointments`) NUNCA importan `platform`.
- `cash` recibe FK de `billing.Payment` con string-ref → sin ciclo de import.
- `analytics` lee anchors de `billing` / `medical_records` / `appointments`; NUNCA escribe.
- `imports` (ADR p43) solo escribe `patients` (Owner/Pet) vía `.save()` directo, saltando los serializers manuales; NUNCA toca billing/inventory/appointments.
- `backup` (host-level, ADR p40) lee la DB vía `pg_dump` fuera de la app; nunca importa código de dominio. Offsite cifrado (age, zero-knowledge) + inmutable (B2 Object Lock).
