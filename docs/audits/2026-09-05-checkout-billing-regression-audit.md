# Auditoría de regresiones Checkout / Billing / Dispensación

**Fecha:** 2026-09-05; implementación y validación cerradas el 2026-09-06

**Estado:** diagnóstico y plan escritos antes de implementar; remediación
estructural aplicada y validada sobre PostgreSQL
**Alcance:** Billing, Checkout, Invoice, Prescription, Inventory, lotes, Cash, Analytics y frontend de Cobros

## 1. Executive Summary

Los dos fallos tienen una causa común de proceso: el rediseño cambió contratos
autoritativos sin instalar gates que compararan esos contratos con sus
representaciones materiales.

El 500 de `POST /api/billing/checkouts/{id}/pay/` no nace en readiness ni en
`post_checkout`. El modelo y el estado de migrations ya no conocen
`confirmed_at_source`, pero la base PostgreSQL local conserva la columna como
`NOT NULL` y sin default. La divergencia se produjo al retirar del árbol una
migration previamente aplicada (`0026_checkout_checkoutitem_commandreceipt_and_more`),
generar otra `0026` distinta desde `0025`, registrar esta segunda rama sin ejecutar
todas sus operaciones de base y usar luego `0032_reconcile_checkout_schema`, que
sólo crea tablas/campos faltantes. `0032` no elimina columnas sobrantes ni instala
constraints/índices ausentes. La evidencia física revela además tres índices UNIQUE
idempotentes ausentes y el índice de `posted_at` ausente.

El caso real de “máx 0” no estaba agotado ni doblemente surtido. La receta prescribe
`2 tabletas` y la única presentación activa es una caja de `100 tabletas`.
`floor(2 / 100) = 0` coincide con la intención actual de UI/ADR de vender
presentaciones comerciales completas, pero esa indivisibilidad no estaba impuesta
por backend: hoy un caller interno puede enviar `0.02` cajas. Por tanto el cero
observado no se cambiará artificialmente; se hará explícita y ejecutable la
granularidad comercial. El problema estructural es que la API entrega magnitudes ambiguas, omite fulfillment
histórico, publica `Presentation.stock` legacy y obliga al frontend a reconstruir
cap clínico, conversión y disponibilidad. La UI presenta una presentación no
elegible como si fuera seleccionable y sólo muestra “máx 0”, sin explicar que el
catálogo comercial no tiene un formato compatible.

La remediación implementada instala: (P0) puente ejecutable para la `0026`
huérfana y migrations forward de expand/verify/contract; (P0) reparación de
provenance y constraints físicos; (P0) contrato de Presentation indivisible,
factor positivo y snapshots inmutables de conversión; (P0) proyección autoritativa
backend de capacidad **adicional**, con cap legal, redelivery, demanda preparada y
stock multilote separados; (P0) cierre de TOCTOU, RBAC, versionado e idempotencia
de dispensación; (P1) gate de schema por firmas y tests PostgreSQL de upgrade/DB
limpia/concurrencia; (P2) retiro de nombres `confirmed` del runtime y aislamiento
explícito de campos legacy.

## 2. Error 1 — Root cause

### Reproducción

Sobre la PostgreSQL local, un Checkout directo abierto (`checkout_id=2`,
`version=2`, total `400.00`) fue enviado al endpoint real mediante `APIClient`, con
usuario ADMIN e idempotency key fija. La autorización llegó a
`RBAC_ALLOWED_DB`. La traza siguió:

```text
pay_checkout_view
  -> _post_checkout_response
  -> post_checkout (transaction.atomic)
  -> Invoice.objects.create (checkout_services.py:1562)
  -> Invoice.save (models.py:164)
  -> PostgreSQL INSERT
  -> psycopg.errors.NotNullViolation
```

Error PostgreSQL reproducido:

```text
el valor nulo en la columna «confirmed_at_source» de la relación
«billing_invoice» viola la restricción «not-null»
```

La API devolvió `500 server_error`. Al fallar dentro de la transacción atómica no
quedaron Invoice, Payment, movimientos de stock ni receipt parciales.

### Cadena causal demostrada

1. `Invoice` actual sólo admite `posted/paid/voided` y no define
   `confirmed_at`/`confirmed_at_source`.
2. La segunda migration `0026_checkout_checkoutestimate_checkoutevent_checkoutitem_and_more`
   elimina ambos campos, retira `idx_inv_org_status_conf` y crea
   `idx_inv_org_status_post`.
3. `django_migrations` contiene dos nombres diferentes con prefijo `0026`:
   - `0026_checkout_checkoutitem_commandreceipt_and_more`, aplicada
     2026-09-03 11:08:54-06;
   - `0026_checkout_checkoutestimate_checkoutevent_checkoutitem_and_more`,
     registrada 2026-09-05 14:06:20.906-06.
4. El archivo fuente de la primera ya no existe, pero su `.pyc` sobreviviente fue
   cargado y renderizado con `MigrationWriter`: creaba Checkout, CheckoutItem,
   CommandReceipt y ReplacementWaiver, añadía `posted_at` y cambiaba statuses,
   pero **no eliminaba** `confirmed_at` ni `confirmed_at_source`.
