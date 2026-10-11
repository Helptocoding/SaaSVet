# Revisión de cierre — Inbox y agente WhatsApp

Fecha: **2026-10-11**. Rama: `codex/e4-capacity-scheduling`. HEAD: `825db75df68bf076929fa787e77beefe96803350`.

**Dictamen: el conjunto no puede declararse completamente implementado, versionado y listo para uso real. Sí están cerrados E4 y la fase D29 en sus alcances y con sus límites aceptados.** El pendiente inmediato de la línea B9 es consolidar su aceptación y la trazabilidad de Git; no hace falta reabrir R1-04 ni iniciar otra ronda de experimentos para efectuar ese cierre administrativo.

Esta revisión no cambia estados de aceptación ni autoriza capacidades. Contrasta documentos, código, recibos existentes y Git local. No ejecutó tests, cargas, sandbox Meta, proveedores, PostgreSQL ni producción; no modificó runtime, planner, contratos, evidencias selladas, staging, commits o ramas.

## 1. Qué significa A–E en cada plan

Existen dos planes relacionados, con criterios de cierre diferentes:

- **UX del Inbox:** la [auditoría del 21 de agosto](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/whatsapp-inbox-auditoria-2026-08-21.md:485) llama A–E a su roadmap; el [plan ejecutable del 22 de agosto](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/plan-implementacion-whatsapp-inbox-2026-08-22.md:182) lo organiza en fases 0–5. Su Definition of Done exige fases 0–3 completas y una prueba de operación con recepción. No está cumplido.
- **Remediación del agente:** el [plan canónico de septiembre](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/plan-implementacion-auditoria-agente-whatsapp-2026-09md:274) usa B0–B9, extensiones E1–E5 y privacidad P-A/P-B. **B9A–B9E son hitos internos de B9**, según el [mapa R01–R15](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/mapa-interno-b9-2026-09-26.md:4). De esta línea surgieron E4 y el trabajo D29 posterior.

Los pendientes UX no se convierten automáticamente en condiciones de B9 o de una beta de texto acotada. Tampoco cerrar el trabajo del agente acredita por sí mismo el DoD del Inbox.

| Alcance | Estado sustentado | Qué falta para el cierre que le corresponde |
|---|---|---|
| B0–B8E | Cierres técnicos documentados, bajo contención | No activan autonomía por sí solos |
| B9A–B9D | COMPLETED técnico en sus asignaciones | Integración en un acta de aceptación B9 vigente |
| B9E / B9 canónica | B9 IN_PROGRESS; FAIL histórico y PROFILE posterior PASS, separados | Conciliar aceptación por versión/alcance y R01/R06–R10/R15 |
| E4 | CLOSED / CAPACITY_LIMIT_CONFIRMED / STOP_BEFORE_TUNING | Conservar límites; no es un mandato de tuning |
| Fase D29 autorizada | Cerrada con R1-04 PENDING aceptado | Ninguna acción adicional autorizada en esa fase |
| Inbox UX 0–3 | Fase 0 cerrada, fase 1 parcial, 2/3 incompletas | Requisitos funcionales y gates propios del plan UX |
| Activación de beta | PENDING_ACTIVATION_REQUIREMENTS | Requisitos humanos, privacidad aplicable y aprobación por capacidad/cohorte |
| Seguimiento e integración Git | Incompletos | Fuentes y evidencia locales sin versionar; diagnóstico histórico en otra rama |

## 2. B9 tiene un cierre formal pendiente, aunque existe un PROFILE aprobado

El [PROFILE del 2 de octubre](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-sql-2026-10-02/report.md:3) aprobó el corpus **46/46** y las cinco variantes temporales: BASE p95 **9.819540 s** y BLOCKED_LLM **9.717606 s**, frente al gate de 10 s. Por tanto, sería incorrecto afirmar que nunca se obtuvo un perfil aprobado.

