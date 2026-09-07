# ADR p62 (propuesta): Checkout separado, posteo financiero y liquidación de Cobros

**Fecha:** 2026-08-30

**Última actualización:** 2026-09-06

**Estado:** Aceptado para lanzamiento greenfield — implementación base completada; contratos legacy/cutover ADR-R59, ADR-R61 y ADR-R62 no aplican mientras no existan datos operativos importados

**Inputs principales:**

- `docs/audits/2026-08-30-billing-status-flow-audit.md`
- `docs/audits/2026-08-30-dar-billing-checkout-review.md`
- `docs/audits/2026-08-31-dar-billing-checkout-rereview.md`
- `docs/audits/2026-08-31-dar-billing-checkout-third-review.md`
- `docs/audits/2026-09-01-dar-billing-checkout-fourth-review.md`
- `docs/audits/2026-09-02-dar-billing-checkout-fifth-review.md`

**Relacionados:**

- ADR p26: atestación regulatoria append-only para receta externa en venta directa
- ADR p27: Payment append-only, split de métodos e Invoice.status como proyección del ledger
- ADR p30: cierre garantiza factura, dispensación de receta y pago total exacto
- ADR p32: consumo clínico charge frente a included
- ADR p38: POS server-driven en dos pasos
- ADR p53: separar agregados por motivo de cambio
- `docs/financial-event-model-contract.md`: contrato frozen que D19 exige enmendar a v1.1

## 0. Propósito y autoridad de esta propuesta

Este documento es la segunda fase de diseño posterior a la auditoría. Responde primero las decisiones de negocio; después define el dominio y solo entonces propone estados y migración.

Este ADR fue aceptado como contrato del lanzamiento greenfield. La implementación conserva las decisiones de producto aquí descritas y esta ADR:

- supera la parte de ADR p30 que obliga a crear una Invoice draft al cerrar toda consulta;
- supera la decisión de ADR p38 de no crear una entidad de checkout separada;
- conserva de ADR p27 Payment append-only, idempotencia, split de métodos y paid como proyección del ledger;
- conserva de ADR p30 el pago total exacto y la receta como selección posterior;
- conserva de ADR p32 la separación entre consumo clínico y cargo.

La propuesta no intenta resolver fiscalidad mexicana, cuentas contables formales, reservas de inventario, multi-sucursal ni pagos parciales. Sí cierra los contratos técnicos necesarios para que esos temas no se resuelvan accidentalmente durante la implementación.

### 0.1 Resolución de las revisiones

Esta versión integra como decisiones normativas ADR-R28–ADR-R39. Se aceptan los problemas señalados, con los siguientes alcances:

| Hallazgo | Resolución incorporada |
| --- | --- |
| ADR-R28 | Precio clínico se congela al abrir el ciclo cobrable y gobierna sus incrementos; impuesto futuro se fija al primer ciclo cobrable. Ambos quedan antes de Checkout. |
| ADR-R29 | En v1 se prohíbe revertir una CreditNote que produjo restock. Los reversos permitidos recomputan capacidad reembolsable excluyendo notas totalmente revertidas. |
| ADR-R30 | Readiness se divide entre preparación estructural y disponibilidad de cada comando para el actor. |
| ADR-R31 | Partial/overpaid legacy se representa en una cuarentena persistente; no se fuerza dentro de `unpaid/paid`. |
| ADR-R32 | Se define `CommandReceipt`, su scope, hash, replay-before-guards y protocolo transaccional. |
| ADR-R33 | El único vocabulario persistido/API es `posted`; “Emitida” es únicamente el label de UI. |
| ADR-R34 | La decisión Rx persistida es `pending/accepted/declined`; full/partial se deriva contra el remanente elegible del Checkout y contra el cap original en una proyección acumulada distinta. |
| ADR-R35 | Void no reabre documentos: una corrección usa Checkout/Invoice de reemplazo con lineage de supersesión y política explícita de stock. |
| ADR-R36 | El orden global incluye Appointment y locks implícitos de `UPDATE`; `Appointment → MedicalRecord` es obligatorio. |
| ADR-R37 | Un cargo clínico disputado entra a un workflow persistente de disputa; nunca queda como `open` invisible ni se abandona para borrar exposición. |
| ADR-R38 | Legacy no inventa aceptación moderna: confirmed usa `legacy_confirmed/not_captured`; paid puede registrar `legacy_payment_implied`. |
| ADR-R39 | v1 mantiene consumo clínico de un único lote explícito; retail/Rx usa allocations multilote. |

La decisión de ADR-R29 es deliberadamente conservadora: no se implementa una salida de stock automática para “deshacer” un restock porque el sistema no puede demostrar que las unidades continúan físicamente disponibles ni cuál lote debe retirarse. Un flujo físico de corrección de ese caso requiere una ADR de Inventory posterior.

La tercera revisión ADR-R40–ADR-R50 se incorpora con estas decisiones:

| Hallazgo | Resolución normativa |
| --- | --- |
| ADR-R40 | Una fuente clínica tiene ciclos cobrables. El primer precio del ciclo gobierna todos sus incrementos; la cantidad cambia mediante eventos append-only. Close factura solo el ciclo activo y su cantidad neta. |
| ADR-R41 | La corrección con exposición continua usa exclusivamente `void_and_prepare_replacement`, un CommandReceipt y una transacción. Los endpoints secuenciales no representan ese caso. |
| ADR-R42 | Un MR abierto no recibe Checkout primario durante backfill: recibe `LegacyCheckoutSeed`. Close reconstruye clínica y crea exactamente un primario. Drafts appointment-only tienen mapping propio. |
| ADR-R43 | Partial se repara agregando Payment exacto; overpaid usa reclasificación a pasivo + `LegacyLiabilityReturn`, nunca CreditNote/RefundPayment sintético. Eventos previos son inmutables. |
| ADR-R44 | Cada modelo lockeable tiene rank propio; el orden es `(model_rank, pk)`. Un comando iniciado desde un hijo prelee y lockea primero sus padres. |
| ADR-R45 | Checkout abierto guarda intención solicitada; `StockAllocation` nace únicamente al post y siempre referencia StockMovement committed. |
| ADR-R46 | Cada acción separa `blockers` de `required_inputs`; un input que el propio comando captura no vuelve indisponible la acción. |
| ADR-R47 | `first_billable` es una política futura deliberada, no una descripción universal del legacy. Migración conserva tax_rate y writer provenance reales. |
| ADR-R48 | `enforced_under_terms` crea `CollectionCase`; `collection_status` es una proyección de ese caso y del settlement, no un flag suelto. |
| ADR-R49 | CommandReceipt usa claim PostgreSQL explícito y canonicalización versionada de payload validado. |
| ADR-R50 | Receipts, evidencia y disputas almacenan envelopes allowlisted, tienen permisos de lectura separados y clases de retención explícitas. |

La cuarta revisión ADR-R51–ADR-R58 se incorpora con estas decisiones:

| Hallazgo | Resolución normativa |
| --- | --- |
| ADR-R51 | `ExternalPrescriptionAttestation` deja de depender de Invoice draft: es evidencia regulatoria append-only del Checkout, ligada a una revisión/fingerprint exactos de las líneas Rx; post la revalida y cada InvoiceItem regulado referencia su cobertura. |
| ADR-R52 | El raw idempotency key identifica CommandReceipt, no eventos hijos. Payment y cualquier evento financiero hijo usan identidad canónica derivada de receipt + event kind + line index. Liability return se modela como documento más eventos monetarios por método y counterevents propios. |
| ADR-R53 | Stock, custodia física, dinero y fulfillment Rx son proyecciones independientes. StockAllocation nunca se vuelve “inefectiva”; eventos append-only determinan salida/retorno y contribución al cap sin contar dos veces replacements o reversos financieros. |
| ADR-R54 | El cutover usa control por organización, instrumentación previa de mutations, freeze DB-enforced, watermark final, catch-up/rebuild autoritativo y reconciliación antes de activar writers futuros. |
| ADR-R55 | `LegacySettlementCase.kind` solo describe matemática. `repairability` gobierna acciones; únicamente `collectible`, con evidencia objetiva de obligación válida, puede ejecutar `settle_legacy_partial`. |
| ADR-R56 | El PDF draft se sustituye por `Checkout Estimate`, documento no financiero versionado y marcado “ESTIMADO — NO ES FACTURA”. El PDF de Invoice queda reservado para documentos posted/voided y legacy archivado. |
| ADR-R57 | El rank gobierna la primera adquisición de lock sobre cada row existente. Una row ya poseída puede actualizarse después; un UPDATE sobre una row no lockeada sí cuenta como adquisición y debe respetar rank. |
| ADR-R58 | Repricing clínico es `reprice_clinical_charge`: comando explícito, versionado, idempotente, permissioned y atómico que cierra un ciclo y abre otro. |

La quinta revisión identifica ADR-R59–ADR-R62. ADR-R60 se cierra normativamente. Producto confirmó además que no existen clínicas ni datos financieros reales operando sobre el esquema legacy. En consecuencia, ADR-R59, ADR-R61 y ADR-R62 se clasifican **no aplicables al lanzamiento greenfield**, no como problemas resueltos por una migración ficticia:

| Hallazgo | Resolución normativa |
| --- | --- |
| ADR-R60 | Se elige **continuidad operacional controlada**. Todo Checkout `kind=replacement` nace con un baseline inmutable de valor ya prestado/retenido, owner y SLA; se proyecta `correction_pending`, no expira ni admite abandono/no_charge genéricos, y solo termina al postear una nueva Invoice o mediante un waiver explícito, autorizado y auditado. No se crea un agregado ReplacementCase separado. |
| ADR-R59 | **N/A greenfield.** No se liquidarán `partial` legacy ni se importarán pagos históricos durante este lanzamiento. `revenue_paid` futuro se deriva de Payments efectivos; si aparece un import legacy, deberá publicarse antes una decisión temporal específica. |
| ADR-R61 | **N/A greenfield.** No existen `LegacyLiabilityReturn` ni casos overpaid heredados. El modelo no crea esos agregados hasta que exista un alcance real de import/reconciliación. |
| ADR-R62 | **N/A greenfield.** No hay convivencia ni cutover entre writers legacy y future: las organizaciones nuevas nacen directamente bajo el flujo Checkout. Si se habilita importación o ejecución dual, `BillingCutoverControl` vuelve a ser gate obligatorio antes del primer writer. |

Esta exención es deliberadamente estrecha. La aparición de cualquier Invoice/Payment legacy importado, tenant activado con writers antiguos o proceso dual-write reactiva ADR-R59/R61/R62 y bloquea ese despliegue hasta materializar sus controles.

### 0.2 Estado de implementación greenfield (2026-09-04)

Quedaron materializados el agregado Checkout, sus líneas/selecciones/estimados, snapshots clínicos, receipts idempotentes, posting/pago autoritativo, Invoice `posted/paid/voided` con anchors nativos `posted_at/paid_at/voided_at`, evidencia de obligación, atestación Rx por revisión, allocations/dispositions/fulfillment, no-charge, abandono, disputa, cobranza disputada, void terminal, replacement atómico, ajuste/asignación/waiver de replacement, refund/reversal permitido, repricing clínico y cierre de consulta idempotente hacia Checkout. POS y Cobros consumen Checkout; los writers de producción ya no usan `draft`, `confirmed` ni `cancelled`.

También existen los comandos explícitos `create_prescription_supplement`, `attest_external_prescription` y `resolve_collection_case`. El post revalida el cap de receta bajo transacción y una cobranza ordinaria no crea falsamente un `CollectionCase`: ese caso nace solo al ejecutar `enforced_under_terms`. La API expone `preparation_readiness` y `actions` como proyecciones derivadas y versionadas; Cobros y POS las consumen para explicar y bloquear acciones, sin persistir un estado `ready` paralelo.

No se implementaron `LegacySettlementCase`, `LegacyLiabilityReturn`, `LegacyCheckoutSeed`, mutation-log ni `BillingCutoverControl`, porque requieren datos/writers legacy que producto declaró inexistentes. Esto es una exclusión de alcance verificable, no una implementación parcial silenciosa.

No se aceptan como solución las siguientes alternativas del espacio de diseño:

| Alternativa descartada | Justificación |
| --- | --- |
| Reconsultar precio/impuesto al cerrar | Reprecificaría hechos ya registrados y perdería el comportamiento económico que hoy conserva Invoice draft. |
| Retirar stock automáticamente al revertir un refund restockeado | Un contraevento monetario no prueba existencia, lote ni nueva entrega física. |
| Ampliar el estado normal a partial/overpaid | Legitimaría datos que los writers nuevos prohíben; la cuarentena los representa sin contaminar el lifecycle. |
| Usar `issued` además de `posted` | Crearía dos contratos de schema para el mismo hecho; `posted` ya tiene anchor y semántica definidos. |
| Tratar `confirmed` legacy como aceptación | El status no conserva parte, canal ni evidencia; se registra `not_captured`, no una aceptación inventada. |
| Habilitar consumo clínico multilote sin allocations clínicas | `MedicalRecordProduct` solo representa un lote; permitirlo perdería provenance necesaria para reversos. |
| Mantener un Checkout disputado en la cola ordinaria | Oculta una exposición real y carece de owner/SLA/resolución. |
| Conservar Invoice draft solo para atestación/PDF | Mantendría el acoplamiento que Checkout elimina; evidencia regulatoria y estimate tienen agregados/contratos propios. |
| Derivar Payment keys desde el header raw | Dos command kinds válidos pueden colisionar en el unique financiero por organización. |
| Tratar retorno, refund y fulfillment Rx como una misma reversa | Dinero, inventario, custodia y capacidad de prescripción cambian por hechos distintos. |
| Activar por feature flag después de una fotografía de backfill | Idempotencia no garantiza frescura; puede perder mutaciones ocurridas entre batch y cutover. |
| Cobrar cualquier partial con saldo matemático | Un saldo no prueba que la obligación original fuera válida o exigible. |
| Tratar un replacement como carrito POS ordinario | Después del void permitiría expirar, abandonar o eliminar valor ya entregado sin nueva Invoice ni waiver. |

## 1. Resumen de decisiones

| # | Pregunta | Decisión recomendada |
| --- | --- | --- |
| D1 | ¿Existe crédito? | Sí, pero limitado: una Invoice puede postearse unpaid y liquidarse después en un solo pago total. Es una excepción explícita, no el default. |
| D2 | ¿Cuándo ocurre el devengo? | En posted_at, cuando el checkout se vuelve obligación inmutable. No al cerrar MedicalRecord ni al preparar líneas. |
| D3 | ¿Qué hacemos con $0? | Se completa el Checkout como no_charge y no se crea Invoice ni Payment. |
| D4 | ¿Quién modifica qué? | VET posee hechos clínicos; recepción solo selección retail; caja registra pago; ADMIN autoriza crédito, descuentos excepcionales, void y refund. |
| D5 | ¿Qué significa rechazar receta? | El cliente decide no comprar ese ítem en este checkout. No cancela la prescripción clínica, no crea cargo y no mueve stock. Se persiste. |
| D6 | ¿Cuándo sale el medicamento? | Al postear/finalizar el checkout, que representa la entrega. En pago inmediato posteo y pago son atómicos. Seleccionar no reserva ni descuenta. |
| D7 | ¿Quién cobra? | ADMIN y personal con payment.create; ASSISTANT lo recibe por default operativo. VET no cobra por ser VET, solo si además recibe ese permiso. |
| D8 | ¿Pagos parciales? | No. Se permite split de métodos, pero la suma debe liquidar el saldo exacto en un solo evento. |
| D9 | ¿Sobrevive el carrito POS? | Sí: sobrevive refresh y reintentos durante una ventana operativa; tiene owner, version, expiry y abandono explícito. No es una deuda. |
| D10 | ¿auto_create_invoice_on_done? | Se depreca y elimina. Appointment.done no crea documentos financieros; MedicalRecord.close crea Checkout. |
| D11 | ¿Cuándo se congelan precio e impuesto? | Cada ciclo clínico congela el precio de su primera alta y lo conserva para incrementos; cantidad se deriva de eventos. Impuesto de consulta se fija al primer ciclo cobrable. POS/Rx versiona cualquier repricing. |
| D12 | ¿Qué ocurre con cargos clínicos disputados? | Pre-post usa CheckoutDispute; si se postea bajo términos, nace CollectionCase. Ninguno se abandona ni queda como flag sin owner/transiciones. |
| D13 | ¿Cómo se revierte un refund con restock? | No se permite en v1. RefundReversal solo aplica si la CreditNote no repuso inventario; lo demás exige reconciliación física separada. |
| D14 | ¿Cómo se garantiza idempotencia y concurrencia? | CommandReceipt durable con claim/canonicalización definidos, replay antes de guards y orden total `(model_rank, pk)`. |
| D15 | ¿Cómo sobreviven partial/overpaid legacy? | LegacySettlementCase conserva eventos originales: partial agrega Payment exacto; overpaid reclasifica pasivo y lo devuelve sin tocar revenue/stock. |
| D16 | ¿Cómo se reemite tras void? | Exposición continua usa `void_and_prepare_replacement` atómico; void standalone queda reservado para resultados terminales. |
| D17 | ¿Qué ocurre con un draft migrado mientras MR sigue abierto? | No nace Checkout primario. Se crea LegacyCheckoutSeed; close reconstruye clínica y crea/adopta una sola operación autoritativa. |
| D18 | ¿Dónde vive la atestación externa sin Invoice draft? | En un agregado regulatorio append-only ligado al Checkout y a una revisión exacta de su scope Rx; post crea cobertura durable hacia InvoiceItems. |
| D19 | ¿Cómo se identifican Payment y liability events hijos? | Por CommandReceipt + event kind + índice canónico, nunca por concatenación del header raw. Cada método es un evento financiero propio y corregible solo por counterevent. |
| D20 | ¿Qué cuenta como fulfillment Rx tras void/refund/replacement? | Una proyección de eventos de dispensación/custodia; stock y dinero no la alteran implícitamente. V1 no restaura cap por devolución y una redelivery probada es neutral. |
| D21 | ¿Cómo se evita perder cambios durante cutover? | Instrumentación de mutations, freeze por organización, watermark final, catch-up/rebuild y reconciliación bajo una única autoridad. |
| D22 | ¿Cuándo puede cobrarse un partial legacy? | Solo si `repairability=collectible` demuestra emisión/obligación, total, ledger, tax, stock y contexto coherentes. |
| D23 | ¿Qué reemplaza el PDF draft? | Un Checkout Estimate versionado, explícitamente no financiero; Invoice PDF existe únicamente después de post o para archivo legacy. |
| D24 | ¿Cómo se cambia un precio clínico capturado? | Solo mediante `reprice_clinical_charge`, con ACL, version, reason, receipt y cierre/apertura atómicos de ciclos. |
| D25 | ¿Qué protege la exposición después de void + replacement? | El replacement tiene baseline obligatorio, owner/SLA y proyección `correction_pending`; no puede abandonarse, expirar ni terminar no_charge. Solo termina en nueva Invoice o waiver explícito. |

## 2. Fase 1 — Decisiones de negocio

### D1. Crédito: sí, limitado y explícito

#### Decisión

El producto soportará una obligación postergada: un checkout listo puede convertirse en una Invoice posted/unpaid mediante la acción **Dejar pendiente**. Esa Invoice se paga después, completa, mediante un único evento de cobro, aunque el evento contenga varios métodos.

No se interpreta como crédito:

- un Checkout abierto;
- una consulta cerrada pendiente de resolver receta;
- un carrito POS;
- una Invoice legacy draft;
- un intento de pago fallido.

Solo existe crédito cuando un actor autorizado ejecuta post_unpaid y el sistema registra:

- posted_at;
- actor;
- owner/cliente;
- total final;
- razón o política de crédito;
- due_at obligatorio según la política v1 descrita abajo;
- items inmutables;
- movimientos de stock retail correspondientes a bienes entregados.

#### Default de producto

- **Cobrar ahora** es el camino normal.
- **Dejar pendiente** es excepcional y requiere invoice.post_unpaid.
- La capacidad organizacional `allow_post_unpaid` está deshabilitada por default.
- ADMIN recibe el permiso por default.
- ASSISTANT no lo recibe por default; puede incorporarse después mediante política organizacional.
- VET no lo recibe por su rol clínico.
- Requiere cliente identificado, razón controlada, `due_at` obligatorio posterior a `posted_at` y `ObligationEvidence` de D12.
- `credit_default_days` propone el vencimiento; v1 admite 1–365 días y el actor autorizado puede ajustarlo dentro de ese rango.
- V1 no calcula límite crediticio automático: cada operación se autoriza individualmente y muestra el outstanding actual del cliente al autorizador.

#### Por qué

El código actual ya mantiene revenue_accrual y outstanding sobre confirmed, por lo que existe intención de cuenta por cobrar. También existe el caso operativo de un cliente que se retira y vuelve. El error actual es que cualquier confirmación crea esa deuda sin declararlo.

#### Si producto decide “no existe crédito”

Se elimina post_unpaid, Invoice nace siempre paid en la transacción Cobrar y revenue_accrual coincide temporalmente con revenue_paid. Los confirmed actuales no podrían migrarse automáticamente a deuda válida: exigirían resolución manual. Ésta sería una simplificación coherente, pero contradice los consumidores actuales de outstanding.

### D2. Devengo: al postear la obligación

#### Decisión

El devengo ocurre en **posted_at**, cuando:

1. la preparación está lista y el comando está disponible para el actor;
2. el total quedó final;
3. las líneas se vuelven inmutables;
4. el cliente/obligado está identificado;
5. existe `ObligationEvidence` válida —aceptación/pago o términos previos—;
6. la entrega de retail se asienta;
7. nace una Invoice.

MedicalRecord.closed_at no devenga por sí solo. El cierre clínico afirma que la atención terminó; todavía puede faltar decidir qué receta se compra, calcular el total final o determinar que no hay cargo.

En Cobrar ahora:

~~~text
posted_at ─┐
           ├─ misma transacción y misma fecha de negocio
paid_at ───┘
~~~

Los timestamps siguen siendo distintos porque representan hechos distintos, aunque sean casi simultáneos.

En Dejar pendiente:

~~~text
posted_at ─────────────── paid_at
    devengo             caja posterior
~~~

#### Analytics

- revenue_accrual bruto se ancla en posted_at; el neto usa adjustments append-only por void y CreditNotes efectivas.
- revenue_paid se ancla en paid_at y se ajusta por CreditNotes efectivas/RefundReversals.
- Checkout open, abandoned y completed/no_charge no afectan revenue.
- El cierre clínico puede tener su propia métrica, pero no sustituye posteo.
- Un void posterior al snapshot requiere evento de ajuste; no se debe reescribir historia silenciosamente.

### D3. Consultas de $0: Checkout no_charge, sin Invoice

#### Decisión

Toda consulta cerrada deja un resultado financiero auditable, pero no necesariamente una Invoice.

Si al resolver todos los cargos y selecciones el total es cero:

~~~text
Checkout open → completed
completion_kind = no_charge
Invoice = inexistente
Payment = inexistente
~~~

Esto cubre:

- consulta sin servicios/productos cobrables;
- solo insumos included;
- receta totalmente rechazada sin otros cargos;
- cortesía o descuento autorizado que lleva el total a cero, si se permite.

No cubre `kind=replacement`: allí un total exigible de cero representa perdón/corrección de valor ya prestado o retenido y debe resolverse como `replacement_waived` conforme D25, nunca como no_charge genérico.

No se crea Payment de $0. No se usa paid para simular resolución. El Checkout conserva:

- MedicalRecord;
- quién resolvió;
- completed_at;
- reason_code: no_billable_items, included_only, prescription_declined, courtesy u otro catálogo controlado;
- total calculado de cero.

Se distinguen dos clases aunque ambas terminen sin Invoice en v1:

- `no_billable`: no hubo líneas cobrables, solo included o toda receta fue declinada;
- `zero_value_adjusted`: sí hubo valor económico, pero cortesía/descuento autorizado lo llevó a cero; conserva líneas, ajustes, permiso, razón y before/after.

Esta distinción evita tratar una cortesía como ausencia de operación y permite auditoría/analytics sin inventar un Payment de cero.

#### Excepción futura

Si fiscal/legal exige un comprobante de $0, debe ser una decisión separada. Podría emitirse un documento zero-settled sin Payment, pero no debe reintroducir una deuda ni bloquear la bandeja. No se incluye en esta fase.

### D4. Ownership: quién puede modificar qué

#### Decisión

El permiso nace del **origen de la línea**, no de que toda línea viva en una factura editable.