5. La segunda `0026` parte otra vez de `0025` y vuelve a crear tablas que la
   primera ya había materializado. Su ejecución normal contra esa base habría
   chocado con relaciones existentes. Aun así fue registrada junto con
   `0027`–`0030` en milisegundos y sus operaciones de eliminación/índices no están
   en PostgreSQL.
6. `0032_reconcile_checkout_schema` agregó tablas y columnas faltantes, pero por
   diseño no compara ni corrige extras, constraints o índices de tablas existentes.

### ¿Cómo creyó Django que la nueva `0026` estaba aplicada?

Django considera aplicada una migration por el par `(app, name)` en
`django_migrations`; no verifica que cada DDL haya ocurrido. La evidencia prueba
que el registro de la segunda `0026` se hizo sin ejecutar sus operaciones físicas
completas: fue una aplicación **fake-like**. `migrate --fake`, una escritura directa
con `MigrationRecorder` o SQL sobre `django_migrations` producen exactamente ese
estado.

No existe evidencia retenida para distinguir cuál de esos tres mecanismos se usó:
el repositorio no contiene script de reconciliación/fake, el historial PowerShell
disponible no conserva el comando, PostgreSQL tiene `log_statement=none` y no está
cargado `pg_stat_statements`. Por tanto no se atribuye un comando o actor sin
prueba. Lo exacto y demostrable es: **las operaciones de DB fueron omitidas y luego
la reconciliación aditiva ocultó parcialmente el fallo**. La falta de auditoría del
procedimiento de migrations es a su vez un hallazgo P1.

## 3. Schema drift encontrado

`makemigrations --check --dry-run` devuelve “No changes detected”: el estado Django
sí coincide con los modelos. La comparación directa contra `pg_catalog` produce:

| Campo/constraint | Modelo actual | Migration state | DB física | Divergencia |
|---|---|---|---|---|
| `status` | `posted/paid/voided` | alterado en nueva `0026` | columna actual; 94 paid, 39 posted, 2 voided | No hay status legacy en datos |
| `invoice_type` | `consultation/direct_sale` | vigente | vigente | No; representa origen, no lifecycle |
| `posted_at` | nullable en campo + CHECK requerido | añadido/norm. en `0026` | presente, 0 nulos | No |
| `posted_at_source` | vigente | añadido en `0026` | presente | No estructural; provenance local quedó `service` |
| `confirmed_at` | ausente | `RemoveField` en `0026` | presente, nullable; 101/135 filas con valor | Columna legacy extra |
| `confirmed_at_source` | ausente | `RemoveField` en `0026` | presente, `NOT NULL`, sin default | **Crítica: bloquea INSERT actual** |
| `paid_at` / source | vigentes | vigentes | presentes + CHECK paid | No |
| `voided_at` / source | vigentes | rename en `0031` | presentes + CHECK voided | No funcional; el nombre interno del NOT NULL aún contiene `cancelled` |
| `cancelled_at` / source | ausentes | renombrados en `0031` | ausentes | No |
| CHECK confirmed/cancelled | ausentes | retirados | ausentes | No |
| `invoice_posted_at_required` | vigente | añadido | presente | No |
| `idx_inv_org_status_conf` | ausente | retirado | presente | Índice legacy extra |
| `idx_inv_org_status_post` | vigente | añadido | ausente | Índice actual faltante |
| índices paid/void/created | vigentes | vigentes | presentes | No |

La auditoría de todos los modelos Billing encontró además tres contratos de
idempotencia presentes en state pero ausentes físicamente:

```text
payment_unique_child_per_command_receipt
refundpayment_unique_child_per_command_receipt
refundreversal_unique_child_per_command_receipt
```

El preflight de datos no encontró duplicados que impidan crearlos. El único record
de migration sin archivo es la primera `0026`. No hay archivos del árbol actual sin
record.

## 4. Error 2 — Root cause

### Caso real capturado

```text
Checkout public_id: 218b71b4-427c-469a-9518-344f7d5fd2f2
PrescriptionItem: Amoxicilina 250 mg
prescribed: 2.00 tabletas base
fulfilled events: 0
selected en checkout: 0
Product.stock_quantity: 200 tabletas base
tracks_lots: false
presentación activa: Caja con 100 tabletas
conversion_factor: 100 base/presentación
Presentation.stock legacy: 2
floor((2 - 0 - 0) / 100) = 0 presentaciones completas
```

En este caso se descartan las hipótesis de fulfillment total, doble descuento,
falta de stock y lotes. El `0` es matemáticamente válido. La falla es contractual y
de UX: no hay formato vendible compatible con dos tabletas, pero backend/frontend
no lo expresan como tal.

Existe un segundo defecto independiente en el mismo contrato:
`CheckoutSerializer.get_prescription_suggestions` llama `dispensed_quantity` a la
suma seleccionada en el Checkout actual y nunca resta
`PrescriptionFulfillmentEvent.quantity_delta`. Un Checkout suplementario puede
mostrar un remanente mayor al legal. El comando de escritura y `post_checkout` sí
revalidan events + líneas, por lo que el backend terminaría rechazando tarde una
cantidad que la propia API sugirió.

