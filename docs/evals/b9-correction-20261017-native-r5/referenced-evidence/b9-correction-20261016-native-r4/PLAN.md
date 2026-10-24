# B9E — campaña WSL2 r9 del 12-10-2026

Nueva instrucción: «prosige», después de recuperar espacio real en C:. Se reanuda la preparación aún sin sellar; el reporte previo de falta de espacio se conserva en preparation-history/REPORT-before-resumption.md. Se preservan las nueve campañas anteriores. Antes del sello se adquiere una solicitud propia SetThreadExecutionState (ES_CONTINUOUS | ES_SYSTEM_REQUIRED), limitada a seis horas, con heartbeat de un segundo, comprobación antes de cada bloque y cada cinco segundos, antigüedad máxima de diez segundos y liberación explícita al cierre. No cambia política global, pantalla ni W32Time. No garantiza impedir suspensión manual, tapa, botón o políticas que prevalezcan. Todos los guards de reloj, recursos e integridad se conservan. No se cambian producto, tests, fixtures, tasas, tiempos, aserciones o gates; los resultados previos no se transfieren.

Autorización: «procede con lo disponible actual, no puedo liberar mas aun». Esta decisión modifica explícitamente el mínimo de admisión de 5 GiB: se permite iniciar con la memoria disponible si Windows y WSL conservan al menos la reserva original de 2 GiB. Se mantiene esa reserva durante la ejecución, disco real mínimo de 1 GiB, monitor horario original y parada ante OOM, corrupción o deriva. No se afirma que estén reservados los 3 GiB estimados para una suite ni que se cumplió el prerrequisito histórico de 5 GiB. Los resultados corresponden a esta condición de recursos modificada por el usuario.

Se conserva el mismo SHA, selección, producto, tests, fixtures, tasas, concurrencia interna, tiempos y gates de contrato. Se preparan y validan ambos intérpretes privados con el mismo lock antes del sello. La pausa temporal de sincronización de WSL previamente autorizada se comprueba durante 120 s y se restaura al cierre, con guardián de seis horas. Windows W32Time no cambia. Las nueve campañas anteriores se conservan. Una corrida formal por bloque y variante, sin reintentos automáticos.

## Objetivo y alcance acordado

Determinar la aceptación técnica integral del candidato **`194772677ca4e9fe1a1dec7f4dafa48396a6c583`**, conservando los requisitos originales. Es un plan de verificación y cierre; no incorpora funcionalidades nuevas.

El usuario expresó acuerdo con la propuesta de aceptación B9E acotada, incluidas sus cinco variantes PROFILE, y solicitó este plan. Ese acuerdo cubre la verificación descrita; mantiene las restricciones ajenas a ella. La preparación original del plan sólo documentó la selección. El encargo posterior «ejecuta el plan» autorizó la campaña del 11 de octubre, cuya parada de preflight queda registrada en el reporte enlazado; no se ejecutaron tests ni PROFILE.

La entrega de evidencia permanece en `codex/e4-capacity-scheduling`. El candidato evaluado sigue siendo el SHA anterior aunque posteriormente se registren documentos/resultados en nuevos commits. [Acta vigente](../b9-consolidation-2026-10-11/ACTA.md), [plan canónico §B9](../../plan-implementacion-auditoria-agente-whatsapp-2026-09md) y [matriz de requisitos histórica](../profile-beta-1-requirements-matrix.md).

**Fuera del alcance:** R1-04 y cualquier nueva ejecución de escenarios físicos D29, tuning, barridos de carga, capacidad comercial E, cambios de planner/runtime/contratos/umbrales, activación, despliegue y push. R1-04 conserva PENDING con limitación aceptada. Los tres cambios previos ajenos del checkout se conservan intactos.

## 0. Congelar y comprobar antes de ejecutar

- Evaluar una copia aislada del árbol Git exacto, sin incorporar cambios locales ajenos, mover la rama compartida ni crear otra línea de desarrollo. La copia debe permitir identificar el commit y verificar sus fuentes.
- Sellar código productivo, tests, scripts evaluativos, locks, versiones, configuración efectiva y gates mediante hashes. Comparar antes/después de cada bloque; las fuentes productivas no se modifican durante la aceptación.
- Resolver por discovery los IDs del [manifiesto de alcance](scope-manifest.json), sin ejecutar tests, y congelar también la selección completa de regresión del candidato. Su total actual se descubre; no se heredan los 2.384 IDs históricos como si fueran una ejecución actual.
- Usar las dependencias bloqueadas del candidato. Referencias de reproducción: Python 3.13, PostgreSQL 16.15; Node 20 y pnpm 9 para los checks frontend del workflow. Registrar las versiones realmente usadas; cualquier incompatibilidad se resuelve antes de emitir carga, sin actualizar locks/producto para conseguir verde.
- PostgreSQL local privado, base nueva por bloque/variante, durabilidad habilitada y proveedores controlados. Registrar nombres, puertos y propiedad de los recursos. No usar credenciales, clínicas ni bases productivas.
- Revisar memoria, disco y ausencia de procesos evaluativos propios residuales; registrar un presupuesto para una sola suite/variante. No iniciar sin margen suficiente ni terminar procesos ajenos para obtenerlo. No cambiar W32Time ni la configuración del reloj del host.

