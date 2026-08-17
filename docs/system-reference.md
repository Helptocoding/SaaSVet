# Referencia Operacional

**Fecha**: 2026-05-29
**Estado**: vigente (refleja Sprint A completo + Sprint B + ADR p30)
**Audiencia**: nuevo desarrollador, QA, tester, soporte.

Este documento contiene la **referencia operacional** del sistema: errores
comunes con su diagnóstico, dependencias críticas que no deben romperse,
invariantes del sistema y el resumen ejecutivo del negocio.

> **Índice general**: [`docs/system-operational-flow.md`](system-operational-flow.md) — mapa de módulos y dependencias.
> **Operaciones por módulo**: [`docs/system-module-operations.md`](system-module-operations.md) — acciones con precondiciones, efectos y bloqueos.
> **Flujos completos**: [`docs/system-flows.md`](system-flows.md) — recorridos extremo a extremo.

---

## 1. Errores operativos comunes

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
| 400 al dispensar: "la receta ampara N…" | Tope clínico (ADR p37): dispensado acumulado + solicitado > recetado (en unidades base). | El mensaje trae amparado/dispensado/restante. Reducir cantidad o corregir la receta (consulta `open`). |
| 400 al agregar producto en cobro de consulta | Ítem manual de presentación en factura `consultation` (no liquidaría stock, ADR p37). | Los productos entran por insumos de la consulta o dispensando la receta; aquí solo servicios. |
| `closed_at` genera log `ANCHOR_LATE_ARRIVAL` | El cierre de consulta cayó en un bucket frozen (>T+2). | Es solo una advertencia (warn-only); revisar la latencia operativa. |
| `RBAC_DENIED` recurrente para el mismo endpoint | El frontend está usando un endpoint que el rol no tiene permitido. | Revisar `can()` antes de mostrar el CTA correspondiente. |
| `400 precondition_required` al mutar una cita | INV-A Fase 3: el llamador no envió `expected_state`. **No es un fallo del dominio: es un llamador que escribe sin declarar qué estaba viendo.** | Añadir la tupla `{status, date, start_time}` **tal como se leyó** (nunca releyendo justo antes de guardar: eso compara el estado contra sí mismo). En el frontend, `expectedStateOf(appt)`. Vale para `PATCH` detalle, `/status/`, `assign-patient` y el `DELETE` deprecado. |
| `409 appointment_changed` al mutar una cita | INV-A (ADR p57): la cita cambió entre que el llamador la leyó y quiso escribir. **No es un bug ni un 5xx.** | El cuerpo trae `current` con el estado real. Recargar y volver a decidir. **Nunca** reintentar sin `expected_state` ni con el mismo `idempotency_key` forzado. |
| `409 verification_required` al autorizar un vínculo de identidad | FLUJO-C (ADR p57 §5.5): falta una verificación **aprobada del mismo caso y candidato**. También sale si el último registro fue un **rechazo**, o si la aprobación era de un hand-off ya cerrado. | Registrar la verificación primero. La frescura está acotada por el CASO, no por reloj: si el caso se cerró y se abrió otro, hay que verificar de nuevo. |
| `409 already_linked` / `owner_changed` al autorizar | El contacto ya quedó vinculado por otra vía, o el candidato dejó de existir en esa organización. | `already_linked`: cerrar el caso, el resultado ya es el correcto. `owner_changed`: releer el caso y verificar de nuevo. |
| El botón «Autorizar vínculo» sale deshabilitado en la bandeja | No hay verificación aprobada de ESE caso, o el caso es `owner_ambiguous` (sin candidato único). | Es el contrato, no un fallo: con varios expedientes hay que ordenarlos antes — el sistema no elige (INV-C). |
| `409 release_conflict` al liberar una conversación de la bandeja | F3 (ADR p57 §5.6): el mundo cambió **dos veces** entre que el release capturó su testigo y fue a aplicarlo — otra persona reclamó, el worker tomó el turno, o apareció una suspensión nueva. | **Cero mutaciones**: ni `flow`, ni estado, ni claim, ni hand-off. El `reason` dice qué campo cambió. Recargar el caso y volver a decidir. **Nunca** reintentar en bucle: el servicio ya reintentó una vez. |
| `409 turn_in_progress` al liberar | El asistente está respondiendo justo ahora (`processing_until > now`). | Reintentar en segundos. No se pisa al worker a mitad de una respuesta al cliente. |
| Una propuesta suspendida desaparece sin evento tras ~24 h | `close_inactive_conversations(idle_hours=24)` cierra el hilo y una conversación cerrada **no se reabre**: el `flow` muere con ella. **Preexistente**, no lo introduce Item 2. | Hueco conocido y aceptado: F3 **no** añade TTL ni avisos (§9.4). Darle una razón auditable (`conversation_inactive`) es una mejora separada, aún sin implementar. |
| `AGENT_TOOL_BUSINESS_CONFLICT` en los logs del agente | **No es una avería** (ADR p57 §5.4): es un desenlace de negocio declarado por esa llamada (`appointment_changed`, `owner_exists`, `owner_ambiguous`, `slot_taken`, `past_date`). | No alertar por él. Su frecuencia SÍ es señal operativa: muchos `appointment_changed` = staff y agente operando sobre las mismas citas a la vez. La fila de `ToolExecution` conserva el `error_code`. |
| El agente responde «tu cita cambió» en vez de ejecutar | INV-A: la cita se movió entre que el cliente vio el parafraseo y confirmó. El dominio devolvió `409 appointment_changed`. | Correcto y deliberado: el cambio humano gana y el cliente se entera. **Nunca** reintentar sin `expected_state`. |
| El agente escala «necesito que alguien confirme tus datos» | INV-B: el alta pidió expediente nuevo (`require_new_owner`) y el teléfono ya tenía uno (`owner_exists`) o varios (`owner_ambiguous`). | Cero escrituras. La intención queda suspendida íntegra en `flow['suspended']` y hay un `HumanHandoff` de identidad con el `reason_detail` que distingue el caso. Se resuelve con verificación humana (FLUJO-C, F4). |
| `409 owner_ambiguous` al dar de alta un cliente, una mascota o al importar | INV-C (ADR p57): ese teléfono normalizado tiene **dos o más** expedientes en la organización. **No es un bug**: el sistema falla cerrado en vez de elegir uno. | `python manage.py audit_owner_phone_duplicates --org <id>` lista los pares con su `public_id`. Los ordena una **persona** de la clínica (`/pets`, edición de cliente). El sistema no fusiona ni ahora ni después. |
| `409 owner_exists` al dar de alta una mascota | INV-B/§4.9: el teléfono ya tiene expediente **con otro nombre**. Crear un segundo fabricaría el duplicado que INV-C obliga a tratar como ambiguo. | El cuerpo trae `candidate` (`public_id`, nombre). La UI pregunta «¿es este cliente?» y reenvía en **modo referencia** (`owner_public_id`), o corrige el teléfono. Nunca se decide por el usuario. |
| `409 owner_exists` al cambiar el teléfono de un cliente | §4.10: la clave nueva ya está ocupada; moverse ahí fabricaría un duplicado. | Cero escrituras (ni el teléfono ni, en la vía anidada de `PATCH /api/pets/`, los campos de la mascota). Corregir el número o resolver cuál es el expediente bueno. |
| Un contacto de WhatsApp deja de ser reconocido tras el deploy de F1 | INV-C (§4.11): dos expedientes que solo coinciden **tras normalizar** ahora dan `ambiguous`; antes la igualdad cruda veía uno y vinculaba a ciegas. | Conducta correcta, no regresión. `audit_owner_phone_duplicates`; en cuanto quede un solo candidato, `_rematch_owner` vincula en el mensaje siguiente. |
| El importador reporta menos filas importadas que antes | Filas que reutilizaban la primera coincidencia (`.first()`) pasan a `owner_ambiguous`. | Esperado (INV-C). El preview ya muestra el mismo desenlace que el commit, así que el conteo aprobado coincide con el real. |
| `RuntimeError: advisory_xact_lock() requiere una transacción abierta` | Alguien llamó al resolvedor de escritura fuera de un `atomic()`. | Es la guarda funcionando: en autocommit el lock se soltaría en la misma sentencia y no serializaría nada. Abrir la transacción en el llamador, que además debe cubrir toda la escritura. |
| `400 slot_taken` en una atención sin cita | INV-D (ADR p57, §9.14): el veterinario tiene una cita activa que solapa esos 30 minutos. Comportamiento **aprobado**, no regresión. | Escoger otro veterinario u otro horario. No existe bandera de forzado; sobrecupo es feature separada. |
| `400 slot_taken` al reactivar una cita cancelada | INV-D (ADR p57, §9.15): el hueco se reasignó mientras estaba cancelada. | Programar de nuevo en un hueco libre. Nada se desplaza automáticamente. |
| La migración `appointments/0014` falla al desplegar | Hay solapes históricos vivos. PostgreSQL no admite exclusiones `NOT VALID` → fail-closed deliberado. | `python manage.py audit_appointment_overlaps`, remediación **humana** por clínica, re-auditar y reintentar. Correrlo el mismo día del deploy. |
| `DEPRECATED_ENDPOINT_HIT` sobre `/api/appointments/<id>/` | Alguien sigue cancelando con `DELETE` (deprecado, ADR p57). | Migrar el llamador a `PATCH /<id>/status/`. El log es el gate para cortar a `410` en F5. |
| `500 server_error` con `deadlock detected` (SQLSTATE `40P01`) al escribir agenda | La serialización preventiva por veterinario (`lock_veterinarians`) no cubrió esa vía: alguna escritura entró o salió del predicado de INV-D sin tomar antes el lock del veterinario (ADR p57). | **Es un bug, y debe seguir siendo visible**: un deadlock no prueba que el hueco esté ocupado, así que NO se traduce a `slot_taken`. Buscar la vía que escribe sin pasar por `lock_veterinarians` y añadirla a la matriz de mutaciones. |

