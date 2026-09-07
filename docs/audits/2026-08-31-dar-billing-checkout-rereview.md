# Revisión de la segunda pasada del ADR Billing / Checkout

**Fecha:** 2026-08-31

**Documento actualizado revisado:** `docs/audits/2026-08-30-dar-billing-checkout-review.md`

**ADR base:** `docs/decisions/2026-08-30-p62-billing-checkout-lifecycle.md`

**Tipo:** addendum independiente; no sustituye ni sobrescribe la auditoría actualizada

**Alcance:** arquitectura y contratos; sin implementación.

## 1. Veredicto

### Sobre el ADR p62: REWORK

El concepto central sigue siendo correcto: `Checkout` es una frontera razonable para separar preparación comercial de obligación financiera, y `Invoice` debe nacer inmutable. La segunda pasada resuelve bien varias objeciones de alcance y hace el informe mucho más útil.

El ADR todavía no puede pasar a plan de implementación. Además de los blockers que la segunda pasada conserva, quedan seis decisiones de integridad no registradas o insuficientemente cerradas: momento efectivo de precio/impuesto, inventario al revertir una nota de crédito, representación de settlement legacy anómalo, identidad/replay de comandos idempotentes, tratamiento de cargos clínicos disputados y grafo real de locks con Appointment.

### Sobre la actualización del informe: APPROVE WITH CHANGES

La reclasificación de R01-R27 es mayormente correcta y puede conservarse. Deben incorporarse los hallazgos R28-R39 de este addendum antes de tratar el informe como inventario completo y normativo de decisiones previas al plan.

## 2. Resumen ejecutivo

1. La actualización mejora materialmente el informe y no cambia la recomendación de conservar un Checkout independiente.
2. Es correcto retirar R03, R18 y R23 como gaps del ADR: p62 ya decide un writer único futuro, permisos separados y líneas clínicas no editables.
3. Es correcto no introducir `PaymentBatch` sin requisito; el contrato real produce 1..N `Payment` por medios.
4. Es correcto tratar partial/overpaid como anomalías legacy, no como estados normales del producto.
5. Sin embargo, una anomalía no cabe todavía en `payment_status=unpaid|paid`; falta decidir dónde y cómo se representa.
6. Eliminar Invoice draft pierde el único snapshot actual del precio clínico si no se agrega un hecho de precio antes del cierre.
7. `MedicalRecordService` y `MedicalRecordProduct` no almacenan `unit_price`; hoy sus writers lo copian inmediatamente a `InvoiceItem`.
8. `RefundReversal` restaura dinero y analytics, pero no compensa el restock ejecutado por el refund; el informe no audita esa rama.
9. Readiness debe distinguir preparación estructural de disponibilidad de cada comando; un Boolean único no cubre caja, permiso, crédito y aceptación.
10. La idempotencia necesita un recibo durable con tenant, comando, agregado, key, hash y resultado, además de un orden explícito de replay.
11. R26 debe incluir Appointment y locks implícitos de `UPDATE`: el código ya contiene caminos MR→Appointment y Appointment→MR.
12. Una consulta con cargos que el cliente disputa/no acepta no puede quedar indefinidamente `Checkout.open` sin aparecer en AR.
13. `void` total de una Invoice unpaid errónea necesita un workflow de reemplazo/supersesión.
14. La segunda pasada debe elegir una sola nomenclatura normativa: `posted` o `issued`.
15. El veredicto permanece `REWORK`; no hay razón para `REJECT`, porque los nuevos problemas son contratos faltantes y no invalidan el agregado Checkout.

## 3. Qué quedó bien resuelto

### Resoluciones confirmadas sin cambio

