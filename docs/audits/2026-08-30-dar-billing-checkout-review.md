# Revisión independiente del ADR — refactor de Billing / Checkout

**Fecha:** 2026-08-30  
**Segunda pasada crítica:** 2026-08-31  
**Documento revisado:** `docs/decisions/2026-08-30-p62-billing-checkout-lifecycle.md`  
**Auditoría de referencia:** `docs/audits/2026-08-30-billing-status-flow-audit.md`  
**Alcance:** revisión arquitectónica; no incluye implementación, migraciones ni cambios de código.

**Estado de esta versión:** incorpora la resolución explícita de cada hallazgo de la primera pasada. La tabla de la sección 4 es normativa: distingue qué se acepta, qué se acepta con alcance reducido, qué se fusiona y qué se rechaza como gap del ADR. Los defectos del código actual que p62 ya manda retirar se conservan como evidencia de implementación, pero no se contabilizan nuevamente como decisiones ausentes.

## 1. Veredicto

# REWORK

La dirección central del ADR es válida: separar la preparación comercial de la obligación financiera elimina la mayor parte de la ambigüedad de `Invoice.status='draft'`, y crear una `Invoice` inmutable únicamente al aceptar el cargo es más coherente que seguir usando la factura como carrito, hoja de trabajo clínica y cuenta por cobrar a la vez.

Sin embargo, el ADR todavía no es ejecutable de forma inequívoca. Hay decisiones estructurales sin cerrar en el orden de cierre de la consulta, mutabilidad de la receta, procedencia de líneas, momento de entrega y stock, semántica de `void`, crédito, aceptación del importe, lotes, cardinalidad de Checkouts, concurrencia y migración. Dos desarrolladores podrían implementar hoy comportamientos distintos —y ambos serían compatibles con el texto actual— en varios caminos que afectan dinero e inventario.

El veredicto no rechaza el agregado `Checkout`; exige una revisión focalizada del ADR antes de convertirlo en plan de implementación. No todos los hallazgos de la primera pasada sobreviven como blockers: varios ya estaban decididos en p62 y ahora quedan reclasificados explícitamente.

## 2. Executive Summary

1. `Invoice draft` sí mezcla hoy tres conceptos distintos: sincronización clínica, preparación comercial y documento financiero editable.
2. Un `Checkout` independiente es justificable, pero solo si se define como agregado comercial y no como una copia mutable de `Invoice` sin límites de propiedad.
3. `Invoice draft` puede eliminarse cuando todas sus responsabilidades actuales tengan un destino explícito; el ADR todavía no cubre todas.
4. `confirmed` puede desaparecer como nombre, pero no pueden perderse el freeze documental, el momento de devengo, `confirmed_at`, la creación de cuenta por cobrar ni el vínculo con stock.
5. Recomiendo el término de dominio `issued`/`emitida`, no `posted`, salvo que el producto defina expresamente una contabilización real. El sistema no tiene libro mayor contable ni emisión fiscal integrada.
6. `Checkout.completed` debe significar únicamente “la preparación terminó de forma irreversible”, con un resultado histórico; no debe cambiar cuando posteriormente se pague una factura a crédito.
7. `readiness` es derivado y útil para UX, pero no es una precondición durable: stock, lotes, caja, permisos, receta y configuración pueden cambiar sin incrementar `checkout_version`.
8. Todo comando final debe volver a validar bajo locks y en una única transacción; `GET readiness → POST finalize` tiene riesgo TOCTOU si se trata el GET como garantía.
9. El orden actual de `close_medical_record` crea la factura antes de materializar protocolos como vacuna. Copiar ese orden al nuevo Checkout puede omitir cargos y procedencia clínica creados durante el propio cierre.
10. La receta y sus ítems siguen siendo mutables después del cierre del `MedicalRecord`; el ADR no define cómo se congela o versiona esa fuente.
11. `PrescriptionSelection` pertenece al Checkout como decisión comercial, pero `accepted_full/accepted_partial` debe derivarse de asignaciones de ítems, no duplicarse como estado manual susceptible a drift.
12. El código ya tiene una cuenta por cobrar mínima (`confirmed` sin pagos + `remaining_balance` + KPI AR), pero no tiene política de crédito, vencimiento, aging ni autorización. Formalizar crédito amplía el alcance.
13. `Payment` ya es una línea de medio de pago append-only; un pago split crea varios `Payment`. El ADR no debe redefinirlo silenciosamente como un único evento agrupador.
14. El mapping de datos históricos no es unívoco para `draft $0`, `draft` de consulta abierta, `cancelled` sin historial suficiente y `confirmed` con pagos. Es necesaria cuarentena determinista.
15. Falta definir quién acepta el importe final y qué evidencia convierte un Checkout preparado en una obligación, especialmente en `issue_on_account`; autorización interna y aceptación comercial no son el mismo hecho.
16. La arquitectura puede avanzar después de cerrar los hallazgos aceptados de este informe y actualizar el ADR con contratos verificables de estado, transacción, migración, stock, aceptación, permisos y API.

### Base de evidencia revisada

La revisión siguió la prioridad código → tests → contratos/API → documentación → ADR. Se inspeccionaron, entre otros:

- Billing: `backend/apps/billing/models.py`, `services.py`, `views.py`, `serializers.py`, `urls.py`, `permissions.py`, sus tests de state machine, ledger, concurrencia, dispensación, anchors y refunds.
- Medical Records e Inventory: `MedicalRecord`, `MedicalRecordService`, `MedicalRecordProduct`, `close_medical_record`, materializadores de protocolos, `cost_behavior`, consumo/restock y ledger de stock.
- Appointments: servicio de completion, signal `create_draft_invoice_on_done` y `auto_create_invoice_on_done`.
- Prescriptions: modelos, serializers y endpoints de creación, PATCH, alta y borrado de ítems.
- Frontend: `pages/billing.jsx`, POS, cierre de consulta, cliente API de Billing y editores de pago.
- Analytics/Cash: snapshots, anchors, AR, `MetricAdjustment`, `CashSession` y contrato de eventos financieros.