---

## 2. Dependencias críticas (no romper)

- `for_organization()` debe ir **siempre primero** en la cadena del queryset.
- Toda mutación de stock debe pasar por `apply_stock_movement()`, con el lock externo ya adquirido por el caller.
- Toda mutación de `InvoiceItem.quantity` debe usar `apply_invoice_item_quantity_delta()` (basado en F()).
- Los anchors (`paid_at`, `confirmed_at`, `cancelled_at`, `closed_at`) solo se escriben dentro de `services.py`.
- Los eventos financieros (`Payment`, `RefundPayment`, `RefundReversal`) solo se crean en `billing/services.py`.
- El orden global de locks es: `CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct`.
- **`User` (veterinario) precede a `Appointment`** (ADR p57). Toda escritura que pueda entrar o salir del predicado de INV-D —crear, `create-with-patient`, atención sin cita, `PATCH` de detalle, `/status/` incluida la reactivación, y `DELETE`— toma antes un `select_for_update()` sobre la fila del veterinario vía `services.lock_veterinarians`. Con dos veterinarios (reasignación) se bloquean **ambos en orden de PK**, o dos reasignaciones cruzadas harían ABBA. Sin esta serialización la restricción de exclusión sigue siendo correcta, pero dos escrituras simultáneas al mismo hueco hacen deadlock (`40P01`) y el perdedor recibe un 500 en vez de `slot_taken`.
- **`Appointment` precede a `MedicalRecord`** (ADR p57). Desde F0, cuatro endpoints lockean la fila de la cita explícitamente (`PATCH` detalle, `/status/`, `DELETE`, `assign-patient`) y dos de ellos tocan después el `MedicalRecord` vinculado. El único camino que va en sentido contrario —`complete_appointment_on_record_close`, invocado con el lock del `MedicalRecord` ya tomado— usa un **UPDATE condicional** justamente para no invertir el orden con un `select_for_update`. Ese UPDATE toma igualmente el row lock implícito de la cita, así que la ventana `assign-patient` ↔ `close_medical_record` sobre el mismo par sigue siendo la única con orden cruzado: es preexistente, estrecha (exige vincular paciente y cerrar consulta en el mismo instante) y PostgreSQL la resuelve abortando una de las dos, no corrompiendo nada. **No añadir un `select_for_update` a `complete_appointment_on_record_close`**: lo convertiría en un ABBA garantizado en vez de una carrera improbable.
- **El lock de deduplicación de teléfono se toma antes de cualquier lock de fila del alta** (ADR p57, INV-C) y se libera con el commit de la transacción del llamador. No introduce ciclo con el orden global (`CashSession → MedicalRecord → Invoice → …`) porque precede a todos. En el **cambio de teléfono** se bloquean las **dos** claves (anterior y nueva) en **orden total** por el valor normalizado: sin ese orden, dos cambios cruzados (A→B y B→A) se abortan por deadlock.
- `recalculate_totals()` solo se invoca bajo lock de la Invoice.
- `seed_permissions` se ejecuta en cada deploy (Procfile).
- El frontend usa `public_id` en URLs y deep links; los PKs solo se usan en campos FK del body y en despliegues de pantalla.
- El header `X-Idempotency-Key` debe figurar en `CORS_ALLOW_HEADERS` para que el navegador no bloquee la petición preflight.
- La extensión `btree_gist` es requisito de la restricción de no-solapamiento (`appointments/0014`): sin ella, los componentes de igualdad no son indexables por GiST y la migración no aplica.
- Una `APIException` puede llevar `error_payload` (dict) y `custom_exception_handler` lo fusiona en el cuerpo del error, junto a `{code, message}`. Es el mecanismo de `409 appointment_changed` (`current`) y `400 slot_taken` (`errors`). Nunca pisa `code`.