Ese mismo [informe](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-sql-2026-10-02/report.md:88) dejó explícitamente B9E histórico FAIL, B9 IN_PROGRESS y el cierre formal de aceptación como encargo separado. El [dossier](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/whatsapp-agent-audit-dossier.md:387) y el encabezado del plan aún muestran cortes anteriores. Los recibos históricos siguen siendo válidos; falta un resumen vigente que los ordene.

El candidato aprobado tenía baseline `0831046`; HEAD es `825db75`. Git confirma cambios posteriores de instrumentación en `durable.py`, `services.py` y `worker.py`, además de módulos diagnósticos y tests. No son archivos idénticos. La [entrega de instrumentación](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-instrumentation-2026-10-03/README.md:225) conserva equivalencia funcional OFF/ON y **216 IDs compuestos por versión**, y sus seis hashes de runtime coinciden con las fuentes actuales. Esto aporta compatibilidad funcional; no demuestra igualdad temporal ni una nueva aceptación integral del HEAD.

**Acción mínima recomendada:** una única acta B9 vigente que evalúe R01/R06–R10/R15 con el PASS existente, la procedencia del candidato, la instrumentación posterior y la cobertura de regresión pertinente. Debe conservar los FAIL anteriores, distinguir evidencia por versión y separar pendientes de activación. No sumar las 192 regresiones D29 como si acreditaran toda la regresión histórica. Si queda una laguna material, registrarla antes de decidir cualquier verificación adicional; esta revisión no ordena repetir PROFILE.

## 3. E4 y D29 permanecen cerrados

El [cierre E4](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/report.md:212) confirma un límite de capacidad de la carga analizada y detiene el trabajo antes de tuning. No demuestra una violación del contrato vigente ni explica causalmente el TurnWork 86 del FAIL histórico. Tampoco invalida el PASS posterior del 2 de octubre.

La [decisión D29](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-phase-closure-2026-10-10/CIERRE.md:3) cierra la fase con R1-04 **PENDING**, sin convertirlo en ACCREDITED o FAILED. Faltó la cadena física forecast válido → selección vacía/yield nativo → corrección posterior → forecast obsoleto → nueva elegibilidad/claims. La ausencia de esa cadena en el único intento no prueba imposibilidad general.

R2-04 está conciliado: **240.6099271 s**, aproximadamente cuatro minutos, con verificador original PASS. La coma del resumen era decimal. No corresponde repetir esa prueba. R1-06, ambas variantes R2-09 y las siete suites tienen sus resultados acreditados en el cierre D29.

La matriz completa, caracterización comercial, definición de la envolvente E y una garantía prospectiva de espera acotada son trabajos de alcance propio. No se inician para poder cerrar administrativamente esta entrega. E1/E2/E3/E5 tampoco son requisitos universales: sólo bloquean las capacidades que expresamente los necesitan, según el [plan](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/plan-implementacion-auditoria-agente-whatsapp-2026-09md:1049).

## 4. El Inbox UX todavía tiene funcionalidad obligatoria incompleta

Estas carencias se contrastaron con el código actual, además de las actas:

