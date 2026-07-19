# Épicas de implementación — Agente WhatsApp

**Rol**: registro de planes de implementación por épica (protocolo Tech Lead: impacto → plan incremental → migraciones → riesgos → pruebas → **aprobación** → código).
**Contrato**: [`whatsapp-agent-functional-spec.md`](whatsapp-agent-functional-spec.md) (congelada F1) + [`whatsapp-agent-implementation-plan.md`](whatsapp-agent-implementation-plan.md) (diseño v1.1, clasificación A/B/C/D).
**Regla**: ningún cambio de arquitectura sin RFC aprobado. Cada épica se planifica aquí ANTES de escribir código y espera aprobación explícita.

## Registro de épicas

| Épica | Alcance | Estado | Depende de |
|---|---|---|---|
| **É0** | Fundaciones core: PR-0 fotografía + fix RBAC `vaccinerecord` (PR-1) + identidad del agente (PR-2) | **✅ COMPLETADA 2026-07-16** — PR-0 (a960e07..997c796), PR-1 (13115af), PR-2 (886fbd6); CI verde en los tres. Pendiente solo el deploy a prod | — |
| É-F0 | Buzón operable: apps `channels`+`agent`, webhook, worker, outbox, plantillas tier-0, bandeja `/inbox` | **CÓDIGO COMPLETO 2026-07-17** — PR-3 (9c253f5) · PR-4 (eb24a83) · PR-5 (90f17ad) · PR-6 (ab2b4d3) · PR-7 (61925dc) · PR-8 (infra+runbooks). CI verde en todos. **Gate pendiente: smoke E2E con sandbox de Meta** (runbook agent-whatsapp.md §2) — requiere credenciales Meta (usuario) + deploy | É0 + número Meta (A0-1, lado usuario) |
| É-F1 | Agente read-only: LLM, Policy Engine, FSM, Tool Executor (incluye minting + throttle scope diferidos de A0-2), tools T1–T8+T15 | **CÓDIGO COMPLETO 2026-07-18** — PR-9 (f3e4f83) · PR-10 (f8c1c0c) · PR-11 (ef14ca0) · PR-12 (fb16a6e) · PR-13 (suite regresión + eval). CI verde en todos. Proveedor LLM = elección abierta del PO (adaptador OpenAI-compatible por env). **Gates pendientes: eval nightly ≥95 % (requiere key LLM) + Gate F1 §10 con clínica piloto (requiere consulta legal A1-1)** | É0, É-F0, consulta legal A1-1 |
| É-F2 | Escritura de agenda: A2-1 idempotencia + T9–T14 + tier-2 + P1 de la revisión UX | **Plan presentado 2026-07-19 — PENDIENTE DE APROBACIÓN** | É-F1 (validado en piloto) |

Pendientes del lado del usuario (ruta crítica, sin código): **A0-1** trámites Meta (número/WABA) · **A1-1** consulta legal (Q2/Q3/Q9).

---

## É0 — Fundaciones core

**Fecha del plan**: 2026-07-15 · **v2 tras revisión del PO** (mismo día) · **Estado**: pendiente de aprobación · **Estimación**: PR-0 0.5 h + PR-1 0.5 día + PR-2 1.5–2 días.

> **Cambios v2** (respuesta a los 5 puntos de la revisión — decisiones formalizadas en [ADR p51](decisions/2026-07-15-p51-virtual-agent-identity.md)):
> 1. **AGENT ya no es solo un rol**: se añade `User.is_service_account` (eje "clase de principal") + `role='AGENT'` (eje "conjunto de permisos"). Las exclusiones de superficies humanas (StaffList/deactivate/reset) discriminan por **flag**, no por nombre de rol → N agentes futuros no requieren tocar esas superficies. Justificación completa y alternativas en el ADR.
> 2. **Cadena de auditoría comprometida** para É-F1: `ToolExecution` incorpora `domain_object_public_id` (indexado) + `request_id` → dado un objeto de dominio se reconstruye Actor → Conversation → Mensaje → Tool → LLM Run. Sin FKs desde el dominio hacia `agent` (boundary intacto).
> 3. **`ensure_agent_users`** (mgmt command idempotente): garantiza el estado deseado de la cuenta por org (recrea si la borraron por shell, reactiva si la desactivaron). Se suma a PR-2.
> 4. **Test de evolución de permisos**: parchear `PERMISSIONS["AGENT"]` en test + re-seed → el `Role` en DB refleja el cambio (ancla el mecanismo con el que F2 añadirá `appointment.create/update` sin código nuevo).
> 5. **PR-0 (infraestructura, sin código)**: fotografía del estado antes de tocar RBAC.

### 1. Impacto sobre el código existente (verificado archivo por archivo)

| Archivo | Cambio | Evidencia |
|---|---|---|
| `apps/core/permissions_codes.py` | +4 códigos `vaccinerecord.list/retrieve/create/update` en `PERMISSION_CODES`; asignación en `PERMISSIONS`: VET (los 4), ASSISTANT (`list`, `retrieve`); + entrada `"AGENT"` con 12 permisos de lectura F1 | Las views ya exigen `vaccinerecord.<action>` (`medical_records/views.py:561,594`) — solo falta el catálogo |
| `apps/users/models.py:10-15` | `ROLE_CHOICES` += `('AGENT', 'Agente virtual')` | — |
| `apps/users/views.py:82-85` | `StaffListView`: excluir también `AGENT` (hoy solo excluye `ADMIN_SAAS`) — no debe aparecer en la UI de Equipo | Verificado en código |
| `apps/users/views.py:114+` (deactivate) y `:197+` (reset-password) | Excluir target `AGENT` (404-as-403, mismo patrón que la exclusión de ADMIN_SAAS) | **Footgun real**: un reset sobre el user agente pondría `password_must_change=True` → el gate embebido en `HybridPermission` (`core/permissions.py:367`) mataría TODAS sus tools |
| `apps/users/services.py` | Nueva `create_agent_user(organization)`: `set_unusable_password()`, `email=''` (el constraint parcial ADR p48 permite cuentas técnicas sin correo — patrón documentado en `users/models.py:54-58`), `role='AGENT'` | El signal `assign_rbac_role_on_create` (`users/signals.py:10`) asigna el `UserRole` automáticamente |

**Lo que NO se toca (hallazgos que redujeron el riesgo del plan original):**

