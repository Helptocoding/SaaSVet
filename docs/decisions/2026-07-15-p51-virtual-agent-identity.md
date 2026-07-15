# ADR p51 — Identidad del agente virtual (service account + rol AGENT)

**Fecha**: 2026-07-15
**Estado**: PROPUESTO (se acepta junto con la aprobación de la épica É0 — `docs/whatsapp-agent-epics.md`)
**Contexto de producto**: subsistema de agente IA por WhatsApp (spec congelada F1: `docs/whatsapp-agent-functional-spec.md`)

---

## Contexto

El agente conversacional ejecuta operaciones reales contra la API (leer agenda, y en F2 crear/cancelar citas). El sistema tiene un invariante duro: **todo actor es server-side** (`docs/system-reference.md` §3.9) — `created_by`, `changed_by`, `Payment.actor`, `AppointmentStatusChange.changed_by` son FKs a `users.User` tomadas de `request.user`. No existe auth máquina-a-máquina (sin API keys, sin service accounts formales).

El agente necesita una identidad de actor. La pregunta de diseño: **¿qué es esa identidad?** ¿Un rol más (como ADMIN/VET/ASSISTANT)? ¿Un tipo de cuenta distinto? ¿Un modelo aparte?

Restricción conceptual señalada en revisión (2026-07-15): ADMIN/VET/ASSISTANT modelan **personas** con un puesto; el agente es un **actor del sistema**. En 6–12 meses puede haber varios (WhatsApp, voz, email, Instagram) — todos "no-personas", no necesariamente con los mismos permisos.

## Decisión

La identidad del agente se modela con **dos ejes ortogonales sobre `users.User`**:

1. **`User.is_service_account = BooleanField(default=False)`** — el eje "**qué clase de principal es**" (persona vs sistema). Toda lógica de "superficies humanas" discrimina por este flag, nunca por nombre de rol:
   - `StaffListView` excluye service accounts (no aparecen en la UI de Equipo).
   - `StaffDeactivateView` y `StaffResetPasswordView` excluyen service accounts como target (404) — un reset pondría `password_must_change=True` y el gate embebido en `HybridPermission` inutilizaría al agente.
   - Cualquier check futuro de "¿es una persona?" (notificaciones a staff, listados, métricas de equipo) usa el flag.

2. **`User.role = 'AGENT'`** — el eje "**qué puede hacer**" (nombre del conjunto de permisos). Reutiliza sin cambios la maquinaria RBAC existente: entrada en `PERMISSIONS` (fallback estático), `Role` por organización sembrado por `seed_permissions`/`_seed_roles_for_org` (ambos iteran `PERMISSIONS` dinámicamente — verificado), `UserRole` asignado por el signal `assign_rbac_role_on_create`, y evaluación DB-first por `HybridPermission`.

**Reglas de la cuenta**:
- **Una por organización**, creada por `create_agent_user(org)` y garantizada por el comando idempotente **`ensure_agent_users`** (recrea/reactiva al estado deseado; protege contra borrados/desactivaciones por shell).
- **`set_unusable_password()`**: no existe login interactivo; los tokens se acuñan server-side (Tool Executor, É-F1). `authenticate()` con password falla siempre.
- **`email=''`**: el constraint parcial de unicidad global (ADR p48) excluye `email=''` explícitamente para cuentas técnicas — patrón ya documentado en `users/models.py`.
- **Username reservado**: `agent.<canal>.<org.public_id>` (v1: `agent.whatsapp.<uuid>`) — la convención deja espacio a futuros agentes por canal.
- **Gates**: el legal gate NO requiere exención en código — `REQUIRED_DOC_TYPES_BY_ROLE` (`legal/services.py:20`) no tiene clave `AGENT` → `legal_acceptance_required()=False` por diseño del mapping. El must-change gate no aplica (flag siempre `False`; reset-password bloqueado por el guard del flag).
- **Kill switch en dos niveles**: operativo = `AgentSettings.enabled` (llega en É-F0; reversible desde la UI); administrativo = `is_active=False` (revoca tokens — comportamiento H-06, ADR p47; se restaura solo vía `ensure_agent_users` o shell).
- **Permisos por fase (menor privilegio)**: F1 = 12 permisos de solo lectura; `appointment.create/update` se añaden en F2 editando `PERMISSIONS["AGENT"]` — el seed propaga el cambio en el siguiente deploy (el `role.permissions.set(...)` del seed sobreescribe, la evolución es un cambio de una lista + deploy).

