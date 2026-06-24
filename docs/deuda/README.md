# Deuda técnica — Índice

Repositorio centralizado de deuda técnica acumulada durante el desarrollo pre-beta. Cada item lleva: prioridad, scope, archivos afectados, ADR de origen, criterio de cierre, estimación.

**Principio operativo:** todo lo aquí documentado fue deferido conscientemente (no olvidado). Si un item lleva 3 meses sin avanzar, re-evaluar: ¿sigue siendo deuda o se convirtió en feature aceptada?

---

## Estado actual (act. 2026-06-24)

| Fase | Prioridad | Items | Archivo |
|------|-----------|-------|---------|
| Fase 2 | 🔴 Alta — post-beta inmediato | 4 | [fase2-prioridad-alta.md](fase2-prioridad-alta.md) |
| Fase 3 | 🟠 Media — sprint dedicado | 7 | [fase3-prioridad-media.md](fase3-prioridad-media.md) |
| Fase 4 | 🟡 Baja — mejoras arquitectónicas | 7 | [fase4-prioridad-baja.md](fase4-prioridad-baja.md) |
| Día 6 — Post-beta | 🔴 Alta — sprint post-cutover | 5 | [../day6/POST-BETA-DEBT.md](../day6/POST-BETA-DEBT.md) |
| Día 6 — Post-cutover | 🟠 Media — 2026-06-19 | 1 | flag `ALLOW_LEGACY_ID_LOOKUP` cleanup (ver POST-BETA-DEBT) |

---

## Reglas de gobernanza

1. **No expandir scope sin justificación documentada.** Cada item adicional debe enlazar al PR/issue/ADR que lo originó.
2. **Cerrar items por commit, no por refactor masivo.** Un sprint = 1-3 items max. Refactor de N módulos = N PRs separados.
3. **No promover infra a `apps/core/` sin battle-testing previo** (≥4 semanas de uptime en producción de los helpers locales).
4. **Mantener separación de eventos de log por severidad** — un evento agregado a la deuda debe especificar event name + level + dashboard impactado.
5. **Tests de regresión obligatorios** para cualquier item con `bug pre-existente` flag. No `@expectedFailure` cerca de release.

---

## ADRs de referencia (origen de la deuda)

- [`2026-05-16-p12-concurrency-lock-order-hardening.md`](../decisions/2026-05-16-p12-concurrency-lock-order-hardening.md) — Sprint Días 1-2 (P0 #1-7 concurrency)
- [`2026-05-16-p13-day12-concurrency-remediation.md`](../decisions/2026-05-16-p13-day12-concurrency-remediation.md) — Remediación post-review Día 1-2
- [`2026-05-16-p14-tenant-validators-day3.md`](../decisions/2026-05-16-p14-tenant-validators-day3.md) — Día 3 (P0 #8-9 tenant) + plan Fase 2
- [`2026-05-09-p9-analytics-anchor-authority.md`](../decisions/2026-05-09-p9-analytics-anchor-authority.md) — Single authoritative writer pattern
- [`2026-05-17-p15-day4-cascade-lockdown.md`](../decisions/2026-05-17-p15-day4-cascade-lockdown.md) — Día 4 PR-4A (P0 #12-13 escalation + DRF perms)
- [`2026-05-17-p16-pr4b-cascade-and-singleton.md`](../decisions/2026-05-17-p16-pr4b-cascade-and-singleton.md) — Día 4 PR-4B (cascade lockdown + Organization singleton)
- [`2026-05-17-p17-analytics-correctness-day5.md`](../decisions/2026-05-17-p17-analytics-correctness-day5.md) — Día 5 (P0 #14-17 analytics)
- [`2026-05-20-p18-ids-en-superficies-externas.md`](../decisions/2026-05-20-p18-ids-en-superficies-externas.md) — Día 6 (P0 #18 + P1 #38-40 IDs/public_id)

---

## Memoria de patrones (preferencias usuario)

Vivienen en `~/.claude/projects/<repo>/memory/`:

- `feedback_invoice_item_f_expression.md` — `F('quantity') ± delta` obligatorio sobre `InvoiceItem.quantity`
- `feedback_serializer_context_access.md` — `.get('request') + assert` pattern (nunca `['request']`)
- `feedback_security_planning.md` — orden correcto de fases en hardening de seguridad
