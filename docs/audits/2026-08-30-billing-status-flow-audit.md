# Auditoría de estados de Cobros y flujo Consulta → Cobros

**Fecha:** 2026-08-30

**Alcance:** código real de backend, frontend, permisos, pruebas, analytics y documentación relacionada.

**Naturaleza:** diagnóstico técnico y de producto; no contiene ni implica cambios de implementación.

## Metodología y criterio de evidencia

La fuente primaria fue el código del árbol de trabajo actual. Se usó el grafo de código para localizar definiciones, rutas y relaciones de llamada; cada comportamiento determinante se contrastó después en modelos, serializers, services, views, frontend y pruebas. Para literales de UI, configuración y documentación se usó búsqueda textual. Cuando existe conflicto se aplica este orden:

~~~text
código ejecutable actual > pruebas ejecutables actuales > documentación
~~~

La revisión focalizada ejecutó 94 pruebas de billing, payment ledger, dispensación, cost behavior y cierre de consultas:

~~~text
Ran 94 tests in 95.039s
OK
~~~

Esto demuestra que el comportamiento descrito es aceptado por la suite actual; no demuestra por sí solo que el comportamiento sea correcto desde producto. La auditoría se realizó sobre un árbol que ya contenía cambios ajenos en appointments y frontend. No se modificaron esos cambios. En los archivos modificados se verificó directamente el contenido del working tree porque el índice del grafo puede representar una revisión anterior.

## 1. Resumen ejecutivo

1. **draft no es hoy un único estado de negocio.** Representa, según el writer, una factura clínica que se sincroniza mientras la consulta sigue abierta, una bandeja generada al cerrar una consulta incluso por $0, una factura anticipada al marcar una cita como done, o el ensamblado técnico multipetición del POS. La única semántica común real es “sus items todavía pueden mutar y aún no se ha asentado stock de venta”.
2. **draft debe REDEFINIRSE, no eliminarse sin reemplazo.** El flujo necesita alguna forma de preparación editable para selección parcial de receta y para el POS; pero esa preparación no debería confundirse con una obligación financiera ni necesariamente ser una Invoice persistente. En consulta puede ser un checkout abierto; en POS puede ser una sesión/carrito transitorio.
3. **confirmed tampoco es una simple confirmación de UI.** En código ejecuta cuatro cosas a la vez: congela items, descuenta stock de venta, fija confirmed_at y reconoce ingreso devengado/cuenta por cobrar. No exige que la consulta esté cerrada, que recepción haya revisado el cobro ni que el cliente acepte el importe.
4. **confirmed debe REDEFINIRSE como “posted/unpaid” o evento de finalización financiera**, y no ser un paso manual obligatorio antes de cada pago. Si el negocio no concede crédito, finalizar y cobrar debería ser una operación atómica. “Dejar pendiente” debe ser una acción explícita que sí crea una cuenta por cobrar.
5. **paid es el estado mejor justificado**, porque representa liquidación total del ledger y es usado por ingresos cobrados, devoluciones y restricciones terminales. Debe conservarse como proyección almacenada o derivada, pero reforzada por la invariante total de Payments = total de Invoice.
6. **cancelled también tiene valor**, pero significa “voided antes de pago”, no una cancelación genérica. Revierte stock asentado al confirmar, impide pagos y conserva trazabilidad. Una factura paid nunca se cancela: se corrige con CreditNote y RefundPayment. Se recomienda renombrar/redefinir, no eliminar.
7. **Consulta → Cobros no es coherente hoy.** La Invoice puede aparecer en Cobros desde el primer servicio/producto, antes del cierre; el cierre siempre garantiza una Invoice draft pero no la “envía” mediante ninguna transición; y confirm puede ejecutarse antes del cierre. Por tanto “Finalizada y enviada a Cobros” es una narrativa de UI, no un límite real del dominio.
8. **Existe un riesgo crítico de divergencia clínica-financiera.** Se puede confirmar una factura de consulta con el MedicalRecord abierto. Después se pueden agregar o eliminar cargos clínicos; el registro clínico y stock cambian, pero la sincronización de Invoice se omite porque ya no está draft.
9. **Existe un segundo riesgo crítico en PATCH de InvoiceItem y de Invoice.** La API permite cambiar el origen service/presentation, lote e incluso invoice_type mientras está draft, sin las validaciones completas de creación, receta o asentamiento de stock. Esto puede omitir o duplicar inventario y eludir la atestación de receta externa.
10. **Las recetas no generan cargo ni stock automáticamente.** La dispensación posterior agrega solo el subconjunto elegido; stock se descuenta al confirmar. El rechazo total no se persiste. El frontend selecciona todos los sugeridos por defecto, no permite editar/quitar líneas ya añadidas y puede mantener selección local obsoleta.
11. **Las consultas sin cargos quedan varadas.** El cierre crea una Invoice draft de $0; si no tiene items, confirm la rechaza. Si tiene un item a precio cero, puede llegar a confirmed pero no existe pago positivo de $0. La UI de billing no ofrece cancelación ni una resolución no financiera.
12. **La separación de roles no existe en permisos financieros.** VET y ASSISTANT pueden crear/modificar items, confirmar, pagar y cancelar. El código sí restringe la edición clínica al veterinario asignado/ADMIN, pero no distingue al clínico, recepción y caja en billing.
13. **consultation y direct_sale comparten la misma máquina real.** Direct sale parece saltar confirmed solo porque direct-pay llama internamente confirm y pay en una transacción. Además, el endpoint genérico permite confirmar una venta directa y pagarla después. La diferencia es de origen, stock y UX, no una máquina de estados verdaderamente distinta.
14. **La recomendación es separar lifecycle de documento, readiness de checkout y settlement del ledger.** Mantener un checkout editable; postear solo una obligación real; cobrar atómicamente en el caso normal; derivar el estado de pago del ledger; y conservar void/refund como eventos terminales auditables.

## 2. Estado real del código

### 2.1 Qué representa cada estado en ejecución

| Estado | Qué significa realmente hoy | Cómo se crea | Quién puede producirlo | Qué puede cambiar | Qué lo termina | Evidencia principal |
| --- | --- | --- | --- | --- | --- | --- |
| draft | Invoice persistente editable, todavía no devengada. Puede ser preparación clínica, checkout de receta, factura $0 o ensamblado POS. En productos de venta todavía no ha asentado stock. | Es default del modelo y de todos los writers automáticos o explícitos. | ADMIN, VET y ASSISTANT vía API; veterinario/ADMIN indirectamente al agregar cargo; cierre; signal de cita; POS. | Header por PATCH, items por POST/PATCH/DELETE, dispensación. La UI de billing, sin embargo, casi no ofrece edición. | confirm, direct-pay o cancel. | backend/apps/billing/models.py:32-228; services.py:145-218, 791-832, 936-1118; views.py:69-190, 313-491 |
| confirmed | Documento congelado y “devengado”; stock de venta ya salió; puede pagarse o cancelarse; no admite modificación de items. No prueba cierre clínico ni aceptación del cliente. | confirm o el paso interno de direct-pay. | ADMIN, VET, ASSISTANT con invoice.confirm; direct-pay usa invoice.pay. | Solo se agregan Payments mediante pay; no items/header. | paid o cancelled. Puede quedar indefinidamente. | services.py:145-218, 331-374, 382-448, 499-550 |
| paid | Total completamente cubierto por uno o varios Payment creados en la misma operación; ingreso cobrado. Permanece paid ante devoluciones. | pay sobre confirmed o direct-pay sobre draft direct_sale. | ADMIN, VET, ASSISTANT con invoice.pay. | No se edita ni cancela; puede recibir CreditNote/RefundPayment. | No hay transición de Invoice. | services.py:309-374, 452-550, 574-702 |
| cancelled | Void terminal previo al pago. Si venía de confirmed, revierte el stock que esa confirmación asentó. No admite Payments. | cancel desde draft o confirmed sin Payments. | ADMIN, VET, ASSISTANT con invoice.cancel. POS lo usa en error o volver al carrito. | Nada en Invoice. | Terminal. | services.py:389-448; frontend/src/pages/pos/index.jsx:103-196 |

Respuesta concreta a la pregunta central: cuando el veterinario termina una consulta y el cobro aparece en Cobros como draft, **el código solo garantiza que existe una Invoice editable enlazada al MedicalRecord; no garantiza que fue creada en ese momento, que su total esté revisado ni que el cliente aceptó comprar los productos sugeridos**. Para dejar de ser draft alguien con invoice.confirm debe pulsar “Confirmar”; esa acción congela líneas, descuenta stock de productos vendidos/dispensados, registra confirmed_at y devenga el total. Después alguien con invoice.pay debe registrar el importe completo. No hay asignación de responsable ni requisito técnico de que la consulta estuviera cerrada.

### 2.2 Máquina de estados real

~~~text
                                             CreditNote + RefundPayment
                                             (Invoice permanece paid)
                                                        │
                                                        ▼
┌────────────┐   confirm / _confirm_locked_invoice   ┌────────────┐
│   draft    │ ─────────────────────────────────────▶ │ confirmed  │
│ editable   │                                        │ frozen/AR  │
└─────┬──────┘                                        └─────┬──────┘
      │                                                     │
      │ direct-pay: internamente draft → confirmed → paid   │ pay exacto
      └──────────────────────────────┐                      │
                                     ▼                      ▼
                                  ┌────────────────────────────┐
                                  │            paid            │
                                  └────────────────────────────┘

draft ────── cancel ──────▶ cancelled
confirmed ── cancel ──────▶ cancelled
paid ─────── cancel ──────▶ PROHIBIDO
~~~

