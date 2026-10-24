# WhatsApp Inbox — Plan de implementación técnico secuencial

**Fecha**: 2026-08-22
**Estado**: **APROBADO PARA IMPLEMENTACIÓN** — D-1..D-10 cerradas por el PO el 2026-08-22 y consolidadas en [ADR p60](decisions/2026-08-22-p60-whatsapp-inbox-decisions.md)

**Seguimiento de cierre vigente:** [Guía para cerrar Inbox y agente WhatsApp](CIERRE-INBOX-WHATSAPP.md). Organiza el trabajo pendiente y conserva los requisitos y el Definition of Done de este plan; no modifica las evidencias históricas ni autoriza nuevas campañas B9 automáticamente.

**Base**:
- Auditoría integral: [`whatsapp-inbox-auditoria-2026-08-21.md`](whatsapp-inbox-auditoria-2026-08-21.md) (hallazgos con evidencia `archivo:línea`)
- Código real verificado para este plan: `backend/apps/channels`, `backend/apps/agent`, `frontend/src/pages/inbox/`
- Arquitectura del subsistema: [`whatsapp-agent-functional-spec.md`](whatsapp-agent-functional-spec.md), [`modules/agent.md`](modules/agent.md), ADR p51–p60
- Convenciones: `backend/CLAUDE.md`, `frontend/CLAUDE.md`, `docs/CLAUDE.md`

**Alcance**: llevar el Inbox desde su estado actual a una bandeja profesional de WhatsApp para recepción veterinaria. No es un clon de WhatsApp Web.

**Qué NO toca este plan**: el agente conversacional (planner, tools, goals, FSM), la spec funcional F3 de plantillas HSM (épica propia ya documentada), y ningún otro módulo del SaaS salvo lo explícitamente listado aquí.

**Regla de ejecución**: cada tarea tiene ID (`WA-*`). Un agente de desarrollo debe poder ejecutar «Ejecuta WA-0XX» con el contexto de su especificación sin re-descubrir la arquitectura. El orden es por dependencias reales, no por deseo.

---

## Contenido

