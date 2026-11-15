# Pendientes documentados: inventario conciliado

Fecha de revisión: **27 de octubre de 2026**, zona America/Mexico_City. Checkout: `8886604` (`codex/e4-capacity-scheduling`).

**Orden de remediación actualizado:** [categorías, prioridades y dependencias — 28 de octubre](plan-remediacion-priorizado-2026-10-28.md). Este inventario conserva el detalle y las fuentes de cada ID.

## Alcance y cómo interpretar el resultado

Se realizó una búsqueda automatizada sobre **409 documentos** Markdown y documentos sin extensión terminados en `md`, seguida de lectura dirigida de backlogs, planes, módulos, auditorías, ADRs y actas recientes. También se inspeccionaron infraestructura/CI y marcadores de deuda del backend/frontend. Se excluyeron dependencias, skills, entornos virtuales, worktrees secundarios, referencias visuales externas y copias de evidencia `referenced*`/`preparation-history`. No se leyó íntegramente cada documento ni se certificó cada criterio de aceptación.

Se priorizó evidencia posterior sobre planes antiguos. Un checkbox vacío no demuestra por sí solo que falte implementar una función. Las filas siguientes representan unidades de seguimiento, no un conteo de bugs únicos: varias comparten dependencia o criterio de cierre.

Estados utilizados:

- **Confirmado en código:** se observó el patrón pendiente en el checkout actual; no implica haber reproducido su impacto mediante pruebas.
- **Documentado abierto:** la fuente mantiene el pendiente y no se localizó cierre posterior suficiente. Debe verificarse antes de implementarlo.
- **Operación por acreditar:** falta evidencia externa; esta revisión local no determina el estado real del VPS, cuentas, contratos o landing.
- **Aceptado/diferido:** sigue sin resolverse, pero no debe promoverse automáticamente a bloqueante.

No se modificó código, no se aplicaron nuevas migraciones, no se accedió a producción y no se iniciaron campañas B9/D29. La única comprobación nueva de calidad fue `rtk proxy pnpm.cmd lint`.

## 1. Pendientes operativos, dependencias y privacidad

