# Operaciones por Módulo

**Fecha**: 2026-06-23
**Estado**: vigente (refleja Sprint A completo + Sprint B + ADR p30 + ADR p45)
**Audiencia**: nuevo desarrollador, QA, tester, soporte.

Este documento describe las **acciones operacionales de cada módulo**: qué
precondiciones exigen, qué efectos provocan, qué desbloquean y qué queda
bloqueado tras cada operación.

No describe código, endpoints ni serializers — esa información vive en
`docs/modules/*` y `docs/decisions/*`. Aquí se modela **cómo se comporta el
negocio dentro del SaaS** para cada dominio.

> **Índice general**: [`docs/system-operational-flow.md`](system-operational-flow.md) — mapa de módulos y dependencias.
> **Flujos completos**: [`docs/system-flows.md`](system-flows.md) — recorridos extremo a extremo.
> **Referencia**: [`docs/system-reference.md`](system-reference.md) — errores, dependencias críticas e invariantes.

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
- Se crea el `User` administrador con `role='ADMIN'`, `is_staff=False`, `is_superuser=False` (los guards impiden la escalación de privilegios), y `password_must_change=True` (sin `password_temp_issued_at` → la contraseña inicial **no caduca**, pero el primer login obliga a cambiarla vía `MustChangePasswordGate`). El service acepta `require_password_change=False` solo para seeds (demo).
- Se asigna el `UserRole` al administrador, con `assigned_by` igual al actor que realizó el provisioning.

**Desbloquea**
- El inicio de sesión del administrador recién creado (forzado a cambiar la contraseña en el primer acceso).
- La creación de staff, citas, pacientes, inventario, facturas y apertura de caja dentro de esa organización (tras el cambio de contraseña).

**Bloquea**
- El administrador recién creado **no** puede provisionar otras organizaciones (no es `ADMIN_SAAS`).
- El payload **no** puede inyectar `role=ADMIN_SAAS`, `is_staff` ni `is_superuser` (el service aplica fuerza-override para prevenirlo).

**Módulos involucrados**
`platform`, `organizations`, `users`.

---

### Acción: Resetear contraseña de usuario (ADMIN_SAAS, cross-tenant — ADR p45)

**Requiere**
- Un usuario `ADMIN_SAAS` autenticado (Bearer JWT).
- `public_id` del usuario target: debe estar activo y **no** ser `ADMIN_SAAS`.
- Throttle: 20 peticiones por hora por actor.

**Resultado** (atómico, dentro de `transaction.atomic`)
- Se genera una contraseña temporal (`secrets.token_urlsafe`, ~22 chars).
- `target.set_password(temp_password)` + `password_must_change=True` + `password_temp_issued_at=now()`.
- Todos los `OutstandingToken` del target quedan blacklisted (sesiones activas invalidadas).
- Se emite log `PLATFORM_PASSWORD_RESET_ISSUED` en `platform.events` con `target_organization_id`
  y `target_organization_name` (campos extra vs reset de clínica — trazabilidad cross-tenant).
- `temp_password` se devuelve **una sola vez** en el response 201 y **nunca se loguea**.

**Desbloquea**
- El target puede loguearse con `temp_password`.
- En el primer login, `must_change_password=true` en el JWT obliga a cambiar contraseña
  (`MustChangePasswordGate` bloquea todos los endpoints hasta el cambio).

**Bloquea**
- ADMIN_SAAS no puede resetear a otro ADMIN_SAAS (queryset excluye `role='ADMIN_SAAS'` → 404).
- ADMIN_SAAS no puede resetearse a sí mismo (mismo mecanismo → 404, convención "404-as-403").
- ADMIN, VET, ASSISTANT no tienen acceso a este endpoint → 403.

**Diferencias vs reset de clínica (`reset_password_for_staff`, ADR p21)**
- Sin restricción de mismo-tenant — funciona con cualquier org.
- Endpoint distinto: `/api/platform/staff/<public_id>/reset-password/` (namespace platform).
- Service propio (`platform_reset_password`) — gates y audit distintos.

**Módulos involucrados**
`platform`, `users`.

---

### Acción: Crear staff (VET o ASSISTANT)

**Requiere**
- Un usuario `ADMIN` autenticado y perteneciente a la organización.
- Contraseña de al menos 8 caracteres, con al menos 1 mayúscula y 1 número.
- Que `seed_permissions` ya se haya ejecutado en la organización.

**Resultado**
- Se crea el `User` con `organization` igual a la del `ADMIN` que lo creó y `password_must_change=True` (contraseña de un solo uso: el empleado la cambia en su primer login vía `MustChangePasswordGate`; sin `password_temp_issued_at` → no caduca).
- El signal `assign_rbac_role_on_create` genera el `UserRole` correspondiente.

