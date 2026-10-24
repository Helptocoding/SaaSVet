# B9 — Acta consolidada de entrega técnica y evidencia

Fecha: **2026-10-11**. Encargo: consolidar B9 y resolver el versionado/conservación de la evidencia existente. Rama única de entrega: `codex/e4-capacity-scheduling`. HEAD de entrada: `825db75df68bf076929fa787e77beefe96803350`.

## Decisión y estados independientes

**Decisión posterior de ejecución, 2026-10-11:** la campaña integral autorizada de `194772677ca4e9fe1a1dec7f4dafa48396a6c583` cierra **PENDING / PREFLIGHT_BLOCKED**. La instalación frontend con el lock congelado produjo `ERR_PNPM_EPERM` al crear un enlace simbólico. Se detuvo antes del bloque 1: **0 pruebas, 0 corridas formales y cinco variantes PROFILE NOT_EXECUTED**. Discovery resolvió 87 IDs dirigidos y 3.331 de regresión; esos números no acreditan ejecuciones. La causa es de preparación del entorno y no se atribuye un fallo al producto. [Decisión, integridad, cleanup y conservación de esta campaña](../b9-integral-acceptance-1947726/REPORT.md). La aceptación integral y activación permanecen pendientes; R1-04 y los alcances E/P/UX conservan sus límites. El resto del acta conserva la procedencia de la consolidación previa y no sustituye sus recibos históricos.

**El expediente técnico B9 queda consolidado.** Se incorpora el PROFILE aprobado del 2 de octubre y la procedencia de B9A–D, E4, instrumentación y D29. Esta acta completa la consolidación documental; no ejecuta una nueva aceptación, no borra FAIL históricos y no convierte el conjunto en beta activada.

| Objeto de decisión | Estado vigente |
|---|---|
| Entregas técnicas B9A/B/C/D | COMPLETED técnico, con sus recibos y límites originales |
| Entrega documental/evidencia B9E | CONSOLIDATED, alcance y pendientes explícitos en esta acta |
| PROFILE del 2026-10-02, candidato `0831046` | PROFILE_BETA_1_PASS; 46/46 IDs únicos y cinco variantes |
| Aceptación integral de B9 para el candidato `1947726` | PENDING_INTEGRAL_ACCEPTANCE / PREFLIGHT_BLOCKED; instalación frontend EPERM, bloques y PROFILE NOT_EXECUTED |
| B9 canónica | Entrega consolidada; aceptación integral y activación pendientes. El IN_PROGRESS anterior no se convierte en COMPLETED global |
| E4 | CLOSED / CAPACITY_LIMIT_CONFIRMED / STOP_BEFORE_TUNING |
| Fase D29 autorizada | CLOSED_WITH_ACCEPTED_LIMITATION; R1-04 PENDING |
| Activación real | PENDING_ACTIVATION_REQUIREMENTS |
| Inbox UX de agosto, garantía futura bounded-wait y caracterización comercial | Planes/alcances separados; no implementados por esta acta |

El usuario autorizó el commit de la selección de 536 archivos el 2026-10-11 («si de acuerdo»). Su registro se identifica en el historial Git de la rama de entrega. Esta autorización se mantiene separada de la aceptación integral, activación y publicación.

## Autoridad y procedencia

1. [Plan canónico B/E/P](../../plan-implementacion-auditoria-agente-whatsapp-2026-09md) y [asignación única R01–R15](../../mapa-interno-b9-2026-09-26.md): conservan requisitos y gates.
2. [Aceptación histórica B9E](../../reporte-aceptacion-b9-profile-beta-1-2026-09-29.md): FAIL histórico; no se reescribe.
3. [PROFILE 02-10](../profile-beta-1-e4-sql-2026-10-02/report.md): PASS de `08310461337a284386299ec47c54125f2139bf7f`, runtime SQL `38c4d458996435d6df56b1b337aeb8987fa1045a`.
4. [Instrumentación 03-10](../e4-instrumentation-2026-10-03/README.md): hooks optativos posteriores, equivalencia funcional, 216 IDs compuestos por versión.
5. [Cierre E4 04-10](../e4-preclaim-scheduling-2026-10-04/report.md): límite confirmado; no transfiere causalidad al TurnWork 86 histórico.
6. [Decisión D29 10-10](../d29-phase-closure-2026-10-10/CIERRE.md): R1-04 pendiente aceptado, cero intentos adicionales; R2-04 conciliado.
7. [Conciliación reproducible](acceptance-reconciliation.json): hashes, cobertura, métricas y límites de esta acta.

Esta acta prevalece como **índice de estado vigente** sobre encabezados de cortes anteriores. Los recibos y sus resultados originales conservan autoridad para su ejecución/versión. No sustituye contratos ni aprobaciones humanas.

## Conciliación por versión

Se verificaron sin ejecutar suites **98/98 archivos** del manifiesto del PROFILE, sus **6/6 entradas congeladas** y los **6/6 hashes de runtime** de la instrumentación. Las 289 fuentes inventariadas del corpus se compararon con el árbol local: las únicas diferencias son `durable.py`, `services.py` y `worker.py`, correspondientes a hooks documentados. No se encontraron deltas inesperados.

