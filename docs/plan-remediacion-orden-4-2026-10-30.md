# Orden 4 — Inventario e importaciones

Fecha: **30 de octubre de 2026**. Estado: **PLAN ACORDADO PARA IMPLEMENTACIÓN LOCAL**. Prepara el trabajo de otro agente; no acredita remediación, regularización de saldos, migraciones aplicadas ni despliegue.

Base: [priorización](plan-remediacion-priorizado-2026-10-28.md), [inventario documental](pendientes-documentados-2026-10-27.md), [ADR p31](decisions/2026-06-03-p31-product-level-stock-base-units.md), [ADR p61](decisions/2026-08-25-p61-importador-inventario.md) y decisiones del usuario. Ejecución: [metaprompt](metaprompt-remediacion-orden-4-2026-10-30.md).

## 1. Decisiones vinculantes

| Tema | Decisión / límite |
|---|---|
| Alcance | Corregir integridad, orden y reportes. Importación de varias presentaciones, lotes y múltiples orígenes/sucursales permanece aplazada. |
| Implementación | El futuro agente modifica código local y prepara migraciones; aplica y valida únicamente en bases aisladas con datos sintéticos. |
| Base habitual | No migrar, recrear, resetear, regularizar ni usarla como destino de pruebas. Que contenga demos no revoca este límite. |
| VPS | Fuera de alcance: sin SSH, conexiones de prueba, pagos, reactivación, despliegues ni migraciones. |
| Stock inicial manual | Conservar la captura actual y registrar automáticamente el movimiento auditable dentro de la misma operación. Sin un paso adicional obligatorio para productos sin lotes. |
| Unidades nuevas | Si `quantity` y `conversion_factor` se envían y difieren, rechazar. Si solo se envía uno, normalizar ambos al mismo valor. Si faltan ambos en un alta, conservar el default explícito de factor 1. |
| Alias antiguo | Preparar corrección determinista de `quantity` desde un factor válido; validarla aisladamente. No cambiar factor, stock, precios, unidades históricas ni snapshots. |
| Conflictos | Muestra acotada y acceso paginado al detalle completo, con totales reales. No cambiar qué filas se importan ni sus reglas de deduplicación. |
| Productos antiguos sin baseline | Diagnosticar y preparar regularización con **aprobación explícita por producto**. No emitir movimientos ni modificar históricos automáticamente. |
| Demo | Añadir código específico estable al 403 existente, conservando bloqueo y contratos de otros errores. |
| Entregas | Pequeñas, con pruebas y cierre por tema. Sin commit, push, PR, publicación ni despliegue automáticos. |

No quedan preguntas de producto indispensables para este alcance. Las decisiones técnicas ordinarias se resuelven con el código vigente, las invariantes y pruebas; no requieren volver a consultar las respuestas ya dadas.

## 2. Cobertura de los ocho pendientes

| ID | Alcance aprobado | Cierre de esta entrega |
|---|---|---|
| I01 | Alta manual con stock inicial mediante writer autoritativo y ledger, atómica | Paridad de saldo con importación, movimiento/autor correctos, rollback completo y ausencia de doble contabilización. |
| I02 | Contrato común del alias/factor, precisión compatible y corrección determinista de alias antiguos | Altas/ediciones e importación consistentes; migración probada en bases aisladas; factores, saldos y snapshots intactos en backfill. |
| B7 | Orden por stock y valor coherente con las columnas mostradas | Comparador usa los mismos helpers que el render; pruebas asc/desc con factor distinto de 1 y sombra legacy divergente. |
| I03 | Resultados con muestra acotada y consulta paginada completa de conflictos | Conteos exactos, detalle estable por ejecución y tenant, memoria/respuesta acotadas; sin modificar decisiones de importación. |
| I04 | Mantener deuda aceptada y límites; sin optimización de locks por volumen | Aplazado. Preservar atomicidad, límites del parser y correcciones de concurrencia existentes; no elevar topes. |
| I05 | Error demo específico dentro del contrato actual | HTTP 403 y código `demo_account_restricted`, o adaptación compatible del código ya existente, con pruebas contra otros errores. |
| I06 | Extensiones de importación | Aplazadas: varias presentaciones por producto, lotes y múltiples orígenes/sucursales. Conservar soporte manual ya existente. |
| I07 | Diagnóstico y propuesta de regularización por producto | Herramienta o procedimiento de diagnóstico sin escrituras de dominio, manifiesto mínimo y pruebas sintéticas. Ejecución real y cierre histórico quedan pendientes de aprobación individual. |