También se devuelve `Presentation.stock`. Ese campo es una proyección legacy que
sólo se actualiza para la presentación usada en cada movimiento, mientras
`Product.stock_quantity` es común a todas las presentaciones. En la base ya existe
un caso stale (`Jeringa 60ml`: 440 base, factor 100, 4 presentaciones calculadas,
`Presentation.stock=0`). Billing no puede usarlo como autoridad.

## 5. Contrato real de unidades

| Campo/magnitud | Unidad real comprobada | Writer/reader autoritativo |
|---|---|---|
| `PrescriptionItem.quantity` | unidades base del `Product` | formulario prescribe por Product; ADR p31/p37; cap backend |
| `PrescriptionFulfillmentEvent.quantity_delta` | unidades base que consumen cap legal | se crea al post exitoso |
| `PrescriptionFulfillmentEvent.physical_quantity` | unidades base físicamente entregadas/devueltas | ledger físico/Rx |
| `CheckoutPrescriptionSelection.selected_quantity` | **no existe** | cantidad seleccionada se deriva de CheckoutItems activos |
| `CheckoutPrescriptionSelection.eligible_remaining_at_open` | unidades base | snapshot al abrir selección/suplemento |
| `CheckoutItem.quantity` con Presentation | unidades de presentación comercial | precio por presentación; write service multiplica por factor |
| `InvoiceItem.quantity` retail | unidades de presentación comercial, snapshot | copia desde CheckoutItem |
| `Presentation.conversion_factor` | unidades base por una presentación comercial | contrato de inventario p31 |
| `Presentation.quantity` | duplicado legacy de `conversion_factor` | no debe gobernar Billing |
| `Product.stock_quantity` | unidades base agregadas; autoridad de stock | `apply_stock_movement` bajo lock |
| `StockLot.quantity_on_hand` | unidades base del lote | `apply_stock_movement` bajo lock |
| `Presentation.stock` | proyección legacy en presentaciones; potencialmente stale | compatibilidad/display, no Billing |
| `StockAllocation.quantity_base` | unidades base committed | post de Invoice |
| `StockDispositionEvent.quantity_base/stock_delta` | unidades base | post/return/disposition |

Respuesta explícita: la receta está expresada en unidades base del producto, no en
dosis clínicas ni paquetes comerciales. El frontend actual divide magnitudes
compatibles (`remaining_base / base_per_presentation`), pero lo hace sin conocer
fulfillment histórico ni stock autoritativo y sin explicar el caso de formato
incompatible.

Hay una divergencia documental que debe corregirse: ADR p62 §3.5 dice que
CheckoutItem conserva `requested_quantity` en base, pero ese campo no existe y los
writers/readers reales usan `CheckoutItem.quantity` en presentaciones. Cambiar el
runtime a base rompería precio, InvoiceItem y movimientos; se actualizará la ADR
para reflejar el contrato material vigente y nombrar siempre las proyecciones base.

## 6. Fulfillment model

`PrescriptionFulfillmentEvent` nace dentro de `_settle_stock`, después de crear la
Invoice y consumir stock, todo en la transacción atómica de post/pay. Seleccionar no
crea event; pagar no crea un segundo event separado. Para una entrega inicial:

```text
quantity_delta = physical_quantity =
CheckoutItem.quantity * Presentation.conversion_factor
```

Es append-only por intención y FKs `PROTECT`. Los UNIQUE condicionales impiden un
`dispensed` duplicado por `(invoice_item, kind)` y un return duplicado por
`(credit_note_item, allocation)`. Esta última granularidad es necesaria para
revertir una línea surtida desde varios lotes sin colapsarla en el primer lote.
Return/refund no restaura cap en v1; redelivery probada aporta delta cero.

Restar `fulfilled historical + selected current checkout` es correcto porque son
hechos distintos en momentos distintos. No hay double fulfillment mientras el
event sólo se cree al post. El riesgo detectado no es doble conteo en el writer sino
que el serializer omite el primer término. `eligible_remaining_at_open` es snapshot
de auditoría/request-scope; el live cap siempre debe rederivarse de events bajo lock
al mutar/postear.

## 7. API contract

La API previa entregaba strings ambiguos:

| Campo actual | Significado real actual | Problema |
|---|---|---|
| `prescribed_quantity` | base prescrita | unidad sólo implícita |
| `dispensed_quantity` | base seleccionada en este Checkout | nombre falso; no es fulfillment |
| `remaining_quantity` | prescribed - selected current | omite history |
| `conversion_factor` | base/presentación | unidad implícita y fallback a 1 |
| `stock` | `Presentation.stock` legacy | fuente no autoritativa |

El backend devuelve ahora, desde una única proyección:

```json
{
  "prescribed_quantity_base": "10.0000",
  "fulfilled_quantity_base": "4.0000",
  "selected_quantity_base": "2.0000",
  "legal_remaining_quantity_base": "4.0000",
  "neutral_redelivery_remaining_quantity_base": "0.0000",
  "eligible_remaining_at_open_base": "6.0000",
  "base_unit": "tablet",
  "presentations": [{
    "conversion_factor_base_per_presentation": "1.0000",
    "checkout_stock_demand_quantity_base": "0.0000",
    "available_stock_quantity_base": "2.0000",
    "available_stock_after_checkout_quantity_base": "2.0000",
    "available_stock_quantity_presentations": 2,
    "clinical_max_additional_quantity": 4,
    "stock_max_additional_quantity": 2,
    "max_selectable_quantity": 2,
    "max_selectable_semantics": "additional_presentation_units",
    "blocking_reasons": []
  }]
}
```

Para productos por lote, la proyección usará la suma de lotes FEFO consumibles
(active, no vencidos, saldo positivo) y expondrá el desglose informativo por lote.
No limitará el máximo al primer lote: ADR p62 exige que retail/Rx pueda comprometer
1..N allocations. El Checkout abierto conserva intención —o un override explícito—
y `post_checkout` recalcula el plan bajo locks Product → Lot, revalida cada lote
lockeado y persiste exactamente los movimientos/allocations comprometidos.

`max_selectable_quantity` significa siempre **unidades de presentación adicionales
que pueden agregarse ahora**. Descuenta la demanda física de todas las líneas
activas del mismo Product en el Checkout, incluso retail no-Rx y otras
presentaciones. No descuenta otros Checkouts abiertos porque no existe reserva; el
post continúa siendo el árbitro. La capacidad clínica efectiva suma por separado el
remanente legal y la allowance neutral de redelivery, sin hacer que esta última
consuma el cap de la receta.

Los aliases de compatibilidad, donde se conservan, se derivan de la misma
proyección y no mantienen cálculos paralelos. Frontend presenta
`max_selectable_quantity` y `blocking_reasons`, sin recalcular cap clínico/stock.

## 8. Hallazgos relacionados detectados antes de implementar

- La migration aditiva `0032` acepta divergencia silenciosa de objetos existentes y
  captura `DatabaseError` durante `create_model`; no es un schema gate.
- `conversion_factor` no tiene CHECK `> 0`; tres rutas Billing usan
  `conversion_factor or 1`, lo que oculta cero/null en vez de denunciar catálogo
  inválido. La base auditada no contiene factores nulos/no positivos.
- `Presentation.quantity` y `conversion_factor` son duplicados escribibles. En los
  datos activos auditados coinciden, pero no existe constraint ni writer único.
- `PrescriptionItemSerializer.product_unit` toma la primera Presentation, no
  `Product.base_unit`; la elección es arbitraria aunque los datos locales hoy
  coincidan.
- El formulario de receta busca Presentations, descarta la Presentation elegida y
  envía sólo Product; la etiqueta de `quantity` no muestra persistentemente la
  unidad base seleccionada.
- El selector de lotes silencia errores de carga y no ajusta el máximo al saldo del
  lote elegido.
- `InvoiceSerializer` conserva otra implementación legacy de
  `prescription_suggestions`; duplica la regla anterior aunque Invoice ya es
  inmutable/posteada.
- Analytics runtime ya usaba `posted_at`, pero conservaba un nombre local
  `excluded_confirmed_anchor_missing` y dos fixtures de tests con claves
  `confirmed_at`; era deuda de nomenclatura, no causa del 500. Se corrigió sin
  alterar referencias históricas de migrations.
- Once suites Billing históricas, incluidas dispensación, concurrencia, ledger y
  state machine, aparecen eliminadas en el changeset. Los tests nuevos prueban el
  flujo ideal en una DB creada desde cero, no el upgrade físico divergente.
- La revisión independiente detectó que `replaces` aislado no permite llegar a una
  migration posterior: con sólo la primera `0026`, `0027` intenta alterar
  `CheckoutPrescriptionSelection`, que aún no existe.
- `0032` agregó `posted_at_source='service'` a filas históricas por default de campo;
  esa provenance es falsa y debe repararse desde `confirmed_at*` antes del DROP.
- Billing fuerza hoy un primer lote aunque Inventory ya resuelve FEFO multilote;
  además `lot.is_consumable` se valida antes del lock y no sobre `locked_lot`.
- `PATCH` de una línea Rx sólo exige `invoice.create`, permitiendo aumentar una
  dispensación sin `billing.rx_dispense`.
- `expected_version` se publica como requerido pero runtime permite omitirlo;
  `dispense_prescription` tampoco reclama receipt y un retry duplica líneas/cargo.
- Los parsers manuales admiten payloads no-object, versiones inválidas y Decimal no
  finito que terminan como 500; los comandos críticos requieren serializers.

## 9. Plan de remediación

### P0 — bloquea flujo / integridad

1. **Construir una ruta ejecutable desde la `0026` huérfana.**
   - `replaces` no se usará como si ejecutara DDL. La `0027` recibirá un puente
     database-only, anterior a su `AlterField`, que crea idempotentemente la tabla
     mínima ausente cuando Django haya reconocido la `0026` huérfana como
     replacement. Fresh/current-correct son no-op; old-only puede alcanzar `0032`.
   - Declarar `replaces` sólo junto a este puente y probar el plan real de
     `MigrationLoader` para: fresh, old-only y ambas `0026` registradas/schema
     parcial. No se utilizará `--fake`.
   - Como no hay inventario de otros entornos en el repositorio, cualquier historial
     distinto (por ejemplo new-only con DDL parcial) debe ser detectado por preflight
     y fallar con instrucción operativa; no se asumirá equivalencia.