El recibo de instrumentación acredita selector AST idéntico y equivalencia funcional al retirar los hooks nombrados, con procesos/locks/rollback OFF/ON. **No acredita igualdad temporal**: no se atribuyen los p95 del candidato `0831046` al HEAD instrumentado `825db75`.

| Evidencia | Resultado aceptado en su alcance | Límite que permanece |
|---|---|---|
| B9D y regresiones históricas | 2.384 IDs únicos en su baseline | No son una ejecución integral del candidato posterior |
| PROFILE 02-10 | 46/46 únicos, 47 referencias canónicas, sin fail/error/skip/xfail | Corpus acotado con proveedores controlados |
| BASE | p95 claim sano 9.819540 s; safety 3.135105 s; outbox 2.697785 s | Sólo cohorte/método/carga del perfil |
| BLOCKED_LLM | p95 claim sano 9.717606 s; safety 3.047379 s | No es bound universal por mensaje |
| META_SLOW | Durabilidad, concurrencia y ausencia de retry ciego aprobadas | No se aplica el mismo SLO BASE a esa variante |
| DUPLICATE / SATURATION | Dedup; safety y concurrencia acotadas aprobadas | Backlog ruidoso no estable; no fairness fuerte |
| Instrumentación posterior | 195 IDs de regresión + 21 diagnósticos = 216 únicos compuestos | No una corrida única ni equivalencia de latencia |
| D29 | 192 regresiones y escenarios acreditados según recibos | No sustituyen full regression B9 ni acreditan R1-04 |

## Matriz consolidada R01–R15

`PROVEN_IN_RECORDED_SCOPE` indica evidencia existente por versión; no una nueva ejecución. `PENDING` conserva una condición no acreditada, sin rebajar el gate.

| ID | Dueño | Disposición vigente y evidencia |
|---|---|---|
| R01 | B9E | Corpus/invariantes compuestos documentados. Aceptación integral actual PENDING; I04/I07 y full regression conservan el límite específico indicado debajo |
| R02 | B9A | PROVEN_IN_RECORDED_SCOPE: harness HTTP→worker→sender, causalidad y etapas; [recibo A](../b9a-acceptance-results.json) |
| R03 | B9B | PROVEN_IN_RECORDED_SCOPE: llamadas/roles/usage, recuperación y presupuesto; [recibo B](../b9b-acceptance-results.json), COST del PROFILE |
| R04 | B9C | PROVEN_IN_RECORDED_SCOPE: un trabajo por org, procesos/sender separados y timeout; [recibo C](../b9c-acceptance-results.json), SCALE del PROFILE |
| R05 | B9B | PROVEN_IN_RECORDED_SCOPE: reserva previa y sin refund indebido; COST/FI-01/02 |
| R06 técnico | B9E | CI crítico existente y artefacto candidato con IDs/hashes. No se afirma ejecución nueva de CI remoto |
| R06 promoción | B9E + release | PENDING: eval real al promover modelo/prompt/semántica/autonomía; responsable/acción y evidencia del candidato real |
| R07 | B9E | PROFILE_BETA_1_PASS adoptado para `0831046`: cinco variantes y topología congeladas. READ ejecuta dos llamadas reales, discrepancia modelada documentada |
| R08 | B9E | CONSOLIDATED: entrega, perfil, aceptación integral y activación separados; FAIL y E4 preservados |
| R09 técnico | B9E | PROVEN_IN_RECORDED_SCOPE: denominadores, colas, p95/máximos, faltantes y gates propios de cada variante |
| R09 ampliación | Release | PENDING si se amplía carga/cohorte: distribución real y perfil pertinente; no extrapolación |
| R10 | B9E | PROVEN_IN_RECORDED_SCOPE: EVAL/COST/SCALE, diez FI, READ y cinco WRITE del corpus de 46. No sustituye todas las regresiones históricas |
| R11 | B9B | PROVEN_IN_RECORDED_SCOPE: FK/counters y legacy desconocido; presupuesto y migraciones de B9B |
| R12 | B9C | PROVEN_IN_RECORDED_SCOPE: constantes/topología, sin billing ni scheduler adicional |
| R13 técnico | B9D | PROVEN_IN_RECORDED_SCOPE: gates por org/capacidad, retiro y rollback; [recibo D](../b9d-acceptance-results.json) |
| R13 operacional | Release | PENDING: aprobación real por alcance/cohorte, cobertura y corte compatible |
| R14 | B9A | Documentación de fronteras/harness conservada; contrato, arquitectura y runbook |
| R15 técnico | B9E | CONSOLIDATED: perfil/candidato, esta acta, conservación y límites por versión |
| R15 operacional | Privacidad/release | PENDING: P-A aprobada y P-B de categorías/plazos comprometidos; fixtures no fabrican esas aprobaciones |

### I01–I14 y lagunas que no se ocultan

