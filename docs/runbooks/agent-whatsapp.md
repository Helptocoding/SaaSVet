# Runbook: Agente WhatsApp + Inbox

**Alcance vigente (2026-08-23)**: operación del webhook, worker con agente,
sender y bandeja agrupada por `(contacto, cuenta)` en `/inbox`. El staff puede
responder con idempotencia, estado optimista y acuses de entrega; el agente
mantiene continuidad entre episodios según ADR p58.

Contratos: [`docs/modules/agent.md`](../modules/agent.md) ·
[`docs/whatsapp-agent-epics.md`](../whatsapp-agent-epics.md) · ADRs p51-p60 ·
[`plan de implementación del Inbox`](../plan-implementacion-whatsapp-inbox-2026-08-22.md).

> **Media/B2 no está activa por este runbook.** Su despliegue sigue bloqueado
> por DPA, aviso/ARCO/transferencia y los gates de ADR p60. No reutilizar el
> bucket ni las credenciales del backup p40.

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

Para el agente LLM, `AGENT_LLM_MODEL_OPERATION_AUTHORIZER` y
`AGENT_LLM_MODEL_OPERATION_VERIFIER` son opcionales: si no se fijan, ambos
usan `AGENT_LLM_MODEL_ROUTER` (y este el modelo planner como último fallback).
Separarlos permite observar o cambiar el rol de control sin cambiar el modelo
que redacta respuestas; no cambian la política ni habilitan operaciones por sí
solos.

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
T0-GREET).

**Horario y datos de la clínica**: en la app → `/config` (Configuración →
Horario y Configuración → Clínica). Es la **fuente única**: el agente lee de
ahí los huecos que ofrece, el aviso de fuera de horario y el teléfono de la
plantilla de urgencia. `AgentSettings.business_hours` se eliminó.

**FAQ libre** (estacionamiento, aviso de privacidad…): `PATCH
/api/inbox/settings/` con `faq_facts`. Rechaza con 400 las claves que ya se
editan en Configuración (`telefono`, `direccion`, `horario`, `correo`…).

---

## 2. Smoke E2E del canal y el Inbox

Desde un número registrado en el sandbox:

1. Enviar "hola" al número de la clínica → **≤10 s** llega la respuesta
   automática (T0-GREET o T0-DISABLED) y la conversación aparece en `/inbox`.
2. Reenviar el mismo texto varias veces rápido → sin duplicados raros
   (dedup por wamid absorbe reintentos).
3. Responder desde la bandeja → la burbuja aparece inmediatamente como
   pendiente, el compositor se limpia y la conversación queda reclamada por
   quien respondió. Repetir la misma petición con igual
   `X-Idempotency-Key` debe devolver el mismo `Message`, no crear otro.
4. Confirmar en el sandbox que llega al WhatsApp del tester y que las marcas
   avanzan `pending → sent → delivered → read` sin retroceder. Este paso es el
   gate E2E real de WA-TCK-01; los tests unitarios no lo sustituyen.
5. Verificar separadores `Hoy`/`Ayer` y horas contra la zona horaria configurada
   de la clínica, no contra la del navegador.
6. Cerrar la sesión → un mensaje nuevo del tester abre un episodio NUEVO, pero
   aparece en el mismo hilo agrupado de contacto/cuenta.
7. `docker compose … logs worker | tail` → `AGENT_FIRST_REPLY_QUEUED`, sin
   errores repetidos.

---

## 3. Operación diaria

- **Bandeja `/inbox`**: ASSISTANT/ADMIN operan (ver, tomar, responder,
  cerrar); VET solo lectura. Una fila representa el hilo agrupado de
  `(ContactIdentity, ChannelAccount)`, no cada episodio. Responder = tomar la
  sesión vigente (claim automático). "Liberar" la regresa a la cola.
- **Envío humano**: el pendiente local se reconcilia solo por
  `client_message_id`. Un 4xx lo retira; red o 5xx lo dejan `failed-local` y
  «Reintentar» reutiliza la misma clave. No crear una clave nueva para un
  intento cuyo resultado es incierto.
- **Cambio de sesión**: un `failed-local` pertenece al `sessionId` original y
  no se ofrece en un episodio nuevo. Es deliberado: evita reenviar un mensaje
  viejo a otra sesión.
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

## 4.1 Revisión semanal de calidad (É-F3 W3)

Una vez por semana durante el piloto:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T backend \
  python manage.py agent_quality --days 7 --sample 20
