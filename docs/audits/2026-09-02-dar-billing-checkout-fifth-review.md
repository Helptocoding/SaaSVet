# Quinta revisión independiente del DAR — Billing / Checkout

**Fecha:** 2026-09-02  
**Documento revisado:** `docs/decisions/2026-08-30-p62-billing-checkout-lifecycle.md`  
**Versión revisada:** 176,003 bytes; SHA-256 `B178C17A267A05D33FFA1957CA8840E8E1B822166AD89CA906DCC52E0DD8FF7E`  
**Alcance:** revisión arquitectónica; no se modificó código, esquema, API, frontend ni tests.

## 1. Veredicto

## APPROVE WITH CHANGES

La separación central `MedicalRecord → Checkout → Invoice → Payment` es correcta y el ADR actualizado cierra de forma sustantiva ADR-R51–ADR-R58. Ya existe un contrato coherente para evidencia Rx externa, identidad de eventos financieros hijos, fulfillment, cutover, repairability legacy, estimados, locks y repricing.

No obstante, **todavía no es seguro convertir literalmente el ADR en migraciones, modelos o endpoints**. Quedan cuatro blockers nuevos y acotados: la semántica temporal de analytics al liquidar un `partial` legacy; el destino de la exposición después de `void_and_prepare_replacement`; el lifecycle del `LegacySettlementCase` cuando se revierte una devolución; y el comportamiento fail-closed cuando falta `BillingCutoverControl` para una organización.

El resultado de readiness de implementación es **NO-GO / REQUEST CHANGES** hasta cerrar ADR-R59–ADR-R62. No se requiere replantear Checkout ni volver a Invoice draft.

## 2. Executive Summary

1. ADR-R51–ADR-R58 están cerrados en sustancia, no solo mencionados.
2. Checkout sigue siendo una frontera adecuada entre preparación comercial editable y obligación financiera inmutable.
3. Readiness por acción, `required_inputs`, revalidación transaccional y versionado cierran correctamente el riesgo TOCTOU.
4. La evidencia Rx externa ahora conserva revisión, fingerprint, coverage, ACL, retención y migración.
5. Stock, custodia, dinero y fulfillment Rx ya están separados mediante eventos y lineage auditable.
6. El cutover por organización con mutation log, freeze y final watermark resuelve la ventana principal de backfill.
7. **ADR-R59 / BLOCKER:** `settle_legacy_partial` exige reconocer solo el pago nuevo hoy, pero el contrato y el código actuales reconocen el total de la Invoice en `paid_at`.
8. **ADR-R60 / BLOCKER:** el comando de replacement anula la obligación y deja un Checkout editable que, especialmente en POS, todavía puede abandonarse o llegar a `no_charge` sin una regla específica.
9. **ADR-R61 / BLOCKER:** revertir un `LegacyLiabilityReturn` reabre el pasivo, pero el case quedó resuelto y el siguiente retorno exige case abierto.
10. **ADR-R62 / BLOCKER:** todo writer debe lockear `BillingCutoverControl`, pero no se define qué pasa si la fila no existe ni cómo se provisiona para organizaciones nuevas.
11. El contrato financiero real continúa en versión 1.0 frozen; la versión 1.1 debe publicarse antes de implementar eventos financieros nuevos.
12. El gate que habla de “rollback de feature flag” contradice la prohibición de volver a writers legacy después del primer evento futuro.
13. Deben acotarse longitud/formato del raw `Idempotency-Key` y rango/cantidad de líneas canónicas.
14. La suite de caracterización ejecutada quedó verde: 114 tests, 1 skipped, 0 fallos.
15. Si ADR-R59–ADR-R62 se cierran normativamente, basta una revisión enfocada; no hace falta otra reestructuración central.

## 3. Qué está bien

### 3.1 Cierre de los hallazgos anteriores