| Dato/acción | Owner de negocio | Editable hasta | Otros actores |
| --- | --- | --- | --- |
| Diagnóstico, servicios realizados | VET responsable | MedicalRecord.close | ADMIN puede corregir según política; recepción read-only |
| Producto consumido y cost_behavior | VET responsable | MedicalRecord.close | ADMIN según política; recepción read-only |
| Precio de ciclo clínico | Catálogo/política clínica | Se congela en la primera alta del ciclo; incrementos lo conservan | Corrección abre ciclo nuevo auditado; Checkout nunca lo edita |
| Selección de receta | Recepción/dispensador autorizado | Checkout post | VET prescribe, no decide compra por el cliente |
| Presentación/cantidad solicitada retail | Recepción/dispensador | Checkout post | Lotes los asigna finalize; sujeto a billing.rx_dispense |
| Producto/servicio POS | Operador del Checkout | Checkout post | Solo Checkout owner o permiso de takeover |
| Descuento | Actor con checkout.apply_discount | Checkout post | Requiere razón y audit before/after |
| Postear deuda | Actor con invoice.post_unpaid | Una vez | No es edición; es comando terminal del Checkout |
| Registrar pago | Actor con payment.create | Invoice unpaid | Append-only |
| Void terminal | Actor con invoice.void_terminal | Invoice posted sin Payment | Razón terminal obligatoria |
| Void + replacement | Actor con invoice.replace | Una transacción | Dispositions + lineage obligatorios |
| Ajustar exposición de replacement | Actor con invoice.replace_adjust | Antes del post/waiver | Conserva baseline y exige razón/evidencia; no puede resolverlo a cero por sí solo |
| Waiver de replacement | Actor con invoice.replace_waive | Una vez, con Checkout replacement open | Resultado terminal excepcional, razón/evidencia y audit append-only |
| Refund | Actor con refund.create | Invoice paid | CreditNote + RefundPayment |
| Resolver disputa/cobranza | Actor con checkout/collection.resolve | Mientras case open | Owner/SLA/evidence; pay puede resolver paid |
| Reparar partial/overpaid legacy | legacy_settlement.collect / legacy_liability.return | Case open | ADMIN por default; eventos append-only |

Reglas duras:

- una línea clinical_* no se edita ni borra desde Checkout;
- una línea de baseline de replacement no se borra, disminuye ni oculta mediante comandos genéricos; una corrección económica conserva su lineage y un perdón total usa waiver;
- recepción corrige selección retail, no reescribe hechos clínicos;
- source, source_object y origin del Checkout son inmutables;
- invoice_type/origin nunca se cambia por PATCH;
- una corrección clínica después del cierre requiere un workflow explícito de corrección/reapertura, fuera de esta ADR;
- toda mutación monetaria registra actor, reason y before/after.

#### Roles por default

| Acción | ADMIN | VET | ASSISTANT |
| --- | --- | --- | --- |
| Editar hechos clínicos propios | Sí | Sí, si asignado | No |
| Ajustar retail/receta | Sí | Solo con permiso operativo | Sí |
| Emitir Estimate | Sí | Sí si owner/consulta asignada | Sí si owner |
| Cobrar | Sí | No por default | Sí |
| Dejar pendiente | Sí | No | No por default |
| Aplicar descuento | Sí | No | No por default |
| Reprice de cargo clínico | Sí | Solo con permiso explícito | No |
| Atestar receta externa | Sí | Sí con `billing.rx_dispense` | No |
| Abrir disputa | Sí | No por default | Sí |
| Resolver disputa/collection | Sí | No | No |
| Void terminal/replacement/refund | Sí | No | No |
| Ajustar/condonar replacement | Solo con permisos separados | No | No |
| Reparar settlement/liability legacy | Sí | No | No |
| Clasificar cobrabilidad legacy | Sí | No | No |
| Ver evidence/receipts administrativos | Sí | Solo evidencia Rx con permiso | No |

Los permisos deben poder acumularse: un veterinario de clínica pequeña puede también ser cajero, pero lo será porque tiene payment.create, no porque el rol VET implique caja.

### D5. Rechazo de receta: decisión comercial, no clínica

#### Decisión

Cada PrescriptionItem sugerido en un Checkout debe resolverse explícitamente antes de que el Checkout esté listo.

Decisiones persistidas:

| Decisión | Significado | InvoiceItem | Stock |
| --- | --- | --- | --- |
| pending | Cliente aún no decidió | No | No |
| accepted | Solicita una cantidad positiva elegible | Sí, como CheckoutItem solicitada | Al postear; entonces nacen allocations |
| declined | No compra ese producto en esta operación | No | No |

La selección inicia en pending, nunca preseleccionada. accepted requiere una o más CheckoutItems solicitadas con presentación y cantidad válidas; todavía no crea StockAllocation. declined puede registrar reason_code opcional: price, already_has, external_purchase, not_now, other.

`accepted_full` y `accepted_partial` no se almacenan como segunda fuente de verdad. Se exponen dos proyecciones distintas:

- `checkout_request_scope`: compara unidades solicitadas en este Checkout contra `eligible_remaining_at_open`, congelado al abrirlo bajo lock;
- `prescription_fulfillment`: suma `quantity_delta` de PrescriptionFulfillmentEvents de D20 contra la cantidad original prescrita; una allocation prueba lote/salida, pero no decide por sí sola la contribución posterior.

En un Checkout suplementario, request “full” significa que se solicitó todo el remanente elegible, no que ya fue surtido. Un finalize revalida bajo lock el cap y solo después del commit los FulfillmentEvents cambian `prescription_fulfillment`.

Rechazar:

- no invalida Prescription;
- no modifica PrescriptionItem;
- no dice que el tratamiento clínico fue rechazado;
- no impide una dispensación posterior si receta, vigencia y caps lo permiten;
- resuelve únicamente la oferta de compra dentro de ese Checkout.

Una compra posterior debe crear otra dispensación/Checkout vinculada al PrescriptionItem y respetar la cantidad previamente surtida. No se borra la decisión histórica.

### D6. Salida física del medicamento: al postear/finalizar

#### Decisión

Seleccionar un medicamento no descuenta ni reserva stock. El stock retail sale cuando el checkout se finaliza y el sistema representa la entrega física:

- Cobrar ahora: posteo, stock y Payment ocurren atómicamente;
- Dejar pendiente: posteo y stock ocurren sin Payment porque el producto se entrega a crédito;
- si el producto no se entrega todavía, no se debe postear: el Checkout permanece open.

~~~text
pending/selected ── no stock
Checkout post ───── stock out
Invoice void ────── disposition explícita; nunca stock return implícito
Invoice refund ──── restock o discard por línea
~~~

El sistema revalida stock y lote bajo lock al finalizar. `actions.pay/post_unpaid` puede informar disponibilidad, pero no garantiza que no haya race. Reservas de inventario quedan fuera de esta fase.

El consumo clínico no cambia: MedicalRecordProduct mueve stock cuando el insumo se usa, independientemente de charge/included. Nunca vuelve a mover stock al postear.

### D7. Quién puede cobrar

#### Decisión

Cobrar es crear eventos Payment y operar caja. Requiere:

- payment.create;
- CashSession válida cuando la organización lo exige;
- `actions.pay.allowed` para Checkout o Invoice posted/unpaid cobrable;
- idempotency key;
- pago completo exacto.

Asignación default:

- ADMIN: sí;
- ASSISTANT: sí, porque representa recepción/caja en el producto actual;
- VET: no por default; puede recibir el permiso explícitamente.

La UI debe consultar capacidad y no mostrar CTAs solo por status. El backend conserva la autoridad.

La misma persona puede preparar y cobrar. No se exige segregación de dos usuarios para clínicas pequeñas; sí se distinguen las acciones y audit logs.

### D8. Pagos parciales: no

#### Decisión

Se mantiene ADR p30:

- una Invoice unpaid se liquida en un solo comando;
- payment_lines puede contener efectivo + tarjeta + transferencia;
- la suma aplicada debe ser exactamente remaining_balance;
- sobrepago en efectivo solo calcula cambio y persiste el total;
- amount de cada Payment es mayor a cero;
- un intento menor al saldo falla completo, sin Payment parcial.

Por tanto payment_status solo necesita unpaid y paid en esta fase. El modelo Payment sigue siendo uno-a-muchos porque split, idempotencia, caja y refunds lo justifican.

Habilitar partial exigiría una ADR nueva para vencimientos, cobranza, aplicación de refunds, write-offs y reporting. No se deja código/UI que sugiera soporte parcial.

### D9. Carrito POS persistente y reanudable

#### Decisión

El carrito POS será un Checkout origin=direct_sale persistente en servidor desde su primera línea o desde una acción explícita de iniciar venta.

Debe:

- sobrevivir refresh y fallo de red;
- conservar owner y organization;
- tener version para evitar cobrar una versión vieja;
- reanudar el intento con la misma idempotency key cuando corresponda;
- admitir takeover solo con permiso;
- tener expires_at o política de antigüedad;
- permitir abandon con reason;
- no aparecer como revenue, AR ni Invoice.

No se exige que sobreviva indefinidamente ni que sea compartido entre terminales. La ventana exacta de expiry es configuración operativa posterior. Al expirar:

~~~text
Checkout open → abandoned
reason = expired
sin Invoice
sin stock
~~~

Esto supera el trade-off de ADR p38 que aceptó drafts/cancelled de Invoice como protocolo técnico.

Esta política aplica únicamente al Checkout POS ordinario. `origin=direct_sale` no concede abandono por sí solo: si `kind=replacement`, D25 prevalece, `expires_at=NULL` y el objeto permanece correction_pending/overdue hasta Invoice o waiver.

### D10. auto_create_invoice_on_done: deprecar y eliminar

#### Decisión

Appointment no será writer de Invoice ni Checkout.

- MedicalRecord.close crea el Checkout consultation y representa el handoff real.
- POS crea Checkout direct_sale explícitamente.
- Appointment.done sin MedicalRecord no crea obligación.
- Un no-show fee o cargo administrativo futuro debe ser un caso de uso explícito, no efecto lateral del status done.

Plan conceptual:

1. dejar de exponer el toggle para nuevas organizaciones;
2. medir organizaciones que lo tienen activo y caminos done sin close;
3. migrar esos casos al flujo explícito que corresponda;
4. ignorar el toggle en nuevos writers;
5. retirar campo, signal y documentación en una migración posterior.

### D11. Precio e impuesto: snapshots en el momento económico efectivo

#### Decisión

Eliminar `Invoice draft` no puede cambiar silenciosamente el precio que hoy conserva al incrementar una fuente única. La unidad económica autoritativa será `ClinicalChargeEntry`; `ClinicalChargeSnapshot` será la proyección inmutable que close copia desde esa entrada y su historial de cantidad.

#### Ciclo cobrable y precio

Una misma `MedicalRecordService` o `MedicalRecordProduct` puede tener varios ciclos históricos, pero una constraint parcial permite **como máximo un `ClinicalChargeEntry` activo por fuente**. Cada entrada contiene:

- organization, MedicalRecord y FK explícita exclusiva a la fuente;
- `cycle_number` monotónico por fuente;
- descripción, `unit_price`, moneda, descuento/regla y provenance;
- `price_effective_at`, actor y catálogo/lista usados;
- lifecycle `active/closed`, `closed_at` y razón.

La identidad de fuente/ciclo y sus campos económicos (`unit_price`, moneda, descuento, regla y provenance) son inmutables después del alta. Cerrar el ciclo solo completa su lifecycle; cambiar el hecho económico exige el cierre + nuevo ciclo descritos abajo y nunca un `UPDATE` de precio.

Al pasar una fuente a cobrable se crea el ciclo con el precio vigente. Ese primer precio gobierna todas las unidades agregadas durante el ciclo, aunque el catálogo cambie después:

~~~text
10:00  qty +1, precio capturado $100
11:00  catálogo cambia a $120
12:00  qty +1 en la misma fuente/ciclo
close  2 × $100 = $200
~~~

No se mezcla $100/$120 dentro de la misma fuente ni se revaloriza todo a $120. Una corrección autorizada antes de close existe únicamente como `reprice_clinical_charge` de D24: cierra el ciclo anterior llevándolo a cantidad neta cero y abre otro con la cantidad completa, precio nuevo, actor y razón. Nunca es efecto del catálogo, PATCH de `unit_price` ni permiso implícito de edición clínica.

#### Cantidad, decremento y eliminación

La cantidad no se sobrescribe dentro de la entrada. `ClinicalChargeQuantityEvent` es append-only y guarda entry, `delta` positivo/negativo, cantidad resultante, unidad, actor, razón, timestamp y `mutation_key`. UNIQUE `(entry, mutation_key)` vuelve idempotente cada administración. Un lock sobre fuente y entry serializa incrementos concurrentes.

El writer actualiza en la misma transacción la cantidad clínica proyectada de MedicalRecordService/Product y el QuantityEvent cobrable; close exige que ambas representaciones reconcilien conforme a cost_behavior. Una fuente que ya tiene entry usa FK PROTECT y eliminación lógica: no se hard-deletea una row necesaria para provenance.

QuantityEvent no es StockMovement. Si cambió consumo físico, el servicio clínico registra/revierte inventario con su propia causa en la misma transacción; cambiar únicamente `cost_behavior` nunca mueve stock.

- incremento: agrega delta y conserva `unit_price` del ciclo;
- decremento: agrega delta negativo; el neto nunca puede ser menor que cero;
- eliminar o cambiar `charge → included`: lleva el neto a cero, cierra el ciclo y conserva la fuente inactiva/auditada;
- volver de `included → charge`: abre un ciclo nuevo con el precio vigente y un baseline igual a la cantidad clínica actual;
- close copia exactamente cada ciclo activo con cantidad neta positiva; ciclos cerrados/superseded no se facturan.

Después de MedicalRecord.close no se admiten nuevos eventos sobre esas fuentes; una corrección clínica usa el workflow posterior definido fuera de esta ADR.

#### Impuesto

`MedicalRecordBillingContext` captura una sola vez `tax_rate`, regla y `tax_effective_at` cuando nace el **primer ciclo clínico cobrable**. Aunque ese ciclo se elimine después, el contexto permanece como provenance y gobierna cualquier ciclo posterior de la consulta. Si nunca existió un ciclo cobrable, no se crea contexto tributario solo para producir un documento de cero.

`first_billable` es una **política futura deliberada**, no una afirmación de equivalencia con todos los writers actuales. Legacy Invoice pudo nacer por primer cargo, close, un producto included o `Appointment.done`, y la señal incluso pudo usar otra inicialización tributaria. La migración conserva el `tax_rate`, timestamp y writer provenance reales; solo etiqueta `first_billable` cuando la evidencia lo demuestra.

Close crea `ClinicalChargeSnapshot` desde entry + suma de eventos + BillingContext bajo locks. El snapshot guarda organization/MR, entry/cycle, source version, descripción, cantidad neta, unit_price/discount/currency, BillingContext/tax provenance y `snapshotted_at`; UNIQUE entry impide copiar el mismo ciclo dos veces. CheckoutItem referencia ese snapshot. Checkout e Invoice nunca reconsultan catálogo y nunca copian ciclos cerrados con neto cero.

En `direct_sale` y `prescription_retail`, el snapshot de línea nace al agregar o cambiar la selección en Checkout. Un Checkout `direct_sale` o `prescription_supplement` captura su tasa de impuesto al agregar la primera línea con precio y la mantiene estable. El Checkout primario de consulta hereda `MedicalRecordBillingContext`. Si la política permite repricing o refrescar impuesto mientras sigue `open`, debe ser un comando explícito que crea una nueva versión, registra before/after e invalida cualquier aceptación previa. La Invoice siempre coincide con la versión y total aceptados.

No se introduce fiscalidad por línea en v1: el modelo conserva la tasa de impuesto a nivel de operación que existe hoy. Una futura mezcla de tratamientos fiscales requiere otra decisión de dominio.

### D12. Aceptación y cargos clínicos disputados

#### Evidencia de obligación

Preparar un Checkout, autorizar crédito y aceptar el importe son hechos distintos. Todo writer nuevo de Invoice debe registrar un `ObligationEvidence` inmutable con:

- `basis`: `payment_authorization`, `customer_acknowledgement` o `preauthorized_terms`;
- `checkout_version` y `accepted_total`;
- parte que acepta, actor interno que captura y timestamp;
- canal (`in_person`, `phone`, `written`, `digital` o el catálogo aprobado);
- referencia/evidencia cuando la política la exige;
- autorización de crédito separada, si aplica.

En pago inmediato, la entrega/tender del pago por el importe y versión presentados constituye `payment_authorization`; no hay CTA financiero intermedio “Confirmar”. En `post_unpaid`, la autorización interna de crédito **no** basta: se exige `customer_acknowledgement` o términos previamente aceptados y recuperables.

#### Disputa

Si el servicio ya fue prestado pero el cliente niega el importe o la obligación, no se permite `abandon` ni se deja el caso en la cola ordinaria. Se crea un `CheckoutDispute` persistente; puede haber historial, pero una constraint parcial permite como máximo uno abierto por Checkout:

- Checkout, líneas e importe disputados;
- declaración/motivo y evidencia disponible;
- `opened_at/by`, `review_due_at` y owner de resolución;
- estado `open/resolved` y resultado inmutable auditado;
- relación con la Invoice, si la obligación se postea por términos previos.

Mientras la disputa está abierta, el Checkout conserva lifecycle `open` pero queda bajo `operational_hold=dispute`; `pay`, `post_unpaid`, `no_charge` y `abandon` se bloquean. El caso sale de “Por preparar” y aparece en una bandeja **Disputas**, con métrica `disputed_clinical_exposure`. No se reconoce como revenue ni AR mientras no exista Invoice.

`resolve_checkout_dispute`, restringido a `checkout.resolve_dispute`, admite tres resultados:

1. `accepted`: registra evidencia y devuelve el Checkout a sus acciones normales;
2. `adjusted_or_waived`: agrega un ajuste autorizado con razón; si el total queda cero, completa `no_charge` con razón `disputed_waived`;
3. `enforced_under_terms`: solo con `preauthorized_terms` verificables; postea Invoice unpaid y crea `CollectionCase.open` en la misma transacción.

La salida `no_charge/disputed_waived` solo aplica a Checkout no-replacement. Si la disputa pertenece a un replacement, resolver el hold no resuelve el baseline: debe continuar hacia nueva Invoice o ejecutar `waive_replacement_exposure` conforme D25.

Sin evidencia de aceptación ni términos previos no se fabrica una deuda. El caso permanece visible, asignado y sujeto a SLA hasta resolución; no se convierte en abandono técnico.

#### Disputa después del post

`collection_status` no es un flag editable. Se deriva así:

~~~text
Invoice posted/unpaid + CollectionCase.open  → disputed
Invoice posted/unpaid + sin case open        → collectible
Invoice paid o voided                        → closed
~~~

`CollectionCase` conserva Invoice, monto/líneas disputados, owner, SLA, evidencia estructurada y eventos append-only. Tiene lifecycle:

~~~text
open
 ├─ customer_withdrew ───────────────▶ resolved/collectible
 ├─ paid ────────────────────────────▶ resolved/paid
 ├─ adjusted_with_replacement ───────▶ resolved/replaced
 └─ authorized_waiver ───────────────▶ resolved/waived
~~~

- `customer_withdrew` cierra el case y deja la Invoice unpaid/collectible;
- `pay_invoice` sobre una Invoice disputada exige `collection_resolution=paid` y cierra case + Payment en la misma transacción;
- ajustar una obligación que continúa usa `void_and_prepare_replacement` y resuelve como replaced;
- condonar terminalmente usa void standalone con permiso/razón y resuelve como waived;
- no existe PATCH directo de `collection_status` ni un estado disputado huérfano sin owner.

### D13. RefundReversal y stock

#### Decisión v1

`RefundReversal` revierte el flujo monetario de una CreditNote, pero no demuestra una nueva salida física. Por tanto:

- `reverse_credit_note` es all-or-nothing para todos los `RefundPayment` efectivos de esa CreditNote;
- fuera de un replay idempotente, si alguno de esos pagos ya tiene reversal y otro no, la operación se rechaza como ledger inconsistente;
- solo se permite si ninguna línea de la CreditNote produjo `restock` ni otro incremento de inventario;
- si hubo restock, responde conflicto `stock_reversal_requires_manual_reconciliation` sin nuevos eventos;
- una línea de origen clínico nunca es elegible para restock automático;
- el reverso permitido crea los `RefundReversal` y adjustments de analytics, sin StockMovement.

`CreditNote.effectiveness` es una proyección derivada: `fully_reversed` si existe al menos un `RefundPayment` y cada pago de la nota tiene exactamente un `RefundReversal`; en otro caso es `effective`. Los cálculos de importe/cantidad todavía reembolsables consideran únicamente `CreditNoteItem` de notas efectivas. Así, revertir un refund sin stock restaura capacidad de refund sin editar ni borrar el ledger.

Los casos legacy `CreditNote + restock + RefundReversal` se censan y quedan en reconciliación de inventario; el backfill no intenta sacar stock. Soportar ese reverso en el futuro exige un comando físico enlazado a allocations/lotes exactos y una ADR de Inventory.

### D14. CommandReceipt y orden global de locks

#### Scope idempotente

Todo comando terminal o con efectos externos (`close_medical_record`, `create_prescription_supplement`, `attest_external_prescription`, `reprice_clinical_charge`, `issue_checkout_estimate`, `pay`, `post_unpaid`, `no_charge`, `abandon`, `void`, `void_and_prepare_replacement`, `adjust_replacement_exposure`, `assign_replacement_owner`, `waive_replacement_exposure`, `refund`, `reverse_credit_note`, clasificación/reparaciones legacy, liability reversal, fases prepare/reconcile/activate de cutover y expiry/takeover terminal) usa `CommandReceipt` durable con:

- unique `(organization_id, command_kind, idempotency_key)`;
- `receipt_uuid` inmutable y único, usado para identidades financieras hijas D19 sin exponer el raw key;
- `aggregate_type` y `aggregate_public_id`;
- `canonical_schema_version` y SHA-256 del comando, agregado, actor, `expected_version` y payload canónico;
- actor, status, `response_status`, envelope allowlisted y referencias resultantes;
- `retention_class`, timestamps de creación/finalización y causal command.

La key tiene scope por tenant y comando, no por agregado. Reutilizar la misma key para otro agregado del mismo comando es conflicto; nunca devuelve el resultado de otro Checkout. El replay exige además el mismo `initiated_by`; otro actor no recibe el resultado aunque tenga permiso general. Reutilizarla con otro target, actor o payload/hash devuelve `409 idempotency_key_reused`. Comandos distintos pueden usar la misma cadena sin colisionar porque `command_kind` forma parte del scope.

#### Canonicalización

El hash no usa JSON crudo. Cada `command_kind` registra un schema canónico versionado. Para v1:

- primero valida tipos y materializa defaults del serializer;
- Decimal monetario se expresa en minor units enteras según moneda; cantidades clínicas usan string decimal normalizado;
- UUID se normaliza lowercase y timestamps a UTC ISO-8601;
- object keys se ordenan; `null` y campo omitido son equivalentes solo si el schema declara el mismo default;
- arrays conservan orden salvo colecciones declaradas como multiset;
- `payment_lines` se normaliza y ordena establemente por método, minor units y referencia; duplicados se conservan;
- dispositions/selecciones identificadas se ordenan por public_id;
- cualquier cambio incompatible crea `canonical_schema_version=2`; un replay se canonicaliza con la versión guardada en su receipt.

#### Claim seguro y orden de evaluación

1. autenticar actor, resolver tenant, permiso y visibilidad del target;
2. abrir transacción y adquirir `BillingCutoverControl` como primera coordination row: compartido para negocio/reconcile, exclusivo para prepare/activate;
3. buscar el scope para conocer la versión canónica guardada, o usar la versión vigente si es nuevo;
4. validar/canonicalizar y calcular hash;
5. si existe receipt, lockearlo y comparar actor, target, versión y hash; si está completo, devolver **antes de guards de cutover/lifecycle/version** su envelope persistido;
6. si no existe receipt y el modo de cutover no autoriza un comando nuevo de esa familia, responder conflicto sin insertar receipt;
7. si está autorizado, ejecutar `INSERT ... ON CONFLICT DO NOTHING RETURNING id`; ante conflicto lockear/revalidar el receipt ganador como en el paso 5;
8. adquirir por primera vez los recursos de dominio restantes según el orden total;
9. releer agregado/dependencias, comprobar `expected_version` y revalidar invariantes;
10. escribir efectos, eventos financieros con identidad D19, LegacyBillingMutation cuando aplique y receipt completo en la misma transacción;
11. commit; cualquier fallo revierte también el receipt y no deja `in_progress` visible.

