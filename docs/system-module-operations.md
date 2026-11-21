# Operaciones por Módulo

**Fecha**: 2026-09-07
**Estado**: vigente (incluye ADR p62 y reconciliación estructural de Billing)
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
- Si el rol es `VET`, cédula profesional: solo dígitos, de 5 a 10 (orden 7, ADR p64).
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

### Acción: Editar integrante (plan Equipo A1)

**Requiere**
- Permiso `staff.update` (sensible, solo ADMIN). El integrante es de la misma organización, está activo y no es `ADMIN_SAAS`, cuenta de servicio ni cuenta semilla de la demo.
- Solo `first_name`, `last_name`, `email`, `specialty` y `license_number`. Nombres por la regla D4 (NFC + recorte; letras latinas, espacio, guion y apóstrofos). Correo único global.

**Resultado**
- Se guardan solo los campos que cambian; `STAFF_PROFILE_UPDATED` con los nombres de los campos.
- Cambiar el correo no cierra sesiones: el correo nuevo sirve para entrar desde ya y el anterior deja de servir.

**Bloquea**
- Cualquier otra clave → 400. Correo ocupado → 400 genérico. Los documentos clínicos cerrados conservan su snapshot.

---

### Acción: Desactivar integrante

**Requiere**
- Permiso `staff.destroy`. No es uno mismo (400) y el actor sigue activo con el bloqueo tomado (`403 actor_inactive`).
- Si el objetivo es ADMIN, debe quedar otro ADMIN activo en la clínica (`409 last_active_admin`), aunque otro rol tenga `staff.destroy` concedido en la base.

**Resultado**
- `is_active=False`; se revocan sus refresh tokens y se incrementa su versión de sesión (ADR p65): ningún token anterior vuelve a servir, ni tras reactivarlo.
- Se conservan PK, `public_id`, rol, `UserRole` e historial.

**Desbloquea**
- Reactivarlo desde Inactivos (`staff.reactivate`).

---

### Acción: Reactivar integrante (plan Equipo A2)

**Requiere**
- Permiso `staff.reactivate` (sensible, solo ADMIN); actor ADMIN activo y organización activa. Integrante inactivo de la misma organización (si ya está activo, `409 already_active`).
- `reactivate_staff` es `durable`: debe ser la transacción más externa.

**Resultado** (atómico)
- `is_active=True`, contraseña temporal de 24 h con cambio obligatorio, todos los refresh tokens revocados y versión de sesión incrementada.
- La contraseña temporal se devuelve una sola vez, después del commit, con `Cache-Control: no-store`. `STAFF_REACTIVATED` sale con `on_commit(robust=True)`.

**Bloquea**
- La contraseña anterior y cualquier token emitido antes.

---

### Acción: Configurar toggles operativos

**Requiere**
- Un `ADMIN` autenticado.
- Un toggle válido entre los disponibles: `auto_create_medical_record`, `require_confirmation_before_start`, `allow_anonymous_walkin`, `show_status_change_history`, `require_open_cash_session` o `allow_post_unpaid`.

**Resultado**
- Se actualiza `OrganizationSettings` para la organización.

**Efectos cruzados**
- `allow_post_unpaid=True` → permite emitir una obligación pendiente con vencimiento y evidencia de aceptación; no habilita pagos parciales.
- `auto_create_medical_record=True` → al pasar una cita a `done`, el signal crea un `MedicalRecord` vacío en estado `open`.
- `require_confirmation_before_start=True` → bloquea cualquier transición directa a `in_progress` si el estado previo no es `confirmed`.
- `allow_anonymous_walkin=True` → el walk-in puede omitir la mascota (usa la mascota genérica).
- `require_open_cash_session=True` → `pay_checkout`, `pay_invoice`, refunds y reversals de efectivo exigen que el actor tenga una caja abierta.

**Defaults actuales** — todos en `False`, excepto `show_status_change_history=True`. Esto privilegia un flujo de trabajo manual y explícito.

---

## 2. Pacientes (Owner + Pet)

### Garantía transversal del módulo: identidad por teléfono (INV-C, ADR p57)

Aplica a **todas** las acciones que siguen y se enuncia una vez aquí.

