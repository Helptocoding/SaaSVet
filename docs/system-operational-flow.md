# Mapa Operacional del Sistema

**Fecha**: 2026-05-29
**Estado**: vigente (refleja Sprint A completo + Sprint B + ADR p30)
**Audiencia**: nuevo desarrollador, QA, tester, soporte.

Este documento describe **cómo opera el SaaS hoy** desde la perspectiva funcional:
qué módulos existen, qué acciones habilita cada uno, qué precondiciones exigen,
qué efectos provocan, qué desbloquean y qué queda bloqueado tras cada operación.

No describe código, endpoints ni serializers — esa información vive en
`docs/modules/*` y `docs/decisions/*`. Aquí se modela **cómo se comporta el
negocio dentro del SaaS**.

---

## 0. Mapa de módulos

| Módulo | Responsabilidad |
|--------|-----------------|
| `platform` | Provisión cross-tenant: crear organizaciones nuevas y su admin inicial. SaaS-wide. |
| `organizations` | Tenant. Una clínica = una organización. Settings, timezone, tax_rate. |
| `users` | Cuentas y roles (ADMIN_SAAS, ADMIN, VET, ASSISTANT). RBAC dinámico. |
| `patients` | Propietarios (Owner) + mascotas (Pet). Punto de entrada a todos los flujos clínicos. |
| `appointments` | Agenda. Estados, walk-in, asignación de paciente, registro rápido. |
| `medical_records` | Acto clínico: consulta, vitales, productos consumidos, servicios prestados, receta. |
| `inventory` | Catálogo (Product) + presentaciones (Presentation) + stock + movimientos. |
| `billing` | Facturación: invoice, items, ledger de pagos, notas de crédito, refunds, attestation rx externa, dispensación. |
| `cash` | Turno de caja (CashSession) y cierre Z. Reconciliación física del efectivo. |
| `analytics` | Snapshots diarios + dashboards (operacional + financiero). Read-only sobre eventos. |
| `logs` | Eventos estructurados JSON a stdout (RBAC, tenant, anchors, deprecation, integridad). |

### Dependencias funcionales

```
platform → organizations → users
                ↓
       patients (Owner, Pet)
                ↓
      ┌────────────────────────┐
      ↓                        ↓
 appointments           inventory (Product/Presentation)
      ↓                        ↓
medical_records ──────► billing (Invoice/Payment/CreditNote)
                              ↓
                         cash (CashSession)
                              ↓
                       analytics (snapshots)
                              ↓
                            logs
```

Reglas de boundary:
- `platform` solo lee `organizations` / `users` / `core`.
- Dominios (`medical_records`, `billing`, `inventory`, `appointments`) NUNCA importan `platform`.
- `cash` recibe FK de `billing.Payment` con string-ref → sin ciclo de import.
- `analytics` lee anchors de `billing` / `medical_records` / `appointments`; NUNCA escribe.

---

## 1. Organización (Tenant)

### Acción: Crear organización (provisioning)

**Requiere**
- Un usuario `ADMIN_SAAS` autenticado (Bearer JWT, con `is_superuser=True` e `is_staff=True`).
- Datos válidos para el administrador inicial: username único, email único, contraseña de al menos 12 caracteres (cumpliendo los validadores de Django).
- Throttle: 20 peticiones por hora por actor.

**Resultado** (atómico, dentro de `transaction.atomic`)
- Se crea la `Organization` con su `timezone` y `tax_rate`.
- El signal `initialize_organization` dispara en cascada:
  - `OrganizationSettings` con valores por defecto.
  - `Owner('Público General', is_generic=True)`.
  - `Pet('Paciente Anónimo', is_generic=True)`.
  - Roles RBAC del sistema (`ADMIN`, `VET`, `ASSISTANT`) con los permisos derivados de `PERMISSION_CODES`.
- Se crea el `User` administrador con `role='ADMIN'`, `is_staff=False`, `is_superuser=False` (los guards impiden la escalación de privilegios).
- Se asigna el `UserRole` al administrador, con `assigned_by` igual al actor que realizó el provisioning.

**Desbloquea**
- El inicio de sesión del administrador recién creado.
- La creación de staff, citas, pacientes, inventario, facturas y apertura de caja dentro de esa organización.

**Bloquea**
- El administrador recién creado **no** puede provisionar otras organizaciones (no es `ADMIN_SAAS`).
- El payload **no** puede inyectar `role=ADMIN_SAAS`, `is_staff` ni `is_superuser` (el service aplica fuerza-override para prevenirlo).

**Módulos involucrados**
`platform`, `organizations`, `users`.

---

### Acción: Crear staff (VET o ASSISTANT)

**Requiere**
- Un usuario `ADMIN` autenticado y perteneciente a la organización.
- Contraseña de al menos 8 caracteres, con al menos 1 mayúscula y 1 número.
- Que `seed_permissions` ya se haya ejecutado en la organización.

**Resultado**
- Se crea el `User` con `organization` igual a la del `ADMIN` que lo creó.
- El signal `assign_rbac_role_on_create` genera el `UserRole` correspondiente.

**Desbloquea**
- El nuevo usuario puede iniciar sesión y operar según los permisos de su rol.

**Bloquea**
- Si `seed_permissions` no se ejecutó, todas las peticiones del nuevo usuario caen en `RBAC_FALLBACK_ALLOWED` o reciben `403`.

**Módulos involucrados**
`organizations`, `users`.

---

### Acción: Configurar toggles operativos

**Requiere**
- Un `ADMIN` autenticado.
- Un toggle válido entre los disponibles: `auto_create_medical_record`, `auto_create_invoice_on_done`, `require_confirmation_before_start`, `allow_anonymous_walkin`, `show_status_change_history`, `require_open_cash_session`.

**Resultado**
- Se actualiza `OrganizationSettings` para la organización.

**Efectos cruzados**
- `auto_create_invoice_on_done=True` → al pasar una cita a `done`, el signal `create_draft_invoice_on_done` genera una factura en `draft`.
- `auto_create_medical_record=True` → al pasar una cita a `done`, el signal crea un `MedicalRecord` vacío en estado `open`.
- `require_confirmation_before_start=True` → bloquea cualquier transición directa a `in_progress` si el estado previo no es `confirmed`.
- `allow_anonymous_walkin=True` → el walk-in puede omitir la mascota (usa la mascota genérica).
- `require_open_cash_session=True` → las operaciones `pay_invoice` y `pay_direct_sale` exigen que el actor tenga una caja abierta.

**Defaults actuales** — todos en `False`, excepto `show_status_change_history=True`. Esto privilegia un flujo de trabajo manual y explícito.

---

## 2. Pacientes (Owner + Pet)

### Acción: Crear Owner

**Requiere**
- Un usuario con permiso `patient.create`.
- Un `name` válido (el regex admite letras, números, acentos, espacios, apóstrofes y guiones).
- Un `phone` de exactamente 10 dígitos (formato de México).

**Resultado**
- Se crea el `Owner` en la organización, con `public_id` (UUID v4).

**Desbloquea**
- Registrar mascotas asociadas a este propietario.
- Facturar ventas directas con un owner real (ADR p25).

**Bloquea**
- Su eliminación si tiene mascotas asociadas → **409 `resource_has_dependencies`** (FK con PROTECT, ADR p16).
- La eliminación del owner genérico → **409 `generic_resource_protected`**.

**Módulos involucrados**
`patients`.

---

### Acción: Crear Pet

**Requiere**
- Un `Owner` existente (no necesariamente real; puede ser el genérico en un escenario walk-in).
- `name`, `species` (de la lista cerrada `SPECIES_CHOICES`) y `birth_date` obligatorios.
- `sex` es opcional (por defecto `unknown`).