| Hallazgo anterior | Evaluación de cierre | Evidencia en el ADR actualizado |
| --- | --- | --- |
| ADR-R51 — atestación Rx externa | **Cerrado** | D18 mueve la evidencia a Checkout/item revision, usa fingerprint, revalida al post, crea coverage de InvoiceItem y conserva ACL/retención/migración. |
| ADR-R52 — identidad financiera hija | **Cerrado en diseño** | D19 deriva identidad de `CommandReceipt + event_kind + line_index`, conserva unique por tenant y define ReturnPayment/Reversal. Falta publicar el contrato 1.1 como gate. |
| ADR-R53 — allocation/fulfillment | **Cerrado** | D20 separa stock, custodia, dinero y cap Rx; define return, discard, `goods_retained` y redelivery neutral. |
| ADR-R54 — cutover online | **Cerrado en su carrera principal** | D21 instrumenta writers, usa locks compartido/exclusivo, final watermark, catch-up/rebuild y cero mutations pendientes. ADR-R62 es un edge de provisioning nuevo. |
| ADR-R55 — collectibility legacy | **Cerrado** | D22 separa `kind` de `repairability`, exige evidence/hashes y hace no sobreescribible el hard check. |
| ADR-R56 — PDF draft | **Cerrado** | D23 crea `CheckoutEstimate` append-only, versionado y explícitamente no financiero; define retiro/adaptación del PDF legacy. |
| ADR-R57 — orden de locks | **Cerrado** | La regla se aplica a primera adquisición de filas existentes y permite re-update de filas ya poseídas. |
| ADR-R58 — repricing | **Cerrado** | D24 define comando, permiso, versión, receipt, razón y transición atómica entre ciclos. |

### 3.2 Decisiones confirmadas

- Invoice nace únicamente como documento financiero `posted`; no existe como área de trabajo editable.
- `Checkout.completed` expresa que terminó una operación comercial y su `completion_kind` distingue `posted_paid`, `posted_unpaid` y `no_charge`.
- `Checkout.abandoned` significa que no nació obligación; no es sinónimo de $0 ni de condonación.
- `payment_status` es una proyección del ledger, no una autoridad independiente.
- Un MedicalRecord abierto no debe producir una Invoice posted; `close_medical_record` crea el Checkout primario.
- Productos clínicos se consumen al usarse y usan single-lot explícito en v1; retail/Rx se asigna y entrega al post.
- El rechazo de una selección Rx es una decisión comercial del Checkout y no altera la receta clínica.
- `post_checkout_unpaid` es una capacidad de crédito deliberadamente limitada, con evidencia de obligación y autorización separada.
- Refund/CreditNote no reabre cobranza; los counterevents mantienen trazabilidad append-only.
- POS y consulta comparten post/payment/stock, pero no comparten origen clínico ni obligación de tener MedicalRecord.

## 4. Problemas encontrados

