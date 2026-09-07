# Cuarta revisión independiente del DAR — Billing / Checkout

**Fecha:** 2026-09-01  
**DAR revisado:** `docs/decisions/2026-08-30-p62-billing-checkout-lifecycle.md`  
**Revisión anterior:** `docs/audits/2026-08-31-dar-billing-checkout-third-review.md`  
**Alcance:** revisión arquitectónica; no incluye implementación  
**Jerarquía aplicada:** código → tests → contratos/API → documentación aceptada → DAR

## 1. Veredicto

## APPROVE WITH CHANGES

El concepto central ya no requiere rediseño: separar un `Checkout` comercial editable de una `Invoice` financiera inmutable sí elimina la sobrecarga actual de `draft`, y la versión actual define con bastante precisión precio clínico, cierre, readiness por acción, posteo, pago, crédito, reemplazo, locks, provenance y anomalías legacy.

Sin embargo, el DAR **todavía no debe convertirse directamente en plan de implementación**. Quedan cinco blockers nuevos y concretos: atestación de receta externa, compatibilidad con el contrato canónico de eventos financieros, semántica de allocations después de reversas/devoluciones, consistencia del cutover en línea y elegibilidad de anomalías legacy para cobro. No son objeciones al agregado Checkout; son contratos transversales sin los cuales dos implementaciones conformes al texto podrían producir resultados regulatorios, financieros o de inventario diferentes.

La respuesta a la pregunta principal es: **sí, el DAR ya separa correctamente preparación comercial de obligación financiera y resuelve gran parte de la ambigüedad `draft`/`confirmed`; todavía no garantiza por completo la consistencia receta–stock–Invoice–Payment en correcciones, migración y direct sale regulada**.

La respuesta a la segunda pregunta es: **sí, aún existen decisiones cuya interpretación puede generar comportamientos distintos**. Están registradas como ADR-R51–ADR-R58.

> Resultado OCR de readiness: **REQUEST CHANGES**. El veredicto arquitectónico sigue siendo `APPROVE WITH CHANGES` porque la dirección central es correcta, pero los blockers deben cerrarse antes del plan.

## 2. Executive Summary

1. Los cinco blockers de la tercera revisión quedaron cerrados en sustancia; no se están reabriendo.
2. El primer precio/impuesto del ciclo clínico, cantidad append-only y repricing mediante ciclo nuevo preservan la semántica temporal que hoy aporta `InvoiceItem` draft.
3. `void_and_prepare_replacement` ya es un contrato atómico, idempotente y con lineage suficiente.
4. `LegacyCheckoutSeed` evita crear anticipadamente el Checkout primario de un MedicalRecord abierto.
5. Partial/overpaid legacy ya no se fuerza mediante CreditNote sintética; el modelo necesita todavía reglas de evento y elegibilidad.
6. El orden `(model_rank, primary_key)` es correcto, aunque debe aplicarse a la primera adquisición del lock, no a cada UPDATE posterior de una fila ya lockeada.
7. R45–R50 mejoran materialmente allocations, readiness, tributación, CollectionCase, idempotencia y gobierno de datos.
8. El flujo regulado de `ExternalPrescriptionAttestation` existe en código, tests y ADR p26, pero no aparece en el nuevo DAR.
9. El scope de idempotencia de `CommandReceipt` puede colisionar con el índice único y las keys derivadas de `Payment`.
10. “StockAllocation effective” no está definido después de void, retorno, restock, discard, refund, reversal o replacement.
11. El backfill por lotes no define cómo capturar mutaciones legacy ocurridas antes del cutover de cada organización.
12. `settle_legacy_partial` valida aritmética, pero no demuestra que la obligación histórica sea válida y cobrable.
13. La eliminación del PDF de Invoice draft requiere una decisión explícita: retirarlo o reemplazarlo por un estimado no financiero de Checkout.
14. El repricing clínico necesita comando, ACL, versionado e idempotencia propios.
15. Cerrados ADR-R51–ADR-R55, una revisión enfocada sería suficiente; no hace falta replantear Checkout.

## 3. Qué está bien

### 3.1 Cierre de los cinco blockers anteriores

| Blocker anterior | Estado | Evaluación independiente |
| --- | --- | --- |
| Precio/impuesto clínico | **Cerrado** | El ciclo activo conserva primer precio y contexto fiscal; los incrementos no reprecifican; decremento/eliminación/reapertura quedan auditados y un reprice total crea ciclo nuevo. |
| Reemplazo después de void | **Cerrado** | `void_and_prepare_replacement` es un solo comando, endpoint, `CommandReceipt` y commit; define rollback, replay, lineage y disposiciones. |
| Migración de MR abierto | **Cerrado** | `LegacyCheckoutSeed` no participa en lifecycle ni finanzas; `close_medical_record` reconstruye fuentes y crea/adopta exactamente un Checkout primario. |
| Partial/overpaid legacy | **Cerrado en su decisión central** | Los Payments previos se conservan; partial añade el saldo exacto; overpaid se reclasifica como pasivo y se devuelve sin CreditNote sintética. Restan los blockers R52 y R55 sobre integración y elegibilidad. |
| Locks con Appointment | **Cerrado en intención** | Hay ranking único por modelo y PK, prelectura de padres y locks explícitos. R57 solo corrige una contradicción literal entre adquisición y UPDATE posterior. |

### 3.2 Decisiones arquitectónicas sólidas