Todo camino que cree un `Owner`, le asocie una `Pet`, mute su teléfono o **lea
identidad por teléfono** pasa por el servicio único de `patients`, que normaliza
el número, toma un **lock de aviso transaccional** sobre `(organización,
teléfono normalizado)` —que cubre el caso «la fila todavía no existe», donde un
lock de fila no llega— y cuenta bajo él.

Cuatro desenlaces, exhaustivos: `created` · `reused` · **`409 owner_exists`** ·
**`409 owner_ambiguous`**. No hay rama que elija entre duplicados.
`owner_ambiguous` **no es opt-in**: aplica también a recepción, porque si el
dominio no sabe cuál es el expediente nadie puede fingir que sí. Los duplicados
históricos se listan (`audit_owner_phone_duplicates`) y los ordena una persona;
**nunca** se fusionan.

El `Owner` genérico queda fuera de todo esto: `phone_normalized = NULL` siempre.

`require_new_owner` (opt-in, solo en el registro rápido) es **INV-B aplicado**:
quien no tiene identidad verificada pide expediente nuevo y recibe
`409 owner_exists` si el número ya tiene uno, en vez de colgar una mascota de un
expediente ajeno.

---

### Acción: Crear Owner

**Requiere**
- Un usuario con permiso `patient.create`.
- Un `name` válido (el regex admite letras, números, acentos, espacios, apóstrofes y guiones).
- Un `phone` de exactamente 10 dígitos (formato de México), que además no sea un relleno evidente.

**Resultado** (bajo el lock de deduplicación)
- Sin expediente con ese teléfono → se crea el `Owner`, con `public_id` (UUID v4).
- **Con un expediente y el mismo nombre** (comparado sin acentos ni mayúsculas) → se **reutiliza** ese expediente: es el cliente que recepción quería, y crear un segundo fabricaría un duplicado.
- El `phone_normalized` lo deriva el dominio; nunca se acepta del cliente.

**Desbloquea**
- Registrar mascotas asociadas a este propietario.
- Facturar ventas directas con un owner real (ADR p25).

**Bloquea**
- **Un expediente existente con OTRO nombre** → **409 `owner_exists`** con el candidato (`public_id`, nombre), cero escrituras.
- **Dos o más expedientes con ese teléfono** → **409 `owner_ambiguous`**, cero escrituras y **sin** candidato en el cuerpo (publicarlo sería sugerir la elección que INV-C prohíbe).
- Su borrado: `DELETE` archiva el cliente y sus mascotas (orden 2); ver «Archivar y restaurar Owner o Pet».
- La eliminación del owner genérico → **409 `generic_resource_protected`**.

**Módulos involucrados**
`patients`.

---

### Acción: Cambiar el teléfono de un Owner

**Requiere**
- Permiso de edición del cliente. Dos vías equivalentes: `PATCH /api/owners/<public_id>/` y la escritura **anidada** desde `PATCH /api/pets/<public_id>/` (la ficha de la mascota).
- Un `phone` válido.

**Resultado**
- Cambiar el teléfono **mueve la clave de deduplicación**: libera una y ocupa otra. La operación bloquea **ambas** claves en **orden total** por el valor normalizado, y comprueba y escribe en el mismo bloque (la comprobación no puede vivir en `Serializer.validate`: DRF valida y guarda en pasos separados, y esa es la ventana que esto elimina).
- Reformatear el mismo número (`"5512345678"` → `"55 1234 5678"`) no mueve la clave: es una edición corriente.

**Bloquea**
- Clave nueva ocupada por **un** expediente → **409 `owner_exists`**: moverse ahí fabricaría un duplicado nuevo.
- Ocupada por **dos o más** → **409 `owner_ambiguous`**.
- En la vía anidada, un `409` **no deja ni el teléfono cambiado ni los campos de la mascota guardados**: la operación entera es una transacción.

**Lo que NO cambia**: el staff sigue pudiendo corregir un teléfono mal capturado, desde Clientes y desde la ficha de la mascota. Lo único que ya no puede es mover un cliente **encima** de otro sin que nadie lo note.

**Módulos involucrados**
`patients`.

---

### Acción: Crear Pet