La transición externa draft → paid de POS no es un verdadero salto del dominio: pay_direct_sale llama a _confirm_locked_invoice y luego a _pay_locked_invoice; crea ambos audit logs y ambos timestamps dentro de la misma transacción (backend/apps/billing/services.py:499-550).

Existe además una ruta alternativa no reflejada en la UX: confirm_invoice no restringe invoice_type. Una direct_sale puede usar confirm genérico y luego pay genérico. Por tanto consultation y direct_sale no tienen máquinas distintas a nivel de API; direct-pay es un comando compuesto de conveniencia.

### 2.3 Transiciones ilegales y capa que las impide

| Intento | Resultado real | Capa |
| --- | --- | --- |
| Confirmar algo distinto de draft | ValidationError | Service, _confirm_locked_invoice |
| Confirmar factura sin items activos | ValidationError | Service |
| Confirmar con stock insuficiente/lote inválido | ValidationError antes de asentar movimientos | Service + inventory |
| Confirmar consultation con MedicalRecord abierto | **Permitido** | No existe guard |
| Pagar algo distinto de confirmed | ValidationError | Service pay_invoice |
| Pagar parcialmente | Rechazado: payment lines deben igualar remaining_balance | Service pay_invoice |
| direct-pay sobre consultation o estado no draft | Rechazado | Service pay_direct_sale |
| Modificar header o items fuera de draft | Rechazado | View |
| Cambiar service ↔ presentation o invoice_type dentro de draft | **Permitido con validación insuficiente** | Serializer/View |
| Cancelar paid, cancelled o cualquier Invoice con Payment | Rechazado | Service cancel_invoice |
| Estado paid sin paid_at | Rechazado | CHECK de base de datos |
| Estado confirmed/paid sin confirmed_at | Rechazado | CHECK de base de datos |
| Estado cancelled sin cancelled_at | Rechazado | CHECK de base de datos |
| paid con remaining_balance distinto de cero | No hay CHECK de DB; auditoría/servicio lo detectan | Service + comando de integridad |
| draft/cancelled con Payments | No hay CHECK relacional de DB; servicios y auditoría lo evitan | Service + comando |

InvoiceSerializer expone status, invoice_type y relaciones como campos escribibles (backend/apps/billing/serializers.py:212-446). Intentar crear o parchar ciertos estados sin anchors puede terminar en IntegrityError de DB, no en una validación de dominio clara. El modelo tampoco prohíbe anchors sobrantes en estados anteriores.

### 2.4 Invariantes reales

| Invariante pretendida | Garantía actual | Dependencia de confirmed |
| --- | --- | --- |
| paid implica paid_at | CHECK DB + service | No |
| confirmed o paid implica confirmed_at | CHECK DB + service | Sí, por el modelo actual |
| cancelled implica cancelled_at | CHECK DB + service | No |
| paid equivale a remaining_balance = 0 | Service y comando audit_payment_ledger_integrity; no CHECK DB | No; se deriva de Payments |
| confirmed tiene total > 0 y pago menor al total | Comando de integridad, no DB; un item de precio cero puede confirmarse | Sí |
| items solo cambian en draft | View; no regla en model.save/delete | Sí como permiso de edición |
| pago requiere confirmed | pay_invoice; direct-pay lo confirma internamente | Sí, pero puede ser detalle de comando compuesto |
| pagos append-only | No hay PATCH/DELETE público; modelos son eventos. No hay override/trigger DB que impida mutación administrativa | No |
| direct-sale puede cobrarse “directo” | Comando compuesto, idempotente y transaccional | Internamente sí pasa por confirmed |
| cancelación de confirmed revierte stock asentado | Service | Sí, porque stock de venta se asienta allí |
| cancelación de draft no revierte stock | Correcto para venta; el consumo clínico ya fue asentado en MedicalRecordProduct y no pertenece a la venta | No |
| idempotencia evita doble pago/refund | Unique por organización/clave y deduplicación de service | No |
| pago exige sesión de caja cuando corresponde | Service bloquea/resuelve CashSession | No |

### 2.5 Qué aporta confirmed que no sea derivable

No aporta una condición de pago: “hay saldo” se deriva de total y Payments. Sí aporta hoy tres hechos no derivables de ese saldo:

- momento de posteo/devengo, consumido por analytics;
- momento en que los items quedan congelados;
- momento en que se descuenta stock de retail/dispensación.

El problema no es que esos hechos no existan, sino que un único estado los acopla y que su precondición no expresa el evento de negocio esperado. confirmed_at puede sobrevivir como posted_at/finalized_at independiente del estado de pago. El stock puede asentarse en la misma operación de finalización o cobro. El permiso de edición puede depender del lifecycle del checkout/documento.

## 3. Inventario de writers

### 3.1 Todos los orígenes que crean Invoice

| Origen | Writer | Crea Invoice | Estado inicial | Motivo y observaciones |
| --- | --- | --- | --- | --- |
| POST genérico de billing | InvoiceListCreateView.perform_create + InvoiceSerializer | Sí | draft por default, aunque status es escribible | Permite creación manual de consultation o direct_sale y relaciones del mismo tenant; no exige coherencia completa entre tipo, cita, MR, owner y pet. |
| Agregar servicio clínico | MedicalRecordServiceListCreateView.perform_create → get_or_create_invoice_for_medical_record | Sí si no existe | draft | Crea la Invoice antes de sincronizar el InvoiceItem. Si Invoice no está draft, guarda el servicio clínico pero omite el cargo. |
| Agregar producto clínico charge | add_medical_record_product → get_or_create_invoice_for_medical_record | Sí | draft | Crea/sincroniza InvoiceItem; MedicalRecordProduct descuenta stock clínico en ese momento. |
| Agregar producto clínico included | mismo service | Sí | draft | Crea header aunque deliberadamente no crea InvoiceItem; puede producir $0. |
| Cierre de consulta | close_medical_record → get_or_create_invoice_for_medical_record | Sí, siempre | draft si es nueva | Garantiza la relación pero no transiciona ni marca “enviado”. |
| Dispensar receta | dispense_prescription_into_invoice → get_or_create_invoice_for_medical_record | Sí | draft | Agrega solo presentación/cantidad aceptada; no descuenta stock hasta confirm. |
| Cita marcada done | post_save create_draft_invoice_on_done | Sí si toggle activo | draft | Puede existir con MR abierto, sin MR o sin items. |
| Cierre de MR completa cita | close_medical_record → complete_appointment_on_record_close | No en el service de appointments | N/A | El QuerySet.update evita signal; no duplica porque close ya creó/obtuvo Invoice. |
| POS | createInvoice desde frontend → POST genérico | Sí | draft direct_sale | Se agregan items en peticiones posteriores; back/error cancelan, pero refresh/abandono puede dejar draft. |
| Materialización de vacunas/protocolos | indirectamente add_medical_record_product | Puede obtener/crear | draft | Usa default_cost_behavior del producto y ocurre alrededor del cierre. |

get_or_create_invoice_for_medical_record bloquea el MR, reutiliza primero la Invoice de la cita y la enlaza; de otro modo hace get_or_create por medical_record (backend/apps/billing/services.py:791-832). Las OneToOne evitan dos facturas por cita/MR en el camino normal, pero hay múltiples momentos de creación. Las rutas no son duplicados técnicos gracias a get_or_create; sí son **redundantes semánticamente** porque nadie puede afirmar que “el cierre crea/envía el cobro”.

El writer automático no asigna created_by cuando el objeto nace mediante get_or_create. Por ello “quién creó el cobro” no siempre puede reconstruirse desde Invoice, aunque las acciones posteriores tengan actor.

### 3.2 Clasificación de draft por contexto

| Pregunta | Consulta abierta / primer cargo | Cierre de consulta | Appointment done automático | POS |
| --- | --- | --- | --- | --- |
| ¿Quién lo construye? | Veterinario asignado/ADMIN mediante datos clínicos | Sistema; recepción debería revisar | Sistema/signal | Operador de POS |
| ¿Puede cambiar el importe? | Sí, al agregar/eliminar servicios/productos | Sí, sobre todo receta aceptada; API también permite más | Sí, si alguien agrega items | Sí, hasta cobrar |
| ¿Cliente presente? | Probablemente, no es invariante | Normalmente sí, no garantizado | No garantizado | Sí |
| ¿Atención terminó? | No | Sí | No necesariamente | No aplica |
| ¿Obligación real? | No necesariamente | Servicios/consumos charge sí; receta opcional no | No necesariamente | Carrito aún no cobrado |
| ¿Usuario necesita ver “draft”? | No necesariamente en Cobros | Necesita “por preparar/listo”, no tecnicismo | Solo si hay tarea operativa real | Necesita carrito/checkout, no documento financiero |
| ¿Puede abandonarse? | Sí, queda visible | Sí, sin owner/SLA | Sí | Sí al cerrar/refrescar antes de back |
| ¿Puede quedar $0? | Sí | Sí, obligatorio incluso sin cargos | Sí | No normalmente; confirm exige item |
| ¿Quién finaliza? | No está asignado | Cualquiera con confirm: ADMIN/VET/ASSISTANT | Igual | Cualquiera con pay desde POS |
| ¿Tiene sentido persistente? | Como agregado de sincronización, quizá; como obligación, no | Sí como checkout/tarea, no siempre como Invoice financiera | Débil sin items/readiness | Solo si se necesita reanudación/auditoría; de otro modo sesión transitoria |

