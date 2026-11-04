# Continuación — Completar el alcance local del orden 4

Fecha: **01-11-2026**. Entregar al agente ejecutor. Conserva el [plan original](plan-remediacion-orden-4-2026-10-30.md), las decisiones del usuario y los límites vigentes.

---

Retoma `C:/Users/LAP/Desktop/VeterinariaSaaS` desde su estado actual. Completa los criterios pendientes; no vuelvas a implementar lo ya válido ni sustituyas el trabajo por otro resumen parcial mientras puedas avanzar. Lee el contrato original, el expediente vigente y `docs/remediaciones/orden-4/REVISION-2026-11-01.md`.

Mantén base habitual, clusters ajenos y VPS intactos; solo migraciones/pruebas sintéticas en el destino exclusivo de orden 4, tras verificar proceso/directorio/puerto/allowlist. Sin regularización real, commit/push/PR, pagos, publicación o despliegue. I04/I06 aplazados. Conserva AGENTS/RTK y cambios ajenos. Usa grafo cuando esté disponible y contrasta código actual; documenta el fallback si no lo está.

## 1. Corregir recuperación de I03 después de rollback y posterior upgrade

El puente 0004 restaura conflictos completos al JSON, pero deja `conflict_report`. Al bajar 0003 se elimina la tabla; al subir de nuevo, queda vacía y el forward 0004 es noop. El endpoint/conversor ven metadata y omiten rehidratar. El JSON sigue teniendo datos, pero la consulta paginada puede dar resultados vacíos con total/available positivos.

Resuelve el ciclo completo, no solo la bajada. La representación de rollback debe ser inequívoca para el lector de la versión anterior y para la reconversión posterior, o debe existir rehidratación segura al volver a subir. No fabricar detalle contra el catálogo actual, marcar completo un legacy incompleto ni sustituir la recuperación por un error permanente. Coordina las escrituras según el procedimiento de rollback y preserva protecciones contra retirar datos prematuramente.

Usa la prueba MigrationExecutor ya existente de 201 detalles: amplíala a publicar → bajar → subir → leer todas las páginas por API. Verifica payloads, orden, conteos, nueva versión/cursor coherentes y ausencia de pérdida/duplicación. Repite el caso legacy incompleto manteniendo lo que realmente faltaba. El `finally` que restaura hojas no es por sí solo una prueba de esa lectura. Conserva compatibilidad de migraciones ya aplicadas y documenta el procedimiento; no reedites ciegamente historial aplicado.

## 2. Resolver recepción del wizard ante respuesta perdida

El aviso de «recepción no confirmada» es correcto, pero el escenario sigue pendiente: si el servidor hizo commit y se pierde la respuesta, una segunda llamada a receive puede sumar otra entrada. Dos compras distintas del mismo lote sí deben poder acumularse.

Implementa la solución mínima compatible con los patrones existentes. Una opción válida es identidad de operación persistente y receipt/idempotencia del servidor; también es admisible recuperación autoritativa equivalente si prueba las mismas garantías. No deduplicar por lote/cantidad/payload idénticos ni depender solo de un booleano de UI.

Si eliges identidad/idempotencia:

- Alcance explícito por organización, operación y presentación/objetivo, con payload canónico ligado a la identidad. Autorización vigente antes de ejecutar o devolver resultados. No exponer receipts de otra clínica/actor ni inventar un tenant para plataforma.
- Misma operación y payload: devolver resultado/evidencia ya confirmados sin nuevos movimientos. Misma identidad con payload incompatible: conflicto sin efectos. Operaciones distintas e iguales en contenido: ambas pueden ser recepciones legítimas.
- Receipt y movimientos/saldos quedan atómicos; dos reintentos concurrentes no duplican la recepción. Mantener orden de locks y writer autoritativo. Un fallo previo al commit no debe dejar un receipt de éxito falso.
- Conservar la identidad para el reintento del wizard y la referencia del producto/presentación ya creados, incluyendo el estado no confirmado. No volver a crear producto, reenviar toda el alta o generar otra identidad automáticamente por una respuesta perdida. Si un reinicio/recarga pierde el contexto, recuperar o exigir reconciliación autoritativa antes de permitir una nueva entrada ambigua.
- No crear infraestructura genérica o un sistema financiero paralelo. Reutilizar un patrón existente solo si sus dependencias y semántica encajan; no relajar permisos ni alterar el contrato de recepciones distintas para facilitarlo.