**Resultado**
- Se crea la `Pet` en la organización, con `public_id`; la FK al `owner` es PROTECT.

**Desbloquea**
- Agendar citas, abrir consultas, emitir recetas, registrar vacunas y facturar (consultation) sobre esta mascota.

**Bloquea**
- Su eliminación si tiene registros médicos, vacunas, recetas, citas o facturas asociadas → **409**.
- La eliminación de la mascota genérica → **409 `generic_resource_protected`**.

**Módulos involucrados**
`patients`.

---

### Acción: Registro rápido (Owner + Pet + Cita en un solo paso)

**Requiere**
- Permiso `appointment.create`.
- Datos completos: `owner_name`, `owner_phone` (10 dígitos), `pet_name`, `pet_species` y los datos de la cita.

**Resultado** (atómico)
- Si el `phone` ya existe en la organización → reutiliza el Owner (el cliente regresa con una nueva mascota).
- Si no existe → crea el Owner.
- Crea siempre una Pet nueva.
- Crea el Appointment con toda la validación habitual (detección de conflictos, fecha pasada, timezone).

**Desbloquea**
- El flujo normal de atención a partir de la cita creada.

**Bloquea**
- Si cualquier paso falla, hay rollback completo (no quedan huérfanos).

**Módulos involucrados**
`patients`, `appointments`.

---

## 3. Agenda (Appointment)

### Estados y transiciones válidas

```
scheduled → confirmed → in_progress → done (terminal)
    ↓           ↓            ↓
 canceled    canceled    canceled
    ↓           ↓
 no_show    no_show

canceled  → scheduled  (solo si fecha futura)
no_show   → scheduled  (solo si fecha futura)
done      → (terminal, sin transiciones)
```

### Acción: Crear cita (scheduled)

**Requiere**
- Una mascota existente (misma organización), un veterinario (misma organización) y fecha con hora futura.
- `end_time > start_time`.
- Que no haya solape con otra cita del mismo veterinario en los estados `scheduled`, `confirmed` o `in_progress`.
- `motivo` (texto sanitizado, máximo 255 caracteres).

**Resultado**
- Se crea el `Appointment` en estado `scheduled`, con `walk_in=False`.

**Desbloquea**
- Confirmar (opcional), iniciar (`in_progress`), cancelar o marcar como no-show.

**Bloquea**
- La creación de una cita que se superponga en la misma franja horaria para el mismo veterinario.

**Módulos involucrados**
`appointments`, `patients`, `users`.

---

### Acción: Walk-in (sin cita previa)

**Requiere**
- Un veterinario de la organización.
- `pet` obligatorio, salvo que `allow_anonymous_walkin=True` — en ese caso se usa la mascota genérica.
- `reason` (texto sanitizado, máximo 255 caracteres, no puede quedar vacío tras sanitizar).

**Resultado**
- Se crea un `Appointment` directamente en estado `in_progress`, con `walk_in=True`, duración de 30 minutos y sin verificación de conflicto de horario.

**Desbloquea**
- La apertura inmediata de una consulta médica.
- Si la cita se creó con mascota genérica, se puede usar `assign-patient` para vincular un paciente real (siempre que la cita no esté en `done`).

**Bloquea**
- La cancelación de la cita ya no aplica las transiciones propias de `scheduled`/`confirmed` (porque ya está en `in_progress`).

**Módulos involucrados**
`appointments`, `patients`.

---

### Acción: Cambiar estado (PATCH `/status/`)

**Requiere**
- Permiso `appointment.update`.
- Una transición válida según la máquina de estados.
- Si `require_confirmation_before_start=True` → bloquea el salto directo `scheduled → in_progress` (exige pasar por `confirmed` primero).

**Resultado**
- El estado se actualiza.
- Se registra un `AppointmentStatusChange` (append-only) con `from_status → to_status`, `changed_by` y `reason`.
- Si el nuevo estado es `done` y `auto_create_invoice_on_done=True` → se crea una factura `draft` vía signal.
- Si el nuevo estado es `done` y `auto_create_medical_record=True` → se crea un `MedicalRecord` vacío en `open`.

**Desbloquea** (al llegar a `in_progress`)
- Abrir o editar la consulta médica vinculada.

**Desbloquea** (al llegar a `done`)
- Crear una consulta médica desde el detalle de la cita (CTA `+ Crear Consulta Médica`).
- Cobrar, si el toggle generó la factura automáticamente.

**Bloquea**
- Transiciones inválidas → 400 con `error` descriptivo.
- `done` es terminal: no admite ninguna transición posterior.

**Módulos involucrados**
`appointments`, `medical_records` (si toggle), `billing` (si toggle).

---

### Acción: Cancelar cita

**Requiere**
- Estado `scheduled`, `confirmed` o `in_progress`.
- Opcional: `cancellation_reason` (texto libre, sanitizado).

**Resultado**
- El estado pasa a `canceled` y se registra un `AppointmentStatusChange`.
- Tanto el PATCH `/status/` como el DELETE producen el mismo event lineage.

**Desbloquea**
- Reprogramar la cita si la fecha original no ha pasado (`canceled → scheduled`).

**Bloquea**
- Cancelar desde `done` (no está permitido).
- Reprogramar si la fecha original ya pasó (en ese caso debe crearse una cita nueva).

---

### Acción: Asignar paciente real (vincular desde genérico)

**Requiere**
- Una cita walk-in cuya mascota actual sea `pet.is_generic=True`.
- Que el estado de la cita **no** sea `done`.
- Un nuevo `pet` válido (misma organización, no genérico).

**Resultado**
- `appointment.pet` se actualiza al paciente real.
- Si existe un `MedicalRecord` abierto vinculado a la cita, su `pet` también se actualiza.
- Se registra un `AppointmentStatusChange` con la descripción correspondiente.

**Bloquea**
- Vincular otra mascota genérica → 400.
- Vincular sobre una cita que ya está en `done`.

---

## 4. Consulta médica (MedicalRecord)

### Estados

```
open → closed (terminal, irrevocable)
```

### Acción: Crear consulta

**Requiere**
- Permiso `medicalrecord.create`.
- `pet` y `veterinarian` deben pertenecer a la misma organización.
- Si se vincula a un `appointment`, este también debe ser de la misma organización.

**Resultado**
- Se crea un `MedicalRecord` en estado `open` con `consultation_type='general'` (valor por defecto).
- **No** se crea una factura automáticamente (creación lazy, ADR p7).

**Desbloquea**
- Registrar signos vitales, agregar productos y servicios, y emitir receta.

**Bloquea**
- Si la mascota no pertenece a la organización → 404.

**Módulos involucrados**
`medical_records`, `patients`, `appointments`.

---

### Acción: Agregar producto usado (insumo)

**Requiere**
- Consulta en estado `open`.
- El VET asignado (o un ADMIN).
- Una `presentation` con stock suficiente.
- Si el `Product` tiene `requires_prescription=True`, debe existir una receta activa que contenga ese producto dentro de la misma consulta.
- La operación completa debe ejecutarse dentro de `transaction.atomic()`.

**Resultado** (siguiendo el orden de locks canónico)
1. Bloquea el `MedicalRecord`.
2. Bloquea la `Invoice` (`get_or_create_invoice_for_medical_record` → crea una factura draft de forma lazy si no existía).
3. Bloquea la `Presentation`.
4. Ejecuta `apply_stock_movement('out')` → descuenta el stock.
5. Sincroniza el `InvoiceItem` en la factura draft (usa `apply_invoice_item_quantity_delta` con F()).
6. Crea o actualiza el `MedicalRecordProduct`.