Conclusión: la hipótesis “draft solo existe mientras recepción decide qué productos llevará el cliente” explica una parte útil del flujo, pero no el comportamiento completo. draft también nace antes del cierre, por included, por configuración de citas y como protocolo técnico del POS. Debe separarse la preparación editable de la existencia de un documento financiero.

### 3.3 Writers de status y anchors

| Writer | Antes | Después | Anchors/efectos |
| --- | --- | --- | --- |
| Invoice model/default y creators | inexistente | draft | Sin anchor de lifecycle; totales inicialmente cero |
| _confirm_locked_invoice | draft | confirmed | confirmed_at/source, audit log, validación y stock de venta |
| _mark_invoice_paid | confirmed | paid | paid_at/source, payment_method derivado, audit log |
| pay_direct_sale | draft | confirmed → paid | Ejecuta ambos writers en una transacción |
| cancel_invoice | draft/confirmed | cancelled | cancelled_at/source, audit log; restock si venía confirmed |
| process_refund | paid | paid | CreditNote, CreditNoteItem, RefundPayment, ajuste analytics; no cambia status |
| PATCH genérico de Invoice | draft | potencialmente campo status/tipo enviado | View solo comprueba estado previo; serializer expone campos. Los CHECK de anchors bloquean parte de los estados, no expresan transición. |

InvoiceAuditLog solo registra cambios de status, actor, notas y momento (models.py:383-394). No registra mutaciones de items, cambios de tipo/lote, decisión de no comprar receta ni el momento clínico que originó cada línea.

## 4. Flujos reales

### 4.1 Consulta → Cobros

~~~text
Appointment
  │ inicio/creación de MedicalRecord
  ▼
MedicalRecord OPEN
  │
  ├─ servicio clínico ───────────────▶ Invoice draft + InvoiceItem(service)
  │
  ├─ producto charge ────────────────▶ MedicalRecordProduct + stock clínico
  │                                    + Invoice draft + InvoiceItem(presentation)
  │
  ├─ producto included ──────────────▶ MedicalRecordProduct + stock clínico
  │                                    + Invoice draft SIN item de cargo
  │
  └─ Prescription/PrescriptionItem ──▶ sugerencia; SIN InvoiceItem y SIN stock

close_medical_record
  ├─ MedicalRecord CLOSED + closed_at
  ├─ obtiene/crea Invoice (permanece draft, incluso $0)
  ├─ materializa protocolos/vacunas
  └─ Appointment in_progress → done (sin signal)

Cobros
  ├─ selecciona subconjunto de receta → InvoiceItem con provenance FK
  ├─ confirm → confirmed + stock retail + devengo + freeze
  └─ pay exacto → Payment(s) + paid + ingreso cobrado
~~~

| Paso | Actor real | Endpoint/service | Modelo/estado | Efectos secundarios |
| --- | --- | --- | --- | --- |
| Crear/completar cita | Roles de appointments | appointments views/services | Appointment | Signal solo si save a done y toggle activo |
| Abrir consulta | VET/ADMIN | medical_records views | MedicalRecord open | Puede enlazar Appointment |
| Agregar servicio | VET asignado/ADMIN | MedicalRecordServiceListCreateView | MRS + Invoice draft/item | Recalcula total; si Invoice no draft omite sync |
| Agregar producto | VET asignado/ADMIN | add_medical_record_product | MRP + quizá item | Stock clínico inmediato; cost_behavior decide cargo |
| Recetar | VET/ADMIN clínico | prescription endpoints | Prescription/Items | No stock/cargo automático |
| Cerrar | VET asignado/ADMIN | close_medical_record | MR closed; Invoice sigue draft | Invoice siempre; cita done; protocolos |
| Dispensar | ADMIN/VET; ASSISTANT solo sin restricción Rx | dispense endpoint | InvoiceItem draft | Aún no stock; cap por cantidad prescrita |
| Confirmar | ADMIN/VET/ASSISTANT | confirm endpoint/service | draft → confirmed | Stock retail, audit, confirmed_at, revenue accrual |
| Registrar pago | ADMIN/VET/ASSISTANT | pay endpoint/service | confirmed → paid; Payment N | Full exacto, caja, idempotencia, paid_at |

No existe un “analytics anchor” de “enviado a Cobros”. Los anchors relevantes son closed_at clínico, confirmed_at devengo y paid_at caja; pueden ocurrir en un orden semánticamente inválido porque confirm no comprueba closed_at.

### 4.2 Venta directa

~~~text
POS local cart
  │ POST Invoice direct_sale
  ▼
Invoice draft
  │ POST item 1 ... item N (multipetición)
  ├─ error / volver al carrito → cancelled
  └─ Cobrar / direct-pay
       ├─ _confirm_locked_invoice → confirmed + stock
       ├─ Payment(s)
       └─ paid
~~~

La diferencia válida respecto a consultation es la procedencia y el stock:

- direct_sale asienta todos los InvoiceItem con presentation al confirmar;
- consultation solo asienta los items de receta/retail identificados por dispensed_from_prescription_item; el producto clínico ya se consumió al crear MedicalRecordProduct;
- direct_sale exige atestación de receta externa al crear un producto Rx;
- consultation tiene relación clínica y suggestions.

La diferencia no justifica dos máquinas. direct-pay oculta el estado intermedio porque el caso normal es pago inmediato. El endpoint genérico permite de todos modos el camino draft → confirmed → paid para direct_sale.

### 4.3 Receta y decisión del cliente

~~~text
PrescriptionItem
  │ genera suggestion derivada
  │ no cargo / no stock
  ▼
Recepción selecciona presentación + cantidad
  │ puede elegir todo, parte o nada
  ▼
dispense_prescription_into_invoice
  │ crea/incrementa InvoiceItem con FK de provenance
  │ Invoice debe seguir draft
  ▼
confirm
  │ valida cap/stock y descuenta stock
  ▼
paid o cancelled (cancel restock)
~~~

Respuestas obligatorias:

1. **La receta no crea InvoiceItem automáticamente.** Solo la dispensación explícita lo hace.
2. **La receta no genera movimiento de stock.** El movimiento ocurre al confirmar la Invoice que contiene la dispensación.
3. **Si el cliente no quiere el medicamento**, recepción lo deja sin seleccionar; no se persiste un rechazo.
4. **Puede comprar solo parte**, por subconjunto de líneas y por quantity menor al máximo prescrito.
5. **Recepción puede agregarlo después** mientras Invoice siga draft y tenga permiso; el cap considera dispensaciones previas.
6. **Puede quitarlo antes de pagar por API DELETE**, pero la pantalla de billing no expone borrar/editar items.
7. **Invoice debe estar draft** durante la decisión. confirmed bloquea dispensar, editar o eliminar.
8. **Stock se descuenta al confirmar**, no al crear la sugerencia ni la línea draft.
9. **Si ya está confirmed**, no puede cambiar la aceptación; habría que cancelar si no hay Payments y reconstruir otro flujo, o cobrar algo que ya no coincide con la decisión.
10. **confirmed dificulta el flujo si se pulsa antes de terminar la conversación con el cliente.** El problema es la ausencia de precondición/readiness, no la congelación en sí.

Hay dos problemas adicionales:

- Si una presentación ya existe como línea clínica sin provenance de receta, dispense rechaza la colisión y pide “ajustar su cantidad directamente en factura”; la UI no ofrece tal ajuste.
- PrescriptionDispensePanel selecciona por defecto todos los sugeridos disponibles y mantiene estado local con key estable tras refrescar la misma Invoice. Una segunda acción puede reenviar selecciones obsoletas hasta que el cap del servidor las rechace. Para una decisión opcional, el default debería ser consentimiento explícito, no opt-out.

### 4.4 Consumo clínico frente a producto vendido

| Concepto | Modelo fuente | cost_behavior | Cargo | Momento de stock | Cómo se distingue en Invoice |
| --- | --- | --- | --- | --- | --- |
| Servicio clínico | MedicalRecordService | N/A | Sí | N/A | InvoiceItem.service, pero sin FK al MRS concreto |
| Producto utilizado y cobrado | MedicalRecordProduct | charge | Sí | Al crear MRP | InvoiceItem.presentation sin provenance clínica explícita |
| Insumo incluido | MedicalRecordProduct | included | No | Al crear MRP | No hay InvoiceItem |
| Medicamento vendido desde receta | PrescriptionItem + dispensación | N/A | Sí | Al confirmar Invoice | InvoiceItem.presentation + dispensed_from_prescription_item |
| Producto POS | Solo InvoiceItem | N/A | Sí | Al confirmar Invoice | presentation; invoice_type direct_sale |

dispensed_from_prescription_item está sobrecargado: sirve a la vez de provenance, cap de receta y discriminador de si una línea consultation debe mover stock. Las líneas de producto clínico cobradas no enlazan al MedicalRecordProduct que las originó. Las líneas de servicio tampoco enlazan al MedicalRecordService. Esto mezcla consumo, cargo y venta en una estructura que puede ser mutada sin saber qué agregado es dueño de ella.

### 4.5 Pago y ledger

~~~text
Invoice.total
  - Σ Payment.amount
  = remaining_balance

pay_invoice:
  exige Payment lines no vacías, cada amount > 0
  exige Σ líneas = remaining_balance completo
  crea un Payment por método
  si saldo <= 0 marca paid
~~~

No existe modelo PaymentLine. “payment_lines” es el payload y componente de UI; cada forma de pago se persiste como Payment independiente. _pay_locked_invoice conserva un parámetro require_full=False y PaymentLinesEditor tiene copy de pago parcial, pero todos los comandos públicos actuales pagan completo. Una solicitud parcial se rechaza antes de crear Payment, por lo que la Invoice permanece confirmed.