- **R01:** materialización y freeze deben preceder al snapshot dentro del mismo commit.
- **R03:** los múltiples writers actuales son riesgo de cutover; p62 ya ordena retirarlos.
- **R04:** Prescription necesita freeze, versión o addendum antes de referenciarla desde Invoice.
- **R05:** `accepted_full/partial` no debe ser una segunda fuente manual de verdad.
- **R06:** provenance y `stock_behavior` deben ser explícitos e inmutables.
- **R08:** un comando split puede producir varios Payments; no hace falta inventar una entidad agrupadora sin caso de negocio.
- **R10/R27:** crédito y aceptación del importe son decisiones distintas y requieren autoridad de negocio.
- **R11:** ausencia de transacción y transacción financiera de total cero no son equivalentes.
- **R13/R14:** cardinalidad y relaciones tenant-safe deben cerrarse con FKs/constraints explícitos.
- **R17:** accrual neto exige adjustments/versionado, no reescritura de snapshots.
- **R18/R23:** permisos y ownership clínico ya están decididos por p62; quedan como gates de implementación/pruebas.
- **R21/R22:** audit de mutaciones y expiración POS server-side son requisitos correctos.
- **R25:** el restock actual de líneas clínicas en refund es un defecto crítico real y gate del refactor.

### Resoluciones correctas que necesitan un addendum

| Hallazgo previo | Resolución de segunda pasada | Precisión adicional necesaria |
| --- | --- | --- |
| R02 readiness/TOCTOU | Fusionado con source y locks | Separar readiness estructural de disponibilidad por comando/actor. |
| R07 void/stock | Aceptado | Añadir replacement/reissue y RefundReversal después de restock. |
| R09 partial/overpaid | Reducido a anomalía | Elegir representación persistente/read model y efecto en AR/API. |
| R15 multi-lote | Aceptado | Incluir consumo clínico o prohibir explícitamente multi-lote clínico. |
| R16 migración | Aceptado focalizado | Añadir acceptance provenance legacy y price snapshot legacy. |
| R19 idempotencia | Aceptado con hash | Añadir scope de comando/agregado y replay-before-guards. |
| R24 posted/issued | Correctamente no conceptual | El informe normativo debe usar un solo nombre, no ambos. |
| R26 lock order | Aceptado | Incluir Appointment y locks implícitos de UPDATE. |
| R27 aceptación | Aceptado | Resolver también el rechazo/disputa de cargos ya prestados. |

## 4. Hallazgos nuevos y refinados