La [matriz original](../profile-beta-1-requirements-matrix.md) conserva la descomposición de todas las invariantes y su estado previo/final de septiembre. El corpus posterior acredita sus IDs E2E/GATE/FI de autoridad, tenant, causalidad, takeover, durabilidad y presupuesto. Los negativos I04 (pregunta no muta) e I07 (error/parcial no es vacío) tienen recibos históricos B8D/B2 incluidos en B9D, pero **no todos figuran como rerun exacto en los 46 IDs del candidato ni en una full regression actual**. La conciliación JSON enumera esos IDs históricos y no los presenta como ejecución nueva.

Por ello no se marca R01/aceptación integral actual como PASS. La laguna queda delimitada y no abre automáticamente pruebas, nuevos fixtures, tuning o una matriz adicional. Esta consolidación documental puede terminar con esa disposición explícita; cualquier decisión posterior de aceptación debe referirse a un candidato/alcance exactos y conservar los gates aplicables.

## H16/H19 y requisitos externos

- **H16: PARTIALLY_MITIGATED / EVIDENCE_CONSOLIDATED.** Harness, etapas, corpus y perfil aprobado tienen procedencia verificable. Regresión integral actual, evaluación real de promoción y gates externos no se inventan.
- **H19: MITIGATED_IN_MEASURED_PROFILE / CAPACITY_LIMIT_DOCUMENTED.** Límites, presupuesto y sender progresan en los escenarios ensayados. No se promete estabilidad de la org ruidosa, espera acotada universal ni capacidad comercial E.
- **H17/P-A/P-B, clínica, owners Inbox/veterinario/privacidad, cobertura, simulacro y fallback:** conservan el [readiness PENDING_REAL](../profile-beta-1-operational-readiness.md). No hay grants reales ni despliegue autorizado por esta acta. El manifest vacío no demuestra ausencia de tráfico READ en un entorno que no se inspeccionó.
- E1/E2/E3/E5 y media/DPA bloquean únicamente el alcance que los requiere. El backlog UX de agosto permanece separado.

## Conservación, rama y cierre de este encargo

Se recuperan los **43 archivos** del diagnóstico histórico `68a4a77` como blobs exactos en sus rutas, sin cherry-pick de runtime ni cambio de rama. [Proveniencia](historical-provenance.json). Los tres commits de `task/7acc74fe-PlanWA-02-F0` ya tienen patches equivalentes; no se duplican.

El harness y los cuatro tests nuevos, auditoría fuente, decisiones, actas e índices se preparan explícitamente para versionado. Los recibos brutos se conservan completos en paquetes ZIP fragmentados, con hashes por archivo/parte y restauración verificada; las copias locales originales permanecen intactas. [Procedimiento y alcance](README.md), [manifiesto](preservation-manifest.json), [verificación de recuperación](preservation-verification.json) y [disposición Git](versioning-disposition.json).

El inventario inicial contiene **5.869 archivos / 2.501.325.941 bytes**. De ellos, **5.833 archivos / 2.500.713.153 bytes** se conservan en 17 paquetes de una parte cada uno, **131.804.434 bytes** en total; 414 reportes/índices de esos paquetes también permanecen legibles directamente en Git. Los otros 36 archivos iniciales se versionan directamente. Los 43 recuperados del diagnóstico histórico son adicionales a ese inventario.

El criterio de terminación es finito: acta y estados vigentes coherentes; evidencia recuperable; diferencias de rama resueltas documentalmente; selección de Git revisable que excluye los cambios ajenos del usuario; registro de la entrega en el commit autorizado. No inicia nuevos experimentos ni obliga a completar UX/activación para terminar este encargo.


## Ejecución posterior en WSL2 — 1947726 — 11-10-2026

La nueva campaña autorizada para WSL2 terminó **PENDING / PREFLIGHT_BLOCKED**. La instalación congelada del frontend pasó en Linux. El bootstrap evaluativo omitió cargar SECRET_KEY antes del import de Django y falló antes del sellado y de todo test. La corrección separada se validó sin reiniciar. Cero bloques formales y cero PROFILE; recursos propios retirados y evidencia Windows preservada. No se atribuye un fallo al producto. Se mantienen R1-04 PENDING aceptado, PENDING_ACTIVATION_REQUIREMENTS y alcances E/P/UX separados. [Reporte y evidencia](../b9-integral-acceptance-1947726-wsl-20261011/REPORT.md).


## Campaña WSL2 r2 — 1947726 — 11-10-2026

La nueva campaña autorizada con «procede» terminó **PENDING / INTERRUPTED_CLOCK_DISCONTINUITY**. Preflight PASS, bootstrap corregido validado y 3.332 fuentes exactas. Se inició una única ejecución del corpus de 87 IDs; el monitor detectó una discrepancia civil−monotónico de +1,724 s durante las migraciones de su base de tests y detuvo el grupo propio. Cero IDs completados; regresiones, checks, frontend, seguridad, auditorías y cinco PROFILE NOT_EXECUTED. Fuentes y 70 archivos del sello intactos. Las dos bases, PostgreSQL y la carpeta propia se retiraron; ambas campañas anteriores se conservaron. No se atribuye un fallo al producto ni se cambió W32Time. R1-04 PENDING aceptado, activación PENDING_ACTIVATION_REQUIREMENTS y E/P/UX separados. [Reporte y evidencia](../b9-integral-acceptance-1947726-wsl-20261011-r2/REPORT.md). Sin reintentos, commits ni push.