Sólo se permite preparar el ensamblaje evaluativo imprescindible: rutas, registro del nuevo SHA, discovery y captura de recibos. Si el runner histórico está ligado al SHA anterior, conservar sus fuentes originales y documentar un adaptador separado con diff/hash antes de la primera ejecución. No desactivar un guard, rebajar un verificador, introducir fixtures de aplicación nuevos ni cambiar tiempos/cargas. Si la adaptación exige algo de eso, detener y registrar el bloqueo.

**Regla ante incompatibilidades:** un problema del entorno o del harness que impida evaluar válidamente el contrato deja el bloque y la aceptación integral en PENDING. Registrar la causa y la evidencia; un error de preparación, un exit code o un recibo inválido no se clasifican automáticamente como fallo del producto. Si el escenario se ejecuta válidamente y viola un requisito aplicable, corresponde FAIL. Esta regla se aplica durante los bloques existentes, sin añadir una fase de auditoría.

**Salida:** preflight íntegro, fuentes selladas, selección por ID, presupuesto de recursos y ausencia de bloqueos. Si falta alguno, no comenzar el bloque 1.

## 1. Corpus dirigido y negativas pendientes

El manifiesto enumera **87 IDs únicos existentes**: 46 del corpus B9E —47 referencias canónicas, con una referencia duplicada— y 41 adicionales de la conciliación histórica. La selección adicional corresponde a 39 pruebas B2 de resultados/transporte/efectos y dos negativas B8D de asistencia. Este conteo es de selección, todavía no de ejecución.

- **I04:** pregunta directa/indirecta no confirma asistencia; una consulta no produce mutaciones incluso ante selección equivocada de herramienta.
- **I07:** error HTTP/transporte, JSON inválido, incompletitud y efecto parcial permanecen distintos de vacío/ausencia y de éxito total.
- Conservar el resto del corpus: READ pública/personal, cinco WRITE, causalidad, autorización, tenant, takeover, presupuesto, concurrencia, release y diez FI.
- Utilizar los fixtures ya existentes y bases privadas. Cada negativa debe conservar sus aserciones de ausencia de efecto/llamada prohibida y la distinción de resultado; un HTTP 200 no las sustituye.

**Gate:** todos los IDs previstos resueltos y PASS; cero fallos, errores, omisiones, skips o xfail en la selección requerida. Registrar recibo por ID y versión de fuentes. Un ID ausente no se elimina de la selección para aprobarla.

## 2. Regresiones y checks del candidato

La autoridad de la selección es [CI del candidato](../../../.github/workflows/ci.yml), cuyo hash queda en el manifiesto. Ejecutar los bloques secuencialmente para controlar recursos; conservar la concurrencia interna que comprueban los tests de procesos.

| Bloque | Evidencia requerida |
|---|---|
| Backend | Checks Django/migraciones, migración en base privada, auditoría de schema Billing, runners críticos B0/B3/B4/B5 y suite completa descubierta en el candidato |
| Frontend | Build, tests y smoke de URLs con las dependencias bloqueadas |
| Seguridad | Gitleaks bloqueante con la configuración del candidato y alcance de historial exigido por CI; salidas redactadas |
| Advertencias | Lint y auditorías de dependencias conservan su carácter advisory del workflow; se registran sin convertirlas artificialmente en gates nuevos |

La suite general backend se ejecuta sin paralelizar suites en el host. Esa diferencia de orquestación local se declara; no equivale a afirmar que corrió CI remoto. Los solapes exigidos entre corpus/runners/suite se registran y deduplican al contar pruebas. Los gates críticos requeridos no admiten skips; cualquier otro skip debe quedar identificado con su aplicabilidad, sin cubrir con él un requisito pendiente.

**Gate:** todos los checks bloqueantes y regresiones requeridas satisfactorios, con IDs, exit codes y fuentes del mismo candidato; cero violación crítica. No excluir pruebas para ocultar un fallo. No iniciar el PROFILE con estos gates incompletos.