Las deudas I03/I04/I05 eran aceptadas en p61: el usuario ahora autoriza abordar I03/I05; esto no convierte I04 ni I06 en requisitos de implementación.

## 3. Evidencia de partida que debe revalidar el ejecutor

Inspección estática local del 30-10-2026. Se priorizó el grafo y se contrastaron archivos cuando sus fragmentos/rangos no bastaban. No se consultó la base habitual ni se ejecutó la aplicación para este plan.

| Fuente | Observación | Implicación |
|---|---|---|
| `backend/apps/inventory/serializers.py::ProductSerializer.create` | Dentro de `atomic`, crea producto/presentación y asigna directamente `Product.stock_quantity = stock × cf`; no crea el movimiento inicial. | Cerrar I01 sin repetir el saldo ya asignado antes de llamar al writer. |
| `PresentationCreateSerializer`, `PresentationSerializer` y modelo `Presentation` | No hay normalización común de ambos nombres. `quantity` tiene 2 decimales y factor 4. | No basta `quantity = factor`: una asignación podría perder precisión. Diseñar ampliación compatible, validadores y transición. |
| `backend/apps/inventory/units.py` | Ya valida factores finitos/positivos y convierte unidades. | Reutilizar y extender donde corresponda; no introducir helpers paralelos con reglas distintas. |
| `backend/apps/inventory/services.py::apply_stock_movement` | Writer de stock en unidades base, lock interno de Product, dual-write legacy, ledger y hook de notificaciones. `adjustment` a nivel producto es saldo absoluto; por lote cambia el agregado por delta. | Mantener semántica y orden de locks. Nunca usar `in` y `adjustment` como si fueran equivalentes. |
| `backend/apps/imports/services_inventory.py` | Crea desde stock cero y aplica entrada inicial con motivo/autor; `quantity == cf`. Una fila por producto/presentación; dedup skip. | Mantener p61 y compartir las invariantes de creación, sin reimplementar todo el importador. |
| `test_inventory_import.py::test_stock_parity_manual_vs_import` | Actualmente fija deliberadamente alias manual 1 frente a factor 3 y ausencia de movimiento manual como deuda conocida. | Actualizar esas expectativas al contrato nuevo y aumentar evidencia; no conservar el defecto para que pase el test ni eliminar el gate. |
| `frontend/src/pages/inventory.jsx` y `frontend/src/utils/inventory.js` | El render usa `productStockQty`/`productStockValue`; el sort lee stock legacy y precio por stock de presentación. | Unificar fuente. Precio × stock de presentación puede coincidir con la columna si la sombra está sincronizada; el defecto no es una multiplicación siempre incorrecta, sino la divergencia de fuente/contrato. |
| `backend/apps/imports/services.py::_append_conflict` | Incrementa agregados exactos y añade todos los conflictos al array. El serializer expone `result`. | Limitar también la acumulación/respuesta, conservando detalle completo en un almacenamiento de reporte consultable. |
| `imports/services.py::commit_job` y `imports/views.py` | Hay cambios locales recientes que releen/bloquean el job, confirman una sola vez y coordinan mapping/validate. | Preservarlos y sus pruebas; no sustituir el servicio por una versión anterior del grafo/documentación. |
| `imports/parsers.py` | Límites 5 MB, 2000 filas y 50 columnas, con lectura perezosa añadida recientemente; XLSX tiene límites documentados propios. | Conservar las defensas actuales. Esta tarea no elimina toda limitación del parser ni autoriza subir topes. |
| `core/permissions.py::NotDemoAccount` | Ya declara `demo_account_restricted`; el problema documentado es su normalización a error genérico. | Arreglar la propagación acotadamente, no crear un segundo permiso ni hacer públicos todos los códigos internos. |
| `inventory/management/commands/audit_stock_integrity.py` | Reconciliación desde último adjustment base; `no_baseline` no equivale a drift. Comprueba además suma de lotes. | El nuevo movimiento inicial `in` no se convierte automáticamente en baseline según ese algoritmo. No insertar ajustes históricos para conseguir un informe verde. |
| `docs/modules/inventory.md` y código de orden 2 | Ledger protegido, consumos e histórico conservados. | Mantener PROTECT, archivo sin movimientos y defensas clínicas/financieras. No reabrir el borrado. |