**Desbloquea**
- El cobro de la factura (al confirmarla).

**Bloquea**
- La eliminación de la consulta mientras tenga una factura asociada → 403.
- Stock negativo (la validación ocurre bajo lock).

**Módulos involucrados**
`medical_records`, `inventory`, `billing`.

---

### Acción: Agregar servicio

**Requiere**
- Consulta en `open`. El VET asignado (o un ADMIN).
- Un `service` activo de la organización.
- La operación dentro de `transaction.atomic()`.

**Resultado** (orden de locks)
1. Bloquea el `MedicalRecord`.
2. Bloquea la `Invoice` (creación lazy).
3. Sincroniza el `InvoiceItem` con FK al `service`.
4. Crea el `MedicalRecordService`.

**Desbloquea**
- El cobro de la factura.

**Bloquea**
- Duplicar el mismo servicio en la misma factura (unique constraint).

---

### Acción: Registrar signos vitales (VitalSigns)

**Requiere**
- Consulta en `open`. Permiso `medicalrecord.vitals.create` (VET).
- Al menos un campo entre `weight`, `temperature`, `heart_rate` y `respiratory_rate`.
- Combinaciones clínicamente coherentes (por ejemplo, `temp ≥ 42°C` junto con `FC < 40 bpm` produce un error).
- Un cambio brusco de peso superior al 150 % requiere `force_weight=true`.

**Resultado**
- Se inserta una fila append-only en `VitalSigns`.
- `recorded_by` queda fijado a `request.user`.

**Bloquea**
- PATCH o DELETE de signos vitales (son inmutables).
- Registrar vitales sobre una consulta `closed`.

---

### Acción: Crear receta médica

**Requiere**
- Consulta en `open` y sin receta previa (relación OneToOneField).
- Cada `PrescriptionItem` debe tener: `product.requires_prescription=True`, `dose` no vacío y `quantity > 0`.
- Validación de tenant sobre cada `product`.

**Resultado**
- Se crea la `Prescription` vinculada al `MedicalRecord`.

**Desbloquea**
- La dispensación en el flujo de cobros (ver §6).
- La reimpresión y visualización desde `/prescriptions`.

**Bloquea**
- Modificar la receta si la consulta ya está cerrada.
- La receta por sí sola **no** descuenta stock ni genera cobro (ADR receta-no-es-factura).

**Módulos involucrados**
`medical_records`, `inventory`.

---

### Acción: Cerrar consulta

**Requiere**
- Estado `open`.
- `diagnosis` no vacío (para todos los tipos de consulta).
- `treatment` no vacío (excepto cuando `consultation_type=vaccine`).
- El VET asignado (o un ADMIN).

**Resultado** (atómico, ADR p30)
- `status='closed'`. `closed_at = now()`. `closed_at_source='service'`. `closed_by` registrado.
- **Garantiza la existencia de una factura**: invoca `get_or_create_invoice_for_medical_record` dentro del mismo `atomic()` → si no existía factura, crea una en `draft` por $0. Toda consulta cerrada aparece en la sección de Cobros.
- La operación es idempotente: cerrar dos veces no re-valida ni genera artefactos adicionales.
- Si `closed_at` cae dentro de un bucket frozen de analytics → se registra el log `ANCHOR_LATE_ARRIVAL` (WARNING, solo advertencia).

**Desbloquea**
- La visualización de la factura en Cobros (como mínimo en `draft` por $0).
- La dispensación de la receta (si existe) sobre la misma factura de la consulta.

**Bloquea** (post-cierre, irrevocable)
- Editar la consulta (ningún rol puede hacerlo).
- Agregar o quitar productos, servicios o signos vitales.
- Modificar o crear una receta.
- Eliminar la consulta (siempre que tenga factura asociada).

**Módulos involucrados**
`medical_records`, `billing`, `analytics` (log).

---

## 5. Recetas y dispensación (ADR p30)

### Acción: Dispensar receta (recepción decide qué lleva el cliente)

**Requiere**
- Una `Prescription` existente vinculada a una consulta.
- Que la factura de la consulta esté en estado `draft`.
- Permiso `billing.rx_dispense` (ADMIN y VET lo tienen por defecto).
- Body con `lines=[{presentation, quantity, prescription_item}]`.

**Resultado** (atómico, orden de locks `MR → Invoice → Presentation → InvoiceItem`)
- Agrega uno o más `InvoiceItem` a la **misma factura de la consulta**, con la FK `dispensed_from_prescription_item` establecida.
- Acumula cantidades si la presentación ya existía como línea dispensada (usa el helper F()).
- **No mueve stock en este momento**: el descuento ocurre al confirmar la factura, por la ruta única `_confirm_locked_invoice` + `_items_settling_stock`. El predicado es: solo ítems con FK `dispensed_from_prescription_item` en facturas `consultation`; todos los ítems en `direct_sale`.
- Devuelve la factura actualizada (200).
- No crea `ExternalPrescriptionAttestation` (la receta interna ya es el respaldo legal).

**Desbloquea**
- Confirmar y pagar la factura en un solo cobro contable que incluye tanto la consulta como la dispensación.

**Bloquea**
- Si la presentación ya figura como insumo (sin FK a prescription_item) → se rechaza; recepción debe ajustar manualmente.
- Si el producto tiene `requires_prescription` y el usuario no tiene permiso `billing.rx_dispense` → 403.
- "Quitar" una línea significa simplemente no incluirla (no-op, sin persistencia ni auditoría).

**Módulos involucrados**
`medical_records`, `billing`, `inventory`.

---

## 6. Inventario

### Acción: Crear producto

**Requiere**
- Permiso `inventory.create`.
- `name` válido (regex restrictivo).
- `category` válida entre `medication`, `food`, `accessory` u `other`.
- Al crear el producto se crea también su presentación inicial.

**Resultado**
- Se crean el `Product` y su `Presentation` con el stock inicial.

**Desbloquea**
- Venderlo en una factura, usarlo como insumo en consulta o recetarlo (si `requires_prescription=True`).

---

### Acción: Ajustar stock (gestión manual)

**Requiere**
- Permiso `inventory.update`.
- La operación debe ejecutarse dentro de `transaction.atomic()` y con `select_for_update` sobre la `Presentation`.

**Resultado**
- Se registra un `StockMovement` de tipo `in`, `out` o `adjustment`.
- `Presentation.stock` se actualiza a través de `apply_stock_movement()`.

**Reglas duras**
- **Nunca** se debe escribir `presentation.stock` directamente fuera de `apply_stock_movement()`.
- El caller **debe** poseer el `select_for_update()` antes de invocar el helper.
- `adjustment` representa un reset absoluto (reconciliación).

---

### Acción: Eliminar presentación

**Requiere** (todas las condiciones deben cumplirse)
1. `stock == 0`.
2. Sin `StockMovement` histórico.
3. Sin `InvoiceItem` histórico.
4. Sin `MedicalRecordProduct` histórico.

**Bloquea** la eliminación si cualquiera de estas condiciones falla.

---

### Acción: Reconciliar stock (vía cron)

**Requiere** la ejecución del comando de administración `audit_stock_integrity`.

**Resultado**
- Exit 0: sin drift. Exit 1: drift detectado. Exit 2: error.
- Detecta presentaciones sin baseline de `adjustment` (esto es informativo, no cuenta como drift).

---

### Efectos cruzados de stock