- `Checkout` representa preparación comercial mutable; `Invoice` nace únicamente al crear una obligación financiera.
- `Checkout.completed` describe el fin exitoso de esa preparación y exige un outcome único: `posted_paid`, `posted_unpaid` o `no_charge`.
- `Checkout.abandoned` es terminal sin decisión comercial exitosa; no equivale a consulta sin cargos.
- `Invoice.posted` tiene una semántica operacional concreta: snapshot inmutable, devengo/obligación y, para retail, entrega/consumo comprometido.
- `Payment` sigue siendo ledger append-only y el settlement se deriva de eventos efectivos, no de un flujo paralelo de mutación arbitraria.
- `readiness` es por acción, separa `blockers` de `required_inputs` y nunca autoriza por sí solo: el POST revalida bajo locks.
- El crédito futuro se limita a un post unpaid explícitamente autorizado, con términos/evidencia y sin habilitar partial normal accidentalmente.
- `CheckoutDispute` y `CollectionCase` separan controversia pre-post de gestión de cobranza post-post.
- La provenance tributaria distingue evidencia fuerte, reconstruida y desconocida; no inventa aceptación histórica.
- La canonicalización idempotente y los tombstones de receipts son una base correcta para replays seguros.
- `StockAllocation` nace al post y referencia un `StockMovement` committed; Checkout abierto solo conserva intención.
- El consumo clínico single-lot en v1 elimina una inconsistencia actual entre FEFO multi-lot y `MedicalRecordProduct.lot` singular.
- Las recetas suplementarias y el fulfillment acumulado resuelven aceptación parcial sin reabrir la prescripción histórica.

## 4. Problemas encontrados

| ID | Severidad | Problema | Evidencia | Recomendación |
| --- | --- | --- | --- | --- |
| ADR-R51 | **BLOCKER** | La receta externa regulada no tiene contrato en Checkout | ADR p26 exige `ExternalPrescriptionAttestation`; modelo en `billing/models.py:479`; gate en `billing/views.py:327`; UI en `Cart.jsx:49`; tests dedicados. El nuevo DAR no menciona el concepto. | Definir evidencia append-only ligada a item/presentación/cantidad/versión, revalidación al post, proyección a Invoice, supervivencia, ACL, retención y migración. |
| ADR-R52 | **BLOCKER** | `CommandReceipt`, Payments hijos y `LegacyLiabilityReturn` no están reconciliados con el contrato financiero congelado | El contrato exige key única por organización y campos canónicos; `Payment` mantiene esa unicidad y hoy deriva `K:i`; D14 permite reutilizar `K` entre command kinds; D15 no define el evento canónico completo. | Versionar/adendar el contrato financiero; identificar hijos por receipt + índice, definir eventos de devolución, cash session, signo, provenance, reversa y analytics. |
| ADR-R53 | **BLOCKER** | “Allocation efectiva” carece de lifecycle después de correcciones | El DAR usa allocations committed/effective para el cap Rx y reutiliza allocations en `goods_retained`, pero no define efectos de return/restock/discard/refund/reversal. | Publicar proyección append-only o tabla normativa que separe stock, custodia, dinero y fulfillment Rx por disposición. |
| ADR-R54 | **BLOCKER** | El cutover en línea puede perder cambios posteriores al backfill | M2–M5 permiten backfill y activación posterior; hoy existen writers en cierre de MR, productos/servicios, signal de Appointment, dispensing y endpoints de Invoice. | Definir freeze + reconciliación/watermark, change capture o fase de compatibilidad autoritativa; gate de cero mutaciones pendientes. |
| ADR-R55 | **BLOCKER** | Una anomalía partial puede cobrarse sin probar validez de la obligación | D15 exige saldo matemático y permisos, pero no closed-MR/posted lineage, tax/stock reconciliados ni precedencia de quarantine. | Añadir `repairability`/matriz de elegibilidad; solo deuda probada puede cobrarse/promoverse. |
| ADR-R56 | **HIGH** | El PDF de Invoice draft desaparece sin decisión de compatibilidad | Endpoint, documentación, frontend y tests aceptan PDF en todos los estados con watermark draft; el DAR no menciona PDF, quote o proforma. | Decidir estimado no financiero de Checkout o retiro explícito como breaking change. |
| ADR-R57 | **HIGH** | El lock order se formula sobre cada UPDATE y contradice el cierre del receipt | `CommandReceipt` se lockea/reclama primero y se actualiza después de efectos de mayor rank; actualizar una fila ya lockeada no adquiere un lock inverso nuevo. | Aplicar ranking a la primera adquisición de filas existentes; permitir escrituras posteriores sobre locks ya poseídos y registrar toda coordination row mutable. |
| ADR-R58 | **HIGH** | Repricing clínico definido como regla, no como comando | El ciclo nuevo requiere actor/motivo, pero no aparece un command kind/endpoint/ACL/version/idempotency específico en la tabla de comandos. | Añadir `reprice_clinical_charge` o nombre equivalente con cierre+apertura atómicos y precondición de versión. |

### 4.1 Por qué ADR-R51 es blocker

La venta directa actual de una presentación que requiere receta no es solo “otro item retail”. El backend exige `rx_attested`, identidad mínima del prescriptor y evidencia en la misma operación que agrega el producto; crea un registro append-only y el ADR p26 exige conservarlo incluso después de cancel/refund. Los tests comprueban rechazo sin evidencia, alta válida y supervivencia.

Al eliminar Invoice draft, la FK actual deja de ser un host natural. El DAR no dice si la evidencia:

- pertenece al Checkout, a su item, a un agregado regulatorio o nace atómicamente con Invoice;
- queda invalidada si cambia presentación o cantidad;
- debe corresponder a `checkout_version` o a un fingerprint de líneas reguladas;
- se vuelve a validar dentro de `pay_checkout`/`post_checkout_unpaid`;
- sobrevive `abandoned`, `void`, refund y replacement;
- se copia, referencia o vuelve a materializar en Invoice;
- se migra desde drafts existentes;
- comparte o restringe los ACL y plazos de R50.

Sin esa decisión, una implementación puede suprimir un control regulatorio y otra puede conservar Invoice draft solo para alojarlo. Ambas seguirían el texto actual; por eso bloquea el plan.

### 4.2 Por qué ADR-R52 es blocker

