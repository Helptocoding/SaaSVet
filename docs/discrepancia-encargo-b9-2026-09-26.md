# B9 — Discrepancia de alcance y parada previa a implementación

Fecha: 2026-09-26. Estado del encargo: **BLOCKED por discrepancia con el plan
canónico; implementación B9 no iniciada**. Activación operacional:
**PENDING_ACTIVATION_REQUIREMENTS**. Este informe no modifica el contrato canónico,
no aprueba un diseño alternativo y no acredita cierre técnico de B9.

## 1. Baseline y cambios ajenos

HEAD inicial verificado: `55d122bcfb26f41b7f23ce0bb523b464017f3a4c`, idéntico al
baseline obligatorio. Se ejecutaron `rtk --version` (0.48.0), `rtk gain`,
`rtk git rev-parse HEAD` y `rtk git status --short`.

Estado inicial exacto:

```text
 D DEPLOY_VPS_PLAN.md
 D DEPLOY_VPS_STATUS.md
?? docs/auditoria-agente-conversacional-veterinario-2026-09-10.md
```

Se conservan las dos eliminaciones y el archivo sin seguimiento. SHA-256 del
archivo de auditoría antes de crear este informe:
`f23f123b168ce596386e2104faf753518f7b1a94eb114a095f6e71f0b7d1652e`.
El único archivo creado por este intento es este informe; no se incluyen cambios
ajenos en ningún commit. No se creó commit de implementación ni documental.

## 2. Condición de parada aplicada

El encargo establece: «El plan canónico es autoridad sobre este prompt» y
«Si B9 tiene un alcance diferente detente y documenta la discrepancia antes de
modificar código».

Se leyó completa la sección B9 del
[plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md), líneas
703–729 del baseline. Su título es **Evaluación y límites mínimos para activar
beta**. La diferencia afecta entregables, modelos y criterios de aceptación;
no es una diferencia de nomenclatura.

La sección define expresamente:

> B9 entrega harness, contabilidad/límites y reporte reproducible bajo contención.

Por esa instrucción se detuvo la implementación antes de modificar runtime,
tests, migraciones, configuración o documentos que constituyen el contrato.
No se sustituyó unilateralmente la B9 canónica por el diseño del encargo ni se
amplió silenciosamente el trabajo para reunir ambos alcances.

## 3. Comparación concreta

| Tema | B9 canónica | Encargo recibido | Consecuencia |
| --- | --- | --- | --- |
| Entrega principal | Composición E2E, contabilidad, límites y acta reproducible por capacidad (§7/B9, 705–718) | Mecanismo persistente de readiness y activación por organización/capability | Implementar solo ese mecanismo no satisface B9 |
| Harness | Guiones por worker/HTTP/sender reales y Meta controlado; cliente responde a Message emitido (710) | Corpus y pruebas de readiness/activación | Faltaría demostrar las etapas y causalidad del guion E2E exigido |
| Contabilidad LLM | Todas las llamadas, roles, retries, timeout y usage desconocido; correlación LLMCall→TurnWork (711, 724) | No exige implementar esta contabilidad | Faltaría un entregable obligatorio |
| Presupuesto durable | Reserva de llamadas/cupo antes de llamar bajo witness; restart no repone cupo (713) | No especifica esa frontera | Un ledger de activación no sustituye COST-01 |
| Concurrencia | Dos planners, sender separado, un trabajo por conversación y como máximo uno por org para el ensayo; claim protegido con fila existente (712, 716) | Carreras de activation/revocation/execution | Las carreras pedidas no sustituyen el límite operativo de B9 |
| Perfil y medición | PROFILE-BETA-1 con carga, tiempos, ventanas, muestras, p95 y fallos definidos (716, 720) | No incluye ejecutar ese perfil | Faltaría la evidencia que decide el gate de carga |
| Tests identificados | EVAL-01/02, COST-01, SCALE-01/02 (722) | B9-01…30 y B9-FI-01…10 sobre activación | Son conjuntos distintos; no se puede declarar equivalencia |
| Persistencia | FK LLMCall→TurnWork y contadores de presupuesto si faltan; reutilizar configuración/constantes para límites (724; §8.1) | Ledger de requisitos con provenance, auditoría y posible activation_revision | El plan no especifica ese nuevo contrato persistente ni su frontera transaccional |
| Alcance de capacidades | READ pública, READ personal y cada WRITE seleccionado; intersección release/política/identidad/contrato (726; §14) | Foco en las cinco operaciones WRITE ya implementadas | READ y evaluación transversal siguen formando parte del alcance canónico |

### Coincidencias que se conservan