- **`core/permissions.py`: CERO cambios.** El legal gate ya excluye roles sin mapping: `REQUIRED_DOC_TYPES_BY_ROLE` no tiene clave `AGENT` → `required_doc_types()` devuelve `()` → `legal_acceptance_required()=False` (`apps/legal/services.py:20-29,53-55`). El must-change gate tampoco aplica (el agente se crea con `password_must_change=False`). El plan de implementación estimaba este archivo como el de mayor blast-radius del proyecto — **no hace falta abrirlo**.
- **`CreateEmployeeSerializer`: cero cambios** — su `ChoiceField(choices=['ADMIN','VET','ASSISTANT'])` (`users/serializers.py:69-72`) ya impide crear usuarios AGENT vía API. Solo se agrega test que ancle esa lista.
- **Propagación automática verificada**: `seed_permissions` (deploy/Procfile; `core/management/commands/seed_permissions.py:42-79`) y `_seed_roles_for_org` (`organizations/signals.py:40-69`, orgs nuevas) iteran `PERMISSIONS` dinámicamente → el rol AGENT se siembra solo en todas las orgs, **sin migración de datos**.
- `VALID_ROLES` (`users/views.py:28`, filtro `?role=` del staff list) se queda como está: AGENT no filtrable.

**Permisos del rol AGENT (menor privilegio, solo lecturas F1):**
`appointment.list/retrieve` · `patient.list/retrieve` · `owner.list/retrieve` · `vaccinerecord.list/retrieve` · `service.list/retrieve` · `inventory.list/retrieve` (12). Los de escritura (`appointment.create/update`) se añaden en É-F2, no antes.

**Desviación de secuencia vs plan (no de arquitectura, sin RFC):** el minting de tokens y el throttle scope de A0-2 se difieren a É-F1 (B15 Tool Executor) — hoy no tienen consumidor = código muerto. Es reordenamiento; el contrato no cambia.

### 2. Plan incremental

- **PR-0 — fotografía del estado (sin código, ~30 min)**: checklist antes de tocar RBAC:
  - [ ] Rama limpia desde `develop`; `git status` sin restos (nota: hay 5 docs `whatsapp-agent-*` + ADR p51 sin commitear — commitearlos primero como cambio de docs independiente).
  - [ ] `makemigrations --check --dry-run` limpio (cero migraciones pendientes no generadas).
  - [ ] Suite backend completa verde + tiempo de corrida anotado (baseline).
  - [ ] Conteo actual de roles por org en producción (query de verificación: 3 system roles/org) y confirmación de que el cron de `seed_permissions` corre en deploy (Procfile).
  - [ ] Backup nightly más reciente verificado fresco (< 24 h, ADR p40) antes del deploy que toque RBAC.
  - [ ] Plan de rollback anotado: revertir commit + re-deploy re-ejecuta `seed_permissions` (el `permissions.set()` del seed sobreescribe → el rollback de permisos es el mismo mecanismo que el rollforward); la migración de `users` es aditiva/no-op y reversible.
- **PR-1 — fix `vaccinerecord`** (0.5 día): catálogo + asignaciones VET/ASSISTANT + tests. Independiente y deployable de inmediato — **corrige bug de producción hoy**: VET/ASSISTANT con `UserRole` en DB reciben `RBAC_DENIED` en `GET /api/vaccines/` (solo ADMIN pasa vía `*.*`); la ficha de mascota post-ADR p50 llama ese endpoint.
- **PR-2 — identidad del agente (ADR p51)** (1.5–2 días): `is_service_account` + choice `AGENT` + migración + entrada `PERMISSIONS["AGENT"]` + guards por flag en staff views + `create_agent_user` + `ensure_agent_users` (command idempotente) + tests (incluido el de evolución de permisos). Depende de PR-1 (los códigos `vaccinerecord` deben existir para asignárselos a AGENT).

### 3. Migraciones

Una sola migración en `users` con dos operaciones:
- `AlterField(role.choices)` — **no-op a nivel Postgres** (Django no materializa choices en DB).
- `AddField(is_service_account, BooleanField(default=False))` — aditiva, default estático (en Postgres moderno es metadata-only, sin rewrite de tabla), cero datos tocados, reversible trivial.

Sin migraciones de datos (Permission/Role los puebla el seed existente en deploy; usuarios existentes quedan `is_service_account=False` por default — semántica correcta: todos son personas).

### 4. Riesgos

| Riesgo | Nivel | Mitigación |
|---|---|---|
| Tests existentes que asuman 3 roles por org (helpers como `_seed_roles` en `organizations/tests/test_views.py:25-35` iteran `PERMISSIONS` → conteos de roles cambian a 4) | Medio | Correr suite completa tras PR-2; ajustar asserts de conteo si truenan (esperado, no señal de bug) |
| User AGENT visible en superficies no auditadas (dropdowns de veterinario del frontend) | Bajo | El frontend obtiene vets con `?role=VET` → AGENT no aparece; test de integración lo ancla |
| Asignación de permisos a AGENT demasiado amplia | Bajo | Test espejo de la lista negativa: AGENT NO tiene `invoice.*`, `medicalrecord.*`, `cashsession.*`, `cashmovement.*`, `staff.*`, `import.*`, `prescription.*`, `appointment.create/update/destroy` |
| `is_active` del agente como kill switch accidental (staff no podría reactivarlo desde la UI) | Bajo | Deactivate excluye AGENT; el kill switch real es `AgentSettings.enabled` (llega en É-F0); interim: shell |

### 5. Pruebas

**Unitarias**
- Meta-test de consistencia del catálogo: todo código en `PERMISSIONS` ⊆ `PERMISSION_CODES ∪ {"*.*"}` — **hoy no existe y habría atrapado el bug de vaccinerecord** (queda como guard permanente).
- `create_agent_user`: password inusable, org correcta, `role='AGENT'`, `is_service_account=True`, `UserRole` creado por el signal, email vacío válido (constraint parcial), idempotencia (segunda llamada no duplica).
- `ensure_agent_users`: idempotente en N corridas; recrea si la cuenta fue borrada; reactiva si `is_active=False`; no toca cuentas humanas.
- **Evolución de permisos** (punto 4 de la revisión): parchear `PERMISSIONS["AGENT"]` con un permiso extra + re-ejecutar seed → `Role.permissions` en DB refleja el cambio (ancla el mecanismo de F2).

**Integración**
- VET y ASSISTANT con rol DB acceden a `GET /api/vaccines/` (antes 403); ASSISTANT no puede POST; VET sí.
- AGENT autenticado: lee citas/mascotas/dueños/vacunas/servicios/productos de SU org; 403 en toda escritura, todo billing, todo staff; 404 en recursos de otra org (no-regresión tenant).
- Gates: AGENT con documentos legales vigentes NO bloqueado; un ASSISTANT sin aceptar SIGUE bloqueado (no-regresión del gate p46).
- `CreateEmployeeSerializer` rechaza `role=AGENT` (400).
- `StaffListView` no incluye service accounts (por flag, no por rol); deactivate y reset-password sobre service account → 404.
- Org nueva → signal siembra el rol AGENT (roles de sistema = 4).