| Origen | Resultado en stock |
|--------|--------------------|
| Producto consumido en consulta (`MedicalRecordProduct.save`) | `−quantity` al consumirse |
| Item agregado a factura `direct_sale` (cualquier presentación) | `−quantity` al **confirmar** la factura |
| Item dispensado de receta en factura `consultation` | `−quantity` al **confirmar** la factura |
| Cancelación de factura `confirmed` con stock movements | `+quantity` reversa por cada item |
| Nota de crédito con `disposition=restock` | `+quantity` al emitir refund |
| Nota de crédito con `disposition=discard` | sin movimiento de stock |

---

## 7. Cobros (Billing)

### Modelos clave

- `Invoice`: documento. Tipos: `consultation` | `direct_sale`. Estados: `draft → confirmed → paid` (con `cancelled` desde `draft|confirmed`).
- `InvoiceItem`: línea (servicio XOR presentación).
- `Payment`: evento append-only de inflow (positivo). `Invoice.status='paid' ⟺ remaining_balance == 0`.
- `CreditNote`: documento de devolución (público).
- `RefundPayment`: evento append-only de outflow (negativo).
- `RefundReversal`: contra-asiento de un refund emitido por error.
- `ExternalPrescriptionAttestation`: append-only, retail de Rx con receta externa.

### Anchors analíticos (`editable=False`)

- `paid_at` ← establecido por `pay_invoice` / `pay_direct_sale`.
- `confirmed_at` ← establecido por `confirm_invoice` / `pay_direct_sale`.
- `cancelled_at` ← establecido por `cancel_invoice`.

Cada anchor tiene su `*_source` (`service`, `legacy`, etc.). Los CHECK constraints en base de datos protegen contra bypass vía `UPDATE`, SQL directo o administrador.

---

### Acción: Crear factura `consultation`

**Requiere**
- `owner` y `pet` obligatorios (por tratarse de un acto clínico).
- Todas las FKs deben pertenecer a la misma organización.

**Resultado**
- Se crea una `Invoice` en `draft`. El `tax_rate` se hereda de la organización y se vuelve inmutable tras la creación.
- Normalmente la factura se crea de forma lazy mediante `get_or_create_invoice_for_medical_record()` al agregar el primer cargo o al cerrar la consulta.

---

### Acción: Crear factura `direct_sale`

**Requiere**
- `owner` (real o genérico; por defecto se asigna el genérico).
- `pet` **opcional** (ADR p25). Si se envía, debe pertenecer al `owner` indicado.

**Resultado**
- Se crea una `Invoice` en `draft` (en el modal del frontend; solo se persiste al momento de cobrar).

**Desbloquea**
- Agregar ítems y cobrar de forma atómica mediante `direct-pay`.

**Bloquea**
- Una factura `consultation` sin `pet` → 400.
- Un `pet` cuyo owner no coincida con el owner de la factura → 400.

---

### Acción: Agregar `InvoiceItem`

**Requiere**
- Invoice en estado `draft`.
- XOR: o `service` o `presentation`, pero no ambos.
- Si es `presentation`: pre-check de stock + lock real al confirmar.
- Si la presentación tiene `requires_prescription` en una `direct_sale`: el body debe incluir `rx_attested=True` y `prescriber_name`, además el usuario necesita el permiso `billing.rx_dispense` → se crea una `ExternalPrescriptionAttestation` dentro del mismo `atomic()`.

**Resultado**
- Se crea el `InvoiceItem` bajo lock de la Invoice. El `unit_price` se copia en ese momento.
- Se invoca `Invoice.recalculate_totals()` (suma vía SQL).

**Bloquea**
- Duplicar presentación o servicio en la misma factura (unique constraints).
- Agregar ítems a una factura en estado `confirmed`, `paid` o `cancelled` (solo `draft` es editable).

---

### Acción: Confirmar factura (`confirm_invoice`)

**Requiere**
- Estado `draft`. Al menos 1 ítem activo.

**Resultado** (atómico, orden de locks `Invoice → Presentation → InvoiceItem`)
- `status='confirmed'`. `confirmed_at = now()`. `confirmed_at_source='service'`.
- Se descuenta el stock de los ítems que `_items_settling_stock(invoice, items)` clasifica como liquidables (ADR p30):
  - En `direct_sale`: todos los ítems que tengan presentación.
  - En `consultation`: **solo** los ítems con `dispensed_from_prescription_item` establecido (los demás ya se descontaron al momento de consumirse en consulta).
- Se registra un `InvoiceAuditLog` con `previous_status → new_status` y `changed_by`.

**Desbloquea**
- El cobro mediante `pay_invoice`.
- La cancelación (que revierte el stock).

**Bloquea**
- La edición de ítems.
- Volver a confirmar una factura ya confirmada.

---

### Acción: Cobrar factura (`pay_invoice`)

**Requiere**
- Estado `confirmed`.
- Body con `payment_lines=[{method, amount[, reference]}]` o el campo legacy `payment_method` único.
- **Total exacto** (ADR p30): `Σ payment_lines == remaining_balance`. No se admiten pagos parciales bajo ningún motivo.
- Header opcional `X-Idempotency-Key` para deduplicación.
- Si `require_open_cash_session=True` en los settings → el actor debe tener una caja abierta.

**Resultado** (atómico, orden de locks `CashSession → MedicalRecord → Invoice → ...`)
- Se crean 1 o más `Payment` (append-only, signo `+`), uno por cada línea. `amount > 0`. `occurred_at = now()`. `actor = request.user`.
- `Invoice.payment_method` se deriva: si todas las líneas comparten el mismo método, se asigna ese método; si hay métodos mixtos, queda `NULL` (legacy `DD-009`).
- Cuando `remaining_balance → 0` ⇒ `status='paid'` + `paid_at = now()` + `paid_at_source='service'`.
- Si el toggle de caja está activo, se asigna `Payment.cash_session`.
- Cambio en efectivo: si el monto recibido supera el total, el frontend muestra el cambio (UI), pero el `Payment` registra **solo** el total (el cambio no se persiste).

**Desbloquea**
- La devolución mediante nota de crédito (no mediante `cancel`).

**Bloquea**
- Volver a pagar una factura que ya está `paid`.
- Pagar desde `draft` (debe confirmarse primero).
- Sumar menos del total → `ValidationError`.
- Pagar sin caja abierta cuando el toggle lo exige.

**Módulos involucrados**
`billing`, `cash`, `analytics`.

---

### Acción: Pagar venta directa (`pay_direct_sale`) — 1 paso

**Requiere**
- `invoice_type='direct_sale'`. Estado `draft`. `payment_method` o `payment_lines`.

**Resultado** (un solo lock, atómico)
- Internamente ejecuta `_confirm_locked_invoice` + `_pay_locked_invoice` sin double-lock.
- `confirmed_at` y `paid_at` quedan casi idénticos (diferencia de milisegundos).
- Se descuenta el stock de todos los ítems con presentación.
- Se registran 1 o más `Payment`.

**Desbloquea / Bloquea**: idéntico a `pay_invoice` en post-condiciones.

---

### Acción: Cancelar factura (`cancel_invoice`)

**Requiere**
- Estado `draft` o `confirmed` (nunca `paid`).
- La factura no debe tener `Payment` registrados (si los tiene → 400; la devolución debe hacerse por nota de crédito).

**Resultado** (atómico)
- `status='cancelled'`. `cancelled_at = now()`.
- Si estaba en `confirmed`: se revierte el stock mediante `_lock_presentations` + `apply_stock_movement('in')`.
- Se registra un `InvoiceAuditLog`.

**Bloquea**
- Cancelar una factura en estado `paid` (debe usarse nota de crédito).
- Cancelar una factura que ya tenga Payments registrados.

---

### Acción: Emitir nota de crédito + refund (`process_refund`)