- Separar cierre técnico, evidencia operacional y activación efectiva.
- Mantener contención durante desarrollo y ensayos; no activar ni desplegar.
- Aprobar capacidades individualmente y permitir una política organizativa más
  restrictiva; terminar B8 no abre otras capacidades.
- Requerir cobertura humana, protocolo/revisión veterinaria y privacidad aplicable.
- No implementar E1–E5 por anticipación ni convertir E4 en dependencia fija.
- P-A/P-B son dependencias de activación según categorías/plazos aplicables. El
  plan no obliga a implementarlas dentro de B9. Su exclusión del encargo no es,
  por sí sola, una contradicción ni permiso para declararlas satisfechas.

El plan respalda gates por capacidad y organización. Esa coincidencia no prueba
que exija el ledger, los comandos administrativos o una revisión persistente
de activación descritos en el encargo. Esas decisiones deben alinearse con el
alcance canónico antes de congelar un contrato de implementación.

## 4. Inventario preliminar del baseline

Este inventario recoge las fronteras contrastadas antes de detener el encargo.
No se presenta como auditoría exhaustiva ni como nueva aceptación de B0–B8E.
Se consultó primero el grafo; no encontró los símbolos recientes de ejecución.
Se usó lectura acotada del código actual para esos símbolos, conforme al fallback
permitido cuando el grafo devuelve resultados insuficientes.

| Gate / evidencia | Autoridad comprobada | Alcance y límite |
| --- | --- | --- |
| Contención B0 | `intake.CONTAINED_WRITES`, derivada de `WRITE_BUSINESS`; `operation_execution._gate` | Cierra nuevos efectos. No es una aprobación clínica |
| Registro de capabilities | `operation_execution.REGISTRY` y `Registration.enabled` | Cinco adapters registrados; disponibilidad técnica no concede activación |
| Configuración de ejecución | `config/settings.py:98`, `AGENT_OPERATION_EXECUTION_ENABLED = {}` | `_gate` exige un diccionario y el kind exactamente en `True` |
| Gate B7B | `config/settings.py:95`, default `False`, y `_gate` | Puede configurarse por entorno; se verificó el default de código, no el valor de un proceso desplegado |
| Contrato del adapter | `_gate`: adapter presente y `transaction_mode == LOCAL_ATOMIC` | Requisito adicional a consentimiento y flags |
| Scope tenant/capability | `_definition_reason` | Concordancia de org/canal/contacto/goal/operación/entidades, digest y actividad |
| Consentimiento | `execute_authorized_operation`, `execution_authorization_evidence` | AUTHORIZED, modo admitido y evidencia B7B causal; no basta una flag |
| Identidad y permiso actual | `operation_permission.actor_permission(..., purpose='execute')` | Relación vigente, tenant, owner, restricciones familiares y estados permitidos |
| Ownership/handoff/safety | `_authority_reason` | Epoch, ausencia de takeover/handoff/señal de safety; no se reemplazan por readiness |
| Binding/identidad/TTL | `_authority_reason` | Revisiones vigentes, sin replacement, nuevo input ni consentimiento vencido |
| Preconditions de dominio | `adapter.validate_preconditions` dentro de B8A | Se revalidan definición y autoridad después de locks del dominio |
| Interruptor por organización | `AgentSettings.enabled`, default `False`; runbook §6 | Control de automatismos existente; no es una certificación de requisitos operativos ni gate B9 nuevo en B8A |
| Automatización safety | `AGENT_SAFETY_AUTOMATION_ENABLED`, default `False`; runbook B5 | Apertura supeditada a revisión veterinaria y requisitos operacionales |
| Evidencia de atención humana | Runbook B5: claim requiere `agentinbox.claim` y org correcta | Abrir Inbox no acredita acuse ni presencia/cobertura de un responsable |

Orden observado para **nuevos efectos** en B8A: locks de autoridad → definición
y scope → consentimiento/modo/evidencia → permiso → tratamiento de resultados
previos/reconciliación → autoridad actual → gates técnicos → preconditions de
dominio → revalidación → efecto/evidencia/resultado en la transacción local.
Dentro de `_gate`: B0 → registry enabled → flag del kind → B7B enabled → adapter
presente → contrato LOCAL_ATOMIC. No se afirma que el orden conceptual del encargo
ya exista en el baseline. Reconciliar un efecto histórico no es ejecutarlo otra vez.

Locks base documentados y observados: Conversation → TurnWork → ContactIdentity →
Goal → ConversationOperation; después, locks del adapter. El acta B8E documenta
Organization FOR SHARE → Owner FOR SHARE NOWAIT → Pet/ledger. No se añadió lock
B9 ni se ensayó un nuevo orden.