| Requisito del plan UX | Evidencia actual | Consecuencia |
|---|---|---|
| HIST-01/02: historial completo y lectura estable | [loadThread](C:/Users/LAP/Desktop/VeterinariaSaaS/frontend/src/pages/inbox/index.jsx:370) carga la página reciente, reemplaza el transcript y no consume `next_before`; [efecto de scroll](C:/Users/LAP/Desktop/VeterinariaSaaS/frontend/src/pages/inbox/index.jsx:489) fuerza el fondo al cambiar la cantidad de mensajes | No se acredita scrollback completo ni preservar lectura antigua |
| PERF-01/02: lista paginada y sin N+1 | [list_threads](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/views.py:866) materializa conversaciones, consulta mensajes por hilo y trunca con `THREADS_CAP` | La lista todavía puede omitir hilos y su coste crece por hilo |
| UNR/CTX/RETRY/WIN: operación diaria | [contador](C:/Users/LAP/Desktop/VeterinariaSaaS/frontend/src/pages/inbox/index.jsx:889) sigue siendo un punto binario; header sin panel de mascotas/expediente; retry sólo `failed-local`; composer sin estado visible de ventana 24 h | No se cumple la prueba operativa global de recepción |
| RPL/MED: replies y media end-to-end | [serializer Inbox](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/serializers.py:42) y [render](C:/Users/LAP/Desktop/VeterinariaSaaS/frontend/src/pages/inbox/index.jsx:1035) no exponen/renderizan el flujo completo de media y citas | Preservar metadata en ChannelEvent para el agente no permite a recepción visualizar la foto o responder citando desde Inbox |
| TCK-01: acuses reales | Ticks implementados; el [gate sandbox Meta](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/plan-implementacion-whatsapp-inbox-2026-08-22.md:241) sigue pendiente sin acta posterior encontrada | Implementación y validación real tienen estados diferentes |

El [DoD](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/plan-implementacion-whatsapp-inbox-2026-08-22.md:1129) no está satisfecho. SSE NO-GO v1 es una decisión legítima; polish perenne, virtualización, media saliente opcional y HSM no deben añadirse indiscriminadamente a los bloqueadores. PERF-03 y los requisitos obligatorios de 0–3 sí forman parte del cierre UX vigente.

Antes de implementar RETRY-01 debe reconciliarse su formulación antigua con B4: un envío incierto no se reintenta como un fallo conocido. El plan UX necesita actualización de alcance/contratos, además de su seguimiento.

## 5. Los gates de operación y privacidad siguen separados

El [registro de readiness](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-operational-readiness.md:7) conserva requisitos PENDING_REAL y cero SATISFIED_REAL. El [release local](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/beta_release.py:58) no tiene grants productivos; los defaults mantienen consentimiento y ejecución contenidos. Esto describe el repositorio, no una inspección de producción. Por contrato, el manifest no es una barrera nueva para READ: release vacío no prueba ausencia de todo tráfico READ.

Antes de ofrecer/activar el alcance correspondiente faltan clínica/capacidades/tasa, responsables y cobertura Inbox, revisión veterinaria de protocolo/corpus, simulacro de atención, fallback, privacidad aplicable y aprobación de candidato/cutover/rollback. La [sección operativa del runbook](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/runbooks/agent-whatsapp.md:739) conserva esos requisitos.

H17/P-A/P-B no están acreditados como cerrados. La política requiere aprobación para las categorías tratadas; P-B requiere purga/restore verificables de categorías/plazos comprometidos. El comando propuesto `prune_agent_data` no existe y `prune_notifications` no acredita purga de chats. No se concluye cumplimiento legal con esta revisión. Los gates DPA/lifecycle de binarios aplican al alcance media; no se trasladan automáticamente a toda beta de texto.

## 6. Git: estar en el mismo directorio no significa estar versionado en la rama

El inventario inicial, antes de crear este informe, registró **5.869 archivos no ignorados sin seguimiento**, **2.501.325.941 bytes** (2,50 GB decimales). El índice no tiene cambios staged. Hay 2.803 rutas tracked.

| Grupo | Archivos sin seguimiento |
|---|---:|
| Harness/drivers y tests en backend | 21 |
| Auditoría fuente del 10 de septiembre | 1 |
| Decisiones de scheduling/D29 | 10 |
| Discrepancia documental B9 | 1 |
| Evals, recibos, cierres y evidencia restante | 5.836 |
| **Total inicial** | **5.869** |

La auditoría fuente, el harness completo `tests/scheduling_characterization/`, los cuatro tests nuevos y `d29-phase-closure-2026-10-10/CIERRE.md` **no existen en HEAD**. Un checkout limpio de esta rama no reproduce esa entrega ni conserva su decisión final. Tres JSON diagnósticos superan individualmente 100 millones de bytes. El inventario es de rutas/tamaños y hashes seleccionados; no representa una nueva validación integral de todos los archivos sellados.

