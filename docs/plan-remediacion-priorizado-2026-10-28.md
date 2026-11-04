# Pendientes por categoría y prioridad de remediación

Fecha: **28 de octubre de 2026**. Base: [inventario conciliado del 27 de octubre](pendientes-documentados-2026-10-27.md), con sus fuentes, estados y límites de evidencia.

Esta es una propuesta de orden de trabajo. Mantiene los IDs originales para rastrear cada pendiente. No cambia decisiones de producto anteriores ni acredita correcciones, producción o cumplimiento que todavía no se hayan comprobado.

## Cómo leer las prioridades

| Prioridad | Importancia | Momento de atención |
|---|---|---|
| **P0 — Verificar de inmediato** | Puede existir exposición activa o falta de recuperación. Primero hay que comprobar el estado real. | Revisar ahora. Si se confirma exposición o ausencia de recuperación, remediar antes de continuar el release afectado. No se afirma un incidente actual. |
| **P1 — Alta** | Integridad, conservación de datos o prerrequisito del alcance que se quiere desplegar/activar. | Primeros bloques de remediación; los gates de WhatsApp/B2 se completan antes de activar ese tratamiento. |
| **P2 — Media** | Bug funcional acotado, calidad, accesibilidad o mantenibilidad con protecciones existentes. | Siguientes bloques; los cambios pequeños pueden adelantarse si no retrasan P0/P1. |
| **P3 — Baja / condicionada** | Refactor amplio, optimización sin necesidad medida, limpieza menor o extensión futura. | Cuando se cumpla su disparador o se priorice el producto. |
| **Aceptada** | Limitación conservada por decisión expresa. | Fuera de la cola obligatoria; requiere nueva priorización para retomarse. |

La prioridad indica importancia; **el estado de evidencia es independiente**. “Falta acreditar rotación” no significa “credencial comprometida vigente”, y “falta publicar” no significa “falta programar”. Las letras A/B/C pertenecen al registro histórico: no equivalen automáticamente a P1/P2/P3 de esta propuesta.

## Vista general: categorías en orden de atención

| Orden | Categoría | Prioridad predominante | Motivo |
|---|---|---|---|
| 1 | Seguridad, accesos y recuperación | P0 de verificación / P1 si se confirma riesgo | Determina exposición real y capacidad de recuperar datos antes de cambios importantes. |
| 2 | Integridad y conservación de datos | P1 | Protege auditorías, recetas, historial y consistencia del stock. |
| 3 | Privacidad, proveedores y activación de WhatsApp | P1 antes de activar | Reúne gates externos y operativos; parte está aplazada por el usuario. |
| 4 | Inventario e importaciones | P1–P2 | Separa consistencia de unidades/ledger de errores de orden y límites de volumen. |
| 5 | Calidad del frontend y experiencia de uso | P2 | Corrige problemas concretos y hace útil el control de calidad. |
| 6 | Arquitectura backend y permisos | P2, con prerrequisitos | Reduce duplicación y elimina caminos legacy sin retirar protecciones prematuramente. |
| 7 | Clínica y analítica | P2–P3 | Completa datos profesionales y reportería con cambios de contrato controlados. |
| 8 | Agente conversacional y crecimiento del producto | P2–P3 | Investigación de problemas reales primero; extensiones según alcance aprobado. |
| 9 | Escalabilidad y decisiones diferidas | P3 / disparador | Evita invertir en infraestructura sin necesidad demostrada. |
| Transversal | Documentación y trazabilidad del backlog | P2 | Evita duplicar tareas resueltas y trabajar sobre planes obsoletos. |

El orden de categorías no obliga a esperar que toda una categoría termine para iniciar otra. Los gates externos pueden prepararse mientras avanza un cambio técnico independiente.

## 1. Seguridad, accesos y recuperación

| Prioridad | IDs | Pendiente | Primera acción / condición de cierre |
|---|---|---|---|
| **P0: verificar** | O13 | Rotación de secretos expuestos históricamente | Conciliar el plan con constancia privada de rotación. Si algún secreto expuesto sigue en uso, rotarlo y comprobar el servicio. No registrar valores en Git. |
| **P0: verificar recuperación** | O14 | Backups y restore reales | Acreditar backup recuperable y un restore verificado. Si faltan, atender antes de migraciones sensibles. Crons, monitoreo, Sentry y alertas del mismo O14 siguen en **P1** para operación. |
| **P0: triaje** | O01 | Avisos de dependencias Python/JS | Revisar vigencia, alcance y explotabilidad de los informes. Priorizar después los hallazgos aplicables; no actualizar indiscriminadamente ni convertir todos los avisos en incidentes. La política advisory de CI/B9 se conserva. |
| **P2** | B3 | Fallback RBAC y User.role legacy | Iniciar la recolección de evidencia. El corte requiere siete días sin fallback permitido, ≥500 requests y cobertura crítica; no retirar el fallback antes. La implementación se sigue en categoría 6. |