## 3. PROFILE del candidato: cinco variantes, una por una

Conservar [perfil v1](../profile-beta-1-v1.json) y [metodología](../profile-beta-1-methodology.md): tres organizaciones, dos planners, un sender, batch 1/poll máximo 1 s, calentamiento 30 s, medición 300 s y drain 20 s. Organizaciones sanas a un inbound/10 s cada una; ruidosa a uno/s. Mantener W1, recencia, fixtures, proveedores, costes y cadencias originales. Registrar las dos llamadas LLM reales de READ sin reemplazarlas por la hipótesis modelada de una llamada.

| Orden | Variante | Gate original |
|---:|---|---|
| 1 | BASE | p95 inbound sano persistido→claim ≤10 s; guidance→dispatch ≤5 s; outbox→dispatch ≤5 s |
| 2 | BLOCKED_LLM | p95 claim sano ≤10 s y safety dispatch ≤5 s; bloqueo original de 10 s |
| 3 | META_SLOW | Estado durable, concurrencia acotada y ausencia de retry ciego; sin imponer el SLO BASE a esta variante |
| 4 | DUPLICATE | Deduplicación de webhook y ausencia de efectos duplicados según sus aserciones originales |
| 5 | SATURATION | `safety_admitted_under_saturation`, `bounded_concurrency` y `saturation_observed`, todos verdaderos según las aserciones originales |

**Límite inequívoco de SATURATION:** se conserva exclusivamente el escenario, las condiciones y el gate ya aprobados en el perfil/metodología y registrados en el [recibo histórico de la variante](../profile-beta-1-e4-sql-2026-10-02/saturation.json). Antes de ejecutarlo debe acreditarse que el runner/adaptador mantiene esa compatibilidad. Se fijan:

- Tres organizaciones —dos sanas y una ruidosa—, dos planners, un sender, batch 1, poll máximo 1 s y N=1 por organización. Cada sana recibe un inbound/10 s, todos de guidance detectable en recepción; la ruidosa conserva un inbound/s en conversaciones distintas. Se mantienen fixtures, recencia, debounce real de 8 s, causalidad, proveedores controlados y límites originales.
- Calentamiento de 30 s, medición de 300 s y observación/drain de 20 s sin nuevos ingresos ni muestras de ingreso durante el drain; como máximo una corrida formal.
- Los tres gates de la tabla conservan sus aserciones originales, junto con cero violaciones críticas. Los p95 se reportan sin trasladar a SATURATION los SLO de BASE ni crear umbrales nuevos.

Quedan prohibidos los incrementos progresivos de carga, cambios de tasas/población/concurrencia, búsqueda de máximos, barridos, tuning, prolongaciones y repeticiones para obtener saturación o verde. El resultado sólo acredita o incumple este contrato fijo; no sustenta una afirmación de capacidad comercial, carga máxima, estabilidad o fairness. Si una ejecución válida no observa saturación, falla `saturation_observed` y se aplica FAIL/parada, sin aumentar carga; si el entorno/harness impide evaluar válidamente ese gate, se aplica PENDING/parada.

Una base nueva por variante. Revisar el recibo y la integridad antes de pasar a la siguiente. Publicar denominadores, faltantes, p95/máximos, colas, errores y gates propios; no promediar percentiles de organizaciones, descartar muestras lentas ni convertir backlog durable en estabilidad/fairness demostrada.

El [PROFILE aprobado del 02-10](../profile-beta-1-e4-sql-2026-10-02/report.md) conserva autoridad para `0831046`. Esta ejecución produciría evidencia temporal de `1947726`; no se atribuye esa evidencia antes de obtenerla.

## 4. Decisión, conservación y cierre

Entregar en este expediente: preflight y hashes; selección resuelta; recibos por bloque/ID; cinco resultados temporales o su estado NOT_EXECUTED; incidentes; integridad final; cleanup de recursos propios; índice de artefactos y decisión R01–R15/I01–I14 por candidato. Las aprobaciones operativas/privacidad se mantienen separadas.

| Resultado | Criterio |
|---|---|
| PASS técnico integral | Todos los gates aplicables completos y satisfactorios, evidencia íntegra y fuentes del candidato intactas |
| FAIL técnico | El escenario se ejecuta válidamente y viola un requisito aplicable; conservar el resultado y la causa observable. No equivale por sí solo a demostrar un defecto universal del sistema |
| PENDING | Una incompatibilidad del entorno/harness u otra incidencia impide evaluar válidamente el contrato: evidencia incompleta, reloj discontinuo o integridad no acreditada. Registrar el bloqueo sin atribuir automáticamente un fallo al producto |

