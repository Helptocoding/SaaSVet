# Tercera revisión independiente del ADR Billing / Checkout

**Fecha:** 2026-08-31

**ADR revisado:** `docs/decisions/2026-08-30-p62-billing-checkout-lifecycle.md`

**Antecedente:** `docs/audits/2026-08-31-dar-billing-checkout-rereview.md`

**Alcance:** revisión arquitectónica y contractual; sin implementación.

## 1. Veredicto

### APPROVE WITH CHANGES

El ADR mejoró de forma material y ya no requiere rediseñar su concepto central. `Checkout` es una frontera coherente para preparación comercial; `Invoice` nace como obligación inmutable y `Payment` conserva el settlement append-only. Los seis blockers anteriores y ADR-R28–ADR-R39 están incorporados en intención.

No debe pasar aún al plan de implementación. Quedan cinco contradicciones que pueden producir resultados financieros, migratorios o de concurrencia diferentes: revisión de snapshots ante incrementos clínicos, replacement atómico, adopción de Checkout migrado al cerrar, eventos de reparación legacy y orden total de locks.

La diferencia frente al veredicto anterior es importante: estas correcciones no exigen cambiar el agregado Checkout ni la máquina principal. Por eso corresponde **APPROVE WITH CHANGES**, no `REWORK`.

## 2. Executive Summary

1. Los seis blockers anteriores ya tienen una decisión explícita.
2. R29, R33, R38 y R39 pueden considerarse cerrados.
3. R28 fija el momento de precio/impuesto, pero no resuelve incrementos de una misma fuente clínica única.
4. El precio actual se conserva por el primer InvoiceItem cuando aumenta la cantidad; el ADR permite más de una interpretación futura.
5. D16 exige replacement atómico, pero comandos, API y flujo describen void y replacement secuenciales.
6. `LegacySettlementCase` representa partial/overpaid, pero no define los eventos append-only que los reparan.
7. Reembolsar un sobrepago es devolver un pasivo del cliente; no debe fingirse como CreditNote sobre revenue.
8. El orden de locks incluye Appointment, pero agrupa tablas distintas en un mismo rank y no constituye un orden total.
9. La migración crea Checkout para MedicalRecord abierto sin definir cómo close adopta ese Checkout único.
10. Los drafts consultation creados por la señal de Appointment sin MedicalRecord no tienen mapping explícito.
11. `StockAllocation` debe reservarse para fulfillment asentado; selección abierta solo debe expresar intención/cantidad solicitada.
12. Readiness por acción necesita distinguir blockers actuales de inputs que el propio comando capturará.
13. El tax anchor “primer hecho cobrable” es una política nueva clara, pero no reproduce todos los caminos actuales.
14. El workflow de disputa ya evita exposición invisible; falta definir la vida de `collection_status=disputed` después del post.
15. Con las cinco correcciones bloqueantes, el ADR puede entrar a plan sin otra revisión conceptual completa.

## 3. Estado de los seis blockers anteriores

| Blocker anterior | Estado | Evaluación |
| --- | --- | --- |
| Precio/impuesto | **Parcialmente cerrado** | D11 fija anchors, pero no la revisión ante incrementos de fuentes únicas y afirma una equivalencia incorrecta con todos los writers actuales. |
| RefundReversal + stock | **Cerrado** | V1 prohíbe reversal cuando hubo restock y manda legacy a reconciliación física. |
| Legacy partial/overpaid | **Parcialmente cerrado** | La cuarentena/read model está definida; falta el ledger de reparación. |
| Idempotencia | **Casi cerrado** | Scope, actor, replay-before-guards y transacción están definidos; faltan canonicalización versionada y primitive segura de claim. |
| Disputa clínica | **Casi cerrado** | Hold, owner, SLA y outcomes resuelven la invisibilidad; falta el lifecycle posterior de la Invoice disputada. |
| Locks con Appointment | **Parcialmente cerrado** | Appointment→MedicalRecord está decidido, pero los ranks agrupados no forman un orden total entre modelos. |

## 4. Revisión ADR-R28–ADR-R39

