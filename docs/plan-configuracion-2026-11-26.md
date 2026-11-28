# Plan de implementación — Módulo Configuración

**Fecha:** 2026-11-26
**Revisión:** 2 (incorpora la revisión externa del 2026-11-26, §0.1)
**Estado:** APROBADO por el PO el 2026-11-26 (D1–D9 según la recomendación), con dos
condiciones explícitas recogidas en el [ADR p70](decisions/2026-11-26-p70-configuracion-clinica-fase-2.md):
(1) el bloqueo de INV-L es atómico, con el mismo orden en ambas rutas, validando contra el estado
persistido y sin escrituras masivas ni fixtures que lo eviten; (2) la atención sin cita bloquea la
organización **antes** de leer la zona y calcular los instantes. Autorizado F0 (F0.1–F0.3). Si el
código contradice lo aprobado, se detiene y se pide decisión.
**Origen:** [auditoría del módulo Configuración](auditoria-modulo-configuracion-2026-11-26.md)
(hallazgos C1–C20 y comparación con los módulos de configuración de Shepherd, Digitail, Provet,
Vetspire y ezyVet).
**Contratos que toca:** [ADR p53](decisions/2026-07-21-p53-clinic-configuration-aggregates.md),
[`modules/organizations.md`](modules/organizations.md), [`modules/agent.md`](modules/agent.md),
[`modules/appointments.md`](modules/appointments.md), [`modules/billing.md`](modules/billing.md),
[`modules/frontend.md`](modules/frontend.md).

**Datos:** no existen clínicas, usuarios ni datos reales, ni en producción ni en develop
(`CLAUDE.md`, confirmado por el PO). En consecuencia:

- las migraciones de datos pueden normalizar directamente, sin backfills conservadores ni
  convivencia de versiones;
- las políticas que solo protegerían datos existentes se simplifican;
- se mantiene todo lo que protege a los usuarios futuros (invariantes, seguridad, aislamiento,
  pruebas) y que las migraciones apliquen limpias en desarrollo, CI y la demo
  (`seed_demo_clinic`).

Rutas relativas a la raíz del repositorio.

---

## 0. Resumen

| Fase | Qué resuelve | Hallazgos | Importancia | Complejidad | Esfuerzo |
|---|---|---|---|---|---|
| F0 | Los tres P1: teléfono ↔ agente (en los dos lados), coherencia del precio con IVA en todas las pantallas, zona horaria protegida | C1, C2, C3 | Crítica | Media | M–L |
| F1 | Consolidación: registro de cambios, navegación por dominio, «Mi cuenta», permisos, estados de pantalla, ajustes sin efecto, servicios | C5–C12, C14, C16, C18–C20 | Alta | Media | L |
| F2 | Operación: cierres excepcionales, agenda con horario, duración por defecto, datos de la clínica en PDFs | C8, C13, C15, brecha de mercado | Media-alta | Media-alta | L |
| En espera | IVA editable por la clínica (C4) y recálculo de citas al cambiar de zona: solo con sus condiciones cumplidas (§6) | C4, C1 (resto) | — | — | — |

S = horas · M = 1–2 días · L = 3+ días. Cada ítem es un PR revisable por separado (§7).

Lo que **no** cambia: el modelo de tres agregados de p53, el aislamiento multi-tenant, el
`PUT` atómico del horario, las reglas de caja y crédito en servidor y el flujo de primer uso.

### 0.1 Cambios respecto a la revisión 1

| Observación de la revisión | Verificación en código (2026-11-26) | Cambio en el plan |
|---|---|---|
| **B1.** El invariante teléfono ↔ agente no estaba demostrado: solo se protegía el serializer de organizaciones | Escritores de `Organization.phone`: `OrganizationSerializer`, admin de Django (sin validación de formato), `seed_demo_clinic`, `agent_eval` (por `queryset.update`, después de crear el agente encendido). Escritores de `AgentSettings.enabled`: `AgentSettingsSerializer` (único con gate), `agent_eval` (lo crea encendido sin teléfono), `provision_channel` y la vista del Inbox (ambos crean apagado). No hay admin de `AgentSettings`. Ninguno bloquea la fila de la organización [E] | F0.1 rediseñado: regla en los **modelos** de ambos lados, bajo el lock de la fila de la organización, gate estático contra escrituras masivas, migración que apaga agentes con teléfono inválido y pruebas desde los dos lados con entrelazado forzado |
| **B2.** Cambiar el IVA con `organization.update` es demasiado amplio; 0–16 % no es una política fiscal | `organization.update` es delegable por ADR p69 (no está en `ADMIN_RESERVED`). La pantalla de plataforma ya ofrece tres valores (0 %, 8 % frontera, 16 % general) pero el backend acepta cualquier valor entre 0 y 1 [E] | La clínica **no** edita el IVA en este plan: solo lo ve (F0.2). La edición pasa a «en espera» (§6) con tres condiciones: política fiscal validada por un contador, permiso dedicado reservado a ADMIN y pruebas del ciclo de vida del cobro |
| **R3.** La zona horaria necesita política explícita: no es lo mismo una zona mal configurada que una mudanza; inventario de consumidores temporales como condición | Inventario hecho (§3.F0.3): solo `Appointment` guarda un par hora local / instante; el resto son fechas locales puras o instantes reales; **no existen recordatorios programados**. La creación y la edición de citas ya bloquean la organización con `FOR SHARE` (`appointments/creation.py` ≈L135, `mutations.py` ≈L154); **la atención sin cita no** (`appointments/views.py` ≈L805) [E] | Sin datos reales, la política es: la zona se fija en la puesta en marcha y se cambia libremente **mientras no haya citas futuras activas**; con citas, el cambio se bloquea. Los dos modos de recálculo («corregir» y «mudanza») quedan definidos y en espera (§6). La atención sin cita pasa por el mismo lock |
| **R4.** F0.2 no cerraba la coherencia del precio en inventario, POS y Cobros | Inventario de puntos de contacto hecho (§3.F0.2): Servicios, Inventario, búsqueda y carrito del POS, cargos de la consulta y agente muestran precios sin IVA sin decirlo; los totales de Cobros, el panel de pago del POS y el panel de la consulta sí desglosan. Conviven cuatro formateadores de moneda [E] | F0.2 amplía la regla a todas las pantallas, sin cálculo de impuestos en React (regla del POS): el backend entrega base, tasa y total |
| **R5.** F1.8 afirmaba que los cobros abiertos conservan su tasa sin probarlo | En código: la consulta fija la tasa en su primer cargo cobrable (`MedicalRecordBillingContext`, `provenance='first_billable'`); la venta directa, al crear el Checkout; el reemplazo hereda la de la factura anulada; la factura copia la del Checkout [E, lectura de código, no probado] | F1.8 sale del plan. La prueba del ciclo de vida completo es condición previa de cualquier edición futura del IVA (§6) |