**Requiere**
- Un `Owner` existente (no necesariamente real; puede ser el genérico en un escenario walk-in).
- `name`, `species` (de la lista cerrada `SPECIES_CHOICES`) y `birth_date` obligatorios.
- `sex` es opcional (por defecto `unknown`).
- **Uno de dos modos explícitos** (INV-B, ADR p57), nunca ambos ni ninguno:
  - **referencia** — `owner_public_id`: el cliente lo eligió una persona, y por eso es legítimo colgarle la mascota;
  - **alta** — `owner: {name, phone}`: pasa por el servicio único, bajo el lock.

  El alta **ya no infiere identidad por teléfono**: antes resolvía con `get_or_create(name, phone, organization)` —una segunda regla de deduplicación— que colgaba mascotas de expedientes localizados solo por coincidencia de número y fabricaba un segundo `Owner` cuando el teléfono coincidía pero el nombre no.

**Resultado**
- Se crea la `Pet` en la organización, con `public_id`; la FK al `owner` es PROTECT.
- La resolución del `Owner` y la creación de la `Pet` ocurren en **una sola transacción**, con el lock tomado antes de ambas: no existe el estado «cliente creado, mascota no».

**Desbloquea**
- Agendar citas, abrir consultas, emitir recetas, registrar vacunas y facturar (consultation) sobre esta mascota.

**Bloquea**
- **Modo alta con un expediente existente de OTRO nombre** → **409 `owner_exists`** con el candidato: la UI pregunta «¿es este cliente?» y reenvía en modo referencia, o corrige el teléfono. **Nunca** se crea un segundo expediente con el mismo número, y **nunca** se decide por el usuario.
- **Modo alta con dos o más expedientes** → **409 `owner_ambiguous`**: cero escrituras, se ordena el dato primero.
- Un `owner_public_id` de otra organización → 400 (no existe para este endpoint).
- Cambiar el cliente de una mascota existente (`owner_public_id` en `PATCH`) → 400: re-parentar es otra operación.
- Su borrado: `DELETE` archiva la mascota (orden 2); ver «Archivar y restaurar Owner o Pet».
- La eliminación de la mascota genérica → **409 `generic_resource_protected`**.

**Lo que NO cambia**: cliente nuevo → crea; cliente conocido con el mismo nombre → reutiliza, igual que hoy. Lo único nuevo es que el caso ambiguo **pregunta en vez de inventar**.

**Módulos involucrados**
`patients`.

---

### Acción: Archivar y restaurar Owner o Pet (orden 2, A5)

**Requiere**
- Ser ADMIN de la clínica, o operador de plataforma.
- Organización activa.
- Para archivar: ninguna cita `scheduled`, `confirmed` o `in_progress` ni consulta `open` de las mascotas afectadas.
- Para restaurar una mascota: su cliente activo.

**Resultado**
- `DELETE /api/owners/<id>/` (o `POST .../archive/`) archiva el cliente y todas sus mascotas; `DELETE /api/pets/<id>/` archiva la mascota. Guarda `archived_at` y `archived_by`; nada se borra.
- `POST .../restore/` restaura. Restaurar un cliente no restaura sus mascotas.

**Desbloquea**
- Ocultar el sujeto de listados y búsquedas sin perder su historia.
- Para plataforma, el borrado físico excepcional del sujeto ya archivado ([platform.md](modules/platform.md)).

**Bloquea**
- Actividad abierta, organización desactivada o sujeto genérico → **409 `archive_blocked`** (el `DELETE` de un genérico sigue en **409 `generic_resource_protected`**).
- Restaurar un cliente cuyo teléfono ocupó otro mientras estaba archivado → **409 `owner_exists`** u **`owner_ambiguous`** (INV-C).
- Listar archivados (`?archived=true`) sin ser ADMIN → **403**.

**Módulos involucrados**
`patients`, `appointments`, `medical_records`, `platform`.

---

### Acción: Registro rápido (Owner + Pet + Cita en un solo paso)

**Requiere**
- Permiso `appointment.create`.
- Datos completos: `owner_name`, `owner_phone` (10 dígitos), `pet_name`, `pet_species` y los datos de la cita.
- Opcional: `require_new_owner` (bool, default `false`). Solo `true`/`false`; cualquier otro valor → **400** (interpretarlo como `false` relajaría INV-B en silencio, justo para el llamador que la necesita).