## Campaña WSL2 r3 — 1947726 — 11-10-2026

La campaña nueva autorizada con «procede» termina **PENDING / ENVIRONMENT_SUBPROCESS_DEPENDENCY_VISIBILITY**. La pausa temporal de systemd-timesyncd en WSL permitió dos observaciones previas estables y siete bloques sin incidentes de reloj o recursos; el límite de 1 s permaneció original. Corpus dirigido **87/87 PASS**, B0 **17/17 PASS** y checks Django/drift/migraciones/schema Billing PASS. B3 terminó con **39 PASS y tres FAIL brutos de arranque**: sus hijos seleccionan el Python base privado, que no puede importar Django instalado en el venv, y no llegaron a B3_READY. La incompatibilidad impide evaluar esos tres contratos; no se atribuye una violación al producto ni se convierten los fallos en PASS. El stderr original de los hijos no fue retenido por el test; el diagnóstico posterior de import es evidencia separada. B4/B5/full, checks frontend, seguridad, auditorías y cinco PROFILE NOT_EXECUTED. Hay 146 observaciones de IDs únicos: 143 PASS y tres fallos de arranque; las negativas I04/I07 sí pasaron. Las 3.332 fuentes y los 91 archivos del sello permanecieron intactos. PostgreSQL, las bases restantes y la carpeta propia se retiraron; systemd-timesyncd volvió a active/running/enabled. W32Time, 319 archivos de las tres campañas previas y los tres cambios ajenos del checkout se conservaron. R1-04 sigue PENDING aceptado, activación PENDING_ACTIVATION_REQUIREMENTS y E/P/UX separados. [Reporte y evidencia](../b9-integral-acceptance-1947726-wsl-20261011-r3/REPORT.md). Sin fixes del candidato, reintentos, commits, push, despliegue ni activación.


## 2026-10-11 — B9E 1947726: campaña WSL2 r4

Decisión integral **PENDING**. Autorización «hazlo» para preparar el Python base y el venv privados con el mismo lock, validar ambos antes del sello y ejecutar una campaña nueva con los mismos gates. La validación de Django, módulos y paridad de dependencias pasó en ambos intérpretes; 13.508 archivos de dependencias y las 3.332 fuentes exactas quedaron comprobados. No se cambiaron producto, tests, fixtures, cargas ni umbrales.

El preflight pasó con 5,70 GiB libres en Windows. En el control inmediato anterior al corpus dirigido bajaron a 3,60 GiB, por debajo de los 5 GiB exigidos. La parada original se conserva: **cero tests, checks de aplicación o PROFILE ejecutados**. No se atribuye fallo al producto ni se trasladan los resultados de r3 a r4. No hubo reintentos.

Cleanup PASS: se retiró únicamente la base control, PostgreSQL y el workspace privado r4. La sincronización de WSL se restauró active/running/enabled; W32Time intacto. Las cuatro campañas anteriores y los cambios ajenos se conservaron. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. Expediente independiente: [reporte r4](../b9-integral-acceptance-1947726-wsl-20261011-r4/REPORT.md) y [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r4/candidate-decision.json). Otra campaña requiere una decisión nueva y recursos suficientes; no se autoriza commit, push, despliegue ni activación.


## 2026-10-11 — B9E 1947726: campaña WSL2 r5 con recursos actuales

Decisión integral **PENDING por entorno/recursos**. El usuario autorizó «procede con lo disponible actual, no puedo liberar mas aun». Se modificó explícitamente el mínimo de admisión de 5 GiB, conservando la reserva de ejecución de 2 GiB, disco/reloj/integridad y todos los contratos de producto. No se cambió el candidato, los tests, fixtures, cargas, tiempos ni aserciones. Ambos Python privados pasaron la validación con las dependencias congeladas.

El preflight pasó y el bloque dirigido inició con 4,09 GiB disponibles en Windows. Durante sus migraciones privadas el host bajó a **1,61 GiB**, agotando la reserva retenida. El controlador interrumpió solo su grupo de procesos mediante SIGTERM. Hubo una invocación formal del bloque, **cero IDs completados**, sin recibo final ni PROFILE. La migración parcial no se convierte en PASS o fallo del producto. STOP original y muestras conservados, sin reintentos. La excepción del mínimo de 5 GiB queda explícita; no se afirma que se cumplió ese prerrequisito histórico.

Cleanup PASS: retiradas las bases control/dirigida, PostgreSQL y solo el workspace r5. Sincronización WSL restaurada active/running/enabled, W32Time intacto. Las cinco campañas anteriores y los cambios ajenos se conservaron. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. [Reporte r5](../b9-integral-acceptance-1947726-wsl-20261011-r5/REPORT.md) y [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r5/candidate-decision.json). No se crearon commits ni se hizo push, despliegue o activación.


