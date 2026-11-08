# Decisiones y transición

Rigen las decisiones cerradas del [plan](../../plan-remediacion-orden-4-2026-10-30.md). B7 compara las mismas cantidades y valoración comercial que muestra la tabla. Los empates conservan el orden de entrada.

En curso: serializers normalizan presencia explícita; 0028 amplía alias a 12/4 y 0029 copia exclusivamente desde factores válidos, deteniendo la migración ante inválidos. El alta manual positiva usa el writer en la transacción y se rechaza stock inicial sin lote para productos que los requieren. Importación propaga solo el código demo específico. No se acredita aún cobertura de todos los writers ni de todas las regresiones. Las decisiones y límites detallados permanecen en el plan.

Continuación r2: se agregó `ImportConflict`, relacionado al job y sustituido bajo su lock; escrituras por lotes de 100, muestra máxima 100 y publicación de metadatos en la misma transacción. Un mapping invalida el reporte anterior y mantiene errores bloqueantes previos. Lecturas usan cursor firmado asociado a job, versión y tamaño. Un resultado legacy se convierte desde su JSON al solicitarlo y se marca incompleto si su contador supera los detalles disponibles; nunca se recalcula desde el catálogo. La UI expone páginas para preview y resultado. Está pendiente probar todos los casos de aceptación y la transición de rollback.

Continuación posterior: `imports.0004` proporciona puente inverso al JSON legacy antes de revertir 0003 y comprueba integridad del conteo disponible. El servicio de commit vuelve a comprobar bloqueantes tras adquirir el lock. El alta de presentación adicional con stock positivo utiliza el writer; el PATCH no asigna stock.

Si falla o se pierde la respuesta de recepción inicial de lotes, el wizard no afirma que falló la escritura remota ni reenvía automáticamente; pide revisar movimientos y lotes. Esto no convierte el endpoint de recepción en idempotente.

## Continuación 01-11

`imports.0005` rehidrata desde el JSON restaurado por 0004 cuando la tabla se recreó vacía, mantiene `complete` y acuña nueva versión. Rechaza estados parciales inconsistentes sin consultar catálogo. `inventory.0030` agrega receipt por organización/UUID de operación, vinculado a actor, presentación y hash del payload validado. Con `X-Idempotency-Key`, una repetición idéntica devuelve el resultado confirmado; contenido u objetivo/actor distinto devuelve 409. Las llamadas sin clave conservan el contrato anterior. Receipt y movimiento se escriben en una transacción. El wizard guarda localmente el UUID, producto, presentación y payload antes de enviar y reintenta esa identidad tras recarga. Queda pendiente verificar la recuperación si se pierde por completo el almacenamiento local y la comprobación visual.

### Writers de producción contrastados

| Ruta | Operación | Regla | Evidencia |
|---|---|---|---|
| `inventory/serializers.py::ProductSerializer.create` | Alta manual | stock cero y entrada por writer; alias normalizado | gate paridad y factores en `test_inventory_import.py` |
| `inventory/serializers.py::PresentationCreateSerializer` | Alta/PATCH | un alias normaliza ambos; contradicción rechazada; PATCH no asigna stock | `test_order4_alias.py`, test de presentación en `test_inventory_import.py`, `test_order4_alias_writers.py` |
| `inventory/serializers.py::ProductSerializer.update` | PATCH del producto con `presentation_input` | edita la primera presentación con el mismo par normalizado; contradicción rechazada sin cambios | `test_order4_alias_writers.py` |
| `inventory/views.py::PresentationDetailView` | PATCH de presentación | sin alias conserva el par; uno solo normaliza ambos; contradicción o factor 0 rechazados | `test_order4_alias_writers.py` |
| `inventory/views.py::PresentationCreateView` | Nueva presentación | entrada positiva por writer, lotes requieren recepción | dos tests de presentación en `test_inventory_import.py` |
| `inventory/admin.py::PresentationAdmin` | Edición | alias solo lectura y sincronizado al cambiar factor | `test_order4_alias.py` |
| `imports/services_inventory.py::_create_product_with_presentation` | Importación/bulk | alias igual a factor con 4 decimales (corregido el 08-11: lo redondeaba a 2), stock cero; writer aplica entrada | gate paridad, suite inventory import y `test_order4_alias_writers.py` |
| `inventory/services.py::apply_stock_movement` | Movimiento | lock de producto, unidades base, ledger y sombra | suite recepción/stock y tests del writer |
| `inventory/views.py::receive_presentation_stock` y `services.py::receive_stock` | Recepción de lotes | identidad opcional, receipt atómico, writer por lote | `ReceptionIdempotencyTests`, `test_order4_reception_concurrency.py` |
| `core/management/commands/seed_demo_clinic.py` | Seed explícito demo | envía ambos aliases iguales y usa writer | pasos de organización y catálogo ejecutados dos veces en `test_order4_alias_writers.py` |