---

## 1. Principios

1. **Lo que se ve hace lo que dice.** Un ajuste sin efecto se conecta o se retira; no se queda
   visible.
2. **El servidor garantiza, la UI explica.** Toda regla nueva se aplica en backend; el frontend
   solo previene y explica.
3. **Un invariante se protege en todos sus escritores.** Se enumeran con evidencia, cada uno
   queda cubierto o excluido explícitamente, y un gate estático vigila los que aparezcan después
   (mismo criterio que INV-C e INV-J).
4. **Fronteras.** `organizations` no importa `agent`; el agente puede leer `organizations`. Los
   efectos sobre otros dominios pasan por un servicio de ese dominio.
5. **Sin matemática financiera en React** (contrato del POS): el backend entrega base, impuesto y
   total; el frontend los muestra.
6. **Servicios, no vistas gordas.** Las escrituras de configuración pasan a servicios
   (`apps/organizations/services.py`, `apps/billing/catalog_services.py`), que es donde se
   registra el evento de auditoría.
7. **Reutilizar antes de crear:** `handleFormError`, `useConfirm`, `EmptyState`, `useBlocker`
   (como en `ConsultationForm.jsx`), el patrón de copia de catálogo con prueba de contraste
   (`features/staff/specialties.json`) y el evento de solo inserción (`StaffAccessEvent`).

---

## 2. Decisiones del PO

| # | Decisión | Opciones | Recomendación | Bloquea |
|---|---|---|---|---|
| D1 | Cambio de zona horaria | (a) libre mientras no haya citas futuras activas; con citas, bloqueado · (b) recalcular las citas en uno de dos modos (§6) | **(a)**: sin clínicas reales, la zona se fija al empezar y no hay citas que mover. Los modos de recálculo se definen ahora y se implementan cuando una clínica real lo necesite | F0.3 |
| D2 | Garantía de «agente encendido ⇒ teléfono válido» | (a) una vez válido, el teléfono puede cambiar por otro válido pero no vaciarse ni volverse inválido; encender el agente exige teléfono válido; ambas reglas en los modelos y bajo el lock de la organización · (b) vaciar el teléfono apaga el agente | **(a)**: el estado «teléfono válido» se vuelve absorbente, así que ningún orden de escrituras concurrentes puede violar el invariante (§3.F0.1) | F0.1 |
| D3 | IVA editable por la clínica | (a) no en este plan: visible de solo lectura; lo fija plataforma · (b) editable ya | **(a)**. Requiere política fiscal validada, permiso dedicado reservado a ADMIN y pruebas del ciclo de cobro (§6) | — |
| D4 | Captura y presentación del precio | (a) se captura sin IVA; las pantallas del personal muestran «sin IVA» y, cuando el backend lo entrega, el total con IVA; lo que ve el cliente (agente, documentos) dice el total con IVA · (b) capturar con IVA incluido | **(a)**: (b) cambia el cálculo de cobros | F0.2 |
| D5 | Ajustes sin consumidor | Retirar o conectar cada uno | **Retirar** `allow_emergency_walkin`, `appointment_buffer_minutes`, `week_starts_on` y `OrganizationSettings.locale`. **Conectar** `default_appointment_duration_minutes` (F2.3) y `display_name` (F1.6). `currency_code` de solo lectura (MXN) | F1.6 |
| D6 | Cierres excepcionales | (a) bloquean al agente y advierten al staff · (b) bloquean a ambos | **(a)**: el staff puede atender una urgencia en día cerrado | F2.1 |
| D7 | Cita del staff fuera de horario | (a) advertir con confirmación · (b) bloquear | **(a)** | F2.2 |
| D8 | Quién entra a `/config` | (a) solo quien gestiona algo (`organization.update` o `service.create/update/destroy`); el resto redirige a `/` · (b) lectura para todos | **(a)**, igual que Equipo; la cuenta personal pasa a `/account` para todos | F1.2 |
| D9 | Quién ve el historial de cambios | (a) quien tenga `organization.update` · (b) solo ADMIN | **(a)** | F1.1 |

Todas se registran en un **ADR p70** antes del código (F0.0).

---

## 3. Fase 0 — Riesgos (P1)

### F0.0 ADR p70 — Configuración de clínica, fase 2

- **Archivo:** `docs/decisions/2026-11-26-p70-configuracion-clinica-fase-2.md`.
- **Contenido:**
  - D1–D9;
  - el invariante teléfono ↔ agente con su lista de escritores;
  - la política de zona horaria y los dos modos de recálculo en espera;
  - la regla de presentación del precio;
  - el retiro de ajustes de p53;
  - los cierres excepcionales (amplía la restricción «sin feriados» de p53);
  - el registro de cambios.
- p53 queda marcado «Implementado; ampliado por p70».
- **Esfuerzo:** S. **Bloquea:** el resto de F0, F1.1, F1.6, F2.1.

### F0.1 Invariante teléfono ↔ agente, en los dos lados (C2)

**Invariante (INV-L, siguiente libre tras INV-K de `system-reference.md`):** no existe una `AgentSettings` con `enabled=True` cuya
organización no tenga un teléfono válido (`apps.core.validators.is_valid_mx_phone`).