**Resultado** (atómico — el expediente lo resuelve el servicio único de `patients` bajo el lock de deduplicación, dentro de la misma transacción que crea la cita)
- Sin expediente con ese teléfono → crea el Owner.
- Con **un** expediente y sin `require_new_owner` → lo reutiliza (el cliente regresa con una nueva mascota).
- Crea siempre una Pet nueva.
- Crea el Appointment con toda la validación habitual (detección de conflictos, fecha pasada, timezone).

**Desbloquea**
- El flujo normal de atención a partir de la cita creada.

**Bloquea**
- **Un expediente existente con `require_new_owner=true`** → **409 `owner_exists`** con el candidato (INV-B: el teléfono localiza, no autoriza).
- **Dos o más expedientes** → **409 `owner_ambiguous`**, con o sin el flag (INV-C no es opt-in).
- Los dos 409 no dejan **nada**: ni Owner, ni Pet, ni Appointment, y **no modifican** el expediente que encontraron.
- Dos altas concurrentes con el mismo teléfono normalizado no pueden fabricar dos expedientes: el lock las serializa.
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

### Garantías transversales del módulo (ADR p57)

Dos invariantes aplican a **todas** las acciones de agenda que siguen. Se
enuncian una vez aquí para no repetirlos en cada acción.

**INV-A — precondición atómica de estado.** Toda mutación sobre una cita
existente (`PATCH` de detalle, `PATCH /status/`, `DELETE`, `assign-patient`)
**exige** `expected_state = {status, date, start_time}` y lo compara contra la
fila tomada con `select_for_update()`, dentro de la transacción que escribe. Si
difiere: **`409 appointment_changed`** con `current` (el estado real) y **cero
escrituras** — ni la cita, ni `AppointmentStatusChange`. El 409 no es un error
técnico: es un resultado de negocio. Si falta: **`400 precondition_required`**
(obligatoria desde la Fase 3 — antes era opt-in mientras el frontend la
adoptaba; volverla obligatoria destapó dos escritores ciegos que el opt-in
hacía indistinguibles de los que sí cumplían). Excluida con justificación:
`complete_appointment_on_record_close` (transición interna que ya falla cerrada
y evita un orden de locks `Appointment↔MedicalRecord`).

**INV-D — no-solapamiento.** Un veterinario no puede tener dos citas **activas**
(`scheduled`, `confirmed`, `in_progress`) con intervalos solapados. Lo garantiza
una restricción de exclusión de PostgreSQL sobre `(organization, veterinarian,
[start_datetime, end_datetime))`, así que cubre a **cualquier actor** y a todas
las vías, incluidas las que antes no validaban cupo. El desenlace es siempre
**`400 slot_taken`**, lo detecte el pre-chequeo o lo rechace la base. **No
existe bandera de forzado**, y nada se desplaza automáticamente.

---

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
- La creación de una cita que se superponga en la misma franja horaria para el mismo veterinario → `400 slot_taken`. Ya no depende de ganar una carrera: si dos creaciones concurrentes apuntan al mismo hueco, exactamente una persiste (INV-D).
- `expected_state` en el body → `400`: no hay estado previo que comparar.

**Módulos involucrados**
`appointments`, `patients`, `users`.

---

### Acción: Walk-in (sin cita previa)

**Requiere**
- Un veterinario de la organización.
- `pet` obligatorio, salvo que `allow_anonymous_walkin=True` — en ese caso se usa la mascota genérica.
- `reason` (texto sanitizado, máximo 255 caracteres, no puede quedar vacío tras sanitizar).

- Que el veterinario **no** tenga una cita activa solapada con los 30 minutos de la atención (INV-D, ADR p57).

**Resultado**
- Se crea un `Appointment` directamente en estado `in_progress`, con `walk_in=True` y duración de 30 minutos.

**Desbloquea**
- La apertura inmediata de una consulta médica.
- Si la cita se creó con mascota genérica, se puede usar `assign-patient` para vincular un paciente real (siempre que la cita no esté en `done`).

