# ADR p70 — Configuración de clínica, fase 2

**Fecha:** 2026-11-26
**Estado:** ACEPTADO (decisiones D1–D9 aprobadas por el PO el 2026-11-26; plan en
[`plan-configuracion-2026-11-26.md`](../plan-configuracion-2026-11-26.md), revisión 2;
origen en la [auditoría del módulo](../auditoria-modulo-configuracion-2026-11-26.md)).
**Enmienda a:** ADR p53. Retira cuatro ajustes de su «Fase 1», admite cierres excepcionales del
horario (p53 los dejaba fuera) y agrega un registro de cambios. Desde aquí p53 es
**Implementado; ampliado por p70**.

## Contexto

La auditoría del 2026-11-26 encontró tres problemas graves en Configuración:

1. Un cambio de zona horaria desalinea las citas existentes.
2. Se puede dejar el agente encendido sin teléfono de la clínica, el número que da en urgencias.
3. Lo que ven el personal y el cliente como precio no incluye el IVA que se cobra.

También encontró ajustes sin efecto, la cuenta personal metida dentro de la configuración de la
clínica y ningún registro de quién cambió qué.

No hay clínicas, usuarios ni datos reales, ni en producción ni en develop (`CLAUDE.md`). Las
migraciones de datos pueden normalizar directamente. Lo que protege a usuarios futuros
(invariantes, seguridad, aislamiento) se mantiene completo.

## Decisiones

### D1 — Zona horaria: se fija al empezar; con citas futuras, no se cambia

- Se elige de un **catálogo cerrado de zonas de México** con nombre para personas. Fuera del
  catálogo → 400.
- Se cambia libremente, con confirmación, **mientras no existan citas futuras activas**
  (`scheduled`, `confirmed`, `in_progress` cuyo fin no ha pasado). Si existen, el cambio se
  rechaza con `409 timezone_change_blocked` y su conteo, sin escribir nada.
- El cambio bloquea la fila de la organización antes de contar las citas. Modo `FOR NO KEY UPDATE`
  (el mismo de INV-L): excluye el `FOR SHARE` de las escrituras de cita, y a diferencia de
  `FOR UPDATE` no frena las altas de cualquier registro que solo referencie a la organización.
- **Toda operación que derive un instante a partir de la zona** debe, dentro de su transacción,
  bloquear antes la fila de la organización (`FOR SHARE`), leer la zona de esa fila bloqueada y
  solo entonces calcular. **La atención sin cita no lo hacía:** calculaba la hora antes de la
  transacción y con la organización de la sesión. Se corrige moviendo el cálculo, no solo el
  bloqueo.
- *Corrección al implementar (2026-11-27), aplicando esta misma regla:* la **edición humana**
  (`PATCH` de detalle) tampoco lo hacía. Esta decisión decía que «creación y edición ya lo
  hacen», pero `mutations.py` es la vía del agente; el `PATCH` de recepción calculaba con la
  organización de la sesión y sin bloqueo. Se corrigió igual que la atención sin cita.
- Orden de bloqueo en esas escrituras: **organización (`FOR SHARE`) → veterinario(s) → cita**,
  el de `validate_creation`. Las vistas de recepción tomaban antes el veterinario; ahora toman
  primero la organización.
- Para que la zona solo cambie por ese camino: `PATCH me/` guarda solo los campos enviados (un
  `save()` completo podía reescribir la zona de la sesión y deshacer un cambio hecho mientras
  tanto), y el alta de plataforma usa el mismo catálogo. El admin de Django queda fuera, como en
  INV-J.
- **Reactivación (decisión del PO, 2026-11-27: opción c).** Reactivar una cita
  (`canceled|no_show → scheduled`, `PATCH /status/`) reutiliza sus instantes guardados, y una
  cita cancelada no cuenta para el bloqueo. Opciones planteadas: (a) contar también las
  canceladas y no presentadas futuras; (b) recalcular los instantes al reactivar; (c) rechazar la
  reactivación si `timezone_at_creation` difiere de la zona vigente. Se eligió **(c)**: no
  recalcula nada y repite la regla del reagendado del agente. Respuesta
  `409 appointment_timezone_changed`; la cita sigue como estaba. La reactivación toma la
  organización con `FOR SHARE` antes del veterinario y compara con la zona de esa fila, así que un
  cambio de zona simultáneo la espera (y ve la cita reactivada) o ella lo espera (y se rechaza).