Fuentes: [B0](implementacion-b0-agente-whatsapp-2026-09-13.md),
[contrato B7B](contrato-consentimiento-causal-b7bmd),
[contrato B8A](contrato-execution-guard-b8amd),
[cierre B8E](implementacion-b8e-agente-whatsapp-2026-09-25.md) y
[runbook](runbooks/agent-whatsapp.md), en particular B5, B7B y B8E.
La revisión completa de todos los contratos/ADRs/actas B5/B7B/B8A–E sigue pendiente
para la implementación que resulte del alcance aclarado.

## 5. Requisitos pendientes de activación

El registro operativo B0 y el runbook B5/B7B/B8E mantienen
**PENDING_ACTIVATION_REQUIREMENTS**. No se encontraron en esas fuentes nombres
ni aprobaciones que permitan sustituir ese estado.

- [ ] Identificar y confirmar cada clínica piloto y su alcance/tasa de uso.
- [ ] Asignar responsable de Inbox y acordar cobertura humana.
- [ ] Asignar responsable veterinario/safety y aprobar realmente corpus/protocolo.
- [ ] Asignar responsable de privacidad y aportar la política/revisión aplicable
      de P-A; acreditar P-B para las categorías/plazos comprometidos cuando aplique.
- [ ] Definir, configurar y validar el canal alternativo de escalamiento/fallback
      de cada clínica, sin inventar destinos ni horarios.
- [ ] Aprobar lista explícita de READ/WRITE del release y su restricción por org,
      identidad y contrato desplegado.
- [ ] Completar EVAL-01/02, COST-01, SCALE-01/02 y PROFILE-BETA-1 con evidencia de
      latencia, muestras, errores, límites y durabilidad.
- [ ] Aportar eval real de promoción de autonomía conforme a §9.3, sin contar
      skips/fallos del proveedor como aprobación.
- [ ] Verificar cobertura humana, cola de incertidumbre atendible, migraciones
      ensayadas y artefacto candidato según el gate de release de §9.3.
- [ ] Ensayar handoff y procedimientos de cierre/rollback aplicables antes de
      autorizar tráfico real, conservando la evidencia de operación.
- [ ] Registrar la decisión operacional de activación del alcance aprobado,
      separada del cierre técnico y del despliegue autorizado.

Esta lista consolida requisitos documentados; no los acredita. No equivale a
consentimiento legal, protocolo clínico nuevo ni aprobación de una organización.

## 6. Validación de este intento

No se ejecutaron suites B9, regresión histórica, pruebas de concurrencia, failure
injection, corpus ni migraciones. No se ejecutaron `manage.py check`,
`makemigrations --check --dry-run` o `migrate --check`: no hay entrega de código
que cerrar, y la condición de parada precede a esa implementación.

Los **2.097/2.097 IDs** son evidencia histórica declarada en el acta B8E del
baseline, no pruebas reejecutadas por este intento. No se publican métricas B9
con valor cero porque no existe corpus ejecutado. No hay PIDs/locks PostgreSQL
nuevos que reportar.

Verificación final: HEAD sigue en el baseline; `git status --short` contiene
exactamente los tres cambios preexistentes y este informe; el SHA-256 del archivo
ajeno coincide. `git diff --check` terminó con código 0. Todos los enlaces locales
del informe existen y su tabla contiene los 53 puntos consecutivos. Los valores
documentados de producción permanecen sin editar:
B0 cerrado, B7B default `False`, execution flags `{}`. No se consultó una base
productiva ni un proceso desplegado; **0 organizaciones activadas por este
intento** no se presenta como censo comprobado de organizaciones en producción.

## 7. Reporte de los 53 puntos solicitados