### 4.6 Cancelación y devolución

~~~text
draft ── cancel ──▶ cancelled
  sin Payment; sin stock retail asentado

confirmed ── cancel ──▶ cancelled
  sin Payment; revierte exactamente los items que asentaron stock

paid ── cancel ──▶ prohibido
paid ── refund ──▶ paid + CreditNote + RefundPayment
                    + restock/discard por línea
                    + ajuste negativo revenue_paid
~~~

El producto clínico consumido no se restockea al cancelar una Invoice consultation: correctamente pertenece al acto clínico, no a la venta. En devoluciones de una factura paid, process_refund puede restockear cualquier InvoiceItem con presentation según disposition; la factura original conserva status paid y el neto analítico se corrige con MetricAdjustment (backend/apps/billing/services.py:574-702).

cancelled es por ello un lifecycle terminal útil, pero su nombre debe dejar claro que es **anulación previa al cobro**. No reemplaza la devolución.

## 5. Frontend vs backend

### 5.1 Acciones visibles y operaciones reales

| Superficie | Lo que comunica/permite | Backend real | Discrepancia e impacto |
| --- | --- | --- | --- |
| Consulta cerrada | “Consulta finalizada y enviada a Cobros”; informa un borrador | La Invoice pudo crearse desde el primer cargo o signal. close solo hace get_or_create y no cambia status | “Enviar” no es un evento auditable; Cobros puede ver casos todavía abiertos |
| Billing, consultation draft | Botón “Confirmar” | Congela, descuenta stock retail y reconoce devengo; no comprueba MR cerrado | CTA subexplica una acción financiera/material y admite ejecución prematura |
| Billing, confirmed | “Registrar Pago” | Solo pago completo exacto; crea uno o varios Payment | Coherente en intención, pero la separación Confirmar/Pagar no corresponde a actores distintos |
| Billing, direct_sale draft | “Cobrar” | direct-pay confirma y paga internamente | UX más coherente para pago inmediato que consultation; el dominio sigue creando confirmed |
| Billing, items draft | Lista read-only | API permite POST/PATCH/DELETE | Recepción no puede quitar o corregir un medicamento después de agregarlo; el propio error de colisión recomienda una acción no disponible |
| PrescriptionDispensePanel | Medicamentos “opcionales” | Todos los sugeridos disponibles nacen seleccionados | Opción comercial opt-out; eleva riesgo de cobrar lo que el cliente no aceptó |
| Panel tras dispensar | Refresca la misma Invoice | key usa el mismo public_id; el estado inicial local puede no recomputarse | Selección obsoleta y reintentos confusos; el servidor limita la sobre-dispensación, pero no previene mala UX |
| Billing | No expone “Cancelar” | cancel existe para draft y confirmed | Casos abandonados o $0 no tienen salida visible |
| PaymentLinesEditor | Tiene modo parcial y texto “quedará confirmada con saldo pendiente” | Billing siempre pasa allowPartial=false y pay exige full | Capacidad muerta/contrato engañoso |
| POS, volver/error | Cancela la Invoice draft | cancel es auditable y correcto | Si el navegador se cierra o refresca antes de esa acción, queda un draft huérfano sin resume/expiry |
| Configuración | “Factura automática” al completar cita | Toggle controla signal save(done), pero cierre de MR siempre crea Invoice y completa cita con QuerySet.update | Configuración solo afecta un camino lateral; su alcance no es comprensible |
| Analytics | Devengado: “Servicio rendido” | Suma status confirmed/paid por confirmed_at | confirmed puede preceder al cierre y direct_sale no es un servicio clínico rendido |

Evidencia de frontend: frontend/src/pages/billing.jsx:640-692, 749, 906, 958, 966-978; frontend/src/pages/pos/index.jsx:103-196; frontend/src/pages/analytics/index.jsx:22,338; frontend/src/api/billing.js; frontend/src/pages/medicalRecords/ConsultationForm.jsx:165,666-686,787,977.

### 5.2 Permisos visibles y efectivos

Los botones principales de billing se deciden principalmente por status e invoice_type, no por una separación de responsabilidad fina. Esto no produce una elevación sobre RBAC porque backend comprueba permisos; el problema es que el catálogo RBAC concede las mismas operaciones financieras a VET y ASSISTANT. La UI, por tanto, reproduce la ambigüedad real del dominio.

### 5.3 Discrepancias de documentación

| Fuente secundaria | Afirmación/intención | Código actual | Veredicto |
| --- | --- | --- | --- |
| ADR de lazy invoice creation, docs/decisions/2026-05-05-p7-lazy-invoice-creation.md | Invoice bajo demanda | close_medical_record siempre la garantiza, incluso sin cargos; también hay signal de done | Parcialmente obsoleta |
| ADR/contratos del payment ledger p27 | Arquitectura conserva noción de parcialidad | pay_invoice fuerza total exacto; no hay endpoint parcial | Código y tests actuales ganan |
| Comentarios de _pay_locked_invoice y frontend billing API | Sugieren pago parcial/split | Split por método sí; parcial del saldo no | Naming/documentación ambigua |
| ADR p32 cost behavior | Distingue insumo incluido vs cobrado; documentación de UX asociada favorece included | ConsultationForm inicializa y reinicia productLine.cost_behavior como charge | Default operativo real es charge |
| Módulos/flujo documentado | Cierre “envía” a billing | No existe transición ni anchor de envío | Narrativa, no contrato |
| Caption analytics | confirmed_at equivale a servicio rendido | No hay guard de cierre y aplica a direct_sale | Semántica incorrecta |

## 6. Roles y responsabilidades

### 6.1 Matriz real

| Acción | ADMIN | VET | ASSISTANT | Actor esperado en diseño recomendado |
| --- | --- | --- | --- | --- |
| Crear Invoice manual | Sí | Sí | Sí | Sistema/check-out; excepcionalmente recepción |
| Definir servicio clínico | Sí | Sí, si asignado | No | Veterinario responsable |
| Definir producto consumido/cost_behavior | Sí | Sí, si asignado | No | Veterinario responsable |
| Modificar cargos clínicos | Sí mientras MR abierto | Sí, si asignado y MR abierto | No | Veterinario; recepción no altera hechos clínicos |
| Agregar/quitar producto retail/receta en Invoice | Sí | Sí | Sí para casos no Rx; Rx requiere permiso adicional | Recepción/dispensador autorizado |
| Modificar cualquier InvoiceItem draft | Sí | Sí | Sí | Solo dueño de la fuente; no mutación libre |
| Confirmar/postear | Sí | Sí | Sí | Caja/recepción; o comando atómico de cobro |
| Dispensar receta | Sí | Sí con billing.rx_dispense | Condicionado; no Rx restringido | Personal autorizado, con aceptación del cliente |
| Registrar pago | Sí | Sí | Sí | Caja/recepción |
| Cancelar antes de pago | Sí | Sí | Sí | Caja/supervisor según política |
| Emitir devolución | Sí | No | No | ADMIN/supervisor |
| Cerrar consulta | Sí | Sí, si asignado | No | Veterinario responsable |

Fuente: backend/apps/core/permissions_codes.py:145-220 y backend/apps/medical_records/policies.py:33-73.

### 6.2 Diagnóstico de responsabilidad

El código sí expresa “veterinario define lo clínico”: can_modify_medical_record_charges y can_close_medical_record exigen MR abierto, tenant y ownership para VET. Pero esa separación se pierde al materializar la Invoice:

- VET y ASSISTANT reciben invoice.create, invoice.destroy, invoice.confirm, invoice.pay e invoice.cancel.
- invoice.create se reutiliza para PATCH de items, por lo que ambos pueden cambiar líneas de cualquier origen.
- No hay permiso separado para “ajustar retail”, “postear receivable” o “cobrar”.
- No hay campo de responsable del checkout ni handoff explícito.

La matriz objetivo no exige necesariamente cuatro roles de sistema distintos. Sí exige que la **propiedad de cada dato** sea inequívoca:

~~~text
Veterinario ── posee hechos clínicos y cost_behavior
Recepción   ── posee selección retail aceptada y preparación del checkout
Caja        ── posee finalización financiera y Payments
Supervisor  ── posee void/refund excepcionales
~~~

Un mismo usuario puede desempeñar varias funciones en una clínica pequeña; la acción y el permiso deben seguir siendo conceptualmente diferentes para auditoría.

## 7. Analytics y anchors

### 7.1 Consumidores reales

| Anchor/condición | Consumidor | Métrica/efecto | Qué se perdería al eliminarlo |
| --- | --- | --- | --- |
| confirmed_at + status confirmed/paid | compute_daily_metrics | revenue_accrual | Momento de devengo histórico |
| confirmed + remaining implícito | dashboard ADMIN | cuentas por cobrar/outstanding | Bandeja/importe de receivables |
| paid_at + status paid | compute_daily_metrics | revenue_paid | Momento de caja/ingreso cobrado |
| paid Invoice + refund occurred_at | MetricAdjustment | neto de revenue_paid | Ajuste de devoluciones |
| cancelled_at | constraints, provenance/health, tests | Trazabilidad de anulación; no KPI central visible | Momento de void |
| closed_at de MedicalRecord | clinical analytics/flujo | Fin clínico | No está enlazado como precondición de devengo |