**Regresión**
- Suite backend completa (la ejecuta el usuario — convención del proyecto).
- Tests de vaccines existentes sin `RBAC_DENIED` residual.

### 6. Aprobación y ejecución

- [x] Aprobado por el Product Owner — 2026-07-15 ("Implementa PR-0 y, una vez validado, continúa con PR-1"; PR-2 conforme al plan v2 + ADR p51).
- [x] **PR-0 ejecutado** — hallazgos mayores: (1) el CI backend corría `Found 0 test(s)` desde siempre (`apps/` sin `__init__.py`) — gate ilusorio; (2) importador XLSX roto en prod (`openpyxl` ausente del lock que instala el Dockerfile) — corregido (`4f9203d`); (3) frontend CI rojo 2 días (`VITE_API_URL`) — corregido (`850a086`); (4) housekeeping: inits + borrado de `apps/pets/` y `serealizers.py` (`e73fa94`); (5) baselines de los audits dual-exposure/tenant-scoping actualizados con revisión ítem por ítem (`997c796`). Resultado: 946 tests despertados en CI, verde completo. Baseline prod: 3 orgs × 3 roles; backup nightly validado offsite.
- [x] **PR-1 ejecutado** (`13115af`, CI verde) — códigos `vaccinerecord.*` + guard AST views→catálogo (`test_permissions_catalog`, con anti-vacuidad) + regresión `test_vaccines_rbac` (roles sembrados desde el catálogo real).
- [x] **PR-2 ejecutado** (`886fbd6`) — `is_service_account` + rol AGENT + guards por flag + `ensure_agent_user(s)` + 15 tests; verificación local de área (users/organizations/core completos) verde. CI: en curso al cierre de esta entrada.
- **Pendiente de deploy a prod**: todo lo anterior llega con el próximo deploy (release.sh corre migrate + seed_permissions). El fix de openpyxl viaja en el mismo deploy.

---

## É-F0 — Buzón operable (channels + worker + bandeja)

**Fecha del plan**: 2026-07-16 · **Estado**: PENDIENTE DE APROBACIÓN · **Estimación**: ~2–2.5 semanas (6 PRs) · **Contrato**: diseño v1.1 (plan §B-F0) + spec congelada (INT-00..06 tier-0).

**Valor entregado al cierre**: la clínica atiende WhatsApp desde el SaaS (bandeja `/inbox`), con saludo/fuera-de-horario automáticos, todo auditado y sin teléfono personal de por medio. Sin LLM todavía.

### 1. Impacto sobre el código existente

É-F0 es **greenfield casi puro** — dos apps nuevas, hoja del grafo de dependencias. Puntos de contacto con lo existente (todos aditivos):

| Superficie | Cambio |
|---|---|
| `config/settings.py` | +2 `INSTALLED_APPS` (`apps.channels`, `apps.agent`); env vars del proveedor (`WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` — vía decouple, valores en `.env.prod`) |
| `config/urls.py` | Namespace **`/hooks/whatsapp/`** fuera de `/api/` (público, autentica por firma HMAC del proveedor, no por JWT — no hereda `DEFAULT_PERMISSION_CLASSES`) |
| `apps/core/permissions_codes.py` | +4 códigos `agentinbox.view/claim/send/config` (Q13). Seed: ADMIN `*.*`; ASSISTANT view/claim/send; VET view. El guard AST de PR-1 valida el alta |
| `docker-compose.prod.yml` + `scripts/deploy.sh` | +1 servicio `worker` (mismo image tag que backend, comando `manage.py run_agent_worker`, `restart: always`) — **cambio de infra: va por repo + deploy.sh** (regla dura del runbook, jamás a mano) |
| Frontend | Página nueva `/inbox` + `api/inbox.js` + ruta privada. Cero cambios a páginas existentes |
| Runbooks | `cron-jobs.md` (+deadman del worker), `deploy.md` (+servicio), runbook nuevo del subsistema |

**Nada de dominio se toca**: ni appointments, ni patients, ni billing. Ningún módulo existente importa `agent`/`channels`.

### 2. Plan incremental (PRs)

| PR | Contenido | Est. |
|---|---|---|
| **PR-3 — esqueleto + modelos** | Apps `channels`+`agent`; modelos v1.1: `ChannelAccount`, `Message` (unificada, dedup wamid con unique parcial `WHERE direction='in'`), `ContactIdentity`, `Conversation` (con `flow`/`summary` embebidos, FSM 4 estados), `AgentSettings` (4 campos, `enabled=False` default); migraciones; provisioning command (`provision_channel --org` que además llama `ensure_agent_users`) | 2d |
| **PR-4 — webhook entrante** | `GET /hooks/whatsapp/` (handshake `hub.challenge` de Meta) + `POST` (verificación firma `X-Hub-Signature-256` HMAC-SHA256 constant-time, resolución número→`ChannelAccount`→org, dedup, persistencia, ACK <1s); normalización telefónica (Q5, función pura); resolución `ContactIdentity`→Owner (0/1/N) | 2d |
| **PR-5 — worker + outbox** | Command `run_agent_worker`: loop `FOR UPDATE SKIP LOCKED` sobre conversaciones con `Message` pending (FIFO por conversación, drain-on-pickup); sender outbox con reintentos exponenciales + ventana 24h; adaptador Meta Cloud API (interfaz + implementación real + stub para tests); plantillas tier-0 F0 (T0-GREET, T0-DISABLED, fuera-de-horario) | 3d |
| **PR-6 — bandeja API** | Endpoints org-scoped: listar conversaciones (estado, no-leídos), transcript, responder como humano (→outbox), claim, cerrar; permisos `agentinbox.*`; `AgentSettings` GET/PATCH (kill switch) | 2d |
| **PR-7 — bandeja frontend** | `/inbox`: lista + transcript + composer + claim + toggle de agente; polling 30s (patrón `useDashboardSummary`); glosario es-MX | 3–4d |
| **PR-8 — ops** | Servicio worker en compose + deploy.sh; deadman Healthchecks.io; logger `agent.events`; runbook del subsistema; smoke E2E contra sandbox de Meta | 1–1.5d |

Cada PR con tests verdes en CI antes del siguiente. E2E real (mensaje de WhatsApp → bandeja → respuesta) al cierre de PR-8 con el **sandbox** de Meta.

### 3. Migraciones