- **`status` de solo lectura en el `PATCH` de detalle (decisión del PO, 2026-11-27).** Se detectó
  al implementar la opción c: ese `PATCH` aceptaba `status` sin pasar por la máquina de estados ni
  dejar `AppointmentStatusChange` (previo a este ADR), y por ahí se reactivaba sin el rechazo de
  (c). Opciones: (1) solo lectura, (2) validar ahí transiciones y zona, (3) dejarlo. Se eligió
  **(1)**: el estado de una cita existente solo cambia por `PATCH /status/`. El alta sigue
  aceptando `status`.
- **El `PATCH` de detalle recalcula el instante solo si mueve la cita (decisión del PO,
  2026-11-27, opción A).** Se detectó al implementar la 1: cualquier edición recalculaba los
  instantes con la zona vigente, aunque solo cambiaran las notas, y en una cita cancelada tras un
  cambio de zona eso aplicaba el modo «corregir» y luego la reactivación pasaba. Opciones:
  (A) recalcular solo al cambiar fecha u hora; (B) no permitir editar citas canceladas, no
  presentadas o completadas; (C) dejarlo. Se eligió **(A)**. Una fila sin instantes (legacy) los
  recibe al editarla, como antes.
- Inventario de consumidores temporales (2026-11-26): solo `Appointment` guarda un par hora local
  / instante. El resto son fechas locales puras o instantes reales, y no hay recordatorios
  programados. Un cambio futuro que agregue otro par hora local / instante debe revisar esta
  decisión antes de mergearse.
- **En espera**: recalcular citas al cambiar de zona, en uno de dos modos, ambos ya definidos:
  - *corregir*: la zona estaba mal; la cita conserva fecha y hora local y se recalcula el
    instante;
  - *mudanza*: la clínica cambia de zona; la cita conserva el instante y se recalcula su hora
    local.

  Se implementa cuando una clínica real lo necesite, repitiendo el inventario.

### D2 — INV-L: agente encendido ⇒ teléfono válido, garantizado en ambos lados

**Invariante INV-L:** no existe una `AgentSettings` con `enabled=True` cuya organización no tenga
un teléfono válido según `apps.core.validators.is_valid_mx_phone`.

Reglas, en los modelos y no solo en los serializers:

1. `Organization.save()`: un teléfono no vacío debe ser válido. Cuando la escritura incluye el
   teléfono de una organización existente, abre una transacción, bloquea su fila
   (`SELECT … FOR NO KEY UPDATE`, ver abajo) y compara contra el **valor persistido**, no contra
   el de la instancia en memoria. Si el persistido es válido, el nuevo no puede ser vacío ni
   inválido.
2. `AgentSettings.save()` con `enabled=True`: abre una transacción, bloquea **primero** la fila de
   la organización y lee de ella el teléfono persistido. Si no es válido, rechaza.
3. **Mismo orden de bloqueo en las dos rutas:** la fila de la organización es la primera que se
   bloquea. Ninguna ruta bloquea `AgentSettings` y después la organización. Ambas usan el mismo
   helper, `apps.organizations.models.lock_organization_phone`, que exige una transacción
   abierta y devuelve el teléfono persistido. El modo es `FOR NO KEY UPDATE`, el que ya usa el
   worker del agente (`durable.py`, `sender.py`): excluye a las otras escrituras de la fila
   (también entre sí) sin frenar a las inserciones que solo referencian la organización por
   clave foránea, que un `FOR UPDATE` común bloquearía en todas las tablas.
4. **Sin escrituras masivas que eviten `save()`:** un gate estático falla si aparece
   `update(phone=…)` sobre `Organization` o `update(enabled=…)`/`bulk_update` sobre
   `AgentSettings`.
5. **Semillas, herramientas de evaluación y fixtures** respetan el invariante. `agent_eval` ya no
   puede crear un agente encendido antes de que la organización tenga un teléfono válido; ese
   flujo deja de existir.
6. Migración de datos: se vacían los teléfonos inválidos y se apagan los agentes cuya
   organización no tenga teléfono válido.

Por qué basta: un teléfono válido solo puede cambiar por otro válido, y encender el agente exige
uno válido leído bajo el mismo bloqueo. La única carrera posible es intentar encender leyendo un
teléfono vacío, y esa se rechaza. Las pruebas de concurrencia fuerzan ambos órdenes de escritura y
verifican el estado final en PostgreSQL.

`organizations` no importa `agent`: el lado del agente es quien lee la organización.

### D3 — IVA: visible, no editable por la clínica

La tasa se muestra de solo lectura y la sigue fijando plataforma.

Su edición por la clínica queda en espera con tres condiciones:

1. política fiscal validada por un contador;
2. permiso dedicado reservado a ADMIN (`ADMIN_RESERVED`, ADR p69), o cambio solo por plataforma;
3. pruebas del ciclo de vida completo del cobro.