compute_daily_metrics suma revenue_paid sobre paid_at y revenue_accrual sobre confirmed_at para status confirmed o paid (backend/apps/analytics/services.py:198-323). Dashboard calcula outstanding sobre confirmed (backend/apps/dashboard/views.py:650-695). Los snapshots y provenance distinguen source de anchors; las devoluciones no reescriben snapshots congelados, sino que añaden MetricAdjustment.

### 7.2 ¿confirmed_at es útil?

Sí, **el momento de devengo/posteo es útil** si el producto soporta cuentas por cobrar o separación entre prestación y cobro. Lo que no está demostrado es que el evento actual sea válido:

- puede ocurrir con MR open;
- puede representar una venta directa todavía no pagada;
- no prueba revisión por recepción ni aceptación del cliente;
- en direct-pay ocurre milisegundos antes de paid_at solo por implementación.

Eliminar confirmed sin migrar ese anchor cambiaría revenue_accrual, outstanding, snapshots, índices, pruebas de late arrival y trazabilidad. La alternativa correcta es conservar el hecho como posted_at/finalized_at y definir su precondición, aunque el estado financiero visible se derive de Payments.

### 7.3 Payment frente a status

Payment aporta información que confirmed no puede aportar: método, importe, referencia, cash session, actor, provenance e idempotencia. A su vez, la existencia de Invoice + items + total + Payments permite derivar:

~~~text
unpaid: total > 0 y suma de pagos = 0
partial: 0 < suma de pagos < total
paid: suma de pagos = total
overpaid: suma de pagos > total, estado inválido
~~~

El código público solo produce unpaid o paid, nunca partial. Por eso paid puede ser una proyección de ledger; conservarlo almacenado es razonable para consultas y constraints siempre que se valide contra el ledger. confirmed no añade información de saldo; añade posteo/freeze/stock.

### 7.4 Impacto exacto de eliminar confirmed sin reemplazo

Habría que modificar, como mínimo:

- choices, CHECK constraints, índices y datos de Invoice;
- confirmed_at y confirmed_at_source;
- _confirm_locked_invoice, confirm_invoice, pay_invoice, direct-pay, cancel y stock settlement;
- permisos invoice.confirm, rutas y serializers;
- audit_payment_ledger_integrity y pruebas de state machine;
- revenue_accrual, outstanding, snapshots, provenance y late-arrival health;
- botones/labels/modal de billing, PaymentLinesEditor y POS;
- PDF/serialización si muestran posteo;
- docs/ADR y contratos externos.

La pérdida analítica no justifica conservar un status ambiguo; sí obliga a modelar explícitamente el evento que hoy contiene.

## 8. Casos de uso

### Caso 1 — Consulta con servicio

~~~text
VET agrega MedicalRecordService
→ get/create Invoice draft
→ InvoiceItem(service), total recalculado
→ close: MR closed, Invoice sigue draft
→ Confirmar: confirmed_at/devengo/freeze
→ Registrar pago completo: Payment(s), paid_at, paid
~~~

No hay stock. La línea no guarda FK al MedicalRecordService concreto. Si se confirma antes de close, servicios posteriores no sincronizan. Resultado esperado recomendado: el servicio clínico queda bajo ownership clínico; al cerrar se prepara checkout; cobro normal finaliza+paga atómicamente.

### Caso 2 — Consulta con producto consumido charge

~~~text
MRP charge
→ stock baja inmediatamente por consumo clínico
→ Invoice draft + item presentation
→ confirm NO vuelve a bajar stock porque no tiene provenance de dispensación
→ pay
~~~

El resultado normal es correcto gracias a _items_settling_stock, pero depende de una inferencia frágil: “consultation + presentation sin dispensed FK” significa consumo ya asentado. Cambiar tipo/provenance por PATCH puede duplicar u omitir stock.

### Caso 3 — Consulta con insumo included

~~~text
MRP included
→ stock clínico baja
→ Invoice draft se crea
→ no InvoiceItem
→ close mantiene draft $0
→ confirm rechaza: no hay items
~~~

Estado actual: documento visible y sin resolución en UI. Producto: el consumo debe permanecer en costo clínico/inventario, pero no necesita una Invoice financiera. Puede registrarse como visita sin cargo o checkout completado $0.

### Caso 4 — Receta completa aceptada

~~~text
Prescription → no cargo/no stock
→ close
→ recepción deja todas las líneas seleccionadas y dispensa
→ InvoiceItem(s) con provenance
→ confirm: stock baja
→ pay: paid
~~~

Soportado. Riesgo: “todas seleccionadas” es default, no aceptación positiva. Debe confirmarse explícitamente el subconjunto y total antes de finalizar.

### Caso 5 — Receta parcialmente aceptada

~~~text
recepción desmarca productos o reduce quantity
→ dispense solo el subconjunto
→ cap del backend impide exceder receta
→ confirm/pay
~~~

Soportado antes de confirm. No se persiste qué fue rechazado, solo qué fue dispensado. Tras agregar una línea, la UI no permite editar/quitarla; por API sí. El remanente puede seguir apareciendo como sugerencia.

### Caso 6 — Receta rechazada

~~~text
recepción no selecciona nada
→ no endpoint de rechazo, no cargo, no stock
→ si hay otros cargos: confirm/pay esos cargos
→ si no hay otros cargos: Invoice draft $0 varada
~~~

La receta clínica conserva validez, lo cual es correcto. Falta un evento opcional declined/not_purchased si producto necesita distinguir “pendiente” de “rechazada”.

### Caso 7 — Consulta sin cargos

Estado real:

- close crea Invoice draft de total cero;
- sin items, confirm falla;
- con un item de precio cero, confirm puede producir confirmed $0;
- Payment exige amount > 0, así que no se puede “pagar $0”;
- billing no muestra cancelar.

Alternativas de producto:

| Alternativa | Ventaja | Consecuencia |
| --- | --- | --- |
| No crear Invoice si total = 0 y no hay items cobrables | Semántica financiera limpia | Se necesita otra marca de “consulta cerrada/sin cargo” |
| Crear Receipt/Invoice $0 ya finalizada | Documento entregable y numeración | Debe definirse que no requiere Payment y excluirse de AR |
| Mantener checkout no financiero hasta resolver receta | Permite decisión posterior | No debe aparecer como deuda ni quedar indefinido |
| Mantener draft actual | Sin migración | Conserva basura operacional y estados irresolubles |

Recomendación: no crear documento financiero $0 por defecto. Guardar outcome “no charge” en el checkout/consulta; si legalmente se requiere comprobante $0, finalizarlo sin Payment mediante regla explícita.

### Caso 8 — Cliente abandona antes de pagar

Puede quedar:

- draft: editable, no AR/devengo, sin owner/SLA/expiry; en POS puede ser huérfano;
- confirmed: congelado, stock descontado y reconocido como AR/devengo, aunque no exista aceptación/política de crédito.

No hay estado “cliente volverá”, promesa de pago, vencimiento ni responsable. La acción correcta depende del negocio: “guardar checkout” no debe devengar; “dejar cuenta por cobrar” debe ser una decisión explícita con responsable/due date; “abandonado” debe permitir void con razón.

### Caso 9 — Pago parcial

El modelo matemático y _pay_locked_invoice podrían representarlo, y PaymentLinesEditor conserva copy para ello. El endpoint público pay_invoice fija require_full=True. Si las líneas no cubren remaining_balance completo, se rechaza la operación y no se crea Payment; status queda confirmed.

Por tanto **el producto actual no soporta pagos parciales**, aunque remaining_balance, comentarios y componentes sugieran que sí. Antes de habilitarlos se requieren política de AR, reembolsos por asignación, UI de saldo, cash session e invariantes de concurrencia.

### Caso 10 — Venta directa

~~~text
carrito local
→ POST Invoice draft direct_sale
→ POST items
→ direct-pay
   → confirm/stock/audit/confirmed_at
   → Payments
   → paid/paid_at
~~~

Back/error cancela. direct-pay es idempotente y transaccional respecto a finalización+pago, pero la construcción previa no es atómica. El status draft es aquí principalmente una fase técnica persistida. Si se conserva, necesita ownership, resume y limpieza; una alternativa es persistir CheckoutSession y crear Invoice solo al cobrar.

## 9. Hallazgos