| ID | Estado | Comentario |
| --- | --- | --- |
| ADR-R28 | Parcial | Evento efectivo elegido; falta semántica de revisión/incremento. |
| ADR-R29 | Cerrado | Prohibición conservadora correcta. |
| ADR-R30 | Parcial | Dos capas correctas; falta separar required inputs. |
| ADR-R31 | Parcial | Representación correcta; reparación incompleta. |
| ADR-R32 | Casi cerrado | Contrato observable correcto; faltan dos precisiones técnicas obligatorias. |
| ADR-R33 | Cerrado | `posted` es único; “Emitida” solo UI. |
| ADR-R34 | Parcial | Baseline local/acumulado correcto; timing de allocations ambiguo. |
| ADR-R35 | Parcial | Lineage y dispositions correctos; falta comando atómico prometido. |
| ADR-R36 | Parcial | Appointment incorporado; falta model sub-order. |
| ADR-R37 | Casi cerrado | Pre-post resuelto; falta resolver collection dispute posterior. |
| ADR-R38 | Cerrado | Provenance legacy débil y explícita, sin evidencia inventada. |
| ADR-R39 | Cerrado | Single-lot clínico v1 y multilote retail/Rx explícitos. |

## 5. Hallazgos nuevos

| ID | Severidad | Problema | Evidencia | Recomendación |
| --- | --- | --- | --- | --- |
| ADR-R40 | **BLOCKER** | `ClinicalChargeSnapshot` no define qué ocurre al incrementar una fuente clínica única después de cambiar catálogo. | D11 ([ADR:400](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L400)); MedicalRecordService es único por MR/service ([models.py:438](../../backend/apps/medical_records/models.py#L438)); el writer incrementa InvoiceItem y conserva `unit_price` ([views.py:223](../../backend/apps/medical_records/views.py#L223), [services.py:24](../../backend/apps/billing/services.py#L24)); MRP hace lo mismo ([services.py:48](../../backend/apps/medical_records/services.py#L48)). | Elegir charge entry/revisión autoritativa, precio de incrementos, constraints de versión activa y qué copia close. |
| ADR-R41 | **BLOCKER** | D16 exige `void_and_prepare_replacement` atómico, pero comandos/API solo ofrecen void seguido de replacement. | Regla atómica [ADR:578](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L578); comandos [ADR:970](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L970); API [ADR:1167](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L1167). | Añadir comando/endpoint idempotente único que void + dispositions + Checkout replacement en una transacción. |
| ADR-R42 | **BLOCKER de migración** | Un draft con MR open crea Checkout primario antes de close, pero close también debe crear el único primario. Falta adopción/rebuild. | Creación normal [ADR:704](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L704); mapping [ADR:1296](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L1296). La señal actual puede crear draft solo con Appointment ([signals.py:10](../../backend/apps/billing/signals.py#L10)). | Diferir materialización o definir protocolo de adopción bajo locks; agregar mapping para appointment-only drafts. |
| ADR-R43 | **BLOCKER** | La cuarentena legacy es read-only y reparable a la vez, sin comandos/eventos financieros definidos. | D15 [ADR:533](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L533); API solo nominal [ADR:1145](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L1145). RefundPayment pertenece obligatoriamente a CreditNote ([models.py:609](../../backend/apps/billing/models.py#L609)). | Definir eventos append-only para completar partial y devolver liability overpaid, o limitar v1 a reconciliación externa. |
| ADR-R44 | **BLOCKER de concurrencia** | El orden global agrupa modelos distintos; PK ascendente no ordena Invoice frente a CreditNote. | Lock graph [ADR:509](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L509). | Rank único por modelo y orden `(model_rank, pk)`; comandos desde hijos preleen y lockean padres primero. |
| ADR-R45 | **HIGH** | “Allocation” se usa para selección abierta y fulfillment con StockMovement. | D5 [ADR:262](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L262), D6 [ADR:293](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L293), StockAllocation [ADR:741](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L741). | Open guarda requested presentation/quantity; StockAllocation nace solo en post y cuenta para fulfillment efectivo. |
| ADR-R46 | **HIGH** | `actions.pay.allowed` puede depender de ObligationEvidence que el propio pay crea. | D12 [ADR:432](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L432); readiness [ADR:768](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L768). | Separar `blockers` de `required_inputs`, o definir allowed como capacidad de intentar con payload completo. |
| ADR-R47 | **HIGH** | El ADR afirma que el draft actual nace con el primer cargo, pero puede nacer en close, included product o Appointment.done. | D11 [ADR:417](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L417); product writer crea Invoice antes de revisar cost_behavior ([services.py:48](../../backend/apps/medical_records/services.py#L48)); close siempre la crea ([views.py:438](../../backend/apps/medical_records/views.py#L438)); signal no copia tax_rate ([signals.py:10](../../backend/apps/billing/signals.py#L10)). | Declarar first-billable como corrección deliberada y clasificar esas provenances en migración/tests. |
| ADR-R48 | **HIGH** | `enforced_under_terms` resuelve CheckoutDispute pero crea Invoice con collection_status disputed sin transición posterior. | Disputa [ADR:445](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L445); Invoice [ADR:812](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L812). | Crear collection case con owner/transiciones o convertir el campo en provenance inmutable `disputed_at_post`. |
| ADR-R49 | **HIGH** | Claim y hash canónico de CommandReceipt no definen primitive segura ni equivalencia de payload. | D14 [ADR:484](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L484). | `INSERT ON CONFLICT`/savepoint explícito, canonical schema versionado y regla para Decimal/defaults/orden de líneas. |
| ADR-R50 | **HIGH** | Receipt, ObligationEvidence y disputa agregan datos persistentes sin contrato completo de minimización/lectura. | Receipt/evidence [ADR:432](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L432), [ADR:484](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md#L484). | Result envelope allowlisted; prohibir secretos/blobs; permisos de lectura, retención y audit. |

## 6. Decisiones confirmadas

Se confirman sin cambio:

1. Checkout independiente.
2. Invoice sin draft/confirmed.
3. `posted` como lifecycle documental y `paid` derivado del ledger.
4. `completed/no_charge`, `completed/posted_paid` y `completed/posted_unpaid` como outcomes únicos.
5. RefundReversal bloqueado después de restock en v1.
6. `LegacySettlementCase` separado del enum normal.
7. ObligationEvidence fuerte para writers nuevos y provenance débil explícita para legacy.
8. PrescriptionRevision inmutable, baseline de remanente y cap acumulado.
9. Single-lot clínico v1; multilote retail/Rx con fulfillment probado.
10. Readiness derivado y comando final autoritativo.
11. Appointment.done deja de ser writer financiero.
12. Cero Invoice/Payment para no_charge v1.

## 7. Cambios requeridos antes del plan

1. Resolver ADR-R40 con una sola semántica de revisión/precio para incrementos.
2. Añadir `void_and_prepare_replacement` al command/API/state contract.
3. Definir adopción de Checkout migrado y mapping appointment-only.
4. Definir eventos/permisos de reparación LegacySettlementCase.
5. Reescribir lock order como orden total por modelo y PK.
6. Precisar R45–R50 en los contratos de API, datos, permisos y tests.

## 8. Precisiones a la máquina recomendada

```text
Clinical source mutation
  → immutable charge entry/revision chosen by R40
  → close copies exactly the authoritative economic facts

Invoice.posted/unpaid + continuing exposure correction
  → void_and_prepare_replacement [one CommandReceipt/transaction]
     → old Invoice.voided
     → new Checkout.replacement.open

LegacySettlementCase.partial
  → append exact settlement event OR external-only resolution

LegacySettlementCase.overpaid
  → liability-return event OR external-only resolution
  → never synthetic CreditNote revenue/stock

CheckoutDispute enforced_under_terms
  → Invoice.posted/unpaid
  → explicit collection-case lifecycle OR immutable disputed-at-post provenance
```

## 9. Invariantes adicionales

47. Dos incrementos de la misma fuente clínica producen el mismo total bajo cualquier retry y cambio de catálogo conforme a una regla única documentada.
48. Exactamente una revisión/entrada económica es autoritativa por unidad cobrada; close no duplica revisiones superseded.
49. Continuing exposure nunca queda sin Invoice ni Checkout replacement entre commits.
50. El comando atómico de replacement tiene un único CommandReceipt y replay devuelve ambas referencias.
51. Un Checkout primario migrado se adopta o difiere; close nunca intenta crear un segundo primario.
52. Todo draft consultation sin MedicalRecord tiene destino/cuarentena explícita.
53. Reparar un partial/overpaid nunca muta ni borra eventos previos.
54. Devolver un overpayment no reduce revenue ni mueve stock.
55. Cada modelo lockeable tiene rank único; el orden es total y verificable.
56. StockAllocation implica fulfillment committed y StockMovement; no existe como selección tentativa.
57. `actions.allowed` no se vuelve falso solo por un input que el propio comando está autorizado a capturar.
58. Receipts/evidencias persisten únicamente datos allowlisted y tienen read policy tenant-safe.

## 10. Migración — precisiones

| Caso | Regla requerida |
| --- | --- |
| draft + MR open | No crear anticipadamente o adoptar bajo close; reconstruir clínica desde snapshots autoritativos. |
| draft appointment-only | Mapping explícito: esperar vínculo, abandoned/no_charge operativo o cuarentena según evidencia. |
| Invoice tax_rate creado antes de cargo | Conservar provenance real; no llamarlo BillingContext first-billable. |
| partial reparable | Evento de settlement exacto append-only con CashSession/idempotencia definidos. |
| overpaid reparable | Liability refund separado de CreditNote, o resolución externa documentada. |
| overpaid/partial no reparado | Permanece fuera de API/AR/revenue normal. |

## 11. Tests adicionales obligatorios

| Caso | Resultado requerido |
| --- | --- |
| Servicio qty 1 a precio A; catálogo B; agregar qty 1 | Line structure, revisions, price y total siguen la política R40. |
| Producto clínico repetido con precio cambiado | Misma garantía y stock single-lot correcto. |
| Concurrent clinical increments | Un total/snapshot autoritativo, sin duplicados. |
| Included-only crea legacy draft | Provenance/tax clasificados; no se inventa first-billable. |
| Appointment.done crea draft sin MR | Mapping determinista o cuarentena explícita. |
| MR open migrado con Checkout; luego editar y cerrar | Un solo primary Checkout y clínica reconstruida correctamente. |
| Fallo al crear replacement después de preparar void | Rollback total: Invoice original sigue posted. |
| Replay atomic replacement | Mismos IDs de void/replacement; cero doble stock/audit. |
| Standalone void con goods_retained/continuing exposure | Rechazado. |
| Legacy partial settlement | Payment/evento exacto, CashSession y read model coherentes. |
| Legacy overpaid return | Liability/cash correctos; revenue y stock sin cambios. |
| refund vs reverse_credit_note concurrente | Sin deadlock no controlado; total order aplicado. |
| replacement vs pay/void concurrente | Una transición, cero efectos huérfanos. |
| Rx accepted mientras open | Cero StockAllocation/Movement committed antes de post. |
| Stock cambia después de selección | Finalize reasigna o bloquea; nunca fulfillment falso. |
| Pay requiere acknowledgement en payload | CTA disponible con required_inputs; comando crea evidence atómicamente. |
| Invoice enforced disputed luego pagada/resuelta | Collection state/provenance final inequívoca. |
| CommandReceipt con Decimal/defaults/line order equivalentes | Resultado conforme a canonicalization versionada. |

### Validación ejecutada

```text
Ran 56 tests in 41.664s
OK
```

Suite: refunds, Payment ledger y MedicalRecord close. Confirma el comportamiento vigente; no valida todavía las entidades futuras.

## 12. Impacto de implementación adicional

| Área | Ajuste adicional |
| --- | --- |
| Backend/DB | Charge revision/entry, atomic replacement command, model lock ranks, legacy repair events. |
| API | Atomic replacement, required_inputs, explicit legacy commands, typed receipt result. |
| Inventory | StockAllocation solo committed; overpayment sin stock; replacement dispositions atómicas. |
| Migration | Open-MR adoption, appointment-only drafts y tax provenance real. |
| Analytics | Separar liability refund, collection dispute y tax-anchor provenance. |
| Permissions | Legacy liability return y read access a evidence/dispute/receipt. |
| Tests | Casos de la sección 11 bajo PostgreSQL cuando hay concurrencia. |

## 13. Preguntas estrictamente necesarias

1. **¿Un incremento posterior de la misma fuente clínica conserva el primer precio o crea unidades a un precio nuevo?**
2. **¿V1 devolverá sobrepagos legacy dentro del ledger o solo documentará una reconciliación externa?**
3. **¿`collection_status=disputed` es estado actual mutable o provenance histórica del post?**

## Conclusión

La actualización sí resuelve la mayor parte de la ambigüedad original de draft/confirmed y conserva mejor consulta, receta, stock, Invoice y Payment. El ADR ya no necesita rework de su arquitectura central.

Todavía no puede implementarse literalmente sin decisiones adicionales: dos desarrolladores podrían cobrar incrementos clínicos con precios distintos, ejecutar replacement con atomicidad distinta, cerrar de manera distinta un MR ya migrado, devolver sobrepagos con eventos incompatibles o adquirir locks en orden inverso. Al cerrar ADR-R40–ADR-R44 y precisar ADR-R45–ADR-R50, el documento puede pasar a planificación.
