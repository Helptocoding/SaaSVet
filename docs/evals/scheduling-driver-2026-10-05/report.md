# SaaSLyVet — acreditación del instrumento de medición D29

Fecha local: 2026-10-05. Estado: **MEASUREMENT_CORE_ACCREDITED**.
Aplicación: baseline `825db75df68bf076929fa787e77beefe96803350`, intacto.
Matriz completa: **NOT_EXECUTED / FULL_CONTROLLER_NOT_ACCREDITED**.

Se preparó el núcleo del conductor de medición y se validó en una copia aislada del baseline, mediante PostgreSQL local 16.15 con fsync/synchronous_commit activados, datos sintéticos y provider contenido. Se añadieron únicamente código de pruebas y estos documentos/recibos. No se ejecutaron benchmarks, barrido, PROFILE, tuning o providers externos. No se implementó scheduling ni se modificó E4.

## Evidencia y resultados

| Validación | Resultado | Recibo |
| --- | --- | --- |
| Análisis: población, intervalos, clocks, transacciones, tenants y backlog | 25 pruebas PASS | [Log de pruebas](unit-tests.log) |
| Fronteras DB, W1/W2, pendientes, duplicado y ACK perdido | 12 controles PASS | [Acreditación](accredit-01/accreditation.json) |
| Pipeline finito: 2 planners + 1 sender, batch 1 y pausa 1 s | 7 controles PASS | [Prueba concurrente](smoke-01/smoke.json) |
| Aislamiento y procedencia | Copia del baseline más overlay exclusivo de pruebas | [Entorno y hashes](environment.json) |
| Limpieza/integridad | Instancia cerrada, datos y credenciales retirados, 3095 rutas previas intactas | [Recibo de limpieza](cleanup-and-integrity.json) |

En la acreditación se conservaron dos episodios READY todavía sin claim en el [primer corte](accredit-01/pending-cohort.json). La corrección quedó agrupada con W1 y conservó su origen en el [corte preclaim](accredit-01/correction-cohort.json). El [corte W2](accredit-01/w2-cohort.json) conserva W2 READY mientras W1 sigue PROCESSING. Un claim liberado desde savepoint y después deshecho por rollback exterior no terminó el episodio; tampoco lo hizo un claim deshecho por rollback de savepoint. El ingreso deshecho no apareció como aceptación durable y el duplicado no añadió otro episodio.

El commit con ACK perdido se registró como error dentro de su bracket. Una conexión independiente verificó work/epoch/fingerprint/membership y acotó visibilidad en el [recibo durable](accredit-01/durable-resolutions.json). El [resultado final](accredit-01/final-cohort.json) concilia cuatro inputs ordinarios durables en tres episodios, sin pérdida de población ni fronteras desconocidas en esa historia controlada.

La prueba concurrente usó dos inputs ordinarios, dos procesos planner reales y sender separado, con el fixture existente de READ público. El [recibo de cohorte](smoke-01/cohort.json) conserva ambos episodios/claims y sus intervalos. Hubo dos trabajos completados y dos aceptaciones del provider simulado. Los logs/journals de cada participante están junto al recibo.

Los dos resultados de cohorte se etiquetan `COHORT_ONLY_NOT_LEVEL_ACCEPTANCE`: sirven para acreditar el instrumento, no una tasa o una promesa comercial. Las comparaciones temporales son observaciones del fixture, condicionadas a la correlación de clocks y ausencia de saltos no observados. No se derivó E, capacidad máxima, percentil de SLA ni causalidad histórica de E4.

## Preparación, limpieza y alcance

La primera llamada al launcher agotó el plazo del wrapper; una conexión independiente comprobó que el servidor oculto ya estaba disponible. La aplicación del esquema también superó su plazo inicial; se verificó la ausencia de un migrador activo y las migraciones committed antes de continuar en la misma base aislada. Se conservan los logs de preparación. No se alteraron migrations fuente ni parámetros de PostgreSQL para acelerar el ensayo.

Las corridas se hicieron sobre bases nuevas clonadas de un esquema vacío local; configuración exclusivamente en procesos hijos. Los participantes finalizaron normalmente, la instancia PostgreSQL fue detenida, su listener cerrado y sus datos/credenciales eliminados. Se conserva la copia de fuentes sin base ni credenciales para trazabilidad.

El mapa de **3095 rutas anteriores**, incluidas ambas `.env`, contratos, D29-v1, preflight anterior y E4, conserva SHA-256 `02d79dfd8c37b2803a676a47349e251768d09cc2afeebcca33fb055a9785bba8`. No hay cambios en esas rutas ni en HEAD. Las eliminaciones/modificaciones previas ajenas a este encargo permanecen intactas. No se crearon commits.

## Preparación restante

El [documento del conductor](../../decisions/2026-10-05-scheduling-measurement-driver.md) describe entrypoints, guardrails y límites. La captura por nivel está preparada como observación; no fue ejecutada ni acreditada como barrido. Falta conectar y acreditar el controlador completo de calibración, avance, refinamiento, confirmaciones y condiciones de cada escenario, con pruebas de conformidad de la oferta e invariantes antes de emitir un nivel compatible. Las recetas R2 de fallos no se ejecutaron ni quedan aprobadas por estos casos finitos.

La caracterización y la aprobación de E siguen posteriores. Los recibos originales de D29-v1, preflight y E4 no se reclasifican ni se sobrescriben.