| ID | Severidad | Hallazgo | Evidencia | Impacto |
| --- | --- | --- | --- | --- |
| BIL-001 | CRÍTICO | Se puede confirmar consultation con MedicalRecord abierto; cambios clínicos posteriores omiten sincronización por no estar draft | billing/services.py:145-218; medical_records/views.py:223-316; inventory/views.py:543-614; test_prescription_dispense.py confirma un MR open | Subcobro/sobrecobro, divergencia clínica-financiera y stock incongruente |
| BIL-002 | CRÍTICO | PATCH de InvoiceItem permite cambiar service/presentation/lote sin repetir validaciones de creación, receta externa o asentamiento | billing/serializers.py:74-209; billing/views.py:410-491 | Elusión Rx, producto/lote incorrecto, stock omitido o doble |
| BIL-003 | CRÍTICO | PATCH de Invoice expone invoice_type y relaciones; cambiar consultation ↔ direct_sale altera qué items mueven stock | billing/serializers.py:212-446; billing/views.py:152-190; _items_settling_stock services.py:82-102 | Doble consumo u omisión de stock; factura con provenance contradictoria |
| BIL-004 | ALTO | Líneas clínicas no tienen FK de ownership a MedicalRecordService/Product y pueden mutarse/borrarse como items genéricos | billing/models.py:231-380; item detail views | Pérdida del cargo o separación del hecho clínico sin audit trail |
| BIL-005 | ALTO | close crea Invoice $0 siempre; sin items no confirma y con item $0 no puede pagarse | medical_records/views.py:438-559; services.py:145-218, 225-250 | Cobros varados, bandeja contaminada, operación manual imposible |
| BIL-006 | ALTO | confirmed acopla freeze, stock, devengo y readiness sin exigir cierre ni aceptación | services.py:145-218; analytics/services.py:198-323 | Evento financiero prematuro y semántica no confiable |
| BIL-007 | ALTO | Receta opcional nace completamente seleccionada y las líneas añadidas no se pueden editar/quitar en UI | billing.jsx:283-471,906,958 | Riesgo de cobrar/dispensar productos no aceptados y bloqueos operativos |
| BIL-008 | ALTO | VET y ASSISTANT comparten crear/editar/confirmar/pagar/cancelar | core/permissions_codes.py:145-220 | Sin segregación de responsabilidad ni auditabilidad del handoff |
| BIL-009 | ALTO | La API acepta confirmar direct_sale por dos caminos y la UX presenta máquinas distintas | confirm service sin guard de type; pay_direct_sale:499-550; billing.jsx:966-978 | Contrato ambiguo, más transiciones/pruebas y operación no uniforme |
| BIL-010 | ALTO | Servicios/productos clínicos se guardan aunque la Invoice ya no sea draft y la sincronización se omite | medical_records/views.py:223-316; medical_records/services.py:48-98; inventory/views.py:559-614 | Factura congelada deja de representar la atención |
| BIL-011 | ALTO | status, invoice_type y FKs de Invoice son escribibles en serializer genérico; DB produce parte de la validación | billing/serializers.py:212-446; models.py:217-225 | Estados imposibles, errores 500 potenciales y bypass del service |
| BIL-012 | ALTO | “Enviada a Cobros” no existe como transición; Invoice puede aparecer mientras consulta está abierta | get_or_create callers; ConsultationForm.jsx:977 | Recepción no sabe si el importe está listo ni quién es responsable |
| BIL-013 | MEDIO | auto_create_invoice_on_done afecta solo save(done); cierre siempre crea Invoice y evita signal | billing/signals.py:10-59; appointments/services.py:553-625; organizations/models.py:73-92 | Toggle de alcance engañoso, drafts prematuros/redundantes |
| BIL-014 | MEDIO | Pago parcial está insinuado pero no soportado por endpoints | services.py:331-374,452-491; PaymentLinesEditor.jsx | Expectativas falsas y código muerto |
| BIL-015 | MEDIO | No existe PaymentLine persistente; cada allocation se guarda como Payment | billing/models.py:397-476 | Nomenclatura induce un modelo mental incorrecto |
| BIL-016 | MEDIO | Append-only de Payment depende de ausencia de endpoints, no de protección model/DB | billing models/views | Mutación administrativa puede invalidar ledger y paid |
| BIL-017 | MEDIO | DB no impone paid ↔ saldo cero ni ausencia de Payments en draft/cancelled | Invoice constraints; audit_payment_ledger_integrity | Corrupción fuera del happy path solo se detecta a posteriori |
| BIL-018 | MEDIO | POS puede abandonar Invoice draft entre creación/items y direct-pay | pos/index.jsx:103-196 | Drafts huérfanos, inventario no afectado pero bandeja/auditoría ruidosa |
| BIL-019 | MEDIO | InvoiceAuditLog solo registra status; no mutación de items, origen ni decisión de receta | billing/models.py:383-394 | No se reconstruye quién cambió el importe |
| BIL-020 | MEDIO | Rechazo total/parcial de receta no se persiste | dispense service + panel | No distingue pendiente de “cliente no compró”; sugerencias recurrentes |
| BIL-021 | MEDIO | Analytics etiqueta confirmed como “servicio rendido” aunque no exige cierre y aplica a POS | analytics/services.py; analytics/index.jsx:22 | KPIs de devengo y comunicación financiera engañosos |
| BIL-022 | MEDIO | Billing no ofrece cancelar aunque backend lo soporta | billing.jsx:966-978; cancel service | Sin salida visible para error, abandono o borrador $0 |
| BIL-023 | MEDIO | Default UI de cost_behavior es charge, contrario a expectativas documentales de seguridad de “included” | ConsultationForm.jsx:165,787; ADR p32 | Sobrecobro por default si el usuario no revisa el selector |
| BIL-024 | BAJO | Writers automáticos con get_or_create no fijan created_by | billing/services.py:791-832 | Provenance de creación incompleta |
| BIL-025 | BAJO | Anchors confirmed_at/cancelled_at no están expuestos consistentemente por serializer/UI | InvoiceSerializer y billing UI | Menor explicabilidad operativa de cuándo ocurrió cada evento |
| BIL-026 | BAJO | La suite de close cubre cierre e idempotencia, pero no afirma exhaustivamente semántica de $0/readiness | medical_records/tests/test_close.py y suite focalizada | Regresiones de producto pueden pasar con máquina técnicamente válida |

### 9.1 Priorización

Antes de discutir una migración estética de nombres, deben cerrarse BIL-001, BIL-002, BIL-003 y BIL-010. Son problemas de invariantes y ownership que seguirían existiendo incluso si draft/confirmed se renombran. Después, la decisión de lifecycle debe resolver BIL-005 a BIL-009 y BIL-012 como un único rediseño de checkout, no como parches de botones.

## 10. Decisión recomendada

~~~text
draft     [REDEFINIR]
confirmed [REDEFINIR]
paid      [CONSERVAR]
cancelled [REDEFINIR]
~~~

### 10.1 draft — REDEFINIR

**Definición recomendada:** preparación/check-out editable, sin reconocimiento financiero y sin pretensión de ser una deuda. Debe tener owner, origen, momento de readiness y política de abandono. Puede persistirse, pero no necesariamente dentro de Invoice.

Por qué no se recomienda eliminarlo de inmediato:

1. La aceptación parcial de receta necesita una ventana editable.
2. El ensamblado POS actual usa varias peticiones y necesita rollback/reintento.
3. Items deben congelarse en algún límite antes de stock/pago.
4. Cancelación y concurrencia necesitan identificar qué agregado se está cerrando.

Por qué no se recomienda conservarlo tal cual:

1. No representa un solo estado de negocio.
2. Nace demasiado pronto y por demasiados writers.
3. Se presenta en Cobros aunque no esté listo.
4. Puede quedar abandonado o en $0 sin resolución.
5. Es la única barrera de edición, pero no expresa ownership de línea.

Evaluación contra el criterio de eliminación:

| Criterio | Resultado |
| --- | --- |
| No representa estado útil | Parcial: preparación sí es útil; el status financiero draft no |
| Puede sustituirse claramente | Sí, por Checkout/preparing + Invoice emitida al finalizar |
| No rompe edición | Requiere migrar edición al checkout |
| No rompe POS | Requiere comando atómico o CheckoutSession reanudable |
| No rompe dispensación | Requiere que selección de receta viva en checkout |
| No rompe stock | Requiere preservar settlement clínico vs retail por source explícito |
| No rompe auditoría/analytics | draft no devenga, pero hay que migrar provenance/abandono |
| No rompe concurrencia | Requiere locking/versioning equivalente |
| No rompe cancelación | Checkout se abandona; Invoice emitida se voida |
| No genera facturas ambiguas | La separación precisamente elimina esa ambigüedad |

Conclusión: **el concepto editable se conserva; su representación como Invoice.status = draft debe quedar como decisión de implementación posterior**.

### 10.2 confirmed — REDEFINIR

**Definición recomendada:** posted/unpaid, es decir, obligación económica real, inmutable, con posted_at, cuyo total todavía no está liquidado. No debe significar “alguien pulsó Confirmar”.

Información de negocio que sí justifica el concepto:

- existe una cuenta por cobrar;
- el importe quedó fijado;
- el ingreso fue devengado según política;
- stock de retail fue entregado/asentado;
- hay un momento histórico independiente de paid_at.

La transición confirmed → paid solo es necesaria **cuando se permite emitir una obligación y cobrar después**. No es necesaria como dos CTAs consecutivos para el caso de pago inmediato. En el flujo normal, un único comando Cobrar debe finalizar el checkout, asentar stock, crear Payment y dejar la Invoice paid atómicamente. “Dejar pendiente” debe ser el comando excepcional que crea posted/unpaid.

Si negocio confirma que nunca concede crédito, no mantiene cuentas por cobrar y no necesita devengo separado de caja, la recomendación cambiaría a ELIMINAR confirmed y conservar solo un finalized_at dentro del cobro atómico. El código actual de revenue_accrual y outstanding indica que hoy sí existe intención de receivable, aunque esté mal modelada.

Evaluación de eliminación:

| Pregunta | Resultado |
| --- | --- |
| ¿Expresa información no disponible en otro lugar? | Sí: posteo/devengo, freeze y settlement de stock; no: saldo/pago |
| ¿Es necesario como paso manual antes de todo pago? | No; direct-pay ya prueba que puede ser interno y atómico |
| ¿Puede ser condición derivada? | El saldo sí; el momento de posteo no |
| ¿Puede ser evento en vez de status? | Sí, posted_at/finalized_at con lifecycle documental |
| ¿Eliminarlo rompe stock? | Sí si no se reubica settlement |
| ¿Eliminarlo rompe analytics/AR? | Sí si no se migra confirmed_at y outstanding |
| ¿Eliminarlo rompe cancelación? | Sí si void no sabe qué stock fue asentado |
| ¿Existe alternativa más clara? | Sí: posted/unpaid explícito y Cobrar atómico para pago inmediato |

### 10.3 paid — CONSERVAR