**Por qué basta con estas dos reglas.** Una vez que un teléfono es válido, solo puede cambiar por
otro válido. Encender el agente exige teléfono válido. Entonces la única carrera posible es que se
intente encender leyendo un teléfono todavía vacío, y esa escritura se rechaza (dirección segura).
El lock compartido de la fila de la organización hace que esa lectura sea la vigente y no una
copia vieja.

**Escritores y cómo queda cubierto cada uno** [E, enumeración 2026-11-26]:

| Campo | Escritor | Cobertura |
|---|---|---|
| `Organization.phone` | `PATCH /api/organizations/me/` | Regla en `Organization.save()` + mensaje de campo en el serializer |
| | Admin de Django | `Organization.save()` (el admin pasa por `save`) |
| | `seed_demo_clinic` | `save()`; su número (`DEMO_ORG_CONTACT`) ya es válido |
| | `agent_eval` (`queryset.update`) | Se cambia a `save()` antes de crear la configuración del agente |
| `AgentSettings.enabled` | `PATCH /api/inbox/settings/` | Regla en `AgentSettings.save()` + mensaje en el serializer |
| | `agent_eval` (`objects.create(enabled=True)`) | `save()` con la regla: el teléfono se guarda antes |
| | `provision_channel`, `views.py` (≈L849) | Crean apagado; cubiertos por la misma regla |

**Reglas en modelo:**

- `Organization.save()`: un teléfono no vacío debe ser válido. Si cambia el teléfono de una
  organización existente, se relee el valor vigente con `select_for_update()` dentro de la
  transacción; si es válido, el nuevo no puede ser vacío ni inválido.
- `AgentSettings.save()`: si `enabled` es verdadero, bloquea la fila de la organización
  (`select_for_update()`) y comprueba el teléfono; si no es válido, `ValidationError`.
- Ambos lados bloquean **la misma fila** (`Organization`), así que se serializan entre sí. Orden:
  `Organization` antes que cualquier otra fila. Antes de codificar, verificar que no invierte el
  orden de `durable.py` (≈L142) ni `sender.py` (≈L113, L173), que ya bloquean la organización
  desde el agente.
- Los serializers conservan sus mensajes para el usuario y llaman al mismo predicado.

**Escrituras masivas:** prueba estática que falla si aparece `update(phone=…)` sobre
`Organization` o `update(enabled=…)` / `bulk_update` sobre `AgentSettings` fuera de una lista
vacía de excepciones.

**Datos existentes:** migración de datos que apaga todo `AgentSettings` cuya organización tenga
teléfono vacío o inválido y vacía los teléfonos inválidos. Sin datos reales, normalizar es lo
correcto. Después de la migración, el invariante se cumple en toda base de desarrollo, CI y demo.

**Frontend:** `ClinicSection.jsx` muestra el error del servidor en el campo (con F1.3; hasta
entonces, toast).

**Pruebas:**

- Lado organización:
  - vaciar uno válido → 400 por API y `ValidationError` por `save()`;
  - inválido → rechazado;
  - vacío sobre vacío → permitido;
  - cambiar por otro válido → permitido.
- Lado agente:
  - encender con teléfono vacío o inválido → 400 por API y `ValidationError` por `save()`;
  - `agent_eval` sigue creando su organización de prueba.
- Concurrencia (PostgreSQL, entrelazado forzado, viendo la espera en `pg_stat_activity`):
  encender el agente mientras otra transacción tiene la organización bloqueada para cambiar el
  teléfono, y al revés. El resultado nunca viola el invariante.
- Gate estático de escrituras masivas.
- Migración: una base con el agente encendido y sin teléfono queda apagada.

**Docs:** `organizations.md` § Teléfono; `agent.md` § Gate del kill switch (en dos direcciones y
con la lista de escritores); ADR p70.

**Aceptación:** todas las filas cumplen el invariante tras la migración, y cada escritor
enumerado lo respeta, probado desde su lado.

**Esfuerzo:** M.

### F0.2 Precio coherente en todos los puntos de contacto (C3)

**Regla (D4):**

- **Personal:** todo precio unitario antes del documento se rotula «sin IVA»; donde el backend
  lo entrega, se muestra además el total con IVA.
- **Cobros, consulta y POS en pago:** desglosan subtotal, IVA (con la tasa) y total.
- **Cliente (agente y documentos):** precio con IVA incluido, dicho expresamente.
- **Cálculo:** nunca en React.

**Inventario de puntos de contacto** [E, 2026-11-26]:

| Pantalla | Hoy | Cambio |
|---|---|---|
| Configuración → Servicios (`ServicesSection.jsx`) | «PRECIO BASE»; lista `$500.00` sin rótulo | «Precio sin IVA» con la nota «Al cobrar se suma IVA (16 %)»; lista `$500.00 sin IVA · $580.00 con IVA` con los campos del backend |
| Inventario (`pages/inventory.jsx`) | Columna «Precio unit.» y precio de presentación sin rótulo | «Precio sin IVA»; en el detalle, total con IVA del backend |
| POS: búsqueda (`components/pos/ProductSearch.jsx`) | `$sale_price` / `$base_price` con `toFixed`, sin rótulo | Rótulo «sin IVA» y total con IVA del backend |
| POS: carrito y pago (`Cart.jsx`, `PaymentPanel.jsx`) | Carrito: «Subtotal» sin rótulo; pago: «Total estimado» con aviso de que el IVA se calcula al cobrar; en pago desglosa con datos del backend | «Subtotal sin IVA»; se conserva el desglose del backend |
| Consulta: cargos (`ChargesSection.jsx`) y panel (`SidePanel.jsx`) | Cargos: subtotales sin rótulo; panel: subtotal, IVA y total | «Subtotal sin IVA» en cargos; panel sin cambios |
| Cobros (`pages/billing.jsx`) y PDF de cobro | Subtotal, IVA y total; PDF con la tasa | Sin cambios; verificar que el PDF muestra la tasa |
| Agente (`get_service_catalog`, `_available_product_details` en `apps/agent/tools.py`) | Cita `base_price` / `sale_price` como «precio» | Cita el precio con IVA del backend y lo dice («$580.00, IVA incluido») |
| Configuración → Clínica | IVA invisible | «IVA aplicado a tus cobros: 16 %», de solo lectura |