La unique constraint hace que un insert concurrente espere el commit/rollback del ganador. No se usa un `get_or_create` no especificado ni se compromete un receipt `in_progress` antes de sus efectos. Un receipt legacy huérfano se clasifica para reparación y nunca se trata como éxito.

Dos requests concurrentes con la misma key se serializan por la unicidad y el lock del receipt; el segundo relee el resultado después del commit. Dos keys distintas contra el mismo agregado compiten bajo el lock del agregado: una puede finalizar y la otra recibe `409 state_conflict` sin efectos. Un timeout posterior al commit se recupera por replay exacto.

#### Orden total de recursos

El orden gobierna la **primera adquisición** de un lock sobre cada row existente, sea explícita o implícita por `UPDATE`: `(model_rank, primary_key)`. Una escritura posterior sobre una row cuyo lock ya posee la transacción no es una adquisición nueva y está permitida; por eso CommandReceipt puede completarse al final. Un UPDATE de una row todavía no poseída sí adquiere lock y debe respetar rank. No existen grupos con `/`; cada modelo/coordination row lockeable tiene rank único:

| Rank | Modelo |
| ---: | --- |
| 005 | BillingCutoverControl |
| 010 | CommandReceipt |
| 015 | BillingCutoverRun |
| 020 | CashSession |
| 030 | Appointment |
| 040 | MedicalRecord |
| 050 | MedicalRecordService |
| 060 | MedicalRecordProduct |
| 070 | ClinicalChargeEntry |
| 080 | Prescription |
| 090 | PrescriptionItem |
| 100 | PrescriptionRevision |
| 110 | PrescriptionRevisionItem |
| 120 | LegacyCheckoutSeed |
| 130 | Checkout |
| 135 | CheckoutItem |
| 137 | ExternalPrescriptionAttestation |
| 139 | ReplacementWaiver |
| 140 | CheckoutDispute |
| 150 | Invoice |
| 160 | CollectionCase |
| 170 | LegacySettlementCase |
| 180 | CreditNote |
| 190 | Payment |
| 200 | RefundPayment |
| 201 | LegacyLiabilityReturn |
| 202 | LegacyLiabilityReturnPayment |
| 203 | LegacyLiabilityReturnReversal |
| 210 | Product |
| 220 | Presentation |
| 230 | StockLot |
| 250 | InvoiceItem |
| 260 | CreditNoteItem |
| 270 | StockAllocation |
| 280 | StockMovement |

Quantity/audit/fulfillment/disposition/mutation/assessment events son inserts append-only después de locks y no se lockean para decidir estado. Si un comando necesita lockear una row existente de uno de esos modelos, primero debe asignarle un rank por ADR; no puede esconder la adquisición dentro de un helper.

El orden es normativo aunque obligue a refactorizar helpers legacy. Dentro de cada modelo se adquieren PKs ascendentes. Ninguna función puede **adquirir por primera vez** una row existente de rank menor después de una mayor; sí puede actualizar una row menor ya poseída. Un comando recibido desde CreditNote prelee sin lock su Invoice inmutable y luego lockea Invoice(150) → CreditNote(180); nunca al revés. Un liability reversal prelee su case/Invoice y adquiere Invoice(150) → LegacySettlementCase(170) → LegacyLiabilityReturn(201) → líneas(202). El registry identifica por comando todas las rows de coordinación y dominio que pueden adquirirse, incluidas las de helpers.

Insertar un hijo nuevo después de lockear su padre no es adquisición inversa de una row preexistente, siempre que el ID nuevo no sea visible, no se adquiera después otra row existente de rank menor y la transacción conserve el parent lock. Esto permite que `void_and_prepare_replacement` lockee Invoice y cree su nuevo Checkout sin abrir una carrera; cualquier replacement ya existente se detecta bajo Invoice/unique constraint. Actualizar al final BillingCutoverControl o CommandReceipt solo se permite si esa misma row fue adquirida al inicio; una row distinta del mismo modelo sigue su PK/rank normal.

`close_medical_record` debe preleer el Appointment relacionado sin lock, lockear primero Appointment y luego MedicalRecord, y revalidar la relación. `assign_patient` conserva el mismo orden Appointment → MedicalRecord. La creencia de que un `UPDATE` directo “no cuenta” es incorrecta: el `UPDATE Appointment` de close y el `UPDATE MedicalRecord` de assign adquieren row locks.

Los conflictos de serialización/deadlock SQLSTATE `40001/40P01` pueden reintentarse como máximo dos veces en el límite de comando, siempre con la misma idempotency key. El retry es resiliencia, no sustituto del orden total. Se requieren tests PostgreSQL con barreras para close-vs-assign/status, refund-vs-reverse, replacement-vs-pay/void, pay-vs-expiry/takeover y operaciones de stock.

#### Minimización, lectura y retención

El `response_envelope` de un comando contiene únicamente command kind, public IDs resultantes, estado, versión, totales monetarios necesarios y result code. La respuesta HTTP del comando usa ese mismo envelope para que replay sea exacto sin guardar DTOs con paciente, cliente, notas, tokens de tarjeta o secretos.

`ObligationEvidence`, CheckoutDispute y CollectionCase guardan enums, actor, timestamps, versión/total, reason codes, nota UTF-8 de máximo 1,000 caracteres sin controles y referencias opacas/hash de evidencia; nunca blobs, firmas, datos de tarjeta ni documentos dentro de JSON. Adjuntos futuros pertenecen a un storage seguro separado con ACL/retención propia.

`ExternalPrescriptionAttestation` es la excepción regulatoria tipada de D18: prescriber_name/folio/notes viven en columnas sanitizadas con los límites de ADR p26, nunca dentro de CommandReceipt/CheckoutEvent ni copiados a Invoice. Los DTOs ordinarios exponen solo estado de cobertura; el detalle PII usa permiso y audit separados.

Permisos de lectura:

- replay ordinario: mismo actor y permiso actual sobre el comando/target;
- `command_receipt.view`: ADMIN/auditor tenant-scoped;
- `billing_evidence.view`: ADMIN/auditor y responsables explícitos de cobranza;
- `billing_dispute.view/manage`: owner asignado, ADMIN/auditor según acción;
- `billing.rx_attestation.view`: ADMIN, VET autorizado y auditor tenant-scoped; recepción/caja sin permiso no ve PII;
- toda lectura administrativa deja audit y nunca cruza organization.

Receipts/evidencias financieras usan `retention_class=financial` y viven al menos tanto como el documento referenciado. Atestación externa usa `regulated_rx` y el plazo D18. Receipts puramente operativos conservan envelope completo 24 meses; después mantienen tombstone de scope/hash/result refs que impide reutilizar la key y devuelve `410 idempotency_result_expired` sin ejecutar efectos. V1 no hace hard-delete de disputas/evidencias; una política posterior solo puede anonimizar texto/actor conforme al contrato de retención sin borrar hechos financieros.

### D15. Settlement legacy parcial o sobrepagado

Los writers nuevos conservan `unpaid/paid` y pago exacto. Las filas existentes que no cumplen esa máquina se representan mediante `LegacySettlementCase`, no mediante un tercer estado normal de Invoice.

Campos mínimos:

- organization y referencia durable a Invoice legacy;
- `kind=partial|overpaid|other`;
- `repairability=unassessed|collectible|returnable|external_resolution_only|quarantined`, independiente de kind;
- total, suma de Payments, balance o exceso y snapshot de IDs del ledger;
- estado `open/resolved`, owner, resolución, actor y timestamps;
- `migration_run_id`, última evaluación/evidence hash y notas de reconciliación.

Reglas:

- “read-only” significa que Invoice, Payments y eventos legacy existentes no se editan ni borran; comandos de reparación solo agregan eventos nuevos;
- el caso no se expone en endpoints normales que aceptan `pay_invoice` o `refund_invoice` futuros;
- `partial` aparece en `legacy_receivables` por el saldo restante, separado de AR normal; solo collectible entra al sub-bucket exigible;
- `overpaid` aparece en `legacy_customer_liability`, nunca como revenue;
- una consola/API `legacy-settlements` permite consultar y resolver con permisos separados.

#### Reparar partial

`settle_legacy_partial` exige `repairability=collectible` vigente conforme D22, `legacy_settlement.collect`, `payment.create`, case open/version actual, hashes de fuentes sin cambios, Payment lines que sumen exactamente el saldo y aceptación `payment_authorization`. La evidencia presenta y conserva por separado total original, pagos efectivos previos, saldo y nuevo tender autorizado; no atribuye al actor actual la aceptación histórica del importe ya pagado. Usa CommandReceipt y lockea BillingCutoverControl → CashSession → Invoice → LegacySettlementCase → Payments según D14.

En una transacción:

1. revalida assessment collectible, obligation evidence y `0 < effective_applied < Invoice.total`;
2. crea 1..N `Payment` append-only normales, ligados a Invoice, case, CashSession y receipt;
3. registra evidencia del settlement sin reescribir aceptación histórica;
4. deriva `effective_applied = total` y resuelve el case;
5. publica revenue_paid/cash únicamente por el importe nuevo en la fecha actual; accrual histórico no cambia.

El status legacy original no se edita. La proyección futura puede mostrar la Invoice como paid porque el ledger efectivo ya satisface el total.

#### Reparar overpaid

El exceso es pasivo con el cliente, no reducción de revenue. `return_legacy_overpayment` exige `repairability=returnable`, una base de obligación reconocida que determine el exceso, `legacy_liability.return`, case open/version, monto exactamente igual al liability abierto y líneas de devolución válidas. En una sola transacción crea:

1. `LegacyPaymentApplicationAdjustment(kind=overpayment_to_liability, amount=excess)`, que reduce lo aplicado a Invoice sin modificar Payments;
2. `LegacyLiabilityReturn` + un `LegacyLiabilityReturnPayment` canónico por método conforme D19;
3. eventos de caja/pasivo y resolución del case.

Adjustment, documento y eventos llevan organization, case/Invoice, causal receipt y timestamps; son append-only. UNIQUE `(case, kind)` evita doble reclasificación y la identidad receipt + kind + line index de D19 evita doble salida. Las líneas usan método/referencia/importe canónicos; su suma debe igualar exactamente el liability abierto. Una corrección usa `reverse_legacy_liability_return`, no mutación.

Fórmulas:

~~~text
effective_applied_to_invoice
  = Σ Payments − Σ overpayment_to_liability adjustments

open_customer_liability
  = Σ overpayment_to_liability adjustments
    − (Σ LegacyLiabilityReturnPayment − Σ LegacyLiabilityReturnReversal)
~~~

El comando termina con `effective_applied_to_invoice = Invoice.total` y liability cero. No crea CreditNote, RefundPayment, InvoiceItem, StockMovement ni adjustment de revenue. La salida de caja se atribuye a la fecha/método de la devolución.

Una reparación ya ejecutada externamente antes del cutover puede documentarse mediante `LegacyExternalResolution` con referencia/evidencia; no crea caja ni normaliza el ledger y el caso permanece archivado como legacy-resolved, fuera del read model normal.

Si el censo de producción demuestra que el conteo es cero, no habrá rows que backfillear, pero el gate matemático sigue siendo obligatorio antes del cutover.

### D16. Void, reemplazo y supersesión

Una Invoice anulada nunca se reabre. Si una Invoice posted/unpaid contiene un error y la obligación corregida debe continuar, el único comando ordinario es `void_and_prepare_replacement`:

~~~text
Invoice.posted/unpaid
  ── void_and_prepare_replacement [1 receipt + 1 transaction] ──▶
Invoice.voided + Checkout.replacement.open [correction_pending]
~~~

Precondiciones: cero Payments, mismo tenant, versión actual, sin replacement previo, razón de corrección, dispositions completas, owner y SLA de corrección válidos, al menos una exposición prestada/retenida que continuará y permiso `invoice.replace`. Bajo un solo CommandReceipt y la transacción:

1. prelee dependencias y lockea Invoice conforme D14;
2. revalida payment ledger, lifecycle, collection case y unique lineage;
3. valida dispositions por fulfillment y construye el baseline obligatorio desde cada servicio prestado, consumo clínico realizado o bien retenido;
4. registra void/adjustments de la Invoice;
5. crea Checkout `kind=replacement`, owner, `correction_due_at`, version y líneas autorizadas; cada línea baseline conserva `source_invoice_item`, cantidad/valor originales, disposition y referencias físicas/regulatorias;
6. enlaza `Checkout.replaces_invoice`, proyecta `correction_pending` y, si existe CollectionCase, lo resuelve como replaced;
7. completa audit/receipt con Invoice, Checkout y hash del baseline;
8. commit o rollback total.

Un fallo de validación, baseline, stock, DB o red antes del commit deja la Invoice original posted. Un timeout después del commit replays las mismas referencias y el mismo baseline. No existen en la API ordinaria `void` seguido de `replacement` para una exposición que continúa, ni puede crearse un replacement sin baseline obligatorio.

Lineage:

- `Checkout.replaces_invoice` es FK explícita;
- cuando ese Checkout se postea, la nueva Invoice registra `supersedes_invoice`;
- el original expone `replacement_checkout` inmediatamente y `superseded_by` cuando existe la nueva Invoice;
- en v1 cada Invoice tiene como máximo un reemplazo directo;
- el motivo, actor y snapshots copiados quedan auditados.

El nuevo Checkout conserva tenant/customer/source. Cualquier cambio usa comandos autorizados de ajuste, nunca PATCH al original. D25 gobierna su lifecycle posterior al commit: el baseline no convierte Checkout en AR, pero impide que la exposición desaparezca por reglas de carrito.

Por cada fulfillment retail del documento anulado se conserva una disposition:

- `returned_restocked`: el reemplazo debe volver a consumir stock al postear; si es Rx, la redelivery exacta puede ser neutral conforme D20, pero el retorno no restaura cap;
- `returned_discarded`: no se repuso stock; el reemplazo necesita nueva entrega/stock normal y el fulfillment anterior no desaparece;
- `goods_retained`: la línea de reemplazo usa `stock_behavior=already_fulfilled` ligada a allocation/fulfillment/coverage originales y no vuelve a descontar ni contar;
- `not_applicable`: servicios y cargos clínicos sin movimiento retail; si ya fueron prestados/consumidos, forman baseline obligatorio.

`void_invoice` standalone queda reservado para resultados terminales `duplicate`, `invalid_obligation` o `authorized_waiver`; exige `invoice.void_terminal` y declara que no continúa la exposición. Con `goods_retained`, consumo clínico o servicios prestados, cualquier reason de corrección/reemisión es rechazado y debe usar el comando atómico. Si realmente se perdona esa exposición, el waiver debe autorizarse como resultado terminal, no esconderse como corrección. Una cadena posterior enlaza cada reemplazo con su predecesor; no se sobrescribe lineage.

### D17. MedicalRecord abierto durante migración

#### Decisión: diferir el Checkout primario

Un legacy Invoice draft ligado a MedicalRecord open **no** se convierte anticipadamente en Checkout. El backfill crea `LegacyCheckoutSeed`, una staging read-only que no participa en lifecycle, revenue, AR, readiness ni constraints de Checkout.

Datos mínimos: tenant, legacy Invoice, MedicalRecord/Appointment nullable, snapshots legacy de líneas/tax, writer provenance, candidatos retail/Rx, migration run, estado `pending/adopted/abandoned/quarantined` y destino final.

Si el draft tiene un `tax_rate` determinista, el seed crea o alimenta `MedicalRecordBillingContext(provenance=legacy_draft)` antes de nuevos cargos; close conserva esa tasa. No se etiqueta `first_billable`. Múltiples tasas o writers incompatibles van a cuarentena.

#### Adopción durante close

`close_medical_record`, bajo su CommandReceipt y orden de locks:

1. prelee sin lock los IDs de seeds por MR/Appointment;
2. lockea Appointment/MR/fuentes, materializa protocolos + ClinicalChargeEntry/PrescriptionRevision y luego lockea LegacyCheckoutSeed;
3. revalida relación/version del seed y crea exactamente un Checkout `primary_consultation` nuevo dentro de la transacción;
4. reconstruye **todas** las líneas clínicas desde ciclos activos, nunca desde InvoiceItem/seed;
5. crea selecciones Rx desde la revisión congelada;
6. conserva candidatos comerciales legacy solo como evidencia/migration note; PrescriptionSelection continúa `pending` y requiere nueva decisión explícita;
7. marca seed `adopted` con Checkout resultante en el mismo commit.

StockMovement, Payment o fulfillment inesperado en un draft impide adopción automática. Un retry devuelve el mismo Checkout por receipt; ninguna ruta intenta crear un segundo primario.

#### Draft ligado solo a Appointment

| Caso appointment-only | Destino |
| --- | --- |
| Appointment obtiene MedicalRecord antes de close | El seed se vincula al MR y sigue el protocolo anterior. |
| Appointment abierta sin MR | Seed pending; no aparece como Cobro ni Invoice futura. |
| Appointment done/cancelled, sin MR, draft vacío y sin anchors/Payments/stock | Seed abandoned, reason=`technical_appointment_draft`; no Checkout. |
| Tiene items, Payment, stock, confirmed/paid anchor o evidencia contradictoria | Quarantine; nunca inferir consultation, direct_sale ni no_charge. |

El signal `auto_create_invoice_on_done` se desactiva para nuevos writes antes de habilitar esta adopción.

### D18. Atestación de receta externa sin Invoice draft

#### Owner y revisión regulatoria

Esta decisión supera únicamente el owner `invoice` y el momento técnico de creación de ADR p26. Conserva su separación de Prescription clínica, append-only, gate backend, `billing.rx_dispense`, PII/retención y supervivencia después de cancel/refund.

`ExternalPrescriptionAttestation` se conserva como evidencia regulatoria de retail y deja de usar Invoice como owner de creación. En el modelo futuro pertenece a organization + Checkout `direct_sale` + CheckoutItem regulado. Es append-only, FK PROTECT y contiene:

- `item_regulatory_revision` monotónica y `line_fingerprint` canónico;
- Presentation, cantidad solicitada en unidad base y snapshots de producto;
- `attested_by` server-side, `attested_at`, prescriber_name sanitizado máximo 255, prescription_folio máximo 100 y notes máximo 5,000;
- Checkout version observada, provenance y retention class.

El fingerprint se calcula sobre organization, CheckoutItem public_id, revisión regulatoria, Presentation public_id y cantidad base normalizada. Agregar o cambiar Presentation/cantidad de un item `requires_prescription`, eliminarlo y volverlo a agregar, o sustituirlo incrementa `item_regulatory_revision`; la evidencia anterior permanece auditable pero queda stale por derivación. Cambios de líneas no reguladas no invalidan una atestación válida.

Un CheckoutItem ya referenciado por attestation no se hard-deletea: “eliminar” lo desactiva/versiona. Reagregar crea una identidad o revisión nueva, por lo que la evidencia antigua no revive aunque Presentation/cantidad coincidan otra vez.

Existe como máximo una attestation por `(CheckoutItem, item_regulatory_revision)`. Corregir prescriber/folio/notes no edita la fila: `attest_external_prescription` con `correction_reason` incrementa la revisión regulatoria sin cambiar la línea, crea otra evidencia con `supersedes_attestation` y vuelve stale la anterior.

`update_direct_sale_item` exige `billing.rx_dispense` y payload de atestación en la misma transacción cuando crea o muta una línea regulada sin cobertura clínica interna. Si falta responde `prescription_required`; nunca crea una Prescription clínica ficticia. El servicio puede conservar una variante UI atómica “agregar + atestar”, pero el checkbox no es autoridad.

#### Gate de post y cobertura durable

`pay_checkout` y `post_checkout_unpaid` preleen y lockean Checkout, items regulados y atestaciones conforme D14. Para cada InvoiceItem externo Rx deben probar que:

1. existe exactamente una atestación aplicable a su item/revisión/fingerprint;
2. Presentation y cantidad coinciden con la línea efectiva que se entregará;
3. actor/organization y permiso de captura son válidos;
4. no existe una PrescriptionRevision interna que deba gobernar esa dispensación;
5. stock y demás guards se revalidan en el mismo post.

El post crea `InvoiceItemExternalPrescriptionEvidence`, vínculo inmutable entre InvoiceItem y attestation; Invoice no duplica PII. Un item sin cobertura exacta aborta Invoice, Payment, allocations y movimientos completos.

Lifecycle:

| Evento | Tratamiento de la atestación |
| --- | --- |
| Cambio/eliminación antes de post | Evidencia previa queda stale; nueva revisión regulada exige nueva atestación. |
| Checkout abandoned | Se conserva como evidencia de presentación no consumada; no adquiere coverage de InvoiceItem. |
| Post | Coverage enlaza la evidencia exacta con InvoiceItem y fulfillment. |
| Void/refund/reversal | No edita ni elimina la evidencia; dinero/stock se corrigen aparte. |
| Replacement `goods_retained` | Nueva línea referencia coverage/fulfillment original; no fabrica otra atestación. |
| Replacement con nueva entrega | La línea nueva regulada exige nueva atestación y nuevo fingerprint. |

Crear requiere `billing.rx_dispense`. Leer PII requiere `billing.rx_attestation.view` (ADMIN, VET autorizado y auditor tenant-scoped); recepción/caja sin ese permiso solo ve `present/missing/stale`. Toda lectura detallada se audita. La clase `regulated_rx` se conserva como mínimo cinco años desde el evento relacionado más reciente —attestation, post, void, refund o reversal—, admite legal hold/plazo organizacional mayor y no tiene hard-delete en v1; archivo/anonimización posterior exige la política DD-005 aprobada.

Migración preserva filas existentes. En draft direct_sale solo se enlazan a Checkout/CheckoutItem si Presentation y cantidad reconcilian exactamente; de otro modo se conservan en regulatory quarantine. En Invoice posted/paid/voided se crea coverage hacia el InvoiceItem probado sin inventar Checkout version. Una atestación nunca se descarta porque la operación haya sido cancelada o reembolsada.

### D19. Identidad canónica de eventos financieros hijos

#### Relación entre header raw, Receipt y ledger

El `Idempotency-Key` del cliente identifica CommandReceipt con scope `(organization, command_kind, raw_key)` conforme D14. **Nunca** se copia ni concatena directamente para identificar Payment u otro evento financiero hijo.

Cada receipt nuevo tiene UUID inmutable. Después de canonicalizar y ordenar las líneas, cada evento hijo recibe:

~~~text
event_identity = (command_receipt_id, event_kind, line_index)
event_idempotency_key = "cr1:" + receipt_uuid_sin_guiones + ":" + event_kind_code + ":" + line_index_4d
~~~

`event_kind_code` es un código canónico ASCII de máximo cuatro caracteres. El string cabe en el límite de 64 caracteres y sigue siendo unique por organization. Payment agrega FK `command_receipt` + `command_line_index`; UNIQUE `(command_receipt, command_line_index)` dentro de su tipo y el unique existente `(organization, idempotency_key)` se conservan. Dos command kinds con raw key `ABC` producen receipts/child keys distintos; el replay del mismo receipt produce exactamente los mismos índices/eventos. La ordenación canónica de D14 ocurre antes de asignar índices y conserva duplicados equivalentes.

Payments pre-cutover conservan su `idempotency_key` y provenance originales y no reciben un receipt/índice inventado. Un campo inmutable `financial_identity_version=legacy_raw|receipt_v1` separa generaciones: receipt/line index son nullable solo para `legacy_raw`; una constraint exige receipt, line index y key `cr1:*` para todo evento `receipt_v1` creado después del cutover.

Esta ADR autoriza y exige una versión 1.1 de `docs/financial-event-model-contract.md` en la misma capability slice: amplía §9 con identidad receipt-derived y agrega los eventos de retorno de pasivo siguientes sin cambiar `amount > 0`, `occurred_at`, actor server-side, cash_session, append-only, sign-by-kind ni counterevents.

#### Devolución canónica de pasivo legacy

`LegacyLiabilityReturn` es el documento dueño inmutable que explica case, Invoice legacy, importe autorizado, razón y CommandReceipt. No es por sí mismo movimiento de dinero. `LegacyLiabilityReturnPayment` es el evento financiero de outflow: existe una fila por método y contiene exactamente los campos canónicos `amount`, `method`, `occurred_at`, `actor`, `cash_session`, `reference`, `idempotency_key`, `provenance`, organization y owner return.