Hasta entonces, ninguna pantalla afirma qué tasa conservan los cobros abiertos.

### D4 — Presentación del precio

- Los precios se siguen capturando sin IVA.
- **Personal:** todo precio unitario previo al documento se rotula «sin IVA» y, donde el backend
  lo entrega, se muestra también el total con IVA.
- **Cobros, consulta y POS en pago:** desglosan subtotal, IVA y total.
- **Cliente (agente y documentos):** precio con IVA incluido, dicho expresamente.
- El cálculo es uno solo y vive en backend, con el mismo redondeo que `invoice_totals`. React no
  calcula impuestos.
- Si falta el precio con IVA, el agente lo trata como dato incompleto («lo cotiza el equipo»),
  nunca da el precio sin IVA.

### D5 — Ajustes sin consumidor

- Se retiran `allow_emergency_walkin`, `appointment_buffer_minutes`, `week_starts_on` y
  `OrganizationSettings.locale`.
- Se conectan `default_appointment_duration_minutes` (formulario de citas del staff) y
  `display_name` (PDFs, agente y encabezado del menú, como `Organization.public_name`).
- `currency_code` queda de solo lectura (MXN).

### D6 — Cierres excepcionales

Bloquean al agente y advierten al staff.

*Implementado (2026-11-27, plan F2.1):* `OrganizationClosure` (migración `organizations.0020`),
fuente única `organizations.services.is_closed_on`, consumida por
`appointments.creation.opening_windows` (alta y reprogramación del agente → `schedule_closed`) y
`agent.clinic_context.day_ranges`/`closed_today`. Registrar o cancelar bloquea con `FOR UPDATE` las
filas del horario de esos días; el agente las toma con `FOR SHARE`. Decisiones de implementación
que no cambian D6: el motivo es obligatorio; el alta devuelve `affected_appointments` (citas por
atender esos días, que no se mueven); `GET` lista solo los vigentes que no han terminado. El
aviso al personal en la agenda es F2.2.

### D7 — Cita del staff fuera de horario

Se advierte con confirmación; no se bloquea.

*Implementado (2026-11-27, plan F2.2/F2.3):* la agenda pinta horario y cierres y confirma antes de
crear o mover fuera de ellos; la hora de fin usa `default_appointment_duration_minutes`.
**Decisión del PO durante la implementación (27-11):** el plan decía «sin cambios en backend», pero
VET y ASSISTANT no tienen `organization.retrieve` (ni `organization.update`, que exigen los
cierres), así que la agenda no podía leer esos datos. Opciones: conceder `organization.retrieve` a
esos roles, una lectura acotada para la agenda o seguir el plan literal. El PO eligió la **lectura
acotada**: `GET /api/appointments/agenda-config/` bajo `appointment.list`, con solo el horario, los
cierres vigentes (sin autor) y tres ajustes (duración, historial de estados, atención sin mascota
registrada). Corrige además el 403 que la agenda recibía y callaba al pedir los ajustes.

### D8 — Acceso

- A `/config` entra solo quien gestiona algo: `organization.update` o
  `service.create/update/destroy`. El resto redirige a `/`.
- La cuenta personal (contraseña, verificación en dos pasos) vive en `/account`, para todo
  usuario autenticado.

### D9 — Historial de cambios

`OrganizationConfigEvent`, de solo inserción, escrito por los servicios de Configuración en la
misma transacción. Lo ve quien tenga `organization.update`. Absorbe `OrganizationTimezoneAudit`.

*Implementado (2026-11-27):* servicios `update_clinic_profile`, `update_operating_rules`,
`replace_schedule`, `change_organization_timezone` y `billing.catalog_services`; escritor único
`record_config_event` con gate estático; `GET /api/organizations/config-history/`; migración
`organizations.0018`. Se añadió `subject` al evento (no estaba en el plan) para nombrar el servicio
aunque su nombre no cambie; no cambia ninguna decisión.

## Regla de implementación

Esta aprobación no autoriza a cambiar decisiones durante la implementación. Si el código
contradice este ADR o el plan aprobado, se detiene el trabajo, se documenta la evidencia y se pide
una decisión al PO.

## Consecuencias

- **Positivas:** el invariante del teléfono deja de depender de que cada pantalla lo recuerde; la
  zona horaria deja de poder desalinear citas; lo que se cotiza coincide con lo que se cobra en un
  artículo.
- **Costos:** dos modelos ganan un bloqueo al guardar (escrituras poco frecuentes); la atención
  sin cita toma un bloqueo compartido más; las fixtures que creaban agentes encendidos sin
  teléfono deben capturarlo primero.