El contrato financiero aceptado declara una identidad idempotente única por organización para cada evento. El ledger actual refuerza esto con un constraint en `Payment` y genera hijos como `raw_key:index`. D14, en cambio, permite que `pay_checkout(K)` y `pay_invoice(K)` sean comandos independientes porque `CommandReceipt` incluye `command_kind` en el scope.

Si los Payments conservan `K:0`, dos comandos válidos colisionan. Si se elimina el unique, se debilita el ledger. Si cada equipo inventa un prefijo distinto, replay y migración dejan de ser canónicos. Además, `LegacyLiabilityReturn` se describe como un objeto más líneas por método, pero no aclara si el evento financiero es la cabecera o cada línea, qué signo tiene, cómo referencia CashSession, qué `occurred_at` usa y cómo se corrige sin editar historia.

Esto puede duplicar, impedir o representar de forma no canónica movimiento de dinero. Debe cerrarse antes de diseñar esquema o endpoints.

### 4.3 Por qué ADR-R53 es blocker

El DAR usa “allocations committed/effective” como fuente del fulfillment acumulado y del límite prescrito, pero solo define el nacimiento de la allocation. Falta definir su efecto posterior:

| Evento | Stock físico | Venta/obligación | Fulfillment Rx | Pregunta abierta actual |
| --- | --- | --- | --- | --- |
| void + `goods_retained` | No sale de nuevo | Se reemplaza documento | Debe contar una sola vez | ¿La allocation original sigue efectiva y la nueva línea solo referencia? |
| void + `returned_restocked` | Regresa y una nueva entrega volvería a salir | Se reemplaza documento | Puede liberarse o no según regla clínica/legal | ¿Qué evento revierte fulfillment? |
| refund sin retorno | Producto permanece con cliente | Dinero revierte | Normalmente sigue dispensado | No está explícito. |
| refund + restock | Producto vuelve | Dinero revierte | Depende de validez de devolución | No está explícito. |
| discard | No vuelve a disponible | Puede haber retorno físico o merma | No equivale automáticamente a “no dispensado” | No está explícito. |
| refund reversal | No es nueva entrega | Dinero se reaplica | No debe duplicar fulfillment | No está explícito. |

Una fórmula equivocada permite dispensar más de lo prescrito o bloquear legítimamente un reemplazo. Eso es inventario y seguridad clínica, no solo analytics.

### 4.4 Por qué ADR-R54 es blocker

La migración es idempotente para una fotografía estable, pero el sistema seguirá recibiendo escrituras. Entre el backfill de una organización y su flag de cutover pueden ocurrir:

- incremento de un producto o servicio clínico;
- cierre de MedicalRecord;
- finalización de Appointment y signal de auto-Invoice;
- cambio de un draft, confirmación, pago, refund o dispensación;
- creación/cambio de atestación de receta externa.

`LegacyCheckoutSeed` evita dos Checkouts primarios, pero no garantiza que items, payments, stock y provenance copiados sigan siendo actuales. “Bloquear writers en M5” llega tarde si el último cambio ocurrió después del batch y nunca se reconcilió. Se necesita una frontera verificable: freeze corto con lectura final, watermark más catch-up, o CDC/compatibilidad equivalentes.

### 4.5 Por qué ADR-R55 es blocker

`0 < effective_applied < total` demuestra que hay una diferencia numérica, no que el total sea una deuda válida. Un legacy partial puede provenir de:

- Invoice draft de MR todavía abierto;
- items sincronizados antes de que la consulta fuera clínicamente final;
- precio/impuesto de provenance débil;
- stock no reconciliado;
- payment real contra un documento cuya obligación nunca fue válidamente emitida.

Permitir `settle_legacy_partial` en todos ellos transforma una anomalía en una Invoice normal paid y puede cobrar una deuda inválida. Debe existir una clasificación objetiva como `collectible`, `returnable`, `external_resolution_only` o `quarantined`, con precedencia sobre el simple tipo partial/overpaid.

## 5. Decisiones del DAR confirmadas

### 5.1 Responsabilidades actuales de `Invoice.draft`

| Uso actual de draft | ¿Lo necesita Checkout? | ¿Lo necesita Invoice? | ¿Puede eliminarse? |
| --- | --- | --- | --- |
| Editar items antes del cobro | Sí | No | Sí, al moverlo a Checkout con versión/audit. |
| Sincronizar MedicalRecord → líneas | Solo recibe snapshot al close | No antes del close | Sí, ClinicalChargeEntry conserva la verdad temporal. |
| Preparar dispensación de receta | Sí, como selección/intención | No antes del post | Sí, con fulfillment post y R51 para receta externa. |
| Alojar stock pendiente | No; open no reserva | Solo allocations committed al post | Sí; no debe conservarse ese uso. |
| Servir como carrito POS | Sí | No | Sí. Direct-sale Checkout es el carrito. |
| PDF “BORRADOR” | Posiblemente como estimate no financiero | No | Solo después de decidir ADR-R56. |
| Permisos de edición | `checkout.edit` y comandos de origen | No | Sí; mejora separación de funciones. |
| Idempotencia/concurrencia | Version + CommandReceipt | Invoice conserva receipts de operaciones financieras | Sí. |
| Cancelar preparación | `abandon` | `void` solo después de post | Sí; evita que cancel signifique dos cosas. |
| Analytics pre-financieros | Funnel/operación de Checkout | Revenue/AR solo desde post | Sí; mejora semántica. |

### 5.2 Decisiones confirmadas