2. **Converger schema y datos en expand/verify/contract.**
   - Migration expand database-only: preflight de anchors/duplicados; corregir
     `posted_at` y `posted_at_source` desde `confirmed_at/confirmed_at_source` cuando
     esa evidencia exista; usar `fallback` sólo si el anchor realmente deriva de
     `created_at`; preservar writers nuevos demostrables.
   - Crear/verificar `idx_inv_org_status_post` y los tres UNIQUE parciales de hijos
     financieros con definición y predicate exactos. Ante datos incompatibles,
     abortar; nunca deduplicar o rellenar con dummy.
   - Migration contract separada: retirar índice/columnas confirmed sólo después del
     verify. Será explícitamente irreversible/forward-only y tendrá runbook de
     backup, locks/timeouts y evidencia de verificación.

3. **Crear autoridad única de disponibilidad Rx en backend.**
   - Nuevo módulo de dominio para conversión base/presentación, fulfillment live,
     selección actual, stock consumible y máximos.
   - Reusar sus primitivas en serializer y comandos; eliminar fallbacks `factor=1`.
   - Separar `legal_remaining_base`, `neutral_redelivery_remaining_base`,
     `selected_cap_consuming_base`, `checkout_stock_demand_base` y
     `available_stock_after_checkout_base`.
   - `max_selectable` es incremental y usa el mínimo entre capacidad clínica
     efectiva y headroom físico multilote después de toda demanda activa del Product.
   - Reusar la misma primitiva en proyección, selección y cap terminal; replacement
     conserva delta legal cero para redelivery.

4. **Hacer ejecutable el contrato de unidades y cambiar API/frontend.**
   - Adoptar la intención vigente de ADR/UI: Presentation retail/Rx indivisible.
     Rechazar fracciones en todos los writers Billing y volver a validar al post.
   - Elevar `conversion_factor > 0` a P0: preflight, validación Inventory compartida,
     CHECK físico y eliminación de todos los fallbacks `or 1`.
   - Backend devuelve contrato explícito y reason codes.
   - Frontend muestra límites clínico y stock por separado, deshabilita formatos con
     máximo cero y explica “remanente menor que la presentación” o “sin stock/lote”.
   - Frontend deja de leer `Presentation.stock` y de dividir cantidades.

5. **Cerrar las fronteras transaccionales descubiertas.**
   - Replanificar FEFO multilote bajo locks deterministas y revalidar consumibilidad,
     tenant, Product y expiración en la instancia lockeada; persistir 1..N
     allocations vinculadas a los movimientos reales.
   - Exigir `billing.rx_dispense` en el servicio para toda mutación Rx, incluida
     disminución/eliminación (supuesto conservador documentado), no sólo en views.
   - Hacer `expected_version` obligatorio y tipado en pay/post/dispense; missing o
     malformed → 400, stale → 409, replay idéntico antes del guard.
   - Mantener `dispense_prescription` como comando incremental, pero volverlo
     idempotente con receipt y payload canónico; mismo key/diferente payload → 409.

### P1 — evita recurrencia

6. **Schema gate ejecutable y CI.**
   - Management command/test PostgreSQL que compare firmas completas: tipo,
     longitud, precisión/escala, null/default, FK target/actions,
     `pg_get_constraintdef`, `pg_get_indexdef`/predicate; prohibir objetos legacy y
     detectar records sin archivo salvo replacements declarados.
   - Test de migrations desde DB vacía.
   - Test de upgrade desde la primera `0026`/snapshot parcial a latest.

7. **Invariantes de catálogo y unidades.**
   - `PrescriptionItemSerializer` expone `Product.base_unit`.
   - Formulario de receta conserva y muestra la unidad base del Product.
   - Comentarios/nombres/API explicitan `_base` y `_presentation`.

8. **Regresiones y concurrencia.**
   - Tests de full/partial/declined, factor 1 y >1, fulfillment histórico,
     selección actual, stock insuficiente, lotes no consumibles, stock legacy stale,
     doble pay/replay/version conflict y ausencia de fulfillment duplicado.

### P2 — cleanup/deuda relacionada

9. Retirar la segunda implementación de sugerencias en `InvoiceSerializer`.
10. Diseñar deprecación de `Presentation.quantity` y `Presentation.stock`; hasta
   retirarlos quedan marcados explícitamente como legacy y ninguna regla Billing los
   lee.
11. Renombrar residuos `confirmed` en Analytics/tests y actualizar ADR p62 §3.5.
12. Documentar runbook de migrations: prohibido reemplazar archivos aplicados;
    `--fake` requiere ticket, evidencia de DDL equivalente y schema gate verde.

## 10. Tests faltantes

El test que debió fallar antes de una prueba manual era un **upgrade test PostgreSQL
desde el schema real de la primera `0026` hasta latest**, seguido por una comparación
state/physical. Un test sólo desde DB vacía no reproduce una migration eliminada y
regenerada; ambos son necesarios.