**Backend:**

- Cálculo único `unit_price_with_tax(amount, tax_rate)` junto a `invoice_totals`
  (`apps/billing/money.py`), con el mismo redondeo. Inventario necesita usarlo: si su dependencia
  hacia billing no es aceptable, ambas funciones pasan a `apps/core/money.py` y billing las
  reexporta (se decide en revisión; no se duplica).
- `ServiceSerializer` y el serializer de presentaciones de inventario exponen, de solo lectura,
  `tax_rate` y `price_with_tax` / `sale_price_with_tax`, con la tasa de la organización del
  request (ya cargada en la autenticación; sin consulta extra).
- `/me/` expone `organization_tax_rate` (dato no sensible) solo para mostrar la tasa en textos.
- `apps/agent/endpoint_contracts.py` (esquemas de servicio y presentación) valida los campos
  nuevos. Un precio sin ellos es dato incompleto: el agente dice que lo cotiza el equipo, nunca da
  el precio sin IVA.

**Frontend:** un solo formateador de moneda (hoy conviven `fmtMXN`, `formatCurrency`, `fmtCur` y
`toFixed`; se elige uno existente en el PR) y un componente de presentación `PriceLabel`
(base + rótulo + total recibido) usado en las pantallas de la tabla.

**Pruebas:**

- Redondeo con tasas 0, 0.08 y 0.16 y precios con centavos.
- Serializers con los campos nuevos.
- Proyección del agente con el precio con IVA, y la falta del campo tratada como dato incompleto.
- Corpus de regresión del agente.
- Pruebas frontend de cada pantalla de la tabla: rótulo y total del backend.
- Un precio con IVA mostrado o citado coincide con el total del Checkout de un solo artículo.

**Riesgo:** con varios artículos el Checkout redondea el impuesto sobre el subtotal; la suma de
precios unitarios con IVA puede diferir en centavos. El agente no promete totales de varios
artículos y la diferencia se documenta en `billing.md`.

**Docs:** `billing.md`, `agent.md`, `frontend.md`, ADR p70.

**Esfuerzo:** M–L.

### F0.3 Zona horaria protegida (C1)

Supone D1 (a).

**Inventario de consumidores temporales** [E, 2026-11-26, búsqueda de todos los campos de fecha y
hora de los modelos]:

| Tipo | Ejemplos | Efecto de un cambio de zona |
|---|---|---|
| Hora local + instante derivado | `Appointment` (`date`, `start_time`, `end_time` ↔ `start_datetime`, `end_datetime`) | **Se desalinean**: es lo único que la política protege |
| Fechas locales puras | Ausencias (`StaffAbsence`), cierres (F2.1), próxima vacuna, revisiones, caducidad de lotes, nacimiento | Ninguno: son días del calendario de la clínica |
| Instantes reales | Pagos, cierres de consulta y caja, `due_at` del crédito, ventanas y plazos de WhatsApp, TTL del agente, auditorías | Ninguno sobre el instante; su fecha mostrada se lee con la zona nueva |
| Agregados por día local | Snapshots de analítica | Los días ya congelados no se reescriben; el día del cambio queda con frontera distinta (documentar) |
| Tareas programadas | — | **No hay recordatorios programados** en el código actual |

Si un PR posterior agrega otro par hora local / instante, F0.3 se revisa antes de aprobarlo
(regla en el ADR p70).

**Política (D1 a):**

- La zona se elige de un catálogo cerrado y se confirma en la puesta en marcha.
- Mientras la clínica no tenga citas futuras activas (`scheduled`, `confirmed`, `in_progress`),
  se cambia libremente, con confirmación.
- Con citas futuras activas, el cambio se rechaza: `409 timezone_change_blocked` con su conteo y
  la explicación.
- Los modos de recálculo («corregir»: conservar hora local; «mudanza»: conservar el instante)
  quedan definidos en el ADR y en espera (§6).

**Backend:**

- Catálogo `apps/organizations/timezones.py` con las zonas de México y su nombre para personas
  («Centro — Ciudad de México», «Sureste — Cancún», «Noroeste — Tijuana», …). Copia en
  `frontend/src/features/config/timezones.json` y prueba de contraste (patrón de
  `specialties.json`). Zona fuera del catálogo → 400.
- Servicio `change_organization_timezone(actor, organization, timezone)`
  (`apps/organizations/services.py`):
  1. bloquea la fila de la organización con `FOR UPDATE`;
  2. cuenta las citas futuras activas;
  3. si hay alguna, devuelve el 409 sin escribir nada;
  4. si no, guarda la zona y su auditoría.

  `PATCH me/` delega en él cuando cambia `timezone`.
- **Serialización con las citas.** Toda escritura que calcule el instante de una cita a partir de
  la zona debe tomar antes el `FOR SHARE` de la fila de la organización:
  - la creación ya lo hace (`appointments/creation.py` ≈L135) [E]; `mutations.py` ≈L154 es la
    edición **del agente**. *Corrección al implementar (2026-11-27):* la edición de recepción
    (`PATCH` de detalle) no lo hacía; se corrigió con la misma regla (ADR p70 D1);
  - **la atención sin cita no**: calcula el instante con la organización de la sesión, fuera de
    la transacción (`appointments/views.py` ≈L805). Se corrige para que pase por el mismo
    bloqueo y recalcule dentro de la transacción.

  Con eso, una cita creada a la vez que el cambio espera al commit y usa la zona nueva, o el
  cambio ve la cita y se bloquea.

**Frontend:**