| ID | Severidad | Problema | Evidencia | Recomendación |
| --- | --- | --- | --- | --- |
| ADR-R59 | **BLOCKER** | Semántica temporal contradictoria para `revenue_paid` al liquidar un `partial` legacy | ADR p62:733–741 y 2229 ordena publicar solo el importe nuevo hoy; p62:1911 define `Revenue paid` por `Invoice.paid_at`. El contrato frozen 1.0, §8.3/DD-008, mantiene cash-basis por Invoice completa. `analytics/services.py:198–221` suma `Invoice.total` de todas las paid por `paid_at`; `billing/services.py:309–328` fija ese anchor al pago final. | Elegir y documentar una sola política. Recomendado: activar DD-008 en el contrato 1.1, derivar cash/revenue paid de Payments efectivos por `occurred_at` y definir late-arrival/frozen-snapshot para pagos legacy anteriores. Si se conserva v1, D15 debe reconocer que el total completo cae en `paid_at` y separar esa métrica del movimiento de caja nuevo. |
| ADR-R60 | **BLOCKER** | `void_and_prepare_replacement` no garantiza qué pasa con la exposición después del commit | p62:774–812 anula la Invoice y crea `Checkout.kind=replacement.open`; un Checkout no es AR. p62:1424 permite abandonar direct sale; p62:1511–1512 deja `no_charge/abandon` a reglas genéricas. No hay baseline obligatorio, case abierto, SLA ni prohibición expresa de remover/abandonar valor ya entregado. | Definir si continuidad significa financiera u operacional. Recomendado: `ReplacementCase.open` o hold derivado, líneas carried obligatorias, owner/SLA y prohibición de `abandon`, expiry, `no_charge` o eliminación del valor ya prestado/retenido salvo comando de waiver explícito y autorizado. Si la obligación debe ser continua en sentido financiero, crear la nueva Invoice posted en la misma transacción en vez de un Checkout editable. |
| ADR-R61 | **BLOCKER** | La reversa del retorno reabre el liability pero no reabre ni sucede el caso operativo | p62:747 exige case open para devolver; el retorno lo resuelve. p62:926 y 1523 dicen que la reversa reabre liability y que otro retorno usa eventos nuevos, pero no cambian `LegacySettlementCase` ni crean sucesor. | Hacer que reversal cree una nueva generación/episode o proyecte el case a `open/reassessment_required`, con owner, SLA, versión y revalidación de repairability. Invariante: todo liability positivo debe tener exactamente un caso accionable abierto. Añadir retorno→reversa→nuevo retorno. |
| ADR-R62 | **BLOCKER** | No existe contrato para organización sin `BillingCutoverControl` | p62:625 y 973 hacen de Control la primera coordination row de todo writer y autoridad por organización, pero no especifican creación, default, missing-row response ni carrera con provisioning. Un `get_or_create` tardío no es equivalente a lockear una fila preexistente. | Provisionar Control antes de habilitar cualquier writer, incluirlo atómicamente al crear organización y fallar cerrado si falta. Definir el mode inicial por fase de despliegue y prohibir creación lazy dentro del comando de negocio. Testear missing row, nueva organización y creación concurrente. |
| ADR-R63 | **HIGH** | El contrato financiero 1.1 todavía no existe como autoridad real | `docs/financial-event-model-contract.md:3` sigue en `Version: 1.0 (frozen)`. D19 y M1 prometen publicar 1.1 en la misma slice, pero hoy el contrato superior aún no autoriza esas formas. | Hacer del documento 1.1 aprobado el primer artefacto del slice financiero. No mergear Payment/Return/Reversal nuevos antes de contract tests y sign-off. Incluir ADR-R59 en esa versión. |
| ADR-R64 | **HIGH** | El gate de rollback es ambiguo y contradice la autoridad future | p62:1002 y 2262 prohíben volver a legacy después del primer evento futuro; p62:2211 exige que “rollback de feature flag” conserve operaciones futuras. | Sustituirlo por rollback de UI/read adapter únicamente. Writers futuros siguen siendo autoridad; recuperación es forward-fix. Definir explícitamente qué componentes sí pueden revertirse. |
| ADR-R65 | **MEDIUM** | Límites del contrato de idempotencia incompletos | D19 fija key hija de 64 caracteres e índice 4d, pero D14 no fija longitud/formato del raw key ni máximo de líneas; `Payment.idempotency_key` real es `max_length=64`. | Fijar límite en bytes y charset para raw key, límite de payment lines y rango `line_index`; rechazar antes de claim con código estable. |

## 5. Decisiones del DAR confirmadas

La siguiente matriz responde si la eliminación de `Invoice.draft/confirmed` conserva las responsabilidades actuales:

| Responsabilidad actual | Destino recomendado | ¿Conservada? |
| --- | --- | --- |
| Edición de líneas y total | Checkout/CheckoutItem versionado | Sí |
| Snapshot clínico antes de cobro | ClinicalChargeSnapshot + Checkout | Sí |
| Selección de receta | PrescriptionSelection | Sí |
| Documento previo | CheckoutEstimate no financiero | Sí |
| Freeze financiero | Creación de Invoice posted | Sí |
| `confirmed_at` como devengo | `posted_at` + evento de posting | Sí |
| Stock retail/Rx | StockAllocation/Movement al post | Sí |
| Consumo clínico | En el writer clínico, antes de Checkout | Sí |
| AR | Invoice posted/unpaid + CollectionCase cuando aplique | Sí |
| Pago/split | Payment append-only por línea canónica | Sí, sujeto a contrato 1.1 |
| Refund/reversal | CreditNote/RefundPayment/RefundReversal | Sí |
| Audit e idempotencia | Eventos + CommandReceipt | Sí |
| Analytics | `posted_at`, Payments y adjustments | **No totalmente:** falta ADR-R59 |

La eliminación de `draft` y `confirmed` sigue aprobada. El problema pendiente no es necesitar esos estados, sino cerrar contratos satélite del modelo futuro.

## 6. Decisiones que deben cambiar

1. Agregar ADR-R59 con fórmula y temporalidad únicas para cash/revenue de settlement legacy.
2. Agregar ADR-R60 con lifecycle posterior del Checkout replacement y definición exacta de “exposición continua”.
3. Agregar ADR-R61 con transición/episode del LegacySettlementCase tras reversal.
4. Agregar ADR-R62 con provisioning y fail-closed de BillingCutoverControl.
5. Enmendar la versión 1.1 del contrato financiero para incluir identidad hija, liability events **y** la decisión de ADR-R59.
6. Reescribir el gate de rollback como rollback de presentación/lectura, nunca de autoridad de escritura.
7. Cerrar límites de `Idempotency-Key` y line index en el contrato API.

## 7. Decisiones que faltan

### Antes del plan de implementación

- Elegir cash-basis por Payment o compatibilidad temporal por Invoice para legacy partial.
- Definir si replacement mantiene una exposición operacional o una obligación financiera continua.
- Definir el estado/generación accionable del case después de `reverse_legacy_liability_return`.
- Definir provisioning y default de `BillingCutoverControl` para organizaciones existentes y nuevas.
- Aprobar D1–D24 por producto; el ADR todavía los presenta como pendientes de sign-off.

### Pueden cerrarse en especificación técnica, pero antes de exponer API

- Longitud/charset del raw idempotency key y máximo de payment lines.
- Envelope exacto y códigos de error de los tres casos nuevos.
- Nombres físicos de índices/constraints, siempre que implementen las invariantes del ADR.

## 8. Máquina de estados recomendada

### 8.1 Checkout normal

~~~text
open
 ├─ pay_checkout ───────────▶ completed / posted_paid   + Invoice posted/paid
 ├─ post_checkout_unpaid ───▶ completed / posted_unpaid + Invoice posted/unpaid
 ├─ complete_no_charge ─────▶ completed / no_charge     + sin Invoice
 └─ abandon permitido ──────▶ abandoned                 + sin Invoice
~~~

`readiness` y `required_inputs` siguen siendo derivados por acción; todos se revalidan bajo locks en el comando terminal.

### 8.2 Replacement

El ADR debe escoger uno de estos contratos; se recomienda A.

**A. Continuidad operacional controlada**

~~~text
Invoice posted/unpaid
 └─ void_and_prepare_replacement
      ├─ Invoice.voided
      ├─ ReplacementCase.open / owner / SLA
      └─ Checkout replacement.open con carried baseline
           ├─ pay/post ─────────────▶ nueva Invoice + case resolved/replaced
           ├─ waiver explícito ─────▶ no_charge + case resolved/waived
           └─ abandon/expiry/remove carried value ─▶ prohibido
~~~

**B. Continuidad financiera estricta**

~~~text
Invoice posted/unpaid
 └─ void_and_replace_invoice ─▶ Invoice original voided + Invoice nueva posted
~~~