paid representa una condición financiera real y terminal para la Invoice original:

- remaining_balance = 0;
- Payments identifican formas, caja y actor;
- paid_at ancla revenue_paid;
- refund exige paid y no reabre la factura;
- cancelar paid está correctamente prohibido.

Debe tratarse como proyección del ledger, no como dato libre del serializer. La invariante debe reforzarse transaccionalmente y, si la tecnología lo permite, mediante constraint/trigger o auditoría automática estricta. Si se habilitan pagos parciales, el payment status debería derivarse como unpaid/partial/paid sin sobrecargar lifecycle.

### 10.4 cancelled — REDEFINIR

Conservar el evento terminal, pero nombrarlo **voided/anulada antes del cobro**. Su valor es:

- impedir reuso de un documento descartado;
- conservar actor, razón y timestamp;
- revertir stock asentado por posteo;
- diferenciarlo de devolución de una venta pagada.

No debería usarse para un checkout técnico nunca emitido: ese agregado se abandona/cierra. Para paid se mantiene CreditNote/RefundPayment.

## 11. Diseño propuesto

### 11.1 Alternativa A — Mantener estados actuales

~~~text
draft → confirmed → paid
  └───────────────→ cancelled
~~~

Para ser defendible necesitaría:

- draft = checkout editable con owner y solo visible en Cobros cuando ready;
- confirm de consultation exige MR closed y selección de receta resuelta;
- confirmed = receivable posted, no “revisión” genérica;
- comando Cobrar puede ejecutar confirm+pay atómico para ambos invoice_type;
- permisos separados para clinical lines, retail, post y pay;
- resolución explícita de $0;
- serializers cerrados y provenance por línea.

Ventaja: menor migración de datos/analytics. Desventaja: sigue haciendo que Invoice cargue preparación, emisión y pago; el término confirmed es poco expresivo y la tentación de usarlo como paso de UI permanece.

### 11.2 Alternativa B — Simplificar a open → paid/voided

~~~text
open/editable ── Cobrar ──▶ paid
      └──────── Abandonar/Anular ──▶ voided
~~~

Ventaja: coincide con POS y con clínicas que siempre cobran al momento; elimina Confirmar seguido de Registrar pago. Pago y stock son atómicos.

Desventaja: no representa una obligación emitida no cobrada. Si se intenta derivar AR de open, se vuelve a confundir preparación con deuda. Solo es correcta si negocio renuncia explícitamente a crédito, pagos posteriores y revenue_accrual independiente.

### 11.3 Alternativa C — Separar checkout, lifecycle documental y payment status

**Recomendada.**

~~~text
Clinical facts / POS cart
          │
          ▼
┌─────────────────────────┐
│ Checkout: preparing     │  editable, owner, no revenue, no AR
│ líneas con source/owner │
└────────────┬────────────┘
             │
             ├─ Cobrar ahora ──────────────────────────────┐
             │                                              ▼
             │                                Invoice issued + Payment(s)
             │                                payment_status = paid
             │
             └─ Dejar pendiente / emitir crédito ─▶ Invoice posted
                                                    payment_status = unpaid
                                                          │
                                                          └─ pago futuro → paid

Checkout abandonado ─▶ abandoned, sin Invoice financiera
Invoice posted sin pagos ─▶ voided según política + reversos
Invoice paid ─▶ CreditNote/Refund, permanece issued/paid
~~~

Separaciones conceptuales:

| Dimensión | Estados/eventos conceptuales | Fuente |
| --- | --- | --- |
| Atención clínica | open / closed | MedicalRecord |
| Preparación | preparing / ready / completed / abandoned | Checkout, o lifecycle separado |
| Documento | issued/posted / voided | Invoice |
| Pago | unpaid / partial / paid, derivado | Payment ledger |
| Corrección | credit issued / refunded / reversed | CreditNote/RefundPayment |
| Stock | clinical consumption / retail fulfillment / restock | Movements con provenance |

No es obligatorio crear cinco nuevos campos/modelos. La tabla define responsabilidades que la implementación posterior debe representar sin volver a colapsarlas en un status ambiguo.

### 11.4 Flujo recomendado de consulta

~~~text
1. VET registra servicios, consumos charge/included y receta.
2. Mientras MR está open:
   - hechos clínicos son editables solo por su dueño;
   - no puede postearse/cobrarse la consultation.
3. VET cierra MR:
   - se fija el conjunto clínico;
   - se crea/activa una tarea de checkout solo si hay cargo o decisión retail pendiente.
4. Recepción:
   - ve cargos clínicos read-only;
   - obtiene aceptación explícita de receta;
   - agrega/edita/quita exclusivamente líneas retail;
   - confirma el total mostrado al cliente.
5a. Cobrar ahora:
   - lock/version check;
   - finaliza líneas;
   - valida y asienta stock retail;
   - crea Invoice/anchors y Payments;
   - queda paid en una transacción.
5b. Dejar pendiente:
   - requiere permiso/razón/política de crédito;
   - finaliza y asienta stock;
   - fija posted_at/due_at;
   - queda receivable unpaid.
6. Corrección:
   - antes de Payment y según política: void;
   - después de paid: CreditNote/Refund.
~~~

### 11.5 Flujo recomendado de venta directa

~~~text
Carrito/CheckoutSession
→ validación de Rx + lote + stock
→ Cobrar atómico
→ Invoice issued/paid + Payment(s) + stock
~~~

Si el carrito debe sobrevivir refresh o permitir varios terminales, persistirlo con owner, version y expiry. Si no, no crear Invoice hasta Cobrar. “Dejar pendiente” en POS solo debería existir si negocio acepta ventas a crédito y aplicaría el mismo posted/unpaid de consultation.

### 11.6 Líneas y provenance

Cada línea debe declarar un source inmutable, por ejemplo:

- clinical_service, enlazado a MedicalRecordService;
- clinical_consumable_charge, enlazado a MedicalRecordProduct;
- prescription_retail, enlazado a PrescriptionItem/dispensación;
- direct_sale_retail.

Reglas:

- recepción no cambia/elimina clinical_*; solicita corrección clínica antes del cierre;
- quantity/presentation/lot de retail son editables solo antes de finalización;
- cambiar source o invoice_type no es una edición: debe estar prohibido;
- stock settlement se decide por source explícito, no por combinación de type + nullable FK;
- cada mutación registra actor, before/after y razón.

### 11.7 Consultas sin cargos

Decisión recomendada:

- si no hay total cobrable ni selección retail pendiente, cerrar como no_charge sin crear Invoice;
- si hay receta pendiente, crear tarea de checkout no financiera; al rechazo explícito se completa sin Invoice;
- si se requiere comprobante $0, emitir documento finalizado con regla de zero-settlement, nunca dejar draft/confirmed esperando Payment $0.

### 11.8 Invariantes objetivo

1. consultation solo se finaliza/postea/cobra si MedicalRecord está closed.
2. Total y líneas posteadas son inmutables; correcciones usan void/credit.
3. Cada línea tiene source y owner inmutables.
4. Stock clínico se asienta una vez al consumo; retail una vez al fulfillment/finalización.
5. paid si y solo si suma de Payments efectivos = total.
6. Un checkout sin obligación no aparece en AR/revenue.
7. posted/unpaid requiere total > 0, actor, reason/policy y, de ser necesario, due_at.
8. Documento $0 sigue una regla explícita y no crea Payment artificial.
9. Idempotency key cubre todo el comando Cobrar, incluidos stock e Invoice.
10. Void y refund son eventos diferentes con reversos trazables.

## 12. Impacto de implementación posterior

Esta sección dimensiona el trabajo; no propone código concreto.

### Models y migrations

- decidir si separar Checkout o añadir lifecycle/readiness/posted_at/due_at;
- migrar/renombrar confirmed_at y confirmed_at_source;
- separar document lifecycle de payment status o formalizar la proyección;
- añadir source/provenance inmutable y FKs a MRS/MRP donde aplique;
- añadir checkout owner/version/expiry si se persiste;
- cerrar campos status, invoice_type y links contra escritura libre;
- reforzar constraints de anchors, total, Payments y type/link coherence;
- resolver documentos $0;
- índices para posted/unpaid, ready checkout y due date.

### Services

- comando único finalize_and_pay para consultation y direct_sale;
- comando explícito post_receivable/dejar pendiente;
- guard MR closed y validación de snapshot clínico;
- mover stock settlement a source explícito;
- control optimista/pesimista de versión para evitar cobrar un total obsoleto;
- política de abandon/void y reanudación;
- backfill/provenance de líneas antiguas;
- conservar idempotencia, cash session y orden de locks.

### Views, serializers y permissions

- retirar escritura genérica de status/type/FKs;
- endpoints por intención de negocio, no PATCH de campos;
- serializers distintos para clinical read-only y retail editable;
- permisos separados: checkout.adjust_retail, invoice.post, payment.create, invoice.void, refund.create;
- respuestas de conflicto claras si MR/checkout cambió;
- deprecar confirm/direct-pay antiguos con ventana de compatibilidad.

### Frontend

- Cobros como bandeja de checkouts ready y receivables, no todos los drafts;
- total clínico read-only y retail editable;
- receta sin selección por default, aceptación/rechazo explícitos;
- un CTA Cobrar en pago inmediato;
- CTA Dejar pendiente solo con permiso/política;
- salida visible Abandonar/Anular con motivo;
- tratamiento explícito de $0;
- reanudación POS o creación atómica;
- badges separados de preparación, documento y pago;
- mostrar actor/timestamps relevantes.

### Tests