**Resultado esperado:** conocer qué riesgos están activos y contar con recuperación acreditada. Gitleaks PASS no sustituye O13, y un script de backup existente no sustituye O14.

## 2. Integridad y conservación de datos

**Plan específico acordado con el usuario:** [remediación del orden 2](plan-remediacion-orden-2-2026-10-28.md) y [metaprompt ejecutor](metaprompt-remediacion-orden-2-2026-10-28.md). Contienen las decisiones vigentes de archivo, borrado excepcional y pruebas aisladas; todavía no acreditan implementación.

| Prioridad | IDs | Pendiente | Dependencia / criterio de cierre |
|---|---|---|---|
| **P1** | A6 | Preservar InvoiceAuditLog al borrar Invoice | Decidir snapshot/FK compatible con Checkout; probar que la auditoría sobrevive. |
| **P1** | D6 | Preservar receta ante borrado del expediente | Definir relación y referencia histórica; migración/backfill y prueba de conservación. |
| **P1** | D7 | Preservar StockMovement ante borrado de presentación | Conservar el ledger y la identificación histórica; comprobar consumidores antes del cambio de FK. |
| **P1** | A5 | Archivo/soft-delete integral de Owner, Pet y Organization | Completar contrato de archivo, recuperación y trazabilidad con los guards/PROTECT actuales. No asumir que hoy todo puede borrarse libremente. |
| **P1** | A7 | Snapshot del veterinario al cerrar expediente | Definir snapshot/backfill y presentación. Implementarlo junto al writer definitivo de A3 o coordinar ambos cambios para no duplicar lógica. |
| **P1** | A3 | Cierre clínico desde servicio autoritativo | Extraer writer conservando atomicidad, idempotencia, efectos de cierre y observabilidad. Es refactor de integridad, no evidencia de que hoy falle todo cierre. |
| **P1: validar alcance** | A2 | Invariante tenant de Invoice en servicio/DB | Inventariar las defensas actuales de Checkout y probar posibles bypasses; cerrar solo las brechas demostradas. No crear una segunda ruta de facturación. |
| **P2** | D5 | Auditoría de timezone con CASCADE | Preservar evento y referencia de organización. Menor urgencia porque el borrado de organizaciones ya está restringido. |
| **P3 hoy; P1 si se habilita borrado** | A4 | Cascade de MedicalRecordProduct sin delete() custom | Mantener la condición documentada. Resolver y probar reversión de stock antes de exponer/permitir el borrado del expediente. |

Los CASCADE observados son deuda de conservación; su presencia no demuestra que exista un endpoint que permita dispararlos hoy. Confirmar alcanzabilidad y protecciones antes de elegir la migración.

## 3. Privacidad, proveedores y activación de WhatsApp

**Alcance acordado el 30-10-2026:** [plan del orden 3](plan-remediacion-orden-3-2026-10-30.md) y [metaprompt ejecutor](metaprompt-remediacion-orden-3-2026-10-30.md). El usuario limita esta entrega a privacidad de la web pública y proveedores actuales: cambios locales y pruebas aisladas en VeterinariaSaaS/LandingSaaS; cuentas y publicación a su cargo. WhatsApp y sus gates específicos quedan aplazados. El plan concilia el banner/GA4 ya existentes y sustituye para prospectos la propuesta local de 12 meses por 180 días desde el último contacto efectivo, sin campañas generales. Estos documentos no acreditan implementación ni publicación.