Lista cerrada el 08-11 con una búsqueda de todas las escrituras de `Presentation` fuera de pruebas: no hay otros writers vivos. `ProductAdmin` no tiene inlines. Las migraciones 0005 y 0018 son históricas, y 0029 corrige su resultado.

**Importador (08-11):** el alias se redondeaba a 2 decimales (0.125 → 0.13) y una guarda rechazaba factores menores a 0.005, ambas cosas porque `quantity` era 10/2 antes de 0028. Ahora copia el factor exacto y solo rechaza un factor que redondea a 0 con 4 decimales. Sigue una diferencia, pendiente de decisión: el importador redondea a 4 decimales un factor con más, mientras el alta manual lo rechaza.

## I01: recuperación sin estado local (06-11)

Contrato: [metaprompt del 02-11](../../metaprompt-orden-4-i01-recuperacion-sin-estado-local-2026-11-02.md). El receipt de 0030 ya garantizaba idempotencia a quien conservara el UUID, pero nadie podía encontrarlo sin él. Se extiende ese mismo modelo; no se crea un segundo concepto ni infraestructura genérica.

**Decisión: intención durable en dos peticiones.** `POST presentations/<id>/receptions/` guarda la captura como `pending` y `POST receptions/<id>/complete/` la aplica. Una sola petición con dos commits no bastaba: mientras aún no llegara a Django sería invisible, así que una lista vacía no probaría nada. Separadas, la ejecución solo sale tras conocer la respuesta de la intención. Cada orden de llegada queda cubierto:

| Qué ocurre | Estado del servidor | Consecuencia |
|---|---|---|
| Intención perdida antes de llegar | Nada | Nada aplicado. Sin rastro que conciliar; una entrada nueva es libre |
| Intención tardía, tras otra entrada | `pending` inerte | Sin stock. Aparece para que una persona la descarte |
| Respuesta de la intención perdida | `pending` | Sin stock. Se completa o descarta sin recapturar |
| Ejecución en vuelo | `pending` | Completar espera el lock y devuelve lo confirmado; descartar espera y da 409 si ya se aplicó; otra entrada del producto → 409 |
| Fallo antes del commit | `pending` | Rollback completo. Se reintenta con la misma identidad |
| Respuesta de la ejecución perdida | `confirmed` | Se recupera la evidencia, sin movimientos nuevos |
| Ejecución tardía tras descartar | `discarded` | 409, sin stock |

**Cómo se descubre sin UUID local.** `GET /api/inventory/receptions/` devuelve, sin filtro obligatorio, las operaciones del usuario autenticado: paginación por cursor con el orden del libro, 50 por defecto, máximo 100 y hasta 10 líneas por fila en la lista. Producto, lote, cantidad, proveedor, fecha, actor y estado bastan para reconocerla, y `operation_id` es la identidad pública con la que se continúa. La organización sale de la sesión. El aviso de pendientes y el panel Recepciones parten de esta lista, no del navegador. El `localStorage` del wizard queda como atajo de reintento: que falle o se borre ya no cambia nada, y un valor ilegible dejó de bloquear el alta.