- matriz completa de transición por invoice_type y MR open/closed;
- tests de no sincronización imposible después de post;
- propiedad e inmutabilidad de cada source de línea;
- PATCH adversarial de type/service/presentation/lot/Rx;
- $0: sin cargos, included-only y item precio cero;
- receta total/parcial/rechazada y edición posterior;
- idempotencia/concurrencia de finalización+stock+Payment;
- abandono/reanudación POS;
- void frente a refund;
- analytics antes/después de migración;
- permisos ADMIN/VET/ASSISTANT por acción;
- integridad ledger a nivel DB/servicio.

### Analytics

- definir formalmente devengo: cierre clínico, posteo de receivable o emisión pagada;
- migrar confirmed_at a posted_at/finalized_at preservando histórico;
- actualizar revenue_accrual/outstanding y captions;
- decidir tratamiento de documento $0;
- mantener paid_at y ajustes de refund;
- versionar snapshots/provenance para evitar series mezcladas.

### Docs y ADR

- ADR de lifecycle/ledger/readiness;
- reemplazar narrativa “enviar a Cobros” por evento real;
- actualizar p7/p27/p32 y documentación de partial;
- contratos de stock por source;
- matriz de roles;
- runbook de migración, rollback y reconciliación.

## 13. Riesgos de migración

### 13.1 Clasificación de datos existentes

| Estado actual | No asumir | Validaciones antes de mapear | Destino probable |
| --- | --- | --- | --- |
| draft | Que esté listo, que MR esté cerrado o que sea obligación | type, total/items, MR status, age, source, appointment, receta pendiente | Checkout preparing/abandoned; Invoice $0 resuelta; algunos ready |
| confirmed | Que el servicio terminó o cliente aceptó | MR closed, Payments, remaining, stock movements, confirmed_at, total > 0 | posted/unpaid o anomalía a reconciliar |
| paid | Que ledger y status coincidan | sum Payments, paid_at, confirmed_at, refunds, cash session, stock | issued/paid; corregir excepciones |
| cancelled | Que nunca movió stock o no tenga pagos | previous status desde audit log, Payments, stock reversal, cancelled_at | voided; checkout abandoned en algunos draft-origin |

### 13.2 Riesgos principales

1. **No es posible inferir source clínico de todas las líneas con certeza.** presentation sin dispensed FK en consultation probablemente es MRP charge, pero no hay enlace. Se requiere matching conservador por MR/presentation/cantidad/tiempo y cola manual para colisiones.
2. **confirmed inválidos pueden existir con MR open.** Mapearlos automáticamente a posted validaría una deuda quizá prematura.
3. **draft antiguos mezclan carrito, $0, consulta activa y abandono.** La edad sola no basta para cancelar.
4. **Anchors alimentan series históricas.** Reescribir confirmed_at cambia devengo/snapshots; debe preservarse como legacy_posted_at con versión semántica.
5. **Stock ya asentado depende de provenance implícita.** Cambiar clasificación puede restockear o descontar dos veces.
6. **paid debe reconciliarse con Payment y refunds antes de constraints nuevas.**
7. **Clients/frontend antiguos pueden seguir llamando confirm/pay/direct-pay.** Se necesita compatibilidad, telemetría y retiro gradual.
8. **Cambiar IDs/relaciones o numeración de documentos $0 puede tener impacto fiscal/operativo no deducible del código.**
9. **Cambiar permisos puede bloquear clínicas donde VET también cobra.** Los permisos deben representar acciones, permitiendo acumular funciones por usuario.
10. **Toggle auto_create_invoice_on_done debe migrarse o retirarse con explicación**, porque organizaciones pueden depender del camino manual de done.

### 13.3 Estrategia segura de migración

1. Ejecutar reporte read-only de integridad por organización: status/anchors/Payments/MR/stock.
2. Añadir primero provenance y nuevos anchors nullable, sin cambiar comportamiento.
3. Backfill determinista; marcar confidence y enviar casos ambiguos a revisión.
4. Dual-write de eventos viejos/nuevos con métricas de divergencia.
5. Introducir nuevos comandos/UI detrás de feature flag por organización.
6. Reconciliar revenue_accrual, revenue_paid, AR y stock antes/después.
7. Bloquear writers genéricos solo cuando clientes nuevos estén desplegados.
8. Migrar estados en lotes idempotentes, conservar audit mapping y rollback lógico.
9. Activar constraints fuertes después de limpiar datos.
10. Retirar rutas/fields legacy y actualizar ADR al finalizar.

No debe ejecutarse una migración masiva del tipo draft → open, confirmed → unpaid, paid → paid, cancelled → voided sin estas comprobaciones.

## 14. Preguntas de negocio pendientes

Estas preguntas no pueden resolverse con precisión desde el código y cambian el diseño:

1. ¿La clínica permite dejar una cuenta por cobrar y que el cliente pague otro día, o todo checkout debe liquidarse al momento? ¿Hay due date y autorización?
2. ¿El devengo contable debe ocurrir al cerrar la consulta, al aceptar el cliente el importe, al emitir una cuenta por cobrar o únicamente al pagar?
3. ¿Existe obligación fiscal/operativa de emitir un documento de $0 o basta registrar la consulta como no charge?
4. ¿Recepción puede modificar precios/descuentos de cargos clínicos, o solo decidir líneas retail? ¿Quién autoriza una corrección clínica tras el cierre?
5. ¿Debe persistirse que un medicamento fue rechazado, pospuesto o surtido externamente, o basta registrar lo dispensado?
6. ¿En qué evento físico se considera entregado el medicamento: selección, confirmación/posteo o pago? La política define el momento correcto de stock.
7. ¿VET y ASSISTANT pueden desempeñar caja por política real, o se requiere segregación/supervisión para postear, cobrar y void?
8. ¿Se habilitarán pagos parciales? Si sí, ¿cómo se aplican devoluciones, vencimientos, saldo y cash reconciliation?
9. ¿Un carrito POS debe sobrevivir refresh/cambio de terminal, o puede ser local y crear Invoice solo al cobrar?
10. ¿auto_create_invoice_on_done tiene usuarios que marcan citas done sin cerrar MedicalRecord y necesitan una tarea de cobro, o es una configuración heredada?

## Apéndice A — Contratos HTTP relevantes auditados

| Operación | Método/ruta conceptual | Permiso | Semántica |
| --- | --- | --- | --- |
| Listar/crear Invoice | GET/POST invoices | invoice.list / invoice.create | Lista todos los estados; POST genérico crea draft |
| Ver/editar Invoice | GET/PATCH invoices/{id} | invoice.retrieve / invoice.update inferido | PATCH solo si estado previo draft |
| Agregar item | POST invoices/{id}/items | invoice.create | Draft; reglas distintas por type |
| Editar/eliminar item | PATCH/DELETE invoices/{id}/items/{item} | invoice.create / invoice.destroy | Draft; PATCH insuficientemente restringido |
| Confirmar | PATCH invoices/{id}/confirm | invoice.confirm | draft → confirmed para ambos types |
| Pagar | PATCH invoices/{id}/pay | invoice.pay | confirmed → paid, full |
| Cobrar venta directa | POST invoices/{id}/direct-pay | invoice.pay | direct_sale draft → confirmed → paid |
| Cancelar | PATCH invoices/{id}/cancel | invoice.cancel | draft/confirmed → cancelled |
| Dispensar receta | POST prescriptions/{id}/dispense | invoice.create + Rx condicional | Añade retail a consultation draft |
| Devolver | POST refund asociado a Invoice | refund/admin | paid permanece paid; crea nota/reembolso |

Rutas: backend/apps/billing/urls.py. Implementación: backend/apps/billing/views.py y services.py.

## Apéndice B — Archivos y pruebas de mayor peso

- backend/apps/billing/models.py
- backend/apps/billing/services.py
- backend/apps/billing/views.py
- backend/apps/billing/serializers.py
- backend/apps/billing/urls.py
- backend/apps/billing/signals.py
- backend/apps/medical_records/models.py
- backend/apps/medical_records/services.py
- backend/apps/medical_records/views.py
- backend/apps/medical_records/serializers.py
- backend/apps/medical_records/policies.py
- backend/apps/inventory/views.py
- backend/apps/appointments/services.py
- backend/apps/appointments/views.py
- backend/apps/organizations/models.py
- backend/apps/core/permissions_codes.py
- backend/apps/analytics/services.py
- backend/apps/dashboard/views.py
- frontend/src/pages/billing.jsx
- frontend/src/api/billing.js
- frontend/src/components/PaymentLinesEditor.jsx
- frontend/src/pages/pos/index.jsx
- frontend/src/pages/medicalRecords/ConsultationForm.jsx
- frontend/src/pages/analytics/index.jsx
- billing tests: invoice state machine, payment ledger, prescription dispense, refunds
- inventory tests: cost behavior
- medical_records tests: close

## Conclusión

Los cuatro labels actuales no son igualmente problemáticos. paid y el evento terminal de void tienen fundamento fuerte. La preparación editable y el posteo también son necesidades reales, pero están mal ubicadas y nombradas: draft mezcla construcción técnica con trabajo operativo, y confirmed mezcla readiness, freeze, stock, devengo y cuenta por cobrar.

La transición confirmed → paid es necesaria solo para una deuda realmente emitida que se cobrará después. No debe ser el camino obligatorio del checkout inmediato. El diseño recomendado conserva los hechos útiles —edición, posteo, stock, pago, anulación y refund— pero los distribuye entre atención clínica, checkout, documento y ledger, con ownership e invariantes explícitos.