Todas **aditivas** (tablas nuevas, cero ALTER a tablas existentes): `channels_channelaccount`, `channels_message`, `agent_contactidentity`, `agent_conversation`, `agent_agentsettings`. Índices según diseño v1.1 §8 (unique parcial wamid; `(organization, state, -last_activity_at)`; unique `(organization, channel_type, external_id)`). Sin migración de datos. Rollback = reverse trivial (drop de tablas sin FKs entrantes desde dominio).

### 4. Riesgos

| Riesgo | Mitigación |
|---|---|
| Endpoint público nuevo (`/hooks/`) | Firma HMAC obligatoria (rechazo 403 constant-time), sin firma válida no se persiste NADA; throttle por IP; sin datos en la respuesta |
| Enrutamiento número→org equivocado (R1, el crítico) | `external_account_id` unique global + test de regresión de enrutamiento + org fijada al crear la conversación (jamás re-derivada) |
| Worker degrada el VPS | Servicio I/O-bound, `restart: always`, deadman; medición de RAM en PR-8 antes de cerrar |
| PII nueva en DB (mensajes) | Cubierta por backup nightly existente (ADR p40); cuerpos jamás en logs/Sentry (regla R15, test de no-logging) |
| Compose/deploy drift | Cambio de infra solo por repo + `deploy.sh` (regla dura runbook) |
| Demo org | `AgentSettings.enabled=False` default; sin `ChannelAccount` para la demo (Q15) |
| Credenciales Meta | Solo en `.env.prod` (regla dura 2); `ChannelAccount.provider_credentials_ref` guarda el NOMBRE de la env var, nunca el secreto |

### 5. Pruebas

- **Unit**: normalización telefónica (tabla de casos: 521/52/13/12 dígitos, no-normalizable); firma HMAC (válida/ inválida/ausente); selección de plantilla tier-0 (dentro/fuera de horario vs `business_hours` con tz de la org); FSM (transiciones válidas/ inválidas); ventana 24h del sender.
- **Integración**: webhook POST→`Message` persistido→conversación creada; **dedup** (mismo wamid ×3 → 1 fila); resolución de identidad (0/1/N owners); worker drena pending en orden FIFO por conversación; outbox reintenta con backoff (stub del proveedor que falla N veces); bandeja: RBAC `agentinbox.*` (ASSISTANT puede, rol sin permiso 403), responder como humano crea `Message` out + entrega vía stub; kill switch (enabled=False → T0-DISABLED).
- **Regresión**: suite completa en CI (ya real, 946+); guard AST de catálogo cubre los códigos nuevos; casos de la spec cubiertos en F0: `TC-INT00-01/02/03`, `TC-INT03-01/02`, dedup (base de `TC-*`), `TC-GB-07` (reinicio del worker a mitad de conversación — estado persiste).
- **E2E manual** (gate de cierre): sandbox Meta → mensaje real → aparece en bandeja → respuesta desde bandeja → llega al WhatsApp del tester.

### 6. Prerrequisitos del lado del usuario

- [ ] **Deploy de É0 a prod** (`bash scripts/deploy.sh`) — antes de PR-8 (el worker se despliega encima).
- [ ] **App de WhatsApp en Meta for Developers** (sandbox: número de prueba + `APP_SECRET` + `VERIFY_TOKEN` + token de acceso) — necesaria desde PR-4 para pruebas reales; el código avanza con stubs sin ella. ~15 min.
- [ ] Verificación de negocio en Business Manager (número real) — en paralelo, sin prisa; gate del piloto F1, no de F0.

### 7. Aprobación

- [x] É-F0 aprobada (PR-3..PR-8) — Product Owner, 2026-07-16

---

## É-F1 — Agente read-only (LLM + Policy Engine + tools de lectura)

**Fecha del plan**: 2026-07-17 · **Estado**: PENDIENTE DE APROBACIÓN · **Estimación**: ~3 semanas (5 PRs; el colchón vive en PR-13/eval, único tramo sin precedente interno) · **Contrato**: spec funcional **congelada** F1 (INT-00..14 + reglas §2 + 63 casos) + plan v1.1 §B-F1.

**Valor al cierre**: el agente responde solo el ~70 % del tráfico real de recepción — "¿cuándo es mi cita?", "¿qué vacunas le tocan?", "¿cuánto cuesta X?", "¿a qué hora abren?" — con escalado a humano impecable. Escritura: cero (llega en É-F2).

### 1. Impacto sobre el código existente

| Superficie | Cambio |
|---|---|
| `backend/requirements.txt` / lock | **SIN dependencias nuevas** (corrección 2026-07-17: el proveedor LLM NO está decidido — asunción retirada). El adaptador habla la API **compatible con OpenAI** (`/chat/completions` + tool calling) con `requests` (ya en el lock): cubre DeepSeek, OpenAI, Groq, Together y self-hosted (vLLM/Ollama) con un solo cliente y `base_url` configurable. Anthropic, si algún día se eligiera, sería una segunda implementación del adaptador |
| `config/settings.py` | + `AGENT_LLM_BASE_URL`, `AGENT_LLM_API_KEY`, `AGENT_LLM_MODEL_PLANNER`, `AGENT_LLM_MODEL_ROUTER` (proveedor y modelos = pura configuración por env, cero código por proveedor), `AGENT_INTERNAL_API_URL` (loopback del worker al backend: `http://backend:8000` en compose), presupuestos (constantes globales v1: 15 turnos LLM/conversación, 5 tools/turno — spec §2.6) |
| `apps/core/throttling.py` | + throttle de usuario **service-account-aware**: el `UserRateThrottle` global (500/h) exime `is_service_account` (el límite real del agente es el presupuesto del Policy Engine, no el throttle HTTP — riesgo R9 del doc de arquitectura). Cambio pequeño con tests de no-regresión (humanos siguen throttleados) |
| `apps/agent/` | Todo lo nuevo vive aquí: `policy.py`, `executor.py`, `planner.py`, `llm.py`, `tools/`, `identity.py` + modelos `ToolExecution`/`LLMCall`/`HumanHandoff` |
| Bandeja (frontend) | Retoque mínimo: chip con `handoff_reason` en conversaciones "Esperando" (la columna ya existe visualmente) |
| Dominios | **CERO cambios** — las tools leen la API existente vía loopback |
| `.env.prod.example` | + sección LLM (key + modelos + presupuestos) |

**Decisiones ya tomadas que este plan solo ejecuta** (no se reabren): loopback HTTP con JWT del user AGENT acuñado server-side (`RefreshToken.for_user`, TTL corto, jamás logueado — diferido de A0-2 exactamente para este momento); handles efímeros con validación server-side de ownership como control primario; plantillas/parafraseos por copy fijo, jamás generados; minimización de proyecciones por tool (R4).