| Prioridad | IDs | Pendiente | Dependencia / responsable propuesto |
|---|---|---|---|
| **P0: verificar situación publicada** | O11 | GA4 sin consentimiento acreditado y retención/aviso de Formspree | Validar el repo de landing y el contenido público. Si la brecha documentada sigue activa, priorizar su corrección. O11 ya es P0 en su fuente; no se verificó remotamente en el inventario. |
| **P1** | O10 | Instrumentos contractuales de proveedores activos | Titular de cuentas y revisión correspondiente: confirmar, aceptar cuando aplique y archivar evidencia. |
| **P1 por categoría de datos** | G06 | Política y purga de chat/texto/metadata/flow/evidencias | Definir política y mecanismos por categoría. La purga de binarios no cierra transcripts ni todas las proyecciones. |
| **P1 antes de activar B2/Meta** | O04 | Región, cuenta e instrumento contractual B2/Meta | Conciliar el proveedor real y tratamiento previsto. Preparar la documentación antes de activar el tratamiento. |
| **P1 antes de activar; aplazado** | O02 | B2 dedicado para media | Usuario/infraestructura: provisión y configuración reales. Su prioridad condicionada no revoca el aplazamiento autorizado. |
| **P1 antes de activar** | O03 | Purga, capacidad del mantenimiento y restore reales | Después de O02 y de definir la configuración O04. Verificar objetos/versiones, revocaciones independientes y recuperación. |
| **P1 antes de activar** | O05 | Publicar aviso actualizado | Revisión final y fecha efectiva, coordinadas con los proveedores/tratamiento realmente definidos. El borrador y build ya existen. |
| **P1 después de publicar** | O06 | Sincronizar versión legal/reaceptación | Depende de O05. Usar fecha y URL publicadas y verificar cuentas de prueba. |
| **P1 antes de activar; a cargo del usuario** | O07 | Meta y aceptación de recepción | Prueba real de ticks, replies, media y DoD. No sustituir con mocks ni iniciar el ensayo por esta clasificación. |
| **P1 antes de activar** | O08 | Cobertura humana, fallback y autorización | Acreditar responsables de Inbox/seguridad clínica y procedimientos; aprobar alcance por clínica/capacidad. |
| **P1 antes de release** | O09 | Despliegue/migraciones de preview y producción | Validar candidato y gates aplicables, backups y rollback antes del release. Las migraciones locales aplicadas no se repiten como pendientes. La activación se controla separadamente. |
| **P2** | O12 | Endpoints ARCO automatizados | Definir alcance y evidencias manteniendo el procedimiento manual vigente mientras tanto. |
| **P2 antes del rollout de onboarding** | O15 | Teléfonos existentes/contactos de orgs internas | Limpieza/captura manual; no reimplementar los seis PRs terminados. |

**Secuencia orientativa:** O04/O10 → O02 → O03; O05 → O06; O07/O08 se preparan según sus accesos. O09 necesita los gates del alcance desplegado, y cualquier activación requiere comprobar el conjunto pertinente. Los plazos externos no se convierten en estimaciones de programación.

## 4. Inventario e importaciones

**Alcance acordado el 30-10-2026:** [plan del orden 4](plan-remediacion-orden-4-2026-10-30.md) y [metaprompt ejecutor](metaprompt-remediacion-orden-4-2026-10-30.md). I01/I02/B7/I03/I05 se implementarán localmente con pruebas y migraciones solo en bases aisladas; I07 se limita a diagnóstico y propuesta con aprobación por producto; I04/I06 permanecen aplazados. El usuario acordó movimiento inicial atómico, alias/factor coherentes con corrección determinista del alias antiguo, detalle de conflictos paginado y código demo específico. Base habitual y VPS quedan intactos. Estos documentos no acreditan implementación ni regularización de históricos.

| Prioridad | IDs | Pendiente | Orden y motivo |
|---|---|---|---|
| **P1** | I01 | Stock inicial manual sin movimiento de ledger | Primero fijar contrato autoritativo y tratamiento de históricos; luego corregir nuevas altas y decidir reconciliación. Importa por auditabilidad del stock. |
| **P1** | I02 | quantity y conversion_factor inconsistentes entre caminos | Abordar con el diseño de I01, pero verificar por separado paridad y backfill. No alterar datos históricos sin clasificación. |
| **P2; cambio pequeño** | B7 | Orden incorrecto de “Valor en stock” | Reutilizar helpers y anclar ejemplo con factor distinto de 1. Es bug visible y acotado, sin pérdida de datos demostrada; puede ser el primer cambio de código mientras se preparan P1. |
| **P2** | I03 | conflicts[] sin límite | Confirmar impacto de payload/memoria y definir tope/paginación con conteos honestos. Mantiene su condición de deuda aceptada del ADR. |
| **P2, después de I01** | I07 | Productos sin baseline verificable | Evaluar movimientos de apertura solo después de definir contrato y evitar duplicar stock. |
| **P3 por volumen** | I04 | Locks acumulados en importaciones grandes | Ya acotado por MAX_ROWS=2000; medir antes de optimizar. |
| **P3** | I05 | 403 demo sin código específico | Decisión de contrato; el bloqueo existe. No representa permiso abierto. |
| **P3 por producto** | I06 | Multi-presentación, lotes y múltiples orígenes/sucursales | Definir cada extensión cuando existan archivos/casos reales. |