| Decisión | Confirmación |
| --- | --- |
| Checkout como agregado independiente | Sí. Elimina la necesidad de usar un documento financiero mutable como staging clínico/comercial. |
| No Invoice posted con MR open | Sí en el futuro model, condicionado a que R54 cierre todos los legacy writers durante cutover. |
| Invoice sin draft | Sí, siempre que quote/PDF se trate como documento no financiero y se resuelva R51. |
| `confirmed` reemplazado por `posted` | Sí. `posted_at` debe conservar el anchor de emisión/devengo que hoy presta `confirmed_at`. |
| Invoice inmutable tras post | Sí. Correcciones por void/replacement, CreditNote/refund/counterevents. |
| `paid` derivado de settlement | Sí. Puede persistirse como snapshot/proyección protegida, pero el ledger manda. |
| Crédito solo explícito | Sí. `posted/unpaid` no debe aparecer por omisión ni por pago parcial normal. |
| Consultas `$0` sin Invoice | Sí para “sin transacción financiera”; conservar Checkout outcome y evento de auditoría. |
| `completed` con outcome único | Sí: paid, unpaid o no_charge. No significa entrega ni pago por sí solo. |
| `abandoned` separado de `no_charge` | Sí. Abandono es falta de conclusión; no_charge es conclusión válida sin obligación. |
| PrescriptionSelection en Checkout | Sí como decisión comercial; la prescripción/revisión clínica sigue siendo autoridad y las allocations post son fulfillment. |
| Direct sale y consulta comparten core | Sí para Checkout/post/payment/stock, con módulos de origen y gates distintos. |
| Readiness derivada y por acción | Sí, con versión y revalidación final dentro de la transacción. |
| Stock retail al post | Sí. El pago no debe ser el único trigger: crédito autorizado también puede entregar y consumir stock. |
| Clinical consumable fuera de Checkout stock | Sí. Se consume cuando se usa clínicamente y Checkout solo refleja el cargo. |

## 6. Decisiones que deben cambiar

1. Incorporar ADR-R51 como contrato regulatorio de evidencia externa, no como detalle de serializer/UI.
2. Incorporar ADR-R52 mediante una enmienda explícita al contrato congelado de eventos financieros.
3. Sustituir “effective allocation” por una proyección definida a partir de eventos y disposiciones.
4. Reemplazar la migración “backfill y luego flag” por un protocolo con frontera de consistencia demostrable.
5. Separar `LegacySettlementCase.kind` de su `repairability`; tipo matemático no implica acción legal permitida.
6. Aclarar que el total order gobierna la primera adquisición de locks sobre filas existentes.
7. Elevar repricing a comando de dominio explícito y auditable.
8. Añadir al compatibility matrix el PDF draft/estimado y la atestación externa.

## 7. Decisiones que faltan

### 7.1 Deben cerrarse en el DAR

- Owner y modelo de `ExternalPrescriptionAttestation` después de eliminar Invoice draft.
- Fingerprint/versión de las líneas Rx cubiertas por una atestación externa.
- Derivación de keys para eventos hijos desde `CommandReceipt` sin colisión entre command kinds.
- Forma canónica y reversa de `LegacyLiabilityReturn` y sus líneas de método.
- Regla de fulfillment Rx para cada disposición física/financiera.
- Protocolo exacto de catch-up/cutover por organización.
- Eligibility/repairability de cada `LegacySettlementCase`.
- Sucesor o retiro del PDF de draft.
- Contrato de comando para repricing clínico.

### 7.2 No requieren una nueva decisión central

- Nombres físicos de tablas e índices, siempre que preserven constraints del DAR.
- Si `payment_status` se materializa como snapshot: es aceptable si siempre se valida/deriva del ledger y no tiene setter independiente.
- El nombre de UI “Cobro pendiente” versus “Checkout pendiente”: puede resolverse en UX usando las categorías semánticas ya definidas.

## 8. Máquina de estados recomendada

### 8.1 Checkout

```text
Checkout.open
  ├─ pay_checkout ───────────────▶ Checkout.completed / posted_paid
  ├─ post_checkout_unpaid ───────▶ Checkout.completed / posted_unpaid
  ├─ complete_no_charge ─────────▶ Checkout.completed / no_charge
  └─ abandon_checkout ───────────▶ Checkout.abandoned

Checkout.completed y Checkout.abandoned son terminales.
Un replacement siempre es un Checkout nuevo ligado a la Invoice voided.
```

`completed` significa: **la preparación terminó exitosamente y se registró exactamente uno de los outcomes anteriores**. No significa por sí solo pago, entrega ni obligación; eso lo expresa el outcome.

### 8.2 Invoice

```text
Invoice.posted/unpaid
  ├─ pay_invoice ───────────────────────────▶ Invoice.posted/paid
  ├─ void_invoice_terminal ─────────────────▶ Invoice.voided
  └─ void_and_prepare_replacement ──────────▶ Invoice.voided + Checkout.open(replacement)

Invoice.posted/paid
  └─ CreditNote / RefundPayment / counterevents

Invoice.voided es terminal y nunca se reabre.
```

`posted` representa emisión/devengo de la obligación comercial/fiscal y freeze del snapshot. Para retail/Rx también coincide con entrega/consumo comprometido según allocations. `posted_at` reemplaza el anchor financiero de `confirmed_at`; `paid_at` conserva el anchor de settlement total.

### 8.3 Settlement

```text
effective_applied = suma de Payment efectivos − reversas/ajustes canónicos

0                       → unpaid
invoice.total exacto    → paid
entre 0 y total         → inválido para writers futuros; legacy case
mayor que total         → inválido para writers futuros; legacy liability case
```

### 8.4 Disputa/cobranza

```text
CheckoutDispute.open
  ├─ accepted_no_charge
  ├─ withdrawn/resolved_for_post
  └─ enforced_under_terms ─▶ Invoice.posted/unpaid + CollectionCase.open

CollectionCase.open
  ├─ paid
  ├─ collectible
  ├─ replaced
  ├─ waived/voided si el contrato lo permite
  └─ resolución administrativa auditada
```

### 8.5 Evidencia y fulfillment: proyecciones, no flags mutables

