# Runbook: Agente WhatsApp (buzón É-F0)

**Alcance F0**: buzón operable — el webhook recibe, el worker auto-saluda una
vez por conversación (o avisa que recepción responderá, según el kill switch)
y el staff atiende desde `/inbox`. **Sin LLM** (llega en É-F1).

Contratos: [`docs/modules/agent.md`](../modules/agent.md) ·
[`docs/whatsapp-agent-epics.md`](../whatsapp-agent-epics.md) · ADR p51.

---

## 1. Provisioning end-to-end (una vez por entorno)

### 1.1 App en Meta for Developers (sandbox o producción)

1. https://developers.facebook.com → crear app tipo **Business** → añadir
   producto **WhatsApp**.
2. Anotar del panel *API Setup*:
   - **Phone number ID** (número de prueba en sandbox; el real tras verificar
     el negocio) → será el `--phone-number-id` del provisioning.
   - **Access token** (el temporal de 24 h sirve para pruebas; producción usa
     un **System User token** permanente).
   - **App Secret**: *App settings → Basic → App secret*.
3. Sandbox: registrar hasta 5 números destinatarios de prueba (*To*).

### 1.2 Variables de entorno (`.env.prod`, sección "Agente WhatsApp")

`WHATSAPP_VERIFY_TOKEN` (lo eliges tú) · `WHATSAPP_APP_SECRET` ·
`WHATSAPP_ACCESS_TOKEN` · `HEALTHCHECK_AGENT_WORKER_URL` (deadman, §4).
**Fail-closed**: sin `APP_SECRET`, el webhook rechaza todo POST — el sistema
queda sordo pero jamás inseguro.

### 1.3 Deploy + provisioning de la clínica

```bash
cd ~/apps/SaaSVet && bash scripts/deploy.sh   # levanta también el servicio `worker`

# Alta del canal (idempotente; crea user AGENT + AgentSettings + ChannelAccount)
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T backend \
  python manage.py provision_channel \
    --org <public_id de la organización> \
    --phone-number-id <Phone number ID de Meta> \
    --display-number "+52 1 55 ..."
```

Guard R1: si el `phone-number-id` ya pertenece a OTRA organización el comando
aborta — un número jamás se reasigna por comando.

### 1.4 Suscribir el webhook en Meta

1. *WhatsApp → Configuration → Webhook*:
   - **Callback URL**: `https://app.saaslyvet.com/hooks/whatsapp/`
   - **Verify token**: el valor de `WHATSAPP_VERIFY_TOKEN`.
   - *Verify and save* → Meta hace el GET de handshake (responde el challenge).
2. **Subscribe** al campo **`messages`** de la WABA.

### 1.5 Encender el buzón

Kill switch (default OFF): en la app → `/inbox` → "Activar respuestas
automáticas" (requiere `agentinbox.config`, ADMIN). Con OFF el buzón igual
captura todo; solo cambia la primera respuesta automática (T0-DISABLED vs
T0-GREET). Horario y FAQ: `PATCH /api/inbox/settings/`
(`business_hours = {"mon": [["09:00","19:00"]], ...}` en hora local de la org).

---

## 2. Smoke E2E (gate de cierre de É-F0)

Desde un número registrado en el sandbox:

1. Enviar "hola" al número de la clínica → **≤10 s** llega la respuesta
   automática (T0-GREET o T0-DISABLED) y la conversación aparece en `/inbox`.
2. Reenviar el mismo texto varias veces rápido → sin duplicados raros
   (dedup por wamid absorbe reintentos).
3. Responder desde la bandeja → llega al WhatsApp del tester; la conversación
   pasa a "Atendida" y queda reclamada por quien respondió.
4. Cerrar la conversación → un mensaje nuevo del tester abre un hilo NUEVO.
5. `docker compose … logs worker | tail` → `AGENT_FIRST_REPLY_QUEUED`, sin
   errores repetidos.

---

## 3. Operación diaria

- **Bandeja `/inbox`**: ASSISTANT/ADMIN operan (ver, tomar, responder,
  cerrar); VET solo lectura. Responder = tomar la conversación (claim
  automático). "Liberar" la regresa a la cola.
- **Estados**: Abierta → Esperando → Atendida → Cerrada. Cerrada es terminal
  (mensaje posterior = hilo nuevo con la misma identidad de contacto).
- **Identidad**: el número se matchea contra `Owner.phone` (0 = desconocido,
  1 = coincidencia, ≥2 = ambiguo — el sistema nunca adivina).
- **Cuenta AGENT dañada/borrada por shell**:
  `python manage.py ensure_agent_users` (idempotente, repara/recrea).

## 4. Worker

- Servicio `worker` del compose (misma imagen que backend, `restart:
  unless-stopped`, 256 MB). Escalar = `docker compose up -d --scale worker=2`
  (SKIP LOCKED reparte sin coordinación).
- **Deadman**: crear check "vet-agent-worker" en Healthchecks.io (period ~5
  min, grace 5 min) y setear `HEALTHCHECK_AGENT_WORKER_URL`. El loop pinguea
  cada ~60 ciclos sanos.
- Logs (JSON, logger `agent.events`): `docker compose … logs -f worker`.
  Eventos: `AGENT_WORKER_STARTED/STOPPED`, `AGENT_FIRST_REPLY_QUEUED`,
  `AGENT_SEND_FAILED`, `AGENT_SEND_WINDOW_CLOSED`, `AGENT_CONTACT_CREATED`,
  `AGENT_CONVERSATION_OPENED`. **Jamás contienen cuerpos de mensaje** (PII
  solo en DB — regla R15).

## 5. Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| Meta no verifica el webhook (handshake falla) | `WHATSAPP_VERIFY_TOKEN` no coincide o vacío | Igualar token en `.env.prod` y en Meta; redeploy |
| `WEBHOOK_SIGNATURE_REJECTED` en logs | `APP_SECRET` incorrecto (o alguien probando el endpoint) | Verificar App Secret; si la fuente no es Meta, es ruido esperado — nada se persistió |
| `WEBHOOK_UNKNOWN_CHANNEL` | Mensaje a un `phone_number_id` sin `ChannelAccount` | Correr `provision_channel` para esa org |
| Mensajes salientes en "enviando…" eternos | Worker caído (deadman alertó) o token vencido | `logs worker`; token sandbox caduca en 24 h → regenerar; `AGENT_SEND_FAILED` con 401 = token |
| "no entregado — ventana de sesión de 24h cerrada" | Se intentó responder >24 h tras el último mensaje del cliente | Esperado (límite del canal): el cliente debe escribir de nuevo; plantillas HSM llegan en F3 |
| Respuesta automática duplicada tras reinicio | No debe pasar (estado en DB, `TC-GB-07`) | Si pasara: bug — revisar `has_outbound` en `agent/worker.py::_process_one` |
| Conversación en org equivocada | NUNCA debe pasar (unique global + guard R1) | Incidente crítico: parar worker, auditar `ChannelAccount`, avisar |

## 6. Kill switch y desmonte

- **Apagar respuestas automáticas**: toggle en `/inbox` (por org, reversible).
- **Apagar TODO el subsistema**: `docker compose … stop worker` (los webhooks
  siguen persistiendo mensajes; nada se responde) o quitar la suscripción del
  webhook en Meta (deja de llegar todo).
- **Desmontar un número de una clínica**: operación manual consciente
  (shell), jamás automatizada — ver guard R1 del provisioning.