No es correcto llamar “obligación financiera continua” a `Invoice.voided + Checkout.open`, porque por definición Checkout no es AR.

### 8.3 Invoice y settlement

~~~text
Invoice.posted/unpaid ── pay exacto ──▶ posted/paid
Invoice.posted/unpaid ── void terminal ─▶ voided
Invoice.posted/paid ── CreditNote/refund/reversal ─▶ permanece paid
~~~

### 8.4 Legacy liability case

~~~text
case open/returnable + liability > 0
 └─ return exacto ─▶ case resolved/returned + liability = 0

case resolved/returned
 └─ reverse return ─▶ nueva generation open/reassessment_required + liability > 0
                         └─ nueva assessment returnable
                              └─ nuevo return exacto
~~~

El historial anterior no se reescribe; `state` es una proyección de episodes/eventos.

## 9. Invariantes

1. `MedicalRecord.status=open ⇒ no Invoice futura posted por esa consulta`.
2. `Invoice posted ⇒ MedicalRecord clínico relacionado está cerrado e inmutable en hechos facturados`.
3. Checkout open no es Invoice, AR, revenue ni aceptación financiera.
4. Invoice posted es inmutable; toda corrección es documento/evento posterior.
5. `paid ⇔ effective Payments = total`; Payment no es status manual.
6. No existen Payments de $0 ni pagos parciales futuros.
7. Un split suma exactamente el saldo y usa índices canónicos únicos.
8. Todo post/pay revalida version, readiness, inputs, evidence, stock, tenant y permisos dentro de la transacción.
9. Cada InvoiceItem regulado tiene coverage válida para la revisión/fingerprint exactos.
10. Stock, custodia, dinero y fulfillment Rx nunca se derivan implícitamente uno del otro.
11. El cap Rx se deriva de FulfillmentEvents; v1 no lo restaura por un return.
12. Replacement `goods_retained` no duplica stock ni fulfillment.
13. Un replacement con valor ya prestado/retenido no puede desaparecer mediante reglas genéricas.
14. Todo legacy customer liability positivo tiene exactamente un case/episode accionable abierto.
15. Una reversa de retorno no deja liability abierto con case terminal.
16. `revenue_paid` y movimiento de caja tienen una única fórmula temporal versionada y reconciliable.
17. Toda organización tiene BillingCutoverControl antes del primer writer instrumentado.
18. Falta de BillingCutoverControl falla cerrado y no ejecuta efectos.
19. `freezing` impide iniciar writers legacy/future; replay completo no duplica efectos.
20. Future solo se activa con `processed_watermark=final_watermark` y cero mutation sin procesar.
21. Ningún writer vuelve a legacy después del primer evento futuro.
22. La primera adquisición de rows existentes respeta `(model_rank, primary_key)`.
23. Todo comando terminal tiene CommandReceipt durable y replay-before-guards.
24. Idempotency keys raw/hijas están acotadas y no colisionan entre command kinds.
25. Ningún backfill inventa aceptación, actor, canal, stock, tax o lineage que no pueda probar.

## 10. Flujo Consulta → Checkout → Billing → Payment

~~~text
Appointment / MedicalRecord open
  ├─ hechos clínicos y ClinicalChargeEntry/QuantityEvents
  ├─ consumo clínico ocurre al uso
  └─ nunca Invoice posted

close_medical_record
  ├─ locks y revalidación Appointment → MedicalRecord
  ├─ congela hechos cobrables y PrescriptionRevision
  ├─ adopta LegacyCheckoutSeed si existe
  └─ crea exactamente un Checkout primary

Checkout open
  ├─ edición retail / PrescriptionSelection / attestation / estimate
  ├─ no_charge ───────────────▶ completed sin Invoice
  ├─ pay ─────────────────────▶ Invoice posted + stock/fulfillment + Payments
  └─ post_unpaid autorizado ──▶ Invoice posted + stock/fulfillment + AR