- Selector cerrado en `ClinicSection.jsx`.
- Al elegir otra zona, confirmación con `useConfirm` («Las fechas y horas se mostrarán en …»).
  Si hay citas futuras, el mensaje del 409 con enlace a Citas.
- Tras el éxito, `refreshUser()` para que `organization_timezone` de `/me/` se actualice.
- El primer uso (`FirstRunAssistant`, paso de datos de la clínica) pide confirmar la zona junto
  con el teléfono, sin convertirla en hito.

**Migración:** ninguna de esquema. Zonas fuera del catálogo en bases de desarrollo: migración de
datos a `America/Mexico_City` (sin datos reales).

**Pruebas** (PostgreSQL):

- Sin citas futuras → cambia y audita.
- Con una cita futura activa → 409 y cero escrituras.
- Citas pasadas o terminales no bloquean.
- Zona fuera del catálogo → 400.
- Una atención sin cita y un cambio de zona concurrentes quedan serializados (entrelazado
  forzado): o la cita usa la zona nueva, o el cambio se rechaza.
- Igual con la creación normal.
- `refreshUser` actualiza la zona en la sesión (frontend).

**Docs:** ADR p70; `organizations.md` § Zona horaria; `appointments.md` (lock de la atención sin
cita); `system-reference.md` (409 nuevo).

**Riesgo:** el `FOR SHARE` de la organización en la atención sin cita cambia su orden de locks:
hoy bloquea al veterinario (≈L820). Se toma antes la organización, igual que en
`validate_creation`; verificarlo contra el orden documentado en `system-reference.md` §2.
*Hecho:* organización → veterinario en alta, registro rápido, atención sin cita y `PATCH`;
documentado en `system-reference.md` §2 y `appointments.md`. Reactivación de citas canceladas:
el PO eligió la opción c (2026-11-27) — `409 appointment_timezone_changed` si la zona de la cita
no es la vigente, con la organización tomada antes del veterinario. En el `PATCH` de detalle,
`status` pasó a solo lectura (PO, opción 1), y solo recalcula el instante si cambia la fecha o
la hora (PO, opción A) (ADR p70 D1).

**Esfuerzo:** M.

---

## 4. Fase 1 — Consolidación

### F1.1 Servicios de escritura y registro de cambios (C9)

- **Modelo:** `OrganizationConfigEvent` (`apps/organizations/models.py`), de solo inserción.
  - Campos: `organization` (PROTECT), `actor` (SET_NULL), `occurred_at`, `kind`, `changes`
    (`{campo: [antes, después]}`) y `request_id`.
  - Tipos de `kind`: `clinic_updated`, `timezone_changed`, `rules_updated`, `schedule_replaced`,
    `closure_added`, `closure_cancelled`, `service_created`, `service_updated`,
    `service_activated`, `service_deactivated`, `service_deleted`.
  - Los datos de la clínica son de la empresa, no personales; no se guardan datos de personas.
- **Absorbe `OrganizationTimezoneAudit`:** migración de datos a eventos `timezone_changed` y
  retiro del modelo (no dos formas de auditar lo mismo).
- **Servicios:**
  - `apps/organizations/services.py`: `update_clinic_profile`, `update_operating_rules`,
    `replace_schedule`, `change_organization_timezone`;
  - `apps/billing/catalog_services.py`: `create_service`, `update_service`, `delete_service`
    (billing ya depende de organizations).

  Las vistas quedan delgadas. Cada servicio registra el evento en su transacción, solo si algo
  cambió.
- **Endpoint:** `GET /api/organizations/config-history/` paginado (`organization.update`, D9).
- **Frontend:** apartado «Historial de cambios» con frases legibles (patrón de
  `features/staff/history.js`).
- **Migraciones:** crear tabla; copiar `OrganizationTimezoneAudit`; borrar ese modelo.
  `seed_demo_clinic` (≈L881) y el reset de la demo (ADR p49) limpian la tabla nueva.
- **Pruebas:**
  - un evento por guardado con cambios, ninguno sin cambios;
  - el rollback no deja eventos;
  - aislamiento entre clínicas;
  - permiso del endpoint;
  - la migración de datos;
  - gate estático de que solo los servicios escriben eventos.
- **Esfuerzo:** L.
- *Hecho (2026-11-27):* backend, migración 0018, apartado «Historial de cambios» y pruebas. El
  evento lleva además `subject` (nombre del servicio). Las vistas de servicios siguen listando
  solo los activos: la lista de inactivos llega con F1.7.

### F1.2 Navegación por dominio, rutas y «Mi cuenta» (C5, C6)

- **Estructura:** `/config/:section`, y `/config` redirige a `/config/clinic`:
  1. Clínica: identidad, contacto, zona horaria e IVA vigente de solo lectura.
  2. Horario: semana base; los cierres llegan con F2.1.
  3. Cobros: caja obligatoria, crédito y plazo.
  4. Atención: confirmación previa, atender sin registrar la mascota, expediente automático,
     historial de estados; la duración llega con F2.3.
  5. Servicios.
  6. Historial de cambios.
- **Guarda de ruta:** `pages/config.jsx` redirige a `/` sin `canAny(CONFIG_PERMS)`
  (`organization.update`, `service.create`, `service.update`, `service.destroy`), igual que
  `pages/staff.jsx`. Cada apartado se muestra según su capacidad.
- **Sin decisiones por rol:** fuera `canManage = role !== "ASSISTANT"` e `isPlatformOperator`
  por rol (`pages/config/index.jsx` ≈L66-69). El operador de plataforma se resuelve como en
  `Sidebar.jsx`, documentado como excepción.
- **Mi cuenta:** `/account` (`pages/account/index.jsx`) para todo usuario autenticado:
  - datos de solo lectura;
  - `ChangePasswordForm` en línea (oculto en la demo);
  - `MfaSettings`.

  Entradas: el bloque de usuario del menú lateral (`Sidebar.jsx` ≈L184-188) y el avatar
  (`Layout.jsx`). Se retiran el botón de la barra y el evento `open-change-password`.