**Bloquea**
- La cancelación de la cita ya no aplica las transiciones propias de `scheduled`/`confirmed` (porque ya está en `in_progress`).
- **La atención sobre un veterinario ocupado → `400 slot_taken`, cero citas creadas** (cambio de comportamiento aprobado, ADR p57 / decisión §9.14). Antes se creaba sin comprobar solapes y la agenda mostraba dos atenciones simultáneas del mismo veterinario, que nunca fueron reales. Recepción escoge alternativa: otro veterinario u otro horario. **No hay bandera de forzado ni sobrecupo.**

**Módulos involucrados**
`appointments`, `patients`.

---

### Acción: Cambiar estado (PATCH `/status/`)

**Requiere**
- Permiso `appointment.update`.
- Una transición válida según la máquina de estados.
- Si `require_confirmation_before_start=True` → bloquea el salto directo `scheduled → in_progress` (exige pasar por `confirmed` primero).
- Obligatorio: `expected_state` (INV-A; su ausencia → `400 precondition_required`). **Toda** la decisión —precondición, transición, toggles, guard de fecha— se evalúa sobre la fila **bloqueada**, dentro del `atomic()` que escribe.

**Resultado**
- El estado se actualiza.
- Se registra un `AppointmentStatusChange` (append-only) con `from_status → to_status`, `changed_by` y `reason`.
- Llegar a `done` no crea documentos financieros. La preparación comercial nace al cerrar el `MedicalRecord` real.
- Si el nuevo estado es `done` y `auto_create_medical_record=True` → se crea un `MedicalRecord` vacío en `open`.

**Desbloquea** (al llegar a `in_progress`)
- Abrir o editar la consulta médica vinculada.

**Desbloquea** (al llegar a `done`)
- Crear una consulta médica desde el detalle de la cita (CTA `+ Crear Consulta Médica`).
- Cerrar la consulta y preparar su Checkout; la transición de Appointment por sí
  sola no crea Checkout ni Invoice.

**Bloquea**
- Transiciones inválidas → 400 con `error` descriptivo.
- `done` es terminal: no admite ninguna transición posterior.
- `expected_state` desfasado → `409 appointment_changed` con `current`, sin transición y **sin** `AppointmentStatusChange`.
- **Reactivación `canceled|no_show → scheduled` sobre un hueco ya reasignado → `400 slot_taken`** (cambio de comportamiento aprobado, ADR p57 / decisión §9.15). La cita **sigue** en su estado terminal y hay que programarla de nuevo; nada se desplaza ni se reubica automáticamente. Es coherente con el guard de fecha pasada que ya vivía en esta transición.

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
- El hueco queda **libre**: `canceled` está fuera del predicado de INV-D.

**Desbloquea**
- Reprogramar la cita si la fecha original no ha pasado **y el hueco sigue libre** (`canceled → scheduled`).

**Bloquea**
- Cancelar desde `done` (no está permitido).
- Reprogramar si la fecha original ya pasó (en ese caso debe crearse una cita nueva).
- Reprogramar si el hueco ya se reasignó → `400 slot_taken` (INV-D).

**Nota de deprecación (ADR p57)**: `DELETE /api/appointments/<id>/` está
**deprecado** a favor de `PATCH /<id>/status/`. Sigue funcionando y respeta
INV-A, pero emite `Deprecation`/`Sunset` (RFC 8594, Sunset 2026-11-06) y el log
`DEPRECATED_ENDPOINT_HIT`. Bajo conflicto de precondición **no** produce una
segunda fila de auditoría.

---

### Acción: Asignar paciente real (vincular desde genérico)

**Requiere**
- Una cita walk-in cuya mascota actual sea `pet.is_generic=True`. La comprobación se re-evalúa sobre la fila **bloqueada**: entre la lectura y el lock, otro actor pudo haber vinculado ya el paciente real.
- Que el estado de la cita **no** sea `done`.
- Un nuevo `pet` válido (misma organización, no genérico).
- Obligatorio: `expected_state` (INV-A). Entra al contrato porque muta la cita y escribe auditoría; queda **fuera** de INV-D porque no toca `veterinarian`, `date`, `start_time` ni `end_time`.

**Resultado**
- `appointment.pet` se actualiza al paciente real.
- Si existe un `MedicalRecord` abierto vinculado a la cita, su `pet` también se actualiza.
- Se registra un `AppointmentStatusChange` con la descripción correspondiente.