- La atestación externa debe ser evidencia append-only con vigencia derivada respecto al fingerprint Rx del Checkout.
- La efectividad de fulfillment debe derivarse de allocations y eventos de disposition/reversal; no debe ser un booleano editable en `StockAllocation`.
- `collection_status` sigue siendo una proyección de CollectionCase + settlement.

## 9. Invariantes

1. Un MedicalRecord abierto nunca produce Invoice posted.
2. Una Invoice posted de consulta referencia un MedicalRecord cerrado e inmutable en sus fuentes facturables.
3. Existe como máximo un Checkout primario por `(organization, medical_record)`; replacements tienen lineage explícito.
4. `LegacyCheckoutSeed` nunca es Checkout, obligación, AR ni revenue.
5. Checkout abierto puede cambiar intención, pero no contiene stock committed ni eventos financieros.
6. Cada terminal command usa receipt idempotente, versión esperada y una transacción.
7. El GET de readiness no autoriza; el POST repite guards y locks sobre estado actual.
8. Checkout completed tiene exactamente un outcome terminal.
9. `no_charge` no crea Invoice ni Payment; `Invoice total=0` solo existe si hay una razón fiscal explícita distinta.
10. Invoice posted es inmutable; cualquier corrección usa documentos/eventos enlazados.
11. `posted_at`, `paid_at` y `voided_at` son anchors append-only, no timestamps reescribibles.
12. Ningún writer futuro crea partial u overpaid.
13. Cada Payment/evento financiero tiene identidad canónica no colisionable, organization scope, receipt/provenance y causalidad.
14. Una misma Payment no se aplica dos veces; una reversa no edita el evento original.
15. Crédito requiere permiso, términos, vencimiento/evidencia y un total exacto.
16. Clinical consumable mueve stock al uso clínico; retail/Rx mueve stock al post exitoso.
17. Cada StockAllocation referencia un InvoiceItem y un StockMovement committed.
18. El fulfillment Rx efectivo se cuenta exactamente una vez a través de void/refund/replacement.
19. Evidencia de receta externa cubre exactamente las líneas/presentaciones/cantidades efectivas y se revalida al post.
20. Una modificación de línea Rx invalida o exige nueva evidencia según fingerprint, nunca conserva aceptación implícita.
21. Ningún caso legacy puede cobrarse/promoverse sin repairability `collectible` demostrada.
22. Backfill/cutover no deja mutaciones fuente posteriores al último watermark sin procesar.
23. Todos los locks sobre filas existentes se adquieren por primera vez en `(model_rank, pk)`; no se reacquire un rank inferior.
24. Toda query y unique constraint de receipts, seeds, cases, allocations y evidencias es tenant-aware.
25. ACL distingue editar intención, postear obligación, mover dinero, otorgar crédito, void, refund y reparación legacy.
26. Retención preserva identidad/auditoría obligatoria y elimina payload sensible cuando vence su necesidad.
27. Analytics se deriva de `posted_at`, settlement efectivo, counterevents y cases; nunca de Checkout abierto.

## 10. Flujo Consulta → Checkout → Billing → Payment

```text
Appointment / MedicalRecord.open
  ├─ captura clínica
  │    ├─ ClinicalChargeEntry + QuantityEvents + precio/impuesto por ciclo
  │    ├─ consumo clínico single-lot + StockMovement inmediato
  │    └─ PrescriptionRevision(s) append-only
  │
  └─ close_medical_record [receipt + locks + revalidación]
       ├─ freeze de fuentes clínicas
       ├─ MedicalRecord.closed + Appointment.completed
       ├─ adopta LegacyCheckoutSeed si existe
       └─ crea Checkout.open + snapshot + selections pending
             ├─ edición comercial / decisión Rx / disputa
             ├─ complete_no_charge
             │    └─ Checkout.completed/no_charge; sin Invoice
             ├─ pay_checkout
             │    └─ Invoice.posted + allocations/movements retail
             │         + evidencia + Payment(s)
             │         └─ Checkout.completed/posted_paid
             └─ post_checkout_unpaid
                  └─ Invoice.posted/unpaid + allocations/movements
                       + evidencia/términos [+ CollectionCase]
                       └─ pago posterior exacto → paid
```

La Invoice no es creada al abrir la consulta, al añadir un cargo, al terminar Appointment por signal aislado ni al consultar readiness. Solo nace en el comando terminal financiero.

### 10.1 Contrato API recomendado

```text
GET  /checkouts/{id}
GET  /checkouts/{id}/readiness
POST /checkouts/{id}/pay
POST /checkouts/{id}/post-unpaid
POST /checkouts/{id}/complete-no-charge
POST /checkouts/{id}/abandon

POST /invoices/{id}/pay
POST /invoices/{id}/void
POST /invoices/{id}/void-and-prepare-replacement
POST /invoices/{id}/refund
```

- Evitar `cancel` como verbo común: en Checkout significa abandono; en Invoice significa void financiero.
- `post-unpaid` expresa mejor la creación de obligación que `confirm`, pero el API/documentación debe usar un único término estable.
- Todo mutating POST terminal exige `Idempotency-Key`; mutaciones de Checkout además `If-Match` o `expected_version`.
- Replay devuelve el mismo status/body/IDs autorizados desde `CommandReceipt`.
- Versión stale responde `409` o `412` de forma uniforme; blockers actuales responden un error de dominio estable; input mal formado sigue siendo `400/422` según la convención elegida.
- La transacción no confía en readiness leído previamente y recalcula precio, permisos, MR, evidencia Rx, crédito, settlement y stock.
- `void-and-prepare-replacement` pertenece a Invoice porque el objeto que se corrige es la obligación; el Checkout nuevo es parte de la respuesta.

### 10.2 Semántica frontend/UX

Recepción no debería ver todos los casos como “cobros”:

| Situación | Semántica de cola |
| --- | --- |
| MR cerrado, Checkout aún incompleto | **Por preparar** / consulta pendiente de preparación |
| Checkout listo para acción | **Pendiente de cobro/decisión** |
| Invoice posted/unpaid | **Cuenta por cobrar** |
| CollectionCase abierto | **Cobro disputado/en gestión** |
| Invoice paid | **Pagado** |
| Checkout no_charge | **Finalizado sin cargos** |
| Checkout abandoned | **No concluido/abandonado**, no “sin cargos” |

Esto permite que el frontend represente el workflow sin exponer al usuario los estados técnicos como si fueran equivalentes.

## 11. POS

POS debe compartir con consulta:

- Checkout/CheckoutItem, pricing snapshot y versionado;
- readiness por acción;
- post/pago/crédito;
- allocations, stock y receipt idempotente;
- Invoice/Payment/refund/void y analytics.

Debe conservar diferencias explícitas:

| Aspecto | Consulta | Direct sale / POS |
| --- | --- | --- |
| Origen | MedicalRecord cerrado | Sesión/usuario POS |
| Cargos clínicos | Sí, autoritativos y no editables comercialmente | No |
| Prescripción interna | Revision/Selection/fulfillment | Puede no existir |
| Receta externa | No sustituye prescripción clínica interna | Gate regulatorio obligatorio para presentación Rx sin receta interna |
| Cliente/paciente | Derivado del MR | Puede requerir selección explícita según reglas actuales |
| No-charge | Consulta válida sin cargos | Normalmente abandono/carrito vacío; no inventar evento clínico |
| Crédito | Bajo política y evidencia | Puede restringirse más por organización |

No debe forzarse que una atestación externa sea `PrescriptionSelection`: una es evidencia regulatoria aportada para direct sale; la otra es decisión de fulfillment sobre una prescripción clínica interna.

## 12. Recetas

Flujo recomendado:

```text
PrescriptionRevision (autoridad clínica append-only)
  ↓
CheckoutPrescriptionSelection (pending / accepted / declined)
  ↓ accepted
CheckoutItem(s) con presentación y cantidad solicitada
  ↓ post bajo locks y stock suficiente
StockAllocation(s) + InvoiceItem(s)
  ↓
PrescriptionFulfillmentProjection acumulada
```

Reglas:

- `pending` nunca preselecciona aceptación.
- `accepted` requiere items válidos, pero no reserva ni consume stock mientras Checkout está abierto.
- Aceptación parcial conserva remanente; una nueva decisión usa suplemento explícito, no reabre historia.
- Sustitución de presentación requiere compatibilidad clínica/regulatoria definida, no un simple cambio de SKU.
- El cap se valida de nuevo en el post con receta/revisiones y allocations relevantes lockeadas.
- Stock insuficiente bloquea post sin crear Invoice, Payment ni allocation parcial.
- Cambio de opinión antes del post modifica selección/items y versión; después del post usa devolución/corrección.
- R53 debe decidir cómo devolución y reemplazo afectan el remanente legal.
- La receta externa del POS es un flujo paralelo de evidencia (R51), no una selección interna ficticia.

## 13. Stock

| Tipo | Reserva | Consumo/salida | Venta/obligación | Devolución/reversa |
| --- | --- | --- | --- | --- |
| `clinical_consumable` | No en v1 | Al registrar uso clínico, single-lot explícito | El cargo se refleja después en Checkout; no vuelve a mover stock al post | Corrección clínica específica con provenance del movimiento; no refund retail automático |
| `prescription_retail` | No mientras Checkout open | Dentro del post exitoso, allocations + movements atómicos | Invoice posted paid o unpaid autorizado | Disposition explícita; R53 define stock y fulfillment por separado |
| `direct_sale_retail` | No mientras Checkout open | Dentro del post exitoso | Invoice posted paid o unpaid autorizado | Refund/void/replacement con disposition y lineage |

`post_unpaid` puede generar stock antes de Payment **solo porque el post representa entrega y obligación válida bajo crédito autorizado**. Si el producto no se entrega aún, entonces no debe postearse ese item como entregado: sería necesario otro concepto de fulfillment/reserva, fuera del contrato v1.

Al hacer void:

- `goods_retained`: no se crea nuevo movement/allocation para el replacement; la línea nueva referencia fulfillment original y no duplica Rx cap.
- `returned_restocked`: se registra retorno físico; una nueva entrega requiere allocation/movement nuevo.
- `discard`: registra pérdida/no disponibilidad, pero no determina por sí sola si la dosis legal deja de contar.
- refund sin retorno: revierte dinero, no stock ni fulfillment automáticamente.
- refund reversal: reaplica el evento financiero; no crea una nueva entrega.

Las dos últimas columnas necesitan la tabla normativa de ADR-R53 antes de esquema o tests.

## 14. Migración

### 14.1 Mapping de estados actuales