- `amount` siempre es positivo; el kind `legacy_liability_return` aporta signo negativo;
- todas las líneas usan el mismo `occurred_at` server-side del comando;
- una devolución mixta cash/card crea dos eventos, suma exacta al total y usa índices canónicos distintos;
- si la política exige caja abierta, todas las líneas se ligan a la CashSession actual resuelta/lockeada, incluidas las no-cash conforme al contrato transversal; si no, quedan null;
- revenue, Invoice total, CreditNote, RefundPayment y stock no cambian; caja/pasivo se mueven por occurred_at.

Una corrección usa `reverse_legacy_liability_return`, nunca UPDATE/DELETE. El comando es all-or-nothing y crea un `LegacyLiabilityReturnReversal` positivo por cada línea efectiva, con `reverses` único, receipt/índice/caja actuales y su propio occurred_at. Cada return payment admite como máximo un reversal; un reversal no se revierte. La reversa reabre el liability por el total; un retorno posterior usa otro CommandReceipt y nuevos eventos.

~~~text
effective_legacy_liability_return
  = Σ LegacyLiabilityReturnPayment − Σ LegacyLiabilityReturnReversal

open_customer_liability
  = Σ overpayment_to_liability adjustments − effective_legacy_liability_return
~~~

### D20. Stock, custodia, dinero y fulfillment Rx

`StockAllocation` es evidencia histórica inmutable de qué lote abasteció una salida; nunca se marca ineffective. Se eliminan expresiones ambiguas como “allocation efectiva” del contrato. Cuatro proyecciones se calculan por separado:

1. **stock disponible:** suma de StockMovement por lote;
2. **custodia física:** entregas, retornos y discard probados;
3. **efecto financiero:** Invoice/Payment/CreditNote/refund/counterevents;
4. **fulfillment Rx:** `PrescriptionFulfillmentEvent` append-only contra PrescriptionRevisionItem.

El post de una línea prescription_retail crea allocation/movement y un `PrescriptionFulfillmentEvent(kind=dispensed, quantity_delta=+q)` ligados al InvoiceItem. Cada corrección física crea `FulfillmentDispositionEvent`; nunca se infiere un cambio Rx desde CreditNote o status de Invoice.

Decisión conservadora v1: una devolución **no restaura** automáticamente el cap prescrito, aunque vuelva stock utilizable. Restaurar capacidad legal requerirá un comando/política regulatoria posterior; hasta entonces no existe delta Rx negativo. Para permitir un cambio físico sin doble conteo, una redelivery de reemplazo exacta puede ser neutral (`quantity_delta=0`) solo si referencia un evento `returned` previo no consumido, no excede su cantidad y valida compatibilidad clínica/presentación bajo locks.

| Hecho | Stock | Custodia | Dinero | Contribución Rx |
| --- | --- | --- | --- | --- |
| Post/entrega inicial Rx | salida por allocations | cliente +q | según posted/payment | `+q` una vez |
| Void + `goods_retained` | sin movimiento nuevo | cliente conserva | obligación se reemplaza/void | `0`; referencia el `+q` original |
| `returned_restocked` | retorno al lote probado | cliente −q | independiente | `0`; v1 no restaura cap |
| `returned_discarded` | no aumenta disponible; movement de discard si aplica | cliente −q | independiente | `0`; v1 no restaura cap |
| Replacement con redelivery probada | nueva salida/allocations | cliente +q | nueva obligación | `0` hasta cantidad retornada; link uno-a-uno al fulfillment original |
| Nueva entrega sin retorno probado | salida nueva | cliente +q | nueva obligación | `+q` y revalida cap |
| Refund sin retorno | sin cambio | cliente conserva | outflow | `0`; fulfillment original sigue contando |
| Refund con retorno/restock | retorno probado | cliente −q | outflow | `0`; fulfillment original sigue contando en v1 |
| RefundReversal | sin cambio | sin cambio | counter-inflow | `0`; nunca es entrega |

La proyección acumulada suma únicamente `quantity_delta` de FulfillmentEvents y exige no superar el cap. Replacement/InvoiceItem puede reutilizar coverage de fulfillment, pero no copiar el delta. Analytics publica por separado dispensed_gross, returned_physical, redelivered y financial_refunded; no llama “dispensado neto” a una deducción financiera.

### D21. Frontera consistente de cutover

Se elige freeze corto + mutation log/catch-up por organización; no CDC ni dual-write financiero. El cutover es una saga administrativa durable `BillingCutoverRun`, no una única transacción larga:

1. `prepare_billing_cutover` abre una transacción, adquiere lock exclusivo de Control —esperando writers in-flight—, reclama Receipt, crea el Run, cambia `legacy → freezing`, captura `final_watermark` y commit;
2. `reconcile_billing_cutover` procesa batches idempotentes mientras freezing, avanza `processed_watermark` y persiste hashes/resultados en el Run;
3. `activate_billing_cutover` abre otra transacción, lockea Control → Receipt → Run, repite reconciliación/gates y cambia `freezing → future` o deja freezing con errores.

Cada fase tiene su CommandReceipt/idempotency key; replay devuelve el mismo Run/resultado. No se mantiene una transacción DB durante todo el backfill.

Una release de compatibilidad previa introduce `BillingCutoverControl(organization, mode, generation, frozen_at, final_watermark, processed_watermark)`, `BillingCutoverRun` y `LegacyBillingMutation` append-only. Todo writer legacy que pueda cambiar cargos, Invoice, items, receta/atestación, Payment, refund o stock financiero:

1. adquiere PostgreSQL `FOR SHARE` sobre la coordination row antes de cualquier row de dominio;
2. permite write solo con `mode=legacy`;
3. agrega en la misma transacción un Mutation con organization, monotonic id, aggregate type/id, source versions, writer kind y receipt/request provenance.

El inventario obligatorio incluye create/update/delete de MedicalRecordService/Product, close_medical_record, signals de Appointment, sincronización/dispensación de receta, atestación externa, CRUD genérico de Invoice/InvoiceItem, confirm/pay/direct-pay/cancel, POS y Payment/CreditNote/refund/reversal con sus movimientos de stock. Un writer no instrumentado bloquea el primer backfill de esa organización.

Prepare/activate usan `FOR UPDATE` sobre la misma row; por definición esperan todos los `FOR SHARE` activos y bloquean nuevos. Reconcile adquiere `FOR SHARE` sobre Control, Receipt y después `FOR UPDATE` sobre su Run conforme a ranks. No se emula esta barrera con un booleano leído sin lock ni solo con middleware/frontend.

El ID puede provenir de una sequence global y admitir gaps por rollback. Como prepare espera todos los shared locks in-flight antes de leer `final_watermark`, ninguna mutation legacy puede comprometer después de ese punto, sin importar cuándo obtuvo su ID. Reconcile marca cada row existente `id <= final_watermark` en una tabla/run mapping idempotente y solo fija `processed_watermark=final_watermark` cuando el query de mutations no procesadas en ese rango devuelve cero; no confía en “último ID visto”.

El protocolo normativo es:

~~~text
compatibilidad instrumentada y verificada
→ backfill inicial por organization + baseline watermark
→ prepare adquiere lock exclusivo (espera writers in-flight)
→ mode legacy → freezing + final_watermark; commit
→ ningún writer nuevo legacy/future inicia efectos
→ reconcile hace catch-up/rebuild autoritativo de cada agregado mutado hasta ese watermark
→ reconciliación completa de sources/items/tax/attestations/Payments/refunds/stock/anchors
→ processed_watermark == final_watermark y cero anomalía no clasificada
→ activate revalida bajo lock y cambia freezing → future
→ rutas/signals legacy rechazan permanentemente nuevos writes
~~~

La mutation log identifica agregados sucios; el catch-up relee y reconstruye desde las tablas legacy bajo locks, no reproduce ciegamente payloads viejos. `LegacyCheckoutSeed` sigue resolviendo MR abierto, pero no sustituye este protocolo. `BillingCutoverControl` es la primera coordination row y `BillingCutoverRun` queda registrado en D14. Durante freezing solo se permiten reads, replay exacto de receipts ya completos y las fases de migración; un comando de negocio nuevo recibe `409 billing_cutover_in_progress` sin receipt/effect.

No se activa una organización si existe mutation posterior al baseline no procesada, un writer sin instrumentar, hash/conteo divergente o caso sin destination/quarantine. Tras el primer evento futuro no hay rollback automático a writers legacy; se desactiva UI y se repara dentro del modelo futuro.

### D22. Elegibilidad de LegacySettlementCase

`kind=partial|overpaid|other` describe únicamente la relación matemática entre total y eventos. Una dimensión independiente `repairability` gobierna qué comando puede mover dinero:

| repairability | Significado | Acciones permitidas |
| --- | --- | --- |
| unassessed | Aún no existe evaluación durable | Ningún movimiento financiero |
| collectible | Obligación histórica válida y saldo exigible demostrados | `settle_legacy_partial` por saldo exacto |
| returnable | Dinero recibido/pasivo demostrable; no se autoriza cobrar más | Retorno legacy específicamente autorizado |
| external_resolution_only | Historia insuficiente pero existe resolución externa documentable | Solo evidencia/audit; sin caja automática |
| quarantined | Contradicción crítica o provenance insuficiente | Ningún comando monetario hasta nueva evaluación válida |

`classify_legacy_settlement` requiere `legacy_settlement.classify`, expected version, reason y CommandReceipt. Crea `LegacySettlementAssessment` append-only con checks/evidence hashes, actor y resultado; el case materializa la última clasificación pero no borra historia. Solo ADMIN/auditor financiero tenant-scoped recibe el permiso por default. El actor que cobra debe tener además `legacy_settlement.collect` + `payment.create`; la clasificación no otorga permiso de caja.

Un partial solo puede clasificarse collectible cuando todos los checks siguientes son positivos:

- Invoice tuvo transición durable a confirmed/obligación emitida; draft/open no califica;
- consultation referencia MedicalRecord closed, o direct_sale tiene evento de emisión/entrega equivalente;
- customer, tenant, items, total, tax y anchors reconcilian sin contradicción;
- precios/source provenance alcanzan el umbral determinista de migración;
- Payments existentes, occurred_at, métodos y CashSessions son íntegros;
- stock/allocations/fulfillment y atestaciones externas requeridas reconcilian;
- no hay cancelled/void/refund/dispute ni writer alternativo incompatibles;
- saldo exacto y obligation evidence legacy quedan congelados en el assessment.

Overpaid solo es `returnable` por el exceso cuando Payments/caja son reales y reconciliados **y** el importe válido de la obligación está demostrado con los mismos checks de emisión, total, tax, items, stock y evidencia regulatoria. Si no puede demostrarse cuánto era obligación, `return_legacy_overpayment` no presume que `Invoice.total` sea la base correcta: el case queda external_resolution_only/quarantined y cualquier devolución total requiere resolución administrativa/legal separada.

Fallar cualquier hard check impide collectible aunque un ADMIN lo solicite. `settle_legacy_partial` revalida classification/version y hashes bajo locks; si la fuente cambió agrega un assessment de invalidación, proyecta unassessed/quarantined y no crea Payment. Solo después de liquidar un collectible puede la proyección futura mostrar paid normal. Un partial no collectible nunca se legitima por el mero pago matemático.

### D23. Sucesor del PDF draft

Se conserva la capacidad operativa de entregar un documento previo, pero deja de llamarse Invoice. `issue_checkout_estimate` exige Checkout.open, expected version e Idempotency-Key y crea un `CheckoutEstimate` append-only único por Checkout/version. Guarda snapshot de líneas/totales, generated_at/by y content hash; no guarda un Invoice ni muta totals/lifecycle. `GET /checkout-estimates/{estimate}/pdf` renderiza exclusivamente ese snapshot no financiero:

- título “Estimado de atención/venta” y watermark visible `ESTIMADO — NO ES FACTURA`;
- Checkout public_id, version, generated_at, customer y snapshots/totales actuales;
- sin Invoice number, posted_at, paid_at, due_at, fiscal folio ni lenguaje de obligación/pago;
- una edición posterior no altera el archivo ya descargado, pero la UI advierte que otra version quedó obsoleta;
- emitir/descargar no crea revenue, AR, acceptance ni Invoice; emisión usa Receipt y cada lectura deja audit de acceso.

Solo Checkout.open puede emitir una versión nueva. Dos requests para la misma Checkout/version reutilizan el mismo snapshot por unique/receipt; una edición posterior puede emitir otra versión sin reescribir la previa. Después de completed/abandoned se conservan Estimates ya emitidos, pero no nace otro; posted enlaza al PDF de Invoice.

Emitir requiere `checkout.estimate.issue` y leer requiere acceso tenant-scoped al Checkout/cliente; ADMIN, owner operativo y auditor autorizado son defaults, no un link público. `retention_class=commercial_estimate` conserva snapshot 24 meses después del terminal del Checkout y luego deja tombstone/hash/metadata sin PII; legal hold o vínculo a disputa suspende esa reducción.

`/invoices/{id}/pdf` solo sirve Invoice posted/voided y archivo legacy. Durante compatibilidad puede seguir mostrando drafts legacy read-only; después de su mapping devuelve `410 legacy_draft_pdf_retired` con el Checkout/estimate relacionado cuando exista. Frontend reemplaza “PDF borrador” por “Descargar estimado”; después de post ofrece exclusivamente el PDF de Invoice. No existe adapter que cree Invoice draft para renderizar.

### D24. Comando explícito de repricing clínico

`reprice_clinical_charge` es el único writer de un cambio de precio capturado. Requiere MedicalRecord open, ClinicalChargeEntry active con cantidad positiva, source/entry/MR versions esperadas, `billing.clinical_charge.reprice`, reason code + nota, nuevo unit_price positivo e Idempotency-Key.

Bajo CommandReceipt y locks `BillingCutoverControl → MedicalRecord → source → ClinicalChargeEntry`:

1. revalida que no exista ClinicalChargeSnapshot/Checkout derivado ni cierre concurrente;
2. agrega QuantityEvent negativo que lleva el ciclo anterior a cero y lo cierra como repriced;
3. crea ciclo siguiente con `supersedes_entry`, precio/provenance nuevos y baseline por la cantidad clínica completa;
4. conserva MedicalRecordBillingContext tributario, no mueve stock y aumenta versiones;
5. registra actor, reason, before/after y completa receipt en el mismo commit.

El permiso es ADMIN por default; VET solo si la organización lo concede expresamente, y recepción/ASSISTANT no lo heredan. No existe PATCH de unit_price. Replay devuelve los mismos ciclos y una versión stale no crea eventos parciales.

### D25. Lifecycle protegido del replacement después de void

#### Decisión: continuidad operacional controlada

Se elige la alternativa A de ADR-R60: después de `void_and_prepare_replacement` existe temporalmente una Invoice original voided y un Checkout sin AR, pero **la exposición no vuelve a ser un carrito descartable**. La continuidad es operacional, no financiera: revenue y AR reaparecen solo cuando nace la nueva Invoice; hasta entonces una proyección obligatoria `correction_pending` mantiene el caso visible, asignado y vencible.

No se crea un agregado `ReplacementCase` separado en v1. `correction_pending` se deriva de:

~~~text
Checkout.kind = replacement
AND Checkout.lifecycle = open
AND EXISTS CheckoutItem.required_replacement_baseline = true
AND no existe resolución terminal
~~~

Todo replacement creado por D16 debe satisfacer esa condición desde el mismo commit. Si no existe valor prestado/retenido que continuar, el caso correcto es `void_invoice` terminal, no un replacement vacío.

#### Baseline obligatorio

El baseline es una propiedad inmutable de líneas de Checkout, no otro agregado. Por cada hecho de valor que sobrevivió al void se conserva:

- `source_invoice_item` y snapshot económico original;
- `baseline_kind=performed_service|clinical_consumed|goods_retained`;
- cantidad prestada/consumida/retenida, valor bruto original y disposition;
- referencias de stock, fulfillment y cobertura regulatoria cuando apliquen;
- `required_replacement_baseline=true` y hash incluido en el CommandReceipt.

El baseline demuestra **qué valor ya fue entregado**, no obliga a repetir un precio erróneo. No se elimina, sustituye ni reduce mediante PATCH, selección retail, descuento genérico o limpieza TTL. `adjust_replacement_exposure` puede corregir la pretensión económica mediante un `CheckoutEvent(kind=replacement_exposure_adjusted)` append-only con `expected_version`, permiso `invoice.replace_adjust`, reason code, nota/evidencia y before/after; la línea baseline y sus hechos físicos permanecen. El resultado debe conservar un importe exigible positivo. Si se pretende perdonar todo el remanente, no se aplica un adjustment a cero: se usa el waiver terminal separado.

Los items adicionales que todavía no fueron entregados sí pueden agregarse o retirarse conforme a su source. Esa edición nunca altera el baseline, revierte stock previo ni cambia fulfillment Rx implícitamente.

#### Únicos resultados terminales

Un Checkout replacement open solo puede terminar por uno de estos comandos:

1. `pay_checkout` o `post_checkout_unpaid`: crea una nueva Invoice con `supersedes_invoice`, copia baseline + adjustments + lineage, y completa `posted_paid` o `posted_unpaid`;
2. `waive_replacement_exposure`: crea `ReplacementWaiver` append-only, completa `completion_kind=replacement_waived` sin Invoice nueva y deja razón, evidencia, actor, importe perdonado, baseline hash, timestamp y CommandReceipt.

El waiver requiere `invoice.replace_waive`, ADMIN por default, reason code allowlisted, nota/evidencia obligatoria y revalidación del baseline/versión bajo lock. Registra como importe perdonado todo el remanente exigible actual. No es `no_charge`, abandono, descuento, void adicional ni CreditNote; tampoco mueve stock o fulfillment. Analytics lo reporta como exposición condonada de corrección y conserva por separado el adjustment del void original. Una reducción parcial existe solo como adjustment explícito; mientras quede importe exigible el Checkout continúa `correction_pending` y debe terminar en Invoice o waiver del remanente. `ReplacementWaiver` usa `retention_class=financial_correction`, FK PROTECT y la misma retención mínima del documento financiero reemplazado.

#### Owner, SLA y no desaparición

- `owner` y `correction_due_at` son obligatorios al crear el replacement; takeover/reasignación exige permiso y audit.
- `correction_due_at` vencido proyecta `correction_overdue`, genera escalamiento operativo y nunca abandona/expira automáticamente el Checkout.
- `expires_at` es nulo para `kind=replacement`; el job de expiry debe omitirlo y fallar cerrado si recibe ese kind.
- `abandon_checkout` y `complete_no_charge` devuelven conflicto estable para cualquier replacement.
- una disputa puede poner `operational_hold=dispute`, pero el objeto permanece en la cola Correcciones y conserva owner/SLA/baseline; su resolución sigue siendo nueva Invoice o waiver.
- ni borrar al cliente, cerrar sesión de caja, cambiar owner ni superar el SLA elimina la exposición.

Así se acepta una ventana sin AR entre las dos Invoices, pero se evita que sea una ventana sin responsabilidad. Si producto necesitara continuidad financiera sin esa ventana, tendría que elegirse otra decisión: postear la Invoice reemplazante dentro del mismo comando y renunciar a la edición posterior. Esa no es la opción adoptada por esta ADR.

#### Justificación y alternativas no adoptadas

| Opción | Decisión | Justificación |
| --- | --- | --- |
| Continuidad operacional controlada en Checkout | **Aceptada** | Permite corregir precio/selección antes de reemitir, pero baseline, owner, SLA y terminales cerrados evitan perder valor ya entregado. |
| `ReplacementCase` como agregado separado | **No aceptada en v1** | Duplicaría identidad, owner, SLA y lifecycle del Checkout sin aportar hoy una transición independiente; la proyección se deriva de kind+lifecycle+baseline. Se reevalúa si aparecen episodios o actores propios fuera del Checkout. |
| Nueva Invoice posted dentro del mismo void | **No aceptada** | Mantendría AR continuo, pero congelaría la corrección antes de que recepción pueda preparar el importe correcto; contradice el propósito del Checkout replacement editable. |
| Abandono, expiry o no_charge genérico | **Rechazada** | Son terminales válidos solo cuando nunca hubo exposición; aquí borrarían servicios prestados o bienes retenidos sin acto de autorización. |
| Adjustment ordinario hasta $0 | **Rechazado** | Haría indistinguible un cambio de precio de una condonación total; el waiver separado conserva autoridad, evidencia y analytics. |

## 3. Fase 2 — Dominio futuro

### 3.1 Lenguaje ubicuo

| Término | Definición |
| --- | --- |
| MedicalRecord | Hechos clínicos de una atención. Posee servicios y consumos; termina en closed. |
| ClinicalChargeEntry | Ciclo económico con precio inmutable y cantidad derivada de eventos append-only. |
| ClinicalChargeSnapshot | Proyección inmutable que close copia desde un Entry activo y su cantidad neta. |
| Checkout | Agregado operativo editable que prepara qué se cobrará/dispensará. No es deuda ni documento financiero. |
| CheckoutItem | Línea cobrable con source y source_object inmutables; puede ser snapshot clínico o retail editable. |
| PrescriptionSelection | Decisión del cliente sobre un PrescriptionItem dentro de un Checkout. |
| Preparation readiness | Validez estructural derivada del Checkout; no es autorización para ejecutar una acción. |
| Action availability | Evaluación derivada por actor y comando; combina preparación, permiso y dependencias operativas actuales. |
| Post | Evento que emite una obligación inmutable, asienta entrega retail y crea Invoice. |
| Invoice | Documento financiero inmutable ya posteado. Nunca es carrito ni borrador. |
| Payment | Evento append-only aplicado a Invoice. |
| Unpaid/Paid | Proyección del ledger; no lifecycle de preparación. |
| Abandon | Cierre de un Checkout que nunca generó obligación. |
| Void | Anulación total de una Invoice posted sin Payments, por error/corrección autorizada. |
| Refund | Devolución monetaria de una Invoice paid mediante CreditNote/RefundPayment. |
| Dispute | Hold operacional explícito sobre cargos clínicos no aceptados; tiene owner, SLA y resolución. |
| CollectionCase | Disputa persistente después de post; gobierna la proyección collection_status. |
| LegacyCheckoutSeed | Staging migratoria para draft con MR abierto; nunca es Checkout ni obligación. |
| CommandReceipt | Recibo durable que hace idempotente un comando y conserva su resultado exacto. |
| ExternalPrescriptionAttestation | Evidencia regulatoria append-only de receta externa para una revisión exacta de línea POS; no es Prescription clínica. |
| PrescriptionFulfillmentEvent | Hecho append-only que contribuye —o enlaza neutralmente— al cap dispensado; separado de stock y dinero. |
| LegacySettlement repairability | Clasificación probada que autoriza o prohíbe una reparación monetaria; no se deriva solo del saldo. |
| BillingCutoverControl | Coordination row tenant-aware que fija la autoridad legacy/freezing/future y su watermark. |
| Checkout Estimate | Snapshot/PDF append-only y versionado de un Checkout; nunca Invoice, deuda ni comprobante de pago. |
| Replacement baseline | Hechos y valor ya prestados/retenidos que el void no puede convertir en carrito descartable; vive en líneas inmutables del Checkout replacement. |
| Correction pending | Proyección operacional de un replacement open con baseline sin resolución; tiene owner/SLA y no es AR. |
| Replacement waiver | Evento terminal, autorizado y append-only que perdona explícitamente la exposición de un replacement sin fabricar no_charge. |

### 3.2 Relación de agregados

~~~text
Appointment
    │
    ▼
MedicalRecord ── close ───────────────────────────────┐
    │                                                │
    │ servicios / consumos / receta                  ▼
    │                                      ┌──────────────────┐
    └─────────────────────────────────────▶│     Checkout     │
                                           │ origin           │
POS ── iniciar venta ─────────────────────▶│ items            │
                                           │ rx selections    │
                                           │ ext-rx evidence  │
                                           │ totals           │
                                           │ readiness        │
                                           │ owner/version    │
                                           └────────┬─────────┘
                                                    │
                          no_charge ────────────────┤
                          Cobrar ahora ─────────────┤
                          Dejar pendiente ──────────┘
                                                    ▼
                                           ┌──────────────────┐
                                           │ Invoice posted   │
                                           │ immutable items  │
                                           └────────┬─────────┘
                                                    │ Payment ledger
                                             unpaid ─────▶ paid
~~~

MedicalRecord y Checkout son agregados distintos:

- MedicalRecord cambia por hechos clínicos;
- Checkout cambia por decisión comercial/dispensación;
- Invoice cambia por eventos financieros y no admite edición de contenido.

La cardinalidad de Checkout es explícita:

- MedicalRecord tiene exactamente un Checkout `primary_consultation` creado por close;
- puede tener cero o más Checkouts `prescription_supplement`, cada uno con remanente Rx congelado y sin volver a cobrar cargos clínicos;
- puede tener Checkouts `replacement` únicamente creados por `void_and_prepare_replacement` en el mismo commit que void;
- un índice único tenant-aware garantiza el único primario; constraints separadas evitan duplicar la misma dispensación o el mismo reemplazo;
- `direct_sale` no tiene MedicalRecord.

### 3.3 Por qué Checkout debe ser un modelo separado

#### Opción A — La propia Invoice

| Ventaja | Problema |
| --- | --- |
| Menos tablas y menor migración inicial | Vuelve a llamar documento financiero a un carrito |
| Reusa InvoiceItem y totals | $0 y rechazo de receta siguen necesitando Invoice falsa |
| Reusa rutas actuales | Mezcla ownership clínico, retail, stock y pago |
| Menos DTOs | POS vuelve a producir documentos huérfanos/cancelled técnicos |

**Descartada como arquitectura objetivo.** Reproduciría la causa raíz de la auditoría.

#### Opción B — Modelo Checkout separado

| Ventaja | Costo |
| --- | --- |
| Tiene lifecycle propio y puede terminar no_charge | Nuevo agregado, tabla, serializer y servicios |
| Persiste receta pending/declined sin Invoice | Hay snapshot/copia de líneas al postear |
| POS reanudable sin documento financiero | Migración de drafts más compleja |
| Ownership/source explícitos | Deben definirse transacciones entre Checkout, Invoice, stock y Payment |
| Readiness y blockers claros | Más contratos de API |

**Seleccionada.** Tiene un motivo de cambio distinto conforme al principio de ADR p53.

#### Opción C — Abstracción conceptual sobre Invoice

Podría crear una capa de servicio Checkout que internamente siga usando Invoice draft.

**Aceptable solo como puente de migración**, no como estado final. Ocultaría parte de la deuda a frontend, pero conservaría $0, writers ambiguos, serializers peligrosos y documentos técnicos en la base.

### 3.4 Checkout conceptual

Campos/responsabilidades mínimas:

| Área | Datos conceptuales |
| --- | --- |
| Identidad | public_id, organization, origin=consultation/direct_sale, kind=primary_consultation/prescription_supplement/direct_sale/replacement |
| Fuente | medical_record nullable, appointment derivable, customer/pet según origen |
| Lifecycle | open/completed/abandoned; completion_kind |
| Operación | owner, version, regulated item revisions, expires_at, operational_hold, correction_due_at para replacement, created_at, completed_at, abandoned_at/reason |
| Totales | subtotal, discount, tax_rate/tax, total calculados exclusivamente en backend |
| Outcome | Invoice derivable por su FK única a Checkout; no_charge_reason; replaces_invoice nullable; replacement resolution/waiver nullable |
| Auditoría | created_by, completed_by, mutation log |

Reglas:

- consultation tiene exactamente un Checkout primario por MedicalRecord;
- una consulta puede tener suplementos Rx y reemplazos únicamente por los comandos definidos;
- direct_sale no requiere MedicalRecord;
- origin no cambia;
- un Checkout completed/abandoned es inmutable;
- un Checkout open no es AR y nunca aparece en revenue;
- no se crean Payments contra Checkout;
- Invoice se enlaza uno-a-uno al Checkout que la originó;
- todo replacement nace con baseline, owner y correction_due_at; no tiene expires_at ni admite terminales genéricos;
- `correction_pending/overdue` se deriva, no agrega otro lifecycle ni convierte el Checkout en obligación financiera.

#### Creación en consulta

MedicalRecord.close:

1. prelee la relación con Appointment y lockea Appointment → MedicalRecord;
2. valida ownership y condiciones clínicas;
3. materializa protocolos, consumos y ClinicalChargeEntry/QuantityEvents faltantes;
4. congela `ClinicalChargeSnapshot` desde ciclos activos y una `PrescriptionRevision`;
5. marca MedicalRecord closed, completa Appointment y crea Checkout en la misma transacción;
6. copia los cargos `charge` desde snapshots, no desde catálogo;
7. crea PrescriptionSelection pending por sugerencia elegible de esa revisión;
8. si no hay cargo ni selección pendiente, completa no_charge; si requiere decisión, lo publica en Cobros.

No crea Invoice. Ningún estado intermedio es visible: un fallo en materialización, snapshot, Appointment o Checkout revierte el cierre completo.

#### Creación en POS

El POS crea Checkout direct_sale y agrega líneas server-side. Los totales reales siempre vienen del backend. Una línea `requires_prescription` sin cobertura clínica interna exige atestación D18 bajo el permiso correspondiente. El usuario puede editar mientras open, abandonar o finalizar **solo si no es un replacement**; un replacement de direct sale queda sujeto a D25 aunque su origin siga siendo POS.

### 3.5 CheckoutItem y ownership

Sources mínimos:

| source | source_object | `stock_behavior` | Editable en Checkout | Mueve stock al post |
| --- | --- | --- | --- | --- |
| clinical_service | ClinicalChargeSnapshot → MedicalRecordService | no_stock | No | No |
| clinical_consumable_charge | ClinicalChargeSnapshot → MedicalRecordProduct | clinical_already_consumed | No | No |
| prescription_retail | PrescriptionRevisionItem + Selection | fulfill_on_post | Sí, campos retail | Sí, por allocations |
| direct_sale_product | Presentation + attestation D18 si requiere receta externa | fulfill_on_post | Sí | Sí, por allocations |
| direct_sale_service | Service | no_stock | Sí | No |
| authorized_adjustment | Regla/actor/razón + línea base | inherit_no_fulfillment | Solo permiso especial | No por sí misma |
| replacement_retail | InvoiceItem/allocation original | fulfill_on_post/already_fulfilled | Solo extras no entregados; baseline por comando D25 | Según disposition original |

Cada CheckoutItem contiene snapshot de description, quantity, unit_price, discount/tax aplicable, `source_kind`, FK explícita compatible y `stock_behavior`. Se prohíbe un `GenericForeignKey` sin integridad y se exige CHECK/XOR más validación de mismo tenant. El link conserva provenance; el snapshot garantiza que el documento futuro no cambia si el catálogo cambia. Líneas de distinta provenance no se fusionan aunque compartan presentación y precio.

Los items included permanecen en MedicalRecordProduct para costo clínico y no se copian como líneas cobrables.

Mientras Checkout está open, `CheckoutItem` conserva únicamente intención: Presentation y `requested_quantity` en unidades base; no contiene lote committed ni StockMovement. `StockAllocation` nace **solo dentro del post exitoso** y pertenece por FK obligatoria al `InvoiceItem` retail/Rx recién creado. Conserva Product, Presentation, StockLot, cantidad base y StockMovement committed. Un InvoiceItem puede tener 1..N allocations; `StockAllocation` sin InvoiceItem o StockMovement es inválida.

Un replacement `goods_retained` no crea allocation ni movement nuevos: su CheckoutItem conserva `required_replacement_baseline`, `source_invoice_item` y el lineage físico; el nuevo InvoiceItem registra `fulfillment_source=reused` y referencias durables a las StockAllocations, regulatory coverage y FulfillmentEvent originales. Servicios prestados y consumos clínicos usan el mismo baseline sin stock. El resto usa `fulfillment_source=new_allocations`. Las variantes son XOR y auditables; su contribución Rx sigue D20.

Finalize puede repartir multilote bajo FEFO y locks; debe satisfacer toda la cantidad solicitada o fallar completo, nunca reducirla silenciosamente. Un reverso vuelve al lote probado o registra discard. El consumo clínico v1 mantiene un lote explícito por `MedicalRecordProduct`: si la cantidad supera el lote elegido se rechaza antes de consumir, en vez de crear una provenance imposible de representar.

### 3.6 PrescriptionSelection

Al cerrar se crea una `PrescriptionRevision` inmutable con sus ítems, dosis/cantidad/cap y provenance. Editar clínicamente una receta cerrada crea una revisión/addendum nuevo; nunca borra/recrea la versión ya referenciada por Checkout o Invoice.

Por cada sugerencia elegible:

- checkout;
- prescription_revision_item;
- decision=`pending/accepted/declined`;
- `eligible_remaining_at_open` en unidades base;
- decision_reason;
- decided_by/decided_at;
- version/provenance.

Invariantes:

- pending no tiene línea retail activa;
- accepted exige una o más CheckoutItems solicitadas válidas y suma > 0; no exige ni crea StockAllocation mientras open;
- declined no tiene CheckoutItem retail activo;
- full/partial se deriva y no se persiste como decisión;
- al abrir un suplemento se lockea la receta y se resta la proyección acumulada de PrescriptionFulfillmentEvents para congelar el nuevo remanente elegible;
- al finalizar se vuelve a lockear y la contribución histórica más los nuevos eventos no puede exceder el cap clínico;
- una mutación actualiza Checkout version y totals;
- la UI no preselecciona.

### 3.7 Readiness es condición derivada

No se crea status ready. El backend devuelve dos capas:

~~~text
preparation_readiness = {
  ready,
  blockers[],
  checkout_version,
  evaluated_at
}

actions = {
  pay:                { allowed, blockers[], required_inputs[] },
  post_unpaid:        { allowed, blockers[], required_inputs[] },
  complete_no_charge: { allowed, blockers[], required_inputs[] },
  abandon:            { allowed, blockers[], required_inputs[] },
  open_dispute:       { allowed, blockers[], required_inputs[] },
  attest_external_rx: { allowed, blockers[], required_inputs[] },
  adjust_replacement: { allowed, blockers[], required_inputs[] },
  waive_replacement:  { allowed, blockers[], required_inputs[] }
}
~~~

Blockers de consultation:

- MedicalRecord no cerrado;
- selection pending;
- línea clínica sin snapshot/precio válido;
- producto aceptado sin Presentation/requested_quantity válida;
- cliente/owner incoherente;
- total inválido;
- Checkout no open.

Blockers de direct_sale:

- carrito vacío;
- cliente requerido ausente;
- línea solicitada/precio inválido;
- línea requires_prescription sin ExternalPrescriptionAttestation vigente para item revision/fingerprint;
- total inválido;
- Checkout no open.

Blockers específicos de replacement:

- baseline ausente, alterado o cuyo hash no coincide;
- owner o correction_due_at ausentes;
- lineage/disposition/source InvoiceItem incompletos;
- `complete_no_charge`, `abandon` y expiry siempre están bloqueados por `replacement_requires_resolution`;
- adjustment a cero exige `waive_replacement_exposure`, no una mutación ordinaria.

`preparation_readiness` cubre estructura, source/version, selections, customer y totales. `actions.<command>.blockers` cubre estado/permiso/dependencias actuales que el payload no puede solucionar: CashSession cerrada, crédito organizacional deshabilitado, disputa abierta o stock insuficiente observado.

`required_inputs` describe datos que el propio comando está autorizado a capturar y por eso **no vuelve `allowed=false`** en lectura. Ejemplos: pay requiere payment lines + aceptación; post_unpaid requiere due_at, razón, aceptación/términos; abandon requiere reason; open_dispute requiere líneas/motivo; attest_external_rx requiere item revision, prescriber y declaración; adjust replacement requiere reason/evidence; waiver requiere reason/evidence y confirmación del importe perdonado. Cada entrada declara nombre, schema y reason. El POST valida que todos estén presentes y crea evidencia/efectos atómicamente. Pay/post no fabrican silenciosamente una atestación ausente: primero debe existir el comando regulatorio D18 o la variante atómica de edición de línea.

Ambas capas son snapshots de lectura y pueden cambiar después de responder. El comando final es autoritativo, revalida todo y devuelve blockers actuales si falla. Si se necesita SLA, puede registrarse `first_ready_at` como anchor analítico sin convertirlo en autoridad.

### 3.8 Invoice futura

Invoice nace únicamente al postear:

- contenido copiado e inmutable desde Checkout;
- origin y source de línea inmutables;
- posted_at obligatorio;
- total > 0 en esta fase;
- no status draft;
- no endpoint genérico para cambiar status/type/links;
- stock retail asentado en la misma transacción de post;
- fulfillment Rx y regulatory coverage asentados/referenciados en la misma transacción de post;
- consulta exige MedicalRecord closed;
- todo writer nuevo exige `ObligationEvidence` fuerte y válido para versión/total; el backfill puede usar provenance legacy débil explícita y read-only;
- `supersedes_invoice` nullable e inmutable;
- `collection_status=collectible/disputed/closed` se deriva de CollectionCase + lifecycle/settlement; no tiene setter genérico.

Para direct_sale Rx externo, cada InvoiceItem referencia la ExternalPrescriptionAttestation exacta mediante coverage D18; Invoice no almacena una copia mutable de prescriber PII. Si el mismo post cobra, cada Payment usa la identidad financiera D19.

Dimensiones:

| Dimensión | Valores |
| --- | --- |
| document_lifecycle | posted, voided |
| payment_status | unpaid, paid; derivado/materializado desde `effective_applied_amount` |

Payment status puede materializarse por rendimiento, pero debe obedecer:

~~~text
normal writer:
  effective_applied_amount = Σ Payments

legacy repaired:
  effective_applied_amount = Σ Payments − Σ LegacyPaymentApplicationAdjustment

unpaid ⇔ effective_applied_amount = 0
paid   ⇔ effective_applied_amount = Invoice.total
~~~

No existe partial en writers normales; cualquier suma intermedia nueva es inválida. La fórmula legacy solo opera para una Invoice marcada con provenance/case migratorio y no habilita sobrepago nuevo.

### 3.9 Constraints y eventos transversales

Constraints mínimas, además de validación de servicio:

| Invariante | Enforcement esperado |
| --- | --- |
| Un Checkout primario por MedicalRecord/tenant | UNIQUE parcial por organization, medical_record, kind=primary_consultation |
| Un resultado financiero por Checkout | `Invoice.checkout` FK obligatoria y UNIQUE; Checkout no duplica ese FK |
| Un replacement directo por Invoice | UNIQUE Checkout.replaces_invoice y UNIQUE Invoice.supersedes_invoice |
| Replacement no descartable | kind=replacement exige replaces_invoice, owner, correction_due_at, expires_at NULL y ≥1 item baseline; service guards bloquean abandon/no_charge/expiry |
| Baseline preservado | Cada baseline tiene source_invoice_item único dentro del Checkout, kind/cantidad/valor/hash inmutables; corrections son adjustments append-only |
| Un resultado de replacement | CHECK/servicio: Invoice superseding XOR ReplacementWaiver; ambos terminalizan una sola vez y waiver es UNIQUE por Checkout |
| Un BillingContext por MedicalRecord | UNIQUE tenant-aware |
| Un ciclo ClinicalChargeEntry activo por fuente | UNIQUE parcial tenant/source donde lifecycle=active |
| Secuencia y snapshot de ciclo | UNIQUE tenant/source/cycle_number y UNIQUE ClinicalChargeSnapshot.entry |
| Una mutación de cantidad por retry | UNIQUE `(clinical_charge_entry, mutation_key)` |
| Una fuente explícita por ClinicalChargeEntry/Snapshot/CheckoutItem | CHECK XOR + FKs reales + validación de organization |
| Una disputa abierta por Checkout | UNIQUE parcial `status=open` |
| Un CollectionCase abierto por Invoice | UNIQUE parcial `status=open` |
| Un LegacyCheckoutSeed por Invoice legacy | UNIQUE tenant-aware; adopted_checkout nullable UNIQUE |
| Un LegacySettlementCase por Invoice legacy | UNIQUE tenant-aware |
| Un receipt por tenant/comando/key | UNIQUE de D14 |
| Un Estimate por Checkout/version | UNIQUE tenant-aware; snapshot/hash inmutables y solo se emite mientras open |
| Un evento financiero hijo por receipt/kind/index | `financial_identity_version`; receipt_v1 exige FK/index/key cr1 + UNIQUE tipada D19; unique por organization se conserva |
| Una selección por Checkout/revisión Rx item | UNIQUE tenant-aware |
| Una atestación externa cubre revisión exacta | UNIQUE CheckoutItem/revision + FK PROTECT + fingerprint; corrección crea nueva revision/supersedes; post crea coverage InvoiceItem→Attestation |
| Fulfillment Rx no excede cap | Lock de PrescriptionRevision + suma de PrescriptionFulfillmentEvent.quantity_delta en finalize |
| StockAllocation significa salida committed | `invoice_item_id` + `stock_movement_id` obligatorios; movement usado una vez y creación en el mismo post |
| Fulfillment nuevo vs reutilizado | CHECK XOR entre allocations nuevas y referencia a allocations/fulfillment originales |
| Redelivery neutral no duplica cap | FK a return/disposition previo; cantidades acumuladas no exceden lo retornado ni se reutiliza el mismo retorno |
| Liability return canónico | Total documento = suma de return payments; ≤1 reversal por evento; identity D19 |
| Settlement collectible probado | settle exige assessment vigente/hash exacto; kind matemático no autoriza |
| Una autoridad de writers por organización | BillingCutoverControl mode + final/processed watermark; writers legacy/future mutuamente excluyentes |

`CheckoutEvent` es append-only y registra al menos organization, Checkout, command, actor, `version_before/after`, reason, timestamp, CommandReceipt/idempotency key, diff monetario y referencias resultantes. No guarda secretos de pago ni evidencia binaria sensible en JSON; conserva referencias a registros tipados. Eventos de Invoice, Payment, liability return, CreditNote, Refund, stock, custody, fulfillment, assessment y cutover siguen en sus ledgers/audits propios y enlazan el mismo receipt/causal command cuando corresponda.

## 4. Fase 3 — Máquina de estados futura

### 4.1 MedicalRecord

No cambia su máquina esencial:

~~~text
open ── close ──▶ closed
~~~

close es el límite de ownership clínico y el único writer normal que crea Checkout consultation. Un Checkout no puede postearse mientras su MedicalRecord esté open, incluidos registros migrados.

### 4.2 Checkout

Lifecycle mínimo:

~~~text
                               ┌─ completion_kind = no_charge
                               ├─ completion_kind = posted_paid
open ── complete ──▶ completed┤
  │                           ├─ completion_kind = posted_unpaid
  │                           └─ completion_kind = replacement_waived
  │
  └── abandon ─────▶ abandoned

open + operational_hold=dispute ── resolve ──▶ open normal o completed

replacement.open + baseline = correction_pending
  ├─ pay/post_unpaid ─────────▶ completed/posted_* + nueva Invoice
  └─ waiver autorizado ───────▶ completed/replacement_waived
  abandon / expiry / no_charge ─▶ PROHIBIDOS
~~~

**Readiness no es un estado.** Es una condición derivada dentro de open.

| Estado | Significado | Editable | Tiene Invoice | Efecto financiero |
| --- | --- | --- | --- | --- |
| open | Se prepara el cobro y se resuelven selecciones | Sí, según source/permiso | No | Ninguno |
| open/correction_pending (proyección) | Se corrige valor ya entregado después de void | Baseline no; extras/adjustments por permiso | No | Exposición operacional, no AR |
| completed/no_charge | Se resolvió sin obligación | No | No | Ninguno |
| completed/posted_paid | Se posteó y cobró atómicamente | No | Sí, paid | Devengo + caja |
| completed/posted_unpaid | Se emitió deuda autorizada | No | Sí, unpaid | Devengo + AR |
| completed/replacement_waived | Se perdonó explícitamente exposición de corrección | No | No nueva; conserva original voided | Waived exposure; no revenue/AR nuevo |
| abandoned | Se descartó antes de crear obligación | No | No | Ninguno |

#### Reglas de abandono

- direct_sale open puede abandonarse o expirar salvo `kind=replacement`;
- consultation sin cargos puede completarse no_charge, no abandonarse;
- consultation con cargos clínicos reales no puede abandonarse para borrar la deuda: debe cobrarse o postearse unpaid;
- consultation con cargos disputados entra a `operational_hold=dispute`, no a abandoned;
- consultation migrada errónea puede abandonarse solo con permiso administrativo y razón de corrección;
- replacement nunca puede abandonarse, expirar ni completar no_charge; vencido permanece `correction_overdue` hasta nueva Invoice o waiver;
- abandoned no mueve stock ni genera documento.

### 4.3 Invoice: lifecycle documental y settlement

~~~text
document_lifecycle:

posted ── void ──▶ voided

payment_status, mientras lifecycle=posted:

unpaid ── pago total ──▶ paid

collection_status, ortogonal:

collectible | disputed | closed
~~~

Vista combinada para producto:

| Lifecycle | Ledger efectivo | Estado mostrado |
| --- | --- | --- |
| posted | effective_applied=0 | Pendiente de pago |
| posted + CollectionCase.open | effective_applied=0 | Pendiente disputada |
| posted | effective_applied=total | Pagada |
| voided | effective_applied=0 | Anulada |
| posted | 0 < effective_applied < total sin LegacySettlementCase | Estado inválido en esta fase |
| voided | effective_applied>0 | Estado inválido |

Una Invoice paid no pasa a voided. Correcciones monetarias usan CreditNote/RefundPayment y la Invoice original permanece posted/paid.

`posted` es el nombre único de schema, API, evento (`invoice_posted`) y timestamp (`posted_at`). La UI en español puede mostrar **Emitida**, pero `issued` no es un segundo estado ni nombre de campo. `CreditNote.issued_at` conserva su vocabulario propio por ser otro tipo documental.

### 4.4 Decisión explícita sobre los nombres actuales

| Nombre actual/candidato | Decisión futura | Motivo |
| --- | --- | --- |
| draft | **Eliminar de Invoice** | Su semántica vive en Checkout.open |
| confirmed | **Eliminar** | El hecho válido se llama posted; no es CTA obligatorio |
| posted | **Conservar como lifecycle de Invoice** | Expresa obligación emitida, freeze, devengo y entrega retail |
| paid | **Conservar como proyección del ledger** | Expresa liquidación completa, no edición/lifecycle |
| cancelled | **Dividir** | Checkout.abandoned si nunca hubo obligación; Invoice.voided si ya estaba posted |

La máquina futura no es:

~~~text
draft → confirmed → paid → cancelled
~~~

Es:

~~~text
Checkout.open
   ├─ no_charge ───────────────────────────▶ Checkout.completed
   ├─ Cobrar ─▶ Invoice.posted/paid ───────▶ Checkout.completed/posted_paid
   ├─ Dejar pendiente ─▶ Invoice.posted/unpaid ─▶ pago ─▶ paid
   ├─ disputa ─▶ hold/dispute ─▶ resolución explícita
   └─ abandon ─────────────────────────────▶ Checkout.abandoned

Invoice.posted/unpaid + exposición continua
  ── void_and_prepare_replacement ──▶ Invoice.voided + replacement.correction_pending
                                             ├─ post/pay ─▶ nueva Invoice
                                             └─ waiver ───▶ replacement_waived
Invoice.posted/unpaid + resultado terminal ── void ──▶ Invoice.voided
Invoice.posted/paid ── refund ──▶ Invoice sigue posted/paid + CreditNote
CreditNote efectiva, sin restock ── reverse ──▶ fully_reversed
~~~

### 4.5 Comandos de dominio