Pruebas PostgreSQL + flujo frontend: fallo antes de commit; commit exitoso con respuesta descartada; reintento de la misma operación; dos reintentos concurrentes; identidad reutilizada con otro payload; otra organización; dos recepciones legítimas del mismo lote. Comprobar Product, StockLot, movimientos/autor y producto único. No basta contar toasts o mockear siempre una respuesta exitosa. No compensar eliminando ledger ni afirmar atomicidad entre dos peticiones separadas.

## 3. Terminar las comprobaciones restantes sin abrir una lista indefinida

Entrega una tabla de writers de producción pertinentes: archivo/símbolo, operación, regla y prueba. Revisa los faltantes de alias y saldos, incluyendo serializers, importador, admin y alta/edición de presentaciones. No convertir todos los fixtures arbitrarios en nuevos writers de producto. Conserva pruebas de upgrade con snapshots y preflight; estados prohibidos por constraints deben probar su rechazo sin eludirlos.

I03: completa solo los escenarios concretos faltantes de aceptación/versión/errores y una comprobación visual local acotada de preview/resultado, paginación y mensajes (loopback, datos sintéticos, sin terceros). Conserva las pruebas de carreras/aislamiento ya suficientes. No rediseñar el wizard ni limpiar todo el lint preexistente.

I07: demuestra con fixtures la comparación de propuesta preparada frente a saldo/ledger/unidad/procedencia cambiados y datos ambiguos. Debe exigir nueva revisión/aprobación individual, sin aplicar stock ni inventar aprobaciones. Si no hay apply (no requerido), verifica la vigencia de la propuesta de preparación; no crees una API de regularización solo para completar esta prueba.

B7 e I05 ya figuran verificados localmente con evidencia acumulada; consérvalos salvo regresión nueva concreta. No reabrir B7 solo por falta de inspección visual manual cuando su integración de página ya fue aceptada. No atribuir PASS a lint global con errores existentes.

## 4. Verificación y terminación

Pruebas dirigidas por cambio, checks/migraciones y build pertinentes. No repetir suites amplias sin cambios o dudas que lo justifiquen. Ante timeout, comprueba procesos propios antes de repetir; ajusta tiempo o divide suites independientes sin alterar atomicidad del dominio. No cambiar a la base habitual ni relajar allowlists. Detén únicamente tu proceso identificado y conserva directorios/evidencia.

Actualiza MATRIZ/EVIDENCIA/DECISIONES/APLICACION-Y-ROLLBACK y README con criterios concretos, código, comandos y resultados. Separa prueba directa, simulación y evidencia reportada. El cierre esperado es I01/I02/B7/I03/I05 implementados y verificados localmente; I07 diagnóstico/propuesta preparados con ejecución real pendiente de aprobación por producto; I04/I06 aplazados.

Continúa autónomamente hasta completar este alcance o acreditar un bloqueo concreto inevitable, completando lo independiente. No existe un bloqueo técnico pendiente demostrado en el reporte actual. Si surge, identifica error/parte afectada y mínima intervención necesaria. No pedir otra vez decisiones ya resueltas ni emitir un nuevo cierre parcial solo porque quedan pruebas ejecutables.

---

[Contrato](plan-remediacion-orden-4-2026-10-30.md) · [Revisión del 01-11](remediaciones/orden-4/REVISION-2026-11-01.md).