---

## 3. Invariantes del sistema (binding)

1. **Multitenancy**: todo acceso cross-tenant retorna 404. Cada fila tiene `organization_id`. El sistema está preparado para RLS (ADR p23).
2. **Anchors inmutables**: `paid_at`, `confirmed_at`, `cancelled_at`, `closed_at` y `closed_snapshot` no se reescriben nunca.
3. **Append-only**: los siguientes modelos son de solo inserción: `Payment`, `RefundPayment`, `RefundReversal`, `CreditNote`, `VitalSigns`, `VaccineRecord`, `ExternalPrescriptionAttestation`, `InvoiceAuditLog`, `AppointmentStatusChange`, `MetricAdjustment`, `DashboardSnapshotAudit`, `OrganizationTimezoneAudit`, `CashMovement` (ADR p39) y `ContactIdentityVerification` (FLUJO-C, ADR p57 — una decisión equivocada se corrige registrando otra; la autorización lee el último registro).
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
21. **Dispensado ≤ recetado** (ADR p37): por ítem de receta, `Σ(quantity × conversion_factor)` de las líneas dispensadas activas de la factura no excede `PrescriptionItem.quantity` (unidades base). Cubre dispensación, edición de línea (PATCH) y bloquea ítems de presentación manuales en facturas `consultation`. El cliente puede llevar menos; nunca más.
22. **INV-A — precondición atómica de estado de cita** (ADR p57): si el llamador envía `expected_state = {status, date, start_time}`, el dominio lo compara contra la fila bajo `select_for_update()` **en la misma transacción que escribe**. Al fallar: `409 appointment_changed` con `current` y **cero escrituras** (ni cita ni `AppointmentStatusChange`). Vale para **cualquier actor**, no solo el agente. **Es obligatoria desde la Fase 3**: omitirla es `400 precondition_required`. Nunca hubo opt-in de la *comparación* — solo del *envío*, y ese periodo terminó porque hacía indistinguible al llamador que no la mandaba del que sí cumplía.
22b. **INV-B — el teléfono localiza, no autoriza** (ADR p57): que un número
    coincida con un `Owner` **no** habilita escribir sobre ese expediente.
    Reutilizar un expediente existente exige identidad verificada por el
    mecanismo que corresponda al actor; quien no la tiene pide expediente nuevo
    (`require_new`) y recibe `409 owner_exists` si el número ya tiene uno. El
    alta de mascota lo aplica también al staff: asociar una mascota exige que el
    usuario **haya elegido** el expediente (modo referencia), no que el número
    coincida.

