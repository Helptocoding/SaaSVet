# Runbook: Agente WhatsApp + Inbox

## B3: despliegue controlado y rollback

Contrato vigente: [trabajo durable B3](../contrato-trabajo-durable-b3.md) y
[ADR](../decisions/2026-09-15-b3-durable-turn-ownership-publication.md).
No se ha desplegado este corte. Activación: **PENDING_ACTIVATION_REQUIREMENTS**.
El kill switch/containment B0 permanece disponible y WRITE continúa cerrado.

### Secuencia de cutover

1. Programar ventana controlada. Pausar el servicio `worker` de **todas** las
   réplicas (`run_agent_worker` incluye planner y sender), dejar terminar sus
   operaciones en vuelo y confirmar que no quedan procesos antiguos. Si un
   proceso debe terminarse forzosamente, registrar sus trabajos/pending y
   reconciliar aceptación externa antes de reanudar; B3 no resuelve B4.
2. Conservar ingress/webhooks durables si el mantenimiento lo permite; pausar
   brevemente las acciones mutadoras de Inbox durante el cambio de API para
   que ningún escritor antiguo opere junto al nuevo. No usar rolling deploy
   de workers: el antiguo ignora TurnWork y podría reclamar los mismos inbound.
3. Respaldar y aplicar migraciones aditivas: `agent.0022`, `channels.0011` y
   `channels.0012`. Verificar `showmigrations agent channels` y
   `makemigrations --check --dry-run` con la imagen nueva. No hay backfill de
   membership histórico ni origin_epoch para mensajes antiguos.
4. Desplegar API, worker y selector sender compatibles B3 desde el mismo corte.
   Inspeccionar pendientes legacy antes de arrancar: outbound sin origin_epoch
   será descartado como `legacy_unverified`, incluidos humanos ambiguos. Es
   visible en historial; no se reenvía ni se le asigna epoch sintético. El staff
   puede evaluar una respuesta nueva usando la ruta normal cuando corresponda.
5. Reiniciar solamente procesos B3 con el alcance previamente autorizado. No
   habilitar WRITE ni ampliar beta por haber desplegado infraestructura. El
   sender compatible opera ya con PENDING B3; no necesita esperar B4.
6. Observar claims, reclaims, expiraciones, completion, FAILED, fencing rejects
   y deferred. Confirmar un único trabajo no terminal, miembros fijos, attempts,
   pending age y ausencia de PROCESSED prematuro. Mantener observación de sender
   y ventana de 24 h existentes; no interpretar COMPLETED como entrega.

Comandos de comprobación (desde `backend/`, entorno elegido explícitamente):

```powershell
rtk proxy python manage.py migrate --noinput
rtk proxy python manage.py showmigrations agent channels
rtk proxy python manage.py makemigrations --check --dry-run
```

### Diagnóstico y rollback operacional

- Leer `TurnWork.status`, attempts, next_attempt_at, lease_expires_at y
  outcome_code por organización. Para pendientes legacy inbound ya PROCESSED
  sin TurnWork, reportar **legacy_unverified**; no inferir completion ni hacer
  replay por ausencia de outbound (puede haber sido un turno sin respuesta).
- `PROCESSING` expirado se recupera por polling con nuevo token; nunca cambiar
  `processing_until` para forzar autoridad. Deadline 12 min, lease 15 min,
  máximo 3 intentos y backoff 30/60 s. FAILED conserva membership y no convierte
  sus inbound a PROCESSED; requiere revisión operativa, sin resurrección automática.
- Ante regresión, pausar autonomía/worker mediante B0 y detener sender si la
  causa afecta publicación o selección. Conservar DB, TurnWork, epochs,
  correlaciones, outcomes y estados de Message. Usar Inbox/lector compatible B3.
- No revertir las migraciones, bajar epochs, borrar trabajos, soltar membership,
  convertir FAILED en PENDING ni reinstalar un worker B2 que ignore TurnWork.
  Corregir hacia delante y reconciliar trabajo/pendientes/posibles envíos antes
  de reanudar. Respuesta humana debe usar la API B3 compatible.