| N.º | Punto | Resultado de este intento detenido |
| --- | --- | --- |
| 1 | Estado técnico B9 | BLOCKED por discrepancia contractual; no implementada |
| 2 | Activation readiness | PENDING_ACTIVATION_REQUIREMENTS documentado |
| 3 | Baseline | HEAD exacto `55d122bcfb26f41b7f23ce0bb523b464017f3a4c` |
| 4 | Commit implementación | No creado |
| 5 | Commit documental/final | No creado; informe conservado en working tree |
| 6 | Migraciones | Ninguna creada ni aplicada |
| 7 | Cambios runtime | Ninguno |
| 8 | Cambios preexistentes | Dos eliminaciones y auditoría sin seguimiento preservadas (§1) |
| 9 | Contrato B9 final | No se congeló otro; prevalece §7/B9 canónica (§3) |
| 10 | Gates descubiertos | Inventario preliminar con autoridad y límites (§4) |
| 11 | Requisitos técnicos | Harness, contabilidad, presupuesto, concurrencia, perfil y gates canónicos (§3) |
| 12 | Requisitos operativos | Checklist documental pendiente (§5) |
| 13 | Modelo de readiness | No se diseñó/persistió un modelo alternativo |
| 14 | Modelo de activation | Sin modificación; intersección canónica de release/política/identidad/contrato |
| 15 | Granularidad tenant/capability | Prevista por el plan; nuevo mecanismo no implementado |
| 16 | Beta cohort | Sin alta de organizaciones ni cohorte nueva |
| 17 | Activation revision/fencing | No añadida; necesidad/diseño B9 sin resolver |
| 18 | Integración B8A | Frontera existente intacta |
| 19 | Lock order | Orden baseline descrito en §4; sin locks B9 |
| 20 | Revocación | Sin mecanismo ni pruebas B9 nuevos |
| 21 | Reactivación | No realizada ni implementada |
| 22 | Prevención de revival | Garantía B9 no demostrada; no se fabrican snapshots/consentimientos |
| 23 | Kill switches | Baseline intacto; sin comandos de activación/desactivación ejecutados |
| 24 | Auditoría | Este informe documental; no ledger de activación añadido |
| 25 | Permisos administrativos | Sin cambios ni nuevo rol |
| 26 | Inspector/readiness report | Inspector existente intacto; reporte B9 runtime no implementado |
| 27 | Commands | Ningún comando operacional B9 creado/ejecutado |
| 28 | Defaults/legacy | Defaults intactos; sin backfill ni migración de orgs |
| 29 | Organizaciones productivas activadas | 0 por este intento; censo productivo no consultado |
| 30 | Cinco capabilities | Registradas en baseline; ninguna activada ni revalidada con B9 |
| 31 | Tests funcionales | B9 no ejecutados |
| 32 | Tests permissions | B9 no ejecutados |
| 33 | Tests multiproceso | B9 no ejecutados |
| 34 | PIDs/locks observados | Ninguna observación PostgreSQL nueva |
| 35 | Failure injection | B9 no ejecutada |
| 36 | Corpus | B9 no creado ni ejecutado |
| 37 | Métricas | Sin resultados B9; no se reportan ceros sintéticos |
| 38 | Regresión B0–B8E | 2.097 IDs aceptados según acta baseline; no reejecutados |
| 39 | Regresión dominios | No reejecutada |
| 40 | Checks finales | Verificación documental/Git; checks Django/PostgreSQL no ejecutados (§6) |
| 41 | B0 efectivo | Contención en código intacta; sin inspección de procesos productivos |
| 42 | B7B efectivo | Default de código False; entorno desplegado no consultado |
| 43 | Operation flags | Configuración fuente `{}` intacta; sin inspección de procesos productivos |
| 44 | PENDING_ACTIVATION_REQUIREMENTS | Se conserva, sin acreditar requisitos |
| 45 | Checklist restante | §5, sin valores inventados |
| 46 | Hallazgos actualizados | Ninguno; matriz H01–H20 intacta |
| 47 | Riesgos residuales | Sin nueva evidencia sobre identidad fuerte, teléfonos compartidos/reciclados, step-up, privacidad, exactly-once externo o pérdida eléctrica |
| 48 | Rollback | No hay cambio runtime/DB que revertir; procedimientos baseline intactos |
| 49 | Documentación | Solo este informe de discrepancia; plan/runbook/ADRs sin enmiendas |
| 50 | No deploy | Confirmado: ninguno realizado |
| 51 | No E1–E5 | Confirmado: ninguna implementada |
| 52 | No P-A/P-B | Confirmado: ninguna implementada ni declarada aprobada |
| 53 | Cierre técnico B9 | No procede; resolver alcance antes de implementar/aceptar |

## 8. Decisión necesaria para reanudar

Reformular el encargo para cubrir B9 canónica, incluidos harness, presupuesto,
contabilidad, límites y PROFILE-BETA-1, y aclarar cuáles requisitos adicionales
del mecanismo de activación deben incorporarse sin sustituirlos; o aprobar
explícitamente una enmienda del plan que ubique ambos conjuntos de entregables.

No basta cambiar el nombre de B9 ni aprobar flags. La parada responde a la
instrucción expresa del encargo sobre discrepancias de alcance; no a falta de
responsables de una clínica, que seguiría bloqueando activación pero no el
desarrollo de un contrato técnico acordado.