Matriz mínima de cantidades:

| Caso | Resultado autoritativo |
|---|---|
| rx 2 base, factor 1, fulfilled 0, stock >=2 | clinical 2, max selectable 2 |
| rx 2 base, factor 3 | clinical additional 0; válido bajo Presentation indivisible, reason `below_presentation_size` |
| rx 10, fulfilled 4 | remaining 6 |
| rx 10, fulfilled 10 | remaining/max 0, `fulfilled` |
| rx 10, fulfilled 4, selected current 2 | remaining 4; no double count |
| clinical 5, stock base 2, factor 1 | stock/max selectable 2 |
| Product stock >0, lot-tracked, cero lotes consumibles | stock/max 0, `no_consumable_lot` |
| lotes consumibles 60 + 40, demanda 100 | max 1 presentación factor 100; 2 allocations al post |
| replacement: legal remaining 0, neutral allowance 2 | max adicional 2; fulfillment delta legal 0 |
| otra línea activa del Product demanda 3 base | stock headroom descuenta 3 aunque no sea Rx |
| `Presentation.stock` stale | no cambia ningún máximo |
| dos pay concurrentes/replay | una Invoice/Payment/stock/fulfillment |
| retry dispense, misma key/payload | una sola línea adicional |
| misma key, payload distinto | 409, cero efectos adicionales |
| lote cambia a quarantine entre lectura y post | post aborta, cero efectos |
| version conflict | 409, cero efectos |

## 11. Impacto cross-module

- **Billing/Checkout:** cambia proyección, validación y schema; Invoice continúa
  siendo snapshot posted, no se reintroduce lifecycle legacy.
- **Inventory:** stock agregado Product y saldo StockLot siguen siendo autoridades;
  `consume_product` deberá devolver movimientos committed multilote y revalidar
  consumibilidad sobre filas lockeadas. No se mueve stock al seleccionar.
- **Medical records/Prescriptions:** cerrar consulta crea Checkout; cantidad Rx se
  mantiene en Product.base_unit. El formulario y serializer harán esa unidad
  visible, sin cambiar dosis clínica.
- **Cash:** la migration desbloquea el INSERT; Payment sigue en la misma transacción
  de pay y sus UNIQUE idempotentes pasan a existir físicamente.
- **Analytics:** `posted_at/paid_at/voided_at` permanecen anchors; eliminar columnas
  confirmed no cambia la consulta actual. Se limpian nombres/tests legacy.
- **Refund/Void/Replacement:** fulfillment, stock y dinero siguen separados; return
  no restaura cap y redelivery neutral conserva su contrato.
- **Frontend/Imports:** Cobros deja de interpretar stock legacy. Imports deberán
  respetar factor positivo; la retirada de campos legacy queda en P2, no se rompe
  en esta remediación.

## 12. Riesgos

- Una DB externa podría contener duplicados en los tres UNIQUE ausentes o anchors
  posted nulos. La migration debe abortar y reportarlos; no deduplicar ni rellenar
  con valores dummy.
- `CREATE INDEX` normal toma locks; producción requiere revisar volumen/ventana. Si
  el tamaño exige `CONCURRENTLY`, la migration deberá ser `atomic=False` y separar
  preflight/DDL con cuidado.
- Availability es una observación, no reserva. Stock puede cambiar entre GET y post;
  el post bajo lock sigue siendo el árbitro.
- El caso factor > remaining seguirá dando cero por diseño. El arreglo UX no debe
  convertirlo artificialmente en uno; se requiere una presentación compatible o
  corregir la receta/catálogo según la realidad clínica/comercial.
- Cambiar semántica de aliases ambiguos puede afectar consumidores no censados; se
  mantendrán como aliases derivados durante una ventana y se documentará su unidad.
- Añadir `replaces` modifica la interpretación del grafo, no el schema. Su despliegue
  queda acoplado al puente previo de `0027` y a pruebas de los tres historiales; no
  se aceptará como arreglo independiente.
- Las bases que ya eliminaron `confirmed_at*` no permiten reconstruir su source
  histórico. El gate debe reportar esa frontera; no fabricar equivalencia.
- Un cambio de factor de catálogo con Checkout abierto ya no reinterpreta el
  compromiso: cada línea snapshottea el factor aceptado y post/refund/void usan ese
  valor inmutable. Una selección nueva sí observa el catálogo vigente.

## 13. Cambios implementados

### 13.1 Convergencia de migrations y schema

- `billing.0026` declara la migration huérfana en `replaces`, preservando la
  procedencia del grafo en vez de borrar el record operativo.
- `billing.0027` incorpora un puente database-only idempotente que crea la tabla de
  selección mínima cuando el historial parte únicamente de la primera `0026`.
- `billing.0033` es la fase repair/verify (`atomic=False`): valida anchors y
  duplicados, repara `posted_at_source` desde evidencia legacy y crea los índices
  actuales/UNIQUE parciales. Si los datos no satisfacen el contrato aborta; no
  inventa valores ni deduplica.
