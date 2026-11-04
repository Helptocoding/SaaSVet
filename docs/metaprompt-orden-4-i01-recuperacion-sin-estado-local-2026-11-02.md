# I01 — Recuperación sin estado local del navegador

Fecha: **02-11-2026**. Precisión del usuario: recuperar o reconciliar autoritativamente una recepción si se pierde totalmente el almacenamiento local; el receipt del servidor no descubre por sí solo al navegador la identidad perdida.

Este encargo complementa el [plan del orden 4](plan-remediacion-orden-4-2026-10-30.md). No reabre B7/I05 ni la preparación de I07 ya acreditados, no amplía I04/I06 y no autoriza aplicación en base habitual/VPS.

---

Retoma I01 en `C:/Users/LAP/Desktop/VeterinariaSaaS`. El objetivo restante es **recuperar o reconciliar una recepción sin conocer su operation_id anterior ni conservar memoria, localStorage o sessionStorage del navegador**. Repetir pruebas que conservan el UUID no satisface este criterio.

## Estado existente que debes conservar

Ya existen `StockReceptionReceipt`, `inventory.0030`, recepción con `X-Idempotency-Key`, vinculación a organización/actor/presentación/payload y resultado atómico. El wizard persiste localmente la identidad y reintenta tras recarga. Revalida el código actual; no lo sustituyas por una versión vieja.

El receipt actual tiene organización, actor, presentación, operation_id, hash, resultado y fecha. No presupongas que el hash permite reconstruir el payload ni que los saldos del resultado equivalen a la cantidad de esa recepción. Los lotes pueden haber recibido otras entradas después. Las llamadas legacy sin clave conservan su contrato, pero no se les atribuyen garantías que no tienen.

## Comportamiento requerido

1. Tras pérdida total del estado local y nueva autenticación, el usuario debe poder consultar desde la app operaciones de recepción que esté autorizado a ver, **sin proporcionar el UUID perdido**. Usa una vía de descubrimiento/reconciliación del servidor, paginada y acotada, con identidad pública de la operación y evidencia suficiente para reconocerla. Reutiliza endpoints/componentes de historial si realmente satisfacen ese contrato.
2. La organización y permisos se resuelven del lado servidor. Mantén el vínculo de actor de la operación; no ampliar permisos ni permitir adoptar/repetir el receipt de otra persona por descubrirlo. Una facultad de supervisión debe provenir de permisos ya existentes y comprobados, no de un rol inventado. Aislar otra clínica y organización desactivada.
3. El descubrimiento puede apoyarse en producto/presentación, actor autorizado y ventana temporal, pero debe permitir encontrar la operación aunque el navegador tampoco conserve el objetivo. Si necesita una selección inicial, obtenerla de datos autorizados del servidor. No exigir una clave que precisamente se perdió ni esconder la única recuperación detrás del almacenamiento local.
4. Una operación confirmada se recupera mediante su evidencia/resultado **sin generar movimientos nuevos**. Distinguir el resultado histórico de esa recepción del saldo actual del producto/lote. No inferir confirmación solo porque el stock actual coincide o el lote existe.
5. Una operación pendiente o incierta debe reconciliarse antes de ofrecer un reenvío como nueva entrada. Si el receipt actual no permite distinguir intenciones en curso, resolver ese vacío de estado del servidor; un registro durable de intención antes de ejecutar es una opción técnica, no una exigencia de infraestructura genérica. Una lista vacía mientras otro request está en vuelo no prueba que la recepción no se haya ejecutado o no vaya a hacerlo.
6. Si hay varias candidatas, la UI exige selección/conciliación explícita y muestra lo que puede acreditar. No elegir `.first()`, buscar una coincidencia de payload y asumir identidad, ni convertir una ambigüedad en éxito o fallo definitivos. Dos recepciones legítimas pueden tener el mismo lote, fecha, cantidad o contenido.
7. Si no hay evidencia suficiente, mantener el resultado como no confirmado y ofrecer una revisión autoritativa operable, sin sumar stock automáticamente. No cerrar el criterio con otro toast, una recomendación genérica de «revisa tus movimientos» o un bloqueo permanente sin vía de resolución. Define el flujo concreto para concluir la conciliación sin alterar historial.
8. Al identificar la operación anterior, usa su identidad/estado del servidor para completar recuperación o reintento seguro. No acuñar automáticamente un UUID nuevo, volver a crear el producto ni reenviar toda la captura. Una **nueva recepción legítima** es una acción explícita distinta y debe seguir permitida, sin deduplicar por similitud.

No se exige adivinar una intención perdida: cuando la evidencia no determina cuál fue, debe existir conciliación humana explícita sobre información autoritativa. No prometer detección automática infalible ni no duplicación basada únicamente en una lista de operaciones recientes.

## Prueba de aceptación decisiva

Con servidor y datos sintéticos en PostgreSQL aislado:

- Registrar/enviar una recepción y descartar la respuesta después del commit. Destruir el componente y **todo el contexto del navegador**, incluyendo preferencias/sesión almacenadas. Volver a autenticarse en un contexto limpio, sin pasar operation_id por fixtures, URL, variables globales o mocks de almacenamiento. Descubrir/reconciliar desde el servidor y verificar que producto, lotes y movimientos no se duplican.
- Repetir con intención/operación aún en curso y con fallo antes de commit; demostrar que ausencia temporal de un receipt visible no produce una segunda entrada. Coordinar las carreras del servidor con conexiones independientes donde corresponda.
- Incluir dos recepciones distintas e idénticas en contenido; ambas son válidas. Incluir varias candidatas y probar que el usuario selecciona o resuelve explícitamente, sin elección automática ni mutación por consultar.
- Otra organización, otro actor sin permiso, usuario no autenticado y organización desactivada no recuperan ni ejecutan datos ajenos. No filtrar resultados ni detalles por cursor/UUID.
- Operaciones anteriores sin identidad/evidencia recuperable quedan con un límite honesto y procedimiento concreto; no fabricar un receipt histórico a partir de saldos. Comprobar también datos actuales modificados después de la recepción para no mostrar un saldo acumulado como cantidad de esa operación.
- Mantener las pruebas ya existentes de mismo UUID/payload, conflicto de payload, concurrencia, rollback y recarga con estado conservado. Añadir únicamente las necesarias para el escenario nuevo; no repetir campañas de otros órdenes.

## Límites y entrega

Código local y migraciones preparadas/probadas solo en el destino sintético exclusivo de orden 4 con allowlist comprobada. Base habitual, clusters ajenos y VPS intactos. Sin regularización real, eliminación de movimientos como compensación, commit/push/PR o despliegue. Respeta AGENTS/RTK y preserva cambios existentes. No implementar extensiones de importación de lotes.

Actualiza la decisión, matriz y evidencia de I01 con rutas/API, estado server-owned, interacción de recuperación, pruebas/comandos/resultados y límites. Explica cómo se descubre la operación sin UUID local y cómo se resuelve una candidata ambigua. I01 no se cierra con un receipt existente que la interfaz no puede localizar ni con un test que conserva la identidad por una vía oculta.

Continúa con este criterio hasta implementarlo y verificarlo o demostrar un bloqueo concreto, sin reabrir las preguntas de producto ya respondidas. El cierre local del resto del orden 4 sigue el contrato y la matriz vigentes.

---

[Contrato general](plan-remediacion-orden-4-2026-10-30.md) · [Estado del expediente](remediaciones/orden-4/MATRIZ.md).