**Cómo se resuelve una candidata ambigua.** El sistema no elige: ni `first()`, ni coincidencia de contenido, ni autoselección con una sola candidata. La persona selecciona una fila, ve lo capturado, las demás entradas de ese producto desde entonces y el saldo actual aparte, y confirma una de dos acciones: **completar** (aplica esa captura, con su identidad) o **descartar** (motivo obligatorio, sin stock). Si la evidencia no determina cuál fue, ese es el procedimiento: comparar con la remisión y decidir. No se promete detección automática.

**Qué acredita cada estado.** `confirmed` y los movimientos enlazados (`StockMovement.reception_operation`, misma transacción) son la prueba; un saldo o lote coincidente no lo es, y un `pending` sigue `pending` aunque el stock coincida. `applied_lines` es lo histórico y `current_balance` se publica aparte, rotulado como acumulado.

**Actor y supervisión.** El vínculo de actor se conserva: ejecutar exige ser quien capturó, y sin supervisión una operación ajena da 404, incluso con `inventory.update`. Reutilizar una identidad descubierta da 409 sin detalle. La supervisión es `staff.reset_password`, permiso existente de administración del equipo: añade lectura con `scope=organization` y permite **cerrar** una operación ajena, nunca ejecutarla, para que la de alguien que ya no está tenga salida. Otra clínica: 404 también con UUID, cursor o filtro de producto. No autenticado: 401. Organización desactivada: rechazada por autenticación.

**Sin evidencia suficiente.**

- *Recibo anterior a 0031:* `confirmed` con `evidence_level=legacy_receipt`. No se reconstruyen payload, cantidades ni enlaces: el hash es de un solo sentido y los saldos del recibo no son cantidades (además podían ser anteriores al movimiento). Solo se publica la identidad de los lotes.
- *Fila sin resultado:* no debería existir. Queda `pending` sin captura y solo puede descartarse.
- *Entrada sin operación:* `GET /receptions/unattributed/` lista esos hechos del libro. Procedimiento concreto en el panel: comparar con la remisión; si está, ya sumó y no hay nada que corregir; si no, recepción nueva explícita. Ninguno de los dos caminos altera el historial, y no se fabrica un receipt.

**Recepción nueva.** Es otra acción, con otra identidad, y sigue permitida: no se deduplica por contenido. Solo se exige resolver antes el `pending` del mismo actor y producto (`UniqueConstraint` parcial). Pendientes de otras personas no bloquean; se ven como evidencia al revisar.

**Límites que permanecen.**

- Si el navegador original sigue vivo con la intención en vuelo y la persona registra otra entrada en otra pestaña, ambas son acciones explícitas y el servidor no puede saber que eran la misma entrega; la segunda aparece como operación propia para revisión. No se promete detección infalible.
- `POST /receive/` con clave sigue siendo una sola petición: idempotente, pero sin visibilidad mientras está en vuelo. Sin clave conserva su contrato y no recibe estas garantías; la app ya no lo usa para recepciones por lotes.
- La entrada rápida de productos **sin lotes** (`adjust`) no tiene identidad de operación: aparece en «Entradas sin identidad», sin idempotencia. Queda fuera de este criterio.
- El alta del producto (`createProduct`) no es idempotente; si se pierde esa respuesta el producto se ve en el catálogo con stock cero. No se amplía el alcance del plan.
- Un `pending` no caduca: permanece hasta que alguien lo resuelve.

## I03: presentación del reporte (08-11)

La revisión visual cambió la presentación, no el contrato del reporte ni las decisiones de importación:

- El detalle paginado usa la misma tarjeta que la muestra (`ConflictCard.jsx`), con «En tu archivo» frente a «Ya registrado». Antes mostraba nombres de campo internos (`name:`, `internal_code:`) sin decir cuál venía de dónde.
- En inventario, «por revisar» puede ser por código con otro nombre o por nombre sin código. La sección pasa a «Posibles duplicados por revisar» con un texto que cubre ambos casos, y cada tarjeta muestra el `message` del servidor. Clientes y mascotas conserva su texto fijo.
- La tarjeta de resultado de inventario lee `skipped_conflicts`. `skipped_duplicates` nunca se incrementa en ese importador, así que mostraba 0 aunque se omitieran filas.