## 5. Calidad del frontend y experiencia de uso

| Prioridad | IDs | Pendiente | Orden y motivo |
|---|---|---|---|
| **P2; priorizar reglas sensibles** | F01 | Lint: 198 errores y 19 warnings en la revisión del 27-10 | Separar app/standalone y agrupar por regla/impacto. Revisar primero auth, hooks y comportamiento; después avisos cosméticos. Pasar a blocking al cerrar el alcance definido, no simplemente ocultar errores. |
| **P2** | C5 | Controles de pago sin nombre accesible | Corrección pequeña de uso real; puede compartir entrega con C4 si conserva alcance y pruebas. |
| **P2** | C4 | Matemática de pagos duplicada | Centralizar sin cambiar redondeo/cambio; mantener tests de dinero. |
| **P2** | C3 | useAuth/AuthProvider en mismo archivo | Separar exports/imports manteniendo restauración de sesión y renovación de token. No mezclar con una reescritura de auth. |
| **P3** | F02 | Extraer subcomponentes/lógica pura de billing | Dividir por unidades; es mantenibilidad, no una reparación general del flujo de cobro. |
| **P3** | F03 | StatusBadge/SortHeader pendientes de consolidar | Uniformidad y mantenimiento; verificar sitios actuales antes de migrar. |
| **P3; cambio documental pequeño** | C6 | Docstring mapFieldErrors incompleto | Corregir explicación sin tocar comportamiento. Puede acompañar una entrega documental. |
| **P3; cambio pequeño** | F04 | Copy “Username requerido” | Ajustar terminología al tocar la pantalla correspondiente. |

No se repitió lint para ordenar el backlog: las cifras son las del inventario y no significan 198 fallos funcionales independientes.

## 6. Arquitectura backend y permisos

| Prioridad | IDs | Pendiente | Dependencia / cierre |
|---|---|---|---|
| **P2** | B3 | Corte de fallback RBAC | Solo tras evidencia operativa de categoría 1. Migrar checks directos y conservar permisos efectivos. |
| **P2** | B5 | Comando explícito de bootstrap_superuser | Sustituir signal coordinando release e idempotencia; preservar guards de colisión. |
| **P2** | B6 | seed_permissions --prune/--dry-run | Implementar reporte y poda explícita con pruebas. No ejecutar poda automática en deploy. |
| **P2** | A1 + B4 | Mixin tenant y retiro de helpers duplicados | Un único frente de trabajo. Hoy hay validaciones locales: es consolidación, no ausencia de aislamiento. |
| **P2 después de A1** | B2 | Base compartida de PrescriptionItem serializers | Mantener diferencias intencionales de requires_prescription. |
| **P2 junto al alcance de A2** | C2 | Regla generic owner→direct_sale en servicio | Conciliar Checkout antes de mover la regla. Evitar servicios de creación paralelos. |
| **P3** | D2 | Retirar endpoint deprecated de organización | Acreditar 410/uso cero; luego quitar ruta/vista. El mecanismo de Sunset ya existe. |
| **P3 por decisión arquitectónica** | C1 | Semántica 400/404 y campos FK tenant-scoped | Requiere cambio de contrato coordinado. No reescribir validadores por consistencia estética. |
| **P3** | C7 | Renombrar apps/platform por colisión stdlib | Workaround vigente; alto alcance de imports/migraciones/ContentType para una fricción de tooling. |

## 7. Clínica y analítica