**Bloquea**
- Vincular otra mascota genérica → 400.
- Vincular sobre una cita que ya está en `done`.
- `expected_state` desfasado → `409 appointment_changed`, sin cambio de paciente y sin fila de auditoría.

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
- Se crea un `MedicalRecord` en estado `open` con
  `consultation_type='general'` (valor por defecto).
- No se crea Checkout ni Invoice. La preparación comercial se materializa al
  cerrar la consulta.

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
- Una presentación cuyo producto tenga stock base suficiente y, si administra
  lotes, asignaciones FEFO consumibles suficientes.
- Si el `Product` tiene `requires_prescription=True`, debe existir una receta activa que contenga ese producto dentro de la misma consulta.
- La operación completa debe ejecutarse dentro de `transaction.atomic()`.

**Resultado** (siguiendo el orden de locks canónico)
1. Bloquea el `MedicalRecord` y los recursos de inventario según el orden global.
2. Ejecuta `apply_stock_movement('out')` → registra el consumo clínico en
   unidades base y actualiza `Product.stock_quantity`/lotes.
3. Crea o actualiza el `MedicalRecordProduct`.
4. Registra un `ClinicalChargeQuantityEvent` append-only sobre un ciclo de precio inmutable.
5. No crea `Invoice`; al cierre, el ciclo activo se copia a `ClinicalChargeSnapshot` y `CheckoutItem`.

**Desbloquea**
- La preparación comercial que se materializa al cerrar la consulta.

**Bloquea**
- La eliminación de la consulta mientras exista evidencia clínica o comercial
  dependiente → 403.
- Stock negativo (la validación ocurre bajo lock).

**Módulos involucrados**
`medical_records`, `inventory`, `billing`.

---

### Acción: Agregar servicio

**Requiere**
- Consulta en `open`. El VET asignado (o un ADMIN).
- Un `service` activo de la organización.
- La operación dentro de `transaction.atomic()`.

**Resultado** (atómico)
1. Bloquea el `MedicalRecord`.
2. Crea o incrementa el `MedicalRecordService`.
3. Registra el delta mediante `record_clinical_charge_delta` sobre
   `ClinicalChargeEntry` y `ClinicalChargeQuantityEvent`.
4. No crea Checkout ni Invoice; al cierre se congela el snapshot clínico y se
   materializa el `CheckoutItem`.

**Desbloquea**
- Incluir el servicio en el Checkout creado al cerrar la consulta.

**Bloquea**
- Editar cargos después del cierre. Incrementos repetidos antes del cierre se
  acumulan como eventos explícitos, no como InvoiceItems prematuros.

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
- Cédula profesional de quien la emite, que es su firmante (orden 7, ADR p64).
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
- Cédula profesional del veterinario de la consulta, que la firma, aunque cierre un ADMIN (orden 7, ADR p64). Se congela en `vet_license_at_close`.

**Resultado** (atómico, ADR p30)
- `status='closed'`. `closed_at = now()`. `closed_at_source='service'`. `closed_by` registrado.
- Materializa o adopta exactamente un `Checkout kind=primary_consultation`, copia snapshots clínicos y crea decisiones de receta pendientes. No existe `Invoice` hasta postear/cobrar.
- La operación es idempotente: cerrar dos veces no re-valida ni genera artefactos adicionales.
- Si `closed_at` cae dentro de un bucket frozen de analytics → se registra el log `ANCHOR_LATE_ARRIVAL` (WARNING, solo advertencia).

**Desbloquea**
- La visualización del Checkout en “Por preparar” de Cobros, incluso si suma $0.
- La selección/dispensación comercial de la receta sobre ese Checkout.

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
- Que exista un Checkout clínico `open` para la consulta cerrada.
- Permiso `billing.rx_dispense` (ADMIN y VET lo tienen por defecto).
- Body con `lines=[{presentation, quantity, prescription_item}]`.

**Resultado** (atómico)
- Agrega `CheckoutItem` retail ligados a `PrescriptionItem` y marca la selección `accepted`; `declined` no altera la receta clínica.
- **No mueve stock en este momento**: el post autoritativo revalida el cap Rx, crea `InvoiceItem`, `StockAllocation`, `StockDispositionEvent`, `PrescriptionFulfillmentEvent` y el movimiento de salida juntos.
- Devuelve el Checkout actualizado (200).
- No crea `ExternalPrescriptionAttestation` (la receta interna ya es el respaldo legal).