La documentación describe correctamente muchos comportamientos, pero el código muestra divergencias relevantes. Por ejemplo, `close_medical_record` crea la factura antes de materializar protocolos ([views.py:438](../../backend/apps/medical_records/views.py#L438)); `PrescriptionSerializer.update` reemplaza ítems sin comprobar que la consulta esté cerrada ([serializers.py:155](../../backend/apps/prescriptions/serializers.py#L155)); y `InvoiceListCreateView` permite crear una factura por el endpoint genérico ([views.py:69](../../backend/apps/billing/views.py#L69)).

**Validación ejecutada:** 93 tests existentes de payment ledger, concurrencia de Invoice, dispensación de receta, refunds, cierre de MedicalRecord y materialización de consultation draft; resultado `OK` en PostgreSQL (`Ran 93 tests in 204.386s`). Estos tests confirman el comportamiento actual, no validan todavía el ADR propuesto.

## 3. Qué está bien

### Separación conceptual

- Separar `Checkout lifecycle`, `Invoice lifecycle` y liquidación monetaria ataca la causa, no solo los nombres de estados.
- Una `Invoice` creada como documento inmutable evita que una obligación financiera siga cambiando por ediciones clínicas o comerciales posteriores.
- Mantener `Payment`, `RefundPayment`, `RefundReversal` y `CreditNote` como eventos/documentos append-only es consistente con `docs/financial-event-model-contract.md`.
- Tratar `payment_status` como proyección del ledger es mejor que usar un flag libre.

### Flujo clínico

- La regla `MedicalRecord OPEN → no Invoice emitida` es correcta y debe convertirse en invariante del writer autoritativo.
- Crear el Checkout de consulta al cierre, en vez de crear una factura al primer cargo, elimina la sincronización oportunista que hoy ocurre desde varios writers.
- Retirar `auto_create_invoice_on_done` es correcto. El signal actual puede crear o vincular una factura al marcar una cita `done`, incluso eligiendo el último expediente asociado ([signals.py:10](../../backend/apps/billing/signals.py#L10)).

### `$0`, readiness y POS

- Distinguir una consulta sin transacción financiera de una factura financiera es correcto.
- Evitar `Checkout.status='ready'` también es correcto: la preparación puede estar abierta y lista ahora, pero dejar de estarlo por cambios externos.
- Persistir el carrito POS en el servidor es coherente con concurrencia, recuperación y auditoría; hoy el POS mantiene el carrito local y solo crea la factura `draft` al presionar Cobrar ([index.jsx:103](../../frontend/src/pages/pos/index.jsx#L103)).

### Migración y observabilidad

- Conservar `confirmed_at` como `posted_at`/`issued_at`, `paid_at` y la provenance de anchors es indispensable y el ADR lo reconoce.
- La idea de cuarentena para filas ambiguas es correcta; el error sería forzar un mapping aparentemente limpio perdiendo verdad histórica.
- La separación entre revenue accrual, cash revenue y AR está alineada con las métricas existentes.

## 4. Resolución de hallazgos

### 4.1 Matriz normativa de aceptación y rechazo

Esta matriz reemplaza la clasificación de la primera pasada. `Aceptar` significa que p62 debe incorporar una decisión o invariante que hoy no está suficientemente cerrada. `Aceptar con ajuste` conserva el riesgo, pero corrige alcance o solución. `Fusionar` evita contar dos veces un mismo problema. `Rechazar como gap` no niega el defecto del código actual: indica que p62 ya tomó la decisión futura y el pendiente pertenece al plan de implementación/cutover.

| ID | Resolución | Severidad final | Justificación | Acción para p62 |
| -- | ---------- | ---------------- | ------------- | ---------------- |
| ADR-R01 | **ACEPTAR CON AJUSTE** | **BLOCKER** | El riesgo de snapshot incompleto es real porque hoy Invoice se crea antes de materializar protocolos. La invariante necesaria es materializar y congelar antes de snapshotear Checkout, todo en una transacción. No se fija innecesariamente si el atributo `MR.closed` se asigna antes o después dentro de esa transacción; el límite autoritativo es el commit. | Especificar `materialización completa → freeze/snapshot → Checkout` y rollback total. |
| ADR-R02 | **FUSIONAR** con R04/R26 | **HIGH** | p62 ya declara readiness derivado, revalidación de stock bajo lock, versión y orden canónico. Falta enumerar dependencias externas y su estrategia de lock/version, no rediseñar readiness. | Añadir una tabla por dependencia: Checkout, Prescription/source version, stock/lote, CashSession, settings y autorización. |
| ADR-R03 | **RECHAZAR COMO GAP** | **N/A — impacto de implementación** | p62 ya establece que Invoice nace solo al postear, prohíbe POST/PATCH genéricos y enumera el retiro de creación genérica, confirm/direct-pay y signal. Los múltiples writers actuales siguen siendo evidencia crítica del cutover. | Mantener el inventario de writers como checklist de implementación y prueba de defensa `MR closed`. |
| ADR-R04 | **ACEPTAR** | **BLOCKER** | Prescription y sus ítems pueden mutar o reemplazarse después del cierre. Sin freeze, versión o addendum, un Checkout puede referenciar una fuente distinta de la aceptada. | Elegir freeze, versionado o addenda; toda Invoice referencia snapshot/version inmutable. |
| ADR-R05 | **ACEPTAR** | **HIGH** | Persistir `accepted_full/partial` además de cantidad/presentación crea dos fuentes de verdad. | Persistir `pending/declined/accepted`; derivar full/partial en unidades base desde items/allocations. |
| ADR-R06 | **ACEPTAR CON AJUSTE** | **HIGH** | p62 ya define `source/source_object`, ownership y una tabla de comportamiento de stock. Falta convertir esa semántica en contrato persistido/constraint y prohibir merge entre provenances. | Exigir `source_kind/source_id` y `stock_behavior` congelados, o una derivación cerrada equivalente con constraints. |
| ADR-R07 | **ACEPTAR** | **BLOCKER** | Anular AR y restockear automáticamente no demuestra devolución física. La deuda puede desaparecer mientras el cliente conserva el producto. | Definir fulfillment/disposition por línea; `void` nunca repone stock por sí solo. |
| ADR-R08 | **RECHAZAR COMO GAP** | **N/A — decisión condicional futura** | p62 conserva Payment 1:N y split por medios; no redefine Payment como grupo. `PaymentBatch/Settlement` solo se justifica si existe un caso de recibo, conciliación o reverso agrupado. | No agregar entidad de agrupación sin requisito explícito. Documentar únicamente que un comando puede producir 1..N Payments. |
| ADR-R09 | **ACEPTAR CON ALCANCE REDUCIDO** | **MEDIUM** | Partial/overpaid son clasificaciones útiles para auditoría y migración, pero estados inválidos para nuevos writes bajo la política sin pagos parciales. Exponerlos como lifecycle normal legitimaría corrupción. | Mantener `payment_status=unpaid/paid` para datos válidos y añadir `settlement_anomaly=partial/overpaid` como diagnóstico/quarantine. |
| ADR-R10 | **ACEPTAR CONDICIONALMENTE** | **BLOCKER si crédito entra en v1** | `issue_on_account` formaliza crédito y exige elegibilidad, autorización, vencimiento, límites y cobranza. Si crédito sale de v1, el blocker desaparece del flujo nuevo pero permanece para legacy confirmed. | Decidir alcance; si entra, completar política. Si no, retirar el comando nuevo y conservar clasificación legacy. |
| ADR-R11 | **ACEPTAR** | **HIGH** | Ausencia de operación cobrable y total cero por cortesía/descuento son hechos distintos. | Separar `no_billable/included/declined` de `zero_value_financial_transaction` y decidir tratamiento documental/fiscal. |
| ADR-R12 | **FUSIONAR / BAJAR** | **MEDIUM** | p62 ya define `completed` terminal y reglas principales de abandono. Falta cerrar catálogo de razones y guards exhaustivos, no redefinir el lifecycle. | Añadir matriz de guards y `reason_code`; conservar la semántica ya decidida. |
| ADR-R13 | **ACEPTAR** | **HIGH** | Un Checkout primario y dispensaciones posteriores requieren cardinalidad y deduplicación explícitas. | Definir MR 1:N con exactamente un `primary_consultation` y kinds suplementarios, o un agregado separado. |
| ADR-R14 | **ACEPTAR CON AJUSTE** | **HIGH** | La integridad referencial y tenant deben ser explícitas. El riesgo de GenericForeignKey es preventivo, no evidencia de que p62 ya lo haya elegido. | Prohibir referencia genérica sin constraints; preferir FKs explícitas + XOR/unique tenant-aware. |
| ADR-R15 | **ACEPTAR CON AJUSTE** | **HIGH** | El sistema ya sabe repartir FEFO entre lotes en `consume_product(lot=None)`. El problema es que la dispensación fija `first_consumable_lot` y InvoiceItem solo conserva un lote. | Reutilizar el motor multilote existente y persistir allocations ligadas a la línea/StockMovement para reversos exactos. |
| ADR-R16 | **ACEPTAR FOCALIZADO** | **BLOCKER** | p62 ya contempla clasificador, dry-run y cuarentena, pero algunos buckets propuestos aún auto-inferían `no_charge` o Checkout válido sin evidencia suficiente. | Corregir únicamente buckets ambiguos; ninguna fila sin provenance/estado previo probado se auto-mapea. |
| ADR-R17 | **ACEPTAR** | **HIGH** | Falta fórmula implementable para netear accrual por void/credit sin reescribir snapshots congelados. | Definir métrica, fecha de atribución, adjustment, schema version y reconciliación. |
| ADR-R18 | **RECHAZAR COMO GAP** | **N/A — impacto de implementación** | p62 ya contiene permisos por comando, defaults de rol y acumulación de capacidades. El código actual sigue incumpliendo ese diseño. | Conservar como checklist de seeds, permisos, endpoints y tests; no contarlo como decisión ausente. |
| ADR-R19 | **ACEPTAR CON AJUSTE** | **HIGH** | p62 exige idempotencia a comandos financieros y versión en mutaciones, pero no cierra replay/payload conflict para todos los terminales, incluidos no_charge/abandon. | Definir key + payload hash, replay idéntico, conflicto por key reutilizada y 409 por versión stale. |
| ADR-R20 | **ACEPTAR COMO SUGERENCIA** | **LOW** | `issue-on-account` y `abandon` comunican mejor la intención; no es un defecto estructural. | Aplicar glosario y naming al contrato API/UI después de cerrar semántica. |
| ADR-R21 | **ACEPTAR COMO PRECISIÓN** | **MEDIUM** | p62 ya exige mutation log y before/after. Falta el mínimo schema del evento y causalidad. | Especificar `CheckoutEvent` append-only o contrato equivalente con actor, command, version, reason, idempotency y diff/snapshot. |
| ADR-R22 | **ACEPTAR COMO REQUISITO OPERATIVO** | **MEDIUM** | p62 ya define owner, version, expires_at, recuperación y abandono. Falta garantizar expiración server-side y takeover idempotente; el TTL exacto puede seguir configurable. | Añadir job/política server-side; heartbeat solo si se demuestra necesario. |
| ADR-R23 | **RECHAZAR COMO GAP** | **N/A — ya decidido** | p62 prohíbe editar/borrar líneas `clinical_*` desde Checkout y asigna recepción únicamente a retail. | Mantener tests de no mutabilidad; eliminar la pregunta “qué campos clínicos edita recepción”. |
| ADR-R24 | **RECHAZAR COMO DEFECTO** | **LOW — preferencia terminológica** | p62 define posted como obligación interna, devengo y entrega, y excluye fiscalidad/GL. `Issued` puede ser más claro, pero no hay ambigüedad normativa si el glosario se conserva. | Elegir nombre por lenguaje de producto; no bloquear la arquitectura por este punto. |
| ADR-R25 | **ACEPTAR Y ELEVAR** | **CRITICAL — defecto actual** | `process_refund` restockea cualquier InvoiceItem con presentation sin distinguir consumo clínico de fulfillment retail. Puede crear stock ficticio hoy. | Corregir antes o como gate del refactor; legacy sin provenance segura no puede restockear automáticamente. |
| ADR-R26 | **ACEPTAR CON AJUSTE** | **BLOCKER** | El orden global debe existir antes de implementar nuevos comandos. El ejemplo del informe no se acepta aún como orden definitivo: debe derivarse y probarse contra el contrato vigente de Inventory/Cash. | Publicar matriz de locks por comando y tests ABBA; ningún endpoint improvisa el orden. |
| ADR-R27 | **ACEPTAR — NUEVO** | **BLOCKER de negocio** | El diseño afirma que Invoice representa una obligación “aceptada”, pero no define quién acepta el importe ni qué evidencia se conserva. Autorizar internamente crédito no equivale a aceptación comercial del cliente. | Decidir si pagar implica aceptación; para `issue_on_account` definir aceptante/evidencia, actor que captura, timestamp, canal y reglas de override. |

Resumen de resolución:

- **15 correcciones sustantivas aceptadas:** R01, R04, R05, R07, R10, R11, R13–R17, R19, R25, R26 y R27.
- **6 hallazgos fusionados o reducidos:** R02, R06, R09, R12, R21 y R22.
- **6 hallazgos retirados como gap o conservados solo como nota:** R03, R08, R18, R20, R23 y R24.

### 4.2 Registro de la primera pasada — evidencia no normativa

La tabla siguiente conserva el razonamiento y las referencias de la primera pasada para trazabilidad. Su columna de severidad queda **superada por la matriz 4.1** y no debe utilizarse para contar blockers ni para definir alcance.

| ID | Severidad de primera pasada | Problema | Evidencia | Recomendación original |
| -- | --------- | -------- | --------- | ------------- |
| ADR-R01 | **BLOCKER** | El ADR no fija el orden transaccional del cierre clínico. El código cierra el MR, crea Invoice, completa Appointment y después materializa protocolos. Una vacuna puede crear `MedicalRecordProduct`, consumir stock y generar cargo dentro de esa materialización. Un Checkout snapshot tomado antes queda incompleto. | `close_medical_record` [views.py:438](../../backend/apps/medical_records/views.py#L438); `_materialize_vaccine` y `add_medical_record_product` [services.py:48](../../backend/apps/medical_records/services.py#L48); test de materialización [test_consultation_draft.py:148](../../backend/apps/medical_records/tests/test_consultation_draft.py#L148). | Definir una única operación atómica: lock MR → validar → materializar protocolos/cargos → congelar fuentes clínicas → marcar closed → completar Appointment → crear/snapshotear Checkout. Cualquier fallo revierte todo. |
| ADR-R02 | **BLOCKER** | `checkout_version` no cubre dependencias externas. Stock, lote, caja, permisos, settings y receta pueden cambiar después de `GET readiness`. | Stock se valida primero al dispensar y autoritativamente al confirmar; CashSession se lockea antes de Invoice [services.py:279](../../backend/apps/billing/services.py#L279); la receta es mutable por PATCH/alta/borrado de ítems [views.py:44](../../backend/apps/prescriptions/views.py#L44). | Declarar readiness como asesoría. El comando final debe lockear, comparar versión y revalidar todas las invariantes externas en la misma transacción antes de escribir Invoice/Payment/StockMovement. |
| ADR-R03 | **BLOCKER** | No basta con retirar el signal. Hoy hay múltiples caminos de creación/sincronización de Billing: servicio clínico, producto clínico, cierre, dispensación, signal de cita y POST genérico de Invoice. Cualquiera que sobreviva puede permitir `MedicalRecord open + Invoice issued`. | Callers de `get_or_create_invoice_for_medical_record`: `add_medical_record_product`, `MedicalRecordServiceListCreateView`, `close_medical_record`, `dispense_prescription_into_invoice`; además [signals.py:10](../../backend/apps/billing/signals.py#L10) y [views.py:69](../../backend/apps/billing/views.py#L69). `confirm_invoice` no verifica MR cerrado [services.py:145](../../backend/apps/billing/services.py#L145). | Hacer que el único writer de Invoice de consulta sea `finalize_checkout`. Retirar o cerrar todos los caminos genéricos y añadir guard de defensa `source MR closed` en el servicio financiero. |
| ADR-R04 | **BLOCKER** | El ADR asume una fuente de receta estable, pero `Prescription` y `PrescriptionItem` pueden modificarse después de cerrar el MR y después de preparar el Checkout. | `PrescriptionDetailView` admite PATCH [views.py:44](../../backend/apps/prescriptions/views.py#L44); `PrescriptionSerializer.update` borra y recrea ítems [serializers.py:155](../../backend/apps/prescriptions/serializers.py#L155); endpoints de alta/borrado no verifican estado del MR [views.py:76](../../backend/apps/prescriptions/views.py#L76). | Definir si la receta se congela al cierre, se versiona, o se emite una nueva revisión. El Checkout debe referenciar una versión/snapshot inmutable; cualquier cambio válido debe invalidar o reconstruir explícitamente decisiones pendientes. |
| ADR-R05 | **HIGH** | `PrescriptionSelection` mezcla decisión, cantidad, presentación y estado full/partial. Esos datos también vivirán en `CheckoutItem`, creando dos fuentes de verdad. | El código actual deriva el cap comparando ítems dispensados por `dispensed_from_prescription_item` y cantidades base [services.py:936](../../backend/apps/billing/services.py#L936). | Modelar la decisión como entidad hija del Checkout (`pending/declined/accepted`) y las presentaciones/cantidades como uno o más CheckoutItems vinculados. Derivar full/partial de la suma aceptada en unidades base. |
| ADR-R06 | **BLOCKER** | Falta una clasificación de provenance/stock por línea. Un mismo `presentation` puede ser insumo clínico ya consumido o producto retail pendiente de entrega; el código actual usa un FK nullable como discriminador. | `_items_settling_stock` distingue por `invoice_type` y `dispensed_from_prescription_item` [services.py:82](../../backend/apps/billing/services.py#L82); el test evita doble consumo [test_prescription_dispense.py:118](../../backend/apps/billing/tests/test_prescription_dispense.py#L118). | Cada CheckoutItem/InvoiceItem debe congelar `source_kind`, `source_id`, `stock_behavior` y snapshot de precio. No inferir stock de nullabilidad. No fusionar líneas con provenance distinta. |
| ADR-R07 | **BLOCKER** | `posted/unpaid` implica en el ADR que el producto retail fue entregado y el stock salió, pero `void` no exige demostrar devolución física ni disposition. Se puede borrar AR y reponer stock de un producto que el cliente conserva. | `cancel_invoice` actual revierte automáticamente stock para confirmed sin pagos [services.py:389](../../backend/apps/billing/services.py#L389). El ADR conserva ese patrón conceptualmente. | Definir que `issue_on_account` solo existe si entrega y crédito ocurren juntos. `void` de una factura con fulfillment debe requerir devolución por línea (`restock/discard/not_returned`) o usar CreditNote/return; nunca restock implícito. |
| ADR-R08 | **HIGH** | El ADR describe `Payment` como evento de pago, pero el contrato real crea un `Payment` por medio. Un split cash/card crea dos Payments con el mismo timestamp. No existe `PaymentLine` persistida. | `_pay_locked_invoice` crea un Payment por línea [services.py:331](../../backend/apps/billing/services.py#L331); test split espera dos filas [test_payment_ledger.py:86](../../backend/apps/billing/tests/test_payment_ledger.py#L86). | Preservar el contrato frozen. Si se necesita agrupar el comando de cobro, agregar un concepto explícito `Settlement/PaymentBatch` o `group_id`; no redefinir `Payment`. |
| ADR-R09 | **HIGH** | `payment_status = unpaid/paid` es binario y no representa datos legacy parciales, sobrepagos corruptos ni reconciliación. | `remaining_balance` ya se deriva de Σ Payments [models.py:32](../../backend/apps/billing/models.py#L32); el contrato admite la clasificación matemática aunque el writer actual rechaza parciales [test_payment_ledger.py:110](../../backend/apps/billing/tests/test_payment_ledger.py#L110). | Derivar `settlement_status = unpaid/partially_paid/paid/overpaid` para integridad y migración. La política de producto puede seguir permitiendo solo unpaid→paid. No persistir salvo proyección cacheada con writer único. |
| ADR-R10 | **HIGH** | El ADR convierte en capacidad formal de crédito lo que hoy es solo una Invoice `confirmed` sin pago. Faltan elegibilidad, autorización, vencimiento, aging, límites y cobranza. | El dashboard calcula AR sobre `status='confirmed'`; test demuestra `800 → 0` al pagar [test_summary_endpoint.py:353](../../backend/apps/dashboard/tests/test_summary_endpoint.py#L353). No hay payment terms ni due date en Invoice. | Decidir si crédito entra en este refactor. Si no, retirar `post-unpaid` del primer release y mantenerlo solo para migración. Si sí, definir permiso, cliente elegible, `due_at`, motivo y auditoría. |
| ADR-R11 | **HIGH** | El ADR equipara `total == 0` con “no hubo transacción”. Una cortesía o descuento 100% sí puede ser una decisión financiera que requiera documento, descuento y audit trail. | InvoiceItem permite descuentos y el total se calcula en backend; el ADR propone no Invoice para todo `$0`. | Separar `no_billable_items/included_only/declined_retail` de `zero_value_financial_transaction`. La segunda requiere decisión de producto/fiscal y, posiblemente, Invoice emitida de total cero. |
| ADR-R12 | **HIGH** | `completed` y `abandoned` todavía permiten interpretaciones distintas, especialmente “cliente se fue” y “Checkout creado por error”. | El ADR usa `completion_kind`, pero no fija guards exhaustivos entre cargos clínicos, decisión pendiente y ausencia de Invoice. | Definir `completed` como terminal de preparación y resultado histórico inmutable. `abandoned` exige `reason_code`, cero Invoice y ausencia de cargos obligatorios sin resolver. |
| ADR-R13 | **HIGH** | “Un Checkout primario por MR” entra en tensión con Checkouts posteriores para dispensaciones tardías de receta. La relación MR↔Checkout no queda definida. | El ADR menciona un Checkout primario y también un Checkout posterior vinculado a Prescription. | Elegir cardinalidad: MR 1:N Checkouts con exactamente uno `kind=primary_consultation`, o separar el checkout suplementario de la relación primaria. Definir cómo se muestran y cómo se evita doble cobro. |
| ADR-R14 | **HIGH** | `source_type/source_object` es ambiguo y puede terminar como GenericForeignKey sin integridad referencial ni enforcement multi-tenant. | Los modelos actuales usan FKs explícitas a Appointment, MedicalRecord y PrescriptionItem, aunque incompletas. | Preferir FKs explícitas + CHECK XOR para fuentes soportadas. Todos los hijos deben llevar organization y validar misma org; constraints únicas deben incluir tenant y tipo de fuente. |
| ADR-R15 | **HIGH** | No se resuelve fulfillment multi-lote. CheckoutSelection elige una presentación, pero una cantidad puede requerir dos lotes. InvoiceItem actual solo tiene un `lot`. | Dispensación fija `first_consumable_lot`; InvoiceItem tiene un lote y unicidad por invoice/presentation [models.py:231](../../backend/apps/billing/models.py#L231). | Definir asignaciones de stock por línea (`StockAllocation/FulfillmentLine`) o permitir líneas por presentación+lote. Readiness y finalize deben operar en unidades base y por lote. |
| ADR-R16 | **BLOCKER** | La migración propuesta no tiene mapping unívoco para `draft` de consulta abierta con ítems, `draft $0` cerrado, `confirmed` con Payments, ni `cancelled` cuyo estado previo no sea recuperable. | Los cuatro estados actuales colapsan preparación y obligación; `InvoiceAuditLog` solo registra transiciones y puede no cubrir legacy [models.py:383](../../backend/apps/billing/models.py#L383). | Definir clasificador por fila con reglas, conteos previos, dry-run, cuarentena y reconciliación. Ningún caso ambiguo debe auto-mapearse a no_charge/paid/voided. |
| ADR-R17 | **HIGH** | El mapping de `confirmed_at` a accrual está bien, pero el neteo por `void` no tiene contrato implementable para snapshots congelados. Refunds hoy solo escriben adjustment de `revenue_paid`. | `compute_daily_metrics` usa `confirmed_at` para accrual [services.py:198](../../backend/apps/analytics/services.py#L198); `process_refund` escribe solo `revenue_paid` [services.py:574](../../backend/apps/billing/services.py#L574). | Definir fórmula exacta de `revenue_accrual_net`, MetricAdjustment para void/credit note, schema version, dual-write/backfill y fecha a la que se atribuye el reverso. |
| ADR-R18 | **HIGH** | Los permisos actuales no separan preparar, crear obligación y mover dinero; VET y ASSISTANT tienen `invoice.create/confirm/pay/cancel`. | Catálogo y roles [permissions_codes.py:50](../../backend/apps/core/permissions_codes.py#L50), [permissions_codes.py:175](../../backend/apps/core/permissions_codes.py#L175). | Crear permisos de comando: checkout create/edit, finalize paid, issue on account, complete no charge, abandon, invoice pay, invoice void, refund. Fijar defaults por rol y ownership por source. |
| ADR-R19 | **HIGH** | La API propuesta no define idempotencia para finalizar/no_charge/abandon/void ni reutilización de key con payload distinto. Tampoco define errores de versión vs blockers. | La idempotencia actual existe en Payment/Refund, no en confirm/cancel; las rutas actuales mezclan PATCH/POST [urls.py:1](../../backend/apps/billing/urls.py#L1). | Todos los comandos irreversibles usan POST + idempotency key + hash de payload. `expected_version`/If-Match obligatorio; 409 para conflicto/stale, respuesta con estado actual y blockers. |
| ADR-R20 | **MEDIUM** | `post-unpaid` es lenguaje técnico y `cancel` de Checkout vuelve a mezclar cancelación financiera con abandono de preparación. | Endpoints conceptuales del ADR. | Usar lenguaje de negocio: `issue-on-account`, `complete-no-charge`, `abandon`; reservar `void` para Invoice emitida sin pago y `refund` para dinero ya movido. |
| ADR-R21 | **HIGH** | La auditoría propuesta no especifica cambios de ítems, decisiones de receta, versión, actor y causalidad. El audit actual de Invoice solo guarda estado anterior/nuevo y notas. | `InvoiceAuditLog` [models.py:383](../../backend/apps/billing/models.py#L383). | Definir `CheckoutEvent` append-only con org, actor, command, version_before/after, reason, idempotency key y diff/snapshot mínimo; conservar eventos financieros separados. |
| ADR-R22 | **HIGH** | El Checkout POS persistente no tiene TTL/lease ni política confiable de abandono. El cleanup por unload actual ya es best-effort. | POS cancela en cleanup y al volver al carrito [index.jsx:63](../../frontend/src/pages/pos/index.jsx#L63), [index.jsx:182](../../frontend/src/pages/pos/index.jsx#L182). | Definir expiración server-side, heartbeat opcional, recuperación, quién puede tomar una venta y job idempotente de abandono. No depender de `beforeunload`/cleanup. |
| ADR-R23 | **BLOCKER** | No está definido quién puede modificar líneas originadas clínicamente. Permitir a recepción cambiar cantidad/presentación/provenance reabre el bug actual con otra entidad. | Hoy PATCH de InvoiceItem permite campos estructurales mientras Invoice está draft [serializers.py:74](../../backend/apps/billing/serializers.py#L74), y la política clínica solo protege writers del MR. | Las líneas snapshot clínicas deben ser no editables en identidad/cantidad. Solo ajustes comerciales explícitos (p. ej. descuento con permiso) pueden cambiar. Retail y líneas manuales tienen reglas distintas. |
| ADR-R24 | **MEDIUM** | `posted` sugiere asiento contable o timbrado, pero el sistema solo congela una obligación interna y arranca accrual. | No existe GL ni integración fiscal en el alcance; `confirmed_at` es hoy anchor de revenue accrual. | Usar `issued`/`emitida` o definir en glosario que `posted` significa exclusivamente “obligación comercial interna aceptada”, no factura fiscal ni asiento contable. |
| ADR-R25 | **HIGH** | El refund actual puede restockear cualquier InvoiceItem con presentation, incluso una línea clínica cuyo stock salió al consumir en la consulta. El ADR no exige corregir esta frontera antes de reutilizar el flujo. | `process_refund` hace restock si `disposition=restock` e `item.presentation_id`, sin revisar provenance [services.py:574](../../backend/apps/billing/services.py#L574). | Solo fulfillment retail retornado puede reingresar stock. Una corrección monetaria de consumo clínico no repone inventario automáticamente; requiere operación clínica/stock separada y auditable. |
| ADR-R26 | **BLOCKER** | Falta un orden global de locks para CashSession, MR/Prescription, Checkout, Invoice y stock. Sin él, los nuevos comandos pueden introducir ABBA respecto del contrato actual. | Orden actual: CashSession → MedicalRecord → Invoice → Product/StockLot → InvoiceItem/MRP; pagos ya lockean caja antes de Invoice [services.py:279](../../backend/apps/billing/services.py#L279). | Congelar un orden nuevo antes de diseñar services y tests. Ejemplo: CashSession → MedicalRecord/Prescription → Checkout → Invoice → Product/StockLot → líneas/eventos. Ningún endpoint debe improvisarlo. |

## 5. Decisiones del ADR confirmadas

### 5.1 Checkout independiente, con condiciones

Se confirma la opción A frente a una `Invoice` editable si se cumplen estas condiciones:

- `Invoice` pasa a significar exclusivamente documento comercial/financiero emitido e inmutable.
- Checkout no replica todo el lifecycle financiero; termina cuando produce un resultado.
- Los ítems conservan provenance y comportamiento de stock explícitos.
- La relación y snapshot de las fuentes clínicas son estables.
- No se usa Checkout para ocultar una nueva factura `draft` con otro nombre.

Comparación:

| Alternativa | Ventajas | Costes/riesgos | Evaluación |
| --- | --- | --- | --- |
| A. Checkout independiente | Separa preparación, Rx, no_charge y POS de la obligación; Invoice nace inmutable; queue operacional clara. | Nuevo agregado, migración, duplicación de snapshots, permisos, auditoría y concurrencia. | **Recomendada**, si se cierran los hallazgos aceptados en 4.1. |
| B. Invoice editable | Menor cambio de DB/API/UI; preserva IDs y flujos actuales. | Conserva la contradicción “factura que aún no existe financieramente”, hace difícil no_charge y mantiene acoplamiento clínico. | Aceptable solo si el producto decide que Invoice no es documento financiero hasta emitirla y renombra explícitamente esa fase; no es la dirección preferida. |
| C. SalesOrder/ChargeSet | `SalesOrder` expresa compromiso comercial; `ChargeSet` expresa cargos clínicos. | `ChargeSet` no cubre bien POS/Rx; `SalesOrder` puede implicar compromiso antes de que el cliente decida. | Útiles como vocabulario parcial, no sustituyen tan bien el espacio de decisión. |

### 5.2 Eliminación de `Invoice draft`

Puede eliminarse del modelo nuevo, pero no simplemente borrando el choice.

| Uso actual de `draft` | ¿Lo necesita Checkout? | ¿Lo necesita Invoice? | ¿Puede eliminarse? |
| --- | --- | --- | --- |
| Cabecera editable y datos de cliente/source | Sí | Solo snapshot final | Sí, después de migrar responsabilidad. |
| Agregar/editar/eliminar ítems | Sí, con reglas por provenance | No | Sí. |
| Sincronizar MedicalRecordService/Product | No como sync continuo; vive en fuente clínica hasta cierre y se snapshottea | No | Sí. |
| Decidir dispensación de receta | Sí | Solo resultado inmutable | Sí. |
| Carrito POS recuperable | Sí | No | Sí. |
| Readiness/prechecks | Sí, derivados | No | Sí. |
| Freeze comercial y creación de AR | Comando final | Sí, al nacer | Sí. |
| Gate de salida de stock retail | Comando final | Guarda evidencia, no decide | Sí. |
| Cancelación antes de obligación | `abandon` | No | Sí. |
| Auditoría de ediciones | CheckoutEvent | Invoice audit solo eventos financieros/documentales | Sí. |
| Preview/PDF previo al cobro | Resumen/quote de Checkout | No “factura” | Sí, con nuevo artefacto. |
| Idempotencia y concurrencia POS | Checkout + comando final | Unicidad 1:1 con Checkout | Sí. |

### 5.3 Eliminación de `confirmed`

El nombre puede desaparecer, pero sus responsabilidades se mueven así:

| Responsabilidad actual | Destino recomendado |
| --- | --- |
| Freeze de líneas/total | Invoice creada inmutable |
| `confirmed_at` | `issued_at` (o `posted_at` si se define el término) |
| Revenue accrual | Anchor `issued_at`, neto de void/credit adjustments según contrato |
| Cuenta por cobrar | Invoice emitida + `remaining_balance > 0` |
| Stock de retail | Transacción de finalización/fulfillment, no el estado en sí |
| Readiness | Derivada en Checkout |
| Cancelación pre-pago | `Invoice.voided` con reglas de retorno/disposition |

`confirmed_at` es una métrica de negocio: inicio de obligación/devengo y base para tiempo-a-pago. No debe desaparecer ni reducirse a un log difícil de consultar. Para datos legacy se conserva su valor y provenance; para nuevos se renombra explícitamente.

### 5.4 Ledger y refunds

- Conservar `Payment`, `CreditNote`, `RefundPayment` y `RefundReversal`.
- Conservar `remaining_balance = total - Σ Payment aplicado`.
- Conservar `paid_at` como momento en que el saldo llega a cero.
- No reabrir una Invoice pagada por refund; el neto vive en eventos/adjustments.
- Mantener pago total exacto como política actual, sin impedir clasificar anomalías legacy.

## 6. Cambios y precisiones que sí deben incorporarse

1. **Incorporar:** materializar protocolos/cargos y congelar fuentes antes del snapshot del Checkout, con rollback total. El momento interno de asignar `MR.closed` no es la invariante; el commit atómico sí.
2. **Precisar:** usar relaciones de fuente con integridad referencial, XOR y tenant; no asumir un `GenericForeignKey`.
3. **Incorporar:** modelar la decisión Rx como `pending/declined/accepted` y derivar full/partial en unidades base.
4. **Precisar:** congelar provenance y comportamiento de stock por línea y prohibir merge de orígenes distintos.
5. **Conservar:** `Checkout.completed` es terminal de preparación y su outcome histórico no cambia cuando se paga después.
6. **Corregir alcance:** mantener `payment_status=unpaid/paid` para datos válidos; partial/overpaid son `settlement_anomaly` de integridad/migración.
7. **Decidir:** si crédito entra en v1. Si entra, `issue-on-account` exige política, permiso, elegibilidad, vencimiento, aceptación y auditoría; si no, se retira del flujo nuevo.
8. **Opcional de lenguaje:** usar `issued` o conservar `posted` con el glosario ya definido; el nombre no bloquea por sí solo.
9. **Precisar:** readiness sigue siendo informativo y el comando final enumera qué dependencias externas revalida y lockea.
10. **Incorporar:** idempotency key, hash de payload, replay y optimistic locking en todos los comandos terminales.
11. **Incorporar:** fulfillment/allocations por lote reutilizando `consume_product`, y retorno/disposition por allocation en void/refund.
12. **Incorporar:** distinguir ausencia de transacción de descuento/cortesía de total cero.
13. **Mantener como cutover:** retirar señales, writers y serializers CRUD genéricos de Invoice; p62 ya tomó esta decisión.
14. **Mantener como implementación:** crear y sembrar permisos separados; p62 ya definió ownership y defaults.
15. **Incorporar:** definir quién acepta el importe final y qué evidencia se conserva, especialmente al emitir deuda.

## 7. Decisiones que faltan

### Dominio y agregados

- Cardinalidad exacta MR↔Checkout y Prescription↔Checkout para dispensaciones posteriores.
- Lista cerrada de `source_kind` y reglas de ownership por fuente.
- Si un descuento/cortesía comercial puede ajustar el importe de una línea clínica sin mutar su identidad, cantidad ni provenance; recepción no edita los hechos clínicos.
- Si una receta se congela al cierre, se versiona o admite addenda.
- Si se permiten sustituciones de producto; el código actual solo permite presentación del mismo producto.
- Cómo representar una línea surtida desde más de un lote.

### Finanzas y producto

- Si crédito entra en el primer release y quién puede autorizarlo.
- Quién acepta el importe y qué evidencia se exige para `issued/posted`; en pago inmediato debe decidirse si el pago es evidencia suficiente.
- Para deuda, quién captura la aceptación del cliente, mediante qué canal y con qué reglas de override.
- Tratamiento de descuento 100%, cortesías y documentos de total cero.
- Política de vencimiento, aging y cobro para Invoice unpaid.
- Si POS puede vender a crédito; no debe heredarlo automáticamente del flujo de consulta.

### Operación y datos

- TTL, recuperación y takeover de Checkout POS.
- Reglas de abandono de consulta con cargos clínicos ya consumidos.
- Mapping fila por fila de legacy y criterios de cuarentena.
- Orden global de locks y códigos de error de conflicto.
- Contrato de analytics para void/accrual net y versionado de snapshots.

## 8. Máquina de estados recomendada

### 8.1 Vista general

```text
MedicalRecord
  open ── close (atómico, materializa y congela) ──> closed
                                                     │
                                                     ▼
Checkout
  open ── complete_no_charge ───────────────────────> completed [outcome=no_charge]
    │
    ├── finalize_paid ──────────────────────────────> completed [outcome=issued_paid]
    │                                                   │
    │                                                   └── Invoice issued + Payment(s)
    │
    ├── issue_on_account ───────────────────────────> completed [outcome=issued_unpaid]
    │                                                   │
    │                                                   └── Invoice issued ── pay ──> settlement paid
    │
    └── abandon (guard + reason) ───────────────────> abandoned

Invoice document lifecycle
  issued ── void (sin dinero; retorno/disposition válido) ──> voided
    │
    ├── Payment(s) exactos ──> payment_status=paid
    │                              │
    │                              └── CreditNote + RefundPayment(s) [Invoice sigue issued]
    └── sin Payment ──────────> payment_status=unpaid

Datos legacy inválidos
  0 < Σ Payments < total ──> settlement_anomaly=partial + quarantine
  Σ Payments > total ──────> settlement_anomaly=overpaid + quarantine
```

### 8.2 Semántica de estados

| Estado/concepto | Qué representa | Quién lo crea/cambia | Evento | Invariantes | ¿Almacenado o derivado? |
| --- | --- | --- | --- | --- | --- |
| `MedicalRecord.open` | Acto clínico editable. | VET/ADMIN mediante writers clínicos. | Creación del expediente. | No Invoice emitida; productos clínicos pueden consumirse; cargos viven en fuentes clínicas. | Almacenado. |
| `MedicalRecord.closed` | Acto clínico principal finalizado. | Comando autoritativo de cierre. | `medical_record_closed`. | Anchor, actor, protocolo materializado; fuentes cobrables congeladas/versionadas; no mutación ordinaria. | Almacenado. |
| `Checkout.open` | Preparación comercial editable y todavía no obligatoria. | Cierre de MR o inicio POS; actores con checkout.create/edit. | `checkout_opened`. | Cero Invoice; versión monotónica; source/tenant válidos; edición por provenance. | Almacenado. |
| `Checkout.completed` | La preparación terminó y produjo un resultado irreversible. | Comando final autorizado. | `checkout_completed`. | `completed_at`, actor, outcome; no más edición; si outcome issued existe exactamente una Invoice. | Almacenado. |
| `Checkout.abandoned` | La preparación terminó sin decisión financiera válida. | Actor autorizado o job de expiry, con reason. | `checkout_abandoned`. | Cero Invoice; sin cargos obligatorios sin resolver; no equivale a no_charge. | Almacenado. |
| `Invoice.issued` | Documento comercial interno inmutable; obligación aceptada y anchor de accrual. | Solo finalización de Checkout con aceptación/evidencia válida para el comando. | `invoice_issued`. | Líneas/total/customer/source inmutables; Checkout 1:1; source clínico cerrado; `issued_at`; aceptante/evidencia según política. | Almacenado. |
| `Invoice.voided` | Obligación emitida anulada antes de dinero, con reversos de stock/AR documentados. | Permiso `invoice.void`. | `invoice_voided`. | Cero Payments; reason; disposition por fulfillment; `voided_at`; no editar documento original. | Almacenado. |
| `payment_status` | Liquidación válida según Payments aplicados. | Cambia al agregar eventos Payment válidos. | `payment_recorded`. | unpaid: sum=0; paid: sum=total. Nuevos writes parciales/sobrepagados se rechazan. | **Derivado**; cache solo si hay necesidad medida. |
| `settlement_anomaly` | Clasificador de corrupción o legacy fuera del contrato. | Integrity audit/migración. | No es transición de producto. | partial: 0<sum<total; overpaid: sum>total; ambos exigen quarantine/policy. | **Derivado**, no estado normal. |
| `readiness` | Evaluación actual para un comando concreto. | Servicio de lectura y revalidación final. | No es evento de dominio. | Incluye blockers, checkout_version y evaluated_at; no promete éxito futuro. | **Derivado**. |

### 8.3 Definición única de `completed`

`Checkout.completed` significa: **el conjunto de decisiones y líneas dejó de ser editable y el sistema registró un resultado terminal del proceso de preparación**.

No significa por sí solo que:

- se pagó;
- se entregó todo producto;
- existe una cuenta por cobrar;
- hubo transacción financiera.

Los tres escenarios son compatibles si el outcome es histórico e inmutable:

| Escenario | Checkout | Invoice | Payment | Nota |
| --- | --- | --- | --- | --- |
| Pago inmediato | completed / `issued_paid` | issued | 1..N, suma exacta | Stock retail sale atómica con finalización. |
| Crédito | completed / `issued_unpaid` | issued | 0 al completar; 1..N después | Si luego se paga, no se cambia outcome del Checkout. |
| Sin cargo | completed / `no_charge` | No | No | Requiere reason; no equivale a descuento 100% sin decisión de producto. |

### 8.4 `abandoned` vs `completed + no_charge`

| Caso | Resultado recomendado | Motivo |
| --- | --- | --- |
| Cliente decide no comprar medicamento y no hay otros cargos | `completed + no_charge`, reason `retail_declined` | Hubo decisión completa y explícita. |
| Cliente se retira antes de decidir y no hay cargos obligatorios | `abandoned`, reason `customer_left_undecided` | El proceso no llegó a una decisión completa. |
| Consulta no genera cargos (todo incluido/no billable) y no hay decisiones Rx | `completed + no_charge`, reason `no_billable_items` | Resultado determinista; puede auto-completarse en el cierre. |
| Checkout creado por error/duplicado | `abandoned`, reason `created_in_error/duplicate` | No hubo transacción ni decisión comercial válida. |
| Hay servicios/productos clínicos cobrables y el cliente se retira | No se permite `abandoned` | Debe quedar open para resolver o emitirse on-account si la política y la evidencia de aceptación lo autorizan. |

## 9. Invariantes

### Clínicas y de fuente

1. Un `MedicalRecord open` nunca puede estar referenciado por una Invoice `issued`.
2. Una Invoice de consulta solo puede crearse desde un Checkout cuya fuente clínica esté cerrada y congelada/versionada.
3. Cerrar una consulta materializa todos los protocolos y cargos antes del snapshot del Checkout, dentro de la misma transacción.
4. Ningún writer ordinario puede modificar MR, servicios, productos consumidos o receta versionada después de crear la Invoice.
5. Una corrección clínica posterior es un addendum/evento nuevo, no mutación silenciosa del documento emitido.

### Checkout

6. Solo `open` es editable.
7. Cada mutación válida incrementa exactamente una vez `checkout.version`.
8. Todo write exige `expected_version`; stale version no produce escrituras parciales.
9. `completed` y `abandoned` son terminales.
10. `completed` exige exactamente un outcome y sus anchors/actor.
11. `abandoned` exige reason y prohíbe Invoice.
12. Un Checkout emitido tiene exactamente una Invoice; una Invoice tiene exactamente un Checkout.
13. Existe como máximo un Checkout `primary_consultation` por MR; cualquier Checkout suplementario usa kind y unicidad distintos.
14. Cada línea tiene provenance, snapshot de descripción/precio/impuesto y stock_behavior explícitos.
15. Líneas de distinta provenance no se fusionan aunque compartan presentación.

### Invoice y Payment

16. Invoice nace `issued`, inmutable y con `issued_at` autoritativo; el comando registra el aceptante y la evidencia exigida por su política (pago inmediato u on-account).
17. `remaining_balance = total - Σ Payment aplicado`.
18. `payment_status` se deriva como unpaid/paid para datos válidos; partial/overpaid se clasifican como `settlement_anomaly` y el writer v1 rechaza esos nuevos writes.
19. `paid_at` es el `occurred_at` del evento que lleva el saldo a cero y no cambia por refund.
20. Una Invoice con Payments no puede `void`; se corrige con CreditNote/RefundPayment.
21. Un reintento con misma idempotency key y mismo payload devuelve el mismo resultado; misma key con payload distinto falla.
22. Payment/Refund/Reversal son append-only y preservan CashSession/provenance.

### Stock

23. El insumo clínico mueve stock al registrarse su consumo, nunca al emitir o pagar Invoice.
24. Producto retail no mueve stock al editar Checkout.
25. Producto retail mueve stock una sola vez al finalizar con pago o al emitir on-account con entrega.
26. Finalización falla atómicamente si stock/lote dejó de ser válido; no queda Invoice ni Payment parcial.
27. Void/refund solo restockea unidades físicamente retornadas y con disposition válida.
28. Una corrección monetaria de un insumo clínico no genera restock automático.
29. Cantidades y caps de receta se comparan en unidades base; allocations por lote suman la cantidad de la línea.

### Multi-tenant, permisos y auditoría

30. Toda entidad y evento lleva organization; source, actor, customer, catálogo y stock pertenecen al mismo tenant.
31. Crear/edit Checkout, emitir obligación, mover dinero, void y refund son permisos distintos.
32. Todo comando terminal genera evento auditable con actor, reason, versión, idempotency key y referencias resultantes.
33. Los endpoints CRUD genéricos no pueden saltarse services de dominio.
34. El orden de locks es único y documentado; ninguna ruta adquiere los mismos recursos en orden inverso.

## 10. Flujo Consulta → Checkout → Billing → Payment

### 10.1 Durante la consulta

```text
MedicalRecord open
  ├─ MedicalRecordService          (servicio prestado; todavía no Invoice)
  ├─ MedicalRecordProduct charge   (consume stock clínico + fuente cobrable)
  ├─ MedicalRecordProduct included (consume stock clínico, no fuente cobrable)
  └─ Prescription / items          (decisión clínica; sin venta ni salida retail)
```

No se crea Checkout de consulta ni Invoice emitida mientras el MR está abierto. La UI puede mostrar una **proyección previa** de cargos, pero no debe persistirla como documento financiero ni duplicarla como fuente de verdad.

### 10.2 Cierre atómico

```text
lock MedicalRecord
  → validar diagnóstico/tratamiento/protocolo
  → materializar protocolos y sus productos/cargos
  → validar/fijar versión de Prescription y fuentes cobrables
  → marcar MedicalRecord closed + anchors
  → completar Appointment cuando corresponda
  → crear Checkout primary_consultation
  → snapshotear líneas con provenance/stock_behavior
  → si no hay cargos ni decisiones pendientes: completed/no_charge
  → commit
```

La secuencia normativa exige que materialización y freeze ocurran antes del snapshot. La asignación interna de `MedicalRecord.closed` puede ocurrir antes dentro de la misma transacción si una precondición técnica lo exige, porque ningún estado intermedio es visible antes del commit; no puede ocurrir después del snapshot.

La respuesta debe indicar si el Checkout quedó `open` o se auto-completó `no_charge`; el frontend no debe adivinarlo.

### 10.3 Preparación y finalización

```text
Checkout open
  → recepción resuelve decisiones Rx
  → agrega/quita solo líneas comerciales permitidas
  → aplica descuentos autorizados
  → GET readiness (asesoría)
  → POST comando final con expected_version + idempotency key
       ├─ revalidar source/versión/permisos/caja/stock/lotes/totales
       ├─ lockear en orden global
       ├─ validar y registrar aceptación/evidencia del importe
       ├─ copiar snapshot a Invoice issued si total financiero > 0
       ├─ mover stock retail/fulfillment
       ├─ crear Payment(s) si pago inmediato
       ├─ completar Checkout con outcome
       └─ commit todo o nada
```

### 10.4 Pago posterior

Una Invoice `issued` on-account se cobra mediante comando sobre Invoice, no reabriendo Checkout. Se lockea CashSession antes de Invoice, se valida el saldo exacto, se crean 1..N Payments según medios y se deriva `paid`.

## 11. POS

POS y consulta pueden compartir el motor de Checkout, cálculo de totales, finalización, Invoice, Payments, CashSession, stock, idempotencia y refunds. No deben compartir ciegamente políticas de fuente.

| Aspecto | Consulta | POS/direct sale |
| --- | --- | --- |
| Creación | Al cerrar MR, server-side | Al iniciar/guardar primera línea del carrito, server-side |
| Source | MR cerrado + opcional Prescription versionada | Sesión POS/actor; sin MR |
| Cliente | Owner/pet del MR | Owner real o genérico; pet opcional |
| Líneas clínicas | Sí, snapshot no editable | No |
| Receta | Interna, decisiones por PrescriptionItem | Atestación externa y permiso `billing.rx_dispense` cuando aplique |
| Crédito | Solo si política clínica lo autoriza | No por defecto; decisión separada |
| Abandono | Guards por cargos clínicos | Permitido/TTL si no hay Invoice |
| Stock | Clínico ya consumido + retail al finalize | Todo retail al finalize |
| Pago | Inmediato o, si se aprueba, on-account | Normalmente inmediato y atómico |

El flujo actual crea Invoice draft después de construir carrito local, agrega ítems secuencialmente y cancela la factura ante error o al volver al carrito. El Checkout persistente elimina esos drafts cancelados, pero requiere:

- `version` y expected_version;
- TTL/expiry server-side;
- idempotencia por comando;
- recuperación/takeover controlado;
- cancelación de cleanup como optimización, no garantía;
- atestación Rx como dato legal asociado al resultado emitido, no solo al carrito efímero.

## 12. Recetas

### 12.1 Responsabilidades

```text
Prescription / PrescriptionItem
  = decisión clínica: qué se indicó, dosis, cantidad y vigencia

CheckoutPrescriptionDecision
  = decisión comercial del cliente: acepta, declina o sigue pendiente

CheckoutItem / StockAllocation
  = qué presentación y cantidad se entregará, y desde qué lote(s)

InvoiceItem
  = snapshot inmutable de lo efectivamente cobrado/emitido
```

La decisión pertenece al Checkout porque no modifica lo prescrito. No debe ser un agregado independiente: es una entidad hija cuya consistencia se protege con el lock/version del Checkout.

### 12.2 Estados y derivaciones

- Persistir por PrescriptionItem: `pending`, `declined`, `accepted`.
- `accepted_full` y `accepted_partial` se derivan comparando unidades base aceptadas contra unidades base prescritas.
- `declined` debe registrar actor/fecha y, opcionalmente, reason.
- Una aceptación puede producir varias líneas si hay varias presentaciones/lotes.
- Antes de completar, el cliente puede cambiar de opinión mediante una edición versionada.
- Después de completar, no se edita Checkout: se usa void/return/refund según dinero y entrega.

### 12.3 Casos

| Caso | Resultado |
| --- | --- |
| Aceptación completa | Suma de allocations = cantidad prescrita; readiness sin blocker. |
| Parcial | 0 < suma < prescrita; decisión derivada partial y auditada. |
| Rechazo | Cero CheckoutItems retail para ese PrescriptionItem; decisión declined. |
| Stock insuficiente | Readiness blocker informativo; finalize vuelve a validar y falla atómico si no se resuelve. |
| Cambio de presentación | Permitido si pertenece al mismo Product y conversión/cap son válidos. |
| Sustitución de producto | Fuera de alcance salvo decisión clínica explícita; no tratarla como otra presentación. |
| Producto eliminado/inactivo | Snapshot clínico se conserva; la política debe decidir si puede surtirse. Nunca cambiar silenciosamente de producto. |
| Cambio de opinión post-emisión | Void/return/refund; no mutación del Checkout completado. |

Antes de implementar debe cerrarse la mutabilidad de Prescription posterior al cierre. El estado actual permite PATCH y reemplazo destructivo de ítems; una FK desde InvoiceItem puede convertir ese reemplazo en error de integridad o dejar decisiones obsoletas.

## 13. Stock

### 13.1 Momento de movimiento

| Tipo | Reserva | Consumo/venta | Entrega | Reverso |
| --- | --- | --- | --- | --- |
| `clinical_consumable` charge | No | Al crear `MedicalRecordProduct`; ya ocurre hoy | Durante la atención | Corrección clínica/stock específica; no refund automático |
| `clinical_consumable` included | No | Al crear `MedicalRecordProduct` | Durante la atención | Igual que anterior; nunca aparece como cargo |
| `prescription_retail` | No en esta fase | Al finalizar paid o issue-on-account con entrega | Mismo evento operacional en el alcance actual | Void/refund con devolución física y disposition |
| `direct_sale_retail` | No en esta fase | Al finalizar pago POS; on-account solo si se aprueba explícitamente | Mismo evento | Refund/return con disposition |

### 13.2 Crédito y `post-unpaid`

Sí, una Invoice unpaid puede haber movido stock, **solo** si el evento de emisión significa además que el producto fue entregado. Entonces:

- el Checkout queda completed;
- la Invoice queda issued/unpaid;
- el StockMovement `out` queda ligado a Invoice/fulfillment;
- void requiere que la mercancía vuelva o una disposition que explique por qué no;
- no se debe reponer stock por el mero hecho de eliminar AR.

Si el negocio quiere emitir una cuenta antes de entregar, hace falta un lifecycle de fulfillment separado. El ADR lo excluye; por tanto no puede soportar ambas interpretaciones en esta fase.

### 13.3 Lotes

Readiness puede sugerir FEFO, pero el finalize debe lockear Product/StockLot y producir allocations exactas. El motor actual `consume_product(lot=None)` ya puede repartir FEFO entre lotes; debe reutilizarse. El gap es que dispensación fija hoy `first_consumable_lot` y un único `lot` en InvoiceItem no conserva el reparto. Cada allocation debe ligarse durablemente a la línea/StockMovement y cada reverso debe volver al lote original o registrar discard.

### 13.4 Refund clínico

Debe corregirse la regla actual como defecto **CRITICAL** y gate del refactor: `process_refund` ofrece `restock` para cualquier línea con presentación. Una línea cobrable derivada de un producto ya aplicado en consulta no es una devolución de mercancía. El nuevo provenance debe cerrar esa posibilidad y las líneas legacy sin provenance segura no deben habilitar restock automático.

## 14. Migración

### 14.1 Principios

1. Preservar IDs y documentos financieros existentes siempre que ya hubo obligación.
2. No inventar decisiones de cliente, actores, anchors ni no_charge.
3. Ejecutar clasificador dry-run por tenant y publicar conteos por bucket.
4. Quarantinar cualquier fila que viole ledger, anchor, tenant, source o stock.
5. Dual-read antes de cutover; jamás dual-write abierto en dos modelos.
6. Mantener legacy Invoice draft oculta/read-only hasta completar reconciliación y rollback window.

### 14.2 Mapping recomendado

| Estado/datos actuales | Mapping candidato | Automático | Observaciones |
| --- | --- | --- | --- |
| `draft`, consultation, MR closed, items y provenance deterministas | Checkout open con snapshot; Invoice legacy archivada/read-only | Sí, con validaciones | No completar: puede haber decisiones Rx pendientes. Si no se puede probar source/stock_behavior, cuarentena. |
| `draft`, consultation, MR closed, total 0 | Checkout open o auto no_charge solo con evidencia determinista | **No** en general | No se sabe si no hubo cargos o faltó decisión. |
| `draft`, consultation, MR open, sin items | No crear Checkout aún; archivar draft legacy | Sí | Checkout nacerá al cierre futuro. |
| `draft`, consultation, MR open, con items | Cuarentena | No | Ítems pueden ser sync clínica, manuales o Rx; no hay mapping seguro. |
| `draft`, direct_sale, reciente | Checkout POS open con versión/expiry | Según ventana definida | Requiere policy de recuperación. |
| `draft`, direct_sale, antiguo | Checkout abandoned `legacy_expired` | Solo con cutoff aprobado | No inferir si el cliente volverá sin policy. |
| `confirmed`, sin Payment, saldo=total | Invoice issued/unpaid; Checkout sintético completed/issued_unpaid | Sí | `issued_at=confirmed_at`, preservar provenance. |
| `confirmed`, Payments parciales, saldo>0 | Invoice issued + `settlement_anomaly=partial` + cuarentena/policy legacy | No para producto v1 | No convertir partial en estado normal ni etiquetar simplemente unpaid; dinero ya existe. |
| `confirmed`, Payments suman total | Reparación/quarantina; luego issued/paid si `paid_at` verificable | No | Estado y ledger discrepan. |
| `paid`, ledger exacto | Invoice issued/paid; Checkout sintético completed/issued_paid | Sí | `issued_at=confirmed_at`; `paid_at` intacto. |
| `paid`, ledger/anchor inconsistente | Cuarentena | No | Ejecutar audit ledger/anchors antes. |
| `cancelled` cuyo audit muestra origen `draft` | Checkout abandoned; Invoice legacy archivada | Condicional | Conservar cancelled_at como evento legacy, no como void financiero. |
| `cancelled` cuyo audit muestra origen `confirmed` | Invoice voided; Checkout sintético completed/issued_unpaid | Condicional | Preservar issued_at y voided_at; verificar reverso stock. |
| `cancelled` sin estado previo recuperable | Cuarentena | No | `cancelled` colapsa abandono y void. |
| Cualquier status con cross-tenant/source inválido o pagos indebidos | Cuarentena | No | Bloquea cutover de esa fila, no del tenant completo si se diseña aislamiento. |

### 14.3 Anchors y analytics

- `confirmed_at` → `issued_at`/`posted_at`; no recalcular con `created_at` salvo provenance `fallback` explícita.
- `cancelled_at` → `voided_at` únicamente si hubo Invoice emitida; para draft cancelado se conserva como evento de abandono legacy.
- `paid_at` se conserva y se reconcilia contra Payments.
- `revenue_accrual` histórico mantiene el anchor original; no reescribir snapshots congelados.
- Crear integrity audits para checkout↔invoice 1:1, source closed, settlement, stock allocations y anchors.

## 15. Tests requeridos

### 15.1 Matriz funcional y de integración

| Caso | Resultado esperado |
| --- | --- |
| Consulta abierta + edición | Cambios clínicos permitidos según rol; no Invoice issued; no Checkout de consulta persistido o solo proyección no financiera definida. |
| Confirmación/emisión desde consulta abierta por cualquier endpoint | Rechazo de dominio; cero Invoice/Payment/StockMovement. |
| Consulta cerrada | Materializa protocolos, congela fuentes, completa Appointment y crea exactamente un Checkout primario en una transacción. |
| Fallo de materialización al cerrar | Rollback: MR sigue open, sin Checkout, sin Invoice y sin movimientos parciales. |
| Consulta cerrada sin cargos ni Rx pendiente | Checkout completed/no_charge automático con reason y audit; no Invoice. |
| Consulta `$0` por descuento 100% | Comportamiento según decisión de producto; test distinto de no_billable_items. |
| Receta completa | Todas las decisiones resueltas; cantidades base exactas; InvoiceItems con provenance; stock una vez. |
| Receta parcial | Estado derivado partial; líneas suman menos que prescrito; finalize permitido si la decisión está explícitamente resuelta. |
| Receta rechazada | Cero líneas retail de ese ítem; decisión declined auditada. |
| Receta modificada después de crear Checkout | Bloqueo por freeze o nueva versión que invalida/reconstruye Checkout según contrato. |
| Producto clínico charge | Stock sale al crear MRP; Checkout/Invoice no lo descuenta de nuevo. |
| Producto clínico included | Stock sale; no CheckoutItem cobrable ni InvoiceItem. |
| Refund monetario de producto clínico | No permite restock retail automático. |
| Producto retail de receta | No movimiento al seleccionar; movimiento al finalize; provenance Rx. |
| POS | Checkout server-side, customer/attestation válidos, finalize atómico, recuperación y expiry. |
| POS abandona antes de Invoice | Checkout abandoned; cero Invoice/StockMovement. |
| Pago completo único | Invoice issued, un Payment, saldo cero, paid_at correcto, CashSession correcta y evidencia de aceptación según política. |
| Pago split | N Payments producidos por el mismo comando idempotente, suma exacta y saldo cero; no exige PaymentBatch. |
| Pago parcial nuevo | Rechazado sin eventos ni cambio de estado. |
| Legacy parcialmente pagado | Clasificado `settlement_anomaly=partial` + quarantine; no pérdida de eventos. |
| Crédito autorizado | Invoice issued/unpaid, due_at/policy/actor y aceptación del importe auditados, stock retail según entrega. |
| Crédito no autorizado | 403/denegación; Checkout sigue open y sin efectos. |
| Deuda sin evidencia de aceptación exigida | Rechazada sin Invoice, Payment ni StockMovement; Checkout sigue open. |
| Pago inmediato como aceptación | Si negocio lo aprueba, el comando de pago registra esa causalidad sin pedir una segunda confirmación redundante. |
| Void sin Payments y sin fulfillment | Invoice voided, AR neto, no stock espurio. |
| Void con retail entregado y retorno restock | Inverse StockMovement al lote original y audit de disposition. |
| Void con retail no retornado | Rechazo o disposition no-restock según contrato; nunca stock ficticio. |
| Void con Payments | Rechazado; requiere CreditNote/refund. |
| Refund | Invoice permanece issued/paid; CreditNote y RefundPayment append-only; net metrics/caja correctos. |
| Concurrent edit/edit | Solo una versión gana; la otra recibe 409 con versión actual; sin lost update. |
| Concurrent edit/finalize | O la edición entra antes y finalize usa nueva versión, o finalize gana y edición falla; Invoice coincide exactamente con Checkout completado. |
| Concurrent pay/pay | Un solo conjunto de Payments; replay idempotente o conflicto; stock una vez. |
| Concurrent pay/void | Un único resultado válido; nunca dinero y void simultáneos. |
| Readiness true, stock cambia antes de finalize | Finalize revalida y falla atómico con blocker actual; GET previo no garantiza éxito. |
| Stock insuficiente | Cero Invoice/Payment/StockMovement parcial; Checkout sigue open. |
| Lote expira/se cuarentena | Readiness/finalize lo bloquean; no se usa allocation stale. |
| Cantidad requiere múltiples lotes | Allocations suman cantidad; cada reverso vuelve al lote correcto. |
| Checkout stale version | 409; response incluye current_version y snapshot/blockers necesarios; cero writes. |
| Idempotency replay mismo payload | Misma respuesta/IDs; no duplica Invoice, Payment, stock ni audit terminal. |
| Idempotency key mismo valor, payload distinto | Conflicto explícito; cero writes nuevos. |
| CashSession se cierra durante pago | Serialización por lock; o entra al Z o falla, nunca queda fuera del cierre. |
| Permisos por rol | Editar, issue-on-account, pay, void y refund se prueban independientemente para ADMIN/VET/ASSISTANT/roles dinámicos. |
| Cross-tenant source/item/actor/id | 404/denegación consistente; cero filtración y cero writes. |
| Unicidad Checkout primario | Dos cierres/reintentos crean uno; carreras respetan constraint. |
| Checkout suplementario Rx | No duplica cargos del primario y respeta cardinalidad/presentation caps. |
| Analytics accrual | issued_at incluye obligation; void/credit adjustments producen fórmula esperada live y frozen. |
| AR | Suma remaining_balance de Invoices issued no voided; partial legacy correcto; no usa total bruto indiscriminado. |
| Migración por bucket | Cada fila cae en un único bucket o quarantine; conteos y sumas de dinero/stock se reconcilian antes/después. |

### 15.2 Tests existentes que deben preservarse conceptualmente

- Pago split crea dos Payments y saldo cero ([test_payment_ledger.py:86](../../backend/apps/billing/tests/test_payment_ledger.py#L86)).
- Pago parcial de consulta se rechaza sin Payment ([test_payment_ledger.py:110](../../backend/apps/billing/tests/test_payment_ledger.py#L110)).
- Dos direct-pay paralelos descuentan stock una vez ([test_invoice_concurrency.py:270](../../backend/apps/billing/tests/test_invoice_concurrency.py#L270)).
- Confirmar descuenta retail dispensado pero no el insumo ya consumido ([test_prescription_dispense.py:118](../../backend/apps/billing/tests/test_prescription_dispense.py#L118)).
- Refund mantiene Invoice paid y genera CreditNote/RefundPayment/adjustment ([test_refund.py:65](../../backend/apps/billing/tests/test_refund.py#L65)).
- AR cae al pagar ([test_summary_endpoint.py:353](../../backend/apps/dashboard/tests/test_summary_endpoint.py#L353)).

## 16. Impacto de implementación

### Backend

- Nuevo agregado Checkout, services autoritativos, lifecycle, readiness, versioning y eventos de auditoría.
- Reescritura del cierre clínico y eliminación de todos los writers alternos de Invoice de consulta.
- Servicios separados para finalize paid, issue-on-account, complete-no-charge, abandon, pay, void y refund.
- Freeze/versionado de Prescription y reglas de ítems por provenance.
- Contrato estable de errores, idempotencia y evidencia de aceptación del importe.

### Frontend

- Nueva queue semántica: **Por preparar**, **Pendiente de pago**, **Pagado**, con historial **Sin cobro/Abandonado**.
- Cierre de consulta debe mostrar el resultado real del backend, no asumir “se creó un cobro”.
- Billing deja de editar Invoice y edita Checkout; Invoice detail es read-only salvo comandos financieros.
- POS persiste carrito, maneja stale version, recuperación/expiry y blockers de finalización.
- Botones dejan de usar “Confirmar” ambiguo: “Finalizar y cobrar”, “Emitir a crédito”, “Completar sin cargo”, “Abandonar”.

### DB

- Tablas/constraints de Checkout, items, decisiones, audit e idempotency.
- FK 1:1 Checkout→Invoice y constraints de fuente/cardinalidad/tenant.
- `issued_at/voided_at` y estrategia de compatibilidad con anchors legacy.
- Modelo de allocations por lote enlazado a línea/StockMovement; no se agrega agrupación de settlement en v1 sin requisito.
- Campos o evento inmutable de aceptación (`accepted_by/at/channel/evidence`) según la decisión de negocio.
- Índices de queue por org/status/source/updated_at y partial unique para Checkout primario.

### Inventory

- `stock_behavior`/provenance explícitos.
- Allocations por lote, movimiento atómico en finalize y reversos por disposition.
- Separación estricta entre consumo clínico y fulfillment retail.
- Nuevos audits de stock↔fulfillment↔Invoice.

### Analytics

- Migrar accrual de `confirmed_at` a `issued_at` preservando historia.
- AR sobre remaining_balance de issued no voided.
- Fórmula y adjustments de void/accrual net.
- KPIs operacionales de Checkout sin mezclarlos con revenue.
- Bump/dual-write/backfill según gobernanza de snapshots.

### Permissions

- Nuevos códigos, seeds y defaults por rol.
- Ownership de Checkout de consulta vs POS.
- High-trust para crédito, void, refund, descuentos/cortesías y Rx.
- Pruebas de roles dinámicos y service accounts.

### Tests

- Unitarios de estado/invariantes, integración cross-domain, Postgres concurrency, API contracts, frontend flows y migración.
- Integrity commands para source closed, 1:1, settlement, anchors, idempotencia y stock allocations.
- Fixtures de todos los buckets legacy y reconciliación de sumas.

### Docs

- No agregar Settlement/PaymentBatch en v1; si aparece un requisito de agrupación, actualizar antes el contrato financiero mediante ADR.
- Actualizar Billing, Medical Records, Prescriptions, Inventory, Cash, Analytics, system flows y permisos.
- Publicar glosario de `Checkout`, `issued`, `void`, `no_charge`, `abandoned`, `settlement` y `fulfillment`.
- Documentar rollout, dual-read, rollback y runbooks de cuarentena.

## 17. Preguntas de negocio

Solo estas decisiones requieren respuesta del negocio antes del plan; el resto es decisión técnica derivable de invariantes:

1. **¿El primer release debe permitir crédito real?** Si sí: ¿qué clientes son elegibles, quién lo autoriza, cuál es el vencimiento y POS también puede usarlo?
2. **¿Quién acepta el importe final y qué evidencia se conserva?** En pago inmediato debe decidirse si pagar es aceptación suficiente; en `issue_on_account`, quién captura la aceptación del cliente, por qué canal y con qué override.
3. **¿Una cortesía/descuento 100% exige un documento financiero de total cero**, o debe terminar como `no_charge`? Esto no es igual a “no hubo ítems cobrables”.
4. **Al emitir una Invoice unpaid, el producto retail se considera entregado en ese mismo acto?** Si sí, ¿qué evidence/disposition se exige para void; si no, se acepta ampliar scope con fulfillment separado?
5. **¿Una receta puede corregirse después de cerrar la consulta?** Si sí, ¿es una nueva versión/addendum y puede generar un Checkout suplementario? ¿Se permiten sustituciones de producto o solo presentaciones equivalentes?
6. **¿Una consulta puede originar más de un episodio comercial?** Por ejemplo, cobro primario hoy y dispensación parcial días después. La respuesta fija la cardinalidad MR↔Checkout.

---

## Conclusión

El ADR sí identifica correctamente la ambigüedad de `draft/confirmed` y propone una separación prometedora entre preparación comercial, obligación y dinero. Todavía no garantiza, sin embargo, consistencia completa entre consulta, protocolo, receta, stock, Invoice y Payment.

Si mañana se implementara p62 literalmente, quedarían al menos estas bifurcaciones legítimas de interpretación: snapshot antes o después de materializar protocolos; receta congelada o mutable; aceptación del importe implícita o explícita; void con o sin retorno; no_charge para todo total cero o solo ausencia de transacción; un Checkout o varios por consulta; y versión local o revalidación de dependencias externas.

Por eso la recomendación es **REWORK**: conservar el concepto central de Checkout, actualizar el ADR con las definiciones e invariantes anteriores y solo entonces producir el plan de implementación.