**B3 garantiza autoridad y publicación local durable. B4 resolverá la frontera
de dispatch externo y resultados inciertos.** El HTTP admitido puede terminar
tras takeover; no se ofrece cancelación remota ni entrega exactamente una vez.

> **Enmienda de alcance B0 — 2026-09-13.** WRITE autónomo cerrado, incluidos asistencia y pendientes heredados. READ dentro de restricciones actuales y atención humana; copy sin aviso/atención garantizados. No cambia el detector clínico ni se amplía beta. Consultar [acta B0](../implementacion-b0-agente-whatsapp-2026-09-13.md) para contratos mínimos, responsables pendientes, gate crítico, despliegue sin workers viejos y rollback que conserve contención. Esta enmienda prevalece sobre ejemplos de autonomía/avisos anteriores.

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
| Respuesta automática duplicada tras reinicio | Frontera HTTP incierta del sender legacy (B4 pendiente) o regresión local | Revisar work/ordinal/epoch y evidencia de envío; pausar y reconciliar, sin replay automático |
| Después de un recibo aparece una confirmación de cita que el cliente no pidió | Regresión en la frontera semántica post-recibo | Revisar `TurnOperationAssessment` de la conversación, sus `source_messages`, `verdict`, `operation`, `failure_code` y los dos `LLMCall` con prompts `operation-authorizer-v1`/`operation-verifier-v1`. Si no hay una evaluación `authorized` vinculada al `ConversationGoal`, es incidente de integridad: no cerrar ni confirmar la propuesta manualmente. |
| `AGENT_TURN_FAILED` | Fallo terminal de TurnWork tras 3 intentos | Revisar outcome/attempts y handoff; inbound sigue pending asignado, nunca PROCESSED ni replay automático |
| Conversación atascada sin procesarse | TurnWork PROCESSING con worker muerto | Lease DB de 15 min; polling recupera el mismo trabajo. No modificar processing_until para reclamar |
| `AGENT_URGENT_HANDOFF` con `alert_delivered: false` | `DISCORD_WEBHOOK_URL` sin configurar o webhook caído | Configurar la variable; el evento igual queda en el log estructurado |
| El agente tarda ~10 s en responder | Esperado (W1-4): la ventana silenciosa de 8 s agrupa la ráfaga del cliente en un solo turno. Tope duro 25 s | Solo investigar si supera los 30 s |
| `AGENT_TURN_DEFERRED_TO_NEW_INPUT` | Llegó input posterior durante W1 | W1 completa sin outbound; nuevo input queda para W2. No reiniciar W1 ni interpretar cortesías/correcciones antes de B6 |
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

## B4: cutover controlado y rollback

Contrato normativo: [sender B4](../contrato-sender-durable-b4.md). No ejecutar
deploy por cerrar el acta. Containment activo y WRITE autónomo cerrado durante
todos los pasos. No hay rollout mixto seguro con el sender pre-B4: ignora claims
durables y puede devolver a pending un HTTP que Meta aceptó.

### Cutover (ventana de mantenimiento)

1. Registrar imagen/base, backup y responsables; mantener B0 y activación
   PENDING_ACTIVATION_REQUIREMENTS. Pausar todas las réplicas sender/worker viejas.
2. Esperar salida de procesos y examinar outbounds existentes. No inferir
   «no enviado» de attempts=0: un rollback legacy también borraba ese contador.
   No reanudar automáticamente un lote antiguo cuyo HTTP pudo salir.
3. Aplicar migración aditiva `channels.0013_b4_durable_sender` con todos los
   senders detenidos. No hace backfill ni reescribe estados históricos.
4. Desplegar API/lector compatible, planner y sender B4; mantener sender parado
   hasta terminar clasificación. No mezclar código anterior y actual.