**Desbloquea**
- Postear y, opcionalmente, pagar el Checkout que incluye consulta y dispensación.

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
- Se crean el `Product` y su presentación inicial. El stock comercial se
  normaliza a unidades base en `Product.stock_quantity`; para productos con
  lotes, `StockLot.quantity_on_hand` conserva el desglose consumible.

**Desbloquea**
- Venderlo en una factura, usarlo como insumo en consulta o recetarlo (si `requires_prescription=True`).

---

### Acción: Recibir mercancía por lotes (operación durable)

**Requiere**
- Permiso `inventory.update` y un producto con `tracks_lots`.
- Un identificador de operación UUID generado por el cliente al preparar. Después, ninguno: la recuperación no lo pide.

**Resultado**
- Preparar guarda la captura como `pending`, sin tocar stock.
- Completar aplica exactamente esa captura en una transacción: stock, lotes, movimientos enlazados y `confirmed`.
- Descartar la cierra sin aplicarla, con motivo, autor y fecha. Nunca elimina ni compensa movimientos.

**Desbloquea**
- Tras perder respuesta, sesión y navegador, consultar en Inventario → Recepciones qué registró el servidor,
  y resolver lo pendiente con su misma identidad, sin volver a capturar ni a crear el producto.

**Bloquea**
- Una entrada nueva del mismo producto y actor mientras haya un `pending` → `409 reception_unresolved`. Se resuelve
  y entonces se registra: dos recepciones iguales siguen siendo válidas, porque no se deduplica por contenido.
- Ejecutar la operación de otra persona, aunque se conozca su identidad.

**Módulos involucrados**
`inventory`.

---

### Acción: Ajustar stock (gestión manual)

**Requiere**
- Permiso `inventory.update`.
- La operación debe ejecutarse dentro de `transaction.atomic()` y tomar los
  locks de Product/lotes requeridos por el servicio de inventario.

**Resultado**
- Se registra un `StockMovement` de tipo `in`, `out` o `adjustment`.
- `Product.stock_quantity` se actualiza en unidades base mediante
  `apply_stock_movement()`.
- En productos con lotes, la suma consumible de
  `StockLot.quantity_on_hand` debe converger con el stock del producto.

**Reglas duras**
- `Product.stock_quantity` y `StockLot.quantity_on_hand` son las autoridades
  de inventario.
- `Presentation.stock` es un campo legacy/display y Billing no lo consulta
  para disponibilidad, límites ni post.
- El caller debe respetar el orden de locks definido por el servicio.
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
- Sin `adjustment`, el saldo se reconstruye desde 0, así que un stock que el libro no explica es drift. Solo los productos con movimientos legacy quedan como `no_baseline` (informativo).

---

### Efectos cruzados de stock

| Origen | Resultado en stock |
|--------|--------------------|
| Producto consumido en consulta | `−quantity_base` al consumirse |
| Item retail en Checkout `direct_sale` | `−quantity × factor_snapshot` al postear |
| Item dispensado de receta | `−quantity × factor_snapshot` al postear |
| Void/reemplazo con devolución autorizada | retorno exacto según `StockAllocation`, por lote |
| Nota de crédito con `disposition=restock` | `+quantity` al emitir refund |
| Nota de crédito con `disposition=discard` | sin movimiento de stock |

---

## 7. Cobros (Billing)

> Contrato vigente: [ADR p62](decisions/2026-08-30-p62-billing-checkout-lifecycle.md)
> y [modelo de eventos financieros](financial-event-model-contract.md).

### Flujo vigente

- `Checkout` es la preparación comercial mutable. Estados: `open → completed|abandoned`;
  readiness y acciones permitidas se derivan, no se persiste un estado `ready`.
- `Invoice` es un documento financiero inmutable que nace al postear. Estados:
  `posted → paid` o `posted → voided`; anchors nativos `posted_at`, `paid_at`,
  `voided_at`.
- Una consulta cerrada crea un `Checkout primary_consultation`; una consulta en
  $0 termina `no_charge` sin crear Invoice.
- POS crea un `Checkout direct_sale`; post/pago crea Invoice, líneas, movimientos
  de stock y Payments dentro de una sola transacción.