Invoice posted/unpaid
  ├─ pay exacto ──────────────▶ paid
  ├─ CollectionCase ──────────▶ collectible/disputed/resolved
  └─ corrección ──────────────▶ replacement según ADR-R60
~~~

## 11. POS

La abstracción común sigue siendo correcta en post, Invoice, Payment, stock, refund, idempotencia y permisos. POS conserva diferencias reales:

- no requiere MedicalRecord ni Appointment;
- su Checkout puede existir antes de cualquier decisión clínica;
- puede abandonarse/expirar solo mientras no sea replacement de valor ya entregado;
- un producto regulado exige ExternalPrescriptionAttestation exacta;
- crédito puede estar más restringido por política;
- replacement de direct sale con `goods_retained` debe quedar cubierto por ADR-R60, pues la regla general de abandono POS es precisamente el hueco actual.

Recepción debería ver `Por preparar`, `Pendiente de pago`, `Pagado`, `Disputa` y `Corrección pendiente`; “Checkout” puede ser término técnico, pero la UI no debe presentar un replacement abierto como si no existiera exposición.

## 12. Recetas

D18 y D20 hacen implementable el flujo:

~~~text
PrescriptionRevisionItem
  → PrescriptionSelection pending/accepted/declined
  → CheckoutItem regulado
  → attestation externa cuando aplique
  → post revalida evidence/cap/stock
  → InvoiceItem coverage
  → FulfillmentEvent acumulado
~~~

Aceptación parcial, suplementos, cambio de presentación, stale attestation, devolución, redelivery y `goods_retained` tienen resultados distinguibles. No se detectó un blocker nuevo de receta. La atestación pertenece a Checkout/revisión como evidencia pre-post y la coverage pertenece al documento/fulfillment post; esa separación es correcta.

## 13. Stock

| Tipo | Reserva | Consumo/salida | Pago requerido | Corrección |
| --- | --- | --- | --- | --- |
| `clinical_consumable` | No | Al usarlo en MedicalRecord; single-lot v1 | No | Evento clínico/ajuste físico explícito; no refund-restock automático |
| `prescription_retail` | No en v1 | Al postear Checkout, con allocations FEFO y fulfillment | Puede ser posted/unpaid | Return/discard/redelivery por eventos; cap Rx separado |
| `direct_sale_retail` | No en v1 | Al postear Checkout | Normalmente pago; crédito si policy lo permite | Return/restock/discard explícito |
| replacement `goods_retained` | No | No crea nueva salida | Nueva obligación según resultado | Reutiliza allocation/fulfillment/coverage original |

`post-unpaid` puede mover stock porque el ADR define posting como emisión más entrega, no como pago. Un void posterior no restockea implícitamente: exige disposition física. Este contrato está correctamente cerrado.

## 14. Migración

### 14.1 Mapping confirmado

| Legacy | Futuro |
| --- | --- |
| draft + MR open determinista | LegacyCheckoutSeed; Checkout primary solo en close |
| draft + MR closed determinista | Checkout open o completed/no_charge según evidencia |
| draft direct_sale | Checkout open/stale o abandoned según decisión probada |
| confirmed válido sin Payment | Invoice posted/unpaid + provenance legacy |
| paid con Payments = total | Invoice posted/paid; preservar anchors/Payments |
| partial | LegacySettlementCase partial/unassessed; no AR normal hasta collectible |
| overpaid | LegacySettlementCase overpaid/unassessed; liability solo si obligación probada |
| cancelled antes de obligación | Checkout abandoned |
| cancelled después de obligación | Invoice voided |
| evidencia contradictoria | Quarantine; no inferir aceptación/venta/no_charge |

### 14.2 Cambios requeridos al cutover