- **Menú:** «Configuración» visible con `canAny(CONFIG_PERMS)`.
- **Onboarding:** `FirstRunAssistant.jsx` navega a `/config/clinic` y `/config/services`;
  `fromOnboarding` se conserva. Se actualiza `FirstRunAssistant.test.jsx`.
- **Pruebas frontend:**
  - redirección sin permisos;
  - VET llega a `/account`;
  - ASSISTANT con `organization.update` delegado edita las reglas;
  - ADMIN sin `organization.update` conserva `/account`;
  - las rutas profundas abren el apartado correcto.
- **Docs:** `frontend.md` (sección nueva «Configuración y Mi cuenta», tabla de rutas).
- **Esfuerzo:** M.
- *Hecho (2026-11-27):* rutas `clinic`, `schedule`, `billing`, `care`, `services`, `history`;
  cada apartado de reglas guarda solo las suyas; «Urgencias sin cita» deja de mostrarse (D5).

### F1.3 Estados de pantalla y guardado (C10, C12, C15, C16)

- **Carga fallida:** `EmptyState` de error con «Reintentar».
- **Cambios pendientes:** borrador por apartado frente a lo último guardado:
  - punto en el ítem del menú y aviso «Cambios sin guardar · Descartar»;
  - `useBlocker` y `beforeunload` al salir con cambios;
  - la cabecera muestra lo guardado, no el borrador.
- **Solo lo cambiado:** los `PATCH` envían únicamente los campos modificados (C16).
- **Errores en el campo:** `handleFormError` en todos los apartados; en Horario, los errores
  `day_N` se pintan en su fila.
- **Validación previa del horario:** con los mismos mensajes que el servidor.
- **Horario en pantallas angostas:** ≤880 px, un día por bloque apilado (C15).
- **Pruebas frontend** por apartado: indicador, bloqueo al salir, solo lo cambiado viaja, error
  por día, reintento.
- **Esfuerzo:** M.
- *Hecho (2026-11-27):* también se pasaron a español claro los mensajes del horario del servidor,
  con prueba de contraste contra el frontend.

### F1.4 Robustez del `PUT` de horario (C19)

- `OrganizationScheduleBulkSerializer`: validar que cada elemento sea objeto y `weekday` entero
  antes de comparar → 400, nunca 500.
- **Pruebas:** elemento de texto y `weekday` de texto. **Esfuerzo:** S.
- *Hecho (2026-11-27):* también `weekday` booleano y decimal.

### F1.5 Reglas con nombre exacto y efecto explicado (C7 parcial, C18, C20)

- **Etiquetas:**
  - «Atender sin registrar la mascota»;
  - «Al completar una cita, crear su expediente si no lo tiene»;
  - caja obligatoria y crédito, con su efecto concreto.
- **Confirmación** (`useConfirm`) al activar o desactivar caja obligatoria o crédito.
- **Estilos:** fuera los inline del plazo de crédito; se baja la línea base del trinquete en el
  mismo PR.
- **Comentario obsoleto** de `apps/appointments/views.py` (≈L396) corregido.
- **Esfuerzo:** S.
- *Hecho (2026-11-27):* el trinquete no bajó: los estilos en línea del plazo eran valores
  permitidos, así que su línea base sigue igual.

### F1.6 Retirar o conectar ajustes sin efecto (C7)

Supone D5.

- **Retirar:** `allow_emergency_walkin`, `appointment_buffer_minutes`, `week_starts_on` y
  `OrganizationSettings.locale`. Se quitan de modelo, serializer, `DEFAULT_ORG_SETTINGS`, UI y
  docs.
- **Solo lectura:** `currency_code` (MXN).
- **Conectar `display_name`:** `Organization.public_name` (comercial o, si está vacío, la legal).
  La usan:
  - el membrete de los PDFs;
  - el saludo y el contexto del agente (`prompts.py` ≈L305, L561; `tier0.py` ≈L273);
  - el encabezado del menú, con `organization_public_name` en `/me/`.

  Clínica muestra el nombre legal de solo lectura.
- **Etiquetas y campos:** «WhatsApp de la clínica (informativo)», y se agrega `address_line2`.
- **Migración:** `RemoveField` ×4. Revisar que `seed_demo_clinic` no los escriba.
- **Pruebas:** las de `test_configuration.py` sobre campos retirados se sustituyen por pruebas
  de que no se aceptan (no se borran sin reemplazo); `public_name` en PDF y agente; corpus del
  agente, con nueva versión del prompt si cambia su texto.
- **Docs:** `organizations.md` (tabla real de ajustes, incluidos `allow_post_unpaid` y
  `credit_default_days`).
- **Esfuerzo:** M.
- *Hecho (2026-11-27):* migración `organizations.0019`; los retirados dan `400` con su nombre;
  `public_name` en PDF, agente y menú. El texto del prompt no cambió (solo el valor que recibe),
  así que no hubo nueva versión; el corpus del agente pasa igual.

### F1.7 Servicios con ciclo de vida y permisos (C11, C5 parcial)

- **Formulario:** interruptor «Activo», con la explicación de lo que deja de mostrar.
- **Lista:** filtro «Mostrar inactivos» y acción Desactivar/Activar.
- **Eliminar:** un 409 por dependencias muestra el mensaje del backend y ofrece desactivar.
- **Permisos:** `can()` por acción.
- **Estilo:** etiquetas con mayúscula inicial.
- **Backend:** eventos vía `catalog_services`.
- **Pruebas frontend:** visibilidad por permiso, desactivar, 409 al eliminar.
- **Esfuerzo:** S–M.
- *Hecho (2026-11-27):* el backend sirve los inactivos con `?include_inactive=true` y el detalle
  los resuelve, para poder reactivarlos; el resto de pantallas sigue viendo solo los activos.

### F1.8 Documentación al día (C14)

- ADR p53 marcado «Implementado; ampliado por p70».
- `organizations.md`, `agent.md`, `system-module-operations.md` §1 y `system-reference.md`
  actualizados.

