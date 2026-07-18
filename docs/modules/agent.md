# Módulos: agent + channels (subsistema del agente conversacional)

> **Estado**: É-F1 (agente read-only con LLM — policy + tools de lectura). É-F0 (buzón) + É-F1 código completo en CI. Contrato de implementación:
> [`docs/whatsapp-agent-epics.md`](../whatsapp-agent-epics.md) · spec funcional
> congelada F1: [`docs/whatsapp-agent-functional-spec.md`](../whatsapp-agent-functional-spec.md)
> · identidad del actor: ADR p51. Runbook operativo:
> [`docs/runbooks/agent-whatsapp.md`](../runbooks/agent-whatsapp.md).

## Boundary (vinculante)

`channels` (transporte) y `agent` (núcleo conversacional) son dominios
**FRONTERA**: consumen el resto del sistema solo vía API HTTP autenticada
(desde É-F1, con el JWT del user AGENT) y **ningún módulo de dominio los
importa**. Entre ellos: `channels` referencia `agent.Conversation` por string
ref; `channels.views` importa `agent.services` perezoso.

## Modelos

| Modelo | App | Claves |
|---|---|---|
| `ChannelAccount` | channels | `external_account_id` (phone_number_id) **unique GLOBAL** — el enrutamiento número→org es el control anti cross-tenant (R1); `provider_credentials_ref` = NOMBRE de env var (secreto jamás en DB) |
| `Message` | channels | Tabla ÚNICA in/out. El inbox ES la cola y el outbox un filtro (`status`); dedup de reintentos: unique parcial `(channel_account, external_message_id)` solo inbound (patrón Payment/ADR p27); `available_at` = drain-on-pickup (+3 s) |
| `ContactIdentity` | agent | Identidad POR ORG (`unique org+channel+external_id` — el mismo cliente puede escribir a 2 clínicas); `verification_level` (unknown→phone_match→confirmed_in_chat→staff_verified); `phone_normalized` (Q5: últimos 10 dígitos, México-only); NO es un User — jamás recibe tokens |
| `Conversation` | agent | `PublicIdMixin` (la bandeja navega por UUID); FSM 4 estados: `active → handoff_pending → human_active → closed`; **CLOSED es terminal** (mensaje posterior = hilo nuevo); org fijada al crear e inmutable; `flow`/`summary` = scratchpad (filosofía ADR p50, jamás fuente de verdad) |
| `AgentSettings` | agent | OneToOne a Organization (patrón OrganizationSettings): `enabled` (kill switch, default False), `agent_user`, `business_hours`, `faq_facts` |

## Flujo F0

```
Cliente → WhatsApp → POST /hooks/whatsapp/ (firma HMAC, fail-closed)
  → routing phone_number_id → ChannelAccount → org (R1)
  → dedup wamid → ContactIdentity (match Owner: 0/1/≥2=ambiguous)
  → Conversation abierta (o nueva) → Message(in, pending, available_at=+3s)
Worker (run_agent_worker, SKIP LOCKED por conversación):
  → marca procesados → si NO hay salientes previos: encola 1ª respuesta
    (T0-GREET / T0-DISABLED / +sufijo fuera-de-horario, plantillas LITERALES)
Sender: outbox → Meta Cloud API (backoff 30s·2^n cap 1h, máx 5; ventana 24h
  se valida ANTES de intentar HTTP) → acuses sent/delivered/read forward-only
Staff → /inbox (bandeja): responder = tomar (human_active + claim).
```

## Endpoints

| Superficie | Auth | Notas |
|---|---|---|
| `GET/POST /hooks/whatsapp/` | Firma del proveedor (SIN JWT, fuera de `/api/`) | Handshake + eventos; sin firma válida no se toca la DB; siempre 200 tras firma válida |
| `GET /api/inbox/conversations/` (+`?state=`) | `agentinbox.view` | Default excluye cerradas; cap 100 |
| `GET /api/inbox/conversations/<uuid>/messages/` | `agentinbox.view` | Transcript cronológico, cap 200 |
| `POST …/send/` | `agentinbox.send` | Sanitizado, máx 4000; deja la conversación en `human_active` + claim |
| `POST …/claim/` · `…/close/` · `…/release/` | `agentinbox.claim` | Claim exclusivo → 409 `already_claimed` |
| `GET/PATCH /api/inbox/settings/` | `agentinbox.config` | Kill switch + `business_hours` (schema validado) + `faq_facts` (caps 20×500) |

Permisos (Q13): ADMIN `*.*` · ASSISTANT view+claim+send · VET view · AGENT
(el bot) ninguno de bandeja.

## Comandos

- `provision_channel --org --phone-number-id [--display-number] [--credentials-ref]`
  — idempotente; guard R1 (número de otra org → error, sin escrituras).
- `ensure_agent_users [--org]` — repara/recrea el service account (ADR p51).
- `run_agent_worker [--once] [--poll] [--batch]` — el proceso worker (F1:
  corre policy→planner→tools por entrante; cierra inactivas 24h en el loop).
- `agent_eval [--json]` — eval nightly con LLM real (no bloqueante, rollback;
  skip si no hay `AGENT_LLM_API_KEY`). Gate del piloto: ≥95 % en 5 corridas.

## Agente F1 (LLM read-only)

Pipeline por entrante (`agent/planner.py`): `policy.evaluate` resuelve
tier-0 sin LLM (urgencia/humano/opt-out/bot/confirmación/presupuesto);
`RUN_PLANNER` corre el bucle acotado LLM↔tools (executor loopback+RBAC
reales, resultado como DATOS G6, `LLMCall` por llamada). El LLM **nunca
autoriza**: policy decide antes, run_tool/executor revalidan
tier/verificación/ownership. Proveedor LLM = elección del operador
(`AGENT_LLM_*` por env, cliente OpenAI-compatible en `agent/llm.py`).
Tools de lectura (spec §9): list_my_pets, get_vaccine_status,
list_upcoming_appointments, get_clinic_info, get_service_catalog,
check_product_availability, request_human. Handles efímeros en `flow.refs`
con resolver+ownership server-side (handle desconocido = denegación dura).
Identidad (`agent/identity.py`): implícita (nombrar mascota) + reto UX-03.
Suite de regresión: 63 casos congelados en CI contra `StubLLMClient`
(bloqueante) + fixture trampa cross-tenant + aserciones prohibidas globales
(`agent/tests/harness.py`).

## Invariantes propios (además de los globales)

1. La organización de una conversación nace del `ChannelAccount` receptor y
   NUNCA se re-deriva (R1).
2. Un wamid entrante se persiste a lo sumo una vez por canal (R5, constraint DB).
3. Cuerpos de mensaje SOLO en DB — jamás en logs ni Sentry (R15).
4. Plantillas tier-0 son literales (contrato spec §1.3) — el copy no se
   improvisa en código.
5. Fuera de la ventana de 24 h no sale texto libre (lo valida el sender).
6. `enabled=False` no apaga la captura: solo cambia la primera respuesta.