Respecto de las ramas:

- `develop`, `codex/b8e-register-pet`, `codex/b9a-harness`, WA-01 y las ramas principales WA-02 verificadas son ancestros de HEAD. La cadena principal ya está acumulada en `codex/e4-capacity-scheduling`.
- La rama actual está **26 commits por delante del develop local** y no tiene upstream configurado. No se hizo fetch ni se afirma estado remoto actual o publicación de estos commits.
- `codex/e4-causal-diagnosis-2026-10-03` conserva el commit único **68a4a77**, no ancestro ni patch-equivalente en HEAD. Sus **43 archivos documentales/diagnósticos están ausentes del checkout actual**. La exigencia de un expediente completo en una rama requiere una disposición explícita de esa historia; no es evidencia de código de runtime faltante.
- `task/7acc74fe-PlanWA-02-F0` no es ancestro por SHA, pero sus tres commits son **patch-equivalentes ya presentes** (`git cherry`: tres `-`). No corresponde concluir que se perdió esa implementación ni duplicarla mediante merge.
- Existen cambios previos ajenos a esta revisión: eliminación de `DEPLOY_VPS_PLAN.md` y `DEPLOY_VPS_STATUS.md`, y modificación de `skills-lock.json`. Deben tener disposición propia antes de cualquier commit conjunto; se preservaron.

**Cierre recomendado de seguimiento:** versionar una selección explícita de fuentes/tests, auditoría, decisiones, actas, resúmenes e índices; asignar al material bruto una conservación verificable con hashes y ubicación duradera; integrar o documentar la disposición del diagnóstico 68a4a77. El tamaño no justifica perder evidencia ni incorporarla indiscriminadamente. Mantener la rama actual permite consolidar la entrega; borrar otras ramas no demuestra integración.

Inventarios adjuntos: [git-inventory.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/inbox-whatsapp-closure-review-2026-10-11/git-inventory.json) y [git-branch-deltas.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/inbox-whatsapp-closure-review-2026-10-11/git-branch-deltas.json). Este informe y sus adjuntos son archivos nuevos de revisión; no están incluidos en la cifra inicial ni fueron añadidos al índice.

## 7. Criterio finito de cierre

Para cerrar **el encargo técnico acotado del agente**: acta consolidada B9 por versión/alcance; resumen vigente H16/H19 enlazado a las evidencias; excepción R1-04 conservada; archivos y diagnóstico histórico con disposición verificable en la entrega. Registrar aparte las condiciones de activación y las extensiones excluidas. No iniciar automáticamente nuevos experimentos.

Para declarar **el Inbox listo para uso real según su plan UX**: completar o revisar explícitamente el alcance de las tareas obligatorias pendientes y acreditar su DoD. Una decisión de terminar el hito y transferir backlog con estado/responsable puede cerrar administrativamente la iniciativa; no equivale a marcar esas funcionalidades como implementadas.

Para **activar una beta concreta**: además, satisfacer los gates técnicos y externos aplicables y aprobar esa lista de capacidades/cohorte. Esta revisión no concede esa autorización.

## Método y límites

Revisión contrastada por las perspectivas principal, quality y security del flujo Open Code Review indicado por AGENTS.md, más inventario Git de sólo lectura. Código descubierto mediante grafo MCP y fallback dirigido cuando el índice no contenía símbolos nuevos. El CLI OCR 2.5.0 resolvió el equipo, pero su registro de estado falló con `stmt.columns is not a function`; se conservaron informes y discurso manuales en `.ocr/sessions/2026-10-11-codex-e4-capacity-scheduling/` sin afirmar registro exitoso del dashboard.

No se revalidaron físicamente los recibos ni se ejecutaron suites. La conclusión se apoya en evidencia existente, inspección de implementación y Git local; no certifica el entorno productivo ni el contenido de aprobaciones externas.