22c. **INV-C — un teléfono normalizado ⇒ como máximo un expediente por
    organización** (ADR p57): toda vía que cree un `Owner`, le asocie una `Pet`,
    mute su teléfono **o lea identidad por teléfono** pasa por el servicio único
    de `patients`, que normaliza con la función única del dominio, toma un lock
    de aviso transaccional sobre `(organización, teléfono normalizado)` y cuenta
    bajo él. Cuatro desenlaces exhaustivos: `created` / `reused` /
    `409 owner_exists` / `409 owner_ambiguous`. **No existe una rama que elija
    entre duplicados**, ni siquiera para recepción, ni siquiera en la vista
    previa del importador. Los duplicados históricos **nunca** se fusionan: se
    listan (`audit_owner_phone_duplicates`) y los ordena una persona. El
    `Owner` genérico tiene `phone_normalized = NULL` siempre — su teléfono de
    relleno no es identidad de nadie.

23. **INV-D — un veterinario no tiene dos citas activas solapadas** (ADR p57): garantizado por una restricción de exclusión de PostgreSQL sobre `(organization, veterinarian, [start_datetime, end_datetime))` con predicado de estados activos. **Sin excepciones**: cubre creación, reprogramación, atención sin cita y reactivación. El desenlace es `400 slot_taken`, lo detecte el pre-chequeo o lo rechace la base. **No existe ninguna bandera de forzado** (`force`, `allow_overlap`, permiso que lo salte).