## 2026-10-11 — B9E 1947726: campaña WSL2 r6, reanudación

Decisión integral **PENDING por entorno/reloj**. Autorización «reanuda», conservando la excepción de admisión de memoria aprobada y la reserva de 2 GiB. Mismo SHA, selección, fixtures, cargas, tiempos y contratos. Se validaron ambos Python privados con el mismo lock. La sonda Windows pasó a un proceso persistente con la misma API, antes del sello.

El corpus dirigido terminó **87/87 PASS**, cero fallos/errores/skips/xfail. Django check y drift de migraciones también PASS. Durante la migración posterior de checks, el monitor detectó **121,912111 s** de discontinuidad civil−monotónica y detuvo su grupo de procesos. Los eventos de Windows confirman suspensión a las 03:59:21 UTC y reactivación a las 04:01:24 UTC del 12-10, todavía 11-10 en México. No se agotaron las reservas de memoria o disco. La migración parcial no se acredita como PASS ni como fallo del producto. Schema Billing, B0/B3/B4/B5/full, frontend, seguridad y las cinco variantes PROFILE quedaron NOT_EXECUTED. No hubo reintentos.

Fuentes, dependencias y sello íntegros. Cleanup PASS: retiradas las tres bases propias, PostgreSQL, workspace r6 y sonda propia de Windows. Sincronización WSL restaurada active/running/enabled, W32Time intacto. Las seis campañas anteriores y los cambios ajenos se conservaron. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. [Reporte r6](../b9-integral-acceptance-1947726-wsl-20261011-r6/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r6/candidate-decision.json) y [eventos del host](../b9-integral-acceptance-1947726-wsl-20261011-r6/windows-clock-power-events.json). No se crearon commits ni se hizo push, despliegue o activación.


## 2026-10-11 — B9E 1947726: campaña WSL2 r7, continuación

Decisión integral **PENDING por entorno/reloj**. Autorización «continua, estara despierto», conservando la admisión modificada y reserva de 2 GiB. Mismo candidato y contratos. Ambos intérpretes privados validados con el mismo lock; 101 archivos de evaluador/herramientas sellados y 13.508 archivos de dependencias comprobados.

Corpus dirigido **87/87 PASS**, cero fallos/errores/skips/xfail; Django check y drift PASS. Durante la migración de checks, nueva discontinuidad civil−monotónica de **391,458861 s**, con parada del grupo propio y exit -15. Windows registra suspensión a las 04:51:58 UTC y un ajuste civil al reactivarse a las 04:58:29 UTC del 12-10, todavía 11-10 en México. No se registró agotamiento de las reservas de memoria/disco. Migración parcial PENDING; schema Billing, B0/B3/B4/B5/full, frontend, seguridad y cinco PROFILE NOT_EXECUTED. Sin reintentos.

La inspección posterior muestra suspensión automática configurada tras 15 minutos con corriente y 10 con batería; no demuestra por sí sola el iniciador exacto del evento. Se preparó después del STOP una solicitud temporal propia de actividad mediante SetThreadExecutionState, comprobando adquisición y restauración durante 2 s, sin cambios de política global. No se usó en las pruebas r7 ni acredita prevención de suspensión durante una campaña completa.

Cleanup PASS: tres bases propias, PostgreSQL, workspace y sonda Windows retirados. Sincronización WSL restaurada active/running/enabled; W32Time intacto. Conservados 1.163 archivos de las siete campañas anteriores y cambios ajenos. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. [Reporte r7](../b9-integral-acceptance-1947726-wsl-20261011-r7/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r7/candidate-decision.json), [diagnóstico](../b9-integral-acceptance-1947726-wsl-20261011-r7/incident-classification.json) y [preparación de remediación](../b9-integral-acceptance-1947726-wsl-20261011-r7/environment-remediation.json). Sin commits, push, despliegue ni activación.


## 2026-10-11 — B9E 1947726: campaña WSL2 r8, solicitud temporal de actividad

Decisión integral **PENDING por entorno/disco**. Autorización «prosigue», conservando la admisión modificada y reserva de 2 GiB, disco de 1 GiB y reloj de 1 s. Mismo candidato y contratos. La nueva lectura de los mensajes completos Kernel-Power 42 confirma System Idle en r6/r7; sus reportes históricos se conservan intactos.

Se adquirió y monitoreó antes del sello una solicitud temporal propia SetThreadExecutionState. Ambos intérpretes privados pasaron con el mismo lock; 106 archivos de evaluador/configuración/herramientas y 13.508 de dependencias verificados; 3.332 fuentes exactas. La campaña formal del 12-10, 05:40:07–05:46:23 UTC, todavía 11-10 en México, se detuvo en el corpus dirigido: /mnt/c registró **908.460.032 bytes (0,85 GiB)** libres, por debajo de 1 GiB. No hubo discontinuidad de reloj ni agotamiento de reserva de memoria en el monitor formal. El espacio volvió a unos 3,8 GiB después del incidente; no se establece la causa de esa caída temporal ni se invalida la parada.