| Prioridad | IDs | Pendiente | Dependencia / cierre |
|---|---|---|---|
| **P2** | M01 | Cédula profesional en usuario/documentos | Definir captura, modelo y PDF, con revisión del requisito aplicable. |
| **P2** | M03 | Peso únicamente en VitalSigns | Mapear consumidores y migrar históricos; no eliminar weight sin transición. |
| **P3; revisar contrato primero** | M05 | presentation obligatorio en InvoiceItem cuando corresponda | El TODO puede requerir reinterpretación por servicios/Checkout. Definir qué filas deben tener presentación antes de cambiar nullabilidad. |
| **P3 por reporting oficial** | M02 | Analítica clínica LITE→snapshots formales | ADR, KPIs, anchors, datos estructurados, dual-write y aprobación del PO. La analítica LITE ya funciona. |
| **P3 por decisión de negocio** | M04 | Charts revenue_paid_net | Sign-off y revisión de schema/semántica. No convertir el cambio de métrica en fix automático. |

## 8. Agente conversacional y crecimiento del producto

| Prioridad | IDs | Pendiente | Dependencia / cierre |
|---|---|---|---|
| **P2** | G01 | Investigar repetición de preguntas de identidad | Obtener caso real/evidencia de tools; distinguir dato no capturado de dato ignorado antes de elegir fix. |
| **P2** | G09 | Oferta con duración real/citas fuera de rejilla | Revalidar limitación actual y casos reales; el dominio ya revalida solape al crear. |
| **P2 de diseño; P1 antes de ampliar datos/capacidades sensibles** | G08 | Identidad fuerte/step-up | Definir riesgo y capacidades permitidas ante teléfonos compartidos/reciclados. No afirmar bypass demostrado. |
| **P3; P1 si la capacidad se incluye en el release** | G05 | Altas compuestas E5 con parcial/idempotencia por paso | Mantener fuera de beta inicial hasta acreditar esa capacidad; no simular atomicidad inexistente. |
| **P3 por alcance** | G02 | E1: referencias/continuidad | Revalidar consumidores y contrato mínimo de contexto; referencia no concede autoridad. |
| **P3 por alcance** | G03 | E2: varios objetivos suspendidos | Extensión de producto, no requisito nuevo del Inbox básico. |
| **P3 por alcance** | G04 | E3: avisos adicionales de atención humana | Reutilizar Inbox/Notification; los avisos no prueban atención humana. |
| **P3** | G07 | Cinco veredictos de TurnDecision | Verificar productores/consumidores antes de reducir vocabulario y ampliar autoridad del árbitro. |
| **P3 por demanda** | G10 | Plantillas/proactividad/transcripción/media saliente y canal avanzado | Descomponer por necesidad real. SSE mantiene NO-GO bajo topología actual; no se habilita como optimización rutinaria. |

G06 se clasificó una sola vez en categoría 3 porque su prioridad principal es privacidad y conservación de datos.

## 9. Escalabilidad y decisiones diferidas

Todas las filas conservan **P3 por disparador**, sin compromiso de implementación inmediato. Si aparece el requisito que las motiva, se reevalúa su prioridad con evidencia.

| Área | IDs | Trabajo y disparador |
|---|---|---|
| Finanzas | DD-001 | Proyección materializada de balance/status cuando el cálculo o allocation ledger lo requiera. |
| Pagos | DD-002 + DD-007 | Ledger unificado y contra-entry generalizado al integrar PSP. |
| Caja | DD-003 | Snapshot Z en tabla aparte por requisito fiscal/exportación. |
| Caja | DD-004 | Register/terminal cuando haya operación multi-terminal. |
| Conservación | DD-005 | Archivo/WORM de atestaciones cuando el requisito correspondiente esté definido. |
| Finanzas | DD-006 | Anticipos/wallet/allocation ledger por necesidad de negocio. |
| Métricas | DD-008 | Ingreso cash-basis por pago/día tras decisión contable y revisión del contrato vigente. |
| Limpieza de modelo | DD-009 | Retirar payment_method legacy al estabilizar el ledger. |
| Recuperación | DD-011 | WAL/PITR si el RPO actual deja de ser aceptable. Esto no pospone verificar backups/restore actuales en O14. |
| Infraestructura | DD-012 | Geo-redundancia/DB gestionada por escala, CPU o requisito multi-región. |
| Colecciones | DD-013 | Paginación, filtros y agregados server-side por crecimiento. Pets ya está implementado. |
| Rendimiento | DD-014 | Índice por total de Invoice cuando la latencia lo justifique. |
| Aislamiento DB | ADR p23 | RLS: depende de tenant directo en InvoiceAuditLog y decisiones de roles/pooling. |
| Escala | Capas 4/5 del plan de remediación | organization_id en InvoiceAuditLog, particionado, PgBouncer, réplica de lectura, warehouse/CDC y sharding según volumen. |
| Analítica | Late arrivals | Cambio de warning a rechazo duro únicamente con contrato aprobado. |
| Infraestructura | C8 | Despliegue independiente de landing cuando se priorice desacople/disponibilidad. |
| Cuenta | Reset por email | Requiere alcance y SMTP; hoy existe reset por operador. |
| Producto | RAG/hospitalización/memoria avanzada | Propuestas a evaluar según demanda y alcance, sin declararlas bugs de la beta. |