| ID | Pendiente vigente | Estado y criterio de cierre | Fuente |
|---|---|---|---|
| O01 | Triaje y remediación de avisos de dependencias Python/JS | **Documentado abierto.** El corte del 22-10 registra `pip-audit`: 162 avisos en 11 paquetes; `pnpm audit`: 8 bajos, 39 moderados y 38 altos. Son resultados históricos, no un escaneo actual ni 247 vulnerabilidades únicas confirmadas. Revisar aplicabilidad, actualizar cuando corresponda y conservar nueva evidencia. Son advisory en B9/CI. | [B9-RESULTS](evals/inbox-readiness-2026-10-22/B9-RESULTS.md), [CI](../.github/workflows/ci.yml) |
| O02 | Provisionar B2 exclusivo para media operativa | **Aplazado por el usuario; operación por acreditar.** Cuenta/bucket/key dedicados, región/endpoint reales, permisos y lifecycle. No reutilizar como prueba los fixtures ni la configuración de backups. | [Cierre B2](compliance/cierre-b2-whatsapp-2026-10-22.md), [preparación](compliance/inbox-privacy-review-2026-10-22/b2-preparacion.md) |
| O03 | Acreditar purga y restore contra almacenamiento real | **Operación por acreditar.** Acceso autorizado, expiración, borrado de versiones/markers, capacidad del cron, custodia independiente del ledger de revocaciones y restore que no reactive contenido. La implementación local y el simulacro no cierran el proveedor real. | [Cierre B2, puntos 2 y garantías](compliance/cierre-b2-whatsapp-2026-10-22.md), [runbook media](runbooks/inbox-media.md) |
| O04 | Completar decisión contractual/región/tratamiento internacional B2 y Meta | **Operación por acreditar.** Archivar instrumento aplicable, aceptación real y ficha de región/subencargados; la decisión de retención ya está definida. | [Cierre B2, punto 1](compliance/cierre-b2-whatsapp-2026-10-22.md), [vendors](compliance/vendors.md) |
| O05 | Revisar y publicar el aviso actualizado | **Operación por acreditar.** Hay copia Astro, parche y build de revisión PASS de 18 páginas. Faltan revisión final, fecha efectiva, release y comprobación del contenido público HTTPS. | [Paquete vigente 23-10](compliance/inbox-privacy-review-2026-10-23/README.md), [cierre](compliance/cierre-b2-whatsapp-2026-10-22.md) |
| O06 | Sincronizar versión legal y verificar reaceptación | **Operación por acreditar.** Promover únicamente la versión efectivamente publicada, comprobar ADMIN/VET/ASSISTANT y conservar aceptaciones previas. | [Cierre B2, publicación](compliance/cierre-b2-whatsapp-2026-10-22.md), [runbook](runbooks/legal-version-sync.md) |
| O07 | Pruebas reales Meta y aceptación de recepción | **Pendiente del usuario según el último cierre.** Ticks delivered/read, replies/media reales y prueba de diez minutos con los ocho puntos del DoD. No equivalen a tests con proveedor simulado. | [Guía vigente, §3 DoD operativo](CIERRE-INBOX-WHATSAPP.md), [readiness](evals/profile-beta-1-operational-readiness.md) |
| O08 | Responsables/cobertura/fallback y autorización de activación | **Operación por acreditar.** Completar responsables humanos de Inbox y seguridad clínica, simulacro, fallback y aprobación por clínica/capacidad. No confundir con la excepción específica de alertas de purga ACEPT02. | [Readiness operativo](evals/profile-beta-1-operational-readiness.md), [guía vigente](CIERRE-INBOX-WHATSAPP.md) |
| O09 | Release de migraciones/código a preview y producción | **Documentado abierto.** M2/M3/M4 y `channels.0018` ya constan aplicadas localmente; preview/producción no se dan por migradas ni activadas. En la tarea previa también se aplicaron localmente appointments 0016–0018 y patients 0019; no deben volver a listarse como migraciones locales pendientes. | [Guía vigente, cabecera y §0](CIERRE-INBOX-WHATSAPP.md) y comprobación local previa en este chat |
| O10 | Acreditar DPAs/instrumentos de proveedores activos | **Documentado abierto.** Registro mantiene pendientes para Hetzner, B2 backups, Sentry, Discord, Formspree, Google y Meta según alcance. Revisar/archivar por proveedor; no se inspeccionaron sus cuentas. | [Registro vendors](compliance/vendors.md) |
| O11 | Consentimiento de GA4 y retención/aviso de Formspree en landing | **Documentado abierto, P0 en la fuente.** GA4: consentimiento denegado por defecto, Consent Mode/banner; Formspree: plazo y aviso. Pertenece al repo de la landing; no se verificó su código actual ni publicación remota. | [vendors, tabla de proveedores](compliance/vendors.md) |
| O12 | Automatización de solicitudes ARCO | **Documentado abierto, P1.** Actualmente se documenta un procedimiento manual; no hay endpoints automatizados acreditados. Definir alcance de exportación/cancelación y evidencia de ejecución antes de sustituir el proceso manual. | [ARCO, cabecera](compliance/arco.md) |
| O13 | Acreditar rotación de secretos expuestos históricamente | **Pendiente documental por conciliar con operación.** El plan del 19-06 sigue indicando ejecución pendiente para clave Django y credenciales administrativas/DB. No se consultaron secretos ni se puede afirmar que sigan vigentes. Cerrar con constancia privada de rotación, sin valores en Git. Gitleaks PASS no demuestra rotación. | [Plan de rotación](security/secret-rotation-plan.md) |
| O14 | Evidencia de operación de backups, restore, crons y monitoreo | **Operación por acreditar; no es implementación faltante.** Los scripts/runbooks existen. Conciliar instalación y resultados reales de backups offsite, restore local/offsite, snapshots/audit de anchors, alertas, Sentry y monitor externo. Evitar tratar la checklist plantilla como prueba de que nada está instalado. | [Production runbook, checklist final](production-runbook.md), [observability](runbooks/observability.md), [cron](runbooks/cron-jobs.md) |
| O15 | Limpieza de teléfonos existentes y captura de contacto de orgs internas | **Documentado abierto.** Los seis PRs de onboarding están implementados; quedan las tareas manuales PR-1 y PR-4 antes del rollout correspondiente. | [Onboarding, §10](onboarding-clinic-config-plan.md) |

## 2. Deuda técnica con evidencia actual

La prioridad de A/B/C es la del registro original. Los textos de mayo/junio contienen ejemplos de un dominio financiero anterior: deben adaptarse al Checkout actual, no copiarse literalmente.