5. Con scope org/cuenta, inspeccionar pendientes del corte: los que carecen de
   epoch conservan política B3 `legacy_unverified`/DISCARDED, sin replay. Si hay
   indicios de HTTP previo o no puede demostrarse que el lote no se admitió,
   poner los mensajes afectados en UNCERTAIN con fecha de clasificación y razón
   `cutover_legacy_dispatch_unknown`. Ese tiempo no es aceptación/delivery.
   Un responsable conserva IDs/decisión en el registro operativo. No usar texto,
   teléfono o proximidad de tiempo para inventar wamid.
6. Conservar SENT+ID, DELIVERED/READ y timestamps existentes; nuevas fechas NULL
   siguen desconocidas. SENT sin ID permanece visible como histórico desconocido.
7. Iniciar `run_agent_worker --mode planner` y `--mode sender` en procesos
   separados (Compose ya los declara). Una réplica sender es suficiente para
   beta; no se amplía capacidad ni se habilitan escrituras.
8. Ejecutar `inspect_agent_outbound`; observar pendientes/edades, SENDING vencidos,
   UNCERTAIN, conflictos, descartes y status unmatched. Probar un envío controlado
   bajo aprobación operativa separada; este trabajo no llamó a Meta real.

Comandos de verificación, desde backend y con entorno explícito correcto:

```powershell
rtk proxy python manage.py migrate --noinput
rtk proxy python manage.py showmigrations agent channels
rtk proxy python manage.py makemigrations --check --dry-run
rtk proxy python manage.py inspect_agent_outbound
rtk proxy python manage.py run_agent_worker --mode sender --once
```

El último comando puede enviar pendientes: solo después de terminar el cutover.
`inspect_agent_outbound` es solo lectura. Para despliegue normal, Compose usa
worker/planner y sender independientes, misma imagen, 256 MiB cada uno. Batch
default 10 (20 candidatos sender), poll 2 s. Configurar deadman separado
HEALTHCHECK_AGENT_SENDER_URL si se utiliza; el del planner no prueba sender vivo.

### Tratar incertidumbre

Un webhook HMAC válido puede reconciliar si ya existe un wamid exacto persistido
para la misma org/cuenta. Mantener original y uncertain_at. Si se perdió ese ID,
no existe recuperación automática segura por el contrato actual. Inspección
manual puede dejar el caso incierto. No crawler/polling de Meta.

La reemisión explícita usa `sender.reemit_uncertain` con Message ID, usuario
humano activo del tenant, motivo y nueva clave de idempotencia. Requiere permisos
send/claim; crea otro Message enlazado, toma ownership y respeta la ventana 24 h
al dispatch. Reusar la misma clave recupera ese nuevo Message. Explicar al operador
que puede duplicar un envío previamente aceptado; no resetear el original.

### Rollback operacional

Pausar sender y planner si corresponde, conservar API/Inbox/lector compatible,
preservar claims, epochs, tokens, provider IDs y todas las fechas/estados. Revisar
UNCERTAIN y permitir reconciliación por webhook válido. Mantener B0. No ejecutar
la reversión de esquema de 0013 en producción ni volver a un sender que ignore B4.
No convertir UNCERTAIN/SENDING a PENDING, no degradar SENT/DELIVERED/READ y no
borrar evidencia para permitir replay. Si no hay lector anterior compatible,
mantener la imagen B4 con sender detenido mientras se corrige.

### Evidencia técnica B4

Corpus requerido `test_b4_sender`, `test_b4_processes`, `test_b4_command`,
`channels.test_b4_transport`, `channels.test_b4_webhook` y `test_b4_migration`;
CriticalB4Runner rechaza ejecución incompleta/skips/xfail. Los procesos reales
prueban dos senders, kill tras claim/aceptación y takeover antes/durante HTTP;
la barrera HTTP permite confirmar otra transacción antes de continuar.
La prueba de migración usa solo DB `test_*` con modelos históricos; no es una
instrucción de rollback productivo. Resultados exactos en el [acta B4](../implementacion-b4-agente-whatsapp-2026-09-16.md).