## 4. Invariantes de unidades y creación

### 4.1 Unidad autoritativa

`Product.stock_quantity` y `Product.min_stock` se expresan en unidades base. Una unidad comercial contiene `conversion_factor` unidades base. La entrada inicial y mínimo capturados en unidades de presentación se convierten una sola vez; no multiplicar en frontend y backend sin contrato explícito. Ejemplo: 2 cajas, factor 12 → 24 unidades base, no 2 ni 288.

Usar Decimal en backend, cantidades finitas, factor positivo y rangos reales del modelo. Conservar la cuantización del writer a 4 decimales y validar antes de escribir los casos fuera de rango. La sombra `Presentation.stock` es compatibilidad, no otra fuente de saldo ni un inventario independiente por formato. No sumar sombras de varias presentaciones para reconstruir el saldo actual.

`quantity` es alias del factor; no es existencia ni cantidad de una receta/factura. El contrato se aplica exclusivamente a `Presentation.quantity`, no a todos los campos llamados quantity. Consumidores de billing, consulta, recepción y snapshots deben seguir interpretando sus cantidades actuales.

### 4.2 Normalización de entradas y precisión

- Analizar presencia real de campos antes de defaults. En alta: solo factor → ambos al factor; solo alias → ambos al alias; ambos iguales → aceptar; distintos → 400 con error de campo; ninguno → ambos 1. Rechazar cero, negativos, NaN, infinitos, nulos/valores inválidos y precisión no admitida sin sustituirlos silenciosamente por 1.
- En PATCH: ninguno → conservar valores; uno explícito → normalizar el par; ambos contradictorios → rechazar. La modificación del factor comercial continúa sujeta a los guards y reglas vigentes: no se autoriza alterar retrospectivamente movimientos ni snapshots. No convertir el backfill de alias en una operación de cambio de factor.
- Inventariar escritores reales: alta de producto, alta/edición de presentación, nested serializer, importador, admin y servicios/fixtures pertinentes. Una normalización solo en el primer endpoint no cierra I02. Mantener checks de tenant, permisos y unidades.
- Ampliar `quantity` para representar exactamente todos los factores válidos, preservando capacidad entera previa cuando corresponda. Un posible diseño es 12 dígitos/4 decimales, sujeto a verificar tipos/rangos y consumidores; no reducir sin diagnóstico el campo a 10/4 perdiendo capacidad entera legacy. La precisión de sombras y stock autoritativo son temas distintos; no aumentar o redondear saldos indiscriminadamente.
- Preparar migración nueva de schema y después backfill **solo de quantity desde un factor válido**. No reejecutar ni editar la migración 0018 para regenerar stock. Hacer preflight, contar casos y detener/reportar factores inválidos sin adivinarlos. La corrección es idempotente; documentar antes/después sin datos sensibles.
- Probar que factor, base_unit, stock, mínimo, precios, lotes, ledger y snapshots de documentos no cambian por ese backfill. No utilizar `save()` que dispare efectos no deseados para una corrección de alias. Si se agrega constraint de igualdad, aplicarla después de migrar escritores/datos y probar todos los caminos; no deshabilitar constraints para pasar pruebas.