| Estado/factos legacy | Destino recomendado | Condiciones |
| --- | --- | --- |
| `draft` + MR open | `LegacyCheckoutSeed` o quarantine | Nunca Checkout primario; close reconstruye y adopta una vez. |
| `draft` + MR closed + fuentes/precio/provenance reconciliables | `Checkout.open` | Snapshot verificable; sin evento financiero. |
| `draft` `$0` + evidencia de cierre real sin cargos | `Checkout.completed/no_charge` | No inferir solo por `total=0`; requiere fuente de cierre. |
| `draft` abandonado/error | `Checkout.abandoned` o quarantine | Solo con evidencia; no inventar decisión del cliente. |
| `draft` con Payment/stock/anchors contradictorios | Quarantine + `LegacySettlementCase` si aplica | Nunca promover por el label draft. |
| `confirmed`, MR closed, cero Payment, total > 0 y stock/provenance válidos | `Invoice.posted/unpaid` | `posted_at ← confirmed_at`; repairability collectible si corresponde. |
| `confirmed` con Payments que suman total | `Invoice.posted/paid` | Preservar eventos y anchors; no sintetizar aceptación. |
| `confirmed` partial | Invoice/proyección legacy + `LegacySettlementCase.partial` | Solo `collectible` si la obligación se demuestra válida; de otro modo quarantine. |
| `confirmed` overpaid | Invoice + `LegacySettlementCase.overpaid` + pasivo | Devolución por eventos canónicos, sin CreditNote sintética. |
| `paid` con Payment(s) exactos | `Invoice.posted/paid` | Ledger existente manda. |
| `paid` sin ledger confiable | Provenance débil/quarantine | No fabricar Payment silenciosamente; aplicar política explícita. |
| `cancelled`, nunca posted y sin efectos | Checkout abandoned/legacy archive | Solo si evidencia distingue borrador abandonado. |
| `cancelled`, antes confirmed/stock/obligación | `Invoice.voided` | Preservar `posted_at/voided_at`, stock y audit. |
| Refund/CreditNote/RefundReversal existentes | Eventos/documentos canónicos enlazados | Conservar causalidad y no duplicar stock. |
| ExternalPrescriptionAttestation existente | Evidencia regulatoria migrada y enlazada | Mantener actor/fecha/presentación/cantidad/Invoice y retención; R51 define enlace futuro. |

### 14.2 Protocolo de cutover requerido

La secuencia M2–M5 debe agregar una de estas garantías normativas:

```text
opción recomendada para v1:
  bloquear writers legacy de una organización
  → registrar watermark/versiones fuente
  → ejecutar catch-up/reconciliación final bajo locks
  → validar conteos, hashes, payments, stock y provenance
  → activar writers futuros
  → impedir permanentemente rutas/signals legacy
```

Si el freeze no es operacionalmente aceptable, el DAR debe elegir CDC/outbox/dual compatibility explícita y definir cuál representación es autoritativa durante la transición. “No dual-write improvisado” es correcto, pero no sustituye una estrategia de catch-up.

### 14.3 Anchors analíticos

| Actual | Futuro |
| --- | --- |
| `confirmed_at` | `posted_at` para emisión/devengo; conservar original migrado y provenance |
| `paid_at` | Fecha de settlement efectivo total, derivada del último evento necesario |
| `cancelled_at` | `voided_at` con causalidad y lineage |
| revenue por confirmed | revenue/accrual por posted válido, neto de documentos/counterevents |
| cash por paid | Payments efectivos por `occurred_at`/CashSession |
| AR | posted/unpaid collectible; disputed separado; legacy anomalies fuera de buckets normales hasta elegibilidad/reparación |

## 15. Tests requeridos

### 15.1 Matriz funcional y de dominio

| Caso | Resultado esperado |
| --- | --- |
| Consulta abierta + edición | Clinical entries/events cambian; no Checkout primario ni Invoice posted. |
| Consulta cerrada | MR y Appointment cierran atómicamente; nace un Checkout primario con snapshot consistente. |
| Consulta `$0` | `completed/no_charge`, audit event, sin Invoice/Payment/stock retail. |
| Transacción financiera total `$0` | Solo si regla fiscal explícita; distinguirla de no-charge. |
| Receta completa | Selections accepted; post crea items/allocations exactos y fulfillment completo. |
| Receta parcial | Fulfillment parcial y remanente; suplemento posterior no reabre revisión histórica. |
| Receta rechazada | Selection declined con motivo opcional; no retail item/allocation. |
| Cambio de presentación Rx | Revalidación clínica/regulatoria y versión; no sobrepasa equivalencia/cap. |
| Stock Rx insuficiente | Post falla completo; Checkout sigue open; cero Invoice/Payment/allocation parcial. |
| Receta externa POS ausente | Add/finalize regulado rechazado según contrato R51. |
| Receta externa válida | Evidencia queda ligada al fingerprint efectivo y sobrevive post. |
| Cambio de item tras atestación | Evidencia se invalida o exige nueva atestación; stale post falla. |
| Producto clínico | Movement single-lot al uso; post no mueve stock otra vez. |
| Producto retail | Cero allocation open; allocations/movements solo al post. |
| POS | Checkout direct_sale sin MR; mismos invariantes financieros/stock. |
| Pago completo | Invoice posted/paid, Payments exactos, paid_at, CashSession consistente. |
| Pago multi-método | Un evento por línea, suma exacta, keys hijas canónicas. |
| Pago parcial normal | Rechazado sin Invoice/Payment parcial. |
| Crédito | posted/unpaid solo con política, terms/evidence/due_at y permiso. |
| Pago posterior de crédito | Saldo total exacto; paid; CollectionCase resuelto si aplica. |
| Void terminal | Solo posted/unpaid sin Payments; dispositions/audit; sin replacement. |
| Void + replacement | Un receipt/commit; rollback total en fallo; replay devuelve mismos IDs. |
| Refund | Counterevents correctos; stock solo según disposition explícita. |
| Refund reversal | Restaura efecto financiero sin duplicar stock/fulfillment. |
| `goods_retained` replacement | Reutiliza allocations originales; cero movement nuevo; Rx cuenta una vez. |
| `returned_restocked` replacement | Return y nueva entrega auditables; fulfillment según verdad R53. |
| Concurrent edit | Una versión gana; la otra recibe conflict sin efectos parciales. |
| Uno cobra y otro edita | Locks/version impiden total stale; exactamente un outcome. |
| Concurrent pay | Un receipt/event set; el otro replay/conflict; cero doble dinero/stock. |
| Readiness true y cambio posterior | POST revalida y falla sin efectos. |
| Stock cambia tras readiness | POST bloquea/consume estado actual o falla atómicamente. |
| Checkout stale version | `409`/precondition failure estable, respuesta con versión actual. |
| Mismo key, mismo command/payload canónico | Replay de respuesta original. |
| Mismo key, payload distinto | Conflict sin filtrar payload sensible. |
| Mismo raw key, command kind distinto | Commands independientes; Payments/eventos hijos no colisionan. |
| Clinical quantity increment | Primer precio/impuesto del ciclo se conserva. |
| Clinical decrement/delete | Eventos append-only; totales/provenance correctos. |
| Clinical reprice | Comando cierra ciclo y abre otro atómicamente con reason/actor/version. |
| Disputa pre-post | No Invoice; owner/SLA/eventos y acciones permitidas. |
| Enforced bajo términos | Invoice unpaid + CollectionCase open en un commit. |
| Partial legacy collectible | Pago exacto del saldo; preserva historia y termina paid. |
| Partial legacy no collectible | Command rechazado incluso con permiso; permanece quarantine/case. |
| Overpaid legacy | Reclass + return canónicos; revenue/stock no se alteran. |
| Draft + MR open | Solo seed/quarantine; close crea/adopta un primario. |
| Writer durante backfill | Freeze lo bloquea o catch-up lo procesa antes del flag. |
| Draft PDF/estimate | Resultado decidido en R56: endpoint nuevo o breaking removal explícito. |
| Cross-tenant receipt/case/evidence | Not found/forbidden sin existencia ni payload leakage. |
| Receipt tombstone | Replay/identidad conforme a retención; payload sensible eliminado. |