**Requiere**
- Factura en estado `paid`.
- Permiso `billing.refund` (ADMIN por defecto).
- Body con: `credit_lines[]` (referencian los `InvoiceItem` originales, con `quantity` y `disposition`), `refund_lines[]` (eventos de outflow), `reason_code` (tipificado) y `reason_notes`.
- Invariante: `Σ refund_lines == Σ credit_lines` (el dinero devuelto debe igualar al crédito emitido).
- Validación anti over-refund: las cantidades y montos no pueden superar lo ya devuelto previamente.
- Header `X-Idempotency-Key` para prevenir dobles refunds.

**Resultado** (atómico, orden de locks `CashSession → Invoice → Presentation → CreditNote/items/refund`)
- Se crean la `CreditNote` (documento público) y sus `CreditNoteItem[]` (internos).
- Se crean los `RefundPayment[]` (signo `−`, append-only).
- `disposition=restock` → `apply_stock_movement('in')` bajo lock. `discard` → sin movimiento de stock.
- Se genera un `MetricAdjustment` negativo sobre `revenue_paid` correspondiente al **día del refund** (no al día de la venta original; modelo dual-window §2.8).
- En efectivo: se resta del `expected_cash` de la sesión de caja abierta actual (nunca se toca un cierre Z ya cerrado).
- La `Invoice` permanece en `paid` (terminal, contrato §8.2). `paid_at` es inmutable.

**Desbloquea**
- Reversar la nota de crédito si fue emitida por error (`reverse_credit_note`).

**Bloquea**
- Emitir refund sobre factura en `draft`, `confirmed` o `cancelled`.
- Over-refund (cantidad o monto superior al disponible ya devuelto).

---

### Acción: Reversar nota de crédito (`reverse_credit_note`)

**Requiere**
- Una `CreditNote` emitida previamente.
- Permiso `billing.refund`.

**Resultado** (append-only)
- Se crea 1 `RefundReversal` por cada `RefundPayment` de la nota de crédito (máximo 1 reversal por refund).
- Se genera un `MetricAdjustment` positivo que cancela el ajuste negativo del refund.
- En efectivo: se suma al `expected_cash` de la sesión de caja abierta actual.
- La nota de crédito se marca como `reversed=true` (derivado: todos sus refunds tienen reversal).

**Bloquea**
- Doble reversal (la relación es 1:1 con el refund).
- Reversar un reversal (no es reversible; la corrección de un error en el reversal se hace mediante un nuevo refund).

---

## 8. Caja (CashSession)

### Estados

```
open → closed (terminal)
```

### Acción: Abrir caja (`open_cash_session`)

**Requiere**
- Permiso `cashsession.open`.
- El usuario no debe tener otra caja abierta (UniqueConstraint parcial `cashsession_one_open_per_user`).
- `opening_float >= 0`.

**Resultado**
- Se crea una `CashSession` en estado `open` con `opened_by`, `opened_at` y `opening_float`.

**Desbloquea**
- Los cobros y refunds del actor cuando `require_open_cash_session=True`.

**Bloquea**
- Abrir una segunda caja para el mismo usuario.

---

### Acción: Cerrar caja Z (`close_cash_session`)

**Requiere**
- `CashSession.status='open'`. Permiso `cashsession.close`.
- Body con `counted_cash`, `notes?` y `force?`.

**Resultado** (atómico, lock solo sobre `CashSession` → sin riesgo de ABBA con Invoice)
- El sistema computa el cierre Z:
  ```
  expected_cash = opening_float
                + Σ(Payment en efectivo dentro de la sesión)
                − Σ(RefundPayment en efectivo dentro de la sesión)
                + Σ(RefundReversal en efectivo dentro de la sesión)
  difference    = counted_cash − expected_cash
  ```
- Los pagos con `card` y `transfer` se registran de forma informativa, pero **no** entran en el conteo de efectivo.
- `closed_snapshot` es un JSON append-only que se congela al cerrar (no se reinterpreta nunca).
- `report_schema_version` versiona la estructura (Sprint A v1; Sprint B agrega la línea de refunds → bump).
- `closed_at` está protegido por un CHECK constraint.

**Desbloquea**
- Que el mismo usuario pueda abrir una caja nueva.

**Bloquea**
- Pagos que estuvieran en vuelo: al tomar el lock, cualquier pago que intente reanudarse ve `status != 'open'` y es rechazado.
- Tras el cierre: `expected_cash`, `counted_cash`, `difference` y `closed_snapshot` son inmutables.

**Módulos involucrados**
`cash`, `billing`.

---

## 9. Analytics

### Eventos que alimentan métricas

| Anchor | Writer | KPI |
|--------|--------|-----|
| `Invoice.paid_at` | `pay_invoice` / `pay_direct_sale` | `revenue_paid`, `invoices_paid_count` |
| `Invoice.confirmed_at` | `confirm_invoice` / `pay_direct_sale` | `revenue_accrual` |
| `Appointment.start_datetime` | creación de cita | `appointments_total/done/no_show` |
| `MedicalRecord.closed_at` | `close_medical_record` | `medical_records_closed` |
| `MetricAdjustment.delta` (Sprint B) | `process_refund` / `reverse_credit_note` | `revenue_paid_net` |

### Acción: Construir snapshot diario (`build_daily_metrics`)

**Requiere**
- La ejecución del comando de administración (vía Railway cron, alrededor de las 06:00 UTC).
- Un advisory lock de PostgreSQL por organización (anti double-fire).

**Resultado**
- Se genera 1 fila en `DailyOrgMetrics` por cada `(organization, date)` con los 7 KPIs v1.
- La operación es idempotente: re-ejecutar el mismo día no modifica `built_at` si no hay diferencias.
- `lifecycle_state` puede ser `provisional`, `frozen`, `rebuilt` o `corrupt`.
- Se registra un `DashboardSnapshotAudit` append-only por cada evento de ciclo de vida.

**Reglas duras**
- El día actual (today) **nunca** se snapshotea (siempre se sirve como live).
- Un snapshot frozen + `force=False` → se omite (idempotencia).
- `excluded_anchor_missing > 0` → el ciclo de vida pasa a `corrupt` y se registra un log ERROR.

---

### Acción: Consumir dashboards

| Endpoint | Roles |
|----------|-------|
| `GET /api/v1/dashboard/operations/series/` | ASSISTANT, VET, ADMIN |
| `GET /api/v1/dashboard/financial/series/` | ADMIN only |
| `GET /api/internal/analytics-health/` | ADMIN_SAAS only |

**Reglas del contrato**
- Cada datapoint expone `source ∈ {snapshot, live}` y `lifecycle_state`.
- Today siempre se sirve con `source=live`, calculado mediante `compute_daily_metrics` (la misma función que usa el snapshot).
- Los días sin snapshot se devuelven con `lifecycle_state='missing'` y valores en cero (nunca se omiten silenciosamente).
- Los decimales se serializan como strings (para evitar drift de punto flotante).
- El rango está capeado a un máximo de 365 días.
- `revenue_paid_net` tiene exposición dual (Sprint B): muestra `gross` (sin cambios) y `net` adicional; sin activar el flip definitivo todavía.

---

### Cuándo aparece reflejado en el dashboard

| Evento | Reflejo en `live` (today) | Reflejo en snapshot (siguiente nightly) |
|--------|---------------------------|------------------------------------------|
| `pay_invoice` exitoso | inmediato | sí, fecha local de la org |
| `confirm_invoice` exitoso | inmediato | sí |
| `cancel_invoice` exitoso | inmediato | (no es KPI v1 directo) |
| `process_refund` | inmediato (live recomputa) | adjustment se aplica vía `revenue_paid_net` |
| `close_medical_record` | inmediato | sí en `medical_records_closed` |
| Cita pasa a `done` o `no_show` | inmediato | sí |
| Caja abierta / cerrada | NO entra a snapshots v1 | NO |