- `billing.0034` es la fase contract forward-only: elimina
  `idx_inv_org_status_conf`, `confirmed_at_source` y `confirmed_at`. Su reversa
  falla explícitamente porque la provenance eliminada no se puede reconstruir.
- `inventory.0025` valida y materializa `conversion_factor > 0` y su límite de
  representación mediante preflight + `NOT VALID`/`VALIDATE CONSTRAINT`.
- `billing.0035` e `inventory.0026` agregan snapshots inmutables de conversión. El
  backfill usa primero verdad física (`StockAllocation / quantity`), luego el
  snapshot clínico y sólo después el catálogo; valida finitud, positividad y escala
  exacta. La nullabilidad en CheckoutItem/InvoiceItem es semántica y permanente
  sólo para líneas de servicio, protegida por CHECK, no una relajación temporal.
- `billing.0035` reemplaza los UNIQUE de devolución por línea por UNIQUE
  `(credit_note_item, allocation)`, habilitando reversión exacta multilote.

### 13.2 Gate y operación segura

- `audit_billing_schema` compara columnas, nullability, CHECKs, índices/UNIQUE,
  ausencia de objetos legacy y migrations requeridas contra `pg_catalog`.
- CI ejecuta el gate inmediatamente después de `migrate`; además existen tests de
  DB limpia, reconocimiento de replacement y drift observado reparado dos veces.
- `docs/runbooks/billing-schema-reconciliation.md` documenta backup, preflight,
  despliegue forward-only, verificación, rollback de aplicación y la prohibición de
  `--fake` sin DDL equivalente y evidencia verificable.

### 13.3 Autoridad de cantidades y disponibilidad

- `inventory/units.py` concentra validación/conversión exacta base↔presentación.
- `billing/prescription_availability.py` es la única proyección de cap clínico,
  fulfillment histórico, selección actual, demanda física del Checkout, stock
  Product/lotes y máximo incremental. `Product.stock_quantity` y lotes consumibles
  son autoridad; `Presentation.stock` no participa.
- Backend expone nombres y unidades explícitos, los tres límites
  `clinical_max_additional_quantity`, `stock_max_additional_quantity` y
  `max_selectable_quantity`, además de reason codes. El frontend dejó de dividir,
  aplicar floor, consultar lotes en cascada o leer stock legacy.
- Presentaciones retail/Rx son enteras en las fronteras de escritura. Un remanente
  base menor al factor conserva máximo cero con `below_presentation_size`; no se
  fuerza una unidad comercial inexistente.

### 13.4 Atomicidad, idempotencia y reversión

- Pay/post/dispense exigen `expected_version` tipado e idempotency key donde
  corresponde; replay idéntico retorna el resultado previo y key con payload
  distinto produce conflicto.
- Los permisos Rx se verifican en el servicio, no sólo en la view. Los payloads
  críticos pasan por serializers y rechazan Decimal no finito.
- El plan FEFO consume 1..N lotes bajo locks deterministas y persiste exactamente
  movimientos + allocations committed.
- `stock_returns.py` bloquea allocations y revierte cada slice a su lote original;
  refund, terminal void y replacement dejaron de usar sólo la primera allocation.
  Una línea sin allocation física no puede fabricar una reposición.
- CheckoutItem, InvoiceItem y MedicalRecordProduct capturan el factor aceptado;
  post, analytics físicos, refund y void nunca reinterpretan historia con el factor
  mutable del catálogo.

### 13.5 Cleanup cross-module

- Analytics normalizó el último nombre/fixtures `confirmed_at` a `posted_at`; las
  únicas menciones restantes pertenecen a migrations históricas, al gate que las
  prohíbe y a sus pruebas de regresión.
- La ADR de lifecycle documenta el contrato material de unidades, snapshots,
  disponibilidad incremental y allocations multilote.
- Serializers clínicos muestran `Product.base_unit`; Billing dejó de publicar o
  consumir `Presentation.stock` como disponibilidad.
- Se actualizó la documentación normativa de
  [Billing](../modules/billing.md), el
  [modelo de eventos financieros](../financial-event-model-contract.md), el
  [checklist de Analytics](../analytics-readiness-checklist.md) y las
  [operaciones por módulo](../system-module-operations.md), además de los
  contratos cross-module de Citas, Historial clínico, Inventario, Caja,
  Organizaciones, Analytics, flujos, referencia operacional, backups y demo
  seed. Los análisis con cortes anteriores conservan su evidencia, pero ahora
  declaran explícitamente que el lifecycle legacy no es operativo.

## 14. Evidencia post-fix

### 14.1 Schema

- PostgreSQL 18.3, base existente: upgrade real hasta `billing.0035` e
  `inventory.0026` aplicado sin fake.
- Base PostgreSQL vacía: Django recreó `test_veterinaria_saas`, aplicó todo el grafo
  y `BillingSchemaContractTests` pasó; la base de prueba se destruyó al terminar.
- Upgrade sintético desde el drift observado ejecutó repair + contract dos veces y
  terminó verde, demostrando idempotencia de la corrección física.
- Comparador Django/PostgreSQL posterior: `tables: {}`. El único record sin archivo
  es la primera `0026`, aceptada exclusivamente por su `replaces` declarado.