El journal conserva **53/87 IDs con estado ok** (39 B2 y dos negativas de asistencia incluidos), sin recibo final del runner: evidencia parcial, **no PASS del bloque**. El journal no contiene timestamps por ID para demostrar que todas las terminaciones precedieron al incidente. Checks backend, B0/B3/B4/B5/full, frontend, seguridad y cinco PROFILE NOT_EXECUTED. Cero reintentos formales y sin cambios productivos.

Cleanup PASS: dos bases propias, PostgreSQL, puerto y workspace retirados. Observador cerrado, solicitud temporal liberada con estado original restaurado, sincronización WSL active/running/enabled y W32Time intacto. Conservados 1.409 archivos de ocho campañas anteriores y cambios ajenos. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX y aprobaciones operativas/privacidad separados. [Reporte r8](../b9-integral-acceptance-1947726-wsl-20261011-r8/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r8/candidate-decision.json) e [incidente](../b9-integral-acceptance-1947726-wsl-20261011-r8/incident-classification.json). Sin commits, push, despliegue ni activación. Otra campaña requiere decisión nueva y margen estable de disco conservando los guards.


## 2026-10-13 — B9E 1947726: campaña WSL2 r9 cerrada

Decisión integral **PENDING por entorno y recibos finales incompletos**. Preparación reanudada por «prosige» el 12-10, mismo candidato y contratos, reserva de memoria autorizada de 2 GiB, disco de 1 GiB y reloj de 1 s. Corpus dirigido **87/87**, B0 **17/17**, B3 **42/42**, B4 **68/68**, B5 **37/37**, Django check/drift/migrate y Billing schema: nueve gates **PASS** con integridad válida. La suite full de 3.331 IDs fue interrumpida por disco: monitor 708.132.864 bytes (0,66 GiB), recibo posterior 267.816.960 bytes (255 MiB), exit -9. Retuvo **2.666 PASS, 10 FAIL, 1 ERROR, 2 SKIP**; 652 IDs sin resultado. Causas de fallos parciales sin clasificar y sin trazas finales; no se atribuyen automáticamente al entorno ni al producto. Frontend, seguridad y cinco PROFILE **NOT_EXECUTED**. Cero reintentos formales.

Al retomar se observaron un reinicio inesperado del host, tres JSON finales con bytes NUL y ausencia de recibos de cierre normal de los monitores/guardián. Se conservan originales exactos. Nueva comprobación posterior: 3.332 fuentes, 13.508 dependencias y 108 archivos sellados sin diferencias; no revalida la suite incompleta. Cleanup recuperado PASS: SQL de propiedad guardado tras recuperar PostgreSQL privado, bases/servicio/puerto/workspace retirados. Sincronización WSL actual active/running/enabled y PIDs originales ausentes, sin afirmar cierre graceful anterior. W32Time y políticas globales intactos. 1.623 archivos de nueve campañas anteriores y cambios ajenos preservados.

Matriz R/I con PASS limitado al corpus dirigido donde corresponde; aceptación integral PENDING. Activación **PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. [Reporte r9](../b9-integral-acceptance-1947726-wsl-20261012-r9/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261012-r9/candidate-decision.json) y [conservación](../b9-integral-acceptance-1947726-wsl-20261012-r9/README.md). Sin commits, push, despliegue ni activación. No hay campaña nueva automática.


## B9 corregido 196aceb — 2026-10-14 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada 155 PASS y un skip histórico, 11 IDs previos PASS. Campaña formal de alcance fijo, sin reruns: **PENDING**. El monitor detuvo full el 2026-10-14 a las 07:10:53 UTC porque Windows disponía de 1,42 GiB de RAM, por debajo de la reserva autorizada de 2 GiB. Hay 353 PASS parciales, cero FAIL/ERROR registrados y 2.978 IDs sin recibo; no existe recibo completo de full. Los nueve bloques anteriores aprobaron. Frontend, seguridad, auditorías advisory y las cinco variantes PROFILE permanecen NOT_EXECUTED. La incidencia invalida la aceptación integral sin demostrar un fallo del producto. Cleanup y restauraciones PASS; 2073 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261013/REPORT.md), [matriz](../b9-correction-20261013/candidate-decision.json).


## B9 corregido r2 196aceb — 2026-10-14 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada de la campaña anterior: 155 PASS y un skip histórico; no repetida aquí, 11 IDs previos PASS. Campaña formal de alcance fijo, sin reruns: **PENDING**. El monitor detuvo B4 al registrar 1,52 GiB de RAM libre en Windows, por debajo de la reserva autorizada de 2 GiB, el 2026-10-15 a las 00:00:44 UTC (14 de octubre, 18:00:44 de Ciudad de Mexico). Los siete bloques terminados aprobaron; B4 conserva 28 PASS parciales de 68 IDs, cero FAIL/ERROR registrados y 40 IDs sin recibo. B5, full, frontend, seguridad, auditorias advisory y cinco variantes PROFILE quedaron NOT_EXECUTED. No se atribuye un fallo al producto ni se declara OOM a partir del exit code de la terminacion controlada. Cleanup y restauraciones PASS; 2446 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261014-r2/REPORT.md), [matriz](../b9-correction-20261014-r2/candidate-decision.json).