### 2. Plan incremental (PRs)

| PR | Contenido | Est. |
|---|---|---|
| **PR-9 — modelos + adaptador LLM** | `ToolExecution` (append-only: tool, `args_redacted`, `policy_tier/decision`, `http_status`, `duration_ms`, **`domain_object_public_id` indexado + `request_id`** — cadena de auditoría ADR p51), `LLMCall` (append-only: provider, model_id, tokens in/out, costo estimado, latencia, `prompt_version` string, retry_of), `HumanHandoff` (reason_code/priority/claimed/resolved), `Conversation.total_llm_calls`; migraciones aditivas; `llm.py` (interfaz `complete()` + cliente OpenAI-compatible con `requests` — proveedor por env — + stub determinista para tests); sin deps nuevas | 2d |
| **PR-10 — Tool Executor + tools de lectura** | Minting JWT interno + loopback con timeout + mapeo de errores DRF→eventos conversacionales (§2.5 de la spec) + registro `ToolExecution`; throttle service-account-aware; registry de tools + T2 (mis mascotas), T3 (vacunas), T5 (info clínica — local, lee AgentSettings), T6 (precios), T7 (disponibilidad producto, sí/no), T8 (mis citas) con **proyecciones mínimas** definidas en la spec §9; resolver de handles (refs en `flow`) | 3d |
| **PR-11 — Policy Engine + FSM + identidad** | Reglas pre-planner en el orden EXACTO del router §3 de la spec (urgencia primero — keywords es-MX, plantilla T0-EMERGENCY + handoff urgent; humano; opt-out; bot-question INT-06; confirmación two-stage UX-02 con falsas afirmativas; saludo; fuera-de-alcance INT-05); presupuestos y anti-flood §2.6; transiciones FSM en services + cierre por inactividad 24h (pasada periódica del worker); **verificación de identidad**: T1 + verificación implícita (mascota nombrada = reto pasado) + reto explícito tolerante UX-03 (normalización, typo distancia 1, repetición sin costo, 2º factor titular, 2 fallos reales → E-06) + caducidad 6 meses; aviso de privacidad just-in-time (T0-PRIVACY, UX-01) | 3–4d |
| **PR-12 — Planner + handoff end-to-end** | Ensamblado de contexto (§10: system prompt versionado + estado FSM + resumen + últimos K mensajes + resultados de tools del turno — datos SIEMPRE delimitados como datos, G6); el worker reemplaza su rama F0: `enabled=True` → pipeline policy→planner→executor (con `enabled=False` T0-DISABLED intacto); `HumanHandoff` reemplaza el claim-lite en los triggers E-01..E-10; chip de motivo en bandeja; presupuesto → degradación a plantilla + handoff | 3d |
| **PR-13 — suite conversacional + eval** | Los **63 casos F1 congelados** (spec §9.4: 21 tier-0 + 23 lecturas + 6 UX P0 + 8 seguridad + 5 bordes) como tests CI contra el **stub determinista** (bloqueantes: policy/FSM/tools/guards) + fixture trampa cross-tenant §9.2 + aserciones prohibidas globales (UUID/PK/stock/consejo médico/jerga); script de **eval nightly con LLM real** (no bloqueante, reporta % pass — gate del piloto: ≥95 % en 5 corridas); hardening de prompt con los hallazgos; runbook actualizado | 4–5d |

Gate de salida de la épica = **Gate F1 de la spec §10** (los 5 criterios, incluido kill switch probado y latencia P50 < 15 s / urgencias < 10 s).

### 3. Migraciones

Todas aditivas en `agent`: 3 tablas nuevas (`ToolExecution`, `LLMCall`, `HumanHandoff`) + `AddField Conversation.total_llm_calls` (default 0, metadata-only). Cero cambios a tablas de dominio. Rollback trivial.

### 4. Riesgos

| Riesgo | Mitigación |
|---|---|
| Prompt injection (R3, directa y 2º orden) | Ya diseñada: policy post-planner valida tool/tier/args/ownership FUERA del LLM; afirmativa jamás amplía el parafraseo (TC-SEC-03 bloqueante absoluto); datos delimitados como datos (G6); 8 casos adversariales en CI |
| Fuga PII al proveedor (R4) | Proyecciones mínimas por tool (contrato §9) — la mitigación de fondo es la MISMA con cualquier proveedor: nada financiero ni expediente en contexto. **Gate: antes del piloto, revisar los términos de datos (retención/training) del proveedor QUE TÚ elijas y registrar la decisión** (la sustancia de Q3 sigue viva; el proveedor es tu elección) |
| Costo fuera de control (R11) | Presupuestos duros (15 turnos/conv) + tier-0 resuelve 40-60 % sin LLM + router en Haiku + kill switch por org + `LLMCall` contabiliza todo desde el día 1 |
| Latencia (O5: P50 < 15 s) | Router barato primero; tools en paralelo no (secuencial simple v1); medición en `LLMCall.latency_ms` desde el arranque |
| JWT del agente | TTL corto acuñado por request, solo en memoria del worker, jamás en logs (gate `noConsoleTokenLeak` equivalente backend: test de que el token no aparece en `ToolExecution.args_redacted` ni logs) |
| Estimación de PR-13 (sin precedente interno) | Colchón explícito; los 63 casos ya están ESPECIFICADOS (fixtures+aserciones definidas en la spec) — es transcripción disciplinada, no diseño |
| Eval nightly flaky | No bloqueante por diseño (§9.1 de la spec); el CI bloqueante es el stub determinista |

### 5. Pruebas

- **Unitarias**: matcher de confirmación es-MX (tabla completa UX-02 incl. falsas afirmativas), detector de urgencia, normalización/reto de identidad (UX-03 tabla), presupuestos, ensamblado de contexto (aserción: jamás PKs, datos delimitados), redacción de `args_redacted`.
- **Integración**: executor end-to-end contra la API real en test (minting + loopback + ToolExecution persistido con `domain_object_public_id`); cada tool con su proyección exacta; throttle: AGENT exento / humano throttleado; FSM completa; handoff crea registro + estado + visible en bandeja.
- **Regresión conversacional**: los 63 casos como suite CI (stub) — **este es el entregable central de la épica**; suite completa del proyecto verde.
- **Manual/piloto**: eval nightly ≥95 % × 5 corridas + Gate F1 §10 con la clínica piloto.

### 6. Prerrequisitos del lado del usuario