**Desbloquea**
- El nuevo usuario puede iniciar sesión y operar según los permisos de su rol (tras cambiar la contraseña en el primer acceso).

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
- Dispensar más de lo recetado: por ítem de receta, lo dispensado acumulado en la factura + lo solicitado no puede exceder `PrescriptionItem.quantity`, comparado en unidades base (`quantity × conversion_factor`, ADR p31) → 400 con amparado/dispensado/restante. El cliente puede llevar menos; nunca más.
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
- Se crea una `Invoice` en `draft`. En el POS (`/pos`, ADR p38) el carrito vive en
  estado local y el draft real se crea al presionar "Cobrar" (paso 1 del checkout);
  si la venta se edita o abandona antes de pagar, el draft se cancela (auditable).

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
- Agregar un ítem de **presentación** a una factura `consultation` → 400 (ADR p37): los productos solo entran como insumos de la consulta o dispensando la receta; un ítem manual se cobraría sin liquidar stock al confirmar. Servicios sí se permiten.
- Editar la cantidad de una línea **dispensada** por encima de lo recetado → 400 (mismo tope clínico de la dispensación, ADR p37; la cantidad nueva reemplaza a la vieja).

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
- El registro de movimientos manuales del cajón (ADR p39).

**Bloquea**
- Abrir una segunda caja para el mismo usuario.

---

### Asociación de pagos al turno (ADR p39)

**Asociación ≠ obligatoriedad.** Si el actor tiene caja abierta, todo
`Payment`/`RefundPayment`/`RefundReversal` se asocia a esa sesión **siempre**,
con o sin el toggle `require_open_cash_session`. El toggle solo decide si el
cobro se **bloquea** cuando NO hay caja abierta (ON → 400; OFF → pago sin
sesión). Antes del p39, con el toggle apagado el pago quedaba sin sesión aunque
hubiera caja abierta → el Z reportaba $0 ventas (diferencia falsa).

---

### Acción: Registrar movimiento manual (`register_cash_movement`, ADR p39)

**Requiere**
- Permiso `cashmovement.create` (ADMIN, VET, ASSISTANT).
- Caja abierta del actor (la operación lockea la `CashSession` — serializada
  contra el cierre Z: ningún movimiento se cuela después del conteo).
- `movement_type ∈ {deposit, withdrawal, expense}`, `amount > 0` (CHECK en DB),
  `reason` obligatorio (sanitizado, máx. 255).

**Resultado**
- Se crea un `CashMovement` append-only (sin PATCH/DELETE; corrección =
  contra-movimiento). `occurred_at` y `actor` son server-side.
- `deposit` suma al efectivo esperado del cierre; `withdrawal` y `expense`
  restan. Solo aplica a efectivo (es el cajón físico).

**Bloquea**
- Registrar sin caja abierta → 400.
- Registrar sobre una caja ya cerrada (el lock lo garantiza).
- Montos ≤ 0 o sin motivo.

**Módulos involucrados**
`cash`.

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
                + Σ(CashMovement deposit)                      ← ADR p39
                − Σ(CashMovement withdrawal + expense)         ← ADR p39
  difference    = counted_cash − expected_cash
  ```
- Los pagos con `card` y `transfer` se registran de forma informativa, pero **no** entran en el conteo de efectivo.
- `closed_snapshot` es un JSON append-only que se congela al cerrar (no se reinterpreta nunca).
- `report_schema_version` versiona la estructura (v1 Sprint A; v2 Sprint B refunds; v3 ADR p39 movimientos manuales — los Z viejos no se reinterpretan).
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
- La ejecución del comando de administración (vía cron — host crontab con `docker compose exec backend python manage.py build_daily_metrics`, alrededor de las 06:00 UTC).
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

Todos los eventos se emiten a stdout en formato JSON (Docker stdout — `docker compose logs backend`). A continuación, el resumen por logger:

| Logger | Eventos clave | Significado |
|--------|---------------|-------------|
| `rbac.events` | `RBAC_ALLOWED_DB`, `RBAC_DENIED`, `RBAC_FALLBACK_ALLOWED`, `TENANT_MISMATCH_DETECTED` | Acceso, permisos, cross-tenant. |
| `apps.tenant_validation` | `TENANT_VALIDATION_REJECTED` | FK cross-org en serializer. |
| `medical_records.events` | `MEDICAL_RECORD_CLOSED`, `OWNERSHIP_DENIED`, `CLOSED_DENIED`, `DELETED` | Ciclo de vida de consulta. |
| `analytics.events` | `ANCHOR_LATE_ARRIVAL`, `DASH_BUILD_*`, `DASH_SNAPSHOT_*` | Late arrivals, build de snapshots. |
| `billing.events` | `IDEMPOTENT_PAYMENT_DEDUPED`, `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` | Pagos dedup, mutaciones fuera de tx. |
| `cash.events` | `CASH_SESSION_OPENED/CLOSED/FORCE_CLOSED`, `CASH_MOVEMENT_REGISTERED` | Turnos de caja y movimientos manuales. |
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
- `CashMovement`: append-only (ADR p39 — corrección = contra-movimiento).
- `OrganizationTimezoneAudit`: cada cambio de timezone de la org.