## B9 corregido r3 196aceb — 2026-10-14 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada anterior, sin repetición actual: 155 PASS y un skip histórico, 11 IDs previos PASS. Campaña formal de alcance fijo, sin reruns: **PENDING**. La suite completa no pudo evaluar validamente los workers B8B: el ensamblaje asigno test_b9i_full, pero sus guards exigen test_b8b_. Siete procesos salieron antes de READY; un octavo fallo se registro durante la parada propia. Se conservan 2.707 PASS, dos skips historicos y ocho FAIL brutos; 614 IDs quedaron sin recibo en full. Los nueve bloques previos aprobaron y los 11 casos corregidos pasaron dentro de full. No se demuestra un fallo del producto. Frontend, seguridad, auditorias advisory y las cinco variantes PROFILE permanecen NOT_EXECUTED. B8C/B8D/B8E tambien requieren prefijos distintos, por lo que la remediacion minima de ensamblaje es una particion secuencial, exhaustiva y sin duplicados del mismo inventario de 3.331 IDs, sellada antes de una nueva ejecucion. Cleanup y restauraciones PASS; 2741 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261014-r3/REPORT.md), [matriz](../b9-correction-20261014-r3/candidate-decision.json).


## B9 corregido r4 196aceb — 2026-10-14 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada anterior, sin repetición actual: 155 PASS, 0 fallos, 0 errores y 1 skips identificados, de 156 IDs. Campaña formal de alcance fijo, sin reruns: **PENDING**. El ajuste del ensamblaje quedó implementado y validado antes del sello: los mismos 3331 IDs, cinco grupos compatibles, sin omisiones ni duplicados. La nueva campaña se detuvo en directed por RAM disponible en Windows (1.826 GiB en el monitor, reserva fija de 2 GiB). El disco conservó al menos 5.859 GiB en ese monitor y WSL mantuvo su reserva. No se completó ningún ID dirigido con recibo. Los grupos full, los demás checks y PROFILE permanecen NOT_EXECUTED. La terminación SIGTERM fue la parada propia del guard; no demuestra OOM ni un fallo del producto. No hubo reintento formal ni transferencia de resultados históricos. Full lógico: NOT_EXECUTED; los grupos se cuentan una vez en los totales de ejecución. Cleanup y restauraciones PASS; 3068 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261014-r4/REPORT.md), [matriz](../b9-correction-20261014-r4/candidate-decision.json).


## B9 Windows nativo r1 196aceb — 2026-10-15 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada anterior, sin repetición actual: 155 PASS, 0 fallos, 0 errores y 1 skips identificados, de 156 IDs. Campaña formal de alcance fijo, sin reruns: **PENDING**. Disco C: por debajo de la reserva fija de 1 GiB después de preparar Windows nativo; no se iniciaron pruebas de aplicación. Full lógico: NOT_EXECUTED; los grupos se cuentan una vez en los totales de ejecución. Cleanup y cierre nativo PASS; 3290 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261015-native-r1/REPORT.md), [matriz](../b9-correction-20261015-native-r1/candidate-decision.json).


## B9 Windows nativo r2 196aceb — 2026-10-16 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada anterior, sin repetición actual: 155 PASS, 0 fallos, 0 errores y 1 skips identificados, de 156 IDs. Campaña formal de alcance fijo, sin reruns: **PENDING**. La reserva de disco C: cayo por debajo de 1 GiB durante B5. El controlador detuvo su arbol propio; B5 conserva 34/37 PASS parciales sin FAIL/ERROR registrados, ocho gates previos PASS y el resto NOT_EXECUTED. La aceptacion integral sigue pendiente por interrupcion ambiental; no se acredita un fallo de producto ni OOM. Full lógico: NOT_EXECUTED; los grupos se cuentan una vez en los totales de ejecución. Cleanup y cierre nativo PASS; 3469 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261016-native-r2/REPORT.md), [matriz](../b9-correction-20261016-native-r2/candidate-decision.json).


## B9 Windows nativo r3 196aceb — 2026-10-16 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada anterior, sin repetición actual: 155 PASS, 0 fallos, 0 errores y 1 skips identificados, de 156 IDs. Campaña formal de alcance fijo, sin reruns: **PENDING**. La RAM disponible cayó por debajo de la reserva de 2 GiB al iniciar full-b8d; el controlador detuvo su árbol propio antes de registrar resultados por ID de ese grupo. Los once bloques anteriores están PASS, incluidos B5 completo y los grupos full-b8b y full-b8c (62 IDs). La suite integral y los bloques posteriores siguen pendientes por interrupción ambiental; no se acredita fallo de producto ni OOM. Full lógico: INCOMPLETE; los grupos se cuentan una vez en los totales de ejecución. Cleanup y cierre nativo PASS; 3760 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261016-native-r3/REPORT.md), [matriz](../b9-correction-20261016-native-r3/candidate-decision.json).