- [ ] **Elegir proveedor LLM** (tu decisión — DeepSeek/OpenAI/Groq/otro con API OpenAI-compatible) + su API key → `AGENT_LLM_BASE_URL` / `AGENT_LLM_API_KEY` / modelos en `.env.prod`. Revisar sus términos de retención/training antes del piloto (sustancia de Q3). Sin key: PR-9..12 avanzan completos con el stub; solo el eval nightly y el piloto la esperan.
- [ ] Smoke E2E de É-F0 (recomendado ANTES de encender F1 — valida el transporte real).
- [ ] Consulta legal A1-1 — **gate del piloto**, no del código.

### 7. Aprobación

- [x] É-F1 aprobada (PR-9..PR-13) — Product Owner, 2026-07-17 (con la corrección proveedor-agnóstico ya incorporada; proveedor LLM = elección abierta del PO, no bloquea PR-9..12)

---

## É-F2 — Escritura de agenda (agendar · confirmar · cancelar · reagendar)

**Fecha del plan**: 2026-07-19 · **Estado**: PENDIENTE DE APROBACIÓN · **Estimación**: ~2.5–3 semanas (6 PRs) · **Contrato**: spec funcional **congelada** F1 §6 (INT-20..24, 30 casos) + revisión UX P1 (UX-04/06/08/09/11) + decisiones §18 (Q11/Q12/Q14).

**Valor al cierre**: el agente **ES** la recepcionista 24/7 para la agenda — agenda citas de clientes existentes y nuevos, confirma, cancela y reagenda, todo con confirmación explícita y sin ensuciar la agenda real. Es la épica que convierte el asistente de "informativo" a "operativo".

> **Precondición de proceso (no negociable)**: no se arranca É-F2 hasta que É-F1 haya sido **validada en piloto real** (Gate F1 §10). Dar poder de *escritura* a un agente cuya *lectura* no se probó con clientes reales es apilar riesgo a ciegas. El smoke de É0/É-F1 en producción (2026-07-18) ya cazó 3 bugs de integración que ningún test unitario vio (Caddy `/hooks/`, número MX con `1` legacy, `cost_estimate` sin cuantizar) — la escritura merece el mismo filtro de realidad antes de construirse encima.

### 1. Impacto sobre el código existente

| Superficie | Cambio |
|---|---|
| `apps/appointments/` (dominio) | **A2-1 — idempotencia**: `POST /api/appointments/` y `POST /api/appointments/create-with-patient/` aceptan `X-Idempotency-Key` opcional; unique parcial `(organization, idempotency_key)`; replay devuelve la cita original. Calca de `_is_payment_replay` (ADR p27). **Mini-ADR de dominio** requerido (cambio de contrato de un endpoint existente). Beneficia también al frontend actual (doble-click). |
| `apps/appointments/serializers.py` | **Fix del guard de fecha-pasada en update** (hallazgo verificado): `validate` solo rechaza fecha pasada en creación (`if not instance and start_utc < now()`, línea 98). El reagendado (PATCH) **puede mover una cita al pasado**. Se cierra en el dominio (un `if`) — beneficia a staff y agente por igual. El solape SÍ se revalida en update excluyéndose (línea 109, Q11 resuelto: T14 = PATCH directo, no cancel+create). |
| `apps/agent/tools.py` | +6 tools de escritura (T9–T14). Reusan el executor loopback+JWT ya existente; el rol `AGENT` gana `appointment.create` y `appointment.update` (editar `PERMISSIONS["AGENT"]` — el mecanismo de evolución ya probado en É0-PR2). |
| `apps/agent/policy.py` | Flujo de confirmación tier-2 **activado** (en F1 quedó dormant): `pending_action` + parafraseo por plantilla + afirmativa ejecuta. La rama ya está cableada (spec §2.4); F2 la llena. |
| `apps/agent/models.py` (AgentSettings) | `scheduling_mode` (`fixed_vet` default \| `any_available`, Q14) + `default_veterinarian` FK opcional; campos de UX P1 (nudge on/off). Migración aditiva. |
| `apps/agent/identity.py` | **Vinculación familiar (UX-04)**: reto triple (titular + mascota + últimos 4 dígitos del teléfono registrado) → número no registrado se vincula como contacto secundario del Owner. Nuevo estado de reto en `flow`. |
| Frontend `/inbox` | Chip "handoff por identidad ambigua" + señalización del vínculo familiar nuevo (revocable). Retoque menor. |

**Dominios de negocio**: el único cambio es en `appointments` (idempotencia + fix de guard), ambos aditivos/correctivos y con beneficio propio más allá del agente. Cero cambios a billing/inventory/medical_records.

### 2. Plan incremental (PRs)

| PR | Contenido | Est. |
|---|---|---|
| **PR-14 — A2-1 idempotencia (dominio)** | Mini-ADR + campo `idempotency_key` en Appointment (unique parcial) + lectura de `X-Idempotency-Key` en las dos vistas de creación + replay devuelve la original + fix del guard de fecha-pasada en update. Tests de dominio (replay, doble-click, PATCH-al-pasado bloqueado). **Deployable solo** (mejora el frontend actual). | 2d |
| **PR-15 — tools de lectura de agenda** | T9 `find_available_slots` (compone ocupación real `GET /appointments/?date=&veterinarian=` ∩ `business_hours`; ≤3 slots; oferta proactiva UX-06). Permiso AGENT sin escritura aún. Tests contra API real. | 2–3d |
| **PR-16 — tools de escritura + confirmación tier-2** | T10 `create_appointment`, T12 `confirm_appointment`, T13 `cancel_appointment`, T14 `reschedule_appointment`; `pending_action` + parafraseo por plantilla (fecha absoluta G5) + ejecución solo con afirmativa (TC-SEC-03 invariante); guard de fecha futura en Policy (reagendado); `scheduling_mode`; idempotency key por acción; **vigencia de oferta explícita (P4) + anotación de auditoría en `reason` (P5)**. | 3–4d |
| **PR-17 — alta de cliente nuevo + vinculación familiar** | T11 `register_new_client_and_pet` (`create-with-patient` atómico + tamiz UX-05); vinculación familiar UX-04 (reto triple → contacto secundario, revocable en bandeja) **+ instrumentación del desenlace (P3)**; conflicto de identidad (número con registro previo → nunca escritura automática, E-05); anotación de auditoría en `reason` (P5). | 3d |
| **PR-18 — proactividad de flujo (UX P1)** | Nudge único de flujo abandonado (UX-08, 1 por conversación, dentro de ventana 24h, jamás tras opt-out); post-agendado con dirección/indicaciones (UX-09); retención con horarios concretos al cancelar (UX-11). | 2d |
| **PR-19 — suite de escritura + métricas de negocio + eval** | Los **30 casos F2 congelados** (spec §9.4: INT-20..24 + TC-UX-05) como tests CI contra el stub (bloqueantes; TC-INT20-06 confirmación vencida y TC-SEC-03 afirmativa-con-extra = bloqueantes absolutos) + fixture trampa cross-tenant sobre escritura + **métricas de negocio (`GET /api/inbox/metrics/` + tile en `/inbox`, §8)** + escenarios de escritura en el eval nightly. | 4–5d |