---

## 10. Logs y auditoría

Todos los eventos se emiten a stdout en formato JSON (capturados por Railway). A continuación, el resumen por logger:

| Logger | Eventos clave | Significado |
|--------|---------------|-------------|
| `rbac.events` | `RBAC_ALLOWED_DB`, `RBAC_DENIED`, `RBAC_FALLBACK_ALLOWED`, `TENANT_MISMATCH_DETECTED` | Acceso, permisos, cross-tenant. |
| `apps.tenant_validation` | `TENANT_VALIDATION_REJECTED` | FK cross-org en serializer. |
| `medical_records.events` | `MEDICAL_RECORD_CLOSED`, `OWNERSHIP_DENIED`, `CLOSED_DENIED`, `DELETED` | Ciclo de vida de consulta. |
| `analytics.events` | `ANCHOR_LATE_ARRIVAL`, `DASH_BUILD_*`, `DASH_SNAPSHOT_*` | Late arrivals, build de snapshots. |
| `billing.events` | `IDEMPOTENT_PAYMENT_DEDUPED`, `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` | Pagos dedup, mutaciones fuera de tx. |
| `cash.events` | `CASH_SESSION_OPENED/CLOSED/FORCE_CLOSED` | Turnos de caja. |
| `core.deprecation` | `DEPRECATED_ENDPOINT_HIT` | Endpoints en sunset (RFC 8594). |
| `core.audit_orphan_fks` | `AUDIT_ORPHAN_FKS_*` | Integridad referencial. |
| `platform.events` | `PLATFORM_ORG_PROVISIONED`, `PLATFORM_ACCESS_DENIED` | Provisión de tenants. |

### Acciones auditadas en DB

- `InvoiceAuditLog`: cada transición de estado de factura.
- `AppointmentStatusChange`: cada cambio de estado de cita (incluyendo asignación de paciente).
- `DashboardSnapshotAudit`: cada lifecycle event de snapshot.
- `VitalSigns`: append-only (es la auditoría por sí mismo).
- `Payment` / `RefundPayment` / `RefundReversal` / `CreditNote`: append-only (son la auditoría).
- `ExternalPrescriptionAttestation`: append-only.
- `OrganizationTimezoneAudit`: cada cambio de timezone de la org.

---

## 11. Flujos completos

A continuación se presentan los recorridos extremo a extremo que cubren los escenarios
operativos más frecuentes en una clínica. Cada diagrama traza el camino desde la acción
inicial hasta el registro en analytics.

### Flujo A — Consulta agendada, atendida y cobrada

```
Recepción
   ↓
Crear cita (scheduled)
   ↓ (opcional)
Confirmar (confirmed)
   ↓
Iniciar (in_progress)
   ↓
[El veterinario abre la consulta médica]
   ↓
Registrar signos vitales (VitalSigns append-only)
   ↓
Agregar servicios (sincroniza InvoiceItem en factura draft lazy)
   ↓
Agregar productos (descuenta stock, sincroniza InvoiceItem)
   ↓ (opcional)
Emitir receta (medicamentos, sin descuento de stock ni cobro)
   ↓
Cerrar consulta (closed_at + garantiza factura draft)
   ↓
[Recepción abre la sección de Cobros]
   ↓ (opcional)
Dispensar receta (agrega líneas a la MISMA factura con FK dispensed_from_prescription_item)
   ↓
Confirmar factura (confirmed + descuenta stock de ítems dispensados)
   ↓
Cobrar (pay_invoice, total exacto, 1+ Payment, paid_at)
   ↓
Cita pasa a done (manual; CTAs en detalle de cita: Ver Consulta, Ver Factura)
   ↓
Analytics nocturno snapshotea:
   - revenue_paid, revenue_accrual, invoices_paid_count
   - medical_records_closed
   - appointments_done
```

### Flujo B — Venta directa (mostrador / POS)

```
Recepción presiona "+ Cobro" (atajo F11)
   ↓
Modal: selecciona owner (genérico por defecto o real) + pet (opcional)
   ↓
Agrega productos y/o servicios (estado local, sin enviar al backend todavía)
   ↓ (si el producto tiene requires_prescription)
Atestar receta externa (prescriber_name, rx_attested=true)
   ↓
Botón "Cobrar" → secuencia atómica:
   - createInvoice (direct_sale, draft)
   - addItem × N (crea ExternalPrescriptionAttestation si aplica)
   - direct-pay (un solo lock):
       * _confirm_locked_invoice → descuenta stock de TODOS los ítems con presentación + confirmed_at
       * _pay_locked_invoice → registra Payment(s) + paid_at
       * Si el toggle de caja está activo: asigna Payment.cash_session
   ↓
El frontend muestra el cambio en efectivo (solo UI) si el monto recibido > total
   ↓
Analytics nocturno snapshotea:
   - revenue_paid (confirmed_at ≈ paid_at, diferencia de milisegundos)
```

### Flujo C — Walk-in anónimo, atendido

```
Un cliente llega sin cita previa
   ↓
Recepción usa la opción walk-in (allow_anonymous_walkin=True)
   ↓
Se crea la cita en in_progress, walk_in=True, pet=genérica
   ↓
El banner amarillo en la UI indica: "vincular paciente"
   ↓ (en cualquier momento antes de done)
PATCH assign-patient con el pet real
   ↓
Se continúa con el Flujo A normal (consulta → cobro)
```

### Flujo D — Devolución (post-pago, Sprint B)

```
La factura está en paid
   ↓
ADMIN abre el detalle de la factura → botón "Devolver" (can('billing.refund'))
   ↓
Selecciona los conceptos a devolver (cantidad/monto por línea) + disposition (restock/discard)
   ↓
Editor de reembolso: payment_lines exactos = Σ credit_lines
   ↓
Rellena reason_code (tipificado) + notas
   ↓
X-Idempotency-Key + POST refund/
   ↓ (atómico)
Se crean CreditNote + CreditNoteItem[] + RefundPayment[]
   ↓
Si restock: apply_stock_movement('in')
   ↓
Se genera un MetricAdjustment negativo en revenue_paid del DÍA DEL REFUND
   ↓
Si es en efectivo: se resta del expected_cash de la caja abierta actual
   ↓
La Invoice permanece en paid (paid_at inmutable)
   ↓
Si fue un error → botón "Revertir" → RefundReversal + ajuste positivo + suma en caja
```

---

## 12. Flujos válidos (resumen)

1. Cita programada: `scheduled → (confirmed) → in_progress → done` (done es terminal).
2. Cancelación de cita: `scheduled|confirmed → canceled` (se puede reprogramar solo si la fecha original no ha pasado).
3. Consulta médica: `open → closed` (terminal, irreversible y garantiza la existencia de factura).
4. Factura de consulta: `draft → confirmed → paid` (cobro por el total exacto).
5. Venta directa: `draft → paid` de forma atómica mediante `direct-pay`.
6. Cancelación de factura: `draft|confirmed → cancelled` (solo si no tiene Payments registrados).
7. Devolución: `paid → (CreditNote + RefundPayment[])` — la factura permanece en `paid`.
8. Reversión de devolución: `RefundPayment → RefundReversal` (relación 1:1, el reversal no es reversible).
9. Caja: `open → closed` (el cierre Z legal queda congelado).
10. Walk-in anónimo: `pet genérico → assign-patient → pet real` (antes de que la cita llegue a `done`).
11. Dispensación de receta: se agregan ítems a la **misma factura de consulta** (en `draft`); el descuento de stock ocurre al confirmar.
12. Receta externa en venta directa: aplica cuando `requires_prescription=True`, con `rx_attested=true`, `prescriber_name` y permiso `billing.rx_dispense`.