Se hace en cada PR; este ítem solo verifica que no quede nada pendiente. **Esfuerzo:** S.
*Hecho (2026-11-27):* ADR p53 marcado; `organizations.md`, `agent.md`, `billing.md`,
`frontend.md`, `system-module-operations.md` §1 y §10 y `system-reference.md` al día con F1.

---

## 5. Fase 2 — Operación

### F2.1 Cierres excepcionales del horario

Supone D6 (a) y amplía p53 vía p70.

- **Modelo:** `OrganizationClosure`:
  - `start_date`, `end_date` (días locales), `reason` (máximo 120), `created_by`,
    `cancelled_at`/`cancelled_by`;
  - mismas reglas que las ausencias de p67: hasta 366 días, sin terminar en el pasado,
    `409 closure_overlap`; cancelar no borra.
- **Lock:** registrar o cancelar toma `FOR UPDATE` sobre las filas de `OrganizationSchedule` de
  los días afectados. La creación del agente ya toma `FOR SHARE` sobre esa fila (`_share_rows`).
- **Consumidores:**
  - `opening_windows(organization, date)` junto a `schedule_windows` (`appointments/creation.py`);
  - el agente la usa en sus cuatro llamadas a `weekday_ranges` (`tools.py` ≈L1223, L1263, L1326;
    `operations.py` ≈L76) y en `validate_creation(require_schedule=True)` → `schedule_closed`;
  - «¿abierto ahora?» considera el cierre de hoy.
- **Staff:** se advierte, no se bloquea.
- **Endpoints:** `GET`/`POST /api/organizations/closures/` y `POST …/<uuid>/cancel/`
  (`organization.update`). Eventos `closure_added` y `closure_cancelled`.
- **Frontend:** bloque «Cierres» en Horario: lista, alta con `DateField` y cancelar con
  `useConfirm`.
- **Migración:** crear tabla; el reset de la demo la limpia.
- **Pruebas:**
  - el agente no ofrece ni agenda en un día cerrado;
  - cierre y cita del agente serializados (entrelazado forzado);
  - solape → 409;
  - cancelar reabre el día;
  - aislamiento;
  - corpus del agente.
- **Esfuerzo:** L.
- **Hecho (2026-11-27):** modelo, servicios, endpoints, consumidores del agente y bloque
  «Cierres» en Horario. Pruebas: `organizations/tests/test_closures.py` (API, agente y dos
  entrelazados forzados, validados quitando el bloqueo) y `ClosuresSection.test.jsx`. Ver la nota
  de D6 en ADR p70 para las decisiones de implementación.

### F2.2 Agenda del staff con el horario de la clínica (C8)

Supone D7 (a).

- `pages/appointments.jsx`:
  - pide `getSchedule()` (existe sin uso) y los cierres;
  - `businessHours` desde el horario;
  - `slotMinTime`/`slotMaxTime` desde la primera apertura y el último cierre, con una hora de
    margen;
  - cierres como eventos de fondo;
  - confirmación al crear o mover fuera de horario o en día cerrado.
- Sin cambios en backend.
- **Pruebas frontend:** horas visibles según el horario y aviso fuera de horario.
- **Esfuerzo:** M.
- **Hecho (2026-11-27), con un cambio decidido por el PO:** VET y ASSISTANT no podían leer el
  horario, los cierres ni los ajustes; en vez de «sin cambios en backend» se añadió la lectura
  acotada `GET /api/appointments/agenda-config/` (`appointment.list`). Ver la nota de D7 en ADR
  p70. Pruebas: `appointments/tests/test_agenda_config.py`, `agendaHours.test.js` y
  `appointments.reception.test.jsx`.
- **Añadido a pedido del PO (28-11):** los botones de hora del formulario siguen el horario del
  día y la hora inicial es la primera apertura (`hourOptions`, `defaultHour`); un clic en una
  casilla de media hora crea la cita a esa hora (`startChoices`).

### F2.3 Duración por defecto de las citas

Supone D5.

- **Atención:** «Duración habitual de una cita» (5–240 min, el rango que ya valida el backend).
- **Citas:** el formulario del staff calcula la hora de fin con ella (`appointments.jsx` ≈L636,
  L660, hoy +30 fijo) y la selección del calendario la usa como valor inicial.
- **Sin cambio:** el agente y la atención sin cita siguen en 30 minutos (documentado).
- **Esfuerzo:** S.
- **Hecho (2026-11-27):** campo en Atención (`RulesSection` `showDuration`, validación previa con
  el mensaje del servidor) y hora de fin en el alta de la agenda (`endTimeFor`, tope 23:59). La
  agenda la lee de `agenda-config` (ver F2.2).

### F2.4 Datos de la clínica en los PDFs (C13)

- `render_branded_pdf` (`apps/core/pdf/document.py`) agrega bajo el nombre público teléfono y
  dirección, si están capturados, escapados con `safe_pdf_text`.
- Sin consultas extra (las pruebas N+1 lo vigilan).
- **Pruebas:** contenido, inyección de marcado y N+1.
- **Verificar [NV]:** requisitos de la receta veterinaria en México antes de afirmar cumplimiento.
- **Esfuerzo:** S–M.
- **Hecho (2026-11-27):** `clinic_contact_line` en `apps/core/pdf/document.py`; el nombre sube
  cuando hay línea de contacto. Pruebas en `core/tests/test_pdf_clinic_contact.py` (contenido,
  marcado literal, corte con «…» y cero consultas). Los requisitos [NV] de la receta siguen sin
  verificar: ningún documento afirma cumplimiento.

---

## 6. En espera: condiciones para retomar