## B9 Windows nativo r4 196aceb — 2026-10-17 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Verificación enfocada anterior, sin repetición actual: 155 PASS, 0 fallos, 0 errores y 1 skips identificados, de 156 IDs. Campaña formal de alcance fijo, sin reruns: **PENDING**. La reserva de disco C: cayó por debajo de 1 GiB durante la preparación de B0. El controlador detuvo únicamente su árbol propio antes de registrar resultados por ID de ese bloque. Cinco gates previos están PASS y el corpus dirigido conserva 87/87 PASS. Las regresiones restantes, full, frontend, seguridad y PROFILE quedan sin ejecutar; no se acredita fallo funcional del producto. Windows registró suspensión por Battery y un intervalo posterior de casi ocho horas en el seguimiento; no se atribuye ese intervalo a ejecución continuada de B0 ni se identifica el consumidor de disco. Full lógico: NOT_EXECUTED; los grupos se cuentan una vez en los totales de ejecución. Cleanup y cierre nativo PASS; 4083 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261016-native-r4/REPORT.md), [matriz](../b9-correction-20261016-native-r4/candidate-decision.json).


## B9 Windows compuesto r5 196aceb — 2026-10-17 — aceptación PENDING

Base 1947726 y árbol 196aceb4f5f234c086b96d8e8af93787613f3c25, dos tests corregidos; runtime/locks/gates/cargas intactos. Aceptación compuesta autorizada por bloques, sin afirmar corrida continua: **PENDING**. 11 bloques PASS referenciados con origen/hash, 56 observaciones backend nuevas completas y 313 referenciadas; no se copian recibos como ejecución nueva. Verificación enfocada separada: 155 PASS, 0 fallos, 0 errores y 1 skips identificados, de 156 IDs. Se conservan 13 gates completos PASS: 11 referenciados y full-b8d/full-b8e nuevos (27/27 y 29/29). Full-general queda incompleto: 2639/3213 IDs, 2636 PASS, 2 SKIP y 1 ERROR por fixture dependiente de la hora en test_upcoming_window, anterior a la interrupción. La parada formal corresponde a heartbeat de vigilia inválido tras una brecha de unas 3 horas; los eventos System documentan suspensión/reanudación. No se establece fallo del producto ni escasez de RAM/disco como causa. La corrección propuesta del fixture no se aplicó al candidato sellado; los bloques pendientes necesitan ejecución válida. [Diagnóstico conjunto](diagnostics/fixture-and-awake-observation.json). Full lógico compuesto: INCOMPLETE; los grupos se cuentan una vez y el agregado no añade ejecuciones. Cleanup y cierre nativo PASS; 4359 archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261017-native-r5/REPORT.md), [matriz](../b9-correction-20261017-native-r5/candidate-decision.json).


## B9 Windows compuesto r12 f5f18d7 — 2026-10-20 — FAIL

Candidato f5f18d71847a46d66644775cd90d30268f072e3b, base 194772677ca4e9fe1a1dec7f4dafa48396a6c583. Decisión FAIL; El gate bloqueante Gitleaks del historial devolvió exit 1 con 3156 detecciones generic-api-key; no se declaran 3156 credenciales reales confirmadas. Se conservan los PASS y los cinco perfiles quedan NOT_EXECUTED por la parada exigida. Backend completo r9 conservado: 3331 IDs, 3319 PASS y 12 SKIP; build frontend r9 PASS. Frontend: 355 PASS conservados (354 r9 y uno r11), cero casos frontend nuevos; smoke PASS y lint ADVISORY_NONZERO referenciados, sin repetir PASS. Timeout original r9 de 5000 ms y exit 1 permanecen PENDING_TIMEOUT; los tres FAIL backend históricos y sus exits se conservan. La aceptación mantiene la limitación histórica de disco/reloj r6; no es campaña continua y los ensambladores no ejecutan tests. El intento r10 permanece PENDING por selector: cero casos, 26 metadatos filtrados, comando exit 0, ensamblador exit 1 y controlador exit 2; r11 repara solo el selector sobre el mismo f5 antes del primer intento real. La seguridad r11 permanece PENDING antes del scanner: scans=[] y comando/controlador exit 2 por referencias internas de captura Codex, sin cambiar HEAD/f5 ni atribuir hallazgos al producto. R12 refresca solo la historia y exige la seguridad y etapas originales restantes. Las ocho aserciones y timeout originales están intactos. Los 14 gates y cinco perfiles deben aprobar. Cleanup y auxiliares actuales PASS; historia y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 y E/P/UX/operación separados. Sin commits, push, despliegue ni activación. [Reporte](../b9-correction-20261020-native-r12/REPORT.md), [matriz](../b9-correction-20261020-native-r12/candidate-decision.json).
