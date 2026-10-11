# B9 — Acta consolidada de entrega técnica y evidencia

Fecha: **2026-10-11**. Encargo: consolidar B9 y resolver el versionado/conservación de la evidencia existente. Rama única de entrega: `codex/e4-capacity-scheduling`. HEAD de entrada: `825db75df68bf076929fa787e77beefe96803350`.

## Decisión y estados independientes

**El expediente técnico B9 queda consolidado.** Se incorpora el PROFILE aprobado del 2 de octubre y la procedencia de B9A–D, E4, instrumentación y D29. Esta acta completa la consolidación documental; no ejecuta una nueva aceptación, no borra FAIL históricos y no convierte el conjunto en beta activada.

| Objeto de decisión | Estado vigente |
|---|---|
| Entregas técnicas B9A/B/C/D | COMPLETED técnico, con sus recibos y límites originales |
| Entrega documental/evidencia B9E | CONSOLIDATED, alcance y pendientes explícitos en esta acta |
| PROFILE del 2026-10-02, candidato `0831046` | PROFILE_BETA_1_PASS; 46/46 IDs únicos y cinco variantes |
| Aceptación integral de B9 para el HEAD actual | PENDING_INTEGRAL_ACCEPTANCE; no inferida de históricos compuestos |
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