| Tema | Por qué espera | Condiciones obligatorias antes de planear su implementación |
|---|---|---|
| **IVA editable por la clínica** (C4, antes F1.8) | Cambia cómo se cobra; un permiso delegable no basta y un rango no es una política fiscal | (1) política fiscal validada por un contador: qué tasas, para qué clínicas y si alguna operación lleva una tasa distinta; (2) permiso dedicado y **reservado a ADMIN** (`ADMIN_RESERVED`, ADR p69), o que solo lo cambie plataforma; (3) pruebas del ciclo de vida completo que demuestren qué tasa usa cada documento: consulta abierta antes y después de su primer cargo cobrable (`MedicalRecordBillingContext`), complemento de receta, venta directa, reemplazo de una factura anulada, post, pago y PDF. Hasta que existan esas pruebas, **ninguna pantalla afirma** que los cobros abiertos conservan su tasa |
| **Recálculo de citas al cambiar de zona** (resto de C1) | Sin clínicas reales no hay citas que mover; la política de F0.3 bloquea el caso | (1) una clínica real que lo necesite; (2) elegir el modo: **corregir** (la zona estaba mal; las citas conservan fecha y hora local y se recalcula el instante) o **mudanza** (la clínica cambia de zona; las citas conservan el instante y se recalcula su hora local, lo que puede moverlas de día); (3) volver a hacer el inventario de consumidores temporales; (4) bloqueos organización → veterinarios → citas y comprobación de solapes dentro de la transacción |
| Logo en PDFs | Almacenamiento de archivos | Decisión de almacenamiento y respaldo |
| FAQ del agente en Inbox (C17) | Agente sin activar | Agente activo |
| Preparación fiscal (RFC, CFDI) | Decisión de producto mayor | Decisión sobre facturación fiscal y proveedor |
| Permisos por área de configuración | Sin uso real de la delegación de p69 | Que se delegue configuración a no-ADMIN |

---

## 7. Orden de PRs

| # | PR | Ítems | Depende de | Notas |
|---|---|---|---|---|
| 1 | ADR p70 | F0.0 | Decisiones D1–D9 | Solo documento |
| 2 | Invariante teléfono ↔ agente | F0.1 | 1 | Backend; migración de datos |
| 3 | Precio coherente con IVA | F0.2 | 1 | Backend + agente + 6 pantallas |
| 4 | Zona horaria protegida | F0.3 | 1 | Incluye el lock de la atención sin cita |
| 5 | Registro de cambios + servicios de escritura | F1.1, F1.4 | 1 | Base para los siguientes |
| 6 | Rutas, «Mi cuenta», permisos | F1.2 | — | Frontend |
| 7 | Estados de pantalla y reglas | F1.3, F1.5 | 6 | Frontend |
| 8 | Ajustes retirados y nombre público | F1.6 | 1, 5 | `RemoveField` |
| 9 | Servicios | F1.7 | 3, 5, 6 | |
| 10 | Cierres | F2.1 | 1, 5 | Agente |
| 11 | Agenda con horario + duración | F2.2, F2.3 | 8, 10 | |
| 12 | PDFs | F2.4 | 8 | |

Los PRs 2, 3, 4 y 6 pueden ir en paralelo tras el ADR. Commits y pushes solo a petición expresa
(`CLAUDE.md`).

---

## 8. Pruebas y gates

- **CI completo en cada PR:**
  - suite de backend en PostgreSQL;
  - `pnpm test` y lint;
  - trinquete de tokens (`designTokensRatchet.test.js`: si baja un conteo, se baja la línea base
    en el mismo PR);
  - `scripts/check-handle-errors.sh`;
  - gitleaks;
  - corpus de regresión del agente cuando se toca `apps/agent`.
- **Concurrencia (F0.1, F0.3, F2.1):** entrelazado forzado: detener la primera transacción y
  comprobar la espera de la segunda en `pg_stat_activity`. Una barrera sola no basta.
- **Invariantes:** cada uno tiene pruebas desde todos sus escritores enumerados y un gate estático
  para los nuevos.
- **Frontend:** cada apartado de Configuración y cada pantalla de la tabla de F0.2 tiene pruebas
  propias.
- **Migraciones:** limpias sobre desarrollo, CI y demo; correr `seed_demo_clinic` y el reset de
  la demo después de cada una.

---

## 9. Riesgos del plan

| Riesgo | Mitigación |
|---|---|
| El lock de la organización en `Organization.save()` / `AgentSettings.save()` o en la atención sin cita invierte un orden existente | Verificar contra `durable.py`, `sender.py`, `state.py`, `archive.py` y el orden de `system-reference.md` §2 antes de codificar; pruebas de entrelazado |
| Aparece otro escritor del teléfono o del interruptor del agente | Gate estático y enumeración en el ADR; un escritor nuevo debe clasificarse antes de mergear |
| Cambios en el agente rompen el corpus o la conducta | Corpus obligatorio en F0.2, F1.6 y F2.1; versión de prompt si cambia el texto |
| Diferencia de centavos entre precios unitarios con IVA y el total de varios artículos | Una sola función de cálculo; el agente no promete totales de varios artículos; documentado |
| Se agrega un par hora local / instante sin revisar la política de zona | Regla del ADR p70: revisión obligatoria de F0.3 |
| Retirar campos rompe un lector no detectado | Búsqueda de consumidores repetida en el PR; prueba de que el serializer los rechaza |

---

## 10. Fuera de este plan

Multisede, varias franjas por día, horario semanal por veterinario, recordatorios configurables,
plantillas editables, moneda o idioma configurables, CFDI, lista blanca de IP y MFA obligatorio
(auditoría §12), además de lo listado en §6.

---

## 11. Definición de terminado

- Los hallazgos C1–C20 quedan cerrados o en §6 con su condición.
- El invariante teléfono ↔ agente se cumple en todas las filas y lo respeta cada escritor
  enumerado, probado desde su lado.
- Todo precio visible dice si incluye IVA, y lo que ve el cliente coincide con lo que se cobra en
  un artículo.
- La zona horaria no puede desalinear citas futuras.
- Todo lo editable en Configuración tiene un efecto verificable y una prueba.
- Nadie entra a `/config` sin poder gestionar algo, y cualquiera llega a `/account`.
- Cada cambio de configuración deja un evento legible.
- La documentación describe el comportamiento real.