### 15.2 Gates de implementación

- Tests de caracterización legacy pasan antes de retirar rutas actuales.
- Contract tests del financial-event model pasan para Payment, refund, credit/reversal y liability return.
- Property tests de suma de settlement y cap Rx nunca permiten partial/overpaid futuro ni fulfillment duplicado.
- Tests transaccionales fuerzan error en cada paso de post, pay, close y replacement y comprueban rollback total.
- Tests de deadlock ejecutan pares de comandos en ambos órdenes sobre parents/hijos.
- Tests de migración son repetibles y además incluyen mutación entre batch y cutover.
- Reconciliación compara conteos, totales, anchors, Payments, movements, allocations y tenant ownership.
- Tests API/frontend cubren desaparición de draft, nuevas acciones y estados UX.
- Ningún flag de organización se activa con casos no clasificados, events no canónicos o source versions posteriores al watermark.

### 15.3 Pruebas de caracterización ejecutadas durante esta revisión

Se ejecutaron los suites legacy de atestación Rx, PDF, payment ledger, refund, prescription dispensing y cierre de MedicalRecord:

```text
python manage.py test \
  apps.billing.tests.test_rx_attestation \
  apps.billing.tests.test_invoice_pdf \
  apps.billing.tests.test_payment_ledger \
  apps.billing.tests.test_refund \
  apps.billing.tests.test_prescription_dispense \
  apps.medical_records.tests.test_close \
  --keepdb --noinput
```

Resultado: **85 tests, OK**. Esto no valida el modelo futuro; confirma que las obligaciones legacy citadas —incluyendo atestación externa y PDF draft— siguen siendo contratos vivos del repositorio actual.

## 16. Impacto de implementación

| Área | Impacto requerido |
| --- | --- |
| Backend | Agregados Checkout/charges/revisions/selections/cases/receipts; servicios terminales; evidencia Rx externa; repricing; projections y guards. |
| Frontend | UI por acciones/readiness; Checkout de consulta y POS; evidencia Rx; conflictos de versión; replacement/disputes/legacy; decisión de estimate. |
| DB | Constraints tenant-aware; lineage; receipts; allocations; cases; provenance; event identity; fulfillment effects; índices/locks y staging migratorio. |
| Inventory | Single-lot clínico v1; allocations post; tabla/proyección de disposiciones; reversas sin duplicación. |
| Analytics | `posted_at`, paid effective, net revenue, AR collectible/disputed, liability legacy, no-charge y provenance quality. |
| Permissions | Separar edit, close, reprice, post, credit, collect, void, replace, refund, legacy classification/repair y acceso a evidencia regulatoria. |
| Tests | Matriz anterior, concurrencia real, rollback, properties, compatibility, tenant isolation y cutover race. |
| Docs | Enmendar ADR p62, contrato financiero y relación con p26; actualizar módulos/API/runbooks/migración/retención. |

Este impacto no autoriza implementar todo simultáneamente. Una vez cerrados los contratos, conviene dividir por capability slices con compatibilidad controlada; el cutover y el ledger no pueden fragmentarse entre interpretaciones diferentes.

## 17. Preguntas de negocio

Solo quedan tres preguntas estrictamente de negocio; el resto son decisiones técnicas que el DAR debe resolver:

1. **Devolución de medicamento prescrito:** ¿en qué condiciones verificadas una devolución restaura cantidad legal disponible para dispensar de nuevo? ¿Producto sellado/reutilizable, cualquier retorno, o nunca?
2. **Documento previo al cobro:** ¿la clínica necesita entregar/imprimir un estimado de Checkout antes de emitir la Invoice, o puede retirarse el PDF draft actual?
3. **Cobro legacy:** ¿qué evidencia mínima convierte una obligación histórica parcial en deuda cobrable, y qué casos deben limitarse a devolución/resolución externa aunque el saldo matemático exista?

## Conclusión

El DAR actualizado **sí resuelve la ambigüedad fundamental de `draft`/`confirmed`** y ya ofrece una arquitectura defendible para Checkout, Invoice y Payment. Los cinco blockers anteriores están atendidos. Los cinco blockers actuales aparecen al integrar literalmente esa arquitectura con contratos reales que siguen vigentes y con transiciones que el texto aún no gobierna.

La recomendación es incorporar ADR-R51–ADR-R55 y cerrar ADR-R56–ADR-R58 antes de producir migraciones, modelos o endpoints. Con esas correcciones, el DAR podría pasar a implementación sin otra reestructuración central.