Gate de salida = **Gate F2 de la spec §10**: A2-1 desplegado, los 30 casos verdes, toda cita creada/cancelada/movida auditada con actor AGENT en `AppointmentStatusChange`, y **2 semanas de piloto con < 1 % de citas erróneas/duplicadas** (medido contra la agenda real).

### 3. Migraciones

- `appointments`: `AddField idempotency_key` (nullable) + `AddConstraint` unique parcial. Aditiva; sin migración de datos.
- `agent`: `AddField scheduling_mode` (default `fixed_vet`) + `default_veterinarian` FK nullable + flag de nudge. Aditiva.
- `ContactIdentity`: sin campo nuevo — el vínculo secundario reusa la FK `owner` existente + un flag; el estado del reto vive en `Conversation.flow`.

Rollback trivial en todas.

### 4. Riesgos

| Riesgo | Mitigación |
|---|---|
| **Doble cita por reintento** (R5/R6, el crítico de escritura) | A2-1 idempotencia (PR-14, patrón Payment probado) + una sola tool mutadora en vuelo por conversación (serialización del worker, ya existe) |
| **TOCTOU de solape** (dos confirmaciones al mismo slot) | El dominio revalida solape bajo el serializer al crear; si dos ganan la carrera, el 2º recibe 400 → el agente se disculpa y re-oferta (compensación, spec INT-20 B5). **No** se toca el orden global de locks (ADR p12) desde el subsistema |
| **Afirmativa que amplía el alcance** (TC-SEC-03) | La afirmativa ejecuta SOLO el `pending_action` parafraseado, jamás lo que el mensaje agregue. Clasificador conservador (ya probado en É-F1) + test bloqueante absoluto |
| **Vinculación familiar → acceso indebido** (UX-04) | Reto triple (titular + mascota + últimos 4 dígitos) — un conocido casual no los tiene los tres; vínculo señalado y revocable en bandeja; notificación al titular cuando existan plantillas (F3) |
| **Agenda ensuciada con datos basura** | Sanitización del dominio (ya aplica a `reason`/nombres); `pet_species` mapeada a lista cerrada; confirmación obligatoria antes de todo alta |
| **Reagendar al pasado** | Fix de dominio (PR-14) + guard redundante en Policy Engine |
| **Presupuesto/costo con escritura** | Sin cambio: el tope de turnos y el kill switch por org ya existen; la escritura no añade llamadas LLM extra por turno |

### 5. Pruebas

- **Unitarias (dominio)**: idempotencia (replay devuelve la misma cita; sin key = comportamiento actual), guard de fecha-pasada en update, solape en update excluyéndose.
- **Integración (agente)**: cada tool T9–T14 contra la API real con el JWT del AGENT (RBAC de escritura verificado end-to-end); flujo de confirmación completo (oferta→parafraseo→afirmativa→cita creada; negativa→cero escritura; vencida→re-parafraseo, jamás ejecuta); alta cliente nuevo atómica; vinculación familiar (reto triple ok/parcial→handoff); conflicto de identidad → cero escritura.
- **Regresión conversacional**: los 30 casos F2 como suite CI (stub) + fixture trampa cross-tenant sobre escritura; **este es el entregable central**. Suite completa del proyecto verde con los 4 guards de auditoría.
- **Piloto**: 2 semanas, < 1 % citas erróneas/duplicadas vs agenda real (Gate F2 §10).

### 6. Prerrequisitos

- [ ] **É-F1 validada en piloto** (Gate F1 §10) — precondición dura (ver arriba).
- [ ] Mini-ADR de A2-1 aprobado (cambio de contrato de un endpoint de dominio — gobernanza del proyecto).
- [ ] Datos reales de la clínica cargados (horario/dirección) para que la oferta de slots y el post-agendado tengan sustancia.

### 7. Revisión del PO (2026-07-19) — respuestas a 5 observaciones

**P1 — ¿Seis tools o una `AppointmentTool(action=...)`? → SE MANTIENEN SEPARADAS (con razón).**
No es preferencia estética: el **tool calling del LLM es más confiable con schemas acotados**. Una tool única con `action ∈ {create,cancel,reschedule,confirm}` obliga a que TODOS los parámetros sean opcionales (create necesita pet+fecha+hora+motivo; cancel necesita solo handle+motivo; reschedule necesita handle+nueva-fecha) → el modelo tiene que **elegir la combinación correcta de campos por acción**, y una combinación mal formada (cancelar con fecha, reagendar sin handle) se cuela. Con tools separadas, el **schema mismo** restringe qué es válido por acción — el modelo no puede alucinar una mezcla ilegal. Además el **tier de política mapea 1:1**: `confirm` es tier-1 (benigno), `create/cancel/reschedule` son tier-2 (parafraseo obligatorio); una tool única metería esa lógica de tiers ADENTRO, rompiendo la tabla de política. Consolidar es barato después si el piloto muestra que sobran; **partir una tool fusionada tras el hecho es caro** (el modelo ya aprendió el patrón fusionado). Regla del proyecto: una responsabilidad por tool.

**P2 — `register_new_client_and_pet` hace 3 cosas → NO se divide (razón de dominio).**
La tool NO mezcla tres dominios: **llama UN endpoint que el dominio construyó atómico a propósito** — `POST /api/appointments/create-with-patient/` (existe justo para crear Owner+Pet+Appointment en una transacción, sin huérfanos). Dividir la tool en `CreateOwner → CreatePet → CreateAppointment` reintroduciría exactamente el riesgo que ese endpoint elimina: owner creado y pet falla → owner huérfano; pet creado y cita falla → pet sin cita. Y obligaría al **agente a orquestar una transacción multi-paso con rollback**, que es precisamente lo que el plan v1.1 §6.7 prohíbe (la atomicidad multi-endpoint vive en el dominio como endpoint compuesto, no en el agente). La tool es delgada; la atomicidad ya está encapsulada. **Se mantiene.**