---

## 13. Flujos inválidos (rechazados explícitamente)

- Pagar una factura en `draft` sin haberla confirmado antes (`pay_invoice` exige `confirmed`).
- Pagar un monto inferior al total (ADR p30: no se admiten pagos parciales bajo ningún motivo).
- Cancelar una factura en estado `paid` (para eso existe la nota de crédito).
- Cancelar una factura en `confirmed` que ya tenga Payments registrados.
- Emitir un refund sobre una factura en `draft`, `confirmed` o `cancelled` (solo se permite sobre `paid`).
- Hacer over-refund (cantidad o monto superior al saldo disponible para devolver).
- Editar o borrar una consulta en estado `closed` (ningún rol puede hacerlo).
- Borrar una consulta que tenga una factura asociada → 403.
- Borrar un Owner o Pet que tenga dependencias → 409 `resource_has_dependencies`.
- Borrar el Owner o Pet genérico → 409 `generic_resource_protected`.
- Borrar un `VaccineRecord` → 405 (modelo append-only por cumplimiento NOM-007/046).
- Borrar un `MedicalRecord` con recetas, facturas o signos vitales asociados → 403 (guard) o 409 (PROTECT).
- Crear un walk-in sin `pet` cuando `allow_anonymous_walkin=False` → 400.
- Realizar transiciones de cita inválidas (`scheduled → done`, `done → *`, etc.).
- Confirmar una factura sin ítems activos → 400.
- Agregar dos veces la misma presentación o servicio a la misma factura → unique constraint.
- Dispensar una receta sobre una factura en `confirmed` o `paid` → solo se permite en `draft`.
- Vender un producto con `requires_prescription` en venta directa sin `rx_attested` → 400 `prescription_required`.
- Vender un producto con `requires_prescription` sin el permiso `billing.rx_dispense` → 403.
- Abrir una segunda caja para el mismo usuario → UniqueConstraint.
- Pagar cuando `require_open_cash_session=True` y el actor no tiene caja abierta → 400 `cash_session_required`.
- Provisionar una organización con un payload que intente inyectar `role=ADMIN_SAAS` → el sistema aplica fuerza-override silencioso (se asigna `ADMIN`).
- Acceder a recursos de otra organización (cross-tenant) → 404 (nunca se devuelve `[]`).
- Crear un `Payment` con `amount <= 0` → se viola el invariante.
- Mutar `Invoice.status` fuera de `services.py` → bloqueado por CHECK constraints de base de datos y auditoría.
- Cerrar una consulta sin `diagnosis` (siempre obligatorio) o sin `treatment` (obligatorio excepto en `consultation_type=vaccine`).

---

## 14. Errores operativos comunes

| Síntoma | Causa probable | Diagnóstico |
|---------|----------------|-------------|
| "Stock insuficiente" al confirmar factura | Otra venta concurrente consumió el stock. | La validación bajo `select_for_update` es correcta. En UX: recargar la disponibilidad. |
| Botón cobrar deshabilitado | `Σ payment_lines ≠ remaining_balance`. | Verificar el split de pago y el cambio en efectivo (el cambio se capea en UI, no afecta `amount`). |
| Factura no aparece en Cobros tras cerrar consulta | Comportamiento pre-ADR p30 (creación lazy). | A partir de p30 el cierre de consulta garantiza la factura. Verificar versión del backend. |
| "No hay caja abierta" al cobrar | Toggle `require_open_cash_session=True` y el actor no tiene sesión de caja. | Abrir caja con `POST /api/cash/sessions/open/`. |
| 403 al dispensar receta | Falta el permiso `billing.rx_dispense`. | Asignarlo al rol correspondiente (ADMIN/VET) desde la sección de Roles. |
| Factura draft de $0 acumulada | Consulta cerrada sin cargos (comportamiento esperado post-p30). | Trade-off aceptado: toda consulta cerrada aparece en Cobros. |
| Drift de stock detectado por `audit_stock_integrity` | Escritura directa a `stock` sin pasar por `apply_stock_movement`. | Investigar el caller. Se corrige con migración de baseline o `adjustment` manual. |
| `RBAC_FALLBACK_ALLOWED` en logs | Usuario sin `UserRole` en la base de datos. | Ejecutar `seed_permissions` en la organización. |
| 401 en frontend tras login válido | Toggle "Recordarme" e inconsistencia en el almacenamiento del token. | Revisar `auth/tokenStorage.js` (session tiene prioridad sobre local). |
| Cita walk-in con pet genérico no se puede vincular | La cita ya está en estado `done`. | Vincular al paciente real antes de cerrar la cita. |
| Over-refund | La suma de líneas supera el monto ya devuelto disponible. | Revisar el detalle de las notas de crédito emitidas previamente. |
| No se puede dispensar un producto que ya figura como insumo | `unique_together(invoice, presentation)`. | Ajustar manualmente la cantidad del insumo en la consulta. |
| `closed_at` genera log `ANCHOR_LATE_ARRIVAL` | El cierre de consulta cayó en un bucket frozen (>T+2). | Es solo una advertencia (warn-only); revisar la latencia operativa. |
| `RBAC_DENIED` recurrente para el mismo endpoint | El frontend está usando un endpoint que el rol no tiene permitido. | Revisar `can()` antes de mostrar el CTA correspondiente. |

---

## 15. Dependencias críticas (no romper)

- `for_organization()` debe ir **siempre primero** en la cadena del queryset.
- Toda mutación de stock debe pasar por `apply_stock_movement()`, con el lock externo ya adquirido por el caller.
- Toda mutación de `InvoiceItem.quantity` debe usar `apply_invoice_item_quantity_delta()` (basado en F()).
- Los anchors (`paid_at`, `confirmed_at`, `cancelled_at`, `closed_at`) solo se escriben dentro de `services.py`.
- Los eventos financieros (`Payment`, `RefundPayment`, `RefundReversal`) solo se crean en `billing/services.py`.
- El orden global de locks es: `CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct`.
- `recalculate_totals()` solo se invoca bajo lock de la Invoice.
- `seed_permissions` se ejecuta en cada deploy (Procfile).
- El frontend usa `public_id` en URLs y deep links; los PKs solo se usan en campos FK del body y en despliegues de pantalla.
- El header `X-Idempotency-Key` debe figurar en `CORS_ALLOW_HEADERS` para que el navegador no bloquee la petición preflight.

---

## 16. Invariantes del sistema (binding)