- No existe `confirm`: emitir y cobrar son comandos separados solo cuando hay
  crédito explícito. Los pagos parciales y sobrepagos están prohibidos.
- La receta es sugerencia clínica. Aceptar crea líneas retail; rechazar conserva
  la receta y no mueve stock. El stock sale al postear, con allocation,
  disposición y fulfillment Rx append-only.
- El backend devuelve `remaining_quantity_base`,
  `available_stock_quantity_base` y `max_selectable_quantity`; el frontend
  los presenta y no recalcula el dominio.
- `CheckoutItem.quantity` e `InvoiceItem.quantity` están en unidades de
  presentación. El `conversion_factor_snapshot` expresa unidades base por
  presentación y congela la conversión usada al postear.
- Un medicamento de venta directa exige `ExternalPrescriptionAttestation`
  vigente para la revisión/fingerprint exactos de la línea.
- Corregir una Invoice emitida usa `void_and_prepare_replacement`: void y Checkout
  replacement nacen atómicamente. El baseline entregado no puede abandonarse,
  expirar ni reducirse a cero sin waiver autorizado y auditado.
- Refunds usan `CreditNote` + `RefundPayment`; una reversa monetaria usa
  `RefundReversal`. Dinero, stock/custodia y fulfillment Rx se proyectan como
  hechos independientes.
- Todo comando terminal usa `CommandReceipt`; los eventos financieros hijos se
  identifican por `(command_receipt, command_line_index)`.

### Comandos principales

| Caso | Comando | Resultado |
| --- | --- | --- |
| Consulta cerrada | `get_or_create_primary_checkout_for_medical_record` | Checkout open, snapshots y selecciones |
| Venta directa | `create_direct_sale_checkout` + items | Checkout open |
| Cobro inmediato | `post_checkout` con payment lines | Invoice paid + Payments + stock |
| Crédito autorizado | `post_checkout` sin pago | Invoice posted/unpaid + evidencia |
| Sin cargos | `complete_no_charge` | Checkout completed/no_charge, sin Invoice |
| Pago posterior | `pay_invoice` | Invoice paid; exige saldo total exacto |
| Corrección | `void_and_prepare_replacement` | Invoice voided + replacement open |
| Anulación terminal | `void_invoice_terminal` | Invoice voided con motivo/evidencia |

Todos los comandos mutantes exigen `expected_version` e
`idempotency_key`. Para validar el schema físico antes o después de un
despliegue, ejecutar `audit_billing_schema --json` siguiendo el
[runbook de reconciliación](runbooks/billing-schema-reconciliation.md).

<details>
<summary>Archivo histórico del contrato retirado — no ejecutar</summary>

El contenido siguiente describe la máquina anterior
`draft → confirmed → paid/cancelled`. No es ejecutable ni normativo desde ADR p62.

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

</details>

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
| `Invoice.paid_at` | `post_checkout` con pago / `pay_invoice` | `revenue_paid`, `invoices_paid_count` |
| `Invoice.posted_at` | `post_checkout` | `revenue_accrual` |
| `Invoice.voided_at` | `void_invoice_terminal` / `void_and_prepare_replacement` | anulaciones y provenance |
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
| `post_checkout` con pago o `pay_invoice` exitoso | inmediato | sí, fecha local de la org |
| `post_checkout` unpaid exitoso | inmediato | sí en `revenue_accrual` |
| Invoice pasa a `voided` | inmediato | anulación/provenance; no es revenue pagado |
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
## Operación REGISTER_PET B8E (2026-09-25)

El alta autónoma individual usa exclusivamente una ConversationOperation autorizada
por B7B y el guard B8A. No usa endpoints/serializers desde el LLM. El owner procede
de ContactIdentity→Goal→Operation; no hay búsqueda por teléfono/nombre durante execute.
Patients comparte su creación humana de referencia con el adapter y guarda un ledger
histórico exacto e inmutable. Se permiten mascotas parecidas distintas; se impide
repetir el efecto de la misma operación. No crea owner, cita ni MedicalRecord.

Los cinco adapters permanecen OFF; no deploy ni B9. Contrato y evidencia:
[B8E](contrato-register-pet-b8e.md), [acta](implementacion-b8e-agente-whatsapp-2026-09-25.md).