**P3 — Vinculación familiar (reto triple): la UX preocupa → SE INSTRUMENTA en el piloto.**
De acuerdo con la observación. Se mantiene el reto triple como **barrera de seguridad** (un vínculo permanente merece ese piso; la esposa que no sabe los 4 dígitos → handoff a humano, que ES la ruta correcta para vincular un número permanente). **Pero** se añade a PR-17 instrumentación explícita: cada intento de vínculo registra su desenlace (`linked | failed_digits | failed_other | abandoned`) en `HumanHandoff.reason_detail` + un contador. El **gate del piloto** incluye medir "% de handoffs cuyo único motivo es la validación de los 4 dígitos" — si duele, se relaja el factor (p.ej. mes de última visita en vez de 4 dígitos) con datos, no por intuición.

**P4 — Vigencia de la oferta de horarios: faltaba explícita → SE AGREGA a la spec.**
Correcto, el plan mencionaba el TOCTOU pero no la regla de vigencia. Enmienda a la spec §6 (INT-20), dos ventanas explícitas:
  - **Ventana de confirmación**: el `pending_action` con los slots ofrecidos vence a los **30 min** (spec §2.4). Un "sí" después de eso NO ejecuta → se re-parafrasea.
  - **Disponibilidad del slot**: **el sistema NO reserva horarios** (sin soft-hold — evita bloquear reservas reales y una tabla de reservas con expiración). La oferta es una **propuesta**; al confirmar se **revalida** y, si otro lo tomó, se compensa: *"ese horario se acaba de ocupar 😅"* + re-oferta (INT-20 B5). Trade-off aceptado a este volumen; trigger para añadir soft-hold = tasa de colisión medida > umbral en el piloto.
El texto de vigencia se agrega a la spec funcional como enmienda de F2 al kickoff de la épica.

**P5 — Auditoría: `decision_reason` + `conversation_id` + `tool_execution_id` → SE AGREGA, respetando el boundary.**
De acuerdo, sin tener que "reconstruir media base de datos". Dos capas, sin romper la regla de que el dominio NUNCA depende de `agent` (ADR p51):
  - **Migaja directa en el dominio**: al crear/cancelar/mover, el agente escribe en el campo **`AppointmentStatusChange.reason` (ya existe, texto libre, sin FK)** una anotación legible: `"Agente virtual · conv <public_id> · exec <tool_execution_id>"`. Quien mira el historial de la cita ve de inmediato **quién y de qué conversación** — cero joins.
  - **Traza profunda en el agente**: `ToolExecution` ya lleva `conversation_id`, `domain_object_public_id` (indexado), `request_id`, `args_redacted`, `policy_decision`. Dado el public_id de la cita se reconstruye Actor→Tool→Conversación→Mensaje→LLMCall.
La anotación es un **string** (no FK) → el dominio no importa `agent`, el boundary se conserva. Se implementa en PR-16/17.

### 8. Métricas de NEGOCIO del piloto (P6 del PO — F2 es una funcionalidad comercial)

Además de las métricas técnicas (latencia, tasa de error, costo/tokens), F2
mide **desempeño comercial** — porque el objetivo real es agendar citas, no
solo "responder bien". Todas se derivan de tablas que YA existen en el
subsistema (sin escribir en `analytics`, que tiene su propio contrato —
arquitectura §12.3): se exponen en un endpoint `GET /api/inbox/metrics/?from=&to=`
+ tile en `/inbox`.

| Métrica | Definición | Fuente |
|---|---|---|
| **Conversaciones iniciadas** | `Conversation` creadas en el periodo | `Conversation.created_at` |
| **Con intención de agendar** | conversaciones que abrieron flujo de cita (T9 ofertó slots o hubo `pending_action` de create) | `ToolExecution(find_available_slots)` / `flow` |
| **Citas creadas** | ejecuciones confirmadas de `create_appointment` / `register_new_client_and_pet` con `http_status < 400` | `ToolExecution` (agente) — coincide con `AppointmentStatusChange` actor=AGENT |
| **Tasa de conversión** | citas creadas ÷ conversaciones con intención | derivada |
| **Handoffs** | por `reason_code` (explícito, urgencia, identidad, presupuesto…) | `HumanHandoff` |
| **Citas abandonadas** | conversaciones con intención que cerraron **sin** cita creada | `Conversation` + ausencia de create |
| **Cancelaciones** | ejecuciones confirmadas de `cancel_appointment` | `ToolExecution(cancel_appointment)` |
| **Embudo (dónde abandonan)** | conversación → intención → slots ofertados → confirmación pendiente → creada | progresión de `ToolExecution` + `pending_action` |

Estas métricas responden las preguntas de producto del PO: *¿cuántas citas
agenda el agente al mes? ¿qué % de conversaciones terminan en cita? ¿en qué
paso abandonan más?* — sin reconstruir la base a mano.

**Materialización**: v1 computa on-the-fly (volumen bajo del piloto — la
consulta agrega sobre ToolExecution/Conversation/HumanHandoff con índices ya
existentes). Trigger para materializar `AgentDailyUsage` (deferido en plan
v1.1 §C8): cuando la agregación duela o al cobrar el add-on. El **Gate F2**
incluye reportar estas métricas de las 2 semanas de piloto.

### 9. Aprobación

- [x] **É-F2 APROBADA** (PR-14..PR-19 + métricas de negocio §8) — Product Owner, 2026-07-19.
- Nota de proceso: el PO autoriza arrancar la implementación; PR-14 (idempotencia de dominio) es seguro de construir de inmediato (mejora el frontend actual, independiente del agente). Las tools de escritura del agente (PR-16+) idealmente se encienden tras validar É-F1 en piloto, pero se construyen ya conforme a esta aprobación.

---

## Deuda técnica detectada en el smoke real (É0/É-F0/É-F1, 2026-07-18) — fuera de las épicas

Anotada para un PR de higiene independiente (no bloquea É-F2):

- **`deploy.sh` no recrea Caddy** cuando cambia `infra/Caddyfile` (hubo que `restart caddy` a mano en el fix de `/hooks/`). El script debe detectar el cambio y reiniciar Caddy.
- **`Message.failure_reason` no se limpia** al reenviar con éxito (queda texto viejo junto a `status=sent`). Cosmético; limpiar en el path de éxito del sender.
- **`header_up X-Forwarded-*` redundantes** en el bloque `/hooks/` del Caddyfile (Caddy los manda por default — WARN inofensivo).
- **Token de WhatsApp temporal (24h)**: operativo, no código — migrar a System User token permanente antes del piloto formal.

---

*Todas las épicas de código (É0, É-F0, É-F1) están completas y verdes en CI, y validadas en producción real. É-F2 es la última épica del roadmap v1.1; F3 (proactividad/recordatorios) se especificará al cerrar F2 con datos reales.*