| Comando | Precondiciones | Efectos atómicos | Actor |
| --- | --- | --- | --- |
| record_clinical_quantity_delta | MR open, source/ciclo válido, mutation_key | Entry/ciclo si falta; QuantityEvent; BillingContext en primer ciclo; stock clínico según source | VET responsable/ADMIN |
| reprice_clinical_charge | MR/entry open, versions, nuevo precio/reason | Cierra ciclo a cero; abre ciclo con baseline nuevo; audit/version; sin stock | billing.clinical_charge.reprice |
| close_medical_record | MR open, validación clínica, ownership | Materializa/freeze; MR closed; Appointment completed; crea un Checkout/snapshot/selections; adopta LegacyCheckoutSeed; quizá no_charge | VET responsable/ADMIN |
| update_prescription_selection | Checkout open, source válido, version actual | Persiste decisión; actualiza retail item/totals/version | checkout.adjust_retail + Rx si aplica |
| create_prescription_supplement | Remanente Rx > 0, revisión vigente | Crea Checkout supplement con baseline remanente | billing.rx_dispense |
| update_direct_sale_item | Checkout direct_sale open, owner/version; attestation si Rx externa | Crea/edita/elimina item; revision/fingerprint Rx; attestation append-only; totals/version | Checkout owner + billing.rx_dispense cuando aplica |
| attest_external_prescription | Checkout/item regulado open, revision actual | Crea atestación exacta append-only; no Invoice/stock | billing.rx_dispense |
| apply_discount | Checkout open, política válida; no reduce baseline replacement | Ajuste auditado; totals/version | checkout.apply_discount |
| issue_checkout_estimate | Checkout open/version actual | Snapshot/hash Estimate append-only; sin obligación/acceptance | checkout.estimate.issue |
| pay_checkout | Checkout open, acción disponible, required_inputs completos, pago exacto; baseline íntegro si replacement | Invoice posted; regulatory coverage; StockAllocations/Movements/FulfillmentEvents; Payments con identity D19; evidence; completa posted_paid; supersedes si aplica | payment.create |
| post_checkout_unpaid | Checkout open, acción disponible, crédito/inputs válidos; baseline íntegro si replacement | Invoice posted/unpaid; regulatory coverage; StockAllocations/Movements/FulfillmentEvents; evidence; completa posted_unpaid; supersedes si aplica | invoice.post_unpaid |
| pay_invoice | Invoice posted/unpaid, pago exacto, caja/idempotencia | Payments; paid_at; paid; si hay CollectionCase lo resuelve paid en el mismo commit | payment.create |
| complete_no_charge | Checkout open, total=0, sin pending, kind≠replacement | Completa outcome no_charge | Sistema o actor que resuelve última selección |
| abandon_checkout | Checkout open, abandonable y kind≠replacement | Cierra con razón; sin Invoice/stock | Owner o checkout.abandon |
| open_checkout_dispute | Cargos clínicos y objeción documentada | Crea hold/disputa, owner y SLA; bloquea terminales | checkout.open_dispute |
| resolve_checkout_dispute | Disputa open, outcome/evidencia válida | Acepta, ajusta/condona o postea bajo términos | checkout.resolve_dispute |
| void_invoice | Invoice posted/unpaid, cero Payments, resultado terminal/disposition | Lifecycle voided; resuelve CollectionCase si aplica; sin replacement | invoice.void_terminal |
| void_and_prepare_replacement | Invoice posted/unpaid, cero Payments, exposición continúa, owner/SLA/baseline derivables | Void + dispositions + Checkout replacement + baseline + owner/SLA + lineage + case resolution, un receipt/commit | invoice.replace |
| adjust_replacement_exposure | Replacement correction_pending, baseline/version vigentes, razón/evidencia, resultado > 0 | Adjustment append-only; conserva baseline; recalcula total/version; no puede llevar el remanente a cero | invoice.replace_adjust |
| assign_replacement_owner | Replacement correction_pending, owner nuevo y SLA válidos | Reasigna owner/due_at con audit/version; no cambia baseline/total | invoice.replace_manage |
| waive_replacement_exposure | Replacement correction_pending, permiso/razón/evidencia, importe remanente exacto | ReplacementWaiver append-only; completa replacement_waived; cero Invoice/stock/fulfillment nuevo | invoice.replace_waive |
| refund_invoice | Invoice posted/paid | CreditNote, RefundPayment, restock/discard, ajuste analytics | refund.create |
| reverse_credit_note | CreditNote efectiva sin efecto de stock | RefundReversals; effectiveness fully_reversed; adjustments | refund.reverse |
| resolve_collection_case | Invoice posted/unpaid, case open | withdrawn→collectible; otros resultados usan pay/void/replacement | collection.resolve |
| classify_legacy_settlement | Case open/version, checks/evidence completos | Assessment append-only + repairability materializada | legacy_settlement.classify |
| settle_legacy_partial | Case partial/collectible open, assessment vigente, saldo exacto | 1..N Payments D19; case resolved; proyección paid | legacy_settlement.collect + payment.create |
| return_legacy_overpayment | Case overpaid/returnable open, liability exacto | Adjustment + Return document + return payments D19; cero revenue/stock | legacy_liability.return |
| reverse_legacy_liability_return | Return efectivo completo, version/razón/caja | Un counterevent por línea; liability reabre; cero revenue/stock | legacy_liability.reverse |
| prepare_billing_cutover | Compat instrumentada, organization legacy | Espera in-flight; crea Run; freezing + final watermark | billing.cutover.execute |
| reconcile_billing_cutover | Run freezing, batch/version | Catch-up/rebuild idempotente; hashes/gates; avanza processed watermark | billing.cutover.execute |
| activate_billing_cutover | Run reconciled, processed=final | Revalida bajo locks y cambia organization a future | billing.cutover.execute |

pay_checkout es el camino normal tanto de consultation como direct_sale. No hay direct-pay separado por type. Las diferencias de stock y permisos provienen de source de línea, no de una máquina distinta.

Todos los comandos financieros:

- reciben idempotency key;
- validan organization y actor;
- cumplen el scope, replay y orden global de locks de D14;
- usan version del Checkout para rechazar total obsoleto;
- hacen rollback completo ante fallo de stock, caja, Payment o Invoice;
- escriben audit event con before/after, actor y provenance.

### 4.6 Transiciones prohibidas

| Intento | Razón |
| --- | --- |
| Postear/cobrar Checkout consultation con MR open | Hechos clínicos aún mutables |
| Postear sin ObligationEvidence válido para versión/total | No existe base demostrable de obligación |
| Crear Invoice directamente en draft | Invoice solo existe posted |
| Marcar ready manualmente | Readiness es derivada |
| Editar Checkout completed/abandoned | Terminal |
| Editar InvoiceItem posted | Documento inmutable |
| Cambiar origin/source/source_object | Rompe ownership y stock |
| Pagar parcialmente | Fuera de alcance/contrato p30 |
| Pagar Invoice voided | Documento sin obligación activa |
| Abandonar consultation con deuda clínica | El abandono no borra obligación |
| Abandonar o expirar replacement | El baseline entregado exige resolución; permanece correction_pending/overdue |
| Completar replacement como no_charge | Una condonación requiere waive_replacement_exposure y outcome replacement_waived |
| Eliminar/reducir línea baseline por PATCH, selección o descuento | El hecho prestado/retenido y su lineage son inmutables; solo adjustment autorizado |
| Ajustar el remanente de replacement a cero sin waiver | Ocultaría una condonación dentro de una edición ordinaria |
| Finalizar Checkout con disputa abierta | Primero debe resolverse el hold |
| Void de Invoice con Payment | Usa refund/credit workflow |
| Void standalone con exposición que continuará | Debe usar void_and_prepare_replacement atómico |
| Crear replacement ordinario después de void | Abriría una ventana sin obligación/replacement |
| Restock implícito por void | Disposition y devolución física deben probarlo |
| Revertir CreditNote que produjo restock | V1 exige reconciliación física separada |
| Payment de $0 | No es evento financiero |
| Descontar stock al seleccionar receta | Selección no equivale a entrega |
| Crear StockAllocation mientras Checkout está open | Allocation significa salida de lote committed + StockMovement; fulfillment Rx nace también al post |
| Postear direct_sale Rx con attestation ausente/stale | La evidencia debe cubrir item revision, Presentation y cantidad efectivas |
| Mutar línea Rx y reutilizar su attestation anterior | La revisión/fingerprint cambió; requiere nueva evidencia |
| Marcar StockAllocation ineffective por refund/void | Allocation es historia de lote; efectos posteriores viven en eventos separados |
| Restaurar cap Rx por retorno/restock | V1 conserva fulfillment; solo una política futura puede emitir delta negativo |
| Contar redelivery probada como segunda dispensación | Debe enlazar retorno original y contribuir delta cero hasta su cantidad |
| Reparar overpaid con CreditNote/RefundPayment | El exceso es liability, no revenue ni devolución de items |
| Crear Payment/event key desde raw header + índice | Puede colisionar entre command kinds; usa receipt/kind/index D19 |
| Settle partial con repairability distinta de collectible | El saldo no demuestra obligación válida |
| Iniciar write durante BillingCutoverControl.freezing | Solo replay exacto/read/migración están permitidos |
| Renderizar Checkout como Invoice draft PDF | Usa Estimate no financiero D23 |
| PATCH de ClinicalChargeEntry.unit_price | Repricing solo mediante comando D24 |
| Lockear CreditNote antes de su Invoice | Viola el orden total aunque el comando nazca desde CreditNote |
| Adquirir por primera vez una row de rank menor después de otra mayor | Actualizar una row menor ya poseída sí está permitido; adquirir otra no |
| Consumo clínico repartido en varios lotes | V1 exige un lote explícito representable por MedicalRecordProduct |

## 5. Flujos futuros

### 5.1 Consulta con cargos y pago inmediato

~~~text
VET registra hechos clínicos
→ primer alta crea ClinicalChargeEntry/precio
→ incrementos agregan QuantityEvents al mismo precio
→ MedicalRecord.close
→ close copia ClinicalChargeSnapshots activos
→ recepción resuelve receta
→ preparation_readiness.ready=true
→ actions.pay.allowed=true para el actor
→ Cobrar
   → CommandReceipt + locks + revalidación
   → ObligationEvidence(payment_authorization, versión, total)
   → Invoice.posted
   → StockAllocations + StockMovements + FulfillmentEvents Rx
   → Payment(s) exactos con identity receipt/kind/index
   → Invoice.payment_status=paid
   → Checkout.completed/posted_paid
~~~

El devengo y pago ocurren en la misma transacción. Los consumos clínicos ya movieron stock y no vuelven a moverlo.

### 5.2 Consulta con deuda

~~~text
Checkout estructuralmente listo
→ Dejar pendiente (permiso + política de crédito + aceptación/términos)
→ Invoice.posted/unpaid + stock retail entregado
→ aparece en Cuentas por cobrar
→ pago futuro exacto
→ Invoice paid
~~~

Si no se entregan productos retail, deben quitarse o permanecer el Checkout open. Postear significa que la obligación y la entrega declarada son reales.

### 5.3 Receta total, parcial o rechazada

~~~text
PrescriptionSelection.pending
   ├─ accepted ─────────▶ una o más CheckoutItems solicitadas
   └─ declined ─────────▶ sin retail item

checkout_request_scope = full/partial contra eligible_remaining_at_open
post exitoso crea StockAllocations + PrescriptionFulfillmentEvents
prescription_fulfillment = unfilled/partial/filled desde quantity_delta acumulado
todas resueltas → preparation_readiness puede ser true
~~~

La decisión es opt-in. Un rechazo no modifica la receta y puede coexistir con una dispensación posterior en un Checkout `prescription_supplement`. Al abrirlo se calcula el remanente contra la proyección D20; al postear se revalida el cap bajo lock. Return/refund no restauran cap en v1 y una redelivery probada contribuye cero.

### 5.4 Consulta sin cargos

~~~text
MR close
→ Checkout con total=0 y sin pending
→ completed/no_charge automático
→ no aparece en cola activa
→ no Invoice
→ no Payment
~~~

Si existe receta pendiente, el Checkout permanece open hasta accepted/declined. Al rechazar todo, `actions.complete_no_charge.allowed=true`; un `complete_no_charge` idempotente produce el resultado terminal. Solo close puede completarlo directamente cuando desde su propia transacción no existieron cargos ni decisiones pendientes.

### 5.5 POS

~~~text
Checkout direct_sale open
→ items server-side + version
→ item Rx externo exige attestation para su regulatory revision/fingerprint
→ refresh/reanudación
→ preparation_readiness + actions por actor
   ├─ Cobrar → Invoice posted/paid
   └─ Abandonar/expirar → Checkout abandoned
~~~

No se crean Invoice cancelled para representar volver al carrito ni fallos de preparación.

### 5.6 Corrección

| Momento | Operación |
| --- | --- |
| MedicalRecord open, ciclo de cargo activo | reprice_clinical_charge con version/reason/receipt; no PATCH |
| Checkout open | Editar líneas permitidas |
| Checkout open antes de post | Descargar Estimate versionado, no Invoice PDF |
| Checkout completed/no_charge o abandoned | No editar; crear nuevo Checkout si hay operación nueva |
| Invoice posted/unpaid sin Payments; obligación corregida continúa | void_and_prepare_replacement, un receipt/commit |
| Checkout replacement open | Conservar baseline; ajustar por comando autorizado; resolver en nueva Invoice o waiver, nunca abandonar/no_charge |
| Invoice posted/unpaid con resultado realmente terminal | void standalone con razón terminal/disposition |
| Invoice posted/paid | CreditNote + RefundPayment |
| CreditNote sin restock creada por error | RefundReversal total; restaura capacidad de refund |
| CreditNote que produjo restock | Reversal bloqueado en v1; reconciliación física separada |
| Error clínico tras MedicalRecord.close | Workflow clínico de corrección separado; no PATCH financiero |

### 5.7 Cargo clínico disputado

~~~text
Checkout con cargo clínico + cliente objeta
→ open_checkout_dispute
→ Checkout.open + operational_hold=dispute
→ bandeja/analytics de exposición disputada
   ├─ accepted ─────────────▶ evidencia → pay o post_unpaid
   ├─ adjusted_or_waived ──▶ ajuste autorizado → pay/no_charge (no replacement)
   └─ enforced_under_terms ▶ Invoice.posted/unpaid + CollectionCase.open

CollectionCase.open
   ├─ customer_withdrew ─▶ collectible
   ├─ paid ──────────────▶ Payment + resolved/paid
   ├─ adjusted ──────────▶ atomic replacement
   └─ waiver ────────────▶ terminal void
~~~

No se usa `abandoned`; tampoco se reconoce revenue/AR antes de una Invoice válida. La disputa conserva exposición operacional, owner y SLA.

### 5.8 Void y reemplazo

~~~text
Invoice.posted/unpaid errónea, sin Payments
→ void_and_prepare_replacement
   → lock/validar dispositions + baseline + owner/SLA
   → Invoice.voided + Checkout.replacement.correction_pending en un commit
→ baseline prestado/retenido queda read-only; extras y pretensión económica solo por comandos autorizados
   ├─ post/pay → nueva Invoice.supersedes_invoice = original
   └─ waiver explícito → completed/replacement_waived, sin Invoice nueva

abandon / expiry / complete_no_charge / remove baseline → rechazados
~~~

`goods_retained` reutiliza allocations, regulatory coverage y fulfillment probados sin descontar ni contar otra vez. Un retorno probado genera su evento físico; una redelivery exige nueva salida, pero contribuye cero al cap solo hasta la cantidad devuelta y ligada. Refund/reversal monetario no altera fulfillment. El vencimiento del SLA solo cambia la proyección a `correction_overdue` y escala: no cierra ni oculta la exposición.

### 5.9 Cierre de consulta migrada abierta

~~~text
Backfill: draft + MR open → LegacyCheckoutSeed (no Checkout)
→ MR sigue recibiendo ClinicalChargeEntry/QuantityEvents
→ close [locks + materialización]
→ crear un solo Checkout primary
→ clínica reconstruida desde entries activos
→ candidatos legacy quedan como evidencia; Rx vuelve pending
→ seed adopted en el mismo commit
~~~

Un draft appointment-only vacío puede abandonarse como artefacto técnico; cualquier item/Payment/anchor contradictorio va a quarantine.

### 5.10 Reparación legacy

~~~text
partial:  assessment collectible vigente
          → Payments históricos + Payment exacto nuevo = total
          → LegacySettlementCase resolved → read model paid

overpaid: assessment returnable + Payments históricos
          → overpayment_to_liability adjustment
          → LegacyLiabilityReturn + ReturnPayments exactos
          → applied=total, liability=0, cero revenue/stock adjustment
          → si hubo error: ReturnReversals reabren liability, nunca UPDATE
~~~

### 5.11 Atestación externa POS

~~~text
agregar/mutar CheckoutItem requires_prescription
→ lock Checkout/item/Presentation
→ billing.rx_dispense + datos del prescriptor
→ incrementa regulatory revision + fingerprint
→ ExternalPrescriptionAttestation append-only
→ post relee/lockea evidencia exacta
→ InvoiceItemExternalPrescriptionEvidence + entrega/fulfillment
~~~

Cambiar cantidad/presentación o eliminar/reagregar vuelve stale la evidencia previa. Abandon, void y refund la conservan. `goods_retained` referencia la cobertura original; una entrega física nueva exige otra atestación.

### 5.12 Cutover por organización

~~~text
release instrumentada → backfill baseline
→ prepare: lock exclusivo Control → freezing + final watermark; commit
→ reconcile: catch-up/rebuild idempotente de mutations pendientes
→ reconcile datos/ledger/stock/evidencia
→ activate: processed == final y cero unknown bajo lock
→ future; writers legacy quedan cerrados
~~~

Un flag no cambia antes de esa reconciliación. Mientras freezing, nuevos comandos no producen receipts ni efectos; replays completos siguen siendo legibles.

## 6. Contrato conceptual de API

La forma exacta puede variar, pero la API debe expresar comandos, no escritura libre de estados.

### Lectura

- GET checkouts: bandeja open, filtros origin/kind/owner/readiness/age y `correction_pending|correction_overdue`.
- GET checkouts/{id}: items, selections, estado de cobertura Rx externa sin PII, totals, `preparation_readiness`, `actions`, dispute, version y, para replacement, baseline/lineage/owner/SLA/resolution.
- GET checkout-estimates/{id}/pdf: render del snapshot no financiero de D23.
- GET invoices: posted/unpaid, paid y voided.
- GET invoices/{id}: snapshot inmutable, Payments, regulatory coverage, fulfillment, credits, CollectionCase y audit.
- GET legacy-settlements: kind, repairability, assessment y resolución; nunca mezclada con la colección normal.

### Mutaciones de Checkout

- Los endpoints clínicos existentes de servicios/productos envían `mutation_key` y llaman internamente `record_clinical_quantity_delta`; no se expone un endpoint financiero genérico ni precio libre.
- POST medical-records/{id}/clinical-charges/{entry}/reprice.
- POST checkouts/direct-sale.
- PATCH checkouts/{id}/items/{item}: solo campos permitidos por source.
- POST checkouts/{id}/items/{item}/external-prescription-attestations.
- PUT checkouts/{id}/prescription-selections/{selection}.
- POST medical-records/{id}/prescription-supplements.
- POST checkouts/{id}/discounts.
- POST checkouts/{id}/estimates.
- POST checkouts/{id}/pay.
- POST checkouts/{id}/post-unpaid.
- POST checkouts/{id}/complete-no-charge.
- POST checkouts/{id}/abandon.
- POST checkouts/{id}/disputes.
- POST checkouts/{id}/disputes/{dispute}/resolve.
- POST checkouts/{id}/replacement-adjustments.
- POST checkouts/{id}/replacement-assignment.
- POST checkouts/{id}/waive-replacement.

### Mutaciones financieras

- POST invoices/{id}/pay.
- POST invoices/{id}/void.
- POST invoices/{id}/void-and-prepare-replacement.
- POST invoices/{id}/collection-case/resolve.
- POST invoices/{id}/refund.
- POST credit-notes/{id}/reverse.
- POST legacy-settlements/{id}/settle-partial.
- POST legacy-settlements/{id}/classify.
- POST legacy-settlements/{id}/return-overpayment.
- POST legacy-liability-returns/{id}/reverse.
- POST admin/organizations/{id}/billing-cutovers/prepare.
- POST admin/billing-cutovers/{run}/reconcile.
- POST admin/billing-cutovers/{run}/activate.

No existen:

- POST genérico de Invoice para frontend ordinario;
- PATCH de Invoice.status, origin, customer o links;
- PATCH de InvoiceItem;
- PATCH/delete de una línea `required_replacement_baseline`;
- PDF de Invoice para un Checkout open;
- POST ordinario de replacement después de void;
- POST abandon/complete-no-charge/expiry válido para `kind=replacement`;
- confirm como comando separado del caso de uso;
- direct-pay específico de direct_sale.

Responses de Checkout incluyen total autoritativo, version y acciones con `blockers/required_inputs`. Mutaciones exigen `expected_version` o `If-Match`. Todo comando terminal exige `Idempotency-Key`; su hash usa el schema canónico versionado de D14. Cobrar con versión vieja responde conflicto y nunca usa un total desactualizado.

Contrato de errores:

| HTTP/code | Significado |
| --- | --- |
| 409 `stale_version` | La key es nueva pero `expected_version` ya no coincide; incluye versión/readiness/actions actuales. |
| 409 `idempotency_key_reused` | Misma key/scope con target o payload distinto. |
| 409 `state_conflict` | Otra key ya ejecutó una transición terminal incompatible. |
| 409 `stock_reversal_requires_manual_reconciliation` | CreditNote tuvo restock y v1 no puede revertirla automáticamente. |
| 409 `billing_cutover_in_progress` | La organización está freezing; no se admiten comandos nuevos. |
| 409 `legacy_assessment_stale` | Cambió una fuente cubierta por el assessment; no se cobra/promueve. |
| 409 `replacement_resolution_required` | El replacement no admite abandon, expiry o no_charge; debe postearse o recibir waiver autorizado. |
| 409 `replacement_baseline_conflict` | Baseline/hash/lineage cambió o el comando intentó eliminar/reducir un hecho protegido. |
| 422 `action_blocked` | El comando no satisface blockers actuales; devuelve lista por acción. |
| 422 `required_input_missing` | La acción es intentable, pero el payload no aportó un input declarado. |
| 422 `prescription_required` | Falta atestación externa exacta o quedó stale para la línea regulada. |
| 410 `idempotency_result_expired` | Existe tombstone válido: no se repiten efectos, pero expiró el envelope operativo. |
| 403 | El actor no tiene permiso/visibilidad; se evalúa antes de revelar un receipt. |

Durante la ventana de retención, un replay idéntico devuelve el mismo status/body aunque Checkout/Invoice ya sean terminales. Tras expirar un envelope operativo, el tombstone devuelve 410 y jamás reejecuta. No se vuelve a evaluar versión, stock o lifecycle después de autenticar/autorizar el acceso al target.

## 7. Frontend futuro

### Consulta

- El CTA clínico dice **Finalizar consulta**.
- Al cerrar muestra el resultado: “Checkout enviado a Cobros”, “Sin cargo” o blockers.
- No afirma que creó factura.

### Cobros

Dos vistas conceptuales:

1. **Por preparar:** Checkout open, owner, edad, total actual, blockers.
2. **Pendientes de pago:** Invoice posted/unpaid, posted_at, due_at/razón.

Y tres colas excepcionales que no se mezclan con las anteriores:

3. **Disputas:** CheckoutDispute pre-post y CollectionCase post, owner, SLA, importe y acciones permitidas.
4. **Reconciliación legacy:** partial/overpaid, ledger original y resolución administrativa.
5. **Correcciones pendientes:** Checkout replacement, Invoice original, baseline protegido, owner, SLA/overdue, total corregido y únicos terminales disponibles.

Detalle de Checkout:

- cargos clínicos read-only;
- acción ADMIN de repricing clínico existe solo antes de close y solicita reason/version; no es edición inline de Checkout;
- consumos included visibles solo como contexto, no total;
- receta inicialmente sin selección;
- aceptación/declinación explícita;
- retail editable;
- total backend;
- preparación estructural separada de blockers y required_inputs de cada CTA;
- Cobrar como CTA primario;
- Dejar pendiente solo con permiso;
- Abrir/Resolver disputa según capacidad;
- no status draft/confirmed.
- “Descargar estimado” muestra version/generado y nunca usa copy de factura.
- en replacement, baseline prestado/retenido es read-only y se distingue de extras editables; no aparecen Abandonar ni Sin cargo;
- ajuste de exposición, reasignación y waiver son CTAs separados por permiso; waiver exige razón, evidencia y confirmación explícita del importe;
- vencimiento muestra `Corrección vencida`, escala y conserva el caso en la cola hasta nueva Invoice o waiver.

### POS

- carrito identificado y recuperable;
- modal regulatorio obligatorio al agregar/mutar presentación Rx externa; muestra `vigente/stale` sin exponer PII a roles no autorizados;
- indicador “Guardado”/conflicto de versión;
- volver no crea cancelled financiero;
- intento fallido conserva Checkout e idempotencia;
- abandonar es explícito solo para direct_sale primario; un replacement POS nunca muestra abandono/expiry;
- cobro comparte el mismo Payment editor.
- cambiar cantidad/presentación Rx solicita nueva atestación; remover/reagregar no recicla la anterior.

### Billing

Estados mostrados:

- Pendiente de pago;
- Pendiente disputada;
- Pagada;
- Anulada.
- Corrección pendiente / Corrección vencida, como proyección del Checkout replacement y no como Invoice.status.

La UI muestra “Emitida” para `posted`, nunca un estado API `issued` ni “Confirmada”. Una Invoice corregible ofrece **Anular y preparar corrección** como una sola acción; una anulada solo enlaza el replacement ya creado, no ofrece crearlo secuencialmente. Ese replacement permanece visible con owner/SLA hasta que el enlace muestre la nueva Invoice o un waiver; nunca se presenta como carrito abandonable. Refund y reversal se presentan como eventos adicionales de la Invoice paid, no como cambio a unpaid. Reconciliación legacy muestra kind y repairability separados: el CTA cobrar no existe salvo `collectible`; return/reversal tienen permisos y trazas propias.