**Límite de ejecución:** una campaña de alcance fijo; una corrida formal por bloque y como máximo una por variante temporal. Los solapes de jobs ya fijados no son reintentos. Ante un gate fallido o un incidente invalidante, detener la campaña, preservar evidencia y dejar los bloques restantes NOT_EXECUTED. OOM, discontinuidad temporal, corrupción o deriva de fuentes provocan parada inmediata. No hacer ajustes adaptativos, fixes productivos ni reruns automáticos; una nueva campaña requiere una decisión nueva sustentada en lo observado.

Conservar recibos históricos sin sobrescribirlos. Aplicar a la nueva evidencia la convención de hashes y recuperación comprobada de [conservación B9](../b9-consolidation-2026-10-11/README.md), con inventario propio; no reusar el empaquetador anterior como si este expediente perteneciera a su inventario congelado. Preparar una selección Git explícita en la misma rama. Nuevos commits/push no están incluidos en la autorización anterior de los 536 archivos.

Actualizar el acta vigente sólo cuando exista una decisión de ejecución respaldada. Incluso un PASS técnico integral mantiene **PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado y los alcances E/P/UX separados. El encargo termina con su decisión y evidencia; no continúa automáticamente hacia activación o nuevos experimentos.


## Adaptación autorizada r4, 2026-10-14

El usuario pidió «procede a ajustar y ejecutar». Se conserva el árbol 196aceb4f5f234c086b96d8e8af93787613f3c25 y todo el contrato anterior. La suite full se divide exhaustivamente en B8B (21), B8C (41), B8D (27), B8E (29) y general (3213), en ese orden, con bases nuevas compatibles. Cada ID se ejecuta una vez dentro de full; la unión debe ser exactamente los 3331 IDs descubiertos. Se conservan runners nativos, procesos internos, aserciones, guards, locks, cargas, tiempos, umbrales y reglas de skips. La configuración y los inventarios se sellan antes de ejecutar. El gate full exige todos los grupos completos y satisfactorios. Sin reintentos formales ni transferencia de resultados históricos.


## Adaptación nativa Windows autorizada, 2026-10-16

El usuario indicó «continua» para reanudar la alternativa autorizada para preparar y ejecutar sin WSL. Se conserva el árbol corregido y el contrato fijo completo. Python3.13.2 y sus dependencias bloqueadas se copian a un runtime privado verificado, PostgreSQL16.15 usa binarios existentes de solo lectura y un cluster privado nuevo, Node20.20.2 y pnpm9.15.9 son privados. pnpm usa node-linker=hoisted y package-import-method=copy con --frozen-lockfile para evitar enlaces simbólicos. Se conservan los3331 IDs y cinco grupos full, procesos internos, assertions, guards, locks, cargas, tiempos, umbrales, reservas2GiB RAM/1GiBdisco y reloj1s. No se invoca WSL ni se modifica W32Time, instalaciones compartidas o políticas globales. Una ejecución formal por bloque, sin reintentos adaptativos.


## Continuidad operativa de los auxiliares para la campaña nativa r4

La instrucción «rocede con lo que falte» autoriza esta nueva campaña fija tras la parada ambiental de r3. Se conserva, antes del sello, el mismo límite operativo de doce horas (43200 s) para la solicitud propia de actividad y trece horas (46800 s) para el observador, ya preparado en la campaña nativa r3. Este apartado sustituye únicamente el límite histórico de seis horas mencionado arriba. Una solicitud acotada, heartbeat de 1 s, antigüedad máxima de 10 s, sin renovación adaptativa y con restauración del estado original. No cambian políticas globales, pantalla ni reloj. PROFILE conserva 30/300/20 s y todas sus cargas y gates; RAM 2 GiB, disco 1 GiB y reloj 1 s siguen vigentes. No se transfieren resultados previos ni se alteran pruebas o runtime productivo.


## Recuperación de preparación antes del sello, 2026-10-17

La preparación r4 falló al instalar pip-audit con MemoryError, sin sello ni pruebas de aplicación. Windows se reinició después. Se conservan intactos los recibos del intento y su incidente; el estado final del capturador original no está disponible. Se continúa únicamente la preparación pendiente con recibos nuevos: PostgreSQL privado del mismo DATA, identidad actual y durabilidad revalidadas, observación nueva del reloj durante 120 s, instalación auxiliar y validación de intérpretes. El cleanup usa la propiedad actual documentada del servidor reiniciado. Fuentes, historial Git, dependencias de aplicación y selección se vuelven a comprobar antes del sello. No se repite ninguna prueba, pues la campaña formal aún no comenzó. Se conservan íntegros los guards, gates, cargas, tiempos y límites operativos acordados.