1. Provisionar BillingCutoverControl para todas las organizaciones antes de instrumentar writers.
2. Crear Control en la misma transacción de provisioning de una organización nueva.
3. Fallar cerrado ante missing/corrupt Control.
4. Guardar baseline y final watermark en el Run; no pre-marcar como procesada una mutation que el backfill no observó.
5. Enumerar y reconciliar todas las mutations existentes `id <= final_watermark`, incluyendo gaps de sequence.
6. Mantener future como única autoridad después de activación; rollback solo de UI/read adapters.
7. Reconciliar analytics de partial conforme ADR-R59 antes de promover el case a paid normal.

## 15. Tests requeridos

### 15.1 Matriz de aceptación

| Caso | Resultado esperado |
| --- | --- |
| Consulta abierta + edición | Cambian entries/events; no Invoice posted ni Checkout primary anticipado |
| Consulta cerrada | Un Checkout primary, MR/Appointment consistentes |
| Consulta $0 real | completed/no_charge; sin Invoice/Payment/stock financiero |
| Transacción financiera total $0 | Documento fiscal solo si negocio/ley lo exige; no confundir con no_charge |
| Receta completa | Selection/coverage/fulfillment por cantidad exacta |
| Receta parcial | Aceptación parcial y remanente acumulado correcto |
| Receta rechazada | Declined; sin cargo ni stock; Prescription intacta |
| Receta suplementaria | Solo remanente elegible; cap acumulado |
| Attestation externa stale | Post bloqueado después de cambio de revisión/fingerprint |
| Producto clínico | Stock al uso, single-lot, no stock duplicado al post |
| Producto retail | Sin reserva; allocation/movement al post |
| POS normal | Checkout reanudable; abandono/expiry sin efectos si no fue post |
| POS Rx | Attestation/ACL/retención y coverage exactas |
| Pago completo | Invoice posted/paid + Payments exactos y `paid_at` |
| Split total | N Payments canónicos; suma exacta; un receipt |
| Pago parcial futuro | Rechazado sin efectos |
| Crédito | posted/unpaid, due/evidence/permiso, stock entregado |
| Void terminal | Solo cero Payments; dispositions; sin replacement |
| Refund | CreditNote/RefundPayment; Invoice permanece paid |
| Refund reversal sin restock | Counterevents exactos; analytics netos |
| Refund reversal con restock | Rechazado en v1; reconciliación manual |
| Concurrent edit | Una versión gana; la stale falla sin efectos |
| Concurrent pay | Un Invoice/ledger/stock; el segundo replay o conflicto estable |
| Readiness true y cambio previo a finalize | Revalidación bajo locks rechaza; cero efectos |
| Stock insuficiente | Rollback de Invoice/Payment/allocations/stock/receipt |
| Checkout stale version | 409; total autoritativo y versión actual |
| Cutover writer entre baseline y freeze | Mutation procesada antes de activar future |
| Cutover writer in-flight | Lock exclusivo espera y final watermark lo incluye |
| Cutover mutation pendiente | Activate rechazado |
| BillingCutoverControl ausente | Writer falla cerrado; cero efecto/receipt terminal exitoso |
| Nueva organización concurrente | Un Control con mode normativo antes del primer writer |
| Replacement goods_retained | No nuevo stock ni fulfillment; carried baseline intacto |
| Abandon replacement con valor retenido | Rechazado; case sigue abierto |
| no_charge replacement sin waiver | Rechazado |
| Waiver replacement autorizado | Outcome auditado y case resuelto; permiso/razón obligatorios |
| Fallo durante void/replacement | Invoice original permanece posted |
| Legacy partial 30 histórico + 70 nuevo | Métrica/caja exactamente según ADR-R59; nunca 70/100 ambiguos |
| Partial collectible stale assessment | Rechazado y reclasificado sin Payment |
| Overpaid return mixto | Eventos por método; liability 0; revenue/stock 0 |
| Return → reversal | Liability reabre y case/episode accionable también |
| Return → reversal → return | Eventos nuevos, ninguna duplicación, case termina resuelto |
| Misma raw key entre command kinds | Receipts e hijos distintos; sin colisión |
| Raw key sobre límite | 4xx estable antes de claim/efectos |
| Más líneas que line_index permitido | 4xx estable; cero Payment parcial |
| Tenant cruzado | 404/denegación sin filtrar existencia ni replay ajeno |
| Contract v1.1 | Payment/LiabilityReturn/Reversal/analytics pasan contract tests |