**Cadena de auditoría comprometida** (se materializa en É-F1): `created_by/changed_by = user AGENT` (dominio, ya gratis) → `ToolExecution` con **`domain_object_public_id` (indexado) + `request_id`** → `Conversation` → `ConversationMessage` (turno) → `LLMCall`. Dado cualquier objeto de dominio creado por el agente, se reconstruye exactamente qué conversación, qué mensaje, qué tool y qué corrida de LLM lo produjeron — sin agregar ninguna FK desde los modelos de dominio hacia el subsistema (el boundary se conserva: ningún dominio importa `agent`).

## Alternativas descartadas

1. **Solo `role='AGENT'` sin flag** (plan original de É0): conflaba "clase de principal" con "conjunto de permisos". Con N agentes futuros: o comparten un solo rol (permisos forzosamente iguales) o proliferan roles (`VOICE_AGENT`, `EMAIL_AGENT`…) y cada exclusión de superficie humana se vuelve una lista de strings frágil (`exclude(role__in=[...])`) que hay que perseguir en cada feature. Cambiarlo después = migración + barrido de todos los call sites. Costo de evitarlo hoy: un boolean.
2. **Solo flag, sin rol**: no funciona — la resolución RBAC exige un nombre de rol (el fallback estático está keyed por `User.role`; el path DB necesita un `Role` con nombre por org). Un flag no otorga permisos.
3. **Modelo `ServiceAccount` separado de `User`**: rompe el invariante actor-server-side — todas las FKs de auditoría apuntan a `users.User` y `request.user` debe ser un `User` (DRF + `TenantJWTAuthentication`). Requeriría FKs paralelas o genéricas en todo el dominio = rearquitectura sin beneficio proporcional.
4. **Reutilizar rol ADMIN para el agente**: viola menor privilegio (el agente tendría `*.*`, incluido dinero) y contamina la semántica de ADMIN.
5. **Auth M2M formal (API keys/OAuth client-credentials)**: no existe en el sistema; construirla solo para esto es superficie de ataque nueva sin beneficio — el JWT del agente nunca sale del servidor (loopback).

## Consecuencias

- (+) N agentes futuros = mismo flag, rol nuevo **solo si** el conjunto de permisos difiere; cero cambios en superficies humanas.
- (+) Auditoría de dominio gratis (`created_by` etc.) + cadena completa reconstruible vía `ToolExecution`.
- (+) Evolución de permisos = editar una lista + deploy (seed idempotente); test de evolución lo ancla.
- (−) `User` gana un campo que solo usan cuentas de sistema (aceptado: es el costo mínimo de no romper el invariante de actor).
- (−) Un humano con acceso a shell puede seguir rompiendo la cuenta (borrar/desactivar) — mitigado con `ensure_agent_users` idempotente y el hecho de que borrar Users ya está desaconsejado proyecto-wide (ADR p16). Si se borra y recrea, las FKs `SET_NULL` de filas viejas pierden atribución (aceptado, documentado).

## Evolución prevista (no implementar ahora)

- Varios agentes por org (por canal): un user por canal con la convención de username; `AgentSettings` referencia cuál usa cada canal.
- Si algún día se necesita auth M2M real (integraciones de terceros), este ADR no la bloquea: el flag `is_service_account` es la base natural para esa clase de cuentas.
