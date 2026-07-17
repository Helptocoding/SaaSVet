# Épicas de implementación — Agente WhatsApp

**Rol**: registro de planes de implementación por épica (protocolo Tech Lead: impacto → plan incremental → migraciones → riesgos → pruebas → **aprobación** → código).
**Contrato**: [`whatsapp-agent-functional-spec.md`](whatsapp-agent-functional-spec.md) (congelada F1) + [`whatsapp-agent-implementation-plan.md`](whatsapp-agent-implementation-plan.md) (diseño v1.1, clasificación A/B/C/D).
**Regla**: ningún cambio de arquitectura sin RFC aprobado. Cada épica se planifica aquí ANTES de escribir código y espera aprobación explícita.

## Registro de épicas

| Épica | Alcance | Estado | Depende de |
|---|---|---|---|
| **É0** | Fundaciones core: PR-0 fotografía + fix RBAC `vaccinerecord` (PR-1) + identidad del agente (PR-2) | **✅ COMPLETADA 2026-07-16** — PR-0 (a960e07..997c796), PR-1 (13115af), PR-2 (886fbd6); CI verde en los tres. Pendiente solo el deploy a prod | — |
| É-F0 | Buzón operable: apps `channels`+`agent`, webhook, worker, outbox, plantillas tier-0, bandeja `/inbox` | Sin planear (tras É0) | É0 + número Meta (A0-1, lado usuario) |
| É-F1 | Agente read-only: LLM, Policy Engine, FSM, Tool Executor (incluye minting + throttle scope diferidos de A0-2), tools T1–T8+T15 | Sin planear | É0, É-F0, consulta legal A1-1 |
| É-F2 | Escritura de agenda: A2-1 idempotencia + T9–T14 + tier-2 + P1 de la revisión UX | Sin planear | É-F1 |

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

- [ ] É-F0 aprobada (PR-3..PR-8)
- Aprobado por: ______ · Fecha: ______

---

*Las épicas siguientes (É-F1, É-F2) añadirán aquí su plan con la misma estructura antes de escribir código.*