24. **INV-E — el modelo propone la lectura; el servidor comprueba que el
    cliente lo dijo** (ADR p58, **enmendado por p59**): en la verificación de
    identidad del chat, el servidor deriva **la procedencia** —qué mensaje
    entrante *del cliente*, en *esta* conversación y dentro del TTL, contiene el
    valor— y añade **la pregunta** que abre el reto. Ninguna de las dos llega en
    los argumentos de una tool.

    p59 retiró el **régimen probatorio** (`match_mode`) y la gramática cerrada
    que decidía si el cliente «quiso decirlo»: eso es comprensión de lenguaje, no
    una decisión de autorización, y enumerar fraseos es un espacio sin fondo que
    en producción rechazó a un cliente legítimo. La frontera que queda es la que
    de verdad cerraba el bypass: **el modelo puede leer mal; no puede inventar el
    aporte.** Corolario verificado con gate estático: **`identity._promote` tiene
    exactamente un llamador**, el servicio de evidencia.

25. **INV-F — un dato que el sistema reveló no prueba identidad** (ADR p58): un
    factor solo cuenta si el cliente lo aportó **primero**. Si el sistema o el
    staff lo dijeron antes —y la bandeja le muestra el nombre del titular a
    recepción—, repetirlo es un eco, no un aporte. Por eso el nombre del titular
    dejó de ser factor: el sistema lo conoce y lo enseña. Mismo criterio que
    `ContactIdentityVerification.EVIDENCE_CHOICES` (p57 §5.5.3), que ya excluía
    toda evidencia basada en el teléfono por circular.

26. **INV-G — un saliente que el cliente no recibió no existe** (ADR p58): los
    mensajes `failed` (ventana de 24 h cerrada) y `discarded` (el cliente siguió
    escribiendo) no entran al contexto del modelo, ni al anti-eco, ni a la
    bandeja. El selector es único (`channels.selectors.visible_messages`): dos
    lecturas del mismo transcript que no coinciden es peor que una.

---