1. [Estado actual — resumen técnico](#1-estado-actual--resumen-técnico)
2. [Arquitectura actual](#2-arquitectura-actual)
3. [Dependency graph](#3-dependency-graph)
4. [Roadmap — fases](#4-roadmap--fases)
5. [Backlog completo con especificaciones](#5-backlog-completo-con-especificaciones)
6. [Contratos técnicos](#6-contratos-técnicos)
7. [Plan de migraciones](#7-plan-de-migraciones)
8. [Plan de tests](#8-plan-de-tests)
9. [Plan de despliegue](#9-plan-de-despliegue)
10. [Riesgos](#10-riesgos)
11. [Decisiones arquitectónicas cerradas](#11-decisiones-arquitectónicas-cerradas)
12. [Fuera de alcance](#12-fuera-de-alcance)
13. [Definition of Done global](#13-definition-of-done-global)

---

## 1. Estado inicial — resumen técnico de la auditoría

> **Baseline preimplementación (2026-08-22).** Este inventario y sus etiquetas
> «No implementado», «P0» o «bug» describen el snapshot que originó el plan; no
> son el registro de ejecución vigente. El estado posterior y su evidencia se
> mantienen en «Estado de ejecución» junto al roadmap (§4).

El backend del subsistema WhatsApp es sólido y está **por delante del frontend**: webhook firmado HMAC fail-closed (`channels/views.py:39-91`), dedup inbound por wamid con unique parcial (`channels/models.py:240-245`), sender con backoff exponencial y ventana 24 h (`agent/worker.py:35-47, 351-410`), claim/close/release serializados con lock y testigo CAS (`agent/views.py:502-595`, `agent/services.py:499-789`), acuses forward-only sent→delivered→read (`agent/services.py:388-432`), permisos granulares `agentinbox.*`.

El frontend Inbox es **una sola pantalla de 781 líneas** (`frontend/src/pages/inbox/index.jsx`) con polling REST (lista cada 20 s, transcript cada 10 s; `index.jsx:34-35`), **cero tests**, sin historial paginado, sin optimistic send, sin media, sin replies, sin unread real, sin realtime (no existe SSE/WS en todo el repo — verificado por grep).

### Mapa funcional por capa

✓ = existe · ✗ = no existe · ~ = parcial

| Funcionalidad | Modelo | Endpoint | Serializer | Service / Worker | Webhook | Frontend API | UI | Tests existentes | Tests faltantes | Estado |
|---|---|---|---|---|---|---|---|---|---|---|
| Historial paginado | `Message` ✓ con cursor `before` | GET `/api/inbox/threads/{c}/{a}/messages/?before=` (`agent/views.py:862-918`, página 50, `next_before`) | `MessageSerializer` (`serializers.py:35-48`) | — | — | `getThreadMessages(c,a,params)` **sí acepta params** (`api/inbox.js:25-28`) pero la página no pasa `before` (`index.jsx:273`) | truncado a últimos 50; scroll forzado al fondo (`index.jsx:334-336`) | API cursor ✓ (`test_inbox_threads.py`) | merge sin duplicados, posición de scroll, buffer límite | **Parcial — backend listo, UI no lo consume** |
| Envío del staff | `Message` out `pending→sent→delivered→read/failed` | POST `/api/inbox/conversations/{pk}/send/` (`views.py:439-499`; auto-claim, author=`human_staff`) | `SendMessageSerializer` (≤4000) | sender `send_pending_outbound` (`worker.py:319-410`); ventana 24 h validada al enviar | statuses → `record_status_update` forward-only (`services.py:402-432`) | `sendInboxMessage` | sin optimistic; rama «enviando…» muerta porque el selector oculta todo out-pending (`channels/selectors.py:38-43`; `index.jsx:745`) | worker/sender ✓; API send ✓ | idempotencia server; reconciliación optimistic | **Parcial** |
| Idempotencia de envío server | ✗ | ✗ | — | patrón replicable: Appointment/Payment (`appointments/models.py:59-107`, ADR p27/p52); receipts por `operation_key` (`agent/outbound.py:63-108`) | — | CORS ya permite header `x-idempotency-key` (`settings.py:531-533`) | — | — | todo | **No implementado** |
| Media entrante | ✗ — solo `{type, timestamp}` en `raw_metadata` (`channels/views.py:151-154`) | ✗ | ✗ | ✗ no hay descarga ni storage (0 resultados de FileField/MEDIA_ROOT en backend) | `_extract_body` descarta media **y caption** (`views.py:94-111`) | ✗ | placeholder `[image]` (`index.jsx:730`) | — | todo | **No implementado — pérdida de datos activa** |
| Replies | ✗ `reply_to` no existe; `msg.context` nunca se lee | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | — | todo | **No implementado (requiere cambio de modelo)** |
| Separadores fecha / agrupación | n/a | n/a | n/a | — | — | — | ✗ hora por burbuja, `fmtTime` TZ navegador (`index.jsx:57-64`) | — | unit formateo | **No implementado (frontend puro)** |
| Estados sent/delivered/read | `Message.status` ✓ ranking forward-only | viaja en serializer ✓ | ✓ | ✓ | ✓ | dato disponible | solo pinta `failed`/`pending` (`index.jsx:740-745`) | acuses backend ✓ | render ticks | **Parcial — costo backend cero** |
| Unread real / marcar leído | ✗ | ✗ | `has_unanswered` heurístico de dirección del último mensaje (`views.py:794-800`) | — | — | ✗ | punto binario (`index.jsx:583`) | — | modelo de lectura por usuario | **Parcial** |
| Draft al cambiar conversación | n/a | n/a | — | — | — | — | **BUG: `body` NO se limpia** al seleccionar otro hilo (`index.jsx:570-579` limpia thread/selección solamente) | — | test cambio de hilo | **Defecto P0** |
| Concurrencia humano↔agente | lease `processing_until` ✓ | release 409 `turn_in_progress` ✓ | ✓ | **BUG latente**: `_discard_if_superseded` (`worker.py:185-226`) descarta TODO out-pending nuevo **sin filtrar `author_type`** → puede borrar respuesta humana pendiente | — | 409 genérico sin contexto | — | discard tests ✓ sin caso humano | caso respuesta humana durante turno | **Bug latente P0** |
| Retry de fallidos | `failed` + `failure_reason` ✓ | ✗ endpoint de reintento | `failure_reason` viaja ✓ | backoff automático solo pre-envío (≤5 intentos) | — | ✗ | «no entregado» sin acción (`index.jsx:740-744`) | ventana 24 h sender ✓ | endpoint retry + validación ventana | **Parcial** |
| Búsqueda | ✗ | ✗ cero params de búsqueda en channels/agent (verificado) | ✗ | — | — | ✗ | ✗ | — | todo | **No implementado** |
| Realtime | ✗ sin SSE/WS/channels (grep confirmado) | polling 20 s/10 s | — | worker propio `run_agent_worker` (docker service) | — | `setInterval` inline sin pausa por visibilidad (`index.jsx:281-293`) | — | — | — | **No implementado** |
| Timezone de organización | `Organization.timezone` ✓ (`organizations/models.py:26`) | `/api/me/` **ya expone `organization_timezone`** (`users/views.py:54`) | — | helpers org-aware ✓ (`core/datetime_utils.py`) | — | authContext carga `/me/` | `fmtTime` usa TZ del navegador; `toDateString()` rompe «Hoy» cerca de medianoche multi-TZ | calendar-rule gate ✓ | render TZ-aware | **Parcial — dato disponible sin usar** |
| Lista de hilos | `Conversation` agrupada en memoria por `(contacto,cuenta)` | GET `/api/inbox/threads/` — cap silencioso 100 (`THREADS_CAP`, `views.py:717,815`) | `ThreadSerializer` (`serializers.py:195-226`) | — | — | `getThreads({archived})` | filtros Activas/Archivadas; punto binario; badges estado/handoff | `test_inbox_threads.py` ✓ | N+1, paginación, filtros segmentados | **Parcial — N+1 estructural (~2 queries/hilo/poll)** |

Conclusión: hay **capacidad backend sin consumir** (cursor, ticks, verificación de contacto, timezone) y **carencias reales de modelo** (media, replies, read-state). Hay **dos defectos con daño potencial activo** que se corrigen antes de cualquier feature: draft leak y discard de respuestas humanas.

---

## 2. Arquitectura auditada — baseline preimplementación

> Los diagramas, paths y hallazgos de esta sección pertenecen al mismo baseline
> preimplementación del 2026-08-22. Se conservan como evidencia causal y no
> contradicen las tareas ya cerradas que constan en §4.

```
Cliente WhatsApp
   │
   ▼
POST /hooks/whatsapp/  (fuera de /api/, firma HMAC fail-closed, ACK <1s, siempre 200)
   channels/views.py ── _extract_body: text | interactive | *media*  ← media/caption/context SE DESCARTAN
   │
   ▼
ingest_inbound_message()   agent/services.py — dedup wamid, debounce 8s/25s,
   │                        resolve_contact_identity → Owner, get_or_create_open_conversation
   ▼
Message(status=pending, direction=in)
   │
   ▼
run_agent_worker (management command; docker service `worker`; NO está en Procfile)
   ├─ process_pending_conversations → lease turno (SKIP LOCKED) → planner/buzón → enqueue_outbound
   │    └─ _discard_if_superseded (worker.py:185-226)          ← BUG: no filtra author_type
   ├─ send_pending_outbound → MetaWhatsAppProvider.send_text   ← ÚNICO método del adaptador (providers.py:58-99)
   │    └─ ventana 24 h + backoff 30s·2ⁿ cap 1h, máx 5 intentos → sent/failed(+reason)
   └─ record_status_update (statuses del webhook) → sent→delivered→read forward-only

Frontend Inbox (pages/inbox/index.jsx · polling REST · sin tests)
   ├── GET /api/inbox/threads/                            lista agrupada, cap 100, N+1, cada 20 s
   ├── GET /api/inbox/threads/{c}/{a}/messages/?before=   transcript 50 + cursor NO usado, cada 10 s
   ├── POST …/{pk}/send|claim|close|release|reset-identity|verify-identity…
   ├── GET/PATCH settings · metrics · whatsapp-token      (ADMIN/config)
   └── permisos client-side can('agentinbox.*') · apiError() · useConfirm · toasts sonner
```

Patrones existentes que este plan REUTILIZA (no se introduce una segunda arquitectura):

| Necesidad | Patrón existente | Referencia |
|---|---|---|
| Multi-tenancy | `OrganizationalModel` + `for_organization(request.user.organization)`; gate CI `test_tenant_scoping_audit.py` | `apps/core/models.py:114-195` |
| Permisos nuevos | catálogo `PERMISSION_CODES` + mapa `PERMISSIONS` por rol; seeding en release (`seed_permissions`) | `apps/core/permissions_codes.py` |
| Idempotencia | columna + unique parcial por org + header `X-Idempotency-Key` | `appointments/models.py:59-107`, `services.py:521-539` |
| Fechas org-aware | `org_today_local(org)`, `utc_to_local` | `apps/core/datetime_utils.py` |
| Errores API | `{code, message/errors}` ↔ frontend `apiError()` | convención global |
| Logging de eventos | logger `<dominio>.events`, JSON estructurado, **sin PII** (R15) | `settings.py:555-660` |
| Storage de archivos | **NO EXISTE** — el SaaS nunca persiste binarios (imports in-memory, soporte reenvía a Discord) | verificado por grep |
| Realtime/cola | no hay Celery ni Channels; worker propio + Redis solo caché/throttle | `docker-compose.prod.yml:59-184` |
| Confirmaciones UI | `useConfirm()` (nunca `window.confirm`) | `components/useConfirm.js` |
| Tests | Django `TestCase`/`APITestCase` + roles sembrados desde `PERMISSIONS` + fixture cross-tenant; frontend Vitest+Testing Library | `test_inbox_api.py`, `vite.config.js:36-41` |

Comandos de verificación del repo:
- Backend: `python manage.py makemigrations --check --dry-run` → `migrate --no-input` → `python manage.py test --parallel` (CI `.github/workflows/ci.yml:65-69`)
- Frontend: `pnpm run build` → `pnpm test` (vitest) → lint (advisory) → `pnpm run smoke:urls`

---

## 3. Dependency graph

```
FASE 0   FIX-01 draft leak ────────────────┐  hotfix independiente
         FIX-02 discard humano ────────────┤
         FIX-03 idempotency_key (M1) ──────┘
                    │
FASE 1             ├─ OPT-01 selector pending staff ── OPT-02 optimistic UI
                   │
         UX-01 util TZ org ──► SEP-01 separadores ──► GRP-01 agrupación
         TCK-01 ticks (sin deps)
         CMP-01 composer · CPY-01 copy/autolink · TAB-01 título pestaña
         VIS-01 pausa polls · VER-01 badge verificación · LDE-01 estados carga/error
         AGT-01 indicador agente (backend bool + chip)
         GTF-01 botón ir-al-final
                    │
FASE 2   PERF-01 fix N+1 threads ──► FIL-01 filtros segmentados ──► SRCH-01 búsqueda f1
            └──► PERF-02 paginación lista ──► PERF-03 ?since incremental
         HIST-01 scroll-back next_before ──► HIST-02 merge nuevos + anclaje scroll + pill
         HIST-03 around=<id> (backend) ─────────────────────────────┐
         UNR-01 read-state backend (M3) ──► UNR-02 contador + divider + mark-read
         RETRY-01 retry fallidos · WIN-01 ventana 24 h visible · CTX-01 panel cliente
         ASN-01 asignación (P2)
                    │
FASE 3   RPL-01 modelo reply_to (M2) ── RPL-02 webhook context ── RPL-03 API send/serializer
            │                                                    │
            └─ RPL-04 quotes entrantes ◄── RPL-05 composer reply ◄┤
               RPL-06 quote block + jump-to-message ◄── HIST-03   │
               RPL-07 suite edge cases ──────────────────────────┘
         MED-01 modelo MessageMedia (M4, tras ADR storage) ── MED-02 webhook parse + caption
            └── MED-03 worker descarga ── MED-04 servido auth-scoped ── MED-05 render frontend
                 MED-06 media saliente (tras MED-04 estable)
                    │
FASE 4   NO-GO SSE v1 (D-5) ──► polling optimizado PERF-03
         RT-00 queda como reevaluación futura; RT-01..03 no forman parte del rollout v1
                    │
FASE 5   VIRT-00 threshold check · PRES-01 presencia · OPS-MET métricas operación humana
         ACTLOG auditoría DB de acciones · A11Y atajos/aria · MOB master-detail móvil
         MRK blue-ticks al cliente · NOT-01 sonido/Notification futura · SRCH-02 búsqueda contenido · ORD-01 diferida
```

Dependencias falsas **descartadas** deliberadamente:
- Separadores/ticks/agrupación no requieren realtime ni store normalizado.
- Optimistic send no requiere SSE: reconcilia contra el poll de 10 s ya existente.
- Búsqueda fase 1 no requiere pg_trgm: es filtro sobre contacto/owner/teléfono.
- Virtualización no depende de ninguna tarea pendiente; se decide con evidencia (VIRT-00).
- Unread v1 visual (título de pestaña) no requiere el modelo de read-state; usa `has_unanswered` que ya viaja.

---

## 4. Roadmap — fases

| Fase | Nombre | Objetivo | Tareas (en orden ejecutable) | Riesgo |
|---|---|---|---|---|
| **0 · CERRADA 2026-08-23** | Seguridad y consistencia | Eliminar los dos defectos con daño potencial activo; dejar idempotencia lista para optimistic send | FIX-01 → FIX-02 → FIX-03 | Bajo-medio |
| **1** | «Deja de sentirse incompleto» | Máximo impacto visual/UX con riesgo mínimo, casi todo frontend sobre datos que ya viajan | UX-01 → SEP-01 → TCK-01 + OPT-01 → OPT-02 → GRP-01 + CMP-01 + CPY-01 + TAB-01 + VIS-01 + VER-01 + LDE-01 + AGT-01 + GTF-01 | Muy bajo |
| **2** | «Inbox profesional» | Operación diaria completa de una recepcionista: historial completo, unread real, filtros, búsqueda básica, retry, ventana 24 h, contexto del cliente, performance | PERF-01 → PERF-02 → FIL-01 → SRCH-01 → HIST-01 → HIST-02 → HIST-03 → UNR-01 → UNR-02 → RETRY-01 → WIN-01 → CTX-01 → PERF-03 → ASN-01 | Medio |
| **3** | Mensajería avanzada | Dejar de perder datos: replies end-to-end y pipeline completo de media entrante | RPL-01..07 · MED-01..05 · MED-06 opcional | Medio-alto |
| **4** | Realtime | **NO-GO SSE en v1 (D-5)**: operar con polling correcto y barato; reevaluar realtime únicamente con evidencia posterior | PERF-03; RT-00 futuro. RT-01..03 diferidas fuera del rollout v1 | Bajo en v1 |
| **5** | Operación a escala | Solo con evidencia de necesidad | VIRT-00, PRES-01, OPS-MET, ACTLOG, A11Y, MOB, NOT-01, MRK, SRCH-02; ORD-01 diferida por D-10 | Variable |

### Estado de ejecución — Fase 0 cerrada (2026-08-23)

- **WA-FIX-01 · IMPLEMENTADA**: el borrador se limpia al cambiar de hilo y el
  envío conserva la sesión seleccionada.
- **WA-FIX-02 · IMPLEMENTADA**: el drain solo descarta salientes del
  agente/sistema; `human_staff` permanece pendiente.
- **WA-FIX-03 · IMPLEMENTADA**: idempotencia org-scoped, constraint parcial,
  replay estable, takeover atómico y recuperación de carrera PostgreSQL real.
- **Evidencia de cierre**: backend dirigido **28/28** —incluida carrera real con
  dos conexiones PostgreSQL—; frontend **10/10**; Vite build correcto;
  `makemigrations --check` sin cambios; revisión independiente **APPROVE**.
- **Suite integral verificada**: `apps.agent --parallel 4` → **Ran 769**, **OK**,
  `skipped=1`; system check: **0 issues**.

### Ejecución Fase 1 — corte 2026-08-23

- **WA-UX-01 y WA-SEP-01 implementadas** en `frontend/src/utils/datetime.js`,
  `frontend/src/pages/inbox/index.jsx` e `inbox.module.css`, con pruebas en
  `datetime.test.js` e `index.test.jsx`: tiempo y agrupación por día usan la TZ
  de la organización; el transcript renderiza separadores Hoy/Ayer/fecha.
- **WA-OPT-01 implementada** en `backend/apps/channels/selectors.py`:
  `visible_messages` incluye `out/pending` exclusivamente para
  `human_staff`; `agent/system` pending y `failed/discarded` siguen ocultos.
  El aislamiento del anti-eco vive en `agent/identity_evidence.py` y sus
  regresiones en `test_identity_evidence.py`/`test_inbox_threads.py`.
- **Desviación descubierta y corregida**: la premisa del plan afirmaba que el
  anti-eco ya usaba `emitted_outbound`, pero `_first_disclosure` consumía
  `visible_messages`. Se auditaron sus **8 consumidores** (tres views, tres
  consumidores de prompts y dos de identidad) y se migró `_first_disclosure`
  a un historial ordenado de entrantes recibidos + `emitted_outbound`. Las
  regresiones prueban que un pending humano no revela el dato y un saliente
  efectivamente emitido sí lo hace.
- **Evidencia**: backend inbox+identity **67/67**; continuity **19/19**;
  frontend **19/19**; Vite build **4637 ms**. La revisión independiente emitió
  **REQUEST CHANGES** por dos P2, ambos corregidos; re-review final **APPROVE**.

### Ejecución Fase 1 — segundo corte verificado (2026-08-23)

- **Prerrequisito backend de WA-OPT-02 implementado**: el
  `MessageSerializer` usado exclusivamente por Inbox expone
  `client_message_id` de solo lectura, derivado de `idempotency_key` únicamente
  para salientes `human_staff`. Inbound, agente/sistema y claves nulas exponen
  `null`; el campo no se acepta como entrada ni permite mutación. POST, replay y
  GET transcript conservan el mismo id y correlación.
- **Remediación de aislamiento**: `_replay_outbound_message` y la constraint
  parcial `message_unique_idempotency_per_org` limitan la correlación a
  `direction=out`, `author_type=human_staff` y key no nula. Una key interna de
  agente/sistema no puede provocar replay ni filtrar su cuerpo al staff.
  Evidencia backend: corrida inicial **35/35**; remediación **26/26**, incluida
  carrera PostgreSQL real y RBAC/tenant; `makemigrations --check` sin cambios.
- **WA-TCK-01 implementada**: `DeliveryTicks` representa pending, sent,
  delivered, read, failed y discarded en mensajes salientes; los entrantes no
  muestran ticks. Cada estado tiene nombre accesible (`aria-label`), y los
  fallos conservan detalle mediante tooltip sin depender solo del color. El
  código y las pruebas render están completos; la validación E2E con acuses
  reales en sandbox Meta permanece pendiente.
- **WA-OPT-02 implementada**: overlay optimista acotado a **20** entradas por
  `sessionId + clientKey`; los 4xx retiran el temporal y muestran error, mientras
  red/5xx conservan `failed-local` y reintentan con la misma key. Las respuestas
  201 y los GET se fusionan por id/correlación sin duplicar. Las regresiones
  cubren A→B→A y `AbortController`/unmount para impedir que una respuesta tardía
  contamine otro hilo.
- **Evidencia frontend final**: **48/48** dos veces (**43.70 s** y **41.29 s**);
  suite aislada del revisor **21/21**; Vite build **4638 ms**; lint sin errores
  nuevos (permanecen **2 históricos**); `diff-check` limpio. La revisión inicial
  emitió **REQUEST CHANGES** por dos hallazgos (P1 y P2), ambos remediados;
  re-review final **APPROVE**.

Regla anti-refactor: cada fase se implementa tocando lo mínimo indicado en sus tareas. La deuda técnica detectada y que NO bloquea features queda registrada en §10/Fase 5, no se mezcla con las PRs de features.

### Seguimiento vigente — WA-CMP-01, WA-GRP-01, WA-CPY-01 y WA-TAB-01 (2026-10-20)

- **WA-CMP-01 implementada y verificada localmente**: altura automática 40–120 px,
  contador después de 3600/4000 y advertencia desde 3800. Borrado, envío y cambio
  de hilo reajustan el campo; envío e idempotencia conservan su contrato.
- [Evidencia dirigida](evals/inbox-cmp-01-2026-10-20/README.md): **30/30** casos de
  Inbox (cuatro nuevos), build PASS y Chromium con fixtures en escritorio/móvil
  PASS. Lint advisory conserva dos errores existentes en efectos de polling.
- La [tabla de cierre](CIERRE-INBOX-WHATSAPP.md) contiene el estado actual de las
  demás familias. Este corte no acredita acuses Meta, operación real, media ni
  aceptación integral; el FAIL de seguridad r12 permanece vigente.
- **WA-GRP-01 implementada y verificada localmente**: ráfagas del mismo autor
  con intervalo inferior a cinco minutos, separadas al cambiar de día local.
  Se preserva cada mensaje con su hora y estado. `human_author_public_id` de
  sólo lectura evita agrupar empleados homónimos; sin identidad, no se agrupa.
  [Evidencia GRP-01](evals/inbox-grp-01-2026-10-20/README.md): 19 casos frontend y
  cuatro backend PASS, build y Chromium escritorio/móvil PASS. Dos errores lint
  previos siguen advisory.
- **WA-CPY-01 implementada y verificada localmente**: copia de mensaje/teléfono,
  enlace telefónico y autolink seguro HTTP/HTTPS, con teclado y táctil. HTML
  permanece literal. [Evidencia CPY-01](evals/inbox-cpy-01-2026-10-20/README.md):
  18 casos únicos PASS (ocho conservados y diez corregidos), build y Chromium
  escritorio/táctil PASS.
- **WA-TAB-01 implementada y verificada localmente**: contador de hilos con
  `has_unanswered` en segundo plano; título restaurado al foco o desmontaje.
  [Evidencia TAB-01](evals/inbox-tab-01-2026-10-20/README.md): siete pruebas nuevas
  y build PASS; sin errores lint nuevos.
- **WA-VIS-01 implementada y verificada localmente (2026-10-21)**: pausa de lista
  e hilo ocultos y refresh inmediato al volver, conservando filtro y selección.
  [Evidencia VIS-01](evals/inbox-vis-01-2026-10-21/README.md): 17 pruebas, build y
  lint PASS; Chromium con visibilidad controlada, cero polls ocultos durante 21 s.
  El siguiente pendiente de ese corte era WA-VER-01.
- **WA-VER-01 implementada y verificada localmente (2026-10-21)**: distintivo de
  identidad en lista y cabecera, con explicación del nivel y actualización por poll.
  [Evidencia VER-01](evals/inbox-ver-01-2026-10-21/README.md): 15 pruebas, build,
  lint y Chromium escritorio/móvil PASS. El siguiente pendiente de ese corte era WA-LDE-01.
- **WA-LDE-01 implementada y verificada localmente (2026-10-21)**: carga, error
  y reconexión por panel, conservando datos y borrador durante fallos.
  [Evidencia LDE-01](evals/inbox-lde-01-2026-10-21/README.md): 18 pruebas, build,
  lint y Chromium escritorio/móvil PASS; caída simulada con recuperación automática.
  El siguiente pendiente de ese corte era WA-AGT-01. Ensayo de backend real pendiente.
- **WA-AGT-01 implementada y verificada localmente (2026-10-21)**: booleano
  informativo de turno y chip que deshabilita Tomar/Liberar mientras esté activo.
  [Evidencia AGT-01](evals/inbox-agt-01-2026-10-21/README.md): seis pruebas API
  PostgreSQL y nueve frontend PASS, build, lint y Chromium escritorio/móvil PASS.
  El siguiente pendiente de ese corte era WA-GTF-01.
- **WA-GTF-01 implementada y verificada localmente (2026-10-21)**: botón de
  retorno al fondo con teclado/puntero, foco conservado y scroll móvil acotado.
  [Evidencia GTF-01](evals/inbox-gtf-01-2026-10-21/README.md): 25 pruebas, build,
  lint y Chromium escritorio/móvil PASS. El siguiente pendiente de ese corte era WA-PERF-01.
- **WA-PERF-01 implementada y verificada localmente (2026-10-21)**: consulta
  agrupada y anotada en SQL, cap previo a materialización y payload conservado.
  [Evidencia PERF-01](evals/inbox-perf-01-2026-10-21/README.md): 14 pruebas API
  PostgreSQL PASS; 15/75 → 1/1 consultas para 7/37 hilos con autenticación de fixture.
  El siguiente pendiente de ese corte era WA-PERF-02.
- **WA-PERF-02 implementada y verificada localmente (2026-10-21)**: páginas de
  100 hilos con aviso y carga adicional; refresco de todas las páginas cargadas,
  deduplicación, errores recuperables y protección contra respuestas tardías.
  [Evidencia](evals/inbox-perf-02-2026-10-21/README.md): 21 pruebas PostgreSQL y
  29 casos frontend únicos PASS, build, lint y Chromium escritorio/móvil PASS.
  El siguiente pendiente de ese corte era WA-HIST-01.
- **WA-HIST-01 implementada y verificada localmente (2026-10-21)**: scrollback
  con cursor, mensajes acumulados, anclaje de inserciones y carga manual desde
  500 mensajes. [Evidencia](evals/inbox-hist-01-2026-10-21/README.md): 77 casos
  frontend únicos PASS, build, lint y Chromium escritorio/móvil PASS; 200
  mensajes accesibles sin duplicados y anclaje con variación inferior a 1 px.
  El siguiente pendiente de ese corte era WA-HIST-02.
- **WA-HIST-02 implementada y verificada localmente (2026-10-21)**: anclaje ante
  llegadas nuevas, seguimiento al fondo y pill con contador deduplicado.
  [Evidencia](evals/inbox-hist-02-2026-10-21/README.md): 96 pruebas frontend
  únicas PASS, build, lint y Chromium escritorio/móvil PASS; lectura de julio
  conservada al llegar mensajes de octubre, sin desplazamiento del ancla.

- **WA-HIST-03 implementada y verificada localmente (2026-10-21)**: consulta
  `around` con hasta 25 anteriores + destino + 24 siguientes, continuidad,
  destino oculto marcado y aislamiento de hilo/organización. La página normal
  y los metadatos de sesión vigente conservan su contrato.
  [Evidencia](evals/inbox-hist-03-2026-10-21/README.md): 33 pruebas PostgreSQL
  únicas PASS (22 nuevas, 11 afectadas); se conservan tres fallos iniciales del
  harness/fixture, resueltos mediante repetición dirigida sin cambiar producto.

- **WA-UNR-01 implementada y verificada localmente (2026-10-21)**: estado por
  usuario/hilo, conteo de entrantes visibles solo del episodio vigente y POST
  read idempotente/monótono con permiso view y upsert serializado.
  [Evidencia](evals/inbox-unr-01-2026-10-21/README.md): 35 pruebas PostgreSQL
  únicas PASS (24 nuevas, 11 afectadas), con dos carreras reales. Migración M3
  aditiva y sin backfill, generada y probada solo en bases temporales.
  Se conservan los fallos iniciales de formato de errores y clasificación SQL.

- **WA-UNR-02 implementada y verificada localmente (2026-10-21)**: contador
  por hilo y total de todas las páginas, divisor y marcado automático con foco,
  visibilidad, debounce y cancelación. Reintento silencioso en el siguiente poll.
  [Evidencia](evals/inbox-unr-02-2026-10-21/README.md): 125 pruebas frontend,
  41 API, build, lint y Chromium escritorio/móvil PASS; dos empleados
  independientes, ancla 0 px al retirar divisor. Proyecciones API aditivas;
  no hay migración nueva y M3 no se aplicó a la base de trabajo.
  WA-RETRY-01 se verifica en el corte siguiente; continúa pendiente WA-WIN-01.

- **Corte WA-RETRY-01, 2026-10-21 — implementación local**: endpoint con permiso
  send y reintento en burbuja, misma fila/cuerpo/autor/key y auditoría sin PII.
  Revalida B4 y ventana sin renovar autoridad ni reenviar incertidumbre.
  [Evidencia](evals/inbox-retry-01-2026-10-21/README.md): 29 pruebas API y 106 casos
  frontend únicos PASS en evidencia compuesta, build, lint y Chromium escritorio/
  móvil PASS. Una sola transición en carrera real y ancla 0 px. Sin migración
  nueva, sin aplicar M3 ni acreditar Meta real. Siguiente de ese corte: WA-WIN-01.

- **Corte WA-WIN-01, 2026-10-21 — implementación local**: proyección de ventana
  en la sesión vigente, aviso bajo 12 h y bloqueo del composer al vencer.
  Conserva borrador y habilita de nuevo tras la renovación por inbound/poll.
  [Evidencia](evals/inbox-win-01-2026-10-21/README.md): 19 pruebas API y 84 casos
  frontend únicos PASS en evidencia compuesta, build, lint y Chromium escritorio/
  móvil PASS. B4 conserva la autoridad de dispatch. Sin migración nueva ni aplicar
  M3 a la base de trabajo. Siguiente de ese corte: WA-CTX-01; aceptación Meta/operativa pendiente.

- **Corte WA-CTX-01, 2026-10-21 — implementación local**: API y panel plegable
  del cliente vinculado, mascotas y última cita anterior no clínica. Acceso al
  expediente correcto en dos clics desde el chat abierto, con permisos y scope
  por clínica. [Evidencia](evals/inbox-ctx-01-2026-10-21/README.md): 20 pruebas API
  y 112 casos frontend únicos PASS en evidencia compuesta; build, lint y Chromium
  escritorio/móvil PASS. Sin nueva migración ni aplicar M3. Siguiente de ese corte: WA-PERF-03;
  la aceptación operativa/Meta real permanece pendiente.

- **Corte WA-PERF-03, 2026-10-21 — implementación local**: cursores firmados por
  usuario/consulta, deltas con retiradas y recuperación del rango leído. Una petición
  activa por recurso, pausa por visibilidad y borrador/ancla conservados.
  [Evidencia](evals/inbox-perf-03-2026-10-21/README.md): 123 pruebas API y 259 frontend
  únicas PASS en evidencia compuesta; build, lint, drift y Chromium escritorio/móvil
  PASS. JSON estable 52.002 → 303 bytes con 6.001 mensajes/50 cargados, índice
  existente y sin nueva migración. [Detalle D-5](decisions/2026-10-21-p60-perf03-cursors.md).
  M3, recepción/Meta y gates de seguridad siguen pendientes. Siguiente: WA-FIL-01.

- **Corte WA-FIL-01, 2026-10-21 — implementación local**: cuatro segmentos
  combinables con AND en servidor, antes de paginar y con cursor ligado al filtro.
  Cambiar segmento cancela GETs anteriores y conserva chat/borrador.
  [Evidencia](evals/inbox-fil-01-2026-10-21/README.md): 52 pruebas API y 119 frontend
  únicas PASS, build, lint y Chromium escritorio/móvil PASS. Un selector del harness
  corregido mediante repetición dirigida, conservando PASS válidos. Sin migración
  nueva ni aplicar M3. Siguiente: WA-SRCH-01; aceptación operativa y gates siguen pendientes.

- **Corte WA-SRCH-01, 2026-10-21 — implementación local**: búsqueda de contacto,
  teléfono y cliente vinculado en servidor, combinada con segmentos y páginas.
  Mínimo dos caracteres, debounce 250 ms, Ctrl/Cmd+K y Escape, con borrador y
  protección de cursores conservados. [Evidencia](evals/inbox-srch-01-2026-10-21/README.md):
  41 pruebas API y 134 frontend únicas PASS; build, lint y Chromium escritorio/móvil
  PASS. EXPLAIN 17,869 ms en 1.004 hilos; navegador/API sintética bajo un segundo.
  Error inicial de fixture conservado y corregido. Sin nueva migración ni aplicar
  M3. Recepción/Meta pospuesta por el usuario, pendiente real. Siguiente: WA-ASN-01.

---

## 5. Backlog completo con especificaciones

Formato por tarea: **ID — Nombre** · Prioridad · Tipo · Riesgo · Complejidad · Depende de → Objetivo / Estado actual / Estado deseado → Backend · Frontend · Base de datos · API → Tests · Edge cases → Acceptance criteria.

---

### FASE 0 — Seguridad y consistencia

#### WA-FIX-01 — Eliminar draft leak entre conversaciones

**P0 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada (hotfix)**

- **Objetivo**: que un texto sin enviar jamás pueda salir hacia el cliente equivocado.
- **Estado actual**: el clic en otra fila limpia `thread` y `selectedThread` pero **no `body`** (`index.jsx:570-579`). Escribir para Ana → clic en Beto → Enter = el texto de Ana sale a Beto. Único reset: tras envío exitoso (`index.jsx:358`).
- **Estado deseado**: cambiar de hilo descarta el borrador visible.
- **Frontend**: en el `onClick` de la fila añadir `setBody("")` junto a `setThread(null)`; actualizar el comentario explicativo (`index.jsx:571-573`). Opción futura optativa: memorizar borrador por hilo — explícitamente NO ahora.
- **BD/API**: no aplica.
- **Tests**: Vitest nuevo `pages/inbox/index.test.jsx`: escribir texto → clic en segundo hilo → textarea vacía; envío tras cambio usa el `sessionId` del hilo nuevo (mock de `api/inbox.js`).
- **Edge cases**: doble clic rápido entre dos hilos → un solo estado final; usuario sin permiso send → clear inocuo.
- **Acceptance**: [x] El texto no sobrevive al cambio de hilo (test). [x] Ningún otro camino conserva `body` entre hilos.

#### WA-FIX-02 — No descartar respuestas humanas en `_discard_if_superseded`

**P0 · Backend · Riesgo Medio · Complejidad S · Depende de: nada**

- **Objetivo**: que el drain anti-eco del turno nunca borre un mensaje redactado por personal humano.
- **Causa raíz**: `_discard_if_superseded` (`agent/worker.py:185-226`) hace UPDATE a `discarded` sobre todo out-pending creado tras el inicio del turno, filtrando solo por PK (`exclude(pk__in=before_ids)`), **sin filtrar `author_type`**. Secuencia de pérdida: cliente escribe → worker procesa turno → recepcionista responde (queda out-pending, `views.py:472-483`) → cliente escribe de nuevo antes del drain → la respuesta humana se descarta con `failure_reason='descartado: el cliente siguió escribiendo'`.
- **Estado deseado**: solo se descartan salientes del sistema (`author_type ∈ {agent, system}`); los de `human_staff` jamás. Los receipts (`semantic_type='operation_receipt'`) ya quedan fuera por la guarda temprana de tools (`worker.py:196-198`) y quedan blindados por el filtro de autor.
- **Backend**: `agent/worker.py` — añadir al UPDATE `.exclude(author_type=Message.AUTHOR_HUMAN)` (o filtro positivo `Q(author_type__in=[AGENT, SYSTEM])`).
- **BD/API**: no aplica.
- **Tests** (`apps/agent/tests/test_w1_experience.py`): (1) turno planner_reply + humano pending posterior al último inbound → humano queda `pending`, agent/system sí descartados; (2) turno con tools → early-return intacto (regresión); (3) caso existente sin humanos → comportamiento preservado.
- **Edge cases**: humano creado antes del turno (en `before_ids`) — ya excluido; carrera webhook vs drain — inmune (filtro por autor).
- **Acceptance**: [x] Test demuestra que un out-pending `human_staff` sobrevive al drain. [x] Pruebas dirigidas de Fase 0 verdes; suite integral `apps.agent --parallel 4` verificada: 769 OK, 1 skipped, system check sin issues.

#### WA-FIX-03 — Idempotencia server-side del envío del staff

**P0 · Backend+modelo · Riesgo Bajo · Complejidad M · Depende de: nada**

- **Objetivo**: que un reintento de red/UI no duplique un mensaje enviado a un cliente. Habilitante directo de WA-OPT-02.
- **Estado actual**: `send_message` (`views.py:439-499`) crea siempre Message nuevo; única guardia anti-doble-click es client-side. El patrón existe dos veces en el repo y CORS ya acepta el header.
- **Estado deseado**: frontend manda `X-Idempotency-Key` (uuid v4 por intento lógico, conservado en reintentos); replay devuelve el mensaje original.
- **Backend**: campo `Message.idempotency_key CharField(64, null=True, blank=True)` + `UniqueConstraint(['organization','idempotency_key'], condition=Q(idempotency_key__isnull=False) & Q(direction='out') & Q(author_type='human_staff'), name='message_unique_idempotency_per_org')` — espejo del patrón de `appointments/models.py:59-107`, acotado al autor del Inbox. En `send_message`: helper de lectura/truncado del header (igual a `appointments/services.py:521-524`), pre-check de replay humano, creación en `transaction.atomic()` con catch IntegrityError → fetch ganador → 201 con el original (respuesta idéntica).
- **Frontend**: `sendInboxMessage(sessionId, body, idempotencyKey)`; key generada en `handleSend` antes del await; reutilizada por el reintento local de OPT-02.
- **BD**: migración M1 (§7) — additive, sin backfill.
- **API**: POST `/api/inbox/conversations/{pk}/send/` + header opcional; la salida Inbox añade `client_message_id` read-only para correlacionar POST/replay/GET, sin aceptarlo como input.
- **Tests**: replay misma key → mismo `message.id`, 1 sola fila; keys distintos → filas distintas; sin header → behavior actual; misma key en otra org → sin colisión; carrera concurrente idéntica → path IntegrityError.
- **Edge cases**: key repetida con body distinto → gana el primero (documentar); header >64 chars → truncado.
- **Acceptance**: [x] `makemigrations --check` limpio. [x] Dos POST seguidos con misma key = 1 Message en DB, incluida carrera real PostgreSQL con dos respuestas 201 al mismo id.

---

### FASE 1 — «Deja de sentirse incompleto»

#### WA-UX-01 — Utilidad de tiempo org-aware compartida

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Objetivo**: que horas, «Hoy/Ayer» y tiempos relativos usen la zona de la clínica, no la del navegador del empleado.
- **Estado actual**: `fmtTime` local con TZ navegador y `toDateString()` (`index.jsx:57-64`). El backend ya entrega `organization_timezone` en `/api/me/` (`users/views.py:54`); existe `utils/datetime.js` (`formatDateTime(iso, tz)`) pero el inbox no lo usa.
- **Estado deseado**: módulo compartido (extender `utils/datetime.js` o crear `utils/inboxTime.js`) con: `orgTz(user)`, `fmtTimeOrg(iso,tz)`, `dayLabelOrg(iso,tz)` → «Hoy»/«Ayer»/fecha absoluta comparando días **locales de la org**, `relativeTimeOrg(iso,tz)` → «hace 5 min». El inbox elimina su `fmtTime` propio.
- **Frontend**: verificar qué guarda `authContext` del payload `/me/`; exponer `organization_timezone` en el objeto user si falta (`auth/authContext.jsx`, `auth/tokenStorage.js`). Reemplazar usos de `fmtTime`.
- **Tests**: unit de `dayLabelOrg`: cross-midnight (UTC 23:30 → America/Tijuana = «Ayer»), DST, formatos es-MX.
- **Edge cases**: TZ inválida en DB → defensivo fallback `America/Mexico_City`.
- **Acceptance**: [x] Cero usos de TZ-navegador/`toDateString()` en `pages/inbox/`. [x] Tests cross-midnight verdes.

#### WA-SEP-01 — Separadores de fecha Hoy/Ayer/fecha

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: WA-UX-01**

- **Estado actual**: sin división por día; hora por burbuja.
- **Estado deseado**: divisor centrado antes del primer mensaje de cada día local de la org: `Hoy`, `Ayer`, `12 ago`. Memo sobre `thread.messages`.
- **Frontend**: `groupMessagesByDay(messages, tz)` + componente `DateDivider`; render en el map de burbujas (`index.jsx:720-750`); CSS en `inbox.module.css`.
- **Tests**: unit agrupación (frontera medianoche org, 3 días, array vacío); render test con fixture.
- **Edge cases**: días intermedios sin mensajes → solo separadores de días presentes.
- **Acceptance**: [x] Transcript multi-día muestra divisores correctos en TZ org.

#### WA-TCK-01 — Ticks sent/delivered/read

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: `status` ya viaja; UI pinta solo `failed` («no entregado», title=`failure_reason`) y `pending` (`index.jsx:740-745`). BD tiene el ranking forward-only completo.
- **Estado deseado**: componente `DeliveryTicks({status})` para out: ✓ sent · ✓✓ delivered · ✓✓ read (color marca) · ⏱ pending (visible tras OPT-01/OPT-02) · ⚠ failed con tooltip. Accesible (aria-label).
- **Backend**: ninguno (0 líneas).
- **Tests**: render por estado; estados inbound no pintan ticks; out `discarded` histórico se trata como failed con reason.
- **Acceptance**: [ ] Código y pruebas render completados; validación E2E sandbox Meta pendiente para confirmar que el tick cambia a delivered/read al llegar el acuse, sin recarga manual.

#### WA-OPT-01 — Selector incluye out-pending del staff

**P0 · Backend · Riesgo Bajo · Complejidad S · Depende de: WA-FIX-03**

- **Estado actual**: `visible_messages` (`channels/selectors.py:38-43`) excluye todo out-pending → tu mensaje aparece 2–12 s después, cuando el sender lo manda; la rama «enviando…» de la UI es código muerto (`index.jsx:745`).
- **Estado deseado**: incluir `Q(direction=out, status=pending, author_type=human_staff)`. El pending agent/system sigue oculto hasta `sent` (el staff no debe ver borradores del bot que el superseded-drain puede descartar).
- **Backend**: `channels/selectors.py`. **Verificación obligatoria antes de merge**: grep de todos los consumidores de `visible_messages`; confirmar que el anti-eco de identidad usa `emitted_outbound` (función aparte, intacta).
- **Tests**: transcript incluye staff-pending (propio y de otros staff); NO incluye agent/system pending; NO incluye discarded/failed (regresión `test_inbox_threads.py`).
- **Acceptance**: [x] Tras POST /send/, el siguiente GET transcript devuelve el mensaje con `status=pending`.

#### WA-OPT-02 — Optimistic send en el composer

**P0 · Frontend · Riesgo Medio · Complejidad M · Depende de: WA-FIX-03 + WA-OPT-01**

- **Objetivo**: tu mensaje aparece al instante con ⏱, sin esperar al poll.
- **Diseño exacto**:
  1. `handleSend`: genera `clientKey = crypto.randomUUID()`; inserta al final del array local `{id:'tmp-'+n, body, direction:'out', author_type:'human_staff', status:'pending', created_at:new Date().toISOString(), _tmp:true}`; limpia composer YA; render con scroll anclado (ver HIST-02 para anclaje correcto; mientras tanto, scroll al fondo como hoy).
  2. POST con header `X-Idempotency-Key: clientKey`.
  3. Al 201: reemplazar/reconciliar el temporal por el Message real mediante
     `client_message_id` (la misma idempotency key devuelta por el backend), no
     por posición ni por un `_tmp` ambiguo.
  4. En error NO retryable (400 session_closed etc.): eliminar tmp + toast `apiError()`.
  5. En error de red/5xx: dejar el tmp visible marcado `failed-local` con botón «Reintentar» que reusa la MISMA key (FIX-03 evita duplicado).
  6. El poll de 10 s reconcilia por id del servidor y deduplica temporales
     **exclusivamente por `client_message_id`**; no usa heurísticas de
     body+ventana reciente.
- **Frontend/API**: `index.jsx` (`handleSend`, overlay optimista acotado por
  sesión), `api/inbox.js` (key idempotente y `AbortController`) y campo de salida
  `client_message_id` read-only en MessageSerializer; nunca se acepta como input.
- **Tests**: Vitest: envío exitoso muestra burbuja inmediata con ⏱ luego ticks; fallo 400 elimina tmp y muestra toast; fallo de red mantiene tmp + reintento no duplica (mock con misma key); poll concurrente no duplica el tmp.
- **Edge cases**: doble Enter rápido — segundo envío permitido (son dos mensajes legítimos, cada uno su key); cambio de hilo o unmount — `AbortController` cancela el request y la respuesta tardía no puede mutar otro hilo; reloj local adelantado — orden final lo fija el servidor.
- **Acceptance**: [x] Latencia percibida de aparición <100 ms. [x] Ningún camino duplica el mensaje tras reintento.

#### WA-CMP-01 — Composer auto-resize + contador de caracteres

**P2 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: CSS fijo `min-height:40px; max-height:120px; resize:none` (`inbox.module.css:241-251`); tope 4000 silencioso (`maxLength`, `index.jsx:758`).
- **Estado deseado**: auto-resize JS (`el.style.height='auto'; el.style.height=Math.min(el.scrollHeight, MAX)+'px'` en onChange), contador `1234/4000` que aparece >3600 chars y cambia a color advertencia cerca del tope.
- **Tests**: render test — escribir texto largo ajusta altura; contador visible cerca del límite.
- **Acceptance**: [x] Pegar 2000 chars no rompe layout; contador aparece al superar 3600, conforme al umbral especificado arriba. Ver [pruebas y capturas CMP-01](evals/inbox-cmp-01-2026-10-20/README.md).

#### WA-CPY-01 — Copiar mensaje / copiar teléfono / URLs clickeables

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: nada de esto existe; URLs en texto plano (`pre-wrap`).
- **Estado deseado**: hover sobre burbuja → acciones «Copiar» (navigator.clipboard + toast) ; header → botón «Copiar teléfono» y link `tel:` ; autolink de URLs en burbujas con `target="_blank" rel="noopener noreferrer"` (sanitizado: solo http/https).
- **Seguridad**: autolink implementado sin `dangerouslySetInnerHTML` (tokenizar texto plano → nodos React); nunca ejecutar formato HTML del proveedor.
- **Tests**: unit tokenizador URL; click-copiar llama clipboard y toast.
- **Acceptance**: [x] Pegar una URL en chat la hace clicable; copiar teléfono funciona. [Evidencia local CPY-01](evals/inbox-cpy-01-2026-10-20/README.md); no acredita gates Meta/operativos.

#### WA-TAB-01 — Título de pestaña con pendientes

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: título estático `SaaslyVet`; cero mutaciones de `document.title` en el repo.
- **Estado deseado**: `(N) SaaslyVet` donde N = hilos con `has_unanswered` del último poll de lista (dato existente). Restaurar título al foco de la ventana. v1 deliberadamente SIN sonido ni Notification API (ver §11 D-9).
- **Frontend**: efecto en `index.jsx` sobre `conversations` + listener `visibilitychange/focus`.
- **Tests**: unit del cálculo N; efecto actualiza document.title (jsdom permite).
- **Acceptance**: [x] Con 3 hilos sin responder en segundo plano, la pestaña muestra `(3)`. [Evidencia local TAB-01](evals/inbox-tab-01-2026-10-20/README.md).

#### WA-VIS-01 — Pausar polling con pestaña oculta

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: los polls siguen toda la noche con la pestaña en background (`index.jsx:281-293`).
- **Estado deseado**: con `document.hidden`, limpiar intervals; al volver a ser visible, refresh inmediato de lista y thread y re-armar polling. Implementación: hook compartido `usePollingWhenVisible(fn, ms)` (patrón nuevo mínimo, sustituye los dos setInterval inline; se inspira en `hooks/useDashboardSummary.js`).
- **Tests**: unit hook con mock de visibilitychange: oculto detiene, visible dispara fetch inmediato.
- **Acceptance**: [x] Cero requests de poll con pestaña oculta. [Evidencia local de red VIS-01](evals/inbox-vis-01-2026-10-21/README.md): frontend real, API sintética y visibilidad controlada.

#### WA-VER-01 — Badge de verificación del contacto

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: `contact_verification` viaja en threads/transcript (`views.py:907`) y solo condiciona el botón Reset; no se pinta.
- **Estado deseado**: badge junto al nombre en header y fila de lista: `Verificado` (staff_verified/confirmed_in_chat, badge-success), `Teléfono coincide` (phone_match), nada para unknown; tooltip con significado.
- **Tests**: render por nivel.
- **Acceptance**: [x] La UI distingue número desconocido, coincidencia de teléfono e identidad verificada. [Evidencia local VER-01](evals/inbox-ver-01-2026-10-21/README.md); la aceptación con recepción real continúa en el DoD.

#### WA-LDE-01 — Estados loading/error/reconexión en ambos paneles

**P1 · Frontend · Riesgo Bajo · Complejidad M · Depende de: VIS-01 (mismo refactor de polling)**

- **Estado actual**: lista: «Cargando…» texto plano y errores a consola (`index.jsx:264`); transcript: toast ante error de poll, sin estado persistente ni reconexión.
- **Estado deseado**: skeleton simple en lista (clase `.skeleton-block` existente en dashboard como referencia); banner inline persistente «Sin conexión — reintentando…» cuando fallan ≥2 polls seguidos, con botón «Reintentar ahora»; error state con EmptyState variante error. Sin cambiar contratos de API.
- **Tests**: mock de API que falla → banner visible; éxito posterior lo quita.
- **Acceptance**: [ ] Matando el backend, la UI muestra estado explícito y se recupera sola al volver.
  **Validación local PASS (21-10)** con peticiones abortadas y recuperación en
  Chromium; se conserva pendiente el ensayo contra backend real.

#### WA-AGT-01 — Indicador «el asistente está respondiendo»

**P1 · Backend+frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: `processing_until` existe en `Conversation` pero no se publica; recepción recibe 409 `turn_in_progress` sin entender por qué.
- **Estado deseado**: `ThreadSerializer`/transcript añaden booleano computado `agent_processing = processing_until and processing_until > now` (no exponer el timestamp crudo). Chip en header: «El asistente está respondiendo…». El chip deshabilita visualmente Tomar/Liberar con tooltip explicativo.
- **Backend**: `agent/serializers.py` (campo SerializerMethodField), sin migración.
- **Tests**: API — conversación con lease vigente → true; expirada → false.
- **Acceptance**: [x] Durante un turno activo, la UI explica quién tiene el turno. [Evidencia local AGT-01](evals/inbox-agt-01-2026-10-21/README.md). Proyección informativa; la autoridad sigue en TurnWork.

#### WA-GTF-01 — Botón «ir al final»

**P2 · Frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: único mecanismo de navegación es el salto forzado al fondo (`index.jsx:334-336`).
- **Estado deseado**: pill flotante «↓ Ir al final» visible cuando `scrollTop` está lejos del fondo (>200 px). La versión completa con «N nuevos mensajes» llega con HIST-02.
- **Nota**: este botón NO corrige aún el salto forzado (eso es HIST-02); solo da escape manual.
- **Tests**: visibilidad según posición de scroll (mock scrollHeight/clientHeight).
- **Acceptance**: [x] Leyendo arriba, hay forma de volver abajo sin recargar. [Evidencia local GTF-01](evals/inbox-gtf-01-2026-10-21/README.md); el anclaje completo sigue pendiente en HIST.

---

### FASE 2 — «Inbox profesional»

#### WA-PERF-01 — Eliminar N+1 y carga total en `list_threads`

**P1 · Backend · Riesgo Medio · Complejidad M · Depende de: nada**

- **Estado actual**: `list_threads` (`agent/views.py:758-815`) carga TODAS las conversaciones de la org a memoria, agrupa en Python y ejecuta ~2 queries extra por hilo (último mensaje `:794-798`, handoff abierto en `_thread_row :727-728`) → con 300 contactos ≈ 600 queries cada poll de 20 s por usuario. Irónicamente la vista deprecada sí usaba `Prefetch` correctamente (`views.py:77-92`).
- **Estado deseado**: misma respuesta exacta (`ThreadSerializer[]`), con: (1) anotación del último mensaje visible por conversación vía `Subquery` (id, body recortado a preview, direction/status para `has_unanswered`), (2) handoff abierto vía `Subquery`/`FilteredRelation`, (3) agrupación por bucket sin cargar episodios cerrados innecesarios (limitar a sesiones relevantes). Prohibido cambiar el shape del serializer en esta tarea.
- **Tests**: `assertNumQueries` acotado (≤ constante fija independiente del número de hilos) con ≥30 conversaciones seed; paridad de payload contra implementación anterior (test de caracterización previo: capturar respuesta JSON actual en fixture y comparar).
- **Edge cases**: hilos solo archivados; empates de `last_activity_at`; contacto sin mensajes.
- **Acceptance**: [x] Payload idéntico al actual en suite de caracterización. [x] Queries por request O(1) respecto a nº de hilos. [Evidencia local PERF-01](evals/inbox-perf-01-2026-10-21/README.md); esto no implica coste SQL ni latencia constantes.

#### WA-PERF-02 — Paginación real de la lista + fin del cap silencioso

**P1 · Backend+frontend · Riesgo Bajo · Complejidad M · Depende de: WA-PERF-01**

- **Estado actual**: `THREADS_CAP=100` trunca sin avisar (`views.py:815`); una clínica con 150 clientes cree que no hay más.
- **Estado deseado**: response `{results:[…], has_more:bool, next_offset}` con página de 100; frontend botón «Cargar más» (patrón append incremental existente en `EntitySearch.jsx:108-126` / `PetSidebar.jsx:88-98`). Mantener orden urgente→reciente dentro de la página.
- **API**: GET `/api/inbox/threads/?archived=&offset=` — backward compatible (sin offset → primera página + has_more).
- **Tests**: API 250 hilos → página 1 = 100 + has_more true; offset 200 → 50 + false; orden estable entre páginas.
- **Acceptance**: [x] Con >100 hilos todos son alcanzables y el aviso es explícito. [Evidencia local PERF-02](evals/inbox-perf-02-2026-10-21/README.md): 250 hilos en tres páginas, refresco acumulado y errores/reintentos verificados.

#### WA-HIST-01 — Historial completo: scroll-back con `next_before`

**P0 · Frontend · Riesgo Medio · Complejidad M · Depende de: nada (backend ya expone cursor)**

- **Objetivo**: poder leer **todo el historial de mensajes disponible y conservado por nuestro sistema para ese hilo**. Es el hallazgo #5 de la auditoría: feature gratuita atrapada en backend.
- **Alcance y límite del dato (definición explícita)**: «historial completo» significa *completo respecto a nuestra BD*, no respecto a WhatsApp. Nuestra BD conserva solo los mensajes recibidos desde la activación del webhook (con dedup wamid). Meta **no proporciona históricos anteriores**. D-1 retiene **los binarios de media** 180 días; no elimina el texto ni la fila del mensaje: después del vencimiento el chat conserva el mensaje/caption y muestra «archivo expirado». Conversaciones previas a la activación del Inbox simplemente no existen aquí. La UI debe comunicar el tope sin prometer de más: al agotar el cursor se muestra «Inicio del historial disponible», nunca «inicio de la conversación».
- **Comportamiento exacto**:
  1. Carga inicial: como hoy (página más reciente de 50 + metadatos).
  2. Al hacer scroll arriba hasta `scrollTop < 160px` y existir `thread.next_before`: fetch `getThreadMessages(c,a,{before: next_before})`.
  3. Insertar los mensajes nuevos AL INICIO del array, **dedupe por `id`** (Set), re-sort estable `(created_at,id)`.
  4. Preservar posición visual: capturar `scrollHeight` antes de render; tras render aplicar `scrollTop += (nuevoScrollHeight - scrollHeightAnterior)` (el clásico anchor-preserve; sin librerías).
  5. Spinner arriba (no overlay completo); ignorar scrolls adicionales mientras hay fetch en vuelo (guard `loadingOlderRef`).
  6. `next_before` nuevo = `data.next_before`; si null → mostrar «Inicio del historial disponible» y desactivar.
  7. Buffer máximo en memoria ≈ 500 mensajes: al superarlo, dejar de auto-cargar y mostrar botón manual «Cargar anteriores» (evita memoria ilimitada en hilos de años).
  8. Cambio de hilo → reset completo del estado local (mensajes, next_before, buffer).
- **Frontend**: refactor del estado del transcript en `index.jsx`: hoy `setThread(data)` reemplaza TODO el objeto cada 10 s — dividir en `threadMeta` (conversation/banners/next_before) y `messages[]` acumulativo.
- **Tests**: Vitest: 10/51/500 mensajes (mocks) — páginas correctas, sin duplicados, posición preservada (assert sobre scrollTop relativo); cursor inválido (400) → banner error, estado intacto.
- **Edge cases**: doble disparo del umbral en un frame (guard); cambio de hilo durante fetch en vuelo (abortar/aplicar solo si sigue seleccionado — comparar target); página que llega vacía pese a `next_before` (defensa: si 0 mensajes, poner next_before=null).
- **Acceptance**: [x] Hilo de 200 mensajes conservados: todo el historial disponible es legible, sin duplicados visibles, sin salto de posición al insertar. [x] Al agotar el cursor la UI dice «Inicio del historial disponible» (no promete historial de WhatsApp). [Evidencia local HIST-01](evals/inbox-hist-01-2026-10-21/README.md).

#### WA-HIST-02 — Merge de nuevos mensajes + anclaje de scroll + pill «N nuevos»

**P0 · Frontend · Riesgo Medio · Complejidad M · Depende de: WA-HIST-01**

- **Objetivo**: eliminar el defecto «salto forzado al fondo» (`index.jsx:334-336`) y fusionar llegadas del poll sin secuestrar la lectura.
- **Comportamiento exacto**:
  1. El poll de 10 s ya no reemplaza el array: hace merge union-sorted por `(created_at,id)` con dedupe por id (los tmp de OPT-02 se conservan hasta reconciliación).
  2. Detección «pegado al fondo»: `atBottom = scrollTop+clientHeight >= scrollHeight - 80` capturada ANTES de cada render de mensajes.
  3. Si atBottom → auto-scroll al fondo (como WhatsApp). Si no → NO tocar scroll; incrementar contador `newBelow` y mostrar pill flotante «↓ N mensajes nuevos»; click en pill = scroll suave al fondo + reset contador.
  4. Efecto único de scroll sustituye al `useEffect([length])` actual.
- **Tests**: Vitest: mensaje nuevo leyendo arriba → scroll intacto + pill con N correcto; pegado al fondo → autoscroll; ráfaga de 5 → N=5; click pill → fondo y N=0.
- **Edge cases**: usuario scrollea hacia abajo manualmente → pill se oculta cuando vuelve a bottom; mensajes históricos insertados por HIST-01 no cuentan como «nuevos» (solo llegadas posteriores a la carga inicial — comparar por id > maxId inicial).
- **Acceptance**: [x] Leyendo un mensaje de hace 3 meses, una llegada nueva NO mueve la vista y ofrece la pill. [Evidencia local HIST-02](evals/inbox-hist-02-2026-10-21/README.md): julio→octubre verificado en Vitest y Chromium escritorio/móvil.

#### WA-HIST-03 — Endpoint transcript con `around=<message_id>`

**P2 · Backend · Riesgo Bajo · Complejidad S-M · Depende de: nada (lo consumen RPL-06 y SRCH futura)**

- **Estado actual**: el cursor solo pagina desde lo más reciente; no hay forma de obtener una página centrada en un mensaje antiguo (necesario para jump-to-message de replies y resultados de búsqueda).
- **Estado deseado**: GET `/api/inbox/threads/{c}/{a}/messages/?around=<id>` devuelve la misma shape + `messages` = 25 anteriores + el mensaje (aunque hoy sea invisible por estado — incluirlo marcado) + 24 siguientes, ordenados cronológicos, con `has_older/has_newer`. Validar pertenencia al hilo/org; id inexistente o ajeno → 404 `{code:'not_found'}`. Mutuamente excluyente con `before` (400 si ambos).
- **Backend**: `agent/views.py` thread_messages — extensión del queryset existente con `Q(id__lte=id) | Q(id__gte=id)` ventanas.
- **Tests**: around centro/historia/inicio/fin; mensaje discarded incluido con su estado; cross-hilo → 404; tenant trap (otra org) → 404.
- **Acceptance**: [x] Página centrada correcta en los 5 puntos de corte probados.
- **Ejecución (2026-10-21)**: implementada y verificada localmente; 33 casos
  PostgreSQL únicos PASS. [Evidencia HIST-03](evals/inbox-hist-03-2026-10-21/README.md).

#### WA-UNR-01 — Read-state real del staff (backend)

**P1 · Backend+modelo · Riesgo Medio · Complejidad M · Depende de: nada**

- **Objetivo**: saber cuántos mensajes espera cada cliente y marcar lectura real por empleado.
- **Modelo nuevo** (app `agent`): `InboxReadState(OrganizationalModel)`: `user FK users.User PROTECT related_name='+'`, `contact FK agent.ContactIdentity PROTECT`, `channel_account FK channels.ChannelAccount PROTECT`, `last_read_message FK channels.Message SET_NULL null`, `updated_at auto_now`. UniqueConstraint `(organization, user, contact, channel_account)` + Index `(organization, user, updated_at)`. Clave por HILO (contacto+cuenta), coherente con la selección de la UI, no por episodio.
- **Semántica unread** (decisión D-3 en §11): `unread_count(thread, user)` = nº de inbound visibles del **episodio vigente** (`current conversation`) con `id > last_read_message_id`; sin fila de read-state → cuenta todo el inbound del episodio vigente (acotado; nunca el historial completo de sesiones pasadas).
- **API**:
  - GET `/api/inbox/threads/` añade `unread_count:int` por fila (calculado para el caller; batch con una query agregada, no N+1 — respetar PERF-01).
  - POST `/api/inbox/threads/{c}/{a}/read/` body `{last_read_message_id}` → upsert serializado; valida que sea un inbound visible del hilo y avanza de forma monótona. Un id anterior nunca retrocede el marcador ni revive unread; idempotente.
- **Permiso**: mismo `agentinbox.view` (leer estado propio no requiere claim).
- **Tests**: upsert idempotente; unread decrece tras read; dos usuarios con estados independientes; mensaje nuevo post-read sube el contador; un mark-read anterior no revive unread; mensaje no inbound/invisible se rechaza; cross-tenant trap; límite: read de mensaje de otra sesión del hilo permitido (es el mismo contacto).
- **Migración**: M3 (§7) additive; sin backfill (baseline implícita = todo el episodio vigente cuenta hasta primera lectura).
- **Acceptance**: [x] Dos recepcionistas ven contadores independientes y correctos.
- **Ejecución backend (2026-10-21)**: modelo, API y conteos verificados localmente,
  35 casos PostgreSQL únicos PASS y migración aditiva agent.0029 sin backfill.
  La integración visual corresponde a UNR-02; la base de trabajo no se ha migrado.
  [Evidencia UNR-01](evals/inbox-unr-01-2026-10-21/README.md).

#### WA-UNR-02 — Contador en lista + divider «Mensajes nuevos» + mark-read

**P1 · Frontend · Riesgo Bajo · Complejidad M · Depende de: WA-UNR-01 (+HIST-02 para divider)**

- **Estado deseado**:
  - Fila de lista: badge numérico (reemplaza/aumenta el punto binario `index.jsx:583`); total junto al filtro Activas.
  - Al abrir un hilo: POST read con el último inbound visible solo si `document.hasFocus()` y `document.visibilityState === 'visible'`; debounce 1,5 s para no martillar en ráfagas y cancelación si se pierde foco/visibilidad antes de vencer.
  - Transcript: línea divisoria «──── Mensajes nuevos ────» antes del primer mensaje con id > last_read_message_id al momento de abrir (calculada localmente al recibir datos; desaparece al marcar leído).
  - Si la ventana está oculta NO marcar leído (coherente con VIS-01) — así el contador sobrevive a la pestaña en background.
- **Tests**: abrir hilo dispara POST con id correcto; divider aparece/desaparece; pestaña oculta, ventana sin foco o pérdida durante debounce no marcan.
- **Edge cases**: usuario sin permiso send igualmente marca leído (view basta); fallo del POST read → reintento silencioso en siguiente poll, sin toast ruidoso.
- **Acceptance**: [x] Flujo completo: llega mensaje → contador sube → abro → divider visible → marco leído → contador baja.
- **Ejecución (2026-10-21)**: 125 pruebas frontend y 41 API PASS, build/lint y
  Chromium escritorio/móvil PASS. Foco/visibilidad controlados en el navegador;
  independencia y persistencia reales cubiertas en PostgreSQL.
  [Evidencia UNR-02](evals/inbox-unr-02-2026-10-21/README.md).

#### WA-FIL-01 — Filtros segmentados server-side

**P1 · Backend+frontend · Riesgo Bajo · Complejidad S · Depende de: WA-PERF-01**

- **Estado actual**: solo `archived`. La materia prima ya viaja y no se expone como filtro: `has_unanswered`, `handoff_priority`, `claimed_by`.
- **Estado deseado**: GET `/api/inbox/threads/?unanswered=1&urgent=1&claimed=me|<user_public_id>` — filtros combinables AND, aplicados sobre la agrupación (un hilo entra si su episodio vigente cumple). Frontend: chips de segmento sobre la lista: «Sin atender» / «Esperando cliente» / «Urgentes» / «Míos». Todo server-side (decisión de la auditoría §10); el filtrado cliente queda solo para estados transitorios.
- **Tests**: API cada filtro aislado y combinado; combinación con archived; sin resultados → 200 vacío.
- **Acceptance**: [x] Segmentos disponibles con un clic y filtrado en servidor, verificados localmente. [Evidencia FIL-01](evals/inbox-fil-01-2026-10-21/README.md): 52 pruebas API, 119 frontend únicas PASS y Chromium escritorio/móvil. El ensayo con recepción real sigue en el DoD global.

#### WA-SRCH-01 — Búsqueda fase 1 (contactos)

**P1 · Backend+frontend · Riesgo Bajo · Complejidad M · Depende de: WA-PERF-01, WA-FIL-01**

- **Estado actual**: cero búsqueda en todo el stack.
- **Estado deseado**: GET `/api/inbox/threads/?q=<texto>` — case-insensitive `icontains` OR sobre: `contact_display_name`, `contact external_id/phone_normalized` (normalizar dígitos del query), `owner__name` del owner vinculado. Sin búsqueda de contenido en esta fase (eso es SRCH-02). Frontend: input arriba de la lista + atajo `Ctrl/Cmd+K`, debounce 250 ms, mínimo 2 chars; estado vacío con sugerencia; ESC limpia.
- **Rendimiento**: 1 query con OR + select_related; índices existentes suficientes para volúmenes de clínica (<10k contactos); revisar plan EXPLAIN antes de merge.
- **Tests**: match por nombre/teléfono parcial/dueño; sin match → vacío; q corta ignorada; tenant isolation (nombre igual en org B no aparece); inyección — parámetro tratado como valor, nunca SQL.
- **Acceptance**: [x] Búsqueda de contacto/cliente disponible; ensayo local Chromium con API sintética bajo 1 s (509/389 ms). [Evidencia SRCH-01](evals/inbox-srch-01-2026-10-21/README.md): 41 pruebas API y 134 frontend únicas PASS, EXPLAIN real de PostgreSQL. La validación con recepción y latencia integrada real sigue pendiente y se pospone por instrucción del usuario.

#### WA-RETRY-01 — Reintento de mensajes fallidos

**P1 · Backend+frontend · Riesgo Medio · Complejidad M · Depende de: nada**

- **Estado actual**: out `failed` con `failure_reason`; sender solo reintenta pre-envío con backoff; tras failed no hay acción ni endpoint. Con ventana 24 h cerrada, todo sale failed («ventana de sesión de 24h cerrada», `worker.py:355-364`).
- **Estado deseado**:
  - Endpoint POST `/api/inbox/conversations/{pk}/messages/{message_id}/retry/` (permiso `agentinbox.send`). Valida: mensaje pertenece a la conversación/org, `direction=out`, `status=failed`. Si la ventana 24 h sigue cerrada → 400 `{code:'window_closed', suggestion:'call'}`. OK → reset `status=pending`, `attempts=0`, `next_attempt_at=now`, `failure_reason=''` vía servicio (no inline en view) y el sender existente lo toma.
  - Frontend: burbuja failed muestra botón «Reintentar» (usa misma idempotency-key original si existe) + si reason menciona ventana → hint «Ventana de WhatsApp cerrada — llámala al {teléfono}».
- **Concurrencia**: retry mientras el worker podría estar tocando la fila → hacer transición con `select_for_update` del Message.
- **Política D-7**: cualquier usuario con `agentinbox.send` puede reintentar aunque el autor sea otro. Se reutiliza la misma fila/carga no editable y la misma idempotency key. Log estructurado sin body: organización, conversación, mensaje, actor del retry, autor original y resultado.
- **Tests**: API feliz; actor distinto al autor original; contenido/idempotency intactos; ventana cerrada → 400 code correcto; mensaje no-failed → 400; cross-hilo/cross-org → 404; retry re-envía realmente (worker test); doble retry concurrente → una sola transición.
- **Edge cases**: retry de un mensaje cuyo wamid ya llegó como sent (carrera acuse tardío) → `record_status_update` forward-only lo corrige solo.
- **Acceptance**: [x] Mensaje con fallo conocido vuelve al sender con un clic; fallido por ventana sugiere llamar. Adaptación obligatoria al contrato B4 posterior: timeout/desconexión/aceptación ambigua permanecen UNCERTAIN, sin reintento por esta ruta. [Evidencia local](evals/inbox-retry-01-2026-10-21/README.md); envío del sender con proveedor simulado, no operación Meta real.

#### WA-WIN-01 — Ventana de 24 h visible

**P1 · Backend+frontend · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Estado actual**: `last_inbound_at` existe (`Conversation:170`) pero la UI nunca muestra la ventana; el staff descubre el límite cuando su mensaje rebota.
- **Estado deseado**: transcript/thread payload añade `session_window_open:bool` y `session_window_expires_at` (computados de `last_inbound_at`). Composer muestra banda sutil: «Respondes dentro de la ventana de 24 h · cierra en 7 h 12 min» cuando quedan <12 h, y estado deshabilitado con explicación cuando cerrada (coherente con RETRY-01). Cálculo de remaining en frontend desde el timestamp UTC.
- **Backend**: campos computados en serializer (sin migración).
- **Tests**: API open/closed/expirando; render de countdown.
- **Edge cases**: conversación archivada (current=null) → no aplica; reapertura por nuevo mensaje del cliente reinicia ventana (comportamiento existente).
- **Acceptance**: [x] El composer informa el vencimiento y bloquea texto libre con ventana cerrada; validado localmente en API, UI y Chromium. La validación final del sender y la aceptación operativa real siguen aplicando. [Evidencia](evals/inbox-win-01-2026-10-21/README.md).

#### WA-CTX-01 — Panel de contexto del cliente

**P1 · Backend+frontend · Riesgo Bajo · Complejidad M · Depende de: nada**

- **Objetivo**: al abrir un hilo ver quién es, sus mascotas y saltar al expediente — el caso #31 de la auditoría.
- **Estado actual**: header muestra owner_name + teléfono. Los datos existen en el SaaS (`patients.Owner`, mascotas, citas) y las rutas del expediente ya existen en el frontend.
- **Estado deseado**:
  - Backend: GET `/api/inbox/threads/{c}/{a}/context/` (permiso `agentinbox.view`) → `{owner:{public_id,name,phone}, pets:[{public_id,name,species}], last_appointment:{date,status}|null}` — compuesto SOLO si hay owner vinculado; org-scoped estricto (el owner debe pertenecer a la org del caller). Reutilizar serializers públicos de patients si existen; no duplicar modelos.
  - Frontend: panel lateral plegable (o drawer bajo el header) con esos datos + botón «Abrir expediente» (`navigate` a ruta existente de mascota/owner). Loading/error propios.
- **Tests**: API con owner/mascotas/última cita; sin owner → `{owner:null}`; owner de otra org vía manipulación de IDs → 404; permisos VET (view sí) / AGENT (403).
- **Decisión D-8 cerrada**: v1 expone owner, mascotas, última cita no clínica y enlace al expediente; NO trae historial clínico al Inbox. Una evolución futura podrá mostrar datos operativos vigentes (productos, servicios y precios) desde sus fuentes de verdad y con permisos explícitos, sin copiarlos al modelo del Inbox.
- **Acceptance**: [x] En ≤2 clics desde el chat abierto se llega al expediente correcto; verificado localmente en Chromium escritorio y móvil con datos sintéticos. [Evidencia](evals/inbox-ctx-01-2026-10-21/README.md). La prueba real con recepción de §13 sigue pendiente.

#### WA-PERF-03 — Polling incremental con cursor de cambios

**P1 · Backend+frontend · Riesgo Medio · Complejidad L · Depende de: PERF-01, PERF-02, HIST-02 · Implementa D-5**

- **Objetivo**: mantener la bandeja actualizada sin descargar de nuevo listas y transcripts completos, preservando el polling como estrategia realtime v1.
- **Cursor**: token opaco emitido por el servidor, acotado a organización/usuario/filtros y compuesto por watermarks `(updated_at,id)`; nunca timestamp del cliente ni `created_at` solo. Empates de timestamp se resuelven por id. Token inválido, expirado o de otro scope → `400 {code:'invalid_sync_cursor'}` y el frontend hace refresh completo.
- **Lista**: GET `/api/inbox/threads/?since=<token>` devuelve `{mode:'delta', sync_cursor, upserts:[Thread], removals:[thread_key]}`. Incluye cambios por mensaje nuevo, cambio de status/último mensaje, unread, claim/assign/close/release y archivo/desarchivo; respeta los filtros de la consulta que originó el token.
- **Transcript**: GET `/api/inbox/threads/{c}/{a}/messages/?since=<token>` devuelve mensajes nuevos **y mensajes existentes modificados** (ticks/failure/retry/media), más metadatos de conversación cambiados. No reemplaza `before`/`around`: es el canal incremental de la página reciente.
- **Autoridad de cambios**: `updated_at` debe avanzar en todos los writes relevantes. Auditar `QuerySet.update()` —que omite `auto_now`— y escribir `updated_at=now` explícitamente o pasar por un servicio único. Añadir índices `(organization, updated_at, id)` si EXPLAIN demuestra que los heredados no alcanzan.
- **Frontend**: merge por id/thread_key, dedupe, removals explícitos y preservación del scroll. Solo un poll en vuelo por recurso; cambio de hilo invalida la respuesta anterior. `visibilityState !== 'visible'` pausa/reduce y al volver intenta delta; cualquier inconsistencia cae a full refresh.
- **Tests**: nuevo mensaje; status de mensaje existente; claim/assign/close; dos cambios con mismo timestamp; cursor inválido/cross-user/cross-org; delta durante scroll-back; cambio de hilo con fetch en vuelo; merge sin duplicados; fallback full; pestaña oculta no martilla red.
- **Acceptance**: [x] Tras estabilizar la UI, los polls normales transfieren solo cambios sin perder ticks, mensajes o removals. [x] Polling completo queda como recuperación, no como camino frecuente. Verificación local en PostgreSQL y Chromium escritorio/móvil, con recuperación explícita y retorno a delta. [Evidencia](evals/inbox-perf-03-2026-10-21/README.md); recepción y Meta reales siguen pendientes.

#### WA-ASN-01 — Asignación explícita a colega

**P2 · Backend+frontend · Riesgo Medio · Complejidad M · Depende de: UNR-01 (misma familia de cambios de claim)**

- **Estado actual**: solo auto-claim (responder = tomar) y Tomar manual; no existe «asignar a María».
- **Estado deseado**: POST `/api/inbox/conversations/{pk}/assign/` body `{user_public_id}` (permiso `agentinbox.claim`) → setea `claimed_by` al objetivo con las mismas garantías de lock que claim. El objetivo debe estar activo, pertenecer a la misma organización y tener `agentinbox.send`; si ya tiene otra asignada no bloquea (asignaciones múltiples permitidas v1). En v1 la persona asignada lo ve en el próximo poll; push/notificación queda en el backlog futuro de D-9, no en Fase 4.
- **Frontend**: selector «Asignar a…» en header (lista de usuarios con permiso send — requiere endpoint existente de usuarios o añadir `assignable_users` al thread context; verificar qué expone hoy `/api/users/`).
- **Auditoría**: log estructurado sin PII con conversación, actor, asignado anterior, destino y timestamp.
- **Tests**: assign feliz; usuario inactivo/sin permiso/cross-tenant → 400/404 según contrato; carrera assign vs claim concurrente → lock decide, sin corrupción; auditoría contiene actor/from/to.
- **Acceptance local**: [x] Asignación a colega activa con permiso send DB, lock
  compartido con claim, auditoría tras commit y selector con borrador conservado.
  20 pruebas API PostgreSQL y 25 frontend únicas PASS, build/lint y navegador
  escritorio/móvil PASS. [Evidencia ASN-01](evals/inbox-asn-01-2026-10-21/README.md).
  **Aceptación operativa**: [ ] Recepción puede derivar un caso a la veterinaria
  en la validación real, pospuesta por el usuario; no se inventa acuse ni push.

---

### FASE 3A — Replies end-to-end

Requisito declarado por la auditoría (§8): replies es **cambio de modelo**, no UI decorativa. Cadena completa: webhook `context.id` → `Message.reply_to` → serializer → API → composer → preview → jump.

#### WA-RPL-01 — Modelo: `Message.reply_to`

**P1 · Modelo · Riesgo Bajo · Complejidad S · Depende de: nada**

- **Cambio**: `reply_to = models.ForeignKey('self', null=True, blank=True, on_delete=PROTECT, related_name='direct_replies')` en `channels/models.py` + Index `['reply_to']`. Elección PROTECT: los mensajes nunca se borran físicamente (estados soft), y una referencia rota sería peor que bloquear el borrado.
- **Migración**: M2 (§7), additive, sin backfill.
- **Tests**: modelo acepta null; FK protege; constraint org no aplica a self-FK (verificar con test de dos orgs que un reply cross-org se rechaza a nivel servicio, no DB).
- **Acceptance local**: [x] `makemigrations --check --dry-run` limpio; M2 generada
  y ensayada en PostgreSQL temporal, sin backfill y con writers previos/nuevos.
  19 pruebas únicas PASS (14 nuevas, cinco afectadas), Django check PASS.
  [Evidencia RPL-01](evals/inbox-rpl-01-2026-10-21/README.md).
  **Aplicación real**: [ ] migración aplicable sin downtime en la release real;
  M2 aún sin aplicar a las bases habitual/preview, sin despliegue ni activación.

#### WA-RPL-02 — Webhook: parsear `context.id` y resolver referencia

**P1 · Backend · Riesgo Medio · Complejidad M · Depende de: WA-RPL-01**

- **Estado actual**: `_process_payload`/`_extract_body` (`channels/views.py:94-163`) ignoran `msg.context`.
- **Estado deseado**: si `msg.context.id` existe → resolver contra `Message.external_message_id` del mismo `channel_account` (cualquier dirección; normalmente será nuestro out). Encontrado → pasar `reply_to` a `ingest_inbound_message` (extender firma con kwarg opcional). No encontrado → log estructurado WARNING `INBOUND_REPLY_UNRESOLVED` (sin PII del body) y continuar con `reply_to=None`: **nunca inventar la cita**.
- **Nota**: `ingest_inbound_message` vive en `agent/services.py:324+`; mantener dedup wamid intacto (un webhook duplicado con context debe re-idempotir igual).
- **Tests**: inbound citando out existente → reply_to seteado; citando wamid inexistente → null + warning; citando mensaje de otra cuenta/canal → null (resolver SIEMPRE scoped al channel_account); webhook duplicado → sin doble efecto.
- **Edge cases**: reply a un mensaje discarded → referencia válida igualmente (el estado se muestra en UI como «no enviado»); reply a media aún sin pipeline → referencia válida, contenido pendiente de MED.
- **Acceptance local**: [x] Webhook firmado de cliente citando un mensaje nuestro
  persiste `Message.reply_to`; 40 pruebas PostgreSQL únicas PASS (21 nuevas y 19
  afectadas), drift/Django check PASS. Casos sin destino y dedup/carrera real
  conservan el entrante y las garantías B1.
  [Evidencia RPL-02](evals/inbox-rpl-02-2026-10-21/README.md).
  **Meta real**: [ ] recepción de una cita real validada; pospuesta por el usuario.

#### WA-RPL-03 — API: enviar con `reply_to_id` + exponer cita en serializer

**P1 · Backend · Riesgo Bajo · Complejidad S · Depende de: WA-RPL-01**

- **Cambios**:
  - `SendMessageSerializer` añade `reply_to_id: IntegerField(required=False, min_value=1)`.
  - `send_message`: si presente, validar que el Message exista en la MISMA org y mismo hilo `(contact, channel_account)` — query scoped; inválido → 400 `{code:'invalid_reply_target'}`. Setear `message.reply_to`.
  - `MessageSerializer` añade objeto anidado `reply_to: {id, author_type, human_author_name, payload_type, excerpt(80 chars de body), status}` calculado con select_related (evitar N+1: los mensajes de una página comparten pocos targets; usar prefetch puntual). Si el target existe pero su cuerpo está vacío/discarded → incluir `status` para que la UI diga «mensaje no enviado».
- **Tests**: send con target válido → 201 con reply_to poblado; target de otro hilo → 400; target inexistente → 400; transcript serializa cita sin queries descontroladas (assertNumQueries acotado).
- **Acceptance local**: [x] Roundtrip API completo: POST con reply_to_id → GET
  transcript devuelve la cita. 42 pruebas PostgreSQL únicas PASS (25 nuevas, 17
  afectadas), con idempotencia/race/retry, lecturas históricas y deltas sin N+1.
  Drift/Django check y EXPLAIN con índice existente PASS.
  [Evidencia RPL-03](evals/inbox-rpl-03-2026-10-21/README.md). No acredita aún
  composer/burbujas ni cita nativa en el payload Meta; ver prerrequisito RPL-07.

#### WA-RPL-05 — Composer de respuesta (seleccionar mensaje a citar)

**P1 · Frontend · Riesgo Bajo · Complejidad M · Depende de: WA-RPL-03**

- **Estado deseado**: hover sobre burbuja → menú contextual «Responder» (v1 solo responder + copiar de CPY-01). Al activar: chip sobre el composer con autor + extracto 1 línea + ✕; Escape o ✕ cancelan; Enter envía incluyendo `reply_to_id`. Solo un reply activo a la vez. Deshabilitar Responder sobre tmps propios optimistic.
- **Frontend**: estado `replyTarget` en `index.jsx`;
  `sendInboxMessage(sessionId, body, key, {signal, replyToId})`. El ID se integra en
  las opciones existentes para conservar compatible la cancelación del cuarto argumento.
- **Tests**: seleccionar → chip visible; cancelar limpia; envío incluye id; cambio de hilo cancela replyTarget (coherente con FIX-01).
- **Acceptance local**: [x] Flujo hover/foco/táctil → responder → enviar, con
  cancelación y cita aislada por hilo. 61 pruebas frontend únicas PASS (27 nuevas,
  34 afectadas), build, lint y Chromium escritorio/móvil PASS con API sintética.
  [Evidencia RPL-05](evals/inbox-rpl-05-2026-10-21/README.md). No acredita todavía
  citas en burbujas, salto al original ni payload nativo Meta.

#### WA-RPL-04 — Cita en burbujas entrantes y salientes

**P1 · Frontend · Riesgo Bajo · Complejidad S · Depende de: WA-RPL-02 + WA-RPL-03 + componente de WA-RPL-06**

- **Estado deseado**: cualquier burbuja (in u out) con `reply_to` pinta dentro el bloque de cita (borde izquierdo, autor label existente, extracto, 📷 si payload_type≠text, «mensaje no enviado» si status∈{discarded,failed}).
- **Tests**: render de cita de texto/media/no-disponible/inexistente (target null tras unresolved → NO pintar bloque).
- **Acceptance local**: [x] Citas entrantes/salientes con autor, extracto, media,
  estado no enviado y ausencia de bloque para target null. Integrada con RPL-06
  como conjunto mínimo pulsable. 128 pruebas frontend únicas PASS (45 nuevas,
  83 afectadas), build, lint y Chromium escritorio/móvil PASS con API sintética.
  [Evidencia RPL-06/04](evals/inbox-rpl-06-04-2026-10-22/README.md).

#### WA-RPL-06 — Jump-to-message con fetch `around`

**P2 · Frontend · Riesgo Medio · Complejidad M · Depende de: WA-HIST-03 + WA-RPL-03**

- **Comportamiento exacto** (diseño auditoría §7.4/§8.5):
  1. Click en cita → buscar `id` en mensajes cargados.
  2. Presente → scroll suave + highlight visual 2 s (clase CSS temporal).
  3. Ausente → GET `?around=<id>` → insertar página al array con merge/dedupe de HIST-01 → scroll + highlight. Preservar posición según reglas HIST-02 (la inserción es intencional: scroll dirigido, pill no interfiere).
  4. Target descartado/failed → highlight igual + la cita ya dice «no enviado»; nunca simular contenido.
- **Tests**: caso cargado/ausente/descartado; merge no duplica solapamiento de páginas.
- **Acceptance local**: [x] Click/teclado/táctil sobre cita carga el destino con
  around si falta, fusiona sin duplicados y centra/enfoca/resalta dos segundos.
  Conserva borrador, cadena before y floor ampliado; cancela búsquedas anteriores,
  evita reemplazos tardíos del poll y respeta el estado descartado/fallido.
  128 pruebas frontend únicas PASS, build, lint y Chromium escritorio/móvil PASS
  en la [evidencia conjunta RPL-06/04](evals/inbox-rpl-06-04-2026-10-22/README.md).
  No acredita todavía el contexto nativo del proveedor ni la matriz final RPL-07.

#### WA-RPL-07 — Suite de edge cases de replies

**P1 · Tests backend+frontend · Depende de: RPL-01..06**

**Prerrequisito de implementación detectado el 21-10 al cerrar RPL-03:** el sender
y el adaptador Meta actuales solo pasan `to`/`body`, sin contexto de cita. Conectar
la referencia al payload del proveedor y probarla antes de acreditar esta matriz
como end-to-end, sin cambiar guards de admisión/retry/uncertainty B4. Es trabajo de
implementación pendiente, separado del gate Meta real pospuesto por el usuario.

Matriz mínima (backend API tests + Vitest):
1. Reply a mensaje cargado ✓ visible.
2. Reply a mensaje antiguo fuera de las últimas 50 → around lo trae.
3. Reply a media (post-MED: cita con tipo; pre-MED: «contenido no disponible»).
4. Reply a mensaje discarded → «mensaje no llegó a enviarse».
5. Reply a mensaje failed → ídem con reason.
6. Reply a wamid inexistente (cliente citó algo que no pasó por nosotros) → sin bloque, sin error.
7. Reply cross-hilo rechazado 400; cross-org 404.
8. Doble envío rápido del mismo reply con misma key → un solo mensaje.
9. Webhook duplicado del inbound-reply → sin duplicar relación.

**Acceptance local (22-10)**: [x] Contexto nativo tras admisión y matriz
completa, conservando guards B4 y evidencias RPL-01..06. 170 pruebas PostgreSQL y 257 frontend únicas PASS.
[Evidencia fase 3](evals/inbox-phase3-2026-10-22/README.md). Meta real aplazada.

---

### FASE 3B — Media entrante (pipeline completo)

Estado anterior a MED (histórico): el webhook guardaba solo `{type,timestamp}` y descarta media-id/caption/filename/mime (`views.py:143-155`). **No existe stack de storage en todo el backend** (0 FileField/MEDIA_ROOT). Las URLs del Graph API expiran → bajar el binario es obligatorio, no opcional.

#### WA-MED-01 — Modelo `MessageMedia` + ADR de storage

**P1 · Modelo+ADR · Riesgo Medio · Complejidad M · Depende de: ADR p60 (D-1/D-2 cerradas) y gates de privacidad/proveedor satisfechos**

- **Modelo** (app `channels`, junto a Message): `MessageMedia(OrganizationalModel)`:
  - `message OneToOneField(Message, PROTECT, related_name='media')`
  - `provider_media_id CharField(128)` + UniqueConstraint parcial `(channel_account, provider_media_id)` — dedup tipo wamid
  - `mime_type CharField(100)`, `file_size PositiveBigIntegerField null`, `filename CharField(255, blank)` (documentos), `sha256 CharField(64, blank)`
  - `file = FileField(upload_to='inbox-media/%Y/%m/', storage=media_storage(), max_length=500)` — `media_storage()` selecciona backend por entorno: `MEDIA_BACKEND=local` (default dev/CI, `FileSystemStorage` privado fuera de rutas públicas) o `b2` en producción (Anexo D-2), detrás de una interfaz común
  - `status choices pending|downloading|ready|failed|expired default pending`, `error CharField(200, blank)`, `attempts PositiveSmallInt default 0`
  - `expires_at DateTimeField null`, `expired_at DateTimeField null`: 180 días desde la persistencia operativa. Al expirar se limpia `file`/object key y se conserva la fila tombstone para renderizar «Archivo expirado».
  - `duration_ms null` (audio/video), `width/height null int` (imágenes/video si Meta las trae)
  - Índices: `(organization, status)`, `(message)`
- **ADR aprobado**: [p60](decisions/2026-08-22-p60-whatsapp-inbox-decisions.md) fija B2 operativo en producción, backend local en dev/CI, bucket y Application Key dedicados, servido Django-auth, límites por tipo y retención física de media a 180 días. **Gate de producción**: aviso de privacidad/ARCO actualizado, transferencia internacional documentada y DPA de Backblaze archivado.
- **Migración**: M4 (§7).
- **Expiración D-1 y reconciliación**: job nocturno idempotente toma filas
  `ready` con `expires_at<=now`, deja de servirlas, elimina/limpia la referencia
  al objeto operativo, marca `expired` y registra evento sin PII. También repara
  drift verificable: una fila `expired` que aún tenga key vuelve a intentar la
  purga; un objeto ausente prematuramente se registra como inconsistencia sin
  fingir expiración. Lifecycle B2 elimina físicamente versiones/hide markers y
  funciona como enforcement independiente. El bucket de media no usa Object
  Lock, incompatible con ARCO/borrado anticipado.
- **Tests**: constraints (dedup provider_media_id por cuenta), estados, clean
  org, cálculo de 180 días, idempotencia/reintento del reconciliador, drift
  fila↔objeto y dos ejecuciones concurrentes sin doble purga.
- **Acceptance local**: [x] Storage conforme al ADR p60 aceptado. [x] M4
aditiva generada y aplicada en PostgreSQL temporal. No aplicada a base habitual;
privacidad/B2/lifecycle reales pendientes. [Evidencia](evals/inbox-phase3-2026-10-22/README.md).

#### WA-MED-02 — Webhook: parsear media + caption

**P0 (pérdida de datos) · Backend · Riesgo Medio · Complejidad M · Depende de: WA-MED-01**

- **Cambios en `_extract_body`/`_process_payload` (`channels/views.py:94-163`)**:
  - Para `image/document/audio/video/sticker`: extraer `id` (media id), `mime_type`, `filename`, `sha256`, y **`caption`** (image/document/video). Crear `MessageMedia(status='pending')` atado al Message nuevo. `payload_type` se preserva como hoy.
  - **Caption → `body`**: si hay caption, guardarla en `Message.body` (así fluye a previews, búsqueda futura y al prompt del agente). El texto de la foto deja de perderse aunque la descarga falle.
  - Mantener ACK <1 s: crear fila pending es O(1); la descarga NUNCA ocurre en el request (eso es MED-03).
  - `raw_metadata` conserva el payload crudo completo del mensaje (hoy recorta a `{type,timestamp}`) para auditoría/debug — respetando R15 en logs, no en DB (DB ya guarda bodies igualmente).
- **Tests**: imagen con caption → body=caption + media pending con provider id; documento con filename; audio ogg; sticker; mensaje duplicado → NO crea segunda media (unique); webhook malformado sin media id → message normal type preserved, sin media row.
- **Acceptance local**: [x] Los cinco tipos conservan referencia pending,
caption y raw completo; dedup y carreras verificadas. Sin HTTP en webhook.
[Evidencia](evals/inbox-phase3-2026-10-22/README.md).

#### WA-MED-03 — Worker de descarga de media

**P1 · Backend · Riesgo Alto (HTTP largo) · Complejidad L · Depende de: WA-MED-02**

- **Diseño**: paso dentro del worker existente `run_agent_worker` como tercer ciclo `download_pending_media(batch)`:
  1. Seleccionar medias `pending|failed` con `attempts<5` y backoff vencido, `select_for_update(skip_locked)`.
  2. `GET {WHATSAPP_API_BASE_URL}/{provider_media_id}` con Bearer → devuelve URL firmada TEMPORAL (expira) → inmediatamente fetch binario con timeout 30 s y tope de tamaño (D-2, propuesto 25 MB).
  3. Descargar a un spool temporal del SO con tope estricto, calcular sha256 y subir al backend FileField. En producción B2 es canónico; el spool se borra en `finally` tanto en éxito como en fallo. Un scavenger periódico, limitado al directorio/prefijo dedicado de media, elimina spools huérfanos más antiguos que el tiempo máximo de ejecución + margen tras un crash; registra conteo/bytes sin nombres ni PII y nunca recorre rutas generales del VPS.
  4. Error retryable (red/5xx/429) → attempts+1 + backoff exponencial; agotados → `status=failed, error=...` + log estructurado `MEDIA_DOWNLOAD_FAILED`. La fila queda como evidencia de que hubo archivo (nunca silencio).
  5. Media huérfana cuyo Message fue descartado → descarga igual (barato, mantiene historial íntegro).
- **Riesgo controlado**: el HTTP largo vive en el worker (no en webhook ni web); batch pequeño evita saturación; SKIP LOCKED permite paralelizar futuros workers.
- **Tests** (Graph API mockeada): feliz imagen/audio/pdf; URL expirada entre llamada 1 y 2 → reintento; 404/410 permanente → failed; tamaño > tope → failed con error claro; crash a mitad → estado consistente y scavenger limpia; éxito/fallo no dejan spool; dos workers concurrentes → SKIP LOCKED sin doble descarga.
- **Acceptance local**: [x] Descarga/checksum, SDK B2 simulado, reintentos,
leases, spool, purga de versiones y drift verificados. [ ] Persistencia y
lifecycle en B2 real (gate previo a producción). Backend local solo dev/CI.
[Evidencia](evals/inbox-phase3-2026-10-22/README.md).

#### WA-MED-04 — Servido autenticado org-scoped

**P0 (seguridad) · Backend · Riesgo Alto · Complejidad M · Depende de: WA-MED-03**

- **Endpoint**: GET `/api/inbox/media/<public_id>/` (permiso `agentinbox.view`). Flujo: resolver media org-scoped (`for_organization`) → 404 si no → si está vencida devolver 410 `{code:'media_expired'}` → validar permiso → `FileResponse` streaming con mime correcto y `Content-Disposition` (inline para imagen/audio/video/pdf; attachment resto) + filename original saneado. **Jamás URL pública ni media en static**.
- **Multi-tenancy explícito**: un usuario de org B que adivine el public_id de org A obtiene 404 (mismo gate `test_tenant_scoping_audit`). PublicIdMixin heredado.
- **Performance**: FileResponse streaming Django v1 (volumen de clínica lo soporta); optimización X-Accel-Redirect/Alias de Caddy registrada como mejora posterior, no bloqueante.
- **Tests**: feliz inline/attachment; expirada → 410 explícito; cross-org → 404; sin permiso view → 403; objeto ausente inesperadamente → 404 limpio + log ERROR; mime spoofing — se sirve el mime almacenado, no el del request.
- **Acceptance local**: [x] Matriz API 403/404/409/410/503 y streaming
autenticado, sin lectura cross-org ni URL pública. [ ] Prueba con staff y
proveedor reales. [Evidencia](evals/inbox-phase3-2026-10-22/README.md).

#### WA-MED-05 — Render de media en transcript y lista

**P1 · Frontend · Riesgo Bajo · Complejidad M · Depende de: WA-MED-04**

- **Comportamiento**:
  - Transcript: imagen → `<img>` con lazy-load desde endpoint auth (fetch con axios→blob→objectURL, porque `<img src>` no manda Bearer header; cachear objectURL por id en un Map módulo-level); click → lightbox simple (modal existente). Audio → `<audio controls>` nativo (ogg/opus: Chrome/Edge sí, Safari viejo no — aceptar). Video → `<video controls>`. Documento → tarjeta filename + tamaño + botón descargar (blob download). Sticker/otros → icono + tipo.
  - Estados: placeholder spinner mientras baja; error → «No se pudo cargar el archivo» con reintentar; media failed del pipeline → «Archivo no disponible (falló la recepción)»; 410/status expired → «Archivo expirado» sin retry infinito.
  - Caption renderizada debajo del archivo como parte de la burbuja.
  - Lista: preview muestra `📷 Foto`, `📄 {filename}`, `🎤 Nota de voz` en vez de `[image]`.
- **Frontend**: componente `MediaBubble({message})`; helper `useMediaUrl(publicId)`; extender `last_message_preview` si el backend manda payload_type (ya viaja en MessageSerializer; ThreadSerializer preview viene de body — con MED-02 las captions llenan body, los archivos sin caption mostrarán vacío → frontend compone por payload_type del último mensaje: añadir `last_message_type` al ThreadSerializer en esta tarea, campo barato).
- **Tests**: Vitest con mocks de blob: render tipos, error/retry, expirado sin retry, caption visible; lista con previews tipadas.
- **Edge cases**: archivo enorme en móvil (indicar peso antes de bajar auto — imágenes sí autoplay-lazy, video/documento SOLO bajo clic, nunca auto-descarga pesada); sesión expirada a mitad de descarga → 401 handler global existente redirige.
- **Acceptance local**: [x] Tipos/caption/previews, lightbox, carga manual
y lifecycle de blobs verificados con Vitest y Chromium escritorio/móvil.
[ ] Cliente real manda foto y recepción la ve tras el poll (validación pospuesta).
[Evidencia](evals/inbox-phase3-2026-10-22/README.md).

#### WA-MED-06 — Media saliente básica (imágenes/documentos) — OPCIONAL

**P2 · Backend+frontend · Riesgo Medio-Alto · Complejidad L · Depende de: MED-04 estable**

- Alcance mínimo: upload staff (multipart ≤ límite D-2, whitelist mime image/*+pdf) → storage privado temporal → provider upload Graph API `/{phone_number_id}/media` → send por media_id reutilizando ventana 24 h/backoff del sender. Botón 📎 en composer con preview antes de enviar. Fuera de alcance v1: video saliente, stickers, audio, plantillas con header media.
- Tests: pipeline completo mockeado; rechazo por tipo/tamaño; fallo de upload → retryable según código; media huérfana subida nunca enviada → limpieza por cron nocturno (jobs Procfile ya existen).

---

### FASE 4 — Polling incremental v1; realtime diferido

#### WA-RT-00 — Reevaluación futura de SSE vs polling mejorado

**DIFERIDA · Análisis futuro (entregable: memo + nueva decisión) · Complejidad M · Depende de: PERF-03 estable y evidencia de necesidad**

- **Decisión vigente D-5**: NO-GO a SSE en v1. Gunicorn opera con capacidad síncrona limitada y cada stream abierto consumiría un worker/thread; Redis disponible no elimina ese cuello de botella HTTP.
- **Implementación v1**: polling correcto en esta secuencia: `poll → merge → dedupe → preserve scroll → pill de nuevos`, con `?since` (PERF-03) y pausa/reducción al ocultar la pestaña (VIS-01).
- **Disparador de reevaluación**: evidencia en producción de que la latencia del polling sigue causando fallos operativos, junto con medición de staff/pestañas concurrentes y presupuesto de capacidad. El memo deberá comparar ASGI/servicio dedicado frente a ampliar Gunicorn; un eventual GO requiere ADR p61.
- **Límite de esta ficha**: entrega únicamente medición y un memo de decisión. No
  define endpoint, eventos, autenticación, toggle, publisher, hook ni pruebas de
  implementación. Los identificadores `WA-RT-01..03` quedan reservados, sin
  tareas ejecutables ni contrato técnico, hasta que un ADR p61 acepte un GO y
  vuelva a estimarlos. Ningún PR v1 puede implementarlos tomando este plan como
  autorización.

---

### FASE 5 — Operación a escala (solo con evidencia)

#### WA-VIRT-00 — Umbral de virtualización del transcript

**P3 · Análisis · Complejidad S**

- Verificación solicitada por el prompt: ¿aplica «~300 mensajes montados»? Con el diseño resultante: página de 50, buffer auto ≈ 500, cada burbuja ≈ 4-6 nodos DOM → peor caso ~3.000 nodos. React con keys estables maneja eso, pero el merge por poll re-renderiza la lista completa (sin store normalizado). **Regla de decisión**: medir con React DevTools Profiler un thread de 500 mensajes; si commit de merge >16 ms en hardware de clínica o jank perceptible → virtualizar (`react-window`, ventana fija) + store normalizado (map por id). Si no → registrar medición y posponer. NO virtualizar por moda.

#### WA-PRES-01 — Presencia multiagente

**DIFERIDA · P2 · Backend+frontend · Complejidad L · Depende de: eventual ADR p61 con SSE GO**

- «X está escribiendo/viendo este hilo»: heartbeats del cliente (throttle 5 s) → Redis TTL → expuesto en thread payload/SSE. Sin nueva tabla persistente. Requiere realtime para ser útil; sin él, no empezar.

#### WA-OPS-MET — Métricas de operación humana

**P2 · Backend · Complejidad M**

- Tiempo de primera respuesta humana por hilo, distribución de carga por staff, hilos atendidos/día — sobre datos ya persistidos (`human_author`, `created_at`, read-state). Endpoint read-only + tile opcional. Base para gestión, no para evaluación punitiva individual sin acuerdo de producto.

#### WA-ACTLOG — Tabla append-only de acciones de bandeja

**P3 · Modelo · Complejidad M**

- Hoy claim/close/release/solo logs JSON. Tabla `InboxActionLog(organization, actor FK, conversation FK PROTECT, action choices, detail JSON)` escrita desde los servicios existentes (un insert por acción, sin cambiar firmas). Consulta admin-only. Habilita «¿quién atendió esto el martes?».

#### WA-A11Y — Accesibilidad y atajos de teclado

**P2 · Frontend · Complejidad M**

- `j/k` navegar lista · `Esc` cancelar reply/cerrar lightbox · `Ctrl+K` búsqueda (SRCH-01) · aria-live polite para mensajes nuevos · roles `list/listitem` en transcript · labels en composer/textarea · foco visible. Auditoría WCAG-AA puntual al cerrar fase.

#### WA-MOB — Master-detail móvil

**P2 · Frontend · Complejidad M**

- <900 px: lista ↔ chat a pantalla completa con botón volver (hoy ambos paneles apilados compitiendo por 50 vh). Composer pegado a bottom con safe-area iOS. Metrics/token bar colapsados tras menú.

#### WA-NOT-01 — Sonido y notificaciones fuera de pestaña

**FUTURA · P2 · Frontend+producto · Complejidad M · D-9 cerrada; requiere preferencias por usuario y una decisión futura de transporte**

- Sonido opt-in y silenciable por usuario; nunca autoplay sin interacción previa del navegador.
- Notification API únicamente con permiso explícito y estado configurable. Payload mínimo, sin body clínico/PII sensible en la notificación del sistema operativo.
- Dedupe/rate limiting por hilo y ráfaga, quiet hours opcionales y acción clara para volver al hilo; evitar una notificación por cada poll.
- Este backlog **no elige ni promete transporte**. Antes de implementar se debe
  decidir cómo llegan señales mientras VIS-01 pausa/reduce polling. D-5 no
  autoriza reintroducir SSE: si la propuesta requiere realtime, aplica el
  gate/ADR p61. La ausencia de transporte no altera el título/contador v1.
- Tests: preferencias, permiso denied/default/granted, dedupe, mute, pestaña visible sin ruido y payload sin PII.

#### WA-MRK — Blue ticks hacia el cliente (mark-as-read vía API)

**P3 · Backend · Complejidad S · Depende de: UNR-01**

- Al marcar leído (UNR-02), best-effort `POST /{phone_number_id}/messages {messaging_product:'whatsapp', status:'read', message_id}` para inbound reciente. Fire-and-forget con log de fallo; nunca bloquea ni reintenta agresivo.

#### WA-SRCH-02 — Búsqueda de contenido (pg_trgm/SearchVector)

**P2/P3 · Backend+frontend · Complejidad L · Depende de: HIST-03**

- Índice trigram/GIN sobre `Message.body` (requiere extensión pg_trgm en Postgres — verificar permisos en el managed service) + endpoint `/api/inbox/search/messages/?q=` devolviendo `{message_id, thread_key, snippet}` → click abre hilo con `around=<id>`. Decisión de índice y mantenimiento requiere ADR breve.

#### WA-ORD-01 — Orden cronológico por timestamp del proveedor

**DIFERIDA fuera de v1 · Backend · Riesgo Medio · Complejidad M**

- Hallazgo latente (#34): hoy se ordena por llegada; webhook fuera de orden puede desordenar histórico. **D-10 cerrada**: v1 conserva orden `(created_at, id)`. Se permite normalizar `meta_timestamp` como telemetría nullable para medir frecuencia/impacto, pero no usarlo en `ORDER BY`, cursores ni unread. Adoptarlo como autoridad futura exige evidencia y una nueva decisión.

---

## 6. Contratos técnicos

Definidos ANTES de implementar. Solo campos nuevos propuestos; todo lo demás ya existe y no se toca.

### Message (existente + adiciones)

```
id:int · public? (no tiene; ids internos expuestos en payload — ADR p24)
conversation:FK agent.Conversation (null) · contact:FK ContactIdentity (null denorm)
channel_account:FK · human_author:FK users.User (null)
direction: in|out · author_type: client|agent|human_staff|system
payload_type: text|audio|image|document|location|sticker|button_reply|other
semantic_type: ''|confirmation|operation_receipt · operation_key:str
body:text · external_message_id:wamid(null) · raw_metadata:json
status: in pending→processed|discarded ; out pending→sent→delivered→read | failed
attempts · next_attempt_at · failure_reason · available_at · process_attempts

[+] idempotency_key: str|null   (WA-FIX-03, unique parcial por org en out)
[+] reply_to: FK self|null      (WA-RPL-01, PROTECT)
```

### MessageMedia (nuevo, WA-MED-01)

```
id · public_id · organization · message:OneToOne Message(PROTECT, related_name='media')
provider_media_id:str · channel_account-scoped unique
mime_type · file_size:null · filename:'' · sha256:''
file:FileField(storage privado, upload inbox-media/%Y/%m/)
status: pending|downloading|ready|failed|expired · error:'' · attempts
duration_ms:null · width:null · height:null · downloaded_at:null
expires_at:null · expired_at:null   (180 días; fila permanece, binario se purga)
created_at/updated_at/is_active (OrganizationalModel)
```

### InboxReadState (nuevo, WA-UNR-01)

```
organization · user:FK User(PROTECT,'+') · contact:FK · channel_account:FK
last_read_message:FK Message(SET_NULL,null) · updated_at
UNIQUE (organization, user, contact, channel_account)
```

### ThreadSerializer (adiciones acumuladas)

```
existente: contact_public_id, channel_account_public_id, nombres, phone,
contact_verification, linked_via, owner_name, conversation_public_id, state,
claimed_by_name, handoff_*, last_activity_at, last_message_preview,
has_unanswered, session_count
[+] unread_count:int            (UNR-01, para el caller)
[+] agent_processing:bool       (AGT-01)
[+] session_window_open/expires (WIN-01)
[+] last_message_type:str       (MED-05 preview tipado)
params GET: archived · offset(PERF-02) · unanswered/urgent/claimed(FIL-01) · q(SRCH-01) · since(PERF-03)
```

### API resumen de endpoints nuevos/modificados

| Método/Ruta | Tarea | Cambio |
|---|---|---|
| POST `/api/inbox/conversations/{pk}/send/` | FIX-03/RPL-03 | header `X-Idempotency-Key`; body `reply_to_id?` |
| POST `/api/inbox/conversations/{pk}/messages/{mid}/retry/` | RETRY-01 | nuevo |
| POST `/api/inbox/conversations/{pk}/assign/` | ASN-01 | nuevo |
| GET `/api/inbox/threads/` | PERF/FIL/SRCH/UNR | params + campos listados arriba; delta `since` |
| GET `/api/inbox/threads/{c}/{a}/messages/` | HIST-03/PERF-03 | params `around` y delta `since` |
| POST `/api/inbox/threads/{c}/{a}/read/` | UNR-01 | nuevo `{last_read_message_id}` |
| GET `/api/inbox/threads/{c}/{a}/context/` | CTX-01 | nuevo |
| GET `/api/inbox/media/{public_id}/` | MED-04 | nuevo (stream auth) |
No existe endpoint ni contrato de eventos SSE en v1. `WA-RT-01..03` son
identificadores reservados, no contratos implementables; un ADR p61 futuro debe
definirlos desde cero si cambia el NO-GO de D-5.

---

## 7. Plan de migraciones

Todas las migraciones son **additive-only** (columnas nullable / tablas nuevas / índices) → aplicables sin downtime en la release phase existente (`release.sh` corre `migrate --no-input` antes de levantar web; compose `depends_on: service_completed_successfully`). Ninguna requiere remedación de datos (prohibida en release por regla del propio script). Rollback = revertir código; las columnas/tablas añadidas quedan inertes y se limpian después si procede.

| ID | App | Contenido | Compatibilidad hacia atrás | Backfill | Riesgo |
|---|---|---|---|---|---|
| **M1** | channels | `Message.idempotency_key` + unique parcial `(organization, idempotency_key)` condicionada a out & not-null | Sí — código viejo ignora el campo; constraint solo aplica a escrituras nuevas con key | No | Bajo |
| **M2** | channels | `Message.reply_to` FK self PROTECT null + index `reply_to` | Sí — null default | No | Bajo |
| **M3** | agent | Tabla `InboxReadState` + unique `(org,user,contact,account)` + index `(organization,user,updated_at)` | Sí — tabla nueva | No (baseline implícita: episodio vigente cuenta como no leído hasta primera lectura) | Bajo |
| **M4** | channels | Tabla `MessageMedia` + unique parcial provider_media_id + estados/timestamps de expiración + índices | Sí — tabla nueva | No para históricos (irrecuperables por diseño actual — documentarlo); sí opcional script manual para re-parsear `raw_metadata` de mensajes recientes si algún operador lo desea | Bajo |
| **M5** (opcional SRCH-02; ORD-01 diferida por D-10) | channels | índice trigram sobre `body`; `meta_timestamp` solo telemetría nullable, nunca ordering v1 | Requiere extensión pg_trgm (verificar) | meta_timestamp: backfill desde raw_metadata posible pero NO automático | Medio |

Gate permanente de CI: `makemigrations --check --dry-run` bloquea drift no migrado.

---

## 8. Plan de tests

Comandos: backend `python manage.py test apps.channels apps.agent --parallel` (suite completa en CI), frontend `pnpm test` (Vitest). Estilo backend: `APITestCase`, roles sembrados desde `PERMISSIONS`, fixture cross-tenant trampa (ejemplo vivo: `apps/agent/tests/test_inbox_api.py`). Frontend: Testing Library + jsdom; mocks por archivo.

### Matriz por fase

| Fase | Unit | API/integración | Frontend | E2E/manual (sandbox Meta, runbook `agent-whatsapp.md`) |
|---|---|---|---|---|
| 0 | discard humano; idempotencia helper | replay send; RBAC retry | draft leak; composer session | enviar a número real tras FIX-01/02 |
| 1 | formateo TZ/día/grupos | selector pending staff | ticks, optimistic, pill título, pausa polls, badge | acuses reales sandbox; ventana 24 h visible |
| 2 | read-state semántica; search query | threads paginado/filtros/q; around 5 cortes; read upsert; retry ventana; N+1 assertNumQueries | scroll-back 10/51/500; merge sin duplicados; posición; divider; búsqueda UI | conversación larga real; dos navegadores simultáneos |
| 3 | resolver context; media estados | send reply target válido/inválido; webhook context/duplicado; descarga Graph mock (éxito/expira/404/tope); servido cross-org 404 | reply chip/jump; media render tipos/error; lightbox | foto+audio+PDF reales de un celular → visibles en inbox; reply citando |
| 4 | N/A v1 (D-5 NO-GO) | PERF-03: deltas, cursores, fallback full | merge/dedupe, pausa hidden, recuperación | polling estable y payload reducido; SSE solo bajo futuro ADR p61 |

### Casos críticos nombrados (obligatorios antes de dar fase por cerrada)

- **Historial**: 10 · 50 · 51 · 500 mensajes; mensaje nuevo durante scroll-back; duplicados absorbidos; cursor inválido; cambio de hilo durante fetch.
- **Concurrencia**: dos staff claim/release/send; humano responde durante turno IA (FIX-02); dos pestañas; webhook duplicado (ya cubierto — mantener verde).
- **Replies**: los 9 casos de WA-RPL-07.
- **Media**: imagen/PDF/audio felices; expiración URL; descarga fallida; archivo vencido 180 días → 410 + «Archivo expirado»; versiones B2 purgadas; archivo sin permisos de org (cross-org 404); caption presente/ausente; spool limpiado en éxito/fallo/crash.
- **Seguridad transversal**: cada endpoint nuevo con matriz ADMIN/VET/ASSISTANT/AGENT y trampa cross-org.

---

## 9. Plan de despliegue

Secuencia de PRs pequeños, cada uno: CI verde (backend tests + build + vitest + smoke:urls + gitleaks) → deploy staging/manual según práctica actual → smoke manual del runbook → siguiente. Migración incluida en su PR correspondiente (release phase la aplica).

| Orden | PR | Contenido | Flag/rollout | Smoke post-deploy |
|---|---|---|---|---|
| 1 | FIX-01 (+tests inbox) | draft leak | ninguno (hotfix) | escribir/cambiar hilo/enviar |
| 2 | FIX-02 | discard humano | ninguno | turno IA + respuesta humana simultánea |
| 3 | FIX-03 (M1) | idempotencia | header opcional — inerte sin frontend | doble POST curl misma key |
| 4 | OPT-01+OPT-02 | pending visible + optimistic | ninguno (reversible por revert) | envío instantáneo + reintento offline |
| 5 | UX batch A: TCK-01, SEP-01(→UX-01), GRP-01 | percepción | ninguno | visual |
| 6 | UX batch B: CMP-01, CPY-01, TAB-01, VIS-01, VER-01, GTF-01 | percepción | ninguno | visual + network tabs oculta |
| 7 | AGT-01 + LDE-01 | señales de estado | ninguno | matar backend → banner recupera |
| 8 | PERF-01 (caracterización previa) | N+1 | ninguno; payload idéntico exigido | comparar payload pre/post |
| 9 | PERF-02 + FIL-01 + SRCH-01 | lista profesional | ninguno | >100 hilos; buscar dueña de Luna |
| 10 | HIST-01 + HIST-02 | historial completo | ninguno | hilo largo real; leer arriba sin secuestro |
| 11 | UNR-01 (M3) + UNR-02 | unread real | contador activo de inmediato | dos usuarios, contadores independientes |
| 12 | RETRY-01 + WIN-01 | operación | ninguno | fallido → retry; countdown |
| 13 | CTX-01 (+D-8) | contexto cliente | panel opt-in visual | abrir expediente desde chat |
| 14 | ASN-01 | asignación | ninguno | asignar entre dos cuentas |
| 15 | RPL-01..07 (M2) | replies | ninguno | reply E2E con sandbox |
| 16 | MED-01 (M4, ADR p60) + MED-02 | ingest media | mantener `INBOX_MEDIA_INGEST=0` en prod hasta DPA + aviso/ARCO/transferencia + bucket/key/lifecycle verificados; publicar el cambio material del aviso en el repo externo de la landing y promover la versión `privacy` para re-consentimiento según `docs/runbooks/legal-version-sync.md` | audio/foto → filas pending en staging |
| 17 | MED-03 + MED-04 | pipeline + servido | tras gate p60, flag env y activar org por org; B2 canónico, spool temporal | foto real visible auth-scoped; fuga cross-org falla; objeto expirado 410 |
| 18 | MED-05 | render | ninguno | ver foto/audio/pdf en UI |
| 19 | PERF-03 (`?since`) | polling barato | backward compatible | payloads reducidos |
| 20 | Cierre de actualización v1 | **D-5 NO-GO**; verificar PERF-03 y registrar baseline | ningún flag/endpoint SSE; RT-00 es solo reevaluación y RT-01/02/03 no son tareas ejecutables | polling estable, payload reducido, hidden tabs pausadas |
| 21+ | Fase 5 según evidencia | — | — | — |

Reglas: ningún PR mezcla feature + refactor grande; PERF-01 lleva test de caracterización ANTES de tocar código; flags de entorno documentados en settings y runbook.

---

## 10. Riesgos

| # | Riesgo | Fase/tarea | Mitigación |
|---|---|---|---|
| R1 | Optimistic UI introduce duplicados o mensajes fantasma | OPT-02 | idempotencia server (FIX-03) + merge por id defensivo + tests de reintento; revert barato |
| R2 | Cambio del selector de visibilidad rompe consumidores ocultos | OPT-01 | grep exhaustivo previo + test de caracterización del transcript; `emitted_outbound` intacto |
| R3 | PERF-01 cambia sutilmente el payload de threads | PERF-01 | test de caracterización (JSON fixture comparado) antes y después |
| R4 | Descarga de media satura el worker o bloquea turnos | MED-03 | ciclo independiente con batch pequeño, SKIP LOCKED, timeouts y tope de tamaño; nunca en webhook/web |
| R5 | Fuga de media cross-tenant | MED-04 | resolución org-scoped obligatoria + tests trampa + gate `test_tenant_scoping_audit` extendido a media |
| R6 | Crecimiento ilimitado de storage / PII retenida | MED-01..04 | límites por tipo, `expires_at` 180 días, reconciliador `expired`, lifecycle que purga versiones B2, ARCO anticipado, backend local en dev/CI y métrica de uso |
| R7 | SSE agota workers gunicorn | RT-00 futuro | **Evitado en v1 por D-5 NO-GO.** Cualquier reapertura exige medición de capacidad + ADR p61; polling permanece fuente de verdad |
| R8 | Read-state mal calculado genera desconfianza («dice 3 pero hay 5») | UNR-01/02 | semántica documentada (episodio vigente), tests de los bordes (ráfaga post-read, sesión nueva) |
| R9 | Replies a mensajes no resueltos confunden al staff | RPL-* | regla dura: nunca inferir contenido; estados explícitos «no disponible/no enviado» |
| R10 | Regresión en flujo agente (worker) por fixes de fase 0 | FIX-02 | suite harness existente + casos nuevos; FIX-02 es filtro aditivo mínimo |
| R11 | Scope creep hacia «clon de WhatsApp» | transversal | §12 fuera de alcance + regla anti-refactor §4 |

## 11. Decisiones arquitectónicas cerradas

Las diez decisiones fueron aceptadas por el PO el 2026-08-22 y su contrato completo vive en [ADR p60](decisions/2026-08-22-p60-whatsapp-inbox-decisions.md). «Cerrada» fija la arquitectura; los gates de privacidad, proveedor y seguridad indicados siguen siendo obligatorios antes de activar media en producción.

| ID | Decisión | Opciones evaluadas | Decisión cerrada |
|---|---|---|---|
| **D-1 · CERRADA** | **Retención/PII de media** | 90/180/365 días/indefinido; borrado físico vs soft | **180 días y borrado físico automático del binario.** No se elimina el texto ni la fila del mensaje: queda visible con «archivo expirado». Lifecycle B2 cubre versiones; los backups Postgres conservan texto/captions y metadatos, pero nunca el binario B2, durante su ciclo p40 intacto (14 días local, 30 daily, 12 meses monthly). Un restore reaplica purgas/anonimizaciones y reconcilia expiraciones antes de abrir tráfico. Aviso/ARCO deben cubrir el tratamiento antes de producción. |
| **D-2 · CERRADA** | **Storage v1** — ver «Anexo D-2» | A: disco VPS + backup posterior · B: B2 operativo · C: híbrido espejo | **B2 operativo en producción.** Binario canónico solo en bucket privado dedicado; VPS únicamente spool temporal; DB solo metadatos. Backend local en dev/CI; proxy Django auth-scoped como único contrato v1; sin presigned GET ni Object Lock en media; clave separada y gates DPA/aviso/ARCO/transferencia internacional. |
| **D-3 · CERRADA** | **Semántica unread** | per-user/global | **Por usuario y acotada al episodio vigente.** La lectura de una persona no limpia la de otra ni revive sesiones históricas. |
| **D-4 · CERRADA** | **Mark-read automático** | auto/manual | **Automático** solo con pestaña/ventana visible y enfocada, tras debounce; background no marca. |
| **D-5 · CERRADA** | **SSE GO/NO-GO v1** | GO / NO-GO-polling-mejorado | **NO-GO SSE en v1.** PERF-03 + polling correcto/pausable son el rollout. Reabrir solo con evidencia y propuesta de capacidad; un GO futuro requiere ADR p61. |
| **D-6 · CERRADA** | **Asignación** | claim-perm para todos / restringir a ADMIN | Quien tenga `agentinbox.claim` asigna a un usuario activo de la misma organización con `agentinbox.send`; sin push v1 y con auditoría actor/origen/destino/fecha. |
| **D-7 · CERRADA** | **Retry** | propio/cualquiera | Cualquiera con `agentinbox.send` puede reintentar un fallo de la clínica: mismo contenido, ventana 24 h, idempotencia, sin duplicados y con actor/resultado auditados. |
| **D-8 · CERRADA** | **Alcance del panel de contexto** | mín (owner+mascotas+última cita) / ampliado | **Mínimo v1:** owner, mascotas, última cita no clínica y enlace; nunca historial clínico dentro del Inbox. Futuro: productos, servicios y precios vigentes mediante permisos/contratos y lectura de sus fuentes de verdad, sin duplicarlos. |
| **D-9 · CERRADA** | **Notificaciones fuera de pestaña** | título only / +sonido / +Notification | **Título en v1.** Futuro: sonido opcional/silenciable y después Notification API con preferencias por usuario, permiso del navegador y dedupe/rate limiting anti-fatiga. |
| **D-10 · CERRADA** | **ORD-01** | adoptar ts-proveedor / mantener llegada | **Mantener orden de llegada (`created_at`, `id`) en v1.** Guardar/medir timestamp proveedor no autoriza reordenar; cualquier cambio futuro requiere evidencia y nueva decisión. |

### Anexo D-2 — Comparativa: filesystem VPS vs Backblaze B2 operativo (2026-08-22)

**Hechos del repo que condicionan la decisión** (verificados):
- B2 ya está en producción como destino de backups Postgres: `pg_dump -Fc → age encrypt (clave privada offline) → rclone copy → bucket B2 inmutable`, tiers daily/monthly, guard fail-loud, deadman healthchecks.io (`scripts/pg-backup.sh`, `restore-drill.sh`, ADR p40). Esa inmutabilidad pertenece al bucket de backups; el bucket separado de media operativa no usa Object Lock.
- La clave B2 actual vive SOLO en `rclone.conf` del host (chmod 600), **explícitamente prohibida en `.env.prod`** (`pg-backup.sh:44-47`). Usar B2 operativamente implica una excepción documentada a esta política con una clave distinta.
- El backend no tiene hoy ningún SDK S3/boto3; sí usa `requests`. No existe stack de media (0 FileField).
- `pg-backup.sh` respalda **solo dumps de Postgres** — no hay pipeline de backup para archivos arbitrarios. La alternativa A exige construirlo.
- Proxy Caddy en el borde; Redis disponible; worker propio ya hace HTTP saliente con backoff.

**Alternativa A — Filesystem local del VPS + backup posterior a B2**
El worker descarga de Meta a disco local (`FileField` + `FileSystemStorage` privado); un nuevo job nocturno empaqueta/media dir → age → rclone → B2.

**Alternativa B — Backblaze B2 como object storage operativo**
El worker descarga de Meta y sube directo a bucket B2 vía API S3-compatible (django-storages+boto3, o firmante SigV4 fino con `requests` si se quiere evitar boto3). En v1 se sirve exclusivamente mediante proxy Django autenticado. Las URLs `presigned GET` quedan fuera de alcance; adoptarlas exigiría medición, revisión de seguridad y un ADR futuro.

| Criterio | A: local + backup posterior | B: B2 operativo |
|---|---|---|
| **Coste** | ~0 marginal al inicio (disco incluido en VPS); crece la necesidad de ampliar disco; coste real = desarrollar y mantener el pipeline de backup de archivos | Storage $6.95/TB-mes (primeros 10 GB gratis); egreso gratis hasta 3× almacenamiento medio (escenario clínico queda órdenes de magnitud debajo); transacciones 2.500/día gratis por clase. Estimado 50 clínicas × ~60 MB/mes ≈ 36 GB/año → **<$0.25/mes**. Coste NO es el diferenciador |
| **Complejidad total** | Inicial baja (FileSystemStorage), pero exige construir subsistema nuevo: job de backup de archivos, retención sincronizada, extensión del restore-drill, reconciliación de borrados. Complejidad permanente | Inicial media (storage class + settings + credenciales + upload/download), pero **elimina para siempre** el subsistema de backup-de-archivos y los scripts de retención (lifecycle rules nativas implementan D-1) |
| **Seguridad** | Texto claro en el mismo trust zone que la DB (consistente con hoy); backups zero-knowledge age (postura p40 intacta) | Objetos con cifrado at-rest gestionado por el proveedor — **NO es zero-knowledge**: delta frente a la postura age de backups que debe aceptarse explícitamente. Mitigaciones: bucket privado sin URLs públicas jamás, Application Key dedicada restringida al bucket/prefix de media (aisla blast-radius respecto a la clave de backups), servido siempre tras auth org-scoped |
| **Crecimiento** | Acotado al disco del VPS; migración futura a object storage = re-subida masiva one-shot dolorosa | Ilimitado y predecible; sin presión sobre disco del VPS (que también aloja DB, logs y statics) |
| **Disponibilidad (servir)** | Depende solo del VPS (ventaja: menos partes móviles); latencia mínima | Añade dependencia de uptime B2 (~99.9%) y latencia de primer byte (~100–300 ms); mitigable con Cache-Control y caché Caddy posterior. Si B2 cae: texto del chat sigue (DB local), media muestra error/reintento (ya diseñado en MED-05) |
| **Pérdida del VPS (DR)** | **RPO media = hasta 24 h**: los mensajes sobreviven (DB) pero las fotos del día se pierden → referencias rotas permanentes a contenido clínico. Además la restauración requiere reconstruir desde bucket + drill extendido | **RPO ≈ minutos** (write-through): el bucket ES la copia offsite; reconstruir el servicio = levantar compose apuntando al mismo bucket. DR de media trivial por diseño |
| **Retención (D-1)** | Scripts propios de purga + verificación | Lifecycle rules nativas de B2 por prefijo/edad; auditable en consola |
| **Compatibilidad con arquitectura actual** | Máxima (patrón clásico Django), pero rompe la simetría «todo lo crítico sale del VPS» que p40 instauró | Alta: storage class custom detrás de FileField es patrón Django estándar; el worker ya hace HTTP con backoff (MED-03 reutiliza exactamente ese esqueleto para subir). Requiere: 2 deps nuevas (o firmante SigV4 fino), env vars nuevas, y **excepción documentada** a la política «clave B2 nunca en .env.prod» (clave separada y restringida) |

**Opción C (híbrido: escribir local + espejar asíncrono a B2, servir local)** — descartada: maximiza disponibilidad de lectura pero duplica estado a reconciliar (cola de espejo, drift, doble purga), que es exactamente la complejidad que este plan evita.

**Decisión cerrada: Alternativa B.** El PO aceptó estos tres efectos de arquitectura; siguen existiendo gates de implementación y producción:
1. Delta de seguridad: media operativa NO es zero-knowledge (cifrado gestionado por proveedor). Los backups age/p40 quedan intactos e inmutados.
2. Política de credenciales enmendada: nueva `B2_MEDIA_*_KEY` en `.env.prod`, Application Key creada específicamente para el bucket de media con acceso limitado a él — nunca reutilizar la clave de backups.
3. Servido siempre autenticado mediante proxy Django en v1, jamás URLs públicas ni compartibles. Un mecanismo `presigned GET` futuro requiere ADR y revisión de seguridad propias; no es una variante seleccionable durante v1.

Condiciones de implementación (se incorporan a MED-01/MED-03/MED-04): backend de storage intercambiable por entorno (`MEDIA_BACKEND=local` default dev/CI sin credenciales · `b2` opt-in en prod tras PR-16), spool local temporal durante upload para que fallos transitorios de B2 usen el mismo backoff del worker, tope por archivo según D-2 (25 MB general / 10 MB imágenes), lifecycle rules ejecutando la retención decidida en D-1.

## 12. Fuera de alcance

Deliberadamente NO construiremos (coherente con auditoría §19):

- Importación de historial anterior desde WhatsApp/Meta: el proveedor no entrega históricos. «Historial completo» (HIST-01) significa *todo lo conservado en nuestra BD* desde la activación del webhook — ver definición de alcance en WA-HIST-01.

- Reacciones, encuestas, catálogo/comercio, notas de voz salientes con waveform custom.
- Presencia tipo Figma (cursores), co-edición de borradores entre agentes.
- Etiquetas/notas visuales y automatizaciones sobre etiquetas (no existe demanda ni modelo).
- App móvil nativa (el responsive master-detail cubre «recepcionista en celular»).
- Multi-canal (Instagram/Messenger) antes de que WhatsApp sea impecable.
- CRM dentro del inbox: el expediente vive en su módulo; enlazar (CTX-01), no duplicar.
- Plantillas HSM / recordatorios fuera de ventana: épica F3 propia ya especificada — este plan solo deja la ventana visible (WIN-01).
- Virtualización prematura (VIRT-00 decide con medición), WebRTC/llamadas, typing indicator hacia el cliente.
- Búsqueda full-text de contenido antes de SRCH-01 validada en uso real.
- Cualquier feature nueva ANTES de FIX-01/FIX-02.

## 13. Definition of Done global

«El Inbox está listo para uso real» cuando TODAS estas condiciones se cumplen:

**Operación (la prueba de los 10 minutos, verificada con una recepcionista real):**
1. Su mensaje aparece al instante con ticks que progresan ✓→✓✓→leído.
2. Ve «Hoy/Ayer» separando días y agrupación limpia de ráfagas.
3. El contador junto a cada cliente dice cuántos mensajes espera; abrir marca leído y muestra el divider.
4. Puede subir a leer lo de hace semanas sin que la vista la secuestre, con pill «N nuevos» cuando llegan cosas.
5. Al abrir un hilo ve quién es, sus mascotas y un clic al expediente.
6. Una foto enviada por un cliente se ve en el inbox (pipeline media activo).
7. Un mensaje fallido ofrece Reintentar o sugiere llamar si la ventana cerró.
8. Ningún borrador viaja entre conversaciones (FIX-01 verificado en su sesión).

**Técnico:**
9. Fases 0–3 completas con acceptance criteria marcados; realtime v1 resuelto por D-5 NO-GO en p60 y PERF-03 verificado. Ninguna tarea RT-01..03 implementada sin ADR p61.
10. CI verde estable: backend `manage.py test --parallel`, frontend build+vitest+smoke; `makemigrations --check` limpio; gitleaks limpio.
11. Cero queries N+1 en polls de lista (PERF-01 con assert permanente).
12. Matrices de permisos y tenant-isolation de todos los endpoints nuevos pasando gates existentes.
13. Media servida exclusivamente auth-scoped con prueba de fuga fallida; expiración 180 días verificada end-to-end (410/UI/lifecycle/versiones) y gates DPA/aviso/ARCO cerrados antes de producción.
14. Docs actualizadas por CLAUDE.md de docs: `docs/modules/agent.md` (contratos nuevos), ADR p60 (p61 solo ante futuro SSE GO), CHANGELOG por fecha.

---

*Fin del plan. D-1..D-10 cerradas en ADR p60; Fase 0 cerrada y segundo corte de Fase 1 verificado el 2026-08-23. WA-CMP-01, WA-GRP-01, WA-CPY-01 y WA-TAB-01 verificadas localmente el 2026-10-20. WA-VIS-01, WA-VER-01, WA-LDE-01, WA-AGT-01, WA-GTF-01, WA-PERF-01, WA-PERF-02, WA-HIST-01, WA-HIST-02, WA-HIST-03, WA-UNR-01, WA-UNR-02, WA-RETRY-01, WA-WIN-01, WA-CTX-01, WA-PERF-03, WA-FIL-01 y WA-SRCH-01 verificadas localmente el 2026-10-21. Fase 3 obligatoria implementada y verificada localmente el 22-10 (RPL-07, MED-01..05); M2/M3/M4 sin aplicar a bases habitual/preview. MED-06 opcional y fase 5 siguen fuera de este cierre; gates reales y evidencia en la guía de cierre. El gate E2E de WA-TCK-01 en sandbox Meta sigue pendiente; recepción/Meta pospuesta por el usuario.*