| ID original | Pendiente | Estado observado / cierre requerido | Fuente y evidencia |
|---|---|---|---|
| A1 + B4 | Centralizar validación tenant en serializers | **Confirmado en código.** Persisten `_validate_same_org` locales y no se localizó `TenantScopedSerializerMixin`. B4 es parte del mismo trabajo, no un bug adicional. Migrar sitios con cobertura y observabilidad equivalentes. | [A1](deuda/fase2-prioridad-alta.md), [B4](deuda/fase3-prioridad-media.md), `backend/apps/{billing,prescriptions}/serializers.py` |
| A2 | Invariante de pertenencia tenant de Invoice en servicio/DB | **Parcialmente confirmado.** `Invoice.clean()` sigue presente; no se acreditó cierre de todos los criterios de A2. Conciliar servicios/constraints de Checkout antes de crear otra ruta de facturación. | [A2](deuda/fase2-prioridad-alta.md), `backend/apps/billing/models.py:146` |
| A3 | Extraer el cierre clínico de la vista | **Confirmado en código.** La vista escribe `closed_at` y `closed_at_source='service'`. Extraer writer y helper de late-arrival manteniendo transacción, idempotencia y efectos actuales. | [A3](deuda/fase2-prioridad-alta.md), `backend/apps/medical_records/views.py:540`, `backend/apps/medical_records/services.py` |
| A4 | Reversión de stock ante borrado en cascada de MedicalRecordProduct | **Documentado abierto y condicional.** El módulo sigue advirtiendo que cascade no invoca el `delete()` custom. Resolver si se habilita borrado del expediente; no se reprodujo corrupción ni se constató un endpoint de borrado expuesto. | [A4](deuda/fase2-prioridad-alta.md), [inventario](modules/inventory.md) |
| A5 | Soft-delete completo de Owner/Pet/Organization | **Parcial; criterios no cerrados.** Hay `is_active`/protecciones, pero DELETE de mascotas/clientes sigue delegando a `super().destroy()`. Falta la solución integral de archivo, trazabilidad y recuperación del registro. No implica que hoy se pueda borrar todo el árbol libremente: existen PROTECT/guards. | [A5](deuda/fase2-prioridad-alta.md), `backend/apps/patients/views.py:147,224`, [organizations](modules/organizations.md) |
| A6 | Preservar InvoiceAuditLog al borrar una factura | **Confirmado en código.** FK `invoice` conserva CASCADE; faltan SET_NULL/snapshot y criterio de consulta del registro preservado. | [A6](deuda/fase2-prioridad-alta.md), `backend/apps/billing/models.py:1080` |
| A7 | Snapshot del veterinario al cerrar expediente | **Confirmado en código.** `MedicalRecord.veterinarian` usa SET_NULL y no se localizó `vet_name_at_close`. Falta snapshot/backfill/consumo en presentación. | [A7](deuda/fase2-prioridad-alta.md), `backend/apps/medical_records/models.py:21` |
| D5 | Preservar auditoría de timezone al borrar organización | **Confirmado en código.** `OrganizationTimezoneAudit.organization` sigue CASCADE. | [D5](deuda/fase2-prioridad-alta.md), `backend/apps/organizations/models.py:147` |
| D6 | Preservar receta al borrar su expediente | **Confirmado en código.** `Prescription.medical_record` sigue OneToOne CASCADE; snapshot propuesto sin cierre acreditado. | [D6](deuda/fase2-prioridad-alta.md), `backend/apps/prescriptions/models.py:6` |
| D7 | Preservar ledger de inventario al borrar presentación | **Confirmado en código.** `StockMovement.presentation` sigue CASCADE. La decisión concreta de SET_NULL/snapshot debe conservar semántica contable vigente. | [D7](deuda/fase2-prioridad-alta.md), `backend/apps/inventory/models.py:266` |
| D2 | Retirar endpoint legacy de organizaciones tras Sunset | **Cleanup documentado abierto.** El 410 automático ya estaba implementado; falta acreditar uso cero/410 real y retirar vista/ruta en cambio separado. La fecha del Sunset ya pasó: 17-08-2026. | [D2](deuda/fase2-prioridad-alta.md), [organizations, endpoint deprecated](modules/organizations.md) |
| B2 | Consolidar PrescriptionItemSerializer/WriteSerializer | **Confirmado en código.** Siguen clases y validadores separados, con diferencias de `requires_prescription`. Preservar diferencias intencionales; depende de A1 según el plan. | [B2](deuda/fase3-prioridad-media.md), `backend/apps/prescriptions/serializers.py:38,169` |
| B3 | Retirar fallback RBAC y dependencia legacy de User.role | **Confirmado en código.** `HybridPermission` mantiene fallback estático. Precondición documental: siete días sin `RBAC_FALLBACK_ALLOWED`, ≥500 requests y cobertura de endpoints críticos; no acreditada por esta revisión local. | [B3](deuda/fase3-prioridad-media.md), `backend/apps/core/permissions.py:342`, [sprint](../spint_seguridad.md) |
| B5 | Reemplazar bootstrap de superusuario por comando explícito | **Confirmado en código.** `UsersConfig.ready()` sigue conectando `_create_default_superuser` a `post_migrate`; no se encontró `bootstrap_superuser`. No quitar guards existentes. | [B5](deuda/fase3-prioridad-media.md), `backend/apps/users/apps.py:10` |
| B6 | `seed_permissions --prune` y `--dry-run` | **Documentado abierto, corroborado parcialmente.** No se localizó `--prune` en el comando actual. Requiere implementación explícita y pruebas; no ejecutar poda en cada deploy. | [B6](deuda/fase3-prioridad-media.md), `backend/apps/core/management/commands/seed_permissions.py` |
| B7 | Orden de inventario “Valor en stock” | **Confirmado en código.** El comparador usa precio×stock sin dividir por factor; la columna usa `productStockValue`. Stock también tiene divergencia de fuente en el comparador. Reutilizar helpers y probar productos con factor distinto de 1. | [B7](deuda/fase3-prioridad-media.md), `frontend/src/pages/inventory.jsx:401` |
| C2 | Regla generic owner→direct_sale dentro de validate() | **Confirmado en código.** El serializer sigue mutando `data['invoice_type']`. Conciliar con servicios Checkout al atender A2. | [C2](deuda/fase4-prioridad-baja.md), `backend/apps/billing/serializers.py:404` |
| C3 | Separar useAuth/AuthContext de AuthProvider | **Confirmado; lint actual también lo reporta.** El archivo sigue exportando hook y componente. Actualizar imports sin cambiar sesión/tokens. | [C3](deuda/fase4-prioridad-baja.md), `frontend/src/auth/authContext.jsx` |
| C4 | Unificar matemática de PaymentLinesEditor | **Confirmado en código.** `sum/remaining/change` continúan inline. Extraer a helper compartido conservando redondeo y semántica de cambio. | [C4](deuda/fase4-prioridad-baja.md), `frontend/src/components/PaymentLinesEditor.jsx:8` |
| C5 | Nombres accesibles de controles de pago | **Confirmado en inspección.** Select, importe y botón iconográfico siguen sin labels accesibles acreditados. Resolver junto con C4 y actualizar queries de tests. | [C5](deuda/fase4-prioridad-baja.md), `frontend/src/components/PaymentLinesEditor.jsx` |
| C6 | Corregir docstring de mapFieldErrors | **Documentado abierto; cabecera sigue sin ejemplo completo del dual-key.** Alinear explicación con claves plana+dotted y colisiones sin cambiar implementación. | [C6](deuda/fase4-prioridad-baja.md), `frontend/src/utils/mapFieldErrors.js` |
| C7 | Colisión de nombre apps/platform con stdlib platform | **Diferido; no se reprodujo en esta revisión.** Ya existe workaround de módulos de tests explícitos. Rename requeriría preservar app labels, ContentType y permisos. | [C7](deuda/fase4-prioridad-baja.md), [platform, tests](modules/platform.md) |
| C8 | Desacoplar despliegue de landing del Caddy SaaS | **Documentado diferido.** Repos separados pero alojamiento temporal compartido; verificar infraestructura real al planificar migración. | [C8](deuda/fase4-prioridad-baja.md), `infra/Caddyfile`, `docker-compose.prod.yml` |