## 4. Reglas que nunca deben romperse

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
- **Jamás mutar una cita sin lock de fila** (ADR p57). Toda vía que escriba sobre un `Appointment` existente entra en la matriz de mutaciones de `docs/modules/appointments.md` **antes** de mergear. Una vía nueva sin lock reintroduce el último-escritor-gana que INV-A cierra.
- **Jamás decidir qué veterinario bloquear a partir de una lectura previa al `atomic()` que escribe** (bloqueador conocido de F0, ADR p57). `get_object()`/`resolve_public_id()` corren antes de RBAC y de instanciar el serializer; si una reasignación de la MISMA cita confirma en esa ventana, bloquear ese snapshot deja la escritura sin serializar contra el veterinario REAL — el hueco por el que se cuela el deadlock (40P01) que `lock_veterinarians` existe para prevenir. `PATCH` de detalle, `/status/` y `DELETE` usan `services.lock_appointment_and_veterinarians`, que relee el veterinario vigente DENTRO de la transacción y verifica contra la fila ya bloqueada (`VeterinarianLockRace` + `retry_on_vet_lock_race` si el peek perdió la carrera). Una vía nueva que bloquee veterinarios a mano, desde un `Appointment` resuelto antes del `atomic()`, reintroduce el mismo bug.
- Jamás borrar la declaración de `expected_state` en `AppointmentSerializer`: DRF descarta en silencio las claves desconocidas y la precondición desaparecería sin error visible (fail-open). El gate es P0-4.
- Jamás capturar `IntegrityError` a ciegas para producir `slot_taken`: se compara el **nombre** de la restricción (`appointment_no_overlap_per_vet`). Capturar todo convierte un bug en un `slot_taken` mentiroso.
- Jamás añadir una bandera de forzado del solape (`force`, `allow_overlap`, permiso que lo salte). Sobrecupo, lista de espera y múltiples recursos son una feature separada con su propio ADR.
- Jamás aplicar `appointments/0014` sin correr `audit_appointment_overlaps` y remediar a mano lo que reporte: la migración falla con solapes históricos vivos.
- **Jamás crear un `Owner`, asociarle una `Pet` ni modificar su teléfono fuera del servicio único de `patients`** (ADR p57, INV-C). `get_or_create(...phone...)` y `get_or_create(...name..., ...phone...)` quedan prohibidos como forma de resolver identidad. Y una regla de **proceso**, porque el fallo de la primera versión fue de método: una vía nueva **no** se «considera cubierta» por la fórmula «cualquier vía futura». Entra en el inventario de `docs/modules/patients.md` —usando el servicio o **excluida con evidencia**— antes de mergear; el gate `patients/tests/test_owner_phone_identity.py::InventoryStaticGateTests` enumera cada sitio que construye un `Owner` y falla si aparece uno sin clasificar.
- **Jamás resolver identidad comparando contra `Owner.phone` en crudo.** La unión es normalizado ↔ normalizado (`ContactIdentity.phone_normalized` ↔ `Owner.phone_normalized`). Comparar un valor normalizado contra la columna cruda ve **una** coincidencia donde INV-C dice **ambigua**, y de ahí sale un vínculo de identidad a un expediente elegido a ciegas. **Leer también es decidir**: `.first()` y `[:2]` como forma de elegir entre candidatos están prohibidos en todas las vías, incluida la vista previa del importador.
- **Jamás degradar el lock de deduplicación a un no-op.** `advisory_xact_lock` es PostgreSQL-only y exige transacción abierta: en otro motor lanza, y en autocommit lanza. Un lock que no bloquea es un fail-open invisible, que es la clase de bug que INV-C existe para cerrar.
- **Jamás derivar `Owner.phone_normalized` desde el cliente ni fuera de `Owner.save()`**, y jamás darle un valor al `Owner` genérico: `NULL` es la representación de «no tiene clave de cliente» (ADR p57 §4.12).
- **Jamás añadir una restricción única de teléfono por organización**: está descartada, no aplazada. Sería incompatible con INV-C (exigiría fusionar duplicados históricos) y es otra decisión, con su propia migración y su propia limpieza.
- **Jamás dejar que el modelo elija su propia prueba de identidad** (ADR p58):
  ni el mensaje que la respalda, ni la pregunta que abre el reto. Una vía nueva
  que acepte cualquiera de los dos desde los argumentos de una tool reintroduce
  el bypass que p58 cierra. La **tolerancia** del matcher salió de esta lista en
  p59: no es una decisión de autorización.
- **Jamás reponer una gramática de intención sobre el lenguaje del cliente**
  (ADR p59, con gate estático). Si un fraseo legítimo no verifica, la respuesta
  no es añadir un caso a una lista: el espacio no tiene fondo, y el fallo es
  fail-closed — deja al cliente sin poder identificarse. La barrera correcta es
  la procedencia, que es un hecho comprobable y no una interpretación.
- **Jamás añadir un segundo llamador a `identity._promote`.** Hay un gate
  estático; si falla, la respuesta no es ampliar la lista permitida sino pasar
  por el servicio de evidencia, que es quien aplica el anti-eco y satisface el
  compromiso.
- **Jamás describir `pet_name` como autenticación fuerte** (ADR p58, riesgo
  residual): es un factor de conocimiento de baja entropía, aceptado para lo que
  el agente hace hoy. Si sube la sensibilidad de lo que puede hacer, se revisa.
- **Jamás mostrar al modelo —ni a la bandeja— un saliente `failed` o
  `discarded`**: el cliente no lo recibió. El selector es
  `channels.selectors.visible_messages`, y filtrar a mano en un consumidor nuevo
  vuelve a crear dos verdades sobre el mismo transcript.

---

## 5. Resumen Ejecutivo

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