| ID | Severidad | Problema | Evidencia | Recomendación |
| --- | --- | --- | --- | --- |
| ADR-R28 | **BLOCKER** | No se define cuándo se congela precio/impuesto de un cargo clínico. Sin Invoice draft, leer catálogo al cierre cambia el comportamiento actual. | `MedicalRecordService` solo guarda servicio/cantidad ([models.py:438](../../backend/apps/medical_records/models.py#L438)); `MedicalRecordProduct` tampoco guarda precio ([models.py:327](../../backend/apps/inventory/models.py#L327)). Hoy los writers copian `service.base_price` y `presentation.sale_price` al crear el cargo ([views.py:256](../../backend/apps/medical_records/views.py#L256), [services.py:82](../../backend/apps/medical_records/services.py#L82)). | Elegir evento efectivo. Para preservar comportamiento, crear snapshot de cargo/precio/impuesto en la fuente clínica al registrarla; Checkout e Invoice copian ese hecho, no el catálogo vigente al cierre/post. |
| ADR-R29 | **CRITICAL / BLOCKER** | `RefundReversal` no tiene semántica de inventario después de un refund con restock. | `process_refund` puede ejecutar `restock_product` ([services.py:574](../../backend/apps/billing/services.py#L574)); `reverse_credit_note` solo crea contraeventos monetarios/analytics ([services.py:706](../../backend/apps/billing/services.py#L706)). El test de reversal solo valida eventos y adjustment ([test_refund.py:178](../../backend/apps/billing/tests/test_refund.py#L178)). | Decidir: movimiento stock inverso con allocations exactas, prohibición de reversal tras restock, o ajuste de stock separado pero causalmente ligado. Añadir gate para líneas clínicas y lotes. |
| ADR-R30 | **HIGH** | La segunda pasada llama readiness “para un comando concreto”, pero ADR/API siguen exponiendo un único `is_ready`. | Informe actualizado [línea 314](2026-08-30-dar-billing-checkout-review.md#L314); ADR expone un único objeto en [línea 512](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L512). | Exponer `preparation_readiness` y `actions.{pay,post_unpaid,no_charge,abandon}` con `allowed/blockers`, o exigir comando en la evaluación. El finalize siempre revalida. |
| ADR-R31 | **BLOCKER de migración** | Una Invoice legacy partial/overpaid no satisface ningún valor del status binario recomendado. | R09 y tabla de migración del informe [líneas 98 y 574](2026-08-30-dar-billing-checkout-review.md#L98). | Elegir: clasificación derivada exhaustiva (`unpaid/partial/paid/overpaid`) con writers nuevos restringidos, o entidad/proyección de cuarentena separada. Definir API, AR, reparación y analytics. |
| ADR-R32 | **BLOCKER** | Idempotencia no define scope ni orden de replay respecto de versión/status. | El informe pide key+hash [línea 231](2026-08-30-dar-billing-checkout-review.md#L231). El código actual dedupea por org y `key:0` ([services.py:260](../../backend/apps/billing/services.py#L260)); el constraint es org+key ([models.py:397](../../backend/apps/billing/models.py#L397)). | Persistir CommandReceipt `(org, command_kind, aggregate_public_id, key, request_hash, result refs)`. Replay idéntico se resuelve antes de guards ordinarios; payload distinto da 409; dos keys distintas compiten bajo lock/unique terminal. |
| ADR-R33 | **HIGH** | El informe rechaza R24 como defecto, pero su máquina normativa cambia `posted` por `issued`. | Resolución R24 [línea 113](2026-08-30-dar-billing-checkout-review.md#L113); máquina recomendada usa `Invoice.issued` [línea 310](2026-08-30-dar-billing-checkout-review.md#L310); ADR usa `posted_at` [línea 36](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L36). | Elegir un único nombre persistido/API. Se puede mostrar “Emitida” en UI aunque el campo siga siendo `posted_at`, pero no dejar dos schemas posibles. |
| ADR-R34 | **HIGH** | Full/partial de receta se compara con cantidad prescrita, no con cantidad elegible restante para un surtido posterior. | Informe [líneas 500-510](2026-08-30-dar-billing-checkout-review.md#L500). | Capturar/derivar `eligible_remaining_at_decision` considerando allocations previas, expiración y correcciones; full/partial del Checkout se compara contra ese baseline. |
| ADR-R35 | **HIGH** | Falta el workflow para corregir y reemitir una Invoice unpaid anulada. | La corrección solo indica void total; Invoice y Checkout son inmutables/terminales. | Definir comando de replacement con nuevo Checkout/Invoice y relación `supersedes/superseded_by`, o declarar el caso fuera de v1 con procedimiento operativo inequívoco. |
| ADR-R36 | **BLOCKER, refina R26** | El grafo de locks omite Appointment y locks implícitos. | Close toma MR y actualiza Appointment ([appointments/services.py:553](../../backend/apps/appointments/services.py#L553)); assign_patient toma Appointment y actualiza MR ([appointments/views.py:484](../../backend/apps/appointments/views.py#L484)). | Incluir ambos caminos en la matriz de recursos. Un `UPDATE` condicional también toma row lock. Diseñar orden/retry y test PostgreSQL close-vs-assign/status. |
| ADR-R37 | **BLOCKER de negocio, refina R10/R27** | Si hay cargos clínicos reales pero el cliente no paga ni acepta el importe/crédito, `abandoned` está prohibido e Invoice no puede nacer; Checkout queda open sin AR. | Caso de abandono del informe [línea 343](2026-08-30-dar-billing-checkout-review.md#L343) y aceptación requerida [línea 370](2026-08-30-dar-billing-checkout-review.md#L370). | Decidir si la obligación nace por términos previos/prestación, aceptación final, dispute, o write-off. No usar open indefinido para ocultar una exposición real. |
| ADR-R38 | **HIGH** | Migración automática de confirmed/paid no tiene provenance de aceptación moderna. | Mapping automático [líneas 573-576](2026-08-30-dar-billing-checkout-review.md#L573) frente a invariant de accepted evidence [línea 370](2026-08-30-dar-billing-checkout-review.md#L370). | Usar `acceptance_basis=legacy_status`/provenance explícita, sin inventar actor/canal, y limitar writers nuevos a bases fuertes. |
| ADR-R39 | **HIGH** | El reparto multi-lote se resuelve solo conceptualmente para fulfillment retail, no para consumo clínico. | `consume_product(lot=None)` reparte FEFO ([services.py:293](../../backend/apps/inventory/services.py#L293)); MRP guarda un solo lote y es único por MR/presentation ([models.py:327](../../backend/apps/inventory/models.py#L327)). | Hacer allocations un concepto común de Inventory o exigir un lote único por MRP y rechazar cantidades que requieran más de uno. |

## 5. Decisiones del informe confirmadas

1. Conservar Checkout separado como agregado operativo.
2. Eliminar `Invoice draft` solo después de reubicar todas sus responsabilidades.
3. Eliminar `confirmed` como estado/CTA, preservando freeze, anchor de accrual, AR y stock/fulfillment.
4. Mantener Payment, RefundPayment, RefundReversal y CreditNote append-only.
5. Derivar settlement del ledger y mantener el pago nuevo total exacto.
6. Hacer readiness derivado y el comando final autoritativo bajo locks.
7. Snapshotear la fuente clínica solo después de materialización y freeze.
8. Hacer `PrescriptionSelection` hija del Checkout y derivar full/partial.
9. Separar `abandoned` de `completed/no_charge`.
10. Persistir carrito POS server-side con versión, owner, expiry y takeover controlado.
11. Retirar `auto_create_invoice_on_done` y writers genéricos en el cutover.
12. Quarantinar migraciones ambiguas y no ejecutar movimientos financieros/stock en backfill.

## 6. Cambios necesarios antes del plan

1. Agregar R28-R39 a la matriz normativa, fusionando R30 con R02, R31/R38 con R09/R16, R32 con R19, R36 con R26 y R37 con R10/R27.
2. Elegir `posted` o `issued` y usarlo en estado, timestamp, evento, completion kind, API, analytics y migración.
3. Agregar un modelo conceptual de `ClinicalChargeSnapshot` o campos equivalentes en fuentes clínicas, con `price_effective_at`, unit price/tax/discount provenance.
4. Definir CommandReceipt e idempotency ordering para todos los comandos terminales.
5. Dividir preparación estructural de action availability.
6. Definir replacement/reissue después de void.
7. Resolver stock de RefundReversal.
8. Elegir representación de settlement legacy anómalo.
9. Ampliar el grafo de locks y tests a Appointment.
10. Resolver deuda clínica disputada/no aceptada.

## 7. Máquina de estados recomendada — precisiones

La máquina de la segunda pasada puede conservarse con estas extensiones. En este addendum se usa `posted` para coincidir con p62; si producto elige `issued`, el cambio debe ser global.

```text
MedicalRecord.open
  └─ registrar hecho cobrable
       └─ ClinicalChargeSnapshot [precio/impuesto efectivo + provenance]
            └─ close atómico → Checkout.open

Checkout.open
  ├─ complete_no_charge ──────────────────────> completed/no_charge
  ├─ pay ─────────────────────────────────────> completed/posted_paid
  │                                               └─ Invoice.posted + Payment(s)
  ├─ post_unpaid ─────────────────────────────> completed/posted_unpaid
  │                                               └─ Invoice.posted/unpaid
  └─ abandon, solo si guard lo permite ───────> abandoned

Invoice.posted/unpaid
  ├─ pay total ───────────────────────────────> settlement=paid
  └─ void total ──────────────────────────────> Invoice.voided
                                                   └─ replacement opcional explícito
                                                      con supersession lineage

Invoice.posted/paid
  └─ CreditNote + RefundPayment
       └─ RefundReversal
            └─ política explícita para el efecto stock previo

Legacy settlement
  ├─ sum=0     → unpaid
  ├─ 0<sum<T   → partial anomaly/quarantine representable
  ├─ sum=T     → paid
  └─ sum>T     → overpaid anomaly/quarantine representable
```

Readiness debe tener dos capas:

```text
preparation_readiness
  = source/version/totals/selections/customer estructuralmente válidos

action_availability(actor, command)
  = preparation + permiso + cash session + credit policy + acceptance +
    revalidación autoritativa de stock/settings al ejecutar
```

## 8. Invariantes adicionales

35. Todo cargo clínico cobrable conserva unit price, impuestos/descuentos aplicables, currency si se introduce y `price_effective_at` antes de perder Invoice draft.
36. Cambios posteriores de catálogo nunca reprecifican silenciosamente un hecho clínico ya registrado.
37. Un recibo idempotente identifica tenant, comando, agregado, payload y resultado; replay idéntico devuelve el mismo resultado aunque el agregado ya sea terminal.
38. La reutilización de una key con payload distinto falla sin nuevos efectos.
39. Readiness estructural no autoriza por sí sola ningún comando financiero.
40. Una anomalía de settlement legacy tiene representación/API explícita y nunca se disfraza como unpaid/paid válido.
41. Revertir una nota de crédito no puede dejar inventario distinto sin evento/disposition causal explícito.
42. Una Invoice voided por corrección, si se reemplaza, enlaza durablemente documento anterior y posterior.
43. Un cargo clínico prestado no puede quedar indefinidamente fuera de AR/revenue solo porque el Checkout continúa open; debe existir una política de disputa/obligación/write-off.
44. `accepted_full/partial` se deriva contra cantidad elegible restante al momento de la decisión.
45. El orden de locks incluye recursos implícitos adquiridos por UPDATE y todos los caminos Appointment↔MedicalRecord.
46. Los documentos migrados declaran acceptance provenance legacy sin inventar evidencia moderna.

## 9. Flujo recomendado con precio y aceptación

```text
Durante MedicalRecord.open
  → registrar servicio/producto clínico
  → capturar hecho cobrable + precio/impuesto efectivo
  → consumir stock clínico si aplica

MedicalRecord.close [una transacción]
  → materializar protocolos
  → congelar/versionar receta y fuentes
  → crear Checkout desde hechos cobrables ya valorados
  → completar Appointment con estrategia de concurrencia definida
  → completed/no_charge si no hay cargos/decisiones

Checkout.open
  → resolver Rx/retail/descuentos autorizados
  → evaluar readiness estructural + actions por actor
  → comando terminal con expected_version + CommandReceipt
     → replay check
     → locks en orden global
     → revalidar permisos/aceptación/caja/stock/settings
     → crear Invoice/Payments/allocations o no_charge
     → completar Checkout
     → commit
```

## 10. Migración — precisiones obligatorias

| Caso | Regla adicional |
| --- | --- |
| Draft con InvoiceItem determinista | El `unit_price`, discount y subtotal del InvoiceItem legacy son evidencia preferente; no reconsultar catálogo actual. |
| Fuente clínica sin InvoiceItem/precio probado | No inventar price snapshot; cuarentena o regla de producto explícita con provenance. |
| Confirmed/paid válido | `acceptance_basis=legacy_status`; actor/channel modernos quedan ausentes con provenance, no fabricados. |
| Partial/overpaid | Mantener todos los Payments y elegir representación concreta antes del backfill; definir AR/API/analytics. |
| Refund restock + reversal | Censar y reconciliar stock movements; no asumir que neto monetario implica neto de stock. |
| Cancelled/voided con replacement histórico | Si no hay vínculo probado, no inferir supersession. |

Gates adicionales:

1. Cero diferencias de precios/tax de cargos deterministas entre InvoiceItem legacy y Checkout/Invoice migrados.
2. Toda anomaly row es consultable y reconciliable sin violar el enum normal.
3. Toda Invoice migrada informa acceptance provenance.
4. RefundReversal con restock tiene resolución de stock o queda bloqueado para cutover.
5. Concurrencia Appointment/MR no introduce deadlock sin retry controlado.

## 11. Tests adicionales requeridos

| Caso | Resultado esperado |
| --- | --- |
| Precio de servicio cambia entre alta clínica y cierre | Checkout conserva el precio del evento definido por política; nunca reprice silencioso. |
| Precio retail cambia mientras Checkout open | Comportamiento explícito: snapshot estable o repricing versionado/aceptado; Invoice coincide con lo aceptado. |
| Tax rate cambia entre alta, cierre y post | Se usa el anchor efectivo definido y queda provenance. |
| Replay de pay después de Checkout completed | Misma respuesta/IDs aunque status/version ya sean terminales. |
| Misma key en otro Checkout/comando | No devuelve resultado ajeno; se aplica el scope definido. |
| Dos keys distintas finalizan el mismo Checkout | Un resultado; la otra operación obtiene conflicto sin efectos. |
| Crash/timeout después de commit | Retry devuelve CommandReceipt/result sin duplicar stock/Invoice/Payment. |
| Structural ready, caja cerrada | `preparation_readiness=true`, `actions.pay.allowed=false`; post/no_charge se evalúan por separado. |
| Structural ready, crédito no permitido | Pay puede estar disponible; post_unpaid bloqueado con razón específica. |
| Cliente disputa cargo clínico | Resultado según política: deuda/dispute/write-off; nunca abandono ni open invisible indefinido. |
| Void + replacement | Documento original inmutable/voided, nuevo Checkout/Invoice enlazado y sin doble stock/cargo. |
| Refund retail restock + RefundReversal | Stock final y movimientos siguen la política elegida; no queda incremento ficticio. |
| Refund clínico + reversal | Nunca usa restock retail automático. |
| Close vs assign_patient/status | Sin deadlock no controlado; un resultado serializable y audit consistente. |
| Surtido suplementario completo del remanente | Derivación full respecto de eligible remaining, cap acumulado respetado. |
| Consumo clínico requiere dos lotes | Allocations exactas o rechazo por invariante single-lot; reverso coherente. |
| Legacy partial visible en API/AR | Representación escogida, saldo correcto, pagos intactos y prohibición/reparación explícita. |
| Legacy confirmed sin evidencia moderna | Migra con `acceptance_basis=legacy_status`, sin actor/canal inventados. |
| Expiry vs pay/edit/takeover POS | Una operación gana bajo lock/version; jamás Checkout abandoned con Invoice/Payment simultáneo. |

### Validación ejecutada

Se ejecutaron 56 tests existentes de refunds, Payment ledger y cierre de MedicalRecord:

```text
Ran 56 tests in 40.314s
OK
```

Confirman que el comportamiento actual sigue vigente. El test actual de `RefundReversal` valida ledger/analytics, pero no stock, por lo que no refuta ADR-R29.

## 12. Impacto adicional de implementación

### Backend/DB

- Snapshot de valor económico en la fuente clínica o entidad de cargo.
- CommandReceipt/idempotency result store.
- Representación de settlement anomaly/quarantine.
- Supersession/replacement links.
- Acceptance provenance legacy.

### Inventory

- Contrato de RefundReversal respecto de stock.
- Allocations clínicas o constraint single-lot.
- Audit refund/reversal/lot.

### Frontend/API

- Readiness estructural y availability por acción.
- Vocabulary único posted/issued.
- Presentación explícita de dispute/anomaly/replacement cuando aplique.

### Analytics

- AR de anomaly rows y disputas.
- Price/tax provenance para reconciliación.
- Adjustments de CreditNote/RefundReversal consistentes con stock sin confundir dominios.

### Concurrencia/Tests

- Appointment incluido en lock matrix.
- Replay después de terminal state.
- Expiry/takeover vs finalización.

## 13. Preguntas de negocio estrictamente necesarias

1. **¿Cuándo queda prometido el precio/impuesto de un cargo clínico:** al registrar el servicio/consumo, al cerrar la consulta o al aceptar el Checkout? ¿Puede repricing exigir nueva aceptación?
2. **¿Qué constituye la obligación por servicios ya prestados cuando el cliente disputa o no acepta el total:** términos previos, prestación clínica, aceptación final, estado de disputa o write-off?
3. **¿Qué significa revertir una nota de crédito que ya repuso mercancía:** retirar nuevamente esas unidades, prohibir el reverso o exigir un ajuste físico separado?
4. **¿La corrección de una Invoice unpaid exige reemisión enlazada**, o v1 admite únicamente void total y creación manual de una operación nueva?

Las demás decisiones —scope de idempotencia, representación de quarantine, lock graph, provenance legacy y modelo de allocations— son técnicas y deben resolverse a partir de estas respuestas e invariantes.

## Conclusión

La actualización es una mejora real y sus reclasificaciones principales son defendibles. No corrige el ADR por sí sola: confirma que p62 debe reescribirse antes del plan.

La respuesta a la pregunta central sigue siendo **“todavía no”**: Checkout sí separa preparación de obligación, pero el contrato no conserva aún todos los hechos que hoy congela draft ni resuelve de extremo a extremo corrección, reversos de stock, settlement legacy y deuda clínica no aceptada. Dos desarrolladores todavía podrían construir resultados distintos y plausibles en esos caminos.