- `audit_billing_schema --json`: `violations=0`, `ok=true`.
- Inspección física final: `billing_invoice` no contiene `confirmed_at` ni
  `confirmed_at_source`; `idx_inv_org_status_conf` no existe;
  `idx_inv_org_status_post`, CHECKs de anchors y los UNIQUE parciales financieros
  sí existen. Los campos snapshot y los UNIQUE por allocation también coinciden
  con model state.
- `showmigrations`: Billing `0026`–`0035` e Inventory `0025`–`0026` aplicadas.
- `makemigrations --check --dry-run`: `No changes detected`; `manage.py check`: cero
  issues.

### 14.2 Checkout, unidades, fulfillment y stock

- `test_checkout_authoritative_flow`: 21 pruebas verdes, incluyendo post/pay,
  doble pay, replay, conflicto de versión, permisos, fulfillment y stock.
- `test_checkout_api_contract`: 7 pruebas verdes sobre la frontera HTTP real,
  incluido `POST /checkouts/{id}/pay/`, validación/errores de versión y RBAC.
- `test_checkout_concurrency`: 2 pruebas PostgreSQL verdes con conexiones reales:
  mismo key simultáneo devuelve una sola Invoice comprometida a ambos callers; keys
  distintas permiten una sola transición. En ambos casos hay exactamente un
  Payment, un descuento de stock y un receipt committed. La base aislada usada para
  evitar colisión con otro runner local se eliminó después de validar.
- `test_prescription_availability`: 12 pruebas verdes con factor 1 y >1,
  fulfillment parcial/total, selección actual, stock insuficiente/stale, lotes,
  cambio de factor después de seleccionar y refund/void multilote exactos.
- `test_schema_contract`: 3 pruebas verdes; `test_units_contract`: 3 pruebas verdes,
  incluyendo rechazo runtime/DB de cero, negativos, infinito y NaN.
- Auditoría de stock real: 116 Products revisados, 83 reconciliados, 33 sin baseline,
  `drift_count=0`, `lot_drift_count=0`.
- Auditoría del ledger de pagos real: 135 Invoices revisadas, cero violaciones.
- Auditoría de anchors real: cero violaciones de `posted_at`, `paid_at`,
  `voided_at` y `closed_at`; cero provenance sin resolver.
- Tests focalizados de Analytics para corrupción/provenance: 3 verdes después de
  normalizar la clave `posted_at`.

### 14.3 Frontend y build

- Helper de presentación: 6 pruebas unitarias verdes; cubre máximos y reason codes
  sin recomputar dominio.
- ESLint focalizado de Billing/API/helper: verde.
- Build de producción Vite: verde.
- El lint global conserva 199 errores preexistentes fuera del alcance de esta
  remediación; no se ocultaron ni se atribuyen a estos cambios.

### 14.4 Límites de la evidencia

No se ejecutó toda la suite histórica del repositorio: el changeset recibido ya
traía once archivos de tests Billing eliminados y numerosos cambios ajenos. Se
preservó ese estado y se usaron suites focalizadas sobre cada invariante nueva más
los gates físicos PostgreSQL. Los tests eliminados se registran como deuda P2 y no
como evidencia aprobatoria.

### 14.5 Correcciones posteriores detectadas por CI (2026-09-07)

El primer CI posterior al merge descubrió contratos secundarios que no estaban
cubiertos por la auditoría inicial:

- El fixture SQL de `audit_appointment_overlaps` no incluía el campo requerido
  `Appointment.category`; se alineó con el schema actual. El helper de walk-in
  también conserva el invariante de fin de cita al cruzar medianoche.
- `discard_lot` distingue una merma de un consumo y ahora transmite esa
  semántica al ledger, permitiendo retirar lotes vencidos o bloqueados sin
  relajar los callers de consumo.
- El cierre de una consulta de vacuna materializaba el producto después de
  marcar el expediente `closed`; ahora materializa cargos mientras está abierto
  y lo sella después, dentro de la misma transacción. El resultado es un
  `Checkout` abierto; la `Invoice` nace al postear/cobrar.
- Los serializers públicos de Checkout/Dispute dejaron de exponer el PK entero
  junto al `public_id`. Las rutas de hijos internos usan segmento textual y
  validan el PK sólo después de resolver el recurso padre tenant-scoped.
- Las notificaciones usan `for_organization()` también en `get_or_create`; se
  retiró del baseline una excepción que ya no existe.
- El editor de pagos documenta visualmente el cambio no registrado cuando se
  permite sobrepago. Los identificadores de fixtures que Gitleaks marcó como
  secretos se sustituyeron y se dejó una allowlist exacta para los valores del
  commit histórico ya publicado, sin desactivar la regla global.

Validación local posterior: 13 tests focalizados de materialización/RBAC,
3 tests de auditoría de URLs/tenant, 19 tests del editor de pagos y la suite
frontend completa (346 tests) quedaron verdes; compilación Python y `git diff
--check` también pasaron. El siguiente CI debe confirmar Gitleaks contra el
historial remoto y la suite backend completa.