### 15.2 Pruebas de caracterización ejecutadas

Comando ejecutado el 2026-09-02:

~~~text
python manage.py test \
  apps.billing.tests.test_rx_attestation \
  apps.billing.tests.test_invoice_pdf \
  apps.billing.tests.test_payment_ledger \
  apps.billing.tests.test_refund \
  apps.billing.tests.test_prescription_dispense \
  apps.medical_records.tests.test_close \
  apps.analytics.tests.test_snapshot_v1 \
  apps.analytics.tests.test_late_arrival_observability \
  --keepdb --noinput
~~~

Resultado: **114 tests ejecutados, 1 skipped, 0 fallos; system check sin issues**. Estos tests prueban el comportamiento legacy actual; no prueban entidades futuras todavía inexistentes.

## 16. Impacto de implementación

| Área | Impacto / gate |
| --- | --- |
| Backend | Agregados/commands del ADR más contratos ADR-R60/R61/R62; writers solo por services |
| Frontend | Colas de preparación, cobranza, disputa y corrección; replacement no puede desaparecer como carrito POS ordinario |
| DB | Constraints de lineage/cases/Control/receipts; provisioning de Control y migrations expand-contract |
| Inventory | Implementación conforme D20; no cambio arquitectónico adicional |
| Analytics | **Bloqueado por ADR-R59**; cambio de métrica/versión y estrategia de snapshots |
| Permissions | Waiver/corrección, reversal y cutover separados; no reutilizar permisos amplios |
| Tests | Contract, PostgreSQL concurrency, migration rehearsal y las matrices anteriores |
| Docs | Publicar financial-event-model-contract 1.1, actualizar dashboard metrics/API/runbooks y marcar D1–D24 aprobadas |

Secuencia segura:

1. cerrar ADR-R59–ADR-R62 y aprobar D1–D24;
2. publicar contrato financiero 1.1 y contrato analytics asociado;
3. especificar constraints/API/errores y generar plan expand-contract;
4. implementar primero instrumentación/Control/receipts sin activar future;
5. construir modelo futuro y pruebas;
6. ensayar migración/cutover sobre copia de producción;
7. activar por organización con gates verdes.

## 17. Preguntas de negocio

Solo quedan dos preguntas que realmente requieren decisión de producto/finanzas:

1. Al liquidar hoy una factura legacy con pagos anteriores, ¿`revenue_paid` debe mostrar solo el dinero nuevo hoy —adoptando cash-basis por Payment y DD-008— o debe conservar la serie legacy que reconoce la Invoice completa en `paid_at`?
2. Tras anular una Invoice errónea con bienes retenidos/servicios prestados, ¿se exige continuidad **financiera** de la obligación o basta continuidad **operacional** mediante un case de corrección con owner/SLA y waiver explícito?

El lifecycle técnico del case tras reversal y el fail-closed de BillingCutoverControl no requieren decisión de negocio; deben resolverse por integridad.

## Conclusión

El ADR **sí resuelve la ambigüedad central de `draft/confirmed`** y separa correctamente preparación comercial, documento financiero y pago. También conserva, con bastante más precisión que versiones anteriores, consulta, receta, stock, refunds, crédito, auditoría y migración.

La respuesta a la segunda pregunta de aprobación sigue siendo por ahora **sí: dos desarrolladores todavía podrían construir comportamientos incompatibles**, concretamente en ADR-R59–ADR-R62. Por ello no se recomienda iniciar migraciones o endpoints. Cerrados esos cuatro contratos y publicada la versión 1.1, la arquitectura puede pasar a plan de implementación sin otro rediseño conceptual.