DD-010 se excluye: pagos split en POS ya figura implementado.

## 10. Deudas aceptadas: fuera de la remediación obligatoria

| IDs | Limitación | Tratamiento |
|---|---|---|
| ACEPT01 | Latencia BASE B9 p95 11,572640 s frente a 10 s | No bloqueante por decisión expresa. Conservar FAIL original/perfiles no ejecutados; no iniciar tuning ni otra campaña. |
| ACEPT02 | Responsable y canal de avisos de purga | No bloqueante por decisión expresa. No inventar entregas/atención ni extender la excepción a incidentes reales de purga. |
| ACEPT03 | D29 R1-04 PENDING | Fase cerrada con limitación aceptada. No reabrir automáticamente ni iniciar ensayos. |

I03/I04/I05 también mantienen su carácter de deuda aceptada del ADR. Su posición P2/P3 es una recomendación de seguimiento, no una conversión en requisito bloqueante.

## 11. Documentación y tareas ya resueltas

**Prioridad P2 transversal:** conciliar TODOS, índices, enlaces rotos y estados recientes; conservar los recibos históricos y enlazar la evidencia posterior. Puede hacerse mientras se resuelven dependencias externas.

No programar remediación funcional nueva para:

- `unlink_family`: el bloqueo de auto-rematch ya existe.
- B1: apply_stock_movement ya adquiere lock interno sobre Product.
- DD-010: split de pagos implementado.
- Consumidores frontend de series: ya existen.
- Replies, búsqueda, unread, asignación e historial/media entrante local de Inbox: hay implementación acreditada; faltan los gates reales aplicables.
- Migraciones locales ya aplicadas y scripts de deploy/rollback/backup pre-deploy ya existentes.
- Gitleaks histórico r12: mantener su resultado histórico junto con el PASS posterior; no contarlo como miles de credenciales vigentes.

Corregir referencias ausentes a POST-BETA-DEBT/DEPLOY_VPS_STATUS y los conteos antiguos de deuda/lint. El detalle está en [inventario, §7](pendientes-documentados-2026-10-27.md).

## Orden concreto de ejecución propuesto

| Bloque | Trabajo | Salida verificable |
|---|---|---|
| **0. Confirmar riesgos** | O13, recuperación de O14, triaje O01 y situación publicada O11 | Estado real y acciones acotadas; remediación inmediata solo donde el incumplimiento esté confirmado. |
| **1. Preparar decisiones y cerrar un bug pequeño** | Diseñar A6/D6/D7/A5/A7 y contrato I01/I02; corregir B7 en entrega acotada | Plan de datos/migraciones y prueba de orden de inventario. La rapidez de B7 no desplaza P0. |
| **2. Integridad y trazabilidad** | Implementar entregas separadas de conservación; coordinar A3/A7; validar A2; corregir I01/I02 | Pruebas significativas de conservación, aislamiento, stock y no duplicación de efectos, más plan de históricos. |
| **3. Calidad y consolidación** | F01 por riesgo, C4/C5, C3, A1/B4→B2 y B5/B6 | Calidad verificada por módulo; corte B3 solo cuando cumpla evidencia operativa. |
| **4. Cierre operativo del alcance elegido** | O02–O10, O14 restante, O15 y G06 según tratamiento | Recibos reales de almacenamiento, publicación, reaceptación, operación y release; respetar aplazamientos y autorizaciones de activación. Preparación puede comenzar antes. |
| **5. Evolución del producto** | G01/G09, clínica/analítica y P3 por disparador | Alcance priorizado y criterio de aceptación por entrega, sin reabrir deudas aceptadas automáticamente. |

La clasificación no ejecuta fixes, upgrades, publicaciones, despliegues ni activaciones. El inventario conserva las evidencias originales para revisar cada entrega antes de implementarla.