## 8. Analytics futuro

| Métrica | Fuente |
| --- | --- |
| Consultas cerradas | MedicalRecord.closed_at |
| Checkouts enviados/preparados | Checkout.created_at/origin |
| Tiempo a readiness | Derivado de close/first_ready_at si se decide persistir |
| No charge | Checkout.completed_at + completion_kind=no_charge |
| Abandono POS | Checkout.abandoned_at/reason |
| Revenue accrual bruto | Invoice.posted_at, lifecycle posted/voided según snapshot histórico |
| Revenue accrual neto | Postings − void adjustments − CreditNotes efectivas; RefundReversal restaura mediante contra-adjustment en la fecha del reverso |
| Accounts receivable normal | Invoice posted + payment_status unpaid, separando collection_status collectible/disputed |
| Exposición disputada sin Invoice | CheckoutDispute open, fuera de revenue y AR |
| Corrección pendiente/vencida | Checkout replacement open + baseline, owner y correction_due_at; exposición operacional fuera de AR |
| Exposición de replacement condonada | ReplacementWaiver.occurred_at, reason y amount; separada de no_charge y del adjustment de void |
| Collection dispute | CollectionCase open/resolved; AR disputed vuelve collectible, paid o voided según evento |
| Legacy receivables/liability | effective_applied, repairability y open_customer_liability de D15/D22, fuera de buckets normales hasta reparación |
| Legacy liability returned | ReturnPayments − ReturnReversals por occurred_at; salida neta de caja/pasivo, revenue=0 y stock=0 |
| Revenue paid | Invoice.paid_at, neto de CreditNotes efectivas y RefundReversals |
| Prescription acceptance | PrescriptionSelection decision |
| Prescription fulfillment | FulfillmentEvents: dispensed gross, physical returns, neutral redeliveries y cap contribution separados |
| External Rx compliance | Attestations/coverage válidas por posted item; PII excluida de métricas |
| Provenance de precio/impuesto | ClinicalChargeEntry/QuantityEvents/Snapshot/BillingContext + writer provenance legacy |
| Cutover integrity | baseline/final/processed watermark, mutation lag y reconciliation result por organization |
| Estimate usage | Audit de generación por Checkout/version; nunca revenue, AR ni aceptación |

No se interpreta Checkout total como revenue, incluido `correction_pending`; su baseline mide exposición operacional y no AR. No se usa MedicalRecord.close como proxy de devengo. `first_ready_at` es analítica operacional, nunca autoridad para postear. Los adjustments son append-only, incluyen `schema_version`, evento causal y fecha del void/credit/reversal; no reescriben snapshots diarios ya publicados. El corte legacy/new queda versionado y reconciliable por organización/fecha.

## 9. Fase 4 — Migración

### 9.1 Principios

1. Ningún mapeo masivo se hace solo por el string de status.
2. La migración no ejecuta servicios que creen movimientos de stock o Payments.
3. No se borran legacy Invoice ni audit logs durante el cutover.
4. Anchors históricos se preservan.
5. Cada transformación es idempotente y deja legacy identifier.
6. Casos ambiguos van a cuarentena; no se “corrigen” automáticamente.
7. Revenue, Payments, refunds y stock se reconcilian por organización.
8. Backfill es una fotografía; solo freeze + final watermark + catch-up de D21 autoriza cutover.
9. At attestations, financial event IDs y fulfillment se preservan/reconcilian como contratos propios, no como atributos de status.

### 9.2 Mapeo principal

~~~text
draft      → LegacyCheckoutSeed / Checkout.open / completed-no_charge / abandoned, según MR/origen/evidencia
confirmed  → Invoice.posted + payment_status=unpaid, si es válido
paid       → Invoice.posted + payment_status=paid
cancelled  → Checkout.abandoned O Invoice.voided, según estado anterior
partial    → LegacySettlementCase.partial/unassessed + eventos existentes inmutables; solo assessment collectible permite cobro
overpaid   → LegacySettlementCase.overpaid/unassessed + eventos existentes inmutables; solo assessment returnable permite devolución
~~~

paid conserva paid; cambia la dimensión en que vive. cancelled no genera automáticamente otro documento.

### 9.3 draft

| Caso actual | Destino | Tratamiento |
| --- | --- | --- |
| consultation + MR open, source/precio deterministas | LegacyCheckoutSeed + ClinicalChargeEntry baseline | No Checkout primario; close reconstruye desde entries y adopta seed |
| consultation + MR open, source/precio divergentes | Quarantine | No inventar entry ni precio; bloquea cutover de esa fila |
| consultation + MR closed + total>0 | Checkout.open | Cargos clínicos read-only; crear selections pending no resueltas |
| consultation + MR closed + total=0 + receta pendiente | Checkout.open | Resolver aceptación/rechazo |
| consultation + MR closed + total=0 + sin receta pendiente | Checkout.completed/no_charge | No crear Invoice futura |
| direct_sale draft reciente/válido | Checkout.open | Owner/version/expiry; reanudable |
| direct_sale draft con ExternalPrescriptionAttestation exacta | Checkout.open + attestation migrada | Enlazar item/revision/fingerprint solo si Presentation/qty reconcilian |
| direct_sale draft con attestation divergente | Regulatory quarantine | Conservar evidencia; no autoriza post ni se elimina |
| direct_sale draft antiguo | Checkout.open flagged stale o abandoned tras revisión/política | No inferir abandono solo por edad en primera pasada |
| appointment-only, aún puede vincular MR | LegacyCheckoutSeed pending | No Checkout; espera vínculo/close |
| appointment-only, done/cancelled, vacío y sin efectos | Seed abandoned/technical_appointment_draft | No Invoice ni no_charge inferido |
| appointment-only con items/Payment/stock/anchor | Quarantine | No inferir consultation ni direct_sale |
| draft con Payment o anchors terminales | Cuarentena | Viola invariantes actuales |

La legacy Invoice draft no se convierte en Invoice posted. Para MR closed/POS determinista sus items pueden copiarse a CheckoutItem. Para MR open son solo evidencia del seed: las líneas clínicas futuras salen de ClinicalChargeEntry baseline + nuevos QuantityEvents. El row legacy se conserva oculto con mapping y no se reutiliza como documento financiero futuro.

El `unit_price`, descuento, subtotal y tax del Invoice/InvoiceItem legacy son la evidencia preferente de valor. No se reconsulta el catálogo actual. Si una fuente clínica no tiene línea legacy determinista ni otra evidencia de precio, va a cuarentena; no se inventa un snapshot.

Para MR open determinista, el backfill crea un ClinicalChargeEntry activo con `price_provenance=legacy_invoice_item` y un único QuantityEvent `migration_baseline`. Quantity/price deben reconciliar contra la fuente clínica; los incrementos posteriores usan nuevos mutation keys y conservan ese primer precio hasta close.

Cada Invoice draft se clasifica con `tax_writer_provenance=clinical_charge|close|included_side_effect|appointment_signal|unknown`, tasa y timestamp reales. Solo los casos probados alimentan `MedicalRecordBillingContext(provenance=legacy_draft)`; ninguno se renombra retroactivamente `first_billable`.

El PDF “BORRADOR” legacy no se convierte en documento financiero futuro. Si el draft produce Checkout, su sucesor es el Estimate D23; downloads/archivos previos conservan su identidad legacy y watermark, pero no se reemiten como Invoice nueva.

### 9.4 confirmed

Mapeo automático solo si:

- total > 0;
- suma de Payments = 0;
- confirmed_at existe;
- consultation tiene MedicalRecord closed;
- links tenant/customer coherentes;
- stock settlement esperado es reconciliable;
- no hay mutaciones posteriores divergentes.

Destino:

~~~text
Invoice.document_lifecycle = posted
Invoice.payment_status = unpaid
posted_at = confirmed_at
Checkout = completed/posted_unpaid
obligation_provenance = legacy_confirmed
acceptance_evidence = not_captured
~~~

Casos a cuarentena:

- confirmed con MR open;
- total=0;
- Payment parcial → LegacySettlementCase.partial/unassessed; no normal posted mapping hasta assessment;
- Payment total pero status incorrecto;
- stock/provenance inconsistente;
- links clínicos contradictorios.

No se debe llamar posted a una confirmed inválida solo para completar el backfill.

`legacy_confirmed` explica el origen del anchor; no equivale a aceptación moderna. No se inventan parte aceptante, actor ni canal. Si una política requiere evidencia fuerte para cobrar judicial/operativamente una deuda, esas filas se mantienen en vista legacy o cuarentena hasta revisión.

### 9.5 paid

Mapeo automático si:

- suma de Payments = total;
- paid_at existe;
- confirmed_at existe o puede justificarse por provenance legacy;
- no existe sobrepago;
- refunds/credit notes están reconciliados.
- cualquier ExternalPrescriptionAttestation requerida por retail Rx está preservada y enlazada al InvoiceItem exacto.

Destino:

~~~text
document_lifecycle = posted
payment_status = paid
posted_at = confirmed_at
paid_at = paid_at original
Checkout = completed/posted_paid
obligation_provenance = legacy_paid
acceptance_evidence = legacy_payment_implied
~~~

Payments, CashSession, idempotency, CreditNote, RefundPayment y MetricAdjustment conservan sus IDs y fechas. La migración no crea un Payment nuevo salvo que exista un backfill legacy previamente definido por ADR p27 y auditado aparte. `legacy_payment_implied` solo prueba que existió liquidación; tampoco fabrica actor/canal de aceptación.

Si `0 < Σ Payments < total` o `Σ Payments > total`, esta sección no aplica: se crea `LegacySettlementCase` y la Invoice permanece read-only fuera de la API normal hasta resolución. El estado legacy nominal no prevalece sobre la matemática del ledger.

#### Reparación posterior al backfill

El backfill nunca crea Payment, LegacyPaymentApplicationAdjustment ni LegacyLiabilityReturn. Después del cutover administrativo:

| Case/repairability | Comando | Efectos nuevos | Promoción |
| --- | --- | --- | --- |
| partial/collectible | settle_legacy_partial | Payment(s) D19 exactos + caja + evidence + receipt | paid normal si effective_applied=total |
| partial no collectible | ninguno monetario | assessment/quarantine o resolución externa | nunca paid normal por reparación automática |
| overpaid/returnable | return_legacy_overpayment | adjustment + ReturnPayment(s) D19 + caja + receipt | paid normal si applied=total y liability=0 |
| liability return erróneo | reverse_legacy_liability_return | counterevents por todas las líneas efectivas | liability reabre; documento original permanece |
| resolución externa histórica | document_legacy_external_resolution | evidencia/audit, sin caja/revenue/stock | permanece legacy-resolved |

Los Payments y snapshots previos conservan IDs/fechas. La devolución de liability no se representa como CreditNote/RefundPayment y no cambia revenue ni stock.

### 9.6 cancelled

La fuente primaria para saber qué fue cancelado es InvoiceAuditLog.previous_status; confirmed_at funciona como evidencia secundaria.

| Origen real de cancelled | Destino | ¿Genera otro documento? |
| --- | --- | --- |
| draft → cancelled | Checkout.abandoned, reason legacy_cancelled | No |
| confirmed → cancelled, sin Payment | Invoice.voided + Checkout.completed/posted_unpaid histórico | No; se conserva la misma identidad documental normalizada |
| cancelled con Payment | Cuarentena | No automático; posible corrupción |
| origen indeterminado | Cuarentena | No |

Para confirmed → cancelled:

- posted_at = confirmed_at;
- voided_at = cancelled_at;
- stock ya fue revertido por el sistema legacy, por lo que la migración **no mueve stock**;
- el audit log se conserva;
- no se crea CreditNote porque nunca hubo Payment.

Una Invoice paid con devolución no es cancelled: permanece posted/paid y conserva CreditNote/RefundPayment. Si fiscalidad exige un documento adicional para void no pagado, debe decidirse antes de implementar; esta propuesta de dominio no lo genera.

No se infiere `supersedes` entre documentos históricos solo por cercanía temporal, mismo cliente o monto. Un lineage legacy se migra únicamente con vínculo/audit inequívoco; de lo contrario queda ausente y documentado.

### 9.7 Backfill de source por línea

| Evidencia legacy | source candidato | Confianza |
| --- | --- | --- |
| direct_sale + presentation | direct_sale_product | Alta |
| direct_sale + service | direct_sale_service | Alta |
| consultation + dispensed_from_prescription_item | prescription_retail | Alta |
| consultation + service | clinical_service | Media: falta FK al MedicalRecordService concreto |
| consultation + presentation sin dispensed FK | clinical_consumable_charge | Media: requiere match con MedicalRecordProduct |
| presentation colisionada entre consumo y receta | Ambiguo | Cuarentena/manual |
| item sin source compatible con origin | Ambiguo | Cuarentena/manual |

El backfill debe guardar:

- legacy_invoice_item_id;
- source elegido;
- source_object si fue posible;
- price/tax snapshot y su evidencia legacy;
- stock_behavior y allocation/movement si fue demostrable;
- ExternalPrescriptionAttestation y coverage exacta por presentation/quantity cuando aplique;
- PrescriptionFulfillmentEvent/projection reconstruida sin inferir reversa desde refund;
- confidence;
- método/regla de matching;
- reviewed_by/reviewed_at para casos manuales.

No se utiliza una inferencia de confianza media para decidir movimientos de stock históricos, restock, acceptance ni supersesión.

### 9.8 Anchors y analytics

| Legacy | Futuro |
| --- | --- |
| confirmed_at válido | posted_at |
| paid_at | paid_at |
| cancelled_at desde draft | Checkout.abandoned_at |
| cancelled_at desde confirmed | Invoice.voided_at |
| created_at draft POS | Checkout.created_at |

Los snapshots congelados no se reescriben. Se establece una versión semántica de métricas en la fecha de cutover:

- historia legacy mantiene “confirmed” según reglas antiguas;
- datos nuevos usan posted;
- reportes de comparación explican la frontera;
- casos en cuarentena no desaparecen: se reportan como legacy_unresolved.

Revenue_paid debe reconciliar exactamente. Revenue_accrual puede exponer diferencias de confirmed inválidas; esas diferencias son hallazgo, no razón para legitimar los datos.

### 9.9 Etapas

#### M0 — Aceptar decisiones

Producto aprueba D1–D25, especialmente crédito, devengo, $0, precio/repricing, evidencia Rx externa, fulfillment tras correcciones, estimate, replacement atómico y continuidad operacional protegida posterior al void. Para el lanzamiento greenfield, repairability/cutover legacy quedan fuera de alcance conforme a la resolución de ADR-R59/R61/R62; su reactivación exige una ADR o addendum previo al import/dual-write.

#### M1 — Censo read-only

Por organización:

- counts por status/type/MR status;
- total y remaining balance;
- anchors;
- Payments/refunds;
- raw idempotency keys, child derivation y posibles colisiones cross-command;
- antigüedad de drafts;
- uso/descargas del PDF draft y consumidor frontend;
- origen de cancelled;
- source-confidence de items;
- stock movement reconciliation;
- uso de auto_create_invoice_on_done;
- diferencias entre precios/impuesto legacy y catálogo actual;
- CreditNotes con restock y RefundReversal;
- partial/overpaid por suma real de Payments;
- drafts appointment-only y posibilidad real de vínculo posterior a MR;
- fuentes clínicas únicas con qty InvoiceItem vs qty actual y precio inicial;
- provenance del writer/tax_rate de cada draft, incluidos included/close/signal;
- evidencia de aceptación y posibles replacement históricos;
- ExternalPrescriptionAttestation por estado, Presentation/qty, InvoiceItem y divergencias;
- fulfillment Rx frente a void/refund/restock/replacement;
- inventario completo de writers legacy a instrumentar con LegacyBillingMutation;
- relaciones/carreras Appointment↔MedicalRecord relevantes al cutover.

#### M2 — Schema aditivo

Introducir ClinicalChargeEntry/QuantityEvent/Snapshot/BillingContext, Checkout/CheckoutItem/CheckoutEstimate, campos y constraints de replacement baseline/owner/SLA, ReplacementWaiver, PrescriptionRevision/Selection/FulfillmentEvent/DispositionEvent, ExternalPrescriptionAttestation futuro + coverage, LegacyCheckoutSeed, StockAllocation, ObligationEvidence, CheckoutDispute/CollectionCase, BillingCutoverControl/BillingCutoverRun/LegacyBillingMutation, CommandReceipt y child financial identity, LegacySettlementCase/Assessment, LegacyPaymentApplicationAdjustment, LegacyLiabilityReturn/ReturnPayment/Reversal, lineage de reemplazo, nuevos campos de Invoice y mappings legacy sin retirar status/rutas actuales. Publicar simultáneamente la enmienda 1.1 del contrato financiero D19.

#### M3 — Backfill idempotente

Después de desplegar e inspeccionar la instrumentación de todos los writers, crear objetos futuros con migration_run_id y baseline watermark. Casos ambiguos quedan pendientes. Ejecutar en dry-run y por lotes mientras `mode=legacy`; cada mutation posterior al baseline queda disponible para catch-up.

#### M4 — Compatibilidad

- adaptador de lectura para URLs/IDs/PDF legacy;
- BillingCutoverControl por organización; el feature flag solo proyecta su mode, no lo sustituye;
- cada writer legacy adquiere coordination lock y emite LegacyBillingMutation en su commit;
- antes de future, únicamente legacy es autoritativo; comandos futuros nuevos están cerrados;
- consumidores analytics pueden comparar old/new;
- no dual-write financiero improvisado: cada comando tiene un writer autoritativo.

#### M5 — Cutover

Ejecutar la saga `prepare_billing_cutover → reconcile_billing_cutover → activate_billing_cutover` por cohorte conforme D21. Prepare fija freezing/final watermark; reconcile hace catch-up/rebuild en batches; activate revalida y solo entonces fija future. En future bloquear:

- creación genérica de Invoice;
- PATCH de status/type/links;
- edición de InvoiceItem;
- confirm/direct-pay legacy;
- signal auto_create_invoice_on_done.

También se bloquean writers no obvios de dispensación/attestation/refund y cualquier endpoint genérico censado en M1. El gate exige `processed_watermark == final_watermark`; una mutation nueva es imposible mientras freezing.

#### M6 — Ratchet y limpieza

Tras reconciliación:

- constraints fuertes;
- retirar campos/rutas/toggle legacy;
- retirar PDF draft como operación futura; conservar archivo legacy y habilitar Checkout Estimate;
- mantener el guard de BillingCutoverControl aunque se retire la UI legacy;
- archivar adaptadores;
- actualizar módulos, ADRs y runbooks;
- mantener mappings/audit históricos.

### 9.10 Gates de aceptación de migración

1. Cero Payments perdidos o duplicados.
2. Para cada paid válido: suma de Payments = total.
3. Conteo y monto de CreditNote/RefundPayment idénticos.
4. Cero StockMovement creado por el backfill.
5. Saldos de inventario antes/después idénticos.
6. Totales históricos por organización/fecha reconciliados.
7. confirmed inválidos contabilizados en cuarentena, no silenciados.
8. Cada draft tiene destino o razón pendiente.
9. Cada cancelled tiene origen probado o cuarentena.
10. No_charge no crea Invoice/Payment.
11. Nuevos permisos probados por rol/acción.
12. Idempotencia y concurrencia probadas en pay/post/void.
13. Suite legacy verde durante compatibilidad y suite futura completa.
14. Rollback de feature flag no pierde operaciones creadas por el modelo nuevo.
15. Cero diferencias de precio/tax en cargos legacy deterministas; casos sin evidencia están censados en cuarentena.
16. Toda Invoice migrada declara obligation/acceptance provenance sin actor o canal inventado.
17. Cada partial/overpaid tiene LegacySettlementCase consultable; el conteo puede ser cero, pero está probado.
18. Normal AR/revenue excluye quarantine; legacy_receivables y legacy_customer_liability reconcilian sus montos.
19. Todo RefundReversal asociado a restock está censado y reconciliado; el backfill no mueve stock.
20. CreditNotes totalmente revertidas no consumen capacidad de refund en el modelo nuevo.
21. Cero línea clínica puede activar restock automático sin provenance retail demostrada.
22. Ningún lineage de replacement se infiere sin evidencia durable.
23. Replay terminal devuelve IDs/respuesta originales y no duplica Invoice, Payment, stock ni audit.
24. Tests PostgreSQL close-vs-assign/status prueban orden Appointment → MedicalRecord y retry controlado.
25. La activación futura bloquea cualquier writer de Invoice que no adjunte ObligationEvidence fuerte; la excepción legacy está separada y read-only.
26. Cada fuente clínica determinista tiene como máximo un ciclo activo y su cantidad coincide con QuantityEvents idempotentes.
27. Incrementar una fuente después de cambiar catálogo conserva el primer precio del ciclo; decrement/delete/reopen cumplen D11.
28. Cada draft + MR open produce LegacyCheckoutSeed o quarantine, nunca Checkout primario anticipado.
29. Close de MR migrado crea exactamente un primary y marca seed adopted; candidates Rx continúan pending.
30. Todo appointment-only draft tiene pending/abandoned/quarantine probado; ninguno desaparece ni se infiere como venta.
31. Fallo en cualquier paso de void_and_prepare_replacement conserva Invoice posted; replay devuelve void + Checkout IDs originales.
32. settle_legacy_partial reconcilia Payments/CashSession/revenue_paid nuevo sin modificar eventos históricos.
33. return_legacy_overpayment deja applied=total/liability=0 y cero CreditNote, RefundPayment, revenue o stock adjustment.
34. Un checker de lock registry prueba rank único por modelo; tests refund-vs-reverse y replacement-vs-pay siguen `(rank, pk)`.
35. Cero StockAllocation existe para Checkout open; cada allocation committed referencia su StockMovement.
36. Action responses distinguen blockers de required_inputs y pay puede capturar evidence atómicamente.
37. Tax writer provenance clasifica first charge, close, included, appointment signal y unknown sin renombrar legacy.
38. CommandReceipt prueba canonical schema version, defaults, Decimal y orden semántico equivalente, además de claim concurrente.
39. Toda Invoice con collection_status disputed tiene CollectionCase open; paid/void/replacement lo resuelve atómicamente.
40. Tests de ACL/tenant, allowlist y retention/tombstone cubren Receipt, Evidence y disputes.
41. Cada ExternalPrescriptionAttestation legacy tiene coverage exacta o regulatory quarantine; ninguna se pierde por cancelled/refund.
42. Toda línea direct_sale Rx futura exige revision/fingerprint vigente y post la revalida bajo lock.
43. Mismo raw key en pay_checkout/pay_invoice produce receipts y event child keys distintos; replay conserva índices.
44. Financial-event-model-contract 1.1 pasa contract tests para Payment, LiabilityReturnPayment y Reversal.
45. Fulfillment Rx se cuenta una vez en goods_retained, retorno, refund, reversal y redelivery; stock/caja se reconcilian aparte.
46. V1 jamás crea delta Rx negativo por return/restock; redelivery neutral no excede retorno probado.
47. Todos los writers legacy censados emiten LegacyBillingMutation en la misma transacción antes del primer backfill.
48. Cutover espera writers in-flight, captura final watermark y no activa future hasta processed==final + reconciliación verde.
49. Todo LegacySettlementCase tiene repairability/assessment; solo collectible expone settle y revalida hashes.
50. CheckoutEstimate es único/inmutable por version, carece de número/anchors fiscales y el endpoint Invoice PDF rechaza objetos futuros no posted.
51. reprice_clinical_charge prueba ACL, version, idempotencia, close/open de ciclos y rollback sin stock.
52. Lock checker distingue primera adquisición de re-update y registra BillingCutoverControl, attestations y liability returns.
53. Retention `regulated_rx` es al menos cinco años, legal hold impide purga y toda lectura PII queda tenant-scoped/auditada.
54. Todo replacement futuro nace en el mismo commit del void con owner, correction_due_at, baseline no vacío y hash reproducible.
55. Abandon, expiry, complete_no_charge, descuento y PATCH/delete no pueden eliminar ni terminalizar un baseline replacement.
56. Cada replacement termina exactamente una vez mediante Invoice superseding XOR ReplacementWaiver; no existe un tercer terminal genérico.
57. Un replacement vencido permanece visible como correction_overdue y conserva owner/baseline hasta resolución.
58. ReplacementWaiver exige permiso separado, importe remanente exacto, razón/evidencia, Receipt y cero efectos de stock/fulfillment.
59. Carreras post/pay vs waiver/adjust/expiry producen un único resultado y replay estable, sin exposición invisible.

