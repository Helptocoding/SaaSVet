# ADR p24: Deuda `id`/`public_id` — contención de exposición dual

**Fecha:** 2026-05-26
**Estado:** Aceptado — deuda registrada + política de contención. Remoción completa diferida.
**Impacto:** contrato de API (serializers de modelos públicos), frontend. Enforcement en `apps/core/tests`.
**Sigue a:** ADR p18 (IDs en superficies externas — `public_id` en URLs), ADR p23 (patrón "diferir cambio grande, control interino ahora").
**Origen:** Auditoría arquitectónica 2026-05-26 (deuda D5) + Capa 3 del plan.

---

## Contexto

~10 serializers de modelos públicos exponen el **PK entero `id`** junto a `public_id` (UUID) en `Meta.fields`:

- `organizations.OrganizationSerializer`, `users.UserSerializer`,
  `billing` (Service, Invoice), `inventory` (Presentation, Product),
  `medical_records` (MedicalRecord, VaccineRecord), `prescriptions.PrescriptionSerializer`,
  `appointments.AppointmentSerializer`.

La exposición de `id` fue **decisión consciente Día 6** (ver `organizations/serializers.py:11`: "expone public_id junto a id (id se conserva pre-beta...)"). Las URLs ya usan `public_id` (ADR p18); el PK ya NO se acepta como lookup en URLs. El residuo es la **exposición en el body de respuesta**.

### Riesgo

1. **Information disclosure** — el PK secuencial revela orden de creación, conteo aproximado de filas y permite inferencia cross-tenant de volumen. Menor que IDOR (las URLs no aceptan PK), pero es superficie innecesaria.
2. **Expansión de dependencia híbrida** — el verdadero peligro NO es el estado actual (contenido), sino que **nuevo código siga consumiendo/exponiendo `id`**, ampliando la deuda y dificultando la migración futura.

---

## Decisión

**NO remover `id` ahora.** Remover de ~10 serializers es un contract change rompedor, acoplado al frontend (que puede leer `.id`), sin auditoría de frontend hecha. Riesgo > beneficio pre-beta.

**En su lugar: CONTENER la deuda.**

- **Nuevo código:** todo serializer nuevo de un modelo con `public_id` expone **solo `public_id`, nunca `id`**.
- **Legacy:** los ~10 serializers actuales se toleran temporalmente (baseline congelado).
- **Enforcement automático:** ratchet test `apps/core/tests/test_public_id_dual_exposure_audit.py` — congela el set actual de serializers que exponen `id`+`public_id`. Un serializer NUEVO con ambos → el test falla y obliga a usar solo `public_id` (o, si es legacy legítimo, alta consciente al baseline con revisión).
- **Frontend:** convención `publicId`; el anti-pattern `editing.public_id || editing.id` ya está prohibido en `CLAUDE.md`.

Esto mantiene la migración **contenida**: la deuda no crece, y se puede pagar cuando se coordine con el frontend.

---

## Opciones rechazadas

### A — Remoción inmediata de `id` de los ~10 serializers
Rechazada pre-beta: breaking contract, frontend-coupled, sin audit de `.id` reads en frontend. Un fallo silencioso rompe la UI. Es una tarea coordinada, no un quick win.

### B — Dejar la deuda sin enforcement (solo documentar)
Rechazada: sin ratchet, nuevo código sigue copiando el patrón `'id', 'public_id'`. La deuda crece. El valor real de esta ADR es **cortar el crecimiento**, no solo describirlo.

### C — Ratchet sobre consumers de frontend (`.id` reads)
Diferida: el frontend usa JS (sin la infra AST de los tests Python) y ya sigue convención `publicId`. El punto de enforcement de mayor leverage es el **suministro backend** — si el serializer no expone `id`, el frontend no puede consumirlo. Un lint de frontend queda como follow-up opcional.

---

## Plan de salida (futuro, coordinado con frontend)

1. Auditar frontend por lecturas de `.id` en recursos de modelos públicos.
2. Migrar esas lecturas a `publicId`.
3. Remover `id` de los serializers fase por fase (con tests de contrato).
4. Vaciar el baseline del ratchet conforme se remueven.

---

## Tests

- `apps/core/tests/test_public_id_dual_exposure_audit.py` — ratchet: el set actual de serializers con `id`+`public_id` debe ser exactamente el baseline congelado. Nuevo → falla; removido → falla (baseline stale).

---

## Referencias

- ADR p18 — `public_id` en URLs / superficies externas.
- ADR p23 — RLS diferido + control interino (mismo patrón de decisión).
- `CLAUDE.md` — sección IDs públicos; anti-pattern `editing.public_id || editing.id`.
- Auditoría 2026-05-26 — deuda D5.