1. **Multitenancy**: todo acceso cross-tenant retorna 404. Cada fila tiene `organization_id`. El sistema está preparado para RLS (ADR p23).
2. **Anchors inmutables**: `paid_at`, `confirmed_at`, `cancelled_at`, `closed_at` y `closed_snapshot` no se reescriben nunca.
3. **Append-only**: los siguientes modelos son de solo inserción: `Payment`, `RefundPayment`, `RefundReversal`, `CreditNote`, `VitalSigns`, `VaccineRecord`, `ExternalPrescriptionAttestation`, `InvoiceAuditLog`, `AppointmentStatusChange`, `MetricAdjustment`, `DashboardSnapshotAudit` y `OrganizationTimezoneAudit`.
4. **`amount > 0`** en todos los eventos financieros. El signo lo determina el tipo de evento, nunca un decimal negativo.
5. **`Invoice.status='paid' ⟺ remaining_balance == 0`**. El estado es una proyección del ledger, no un flag arbitrario.
6. **Los refunds no afectan `remaining_balance`**. La factura en `paid` es terminal.
7. **Los snapshots frozen jamás se reescriben**. Los ajustes posteriores se registran mediante `MetricAdjustment` en el modelo dual-window.
8. **Total exacto**: toda factura se cobra por el monto completo (ADR p30, que reemplaza el modelo de pagos parciales de p27).
9. **`actor` es siempre server-side**: se toma de `request.user`, nunca del body de la petición.
10. **`organization_id` existe desde el día 0** en cada modelo (no se repite la deuda técnica de `InvoiceAuditLog`).
11. **Idempotencia**: la combinación `(org, idempotency_key)` es única; un reintento devuelve el mismo resultado.
12. **Causalidad en DAG**: `Payment → RefundPayment → RefundReversal`. Cada nodo es inmutable. Máximo 1 reversal por refund; el reversal no es reversible.
13. **Una receta no descuenta stock ni genera cobro por sí sola**. El cobro y el descuento de stock ocurren al dispensar y confirmar la factura de la consulta.
14. **Una consulta cerrada siempre tiene factura** (como mínimo una en `draft` por $0, según ADR p30).
15. **Una consulta con factura asociada no se puede eliminar** (403).
16. **Los CHECK constraints en base de datos** bloquean `queryset.update()`, `bulk_update` y SQL directo que dejaría un estado sin su anchor correspondiente.
17. **El día actual (today) nunca se snapshotea** en analytics (siempre se calcula como live).
18. **Caja-efectivo ≠ revenue_paid**: los pagos con tarjeta o transferencia no entran en el conteo del cierre Z.
19. **El administrador de una clínica no puede provisionar otras organizaciones** (no es `ADMIN_SAAS`; el payload no permite escalar privilegios).
20. **`InvoiceItem.dispensed_from_prescription_item`** es el discriminador único para determinar qué ítems descuentan stock en una factura de consulta (no existe una segunda función de stock).

---

## 17. Reglas que nunca deben romperse

- Jamás escribir `Invoice.status` fuera de `billing/services.py`.
- Jamás escribir `Presentation.stock` fuera de `apply_stock_movement()`.
- Jamás mutar `InvoiceItem.quantity` con `+=` seguido de `save()` (debe usarse el helper basado en F()).
- Jamás invertir el orden global de locks.
- Jamás crear un `Payment` fuera de `pay_invoice` o `pay_direct_sale`.
- Jamás admitir pagos parciales en una factura.
- Jamás reabrir una factura que ya está en estado `paid`.
- Jamás editar ni borrar eventos financieros (la corrección se hace mediante contra-asiento).
- Jamás exponer `id` junto con `public_id` en serializers de modelos públicos **nuevos** (los legacy están baselineados).
- Jamás usar el patrón `editing.public_id || editing.id` en el frontend (anti-patrón verificado con grep).
- Jamás llamar a `cache.clear()` de forma masiva dentro de signals.
- Jamás snapshotear el día actual (today).
- Jamás bumpear `METRICS_SCHEMA_VERSION` sin un ADR que lo respalde, con dual-write durante 30 días y aprobación del Product Owner.
- Jamás borrar `Organization`, `Pet`, `Owner` o `MedicalRecord` que tengan dependencias (PROTECT + 409).
- Jamás colocar `for_organization()` después de `select_related()` o `prefetch_related()` en la cadena del queryset.
- Jamás leer `localStorage` directamente para obtener `access_token`, `refresh_token` o `user` fuera de `tokenStorage.js`.

---

# Resumen Ejecutivo

VeterinariaSaaS es un sistema multitenant para clínicas veterinarias en México. Cada
clínica es una **organización** (tenant) con su propio timezone, tax_rate, usuarios
(`ADMIN`/`VET`/`ASSISTANT`), settings, pacientes, inventario y caja. Una capa
**platform** (ADMIN_SAAS) provisiona organizaciones nuevas con su admin inicial
de forma atómica.

El negocio se opera en cinco flujos centrales:

1. **Agenda**: recepción crea citas (o un walk-in, o un registro rápido owner+pet+cita
   atómico). La cita avanza `scheduled → confirmed → in_progress → done` con audit
   trail completo (`AppointmentStatusChange`).

2. **Consulta médica**: el VET abre `MedicalRecord` sobre la mascota, registra
   vitales (append-only), agrega servicios y productos (estos descuentan stock al
   consumirse y sincronizan items en una factura draft creada lazy), opcionalmente
   emite receta (sin stock, sin cobro), y finalmente la cierra. **El cierre
   GARANTIZA la factura en Cobros** (mínimo draft $0, ADR p30) — toda consulta
   finalizada es visible para recepción.

3. **Cobros**: la factura `consultation` tiene flujo `draft → confirmed → paid`
   (cobro total exacto, sin parciales). La factura `direct_sale` (venta de mostrador
   sin consulta) usa `direct-pay` atómico (un solo lock). En consulta, recepción
   puede **dispensar la receta** agregando líneas a la **misma factura** de la
   consulta (FK `dispensed_from_prescription_item` discrimina qué descontar al
   confirmar). En venta directa, productos `requires_prescription` requieren
   **attestation de receta externa** (modelo append-only legal).

4. **Devoluciones** (Sprint B): una factura `paid` NO se cancela; se devuelve vía
   `CreditNote` + `RefundPayment` (append-only, signo `−`). Si fue error, se
   contra-asienta con `RefundReversal`. La factura permanece `paid` (terminal).
   `revenue_paid_net` se ajusta vía `MetricAdjustment` en el día del refund
   (los snapshots frozen NO se reescriben).

5. **Caja**: cada usuario abre 1 sesión (`CashSession`) y al final hace cierre Z
   (`opening_float + Σ cash payments − Σ refunds + Σ reversals = expected_cash`;
   `difference = counted − expected`). El Z legal queda frozen en
   `closed_snapshot`. Cuando el toggle `require_open_cash_session=True`, todo
   cobro exige caja abierta.

**Eventos** (Payment, RefundPayment, RefundReversal) son append-only con `amount > 0`
siempre; el signo lo da el tipo. Los **anchors** (`paid_at`, `confirmed_at`,
`cancelled_at`, `closed_at`) son `editable=False` con CHECK constraints DB y
único writer en `services.py` — la regla autoritativa de analytics y auditoría.

**Analytics** corre nightly (`build_daily_metrics`) por organización con advisory
lock y genera snapshots `DailyOrgMetrics` idempotentes; today es siempre live
calculado con la misma función. El dashboard expone `source` y `lifecycle_state`
por datapoint; nada se sirve silenciosamente.

**Reglas duras**: multitenancy estricto (cross-org = 404, NUNCA `[]`); orden global
de locks `CashSession → MR → Invoice → Presentation → InvoiceItem → MRP`;
toda mutación de stock vía `apply_stock_movement()` + lock externo; toda mutación
contable de `InvoiceItem.quantity` vía F(); IDs públicos UUID (`public_id`) en
URLs, PKs solo en body FK fields. Toda acción crítica deja audit trail (DB o log
JSON estructurado en stdout).

Operativamente, un día típico en una clínica abre con la apertura de caja, recibe
citas + walk-ins, ejecuta consultas que generan facturas, cobra en efectivo o
tarjeta (con dispensación de receta cuando aplica), eventualmente emite
devoluciones por producto vencido / error, y cierra el día con el Z de caja. La
información se refleja inmediatamente en el dashboard live; al siguiente nightly
queda snapshoteada como histórico inmutable.
