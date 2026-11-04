# Continuación r3 — Cerrar criterios pendientes del orden 4

Preparado el **31-10-2026**. Copiar al agente ejecutor. Mantiene el [contrato original](plan-remediacion-orden-4-2026-10-30.md) y sus límites. No inicia otro chat ni regularización real.

---

Retoma el checkout actual de `C:/Users/LAP/Desktop/VeterinariaSaaS` y completa los criterios pendientes del alcance local del orden 4. I03 ya está implementado en primera versión; no lo reescribas desde cero ni entregues solo otro informe de avance mientras puedas seguir trabajando.

Lee el plan y metaprompt originales, el expediente vigente y `docs/remediaciones/orden-4/REVISION-2026-10-31-r3.md`. Conserva cambios y pruebas existentes, incluyendo corrección de I07, collector/paginación, transición de alias, admin, writer inicial, concurrencia del importador y caps del parser. Respeta AGENTS/RTK y usa grafo si está disponible; fallback documentado a fuente actual cuando no lo esté.

Base habitual, clusters ajenos y VPS siguen fuera de alcance. Solo migraciones/pruebas en el cluster exclusivo de orden 4 y bases sintéticas verificadas mediante su allowlist. No aplicar propuestas, regularizar datos existentes, publicar, hacer commit/push/PR o despliegue. I04/I06 aplazados. No volver a preguntar decisiones de producto ya resueltas.

## Criterios restantes, en este orden

### C1. Proteger y verificar el rollback de I03

`imports.0003_importconflict` solo crea una tabla. Revertirla ahora elimina el detalle completo mientras el JSON guarda muestra 100. La advertencia del runbook no impide pérdida. Implementa una transición segura antes de retirar la tabla y una protección verificable contra retirada prematura. Respeta migraciones ya aplicadas: elige una secuencia nueva o mecanismo compatible y explica el orden, sin reescribir ciegamente una migración aplicada.

Conserva el detalle completo, orden, conteos y estado del job en una representación que el lector de rollback realmente soporte. No dependas de la muestra, un export no comprobado ni recalcular contra catálogo actual. Durante conversión/retirada, coordina o bloquea nuevas publicaciones de reportes para que no reaparezca un JSON truncado entre ambos pasos. Si la transición no puede completarse, detener la retirada preservando datos; no borrar para que migre.

Pruebas en DB sintética: 101 y 2000 detalles, legacy completo e incompleto, lectura posterior compatible, fallo a mitad y reintento. Verifica antes/después payloads, orden, conteos y ausencia de pérdida. Nunca declarar completos los detalles que ya faltaban en un legacy. Incluye upgrade/downgrade pertinente con MigrationExecutor o mecanismo equivalente, no solo invocación aislada de una función.

### C2. Carreras y aceptación de I03

Con PostgreSQL y conexiones/hilos independientes, coordina con barreras estos casos:

- Una página del reporte anterior frente a una publicación nueva: respuesta íntegra de la versión que corresponda y cursor anterior invalidado según contrato, sin mezclar páginas.
- Un lector frente a publicación aún no confirmada o fallida: datos/metadata atómicos y resultado coherente tras commit/rollback.
- Mapping/revalidate/commit frente a lectura con versión/cursor anterior; conservar commit una sola vez y evitar rehabilitar el job.

Completa tests de API para tamaños/cursor/versión inválidos, otro job/tenant, acceso sin permiso/demo/organización desactivada, y totales/muestras de ambos niveles de confianza. Reutiliza lo ya cubierto; no dupliques baterías por contar más tests.

En el wizard, comprueba primera/siguiente/anterior, última página, error de carga y versión reemplazada, revalidación y transición preview→resultado. La muestra y los totales deben seguir coherentes, sin presentar un detalle viejo como la nueva versión ni perder el acceso tras error. Incluye legacy donde corresponda. No rediseñar el wizard ni modificar reglas de filas aceptadas/omitidas.

### C3. I01/I02: writers y límites de transición

Entrega una tabla **finita** de escritores de producción pertinentes (archivo/símbolo, alta/edición, camino de entrada y prueba). Cubre serializers anidados, alta/edición de presentación, importador, admin y otros caminos de producción descubiertos. No convertir cada fixture o escritura SQL arbitraria en un nuevo requisito de producto. Si un camino legítimo rompe el alias después del backfill o escribe stock fuera del writer, corrígelo y prueba su guard.