```

Imprime latencia real p50/p95, turnos por resolución, tasa de repregunta y de
handoff, % de audio entrante, y una **muestra estratificada de conversaciones
para leer en `/inbox`** (escaladas, abandonadas y completadas — leer solo las
felices no enseña nada).

Umbrales de atención: latencia p95 > 30 s · handoff > 40 % · repregunta > 20 %
· audio > 15 % (activa el requisito de transcripción, UX-14).

## 5. Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| Meta no verifica el webhook (handshake falla) | `WHATSAPP_VERIFY_TOKEN` no coincide o vacío | Igualar token en `.env.prod` y en Meta; redeploy |
| `WEBHOOK_SIGNATURE_REJECTED` en logs | `APP_SECRET` incorrecto (o alguien probando el endpoint) | Verificar App Secret; si la fuente no es Meta, es ruido esperado — nada se persistió |
| `WEBHOOK_UNKNOWN_CHANNEL` | Mensaje a un `phone_number_id` sin `ChannelAccount` | Correr `provision_channel` para esa org |
| Mensajes salientes en "enviando…" eternos | Worker caído (deadman alertó) o token vencido | `logs worker`; token sandbox caduca en 24 h → regenerar; `AGENT_SEND_FAILED` con 401 = token |
| Mensaje humano queda `failed-local` | La petición no tuvo respuesta fiable (red) o devolvió 5xx | Corregir conectividad/servicio y usar «Reintentar»: conserva la misma clave idempotente. Un 4xx requiere corregir el dato, no reintentar a ciegas |
| El mensaje optimista desaparece o se duplica tras el polling | Falló la correlación por `client_message_id` | Tratar como bug. Confirmar que POST/replay/GET devuelven la misma correlación humana. Nunca deduplicar por cuerpo, autor o tiempo |
| Las marcas quedan en `pending` aunque Meta recibió el mensaje | Sender/webhook de estados detenido, token vencido o acuses no suscritos | Revisar worker, eventos `AGENT_SEND_FAILED`, suscripción `messages` y payloads de estados; repetir el smoke E2E sandbox |
| "no entregado — ventana de sesión de 24h cerrada" | Se intentó responder >24 h tras el último mensaje del cliente | Esperado (límite del canal): el cliente debe escribir de nuevo; plantillas HSM llegan en F3 |
| Respuesta automática duplicada tras reinicio | No debe pasar (estado en DB, `TC-GB-07`) | Si pasara: bug — revisar `has_outbound` en `agent/worker.py::_first_reply_fallback` |
| Después de un recibo aparece una confirmación de cita que el cliente no pidió | Regresión en la frontera semántica post-recibo | Revisar `TurnOperationAssessment` de la conversación, sus `source_messages`, `verdict`, `operation`, `failure_code` y los dos `LLMCall` con prompts `operation-authorizer-v1`/`operation-verifier-v1`. Si no hay una evaluación `authorized` vinculada al `ConversationGoal`, es incidente de integridad: no cerrar ni confirmar la propuesta manualmente. |
| `AGENT_TURN_FAILED` repetido en la misma conversación | Un turno revienta (payload raro, bug). El worker ya NO se cae: reintenta hasta 3 veces con 30 s de respiro | Al agotar reintentos el mensaje pasa a `discarded` y la conversación escala a humano. Revisar el traceback del log y la conversación en `/inbox` |
| Conversación atascada sin procesarse | `processing_until` quedó en el futuro (worker muerto a mitad de turno) | El lease expira solo a los 5 min. Si urge: poner `processing_until=NULL` por shell |
| `AGENT_URGENT_HANDOFF` con `alert_delivered: false` | `DISCORD_WEBHOOK_URL` sin configurar o webhook caído | Configurar la variable; el evento igual queda en el log estructurado |
| El agente tarda ~10 s en responder | Esperado (W1-4): la ventana silenciosa de 8 s agrupa la ráfaga del cliente en un solo turno. Tope duro 25 s | Solo investigar si supera los 30 s |
| `AGENT_REPLY_SUPERSEDED` en logs | El cliente siguió escribiendo mientras el modelo pensaba: la respuesta se descartó y se replanificó | Normal. Frecuencia alta sostenida ⇒ subir `QUIET_WINDOW` |
| `AGENT_OUTPUT_GUARD` con `action: blocked` | El modelo insistió en un precio inventado, un consejo médico o una promesa: **no se envió** y escaló | Revisar la conversación y el prompt. Un pico ⇒ regresión de calidad del proveedor |
| `AGENT_COMMIT_REJECTED` | El dominio rechazó la escritura por datos inválidos (ya no se disfraza de "se ocupó el horario") | El `detail` del log trae el mensaje real del serializer |
| Conversación en org equivocada | NUNCA debe pasar (unique global + guard R1) | Incidente crítico: parar worker, auditar `ChannelAccount`, avisar |

## 6. Kill switch y desmonte

- **Apagar respuestas automáticas**: toggle en `/inbox` (por org, reversible).
- **Apagar TODO el subsistema**: `docker compose … stop worker` (los webhooks
  siguen persistiendo mensajes; nada se responde) o quitar la suscripción del
  webhook en Meta (deja de llegar todo).
- **Desmontar un número de una clínica**: operación manual consciente
  (shell), jamás automatizada — ver guard R1 del provisioning.