La precisión depende de dígitos totales y escala, como describen [DecimalField de Django](https://docs.djangoproject.com/en/6.0/ref/models/fields/#decimalfield) y [numeric de PostgreSQL](https://www.postgresql.org/docs/current/datatype-numeric.html). Verificar la versión real del entorno; estas fuentes no prueban que una migración local ya se haya aplicado.

### 4.3 Stock inicial manual

Crear Product y Presentation con saldo cero; preparar metadatos/unidad/mínimo y registrar **una sola entrada positiva** mediante `apply_stock_movement` dentro de la misma transacción. No conservar la asignación inicial directa y sumar encima. Pasar organización y actor desde contexto confiable; no depender solo de thread-local ni aceptar el autor del payload. Conservar código interno autogenerado, validación de precios/barcodes y resultado coherente tras refrescar objetos.

Para stock cero no inventar una entrada positiva ni un ajuste histórico. Documentar si no se emite movimiento por no existir cambio; no confundirlo con una apertura auditada. Con stock positivo, el motivo debe distinguir alta manual de importación. La procedencia humana legible no sustituye por sí sola una prueba estructural del estado inicial.

Si falla movimiento, validación o persistencia, se revierten producto, presentación y saldo: nunca éxito con catálogo a medias en esa operación. Evitar dobles movimientos por signals, normalización repetida o extracción de helpers. Mantener los savepoints/atomicidad del importador y el 409 de un job ya confirmado. Esto no añade por sí solo idempotencia global a POST de catálogo ni fusiona altas distintas.

Los productos con `tracks_lots` conservan recepción mediante el flujo manual de lotes ya existente. No admitir stock inicial positivo sin lotes identificados ni duplicar el stock entre alta y recepción. El wizard actual crea con cero y llama después a recepción: varias peticiones no son una única transacción. Mantener resultado parcial honesto ante fallo de recepción y permitir corregirlo sin recrear/doblar stock; no borrar automáticamente producto o ledger para simular rollback entre peticiones. No se incluye importación de lotes por este trabajo.

## 5. B7 — Orden coherente con lo mostrado

Usar `productStockQty` para columna/orden de stock y `productStockValue` para columna/orden de valor. Mantener filtros, dirección, empates estables, valores ausentes según helper y demás columnas. No cambiar de valor comercial a costo contable ni modificar precios para arreglar el orden.

Caso que debe fallar antes de la corrección: A con stock base 12, factor 12 y precio 120, pero sombra legacy 12 → valor mostrado 120 y comparador antiguo 1440; B con stock base 6, factor 1 y precio 50, sombra 6 → valor 300. Ascendente debe mostrar A y después B. Añadir caso con sombras coherentes, cero y dirección descendente. Probar también stock base frente a sombra, sin tratar cifras de unidades distintas como intercambiables.

## 6. I03 — Conflictos acotados y detalle completo

### 6.1 Contrato propuesto

- Mantener `result.conflicts` como muestra con máximo **100** entradas. Agregados exactos para total/high/uncertain; metadatos aditivos de muestra, truncamiento y versión de reporte. `conflicts_high + conflicts_uncertain == skipped_conflicts` sigue vigente. No calcular totales con `.length` ni usar el tamaño de la muestra para decidir commit o filas omitidas.
- Consulta paginada del detalle completo por job y versión de reporte, por ejemplo acción `GET /api/imports/<public_id>/conflicts/`, siguiendo convenciones vigentes. Página por defecto 50, máximo 100; orden estable por número de fila y ordinal del conflicto. Publicar contrato exacto en ADR/API. La primera página devuelve versión; las siguientes la fijan. No aceptar tamaños arbitrarios ni un `all=true` que reconstruya el payload completo.
- Mantener clasificación, reglas skip, errores bloqueantes y dedup de owner_pet/inventory. No introducir update/create_anyway, normalización distinta de identidad ni efectos en stock para mejorar contadores.
- Mostrar «Mostrando N de M» y acceso real a páginas completas tanto en preview como resultado final. Conservar grupos high/uncertain y sus totales aunque una muestra no incluya ambos. No romper el CSV de errores/avisos existente ni presentarlo como descarga completa de conflictos si no lo es. La descarga nueva no es requisito: el usuario eligió paginación.

### 6.2 Persistencia, estabilidad y compatibilidad

Conservar detalles mínimos del reporte de cada ejecución, no recalcularlos contra un catálogo que cambió. Se admite una tabla de detalles vinculada al ImportJob/revisión, u otra estructura equivalente justificada en ADR. Es infraestructura del importador existente: no un segundo importador ni un sistema genérico de reportes. Acotar campos, almacenamiento por fila y escritura por lotes; un array completo construido en memoria y cortado justo antes del Response no resuelve I03.

La persistencia de metadatos/resultados de validate ya existe. Se permiten detalles de reporte dentro de esa misma transición; **el dry-run no crea ni modifica Product, Presentation, stock, lotes, Owner/Pet ni ledger**. No afirmar que el endpoint validate no escribe absolutamente nada: guarda estado/resultados del job. Conservar la posibilidad de probar el cálculo de validación sin escrituras de dominio.

Mapping, revalidate y commit producen versiones coherentes. Evitar mezclar páginas de preview y commit o del mapping anterior: invalidar cursores/versiones antiguas con error de conflicto y actualización explícita, o servir snapshots inmutables retenidos según una política documentada. Elegir y probar una sola semántica; por defecto invalidar con 409 al reemplazar el reporte vigente. La publicación de versión, detalle y agregados debe ser atómica. No permitir que una validación tardía pise el resultado committed ni duplicar importaciones.

Migrar resultados antiguos desde su contenido persistido con procesamiento acotado, sin volver a validar/importar ni cambiar estado, conteos, decisiones o saldo. Si un detalle histórico ya no existe, declararlo incompleto; nunca reconstruirlo como evidencia original contra el catálogo actual. No truncar JSON antiguo hasta asegurar que su detalle completo queda disponible, o mantener la compatibilidad legacy visible hasta su conversión controlada. Mantener rollback/lectura compatibles con ambos formatos durante la transición.

Autorización: misma organización y permiso de lectura del importador, public_id, guards de demo/organización desactivada y demás controles vigentes. Validar job, versión y cursor del lado servidor. Cross-tenant 404 sin totales, nombres o UUID filtrados; no exponer PK internos. Detalles de owner_pet pueden contener PII: mínimos necesarios, sin logs de filas completas, sin exportar datos reales a fixtures y con ciclo de vida ligado al job. No cambiar políticas globales de privacidad o retención por este trabajo.

## 7. I07 — Preparar regularización, sin aplicarla automáticamente

El resultado `no_baseline` expresa falta de cobertura del algoritmo, no saldo erróneo. Registrar una entrada inicial corrige trazabilidad futura, pero el auditor actual busca un adjustment y puede seguir reportándola como `no_baseline`. Mantener ambas afirmaciones separadas. No crear ajustes masivos, sumar stock otra vez ni cambiar el auditor para que ignore casos difíciles.

Entregar diagnóstico clasificado: baseline absoluto de producto verificable; sin baseline; ledger legacy/unidades mixtas; movimientos sin referencia suficiente; productos con lotes; inconsistencias de lotes; cobertura no comprobable. Revisar mediante fixtures la distinción entre adjustment absoluto de producto y ajuste por lote: el saldo final de un lote no es automáticamente el saldo inicial de todo el producto. Si la evidencia no permite reconstruir un delta, marcar la limitación. No afirmar reconciliación integral por comprobar solo `sum(lotes) == stock`.

Preparar por producto una propuesta con organización/public_id, saldo base observado, unidad, presentaciones, watermark/revisión del ledger, cobertura, inconsistencias, acción propuesta, efectos esperados y campos de aprobación/actor/fecha/motivo. El reporte por defecto es sin escrituras. No consulta ni opera la base habitual por esta implementación; demostrarlo con fixtures aislados. Documentar la invocación posterior que requerirá autorización para datos reales.

Una apertura futura debe identificar expresamente que es **regularización/reconstrucción desde el saldo observado**, no certificación del pasado. No puede ser una entrada que vuelva a sumar ese saldo. Debe revalidar saldo, movimientos, organización y lotes bajo la transacción/locks apropiados; cambios desde la propuesta invalidan la aprobación y exigen nueva revisión. No reparar drift, lotes faltantes ni datos ambiguos de oficio. Debe ser repetible sin duplicar apertura y conservar aprobación individual. El usuario no ha autorizado ejecutar ninguna de estas aperturas en datos existentes.

En esta entrega se exige el diagnóstico y el diseño verificable de ese procedimiento, con casos sintéticos; no una API operativa de regularización ni un comando apply habilitado por defecto. Si se implementa alguna primitiva de preparación, debe quedar inerte para aplicar sin nueva autorización concreta. No poner una regularización de stock en `RunPython`, post_migrate, seed o deploy. Esta restricción no impide preparar el backfill separado de **alias** aprobado en I02.

## 8. I05 — Código demo estable

Propagar el código ya definido `demo_account_restricted` en la respuesta normalizada 403 de importación, conservando mensaje/envelope esperados. Evitar una modificación global que exponga arbitrariamente códigos o cambie otras denegaciones. Mantener `NotDemoAccount` autoritativo y probar llamadas directas a API, no solo ocultar botones. Revisar consumidores compartidos del permiso (incluido cambio de contraseña demo) antes de elegir una adaptación; preservar sus contratos fuera del alcance aprobado.

No convertir cuenta demo en un permiso de importación, no retirar RBAC/throttles ni asumir que ADMIN_SAAS sin organización tiene un tenant implícito. Probar no autenticado, no ADMIN, demo, clínica real y acceso a job de otra clínica con sus respuestas vigentes.

## 9. Entregas de implementación

| Entrega | Contenido | Criterio de cierre |
|---|---|---|
| E0 — Línea base y ADR | Revisiones/cambios existentes, impacto en writers/readers, contrato de alias/reportes y mapa de ocho IDs | Revalidación estática y entorno aislado definido; sin presentar deudas documentadas como incidente actual. |
| E1 — B7 | Sustituir fuentes del comparador por helpers del render | Casos asc/desc y sombra divergente; sin cambios de valoración o rediseño. |
| E2 — I02 | Normalización común, precisión, migración de schema/alias y pruebas de todos los writers relevantes | Par correcto en API/imports; contradicciones 400; alias antiguos corregibles sin cambios en saldos/factores/snapshots. |
| E3 — I01 | Alta manual con writer y entrada inicial atómica; paridad con imports | Dos cajas × 12 = 24 una sola vez; actor/procedencia; rollback; cero y lotes tratados honestamente. |
| E4 — I03 | Reporte completo versionado, muestra acotada, endpoint paginado y wizard | Detalle accesible sin pérdida, totales exactos, versiones coherentes y aislamiento; decisiones de importación conservadas. |
| E5 — I05 / I07 | Código demo y diagnóstico/propuesta de regularización por producto | 403 específico sin regresiones; diagnóstico sin escrituras y regularización real pendiente de aprobación. |
| E6 — Integración y expediente | Suites pertinentes, migraciones fresh/upgrade, documentación y rollback | Evidencia reproducible del alcance local; I04/I06 siguen aplazados; no afirmar regularización real ni despliegue. |

E1 puede entregarse temprano sin esperar el diseño de datos. E2/E3 deben coordinarse para compartir reglas y evitar writers divergentes. No bloquear el trabajo local por el VPS o por aprobaciones de regularización que todavía no se van a ejecutar.

## 10. Pruebas y aislamiento

- Crear/verificar una base y configuración de pruebas explícitamente aisladas, con allowlist de host/puerto/nombre y credenciales de prueba sin publicarlas. No heredar ciegamente `.env` ni usar la base habitual. Probar migraciones en base fresca y actualización desde el estado previo compatible, solo con datos sintéticos. No instalar/actualizar dependencias para remediar otro orden.
- I02: factor solo, alias solo, ambos iguales/contradictorios, ninguno en alta/PATCH; fracciones como 0.125 y 1.2345, límites, inválidos y redondeo. Guardar/recargar desde PostgreSQL para detectar pérdidas de escala. Verificar invariantes de backfill con before/after de campos pertinentes y segunda ejecución sin cambios; snapshots cerrados permanecen idénticos.
- I01: alta manual/import equivalente con factor 1, 3, 12 y fraccionario válido; cantidad/min_stock; saldo base y ledger correctos; actor explícito; cero, errores y rollback total. Simular fallo del writer después de crear catálogo y confirmar ausencia de restos. Preservar recepción de lotes y fallo parcial entre peticiones sin duplicación.
- B7: ordenar la misma lista mostrada, asc/desc, sombra divergente y coherente, valores ausentes y cero; stock base/valor usan helpers. No cambiar la política monetaria de otros módulos.
- I03: 0, 100, 101 y 2000 conflictos, ambos niveles de confianza, varias páginas, tamaño inválido/excesivo, sin duplicados/omisiones entre páginas y totales correctos. Cambiar catálogo después no reescribe el reporte. Probar mapping/revalidate/commit, cursor de otra versión/job/tenant, reporte antiguo y rollback de publicación fallida. Comparar decisiones y conteos owner_pet/inventory con el contrato previo salvo cambios aditivos/muestra acordados.
- Concurrencia PostgreSQL real: dos commit del mismo job producen un solo efecto; validate/mapping contra commit no rehabilitan el job; páginas no mezclan versiones. Preservar `test_import_commit_concurrency.py`, `test_parser_streaming_caps.py` y cambios de conservación/organización desactivada de orden 2. Los locks requieren pruebas transaccionales reales, como distingue [Django para select_for_update](https://docs.djangoproject.com/en/6.0/ref/models/querysets/#select-for-update); SQLite o solo mocks no los acreditan.
- I05: mismo bloqueo 403, código concreto y otros errores inalterados. I07: diagnóstico sin modificaciones y propuestas aprobadas/obsoletas/ambiguas simuladas, sin aplicar en datos reales ni afirmar histórico reconciliado a partir de una apertura nueva.
- Regresión de stock/consumo, recepción, movimientos y auditoría aplicable; checkout/documentos tocados por dependencias de unidades. Ejecutar checks, drift de migraciones y ratchets del proyecto pertinentes. Frontend: tests dirigidos del helper/página/wizard, lint de archivos tocados y build; no convertirlo en limpieza global de lint. Verificación visual local del orden y paginación si hay UI.
- Mantener topes de parser y una transacción por job con savepoints de fila. No paginar el **commit** ni introducir commits por lote para resolver paginación de **lectura**. I04 no autoriza benchmarks amplios, subir MAX_ROWS o rediseñar workers.
- Procesos propios en loopback/puertos libres, efectos externos desactivados. No detener servidores ajenos, conectar VPS, restaurar dumps reales ni ejecutar campañas B9/D29 o escaneos nuevos. Registrar comandos/entorno/revisión/resultados, límites y fallos previos separados de regresiones.

## 11. Migraciones, entrega y estado final

Crear migraciones nuevas sobre las hojas reales del repositorio y conservar cambios existentes. Secuencia: schema compatible, writers/lectores, backfill de alias validado y constraints si proceden; reportes antiguos conservados hasta disponer de detalle completo. No editar migraciones históricas aplicadas ni usar fake, flush o desactivar constraints. El rollback de datos debe preservar evidencia: no borrar movimientos ni restaurar aliases incorrectos indiscriminadamente; una reducción de precisión puede ser irreversible para valores nuevos y debe quedar documentada.

El ejecutor creará `docs/remediaciones/orden-4/` con:

- `README.md`: alcance, revisiones, cambios y estado local.
- `DECISIONES.md`: ADR de unidades, creación y reportes; compatibilidad y límites.
- `MATRIZ.md`: ocho IDs, evidencia, cierre local, preparación o aplazamiento.
- `EVIDENCIA.md`: pruebas/comandos/migraciones, fixtures y limitaciones.
- `REGULARIZACION-PROPUESTA.md`: diagnóstico, esquema de propuesta por producto y condiciones de aprobación futura; ninguna aprobación inventada.
- `APLICACION-Y-ROLLBACK.md`: pasos revisables de aplicación posterior, orden de migraciones, compatibilidad y rollback; sin ejecutarlos en habitual/VPS.

Actualizar módulos de inventario/imports y añadir referencia posterior a los ADR p31/p61 sin reescribir recibos históricos. Un test antiguo que fija la deuda debe cambiar explícitamente a la nueva expectativa, manteniendo cobertura.

I01/I02/B7/I03/I05 podrán declararse **IMPLEMENTADOS_Y_VERIFICADOS_LOCALMENTE** únicamente con evidencia suficiente. I07 quedará **PREPARADO_PENDIENTE_DE_APROBACION_POR_PRODUCTO**; I04/I06 **APLAZADOS_POR_ALCANCE**. Una migración probada aisladamente no está aplicada en la base habitual o producción. El cierre del alcance local no certifica saldos históricos ni cierra el orden 4 íntegro sin esas salvedades.