### 9.11 Rollback

Rollback no significa borrar Checkouts/Invoices nuevos. Significa:

- desactivar UI/comandos nuevos para una organización;
- volver temporalmente al adaptador **de lectura** legacy;
- conservar mapping y eventos ya emitidos;
- mantener writers legacy cerrados si ya existe cualquier evento futuro; nunca reactivarlos por simple flag;
- reconciliar antes de reintentar cutover.

Una Invoice posted/paid creada por el modelo futuro nunca vuelve a draft por rollback técnico.

## 10. Impacto de implementación

### Backend

- modelos Checkout, CheckoutItem, CheckoutEvent, CheckoutEstimate, PrescriptionRevision/Selection, PrescriptionFulfillmentEvent/FulfillmentDispositionEvent y StockAllocation;
- ClinicalChargeEntry/QuantityEvent/Snapshot y MedicalRecordBillingContext;
- ExternalPrescriptionAttestation owned por Checkout/item revision + InvoiceItemExternalPrescriptionEvidence;
- lifecycle lógico/FK PROTECT de fuentes clínicas con entry y writers que actualizan source/event/stock atómicamente;
- ObligationEvidence, CheckoutDispute y CollectionCase;
- CommandReceipt con claim PostgreSQL, canonical schema registry, envelope/tombstone y ACL;
- LegacyCheckoutSeed y adopción en close;
- BillingCutoverControl, BillingCutoverRun y LegacyBillingMutation en todos los writers legacy/future;
- LegacySettlementCase/Assessment, LegacyPaymentApplicationAdjustment, LegacyLiabilityReturn/ReturnPayment/Reversal y comandos de clasificación/reparación;
- Payment y demás eventos hijos con FK Receipt/line index e idempotency key derivada;
- source/provenance/stock_behavior inmutables y constraints tenant-aware;
- baseline de replacement sobre CheckoutItem, owner/SLA, proyecciones correction_pending/overdue y ReplacementWaiver append-only;
- lifecycle/payment/collection dimensions de Invoice y lineage supersedes;
- proyección CreditNote.effectiveness y guard de RefundReversal con restock;
- servicios charge delta/reprice, close→checkout/seed adoption, attestation, supplement, pay/post, no_charge, dispute/collection, custody/fulfillment, terminal void, atomic replacement, replacement adjust/assign/waive, refund/reverse, cutover y legacy repair;
- totals server-side reutilizables;
- version/concurrency, registry total de model ranks y retry controlado;
- permisos granulares;
- serializers de comandos;
- retiro gradual de writers genéricos y signal.

### Frontend

- bandeja separada de Checkouts y cuentas por cobrar;
- bandejas separadas de disputas y reconciliación legacy;
- bandeja separada de correcciones pendientes/vencidas con owner/SLA y baseline protegido;
- editor retail y PrescriptionSelection explícita;
- atestación Rx externa por revision/fingerprint y disclosure PII por permiso;
- fulfillment Rx local/acumulado derivado de eventos y suplementos;
- carrito POS reanudable;
- Checkout Estimate en sustitución del PDF draft;
- CTA Cobrar unificado;
- Dejar pendiente condicionado;
- no_charge y abandon solo para kinds permitidos; nunca para replacement;
- void_and_prepare_replacement como CTA único con lineage/dispositions/baseline; post o waiver como únicos cierres;
- readiness estructural y blockers/required_inputs por acción;
- eliminación de draft/confirmed en copy;
- manejo de version/idempotency/state conflict sin reintentos duplicados.
- reconciliación legacy separa kind/repairability y oculta cobro no collectible.

### Analytics

- posted_at como accrual;
- outstanding desde posted/unpaid;
- no_charge, abandono y aceptación de receta;
- disputed exposure, AR disputed y legacy anomaly buckets;
- correction_pending/overdue y replacement waived exposure separados de AR/no_charge;
- liability return separado de revenue/stock;
- child event identity por Receipt y return reversals por occurred_at;
- Rx dispensed/returned/redelivered/cap contribution como dimensiones separadas;
- external attestation compliance sin PII;
- mutation lag/watermarks/cutover result;
- CreditNote efectiva/revertida y neteo append-only;
- provenance de precio/impuesto;
- versionado de métricas;
- reconciliación con snapshots legacy.

### Tests

Además de la regresión de estados, ownership, $0, crédito, pago exacto/split, POS y analytics, el plan debe incluir como mínimo:

| Caso | Resultado requerido |
| --- | --- |
| Servicio qty 1 a precio A; catálogo B; incrementar qty 1 | Un ciclo, dos QuantityEvents y total 2×A; retry no duplica. |
| Producto clínico repetido tras cambio de precio | Conserva primer precio del ciclo y stock single-lot coherente. |
| Decrementar/eliminar/reabrir source cobrable | Deltas no bajan de cero; ciclo cerrado no factura; reopen crea precio/ciclo nuevo. |
| Incrementos clínicos concurrentes | Lock + mutation_key producen cantidad/total únicos sin eventos duplicados. |
| Clinical reprice autorizado | Receipt/version/ACL cierran ciclo a cero y abren otro; retry devuelve mismos IDs; cero stock. |
| Clinical reprice stale/sin permiso | Rechazo sin QuantityEvent/ciclo parcial. |
| Tax cambia entre primer cargo, close y post | Consulta conserva MedicalRecordBillingContext del primer cargo. |
| Included/close/Appointment signal creó tax legacy | Writer provenance real; no se etiqueta first_billable sin evidencia. |
| Retail/Rx se reprecifica mientras open | Incrementa versión, audita before/after e invalida aceptación anterior. |
| Materialización de protocolo falla durante close | Rollback de MR, Appointment, snapshots, Checkout, stock y cargos. |
| Prescription editada después de close | Revisión anterior inmutable; cambio crea addendum, no altera Invoice/Checkout existente. |
| Suplemento completa remanente Rx | Full local contra remanente y filled acumulado contra cap original. |
| Dos suplementos concurrentes | Uno no puede superar el cap; el otro revalida/conflicta sin stock duplicado. |
| Consumo clínico necesitaría dos lotes | Rechazo atómico por single-lot v1. |
| Retail/Rx necesita dos lotes | Allocations y StockMovements exactos por lote. |
| Rx accepted mientras Checkout open | CheckoutItem requested; cero StockAllocation/StockMovement hasta post. |
| POS Rx externa sin atestación | Agregar/mutar o post rechaza `prescription_required`; cero Invoice/stock. |
| POS Rx externa válida | Attestation exacta + coverage InvoiceItem; PII solo a permiso dedicado. |
| Cambiar qty/presentation o remover/reagregar Rx | Incrementa regulatory revision; evidencia anterior stale; exige nueva. |
| Abandon/void/refund de venta Rx externa | Attestation sobrevive; cada efecto físico/financiero queda separado. |
| Stock cambia después de selección | Finalize reasigna FEFO completo o bloquea; nunca crea fulfillment parcial/silencioso. |
| Structural ready con caja cerrada | preparation ready; `actions.pay.allowed=false`; otras acciones independientes. |
| Crédito deshabilitado/sin evidencia | pay puede seguir disponible; post_unpaid bloqueado sin Invoice/stock. |
| Pay captura acknowledgement en payload | allowed=true + required_inputs; evidence nace en el mismo commit. |
| Cliente disputa cargo clínico | Hold/cola/SLA visibles; nunca abandoned ni open ordinario invisible. |
| Resolución enforced sin términos previos | Rechazo sin Invoice. |
| Enforced bajo términos y pago posterior | CollectionCase open→resolved/paid; collection_status closed. |
| Replay pay tras Checkout terminal | Mismo status/body/IDs; cero nuevos efectos. |
| Misma key, otro target o payload | 409; jamás devuelve resultado ajeno. |
| Mismo raw key para pay_checkout y pay_invoice | Receipts distintos y Payment child keys no colisionan. |
| Split con líneas duplicadas/equivalentes | Orden/índices canónicos estables; cada evento ocurre una vez. |
| Dos keys finalizan un Checkout | Un commit; el otro 409 sin efectos. |
| Timeout tras commit | Retry obtiene CommandReceipt completo. |
| Decimal/defaults/payment lines equivalentes | Mismo hash según canonical schema version; cambio real da 409. |
| Dos claims simultáneos misma key | INSERT ON CONFLICT serializa; un efecto y un replay. |
| Close vs assign_patient/status en PostgreSQL | Orden Appointment→MR, resultado serializable y sin deadlock no controlado. |
| Refund vs reverse_credit_note concurrentes | Ambos preleen y lockean Invoice→CreditNote; sin ABBA. |
| Re-update de CommandReceipt ya lockeado al final | Permitido; checker no lo reporta como adquisición inversa. |
| Helper intenta UPDATE de row inferior no adquirida | Test/guard falla antes de crear efectos. |
| Replacement vs pay/void concurrentes | Una transición; cero obligación/replacement huérfano. |
| Pay/edit/takeover/expiry POS concurrentes | Una transición válida; nunca abandoned junto con Invoice/Payment. |
| Fallo en creación del replacement | Rollback total: Invoice original continúa posted. |
| Replay void_and_prepare_replacement | Mismos IDs de Invoice voided/Checkout; cero doble stock/audit. |
| Replacement de servicio prestado o goods_retained | Nace baseline no vacío, owner/SLA y correction_pending en el mismo commit. |
| Abandon/expiry/no_charge de replacement | 409 replacement_resolution_required; baseline y cola permanecen. |
| PATCH/delete/descuento sobre baseline | Rechazado sin mutación; extras aún no entregados conservan edición permitida. |
| Adjustment autorizado de replacement | Baseline físico inmutable, adjustment append-only y total/version auditados; resultado >0. Intentar cero se rechaza y exige waiver. |
| SLA de replacement vencido | Proyecta correction_overdue y escala; no se abandona ni desaparece de consulta/UI/analytics. |
| Post/pay de replacement | Nueva Invoice supersedes original; baseline/adjustments copiados una vez; resolución terminal. |
| Waiver de replacement | Permiso/razón/evidencia/importe exactos; ReplacementWaiver único; sin Invoice, Payment, stock ni fulfillment nuevo. |
| Post/pay vs waiver concurrentes | Solo uno termina; el otro 409/replay estable; nunca ambos outcomes. |
| Void standalone con goods_retained/exposición continua | Rechazado; exige comando atómico. |
| Void atómico con retail retenido | Replacement usa already_fulfilled y no descuenta ni contribuye fulfillment doble. |
| Void con retorno demostrado y redelivery Rx | Stock retorna/sale de nuevo; redelivery enlazada aporta delta Rx cero hasta cantidad retornada. |
| Return/restock Rx sin redelivery | Stock/custodia cambian; cap Rx no se restaura en v1. |
| Nueva entrega Rx sin retorno probado | Aporta +q y falla si excede cap. |
| Refund de línea clínica con `restock` | Rechazado; cero StockMovement ficticio. |
| Refund retail con restock y luego reversal | Reversal 409 manual reconciliation; stock permanece explicable. |
| Refund sin stock y reversal | Ledger/analytics netos, CreditNote fully_reversed y capacidad financiera de refund restaurada; fulfillment Rx intacto. |
| MR open con seed, luego cambia y cierra | Un solo primary; clínica desde entries actuales; seed adopted; Rx pending. |
| Appointment-only draft vacío/con efectos | Abandoned técnico o quarantine exactamente según matriz. |
| Legacy partial collectible | Assessment/hash vigentes + Payment exacto/CashSession/revenue_paid nuevo; historia intacta. |
| Legacy partial no collectible | Settle rechazado aunque saldo/permiso sean correctos. |
| Legacy overpaid return mixto | ReturnPayment por método/índice; applied=total, liability=0, revenue/stock sin cambio. |
| Reverse liability return | Counterevent por línea; liability reabre; eventos originales intactos. |
| Legacy confirmed/paid | Provenance legacy correcta, sin aceptante/canal inventado. |
| Writer entre baseline y freeze | Emite mutation; catch-up reconstruye antes de activar future. |
| Writer in-flight al freeze | Lock exclusivo espera commit; final watermark lo incluye. |
| Cutover con mutation/hash pendiente | No cambia a future. |
| Cutover de todos los writers legacy | MR open no puede producir Invoice por ruta alternativa. |
| Checkout Estimate | Emisión idempotente congela versión/hash; PDF no financiero sin Invoice number/anchors/revenue; edición no altera anterior. |
| PDF Invoice sobre Checkout open | Rechazado; legacy draft solo por adapter read-only. |
| ACL/retention de receipt/evidence/disputes | Tenant isolation, envelope allowlisted, audit y tombstone 410. |

## 11. Riesgos y trade-offs

| Riesgo/costo | Mitigación |
| --- | --- |
| Nuevo agregado incrementa complejidad | Frontera clara, comandos únicos y API por intención |
| Snapshot duplica datos clínicos | source_object + snapshot inmutable con razón financiera |
| Migración de drafts no es uno-a-uno | Clasificación, legacy mapping y cuarentena |
| Dos listas operativas confunden | UI “Por preparar” vs “Pendientes de pago” |
| POS server-side aumenta escrituras | Version, TTL y limpieza; elimina Invoice técnicas |
| Crédito puede usarse como escape | Permiso restringido, razón, due_at y analytics |
| posted acopla entrega y devengo | Es deliberado en esta fase; si hay reserva/entrega posterior se requerirá Fulfillment separado |
| No partial limita cobranza | Decisión explícita p30; evita estado financiero adicional |
| Dispute agrega una cola operativa | Hace visible la exposición y exige owner/SLA; evita fabricar o esconder deuda |
| Reversal con restock queda bloqueado | Seguridad de inventario primero; reconciliación física explícita en vez de stock ficticio |
| CommandReceipt aumenta persistencia | Permite replay exacto y elimina doble efecto ante timeout/concurrencia |
| Single-lot clínico limita consumos | Conserva provenance actual; rechazo temprano hasta diseñar allocations clínicas |
| Primer precio gobierna incrementos clínicos | Preserva comportamiento actual y evita mezcla; reprice total solo mediante ciclo nuevo auditado |
| Seed migratorio agrega staging | Evita Checkout obsoleto/duplicado y permite reconstrucción autoritativa al close |
| Replacement atómico amplía transacción | Evita desaparición de exposición; un receipt y rollback total |
| Continuidad operacional deja una ventana sin AR | Baseline inmutable, owner/SLA, cola correction_pending/overdue y solo dos terminales; producto acepta que la nueva AR nace al post |
| Waiver de replacement puede ocultar pérdida | Permiso separado, evidencia/importe explícitos, evento append-only y métrica distinta de no_charge |
| Eventos legacy especiales amplían ledger | Separan Payment, aplicación a Invoice y liability sin corromper revenue/stock |
| Registry total de locks exige disciplina global | Checker/tests por comando; retries solo como resiliencia |
| Retener evidence/receipts tiene costo | Allowlist, ACL, clases de retención y tombstone sin PII/blobs |
| Atestación externa contiene PII regulatoria | Owner propio, coverage exacta, ACL separado, audit y retention class; Invoice no copia PII |
| Identidad receipt-derived cambia contrato financiero | Enmienda 1.1 atómica con schema/migration/contract tests; unique por organization se conserva |
| V1 no restaura cap Rx por devolución | Política conservadora evita sobredispensar; redelivery probada es neutral y restauración futura exige ADR |
| Freeze interrumpe writes por organización | Ventana corta después de baseline/catch-up; lock espera in-flight y reconciliación evita fotografía stale |
| Repairability agrega revisión operativa | Solo anomalías legacy; evita convertir aritmética dudosa en deuda cobrable |
| Estimate puede confundirse con factura | Título/watermark/campos/endpoint distintos y sin número ni anchors financieros |

## 12. Decisiones excluidas

- pagos parciales en writers normales; `settle_legacy_partial` únicamente completa una anomalía preexistente por su saldo exacto;
- reservas de stock;
- fulfillment/reserva diferidos de posteo; D20 solo agrega ledger de fulfillment dentro de entrega/post y correcciones;
- write-off contable/cartera incobrable formal; un waiver de disputa es ajuste comercial auditado, no write-off;
- factura fiscal y timbrado;
- reapertura/corrección formal de MedicalRecord;
- Checkouts arbitrarios por consulta fuera de los kinds cerrados primary/supplement/replacement;
- surtido externo interoperable;
- límite de crédito automático y scoring; v1 autoriza cada operación individualmente;
- reverso automático de CreditNote que ya restockeó;
- consumo clínico multilote;
- TTL exacto de POS.
- restaurar automáticamente capacidad Rx por retorno/restock;
- CDC o dual-write financiero como alternativa al freeze/catch-up v1;
- hard-delete/anonimización automática de atestación antes de cerrar DD-005/legal hold.

Estas exclusiones no deben resolverse accidentalmente mediante campos genéricos.

## 13. Checklist de aprobación de producto

Aceptar esta ADR significa aprobar explícitamente:

- [x] D1: existe deuda posted/unpaid, excepcional y sin parcial.
- [x] D2: devengo ocurre en posted_at.
- [x] D3: $0 termina no_charge sin Invoice.
- [x] D4: ownership por source y recepción no modifica hechos clínicos.
- [x] D5: rechazo de receta se persiste y no cancela prescripción.
- [x] D6: stock retail sale al postear/entregar.
- [x] D7: cobrar requiere payment.create; VET no lo hereda.
- [x] D8: no pagos parciales; split total sí.
- [x] D9: POS usa Checkout persistente/reanudable.
- [x] D10: auto_create_invoice_on_done se elimina.
- [x] D11: el primer precio del ciclo gobierna incrementos; quantity events son append-only; tax first_billable es política futura.
- [x] D12: obligación exige evidencia; CheckoutDispute y CollectionCase cubren antes/después del post.
- [x] D13: RefundReversal después de restock queda bloqueado en v1.
- [x] D14: CommandReceipt usa claim/canonicalización versionados; lock order gobierna primera adquisición y permite re-update de rows poseídas.
- [x] D15: contrato aprobado, fuera del alcance greenfield hasta que exista import legacy.
- [x] D16: exposición continua usa void_and_prepare_replacement atómico; no endpoints secuenciales.
- [x] D17: contrato aprobado, fuera del alcance greenfield al no existir MR legacy.
- [x] D18: ExternalPrescriptionAttestation pertenece a Checkout/item revision, post exige coverage exacta y la evidencia sobrevive lifecycle.
- [x] D19: eventos financieros hijos usan receipt/kind/index; liability legacy queda fuera del alcance greenfield.
- [x] D20: stock, custodia, dinero y fulfillment Rx son proyecciones separadas; retorno no restaura cap en v1.
- [x] D21: contrato de cutover aprobado pero no aplicable al lanzamiento sin convivencia de writers.
- [x] D22: contrato aprobado, fuera del alcance greenfield al no existir settlement legacy.
- [x] D23: PDF draft se reemplaza por Checkout Estimate no financiero.
- [x] D24: reprice_clinical_charge es el único cambio de precio capturado y exige ACL/version/reason/receipt.
- [x] D25: replacement conserva baseline/owner/SLA, no admite abandon/expiry/no_charge y solo termina en nueva Invoice o waiver explícito.
- [x] Checkout es un modelo separado.
- [x] Invoice no tiene draft ni confirmed.
- [x] El nombre persistido/API es posted; “Emitida” es solo copy de producto.
- [x] cancelled se divide entre abandoned y voided.
- [x] cancelled legacy no genera otro documento por defecto.
- [x] Consumo clínico es single-lot en v1; retail/Rx persiste allocations multilote.
- [x] StockAllocation solo existe después de post y siempre referencia StockMovement committed.
- [x] PrescriptionFulfillmentEvent, no StockAllocation “effective”, gobierna cap y correcciones.
- [x] Actions separan blockers de required_inputs.
- [x] Nuevos writers exigen ObligationEvidence; no se inventa provenance legacy en greenfield.
- [x] Financial-event-model-contract se publica como v1.1 en la misma slice que child identity.
- [x] BillingCutoverControl queda explícitamente condicionado a importación, dual-write o tenants legacy.

## 14. Decisión propuesta final

~~~text
MedicalRecord.close
        │
        ▼
Checkout.open
        │
        ├─ Estimate PDF ───────────────────▶ no financiero; versionado
        ├─ POS Rx externo ─────────────────▶ attestation exacta o blocker
        ├─ total=0 y decisiones resueltas ─▶ completed/no_charge
        ├─ Cobrar ─────────────────────────▶ Invoice posted/paid + stock/fulfillment + completed/posted_paid
        ├─ Dejar pendiente ────────────────▶ Invoice posted/unpaid + stock/fulfillment ─▶ paid
        ├─ disputa ─────────────────────────▶ hold/dispute ─▶ resolución explícita
        └─ abandon permitido ──────────────▶ abandoned

Invoice posted/unpaid + exposición continua
  ─▶ void_and_prepare_replacement ─▶ voided + replacement.correction_pending
                                           ├─ post/pay ─▶ nueva Invoice
                                           └─ waiver ───▶ completed/replacement_waived
       abandon / expiry / no_charge / remove baseline ─▶ prohibidos
Invoice posted/unpaid + final terminal ─▶ voided
Invoice posted/paid ───▶ CreditNote/Refund; Invoice permanece paid
CreditNote efectiva sin restock ─▶ RefundReversal/fully_reversed
CollectionCase.open ─▶ collectible / paid / replaced / waived
Legacy partial collectible ─▶ Payment exacto; otro partial ─▶ no cobro
Legacy overpaid returnable ─▶ liability return payments/reversals
MR open legacy draft ─▶ LegacyCheckoutSeed ─▶ close ─▶ único primary Checkout
organization legacy ─▶ freeze/watermark/catch-up/reconcile ─▶ future
~~~

La entidad editable es Checkout. La entidad financiera es Invoice. El estado de pago pertenece al ledger. Un replacement sigue siendo Checkout, pero su baseline ya entregado no es editable ni descartable: owner, SLA y resolución explícita impiden perder la exposición entre el void y la nueva Invoice. Precio/repricing, aceptación, atestación externa, stock, custodia, fulfillment, disputa, waiver, repairability, cutover e idempotencia tienen evidencias propias y no se esconden dentro de un status. Esa separación responde a motivos de cambio distintos y elimina la necesidad de usar draft o confirmed como conceptos ambiguos sin perder las responsabilidades que hoy cumplen accidentalmente.

## 15. Enmienda 2026-09-06 — unidades, disponibilidad y schema verificable

La auditoría de regresión posterior al rediseño fija estas decisiones normativas:

- `PrescriptionItem.quantity`, `PrescriptionFulfillmentEvent.quantity_delta`,
  `physical_quantity`, `Product.stock_quantity`, `StockLot.quantity_on_hand` y
  `StockAllocation.quantity_base` usan unidades base de `Product.base_unit`.
- `CheckoutItem.quantity` e `InvoiceItem.quantity` usan unidades de presentación
  comercial. Retail y dispensación Rx aceptan sólo presentaciones completas.
- `Presentation.conversion_factor` significa unidades base por presentación. Cada
  línea captura `conversion_factor_snapshot`; editar el catálogo nunca reinterpreta
  un Checkout, una Invoice, un movimiento ni una devolución existentes.
- `MedicalRecordProduct` captura el mismo snapshot al consumo clínico para que una
  edición/eliminación posterior revierta exactamente las unidades consumidas.
- `Product.stock_quantity` y, para productos por lote, la suma de lotes consumibles
  son invariantes autoritativas. `Presentation.stock` y `Presentation.quantity` son
  compatibilidad legacy y Billing no los usa para decidir.
- `max_selectable_quantity` es el mínimo entre límite clínico y stock físico,
  expresado siempre en presentaciones **adicionales**. Backend lo calcula; frontend
  sólo presenta el resultado y `blocking_reasons`.
- Una entrega retail/Rx puede tener 1..N `StockAllocation` FEFO. Refund, void y
  replacement revierten cada asignación exacta; ningún flujo puede usar “primer
  lote” como representación de toda la línea.
- El schema físico es parte del contrato. CI ejecuta migrations en PostgreSQL y
  `audit_billing_schema`; una migration registrada sin DDL equivalente es fallo de
  despliegue, no una compatibilidad aceptable.

Esta enmienda corrige la descripción anterior de `requested_quantity`: ese campo no
existe. La intención comercial material está en `CheckoutItem.quantity` y su
equivalencia base queda determinada por el snapshot inmutable.