## 3. Frontend, inventario, importaciones, clínica y analítica

| ID | Pendiente | Estado y cierre requerido | Fuente |
|---|---|---|---|
| F01 | Remediar lint y convertirlo en gate requerido cuando esté listo | **Confirmado hoy:** `pnpm lint` termina exit 1 con **198 errores y 19 advertencias**. Incluye `frontend/standalone`, además de la app; no atribuir todo a `src` ni usar las cifras antiguas de ~6/42/64 como actuales. Aparecen reglas de hooks, memoización, exports y variables sin uso. CI mantiene lint advisory. | [Plan P1-4](p1-4-frontend-reliability.md), [frontend, siguientes fases](modules/frontend.md), [CI](../.github/workflows/ci.yml) |
| F02 | Extraer subcomponentes/lógica pura restante de billing | **Documentado abierto, Fase C.** Definir unidad acotada antes de refactor; C4 se sigue por separado pero comparte objetivo. | [P1-4, checklist](p1-4-frontend-reliability.md), [frontend, siguientes fases](modules/frontend.md) |
| F03 | Consolidar StatusBadge y SortHeader donde aún no se migraron | **Documentado abierto, deuda contenida.** Se listan billing/cash/petDetail/appointments/AppointmentBreakdown y SortHeader local de inventario; verificar cada consumidor antes de tocarlo. | [frontend, StatusBadge/SortHeader](modules/frontend.md) |
| F04 | Copy “Username requerido” en alta de organización | **Documentado abierto, menor.** Cambiar a terminología española coherente cuando se aborde esa pantalla. | [frontend, deuda de platform](modules/frontend.md) |
| I01 | Stock inicial manual sin movimiento de ledger | **Confirmado en código.** `ProductSerializer.create` asigna `stock_quantity` directamente; el importador usa movimiento. Unificar contrato y decidir reconciliación/baseline antes de backfill. | [Plan importador §9.1](PLAN-importador-inventario.md), `backend/apps/inventory/serializers.py:232` |
| I02 | quantity de presentación no sincronizada con conversion_factor en alta manual | **Documentado abierto; create inspeccionado no mostró sincronización explícita.** Decidir contrato y backfill; el importador ya usa `quantity == conversion_factor`. | [ADR p61, deuda #1](decisions/2026-08-25-p61-importador-inventario.md), [imports](modules/imports.md) |
| I03 | `conflicts[]` sin límite en importación | **Deuda aceptada en ADR, sin cierre posterior localizado.** Definir límite/paginación y conteos honestos. | [ADR p61, consecuencias](decisions/2026-08-25-p61-importador-inventario.md) |
| I04 | Locks acumulados por fila en importaciones grandes | **Deuda aceptada/acotada por MAX_ROWS=2000.** Optimizar solo con evidencia de necesidad, conservando atomicidad. | [ADR p61, consecuencias](decisions/2026-08-25-p61-importador-inventario.md) |
| I05 | Código de error específico de bloqueo demo perdido en handler global | **Documentado aceptado.** Actualmente 403 genérico; cambiar requiere decisión de contrato. | [ADR p61, consecuencias #5](decisions/2026-08-25-p61-importador-inventario.md) |
| I06 | Importación multi-presentación, lotes y múltiples orígenes/sucursales | **Extensiones futuras, no defectos de V1.** Definir alcance y unicidad de `legacy_id` por origen; no deducir que el importador base falta. | [ADR p61 D5/exclusiones](decisions/2026-08-25-p61-importador-inventario.md), [imports, estrategia futura](modules/imports.md) |
| I07 | Baseline de productos sin adjustment en auditoría de stock | **Documentado diferido.** Sin baseline no se puede verificar todo el historial; decidir si corresponde emitir movimientos de apertura trazables. | [Audit remediation, deuda menor](audit-remediation-2026-05-26.md) |
| M01 | Cédula profesional del veterinario en documentos | **Documentado abierto; User no mostró `license_number`.** Campo, captura y PDF pendientes de la fase prevista. | [medical_records, documentos](modules/medical_records.md), `backend/apps/users/models.py` |
| M02 | Snapshot formal de analítica clínica por protocolo | **Documentado abierto; LITE ya existe.** Faltan KPIs versionados, anchors de cirugía, complicaciones estructuradas, snapshot/series y migración del frontend. Requiere ADR, dual-write 30 días y aprobación PO según contrato. | [analytics, deuda LITE](modules/analytics.md) |
| M03 | MedicalRecord.weight→VitalSigns como única fuente | **Confirmado que weight legacy permanece; migración no acreditada.** Requiere migración de datos y revisión de consumidores. | [Contexto §10](../CONTEXTO_ACTUAL_PROYECTO.md), [audit remediation](audit-remediation-2026-05-26.md), `backend/apps/medical_records/models.py:35` |
| M04 | Charts con revenue_paid_net | **Documentado diferido; la pantalla actual mantiene `FIN_HERO='revenue_paid'`.** No cambiar semántica contable sin sign-off y revisión de versión de métricas. | [Contexto §10](../CONTEXTO_ACTUAL_PROYECTO.md), [ADR p29](decisions/2026-05-27-p29-credit-notes-refunds-analytics-net.md), `frontend/src/pages/analytics/index.jsx` |
| M05 | Hacer presentation obligatorio en InvoiceItem cuando corresponda | **TODO v2 confirmado en código.** El propio comentario exige migrar flujos, seeds y frontend primero. Revalidar su alcance frente a ítems de servicio/constraints actuales antes de aplicar un null=False indiscriminado. | `backend/apps/billing/models.py:917` |

## 4. Agente conversacional: investigaciones y extensiones abiertas

Estas extensiones no deben confundirse con B0–B9 ya implementados en sus alcances ni con funciones de Inbox cerradas localmente. No se localizó acta posterior que acredite cierre completo de las filas siguientes.

| ID | Pendiente | Estado / límite | Fuente |
|---|---|---|---|
| G01 | Investigar repetición de preguntas de identidad | **Investigación documentada abierta.** Necesita transcript/evidencia de tools con modelo real para distinguir captura incompleta de datos ignorados. No aplicar el fix descartado de goals sin caller productivo. | [TODOS, segundo ítem](../TODOS.md) |
| G02 | E1: referencias y continuidad después de recibos | **Extensión documentada.** Contexto mínimo con procedencia, aclaraciones y separación entre referencia y autorización. Verificar consumidores antes de implementar por la antigüedad del plan. | [Plan canónico, Fase E1](plan-implementacion-auditoria-agente-whatsapp-2026-09md) |
| G03 | E2: varios objetivos suspendidos y un frente activo | **Extensión documentada.** No declarar que B6 ya resuelve todo multi-goal. | [Plan canónico, Fase E2](plan-implementacion-auditoria-agente-whatsapp-2026-09md) |
| G04 | E3: avisos/seguimiento adicionales de atención humana | **Extensión documentada.** El Inbox durable y el centro de notificaciones existentes no equivalen a atención humana acreditada; reutilizarlos en la ampliación. | [Plan canónico, Fase E3 y seguimiento B5](plan-implementacion-auditoria-agente-whatsapp-2026-09md) |
| G05 | E5: altas compuestas con resultado por paso | **Fuera de beta inicial.** Idempotencia y resultado PARTIAL honesto para mascota+cita; no borrar mascota ni inventar cita tras fallo del segundo paso. | [Plan canónico, Fase E5](plan-implementacion-auditoria-agente-whatsapp-2026-09md) |
| G06 | P-A/P-B de texto, metadata, flow/slots y evidencias | **Documentado abierto por categoría.** La retención/purga de binarios de media ya implementada no acredita purga de transcripts ni de todas las proyecciones. Faltan política aprobada por categoría, jobs aplicables y restore verificable. | [Plan canónico, P-A/P-B y D08](plan-implementacion-auditoria-agente-whatsapp-2026-09md) |
| G07 | TurnDecision.verdict limitado a cinco veredictos | **Pendiente declarado; verificar runtime antes de abordar.** El módulo conserva deuda de valores libres y de absorción de las salidas del planner por el árbitro. | [agent, “Pendiente declarado”](modules/agent.md) |
| G08 | Identidad fuerte ante teléfonos compartidos/reciclados y step-up | **Riesgo residual documentado, no bypass multitenant demostrado aquí.** Hace falta decisión y evaluación específica antes de ampliar autonomía. | [Acta B8C, riesgos](implementacion-b8c-agente-whatsapp-2026-09-22md), [plan, D07](plan-implementacion-auditoria-agente-whatsapp-2026-09md) |
| G09 | Disponibilidad con duración real/citas fuera de rejilla | **Limitación MP-5 documentada; requiere revalidación.** El dominio revalida solapes al crear; no presentar una oferta incorrecta como reserva. | [agent, deuda MP-5](modules/agent.md), [épica F3, fuera de alcance](whatsapp-agent-epica-f3-conversacion-por-objetivos.md) |
| G10 | Proactividad/plantillas, transcripción y opciones avanzadas del canal | **Roadmap condicionado.** Recordatorios/plantillas fuera de ventana, transcripción UX-14 según volumen de audio, media saliente MED-06, botones/listas, presencia/notas y búsqueda interna avanzada. No son condiciones nuevas para cerrar el Inbox obligatorio. SSE/realtime conserva NO-GO en la topología actual. | [Spec, F3/GB-1](whatsapp-agent-functional-spec.md), [auditoría Inbox](whatsapp-inbox-auditoria-2026-08-21.md), [guía vigente](CIERRE-INBOX-WHATSAPP.md), [plan Inbox, Fase 4](plan-implementacion-whatsapp-inbox-2026-08-22.md) |

## 5. Deudas aceptadas: conservar la excepción

| ID | Pendiente conservado | Decisión vigente |
|---|---|---|
| ACEPT01 | Latencia BASE B9: claim p95 **11,572640 s** frente a 10 s | **ACCEPTED_DEBT_NON_BLOCKING.** El FAIL original permanece, pero no bloquea por sí solo el cierre/consideración de activación. No exige tuning, repetir BASE ni otra campaña. Cuatro perfiles siguen NOT_EXECUTED; brecha de percentiles por organización documentada, sin inventar aceptación integral. [Decisión del 22-10](decisions/2026-10-22-b9-base-latency-accepted-debt.md). |
| ACEPT02 | Responsable y canal de alertas de purga | **ACCEPTED_DEBT_NON_BLOCKING.** No inventar entrega/atención humana. La excepción no elimina plazos de purga ni cierra incidentes persistentes. [Decisión del 23-10](decisions/2026-10-23-inbox-media-alert-ops-deferred.md). |
| ACEPT03 | D29 R1-04 sin trayectoria física acreditada | **PENDING con limitación aceptada; fase cerrada en su alcance.** No es orden de ejecutar otro ensayo ni debe reabrirse automáticamente. [Decisión del 10-10](evals/d29-r104-decision-2026-10-10.md). |

## 6. Decisiones diferidas con disparador

El [registro DD](deferred-decisions.md) conserva **13 entradas diferidas**; DD-010 está implementada. Esta es una clasificación documental, no verificación exhaustiva de cada implementación. Algunas descripciones financieras preceden p62 y necesitan conciliación.

| ID | Trabajo diferido | Disparador documentado |
|---|---|---|
| DD-001 | Balance/status de Invoice materializados como proyección del ledger | Dolor de rendimiento o allocation ledger. |
| DD-002 | LedgerEntry unificado, PSP/fees/chargebacks | Integración con pasarela de pagos. |
| DD-003 | Snapshot Z en tabla aparte | Exigencia fiscal/exportación. |
| DD-004 | Caja por terminal/register | Clínicas con varias terminales. |
| DD-005 | Archivo/WORM de atestaciones externas | Requisito de conservación correspondiente. |
| DD-006 | Allocation ledger, anticipos/wallet/saldo a favor | Necesidad de negocio. |
| DD-007 | Contra-entry generalizado | Junto a DD-002. |
| DD-008 | Ingreso cash-basis por pago parcial/día | Cambio contable aprobado y revisión del contrato de pagos vigente. |
| DD-009 | Eliminar Invoice.payment_method legacy | Estabilidad post-beta del ledger. |
| DD-011 | WAL archiving/PITR | RPO de 24h insuficiente, requisito PITR o escala indicada en el registro. |
| DD-012 | Geo-redundancia/DB gestionada | CPU, volumen de clínicas o multi-región. |
| DD-013 | Paginación+filtros/agregados server-side en catálogos crecientes | Volumen/latencia. **Pets ya está implementado**; siguen recetas/productos/agenda según módulo, previa verificación. |
| DD-014 | Índice para orden por total de Invoice | Latencia de ese orden a escala. |

Otros diferidos arquitectónicos documentados, fuera de esas 13 DD:

- **RLS Postgres** (ADR p23 propuesto): depende del tenant directo en InvoiceAuditLog y de decisión de roles/pooling. No se confunde con aislamiento ORM actual. [Remediación](audit-remediation-2026-05-26.md), [ADR p23](decisions/2026-05-26-p23-rls-tenant-isolation.md).
- **Escala:** `organization_id` en InvoiceAuditLog, particionado/retención de append-only, PgBouncer, read replica de analítica, warehouse/CDC y sharding solo con necesidad demostrada. [Remediación, capas 4/5](audit-remediation-2026-05-26.md).
- **Late arrivals:** evaluar rechazo duro frente al warning actual cuando se adopte el contrato correspondiente. [Remediación, capa 5](audit-remediation-2026-05-26.md).
- **C1:** decidir semántica 400/404 y campos FK tenant-scoped; requiere ADR/cambio coordinado del contrato. [Deuda C1](deuda/fase4-prioridad-baja.md).
- **Recuperación de contraseña por email:** diferida; hoy se documenta reset por operador. [Platform](modules/platform.md).
- **RAG/hospitalización/memoria avanzada:** propuestas/roadmap, sin convertirlas en defectos de la beta. [Auditoría RAG](auditoria-rag-agentes-iamd.md), [plan clínico](plan-implementacion-protocolos-clinicos-2026-07-09.md), [épica F3](whatsapp-agent-epica-f3-conversacion-por-objetivos.md).

## 7. Falsos pendientes y documentación que necesita reconciliarse

| Registro antiguo | Evidencia posterior / acción documental |
|---|---|
| TODOS: `unlink_family` no bloquea auto-rematch | **Resuelto en código.** `backend/apps/agent/views.py:433` asigna `auto_rematch_blocked=True` y lo guarda. No implementar de nuevo; actualizar TODOS con evidencia/prueba correspondiente. |
| B1: apply_stock_movement depende de lock externo sobre presentación | **La condición original está resuelta por ADR p31.** El servicio adquiere lock de Product internamente y de lote después. Sigue exigiendo atomic/orden de locks; no eliminar ese contrato válido. `backend/apps/inventory/services.py:37,66`. |
| Contexto: frontend aún no consume series de dashboard | **Desactualizado.** `frontend/src/pages/analytics/index.jsx` importa/usa `getFinancialSeries` y `getOperationsSeries`; ya existe consumidor. No equivale a cerrar M02/M04. |
| M2/M3/M4 y channels.0018 pendientes localmente | Cabecera vigente del cierre acredita aplicación local; los párrafos inferiores son cortes históricos. Preview/producción siguen aparte. |
| Gitleaks r12 FAIL con 3156 detecciones / 550 sin clasificar | El FAIL histórico se conserva, pero el corte del 22-10 acredita **nueva verificación PASS** con clasificación/fingerprints exactos. No presentar 3156 como credenciales activas confirmadas ni como bloqueo actual sin nuevo hallazgo. |
| Inbox sin replies, search, historial completo, unread, asignación o media entrante local | Implementaciones/evidencias de 20–23 de octubre reemplazan el diagnóstico inicial. Siguen pendientes proveedor/aceptación real y extensiones opcionales. |
| DD-010: pagos split en POS | El registro la marca **Implemented**, actualizada por p62. |
| Plan raíz de importación con todos los checkboxes vacíos | El módulo documenta máquina de conflictos, preview y conteos actuales; ADR p61 acredita importador de inventario implementado. No marcar el plan completo como ausente por las casillas; verificar criterios puntuales. |
| P1-6A: faltan deploy.sh, rollback y backup pre-deploy | Ya existen `scripts/deploy.sh`, `rollback.sh`, `pre-deploy-backup.sh` y runbooks. Falta acreditar operación donde corresponda, no volver a escribirlos por ese diagnóstico antiguo. |
| Contexto: inconsistencia `billing=cancelled` vs `appointments=canceled` | El lifecycle Billing fue sustituido por p62 y la auditoría posterior; no aplicar un rename basado en estados financieros legacy. |
| docs/deuda/README: Fase 2 tiene 4 ítems | El archivo enlazado contiene A1–A7 y D2/D5/D6/D7. Índice/conteos no están conciliados; B4 también duplica parte de A1. |
| Referencias a docs/day6/POST-BETA-DEBT.md y docs/DEPLOY_VPS_STATUS.md | No existen en este checkout en esas rutas. Recuperar la fuente o sustituir el enlace por el registro vigente; no se pueden acreditar sus “5 pendientes” leyendo solo el índice. |
| Cifras antiguas de lint: ~6/42/64/199 | Cambian por fecha/candidato y alcance. La ejecución de esta revisión es 198 errores/19 warnings sobre `eslint .`, incluida `standalone`. |
| B9-RESULTS recomienda reducir latencia antes de otra aceptación | La decisión posterior ACEPT01 tiene precedencia y retira ese bloqueo. El informe técnico permanece intacto. |

**Conciliación del 15-11-2026.** Cada fila de la tabla quedó así:

- `unlink_family`: `TODOS.md` lo marca resuelto (`9643c03`, 19-09) y declara que falta una aserción del flag en la prueba de la vista.
- B1: línea de estado en [fase 3 de deuda](deuda/fase3-prioridad-media.md).
- Consumidor de series y `cancelled`/`canceled`: corregidos en `CONTEXTO_ACTUAL_PROYECTO.md`, que además avisa que su descripción de Billing es anterior a ADR p62.
- M2/M3/M4, Gitleaks r12, Inbox, DD-010 y B9-RESULTS: sin cambio. Sus documentos vigentes ya registraban la evidencia posterior (`CIERRE-INBOX-WHATSAPP.md` recoge el PASS del 22-10 y la decisión ACEPT01).
- Planes del importador: aviso de estado en los tres planes.
- P1-6A: nota de actualización al inicio; los scripts de deploy existen desde `6d41e14` (19-06).
- `docs/deuda/README`: conteos rehechos. La Fase 2 tiene 11 ítems, todos cerrados.
- POST-BETA-DEBT y DEPLOY_VPS_STATUS: [POST-BETA-DEBT](day6/POST-BETA-DEBT.md) se recuperó en su ruta con el estado de cada ticket (los cinco siguen abiertos). Las referencias vivas a `DEPLOY_VPS_*` citan el commit de retiro (`8886604`). Los recibos históricos que nombran esos archivos no se tocaron.
- Lint: `p1-4-frontend-reliability.md` marca sus cifras como foto de junio y registra el lint bloqueante del orden 5. Las cifras de recibos históricos no se cambian.

## 8. Orden sugerido para convertir esto en trabajo

1. **Conciliar el backlog:** retirar falsos pendientes, restaurar enlaces e identificar dueños de operación. Mantener los recibos históricos intactos.
2. **Triaje de dependencias y tareas externas de cierre:** O01–O15 según aplicabilidad. La publicación/activación es una acción separada, no autorizada por este inventario.
3. **Corrección funcional pequeña:** B7 (orden de inventario), con prueba del factor de conversión.
4. **Integridad/trazabilidad:** acordar alcance de A6/A7/D5/D6/D7, A3 y stock inicial I01/I02. Revisar efectos y backfills antes de migrar datos.
5. **Frontend:** F01 y C4/C5; luego consolidaciones A1/B2/C2. No mezclar todo en un refactor masivo.
6. **Extensiones y escala:** activar cada DD/Gxx por necesidad/prioridad explícita; conservar las tres excepciones aceptadas.

Este informe es un índice de investigación y planificación con evidencia local. Los puntos de operación requieren recibos reales, y los documentados sin comprobación completa deben verificarse antes de convertirlos en cambios.