Prueba factores inválidos/fronteras y rechazo en transición sin alterar saldos, factores o snapshots. Si un estado previo ya tiene constraints que impiden un factor inválido, demuestra el rechazo real y delimita el preflight; no desactives protecciones de orden 2 o constraints para fabricar un fixture imposible. Mantén la prueba de upgrade con snapshots y completa solo las invariantes faltantes.

Para el wizard de lotes, simula fallo entre creación de producto a cero y recepción, y reintento: resultado parcial honesto, referencia al producto ya creado y sin duplicar producto/stock por reenviar todo el alta. Si el contrato actual de recepción tiene límites de idempotencia, no los ocultes: resuelve el escenario autorizado o registra una decisión técnica concreta compatible con el plan, sin implementar importación de lotes ni borrar ledger como compensación. Prueba también recepción rechazada y recuperación por el flujo existente.

### C4. I05/I07: denegación y diagnóstico pendiente

Completa organización desactivada en los endpoints afectados y las denegaciones faltantes, conservando código demo y otros contratos. No amplíes un permiso para facilitar pruebas.

Diagnóstico: cubrir referencias incompletas, unidades mixtas, balances de lotes inconsistentes y propuesta cuyo saldo/ledger/procedencia cambia después. El resultado debe identificar que requiere nueva revisión, sin certificar el pasado ni aplicar movimientos. Conserva la regresión ya añadida de lot_number con FK nula y ausencia de escrituras. Si no existe una operación de aplicación (no requerida), verifica obsolescencia del manifiesto por su comparación/validación de preparación; no inventes una API apply para probarla.

### C5. Conciliar evidencia y cerrar por criterio

B7 ya tiene prueba de integración de página que verifica valores y cabeceras en ambas direcciones. En revisión independiente pasaron **36/36** al ejecutar juntos `src/pages/inventory.order.test.jsx` y `src/utils/inventory.test.js`. Esa evidencia satisface la comprobación de página aceptada en la continuación; no mantengas B7 pendiente únicamente por ausencia de inspección visual manual ni agregues una aprobación nueva. No atribuyas PASS al lint global: registra por separado fallos previos comprobados y regresiones del cambio.

Para I03, aporta evidencia de comportamiento del wizard y los criterios C1/C2. Una comprobación visual adicional puede complementar los tests si resuelve una duda concreta; no reemplaza pruebas de integridad ni abre un rediseño fuera de alcance.

Actualiza MATRIZ por criterio con archivo, prueba/comando, resultado y límite. Sustituye frases abiertas como «faltan regresiones completas» por casos/módulos concretos del contrato que falten. Reutiliza evidencia válida; repite pruebas amplias solo si cambios o dudas nuevas lo justifican. El número de tests no sustituye cobertura de transiciones.

## Entorno y terminación

Verifica directorio, puerto, proceso y destino efectivo del cluster exclusivo antes de iniciarlo o migrar. No use la base habitual/orden 2. Ante timeout, revisa si tu proceso sigue activo antes de repetir; ajusta tiempo o divide suites independientes manteniendo transacciones de dominio. No borrar clusters/directorios de evidencia ni relajar allowlists. Mantén integraciones externas desactivadas.

Continúa con C1–C5 hasta completar lo autorizado o demostrar un bloqueo concreto e inevitable. No hay un bloqueo técnico pendiente acreditado en la entrega actual. Si aparece uno, registra comando/error saneado, parte afectada y mínima intervención necesaria; completa lo independiente. No terminar por tener otro resumen de pendientes disponible.

El cierre esperado conserva salvedades: I01/I02/B7/I03/I05 implementados y verificados localmente; I07 diagnóstico/propuesta preparados con aplicación real pendiente de aprobación por producto; I04/I06 aplazados. No declarar regularización real, migraciones en habitual/producción ni go-live. Sin commit/push/PR o despliegue.

---

[Plan original](plan-remediacion-orden-4-2026-10-30.md) · [Revisión r3](remediaciones/orden-4/REVISION-2026-10-31-r3.md).
