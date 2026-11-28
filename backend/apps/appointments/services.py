from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.utils.dateparse import parse_date, parse_time
from rest_framework.exceptions import APIException, NotFound, ValidationError

from .models import Appointment, AppointmentStatusChange


# ---------------------------------------------------------------------------
# INV-A — Precondición atómica de estado (ADR p57, decisión §3.2/§3.3)
#
# `expected_state` es la tupla semántica que el llamador vio cuando decidió
# mutar la cita: {status, date, start_time}. El dominio compara esa tupla
# contra la fila REAL, bajo `select_for_update()` y dentro de la MISMA
# transacción que escribe. Si difiere → 409 `appointment_changed` con el
# estado real (`current`) y CERO escrituras (regla R1 de §5.1).
#
# Tres cosas que este módulo existe para garantizar:
#   1. La comparación no es una lectura previa: sin lock no es compare-and-swap.
#   2. La precondición es del DOMINIO, no del agente: cualquier actor que mute
#      una cita puede enviarla y recibe el mismo 409 (P0-7).
#   3. El campo va DECLARADO en el serializer. Un `expected_state` no declarado
#      lo descartaría DRF en silencio y el PATCH pasaría incondicionalmente:
#      un fail-open perfecto e invisible (P0-4).
#
# Opt-in hasta F5 (§1.2): sin `expected_state` el comportamiento es idéntico
# al actual (P2-4). En F5 pasa a obligatoria (`400 precondition_required`).
# ---------------------------------------------------------------------------

EXPECTED_STATE_KEYS = ('status', 'date', 'start_time')

EXPECTED_STATE_FIELD = 'expected_state'


class _Missing:
    """Centinela: «la clave no vino» ≠ «la clave vino con `null`».

    Sin él, `data.get('expected_state')` devuelve `None` en los dos casos y el
    dominio no puede distinguirlos: un `expected_state: null` explícito se
    trataría como ausencia y la escritura pasaría **sin precondición**. Ausencia
    es el opt-in del rollout (§1.2); `null` explícito es un llamador que CREE
    estar mandando una precondición y no la manda — el fail-open que INV-A
    existe para cerrar. Los dos no pueden compartir representación.
    """

    def __repr__(self):  # pragma: no cover - ayuda de depuración
        return '<missing>'

    def __bool__(self):
        return False


MISSING = _Missing()


class AppointmentChanged(APIException):
    """409 — la cita cambió desde que se confirmó la intención (INV-A).

    NO es un error técnico (regla R2 de §5.1): es un resultado de negocio.
    El cuerpo lleva `current` para que quien reintente lo haga informado
    (regla R3) — nunca se responde «falló» sin decir qué cambió.
    """
    status_code = 409
    default_detail = 'La cita cambió desde que se propuso.'
    default_code = 'appointment_changed'

    def __init__(self, appointment, detail=None):
        super().__init__(detail)
        # `error_payload` lo fusiona custom_exception_handler en el cuerpo.
        self.error_payload = {'current': current_state(appointment)}


def current_state(appointment):
    """La tupla semántica vigente de la cita, en el formato del contrato."""
    return {
        'status': appointment.status,
        'date': appointment.date.isoformat() if appointment.date else None,
        'start_time': (
            appointment.start_time.strftime('%H:%M') if appointment.start_time else None
        ),
    }


def parse_expected_state(raw):
    """Valida la FORMA de `expected_state` y la normaliza.

    Devuelve `{'status': str, 'date': date, 'start_time': time}`, o `None` si la
    clave **no vino** (`MISSING`). Desde la Fase 3, ese `None` ya no significa
    «adelante sin comparar»: `enforce_expected_state` lo convierte en
    `400 precondition_required`. Aquí se sigue distinguiendo de un valor mal
    formado porque el llamador merece saber cuál de las dos cosas hizo.

    `null` explícito **NO** es ausencia: es `400 validation_error`, cero
    escrituras. Quien manda `expected_state: null` cree que está mandando una
    precondición, y quien la omite no sabía que hacía falta; son dos errores
    distintos del llamador y por eso llevan `code` distinto.

    Una precondición mal formada es un error del llamador, no un conflicto:
    400 `validation_error`. Fallar aquí es deliberado — aceptar una tupla que no
    se puede comparar sería el mismo fail-open que P0-4 persigue.
    """
    if raw is MISSING:
        return None
    if raw is None:
        raise ValidationError({
            EXPECTED_STATE_FIELD: [
                'No puede ser null. Omite la clave si no quieres enviar '
                'precondición de estado.'
            ]
        })
    if not isinstance(raw, dict):
        raise ValidationError({
            EXPECTED_STATE_FIELD: [
                'Debe ser un objeto con status, date y start_time.'
            ]
        })

    unknown = sorted(set(raw) - set(EXPECTED_STATE_KEYS))
    if unknown:
        raise ValidationError({
            EXPECTED_STATE_FIELD: [
                f'Claves no reconocidas: {", ".join(unknown)}. '
                f'Solo se aceptan {", ".join(EXPECTED_STATE_KEYS)}.'
            ]
        })
    missing = [k for k in EXPECTED_STATE_KEYS if k not in raw]
    if missing:
        raise ValidationError({
            EXPECTED_STATE_FIELD: [
                f'Faltan claves: {", ".join(missing)}.'
            ]
        })

    valid_statuses = {choice for choice, _ in Appointment.STATUS_CHOICES}
    status_value = raw['status']
    if status_value not in valid_statuses:
        raise ValidationError({
            EXPECTED_STATE_FIELD: [f'Estado inválido: {status_value}.']
        })

    date_value = raw['date']
    parsed_date = parse_date(date_value) if isinstance(date_value, str) else None
    if parsed_date is None:
        raise ValidationError({
            EXPECTED_STATE_FIELD: ['`date` debe tener formato YYYY-MM-DD.']
        })

    time_value = raw['start_time']
    parsed_time = parse_time(time_value) if isinstance(time_value, str) else None
    if parsed_time is None:
        raise ValidationError({
            EXPECTED_STATE_FIELD: ['`start_time` debe tener formato HH:MM.']
        })

    return {
        'status': status_value,
        'date': parsed_date,
        'start_time': parsed_time,
    }


class PreconditionRequired(APIException):
    """400 — mutar una cita exige declarar cómo se la vio (INV-A, Fase 3).

    Hasta la Fase 3 la precondición era **opt-in**: quien la enviaba quedaba
    protegido y quien no, escribía a ciegas. Eso hacía que la garantía dependiera
    de que cada llamador se acordara — y el que se olvida nunca es el que ya
    existe, sino el que se escribe con prisa un viernes por la mañana.

    Ahora el dominio se niega. El coste es que un llamador nuevo falla en su
    primera llamada, ruidosamente, en vez de sobrescribir en silencio la
    decisión de otra persona.
    """
    status_code = 400
    default_detail = (
        'Para modificar una cita hay que declarar cómo estaba cuando se leyó '
        '(expected_state con status, date y start_time).'
    )
    default_code = 'precondition_required'


def enforce_expected_state(appointment, expected):
    """Compara la precondición contra la fila REAL. Debe correr bajo lock.

    `appointment` tiene que venir de un `select_for_update()` dentro de la
    transacción que escribe: fuera de ahí esto sería una lectura optimista,
    no una garantía (exigencia 2 de §3.2).

    Desde la Fase 3, su ausencia es `400 precondition_required` — ya no un
    no-op. La lista de exentos vive en la vista, no aquí: este helper solo
    conoce «hay precondición o no la hay».
    """
    if expected is None:
        raise PreconditionRequired()
    if not matches_expected_state(appointment, expected):
        raise AppointmentChanged(appointment)


def matches_expected_state(appointment, expected):
    """¿La fila coincide con la tupla que el usuario vio? Solo la comparación:
    quien la llama decide qué hacer si no coincide (409 en una cita sola, una
    cita omitida en una reasignación en bloque). Debe correr bajo lock."""
    return (
        appointment.status == expected['status']
        and appointment.date == expected['date']
        # Comparación al minuto: la tupla que viaja es wall-clock del usuario
        # (HH:MM), no el instante UTC. Los segundos nunca son significativos
        # en la agenda (el schema los ignora en toda la UI).
        and appointment.start_time is not None
        and appointment.start_time.replace(second=0, microsecond=0)
        == expected['start_time'].replace(second=0, microsecond=0)
    )


def expected_state_from_request(request):
    """Lee y valida `expected_state` del body de una FBV (status/assign/delete).

    El `PATCH` de detalle lo recibe DECLARADO en el serializer; las FBVs no
    pasan por él, así que leen del body con esta misma función — una sola
    definición de la forma, no dos.

    Usa `MISSING` como default del `get`: pasar `None` colapsaría «ausente» y
    «null explícito» en el mismo valor. Vale igual para un `dict` de JSON que
    para el `QueryDict` de form-data (ambos implementan `in`/`get`); en
    form-data la clave presente llega como cadena y `parse_expected_state` la
    rechaza por forma.
    """
    data = getattr(request, 'data', None)
    if not isinstance(data, dict):
        return None
    return parse_expected_state(data.get(EXPECTED_STATE_FIELD, MISSING))


def reject_expected_state_on_create(request):
    """Las vías de CREACIÓN no aceptan precondición de estado (matriz §3.3).

    No hay estado previo que comparar, así que tragarse un `expected_state` en
    silencio sería anunciar una garantía que nadie aplica — la misma familia de
    fail-open que P0-4 persigue en el serializer. `POST /appointments/` lo
    rechaza dentro del serializer; `create-with-patient` y `walk-in` arman el
    payload a mano, así que lo rechazan aquí.

    Se rechaza por **presencia de la clave**, no por su valor: `null` explícito
    también es un llamador que cree estar mandando precondición.
    """
    data = getattr(request, 'data', None)
    if isinstance(data, dict) and EXPECTED_STATE_FIELD in data:
        raise ValidationError({
            EXPECTED_STATE_FIELD: [
                'No aplica al crear una cita: no hay estado previo que comparar.'
            ]
        })


def lock_appointment(appointment):
    """Re-lee la cita con `select_for_update()`. Debe correr dentro de atomic().

    Sin `select_related`: `FOR UPDATE` sobre el lado nullable de un LEFT JOIN
    (veterinarian) es un error de PostgreSQL. Aquí solo se necesita la fila de
    la cita; las relaciones se resuelven después, ya serializando.

    Si la fila desapareció entre la resolución del `public_id` y el lock, la
    respuesta honesta es 404 — no un 500 por `DoesNotExist` sin manejar.
    """
    try:
        return (
            Appointment.objects
            .for_organization(appointment.organization_id)
            .select_for_update()
            .get(pk=appointment.pk)
        )
    except Appointment.DoesNotExist:
        raise NotFound('El recurso solicitado no existe.')


# ---------------------------------------------------------------------------
# INV-D — No-solapamiento garantizado por PostgreSQL (decisión §3.4)
#
# La disponibilidad la garantiza una restricción de exclusión sobre
# (organization, veterinarian, [start_datetime, end_datetime)) con predicado
# parcial de estados activos. El pre-chequeo del serializer SE CONSERVA: es
# quien produce el mensaje legible. Lo que cambia es que perder la carrera ya
# no significa escribir.
#
# La garantía tiene DOS piezas y hacen falta las dos:
#
#   1. La restricción de exclusión — dice la verdad sobre el cupo, siempre.
#   2. La serialización preventiva por veterinario (`lock_veterinarians`) —
#      hace que esa verdad se cobre como `slot_taken` y no como un deadlock.
#      Sin ella la restricción sigue siendo correcta, pero el perdedor de una
#      carrera puede recibir un 500 en vez de su desenlace de negocio.
#
# El error de integridad se traduce POR NOMBRE de restricción, nunca capturando
# `IntegrityError` a ciegas — capturar todo convertiría un bug en un
# `slot_taken` mentiroso. Cualquier otro IntegrityError se propaga, y el
# deadlock (40P01) también: no prueba que el hueco esté ocupado.
# ---------------------------------------------------------------------------

NO_OVERLAP_CONSTRAINT = 'appointment_no_overlap_per_vet'

ACTIVE_STATUSES = ('scheduled', 'confirmed', 'in_progress')


def future_active_appointments_count(organization_id, now):
    """Citas activas cuyo fin aún no pasa (ADR p70 D1).

    Son las que un cambio de zona horaria desalinearía: guardan su hora local y
    el instante UTC calculado con la zona vigente al crearlas. Las filas sin
    instante (legacy) se cuentan siempre, por precaución. Se usa `all_objects`,
    igual que la restricción de no-solapamiento: `is_active` no es su predicado.
    """
    from django.db.models import Q
    return Appointment.all_objects.filter(
        organization_id=organization_id, status__in=ACTIVE_STATUSES,
    ).filter(Q(end_datetime__gt=now) | Q(end_datetime__isnull=True)).count()


APPOINTMENT_TIMEZONE_CHANGED_MESSAGE = (
    'Esta cita se programó con otra zona horaria de la clínica y no se puede '
    'reactivar. Crea una cita nueva.'
)


class AppointmentTimezoneChanged(APIException):
    """409 `appointment_timezone_changed` — reactivar con otra zona (ADR p70 D1).

    Decisión del PO (2026-11-27, opción c): una cita cancelada o no presentada
    no bloquea el cambio de zona, así que puede quedar con instantes calculados
    con la zona anterior. Reactivarla los reutilizaría desalineados; se rechaza
    y la cita sigue como estaba. No se recalcula nada: el recálculo está en
    espera. Es la misma regla que el reagendado del agente (`validate_mutation`).
    """
    status_code = 409
    default_detail = APPOINTMENT_TIMEZONE_CHANGED_MESSAGE
    default_code = 'appointment_timezone_changed'


def reject_if_timezone_changed(appointment, organization):
    """Debe recibir la organización tomada con `FOR SHARE` en la misma
    transacción (`creation.share_lock_organization`): así no pierde la carrera
    contra un cambio de zona. Mismo predicado que `mutations.validate_mutation`:
    una fila sin instantes (legacy) no tiene nada que desalinear."""
    if (appointment.start_datetime is not None
            and appointment.timezone_at_creation != organization.timezone):
        raise AppointmentTimezoneChanged()


SLOT_TAKEN_MESSAGE = 'Ya existe una cita para este veterinario en ese horario'


class SlotTaken(APIException):
    """400 `slot_taken` — el hueco del veterinario está ocupado (INV-D).

    Mismo desenlace tanto si lo detecta el pre-chequeo del serializer como si
    lo rechaza la restricción de la base: el llamador no puede —ni debe—
    distinguir «ya estaba ocupado» de «lo ocuparon hace 3 ms». La acción a
    tomar es idéntica (§3.4).

    El cuerpo es un SUPERSET del 400 que este caso devolvía antes
    (`errors: {error: [...]}`), más el `code` que la convención del proyecto
    pide: ningún consumidor actual se rompe (`map_domain_400` del agente y
    `apiError` del frontend siguen encontrando el mensaje).
    """
    status_code = 400
    default_detail = SLOT_TAKEN_MESSAGE
    default_code = 'slot_taken'

    def __init__(self, detail=None):
        super().__init__(detail)
        self.error_payload = {'errors': {'error': [str(self.detail)]}}


VETERINARIAN_ABSENT_MESSAGE = (
    'Ese veterinario tiene registrada una ausencia ese día. '
    'Elige otro veterinario u otra fecha.'
)


class VeterinarianAbsent(APIException):
    """400 `veterinarian_absent` — ausencia vigente ese día (ADR p67).

    Decisión del PO: una ausencia **bloquea** crear, mover o reactivar citas de
    ese integrante en esos días, para recepción y para el agente. Si al final sí
    viene a trabajar, se cancela la ausencia. Mismo cuerpo que `slot_taken`: el
    mensaje va a `errors.error`, que la interfaz muestra como aviso.
    """
    status_code = 400
    default_detail = VETERINARIAN_ABSENT_MESSAGE
    default_code = 'veterinarian_absent'

    def __init__(self, detail=None):
        super().__init__(detail)
        self.error_payload = {'errors': {'error': [str(self.detail)]}}


def reject_if_veterinarian_absent(organization_id, veterinarian_id, day):
    """Debe correr con la fila del veterinario ya bloqueada (`lock_veterinarians`):
    registrar una ausencia bloquea esa misma fila, así que la comprobación no
    pierde la carrera contra una ausencia concurrente."""
    from apps.users.absences import is_absent
    if is_absent(organization_id, veterinarian_id, day):
        raise VeterinarianAbsent()


def is_no_overlap_violation(exc):
    """True solo si la excepción es la violación de INV-D, POR NOMBRE.

    La violación llega por DOS caminos y ambos cuentan:

      - `DjangoValidationError`, cuando `OrganizationalModel.save()` invoca
        `full_clean()` y `ExclusionConstraint.validate()` la detecta con una
        consulta previa. Es un pre-chequeo: cómodo, pero no es la garantía.
      - `IntegrityError`, cuando ese pre-chequeo pasó y la BASE rechazó. Ésta
        sí es la garantía, y es la única que cubre la carrera (P0-18).

    **El deadlock (SQLSTATE 40P01) NO entra aquí, a propósito.** Un deadlock
    dice «PostgreSQL rompió un ciclo de esperas», no «el hueco está ocupado»:
    no prueba nada sobre el cupo. Traducirlo a `slot_taken` —con o sin
    re-chequeo posterior— es afirmar algo que no se sabe: el re-chequeo puede
    correr antes de que el competidor confirme y ver el hueco libre, o después
    de que lo cancele. El deadlock se **previene** serializando por
    veterinario (ver `lock_veterinarians`); si aun así apareciera, debe salir
    como error visible para poder diagnosticarlo, no disfrazado de resultado
    de negocio.

    En ninguno de los dos casos se captura a ciegas: se compara el nombre de la
    restricción. Cualquier otra violación se propaga — convertir un bug en un
    `slot_taken` mentiroso sería peor que el 500.
    """
    if isinstance(exc, DjangoValidationError):
        return any(
            NO_OVERLAP_CONSTRAINT in str(message)
            for message in exc.messages
        )

    cause = getattr(exc, '__cause__', None)
    diag = getattr(cause, 'diag', None)
    constraint = getattr(diag, 'constraint_name', None)
    if constraint:
        return constraint == NO_OVERLAP_CONSTRAINT
    # Fallback para backends/drivers que no exponen `diag`: sigue siendo por
    # nombre de restricción, nunca «cualquier IntegrityError».
    return NO_OVERLAP_CONSTRAINT in str(exc)


# Las dos excepciones que puede levantar una escritura que viola INV-D. Los
# callers capturan esta tupla y delegan la clasificación en
# `is_no_overlap_violation`. `OperationalError` NO está: un deadlock no es un
# desenlace de negocio (ver arriba).
NO_OVERLAP_EXCEPTIONS = (IntegrityError, DjangoValidationError)


def lock_veterinarians(organization_id, *veterinarian_ids):
    """Serializa la agenda POR VETERINARIO antes de tocarla. Dentro de atomic().

    Ésta es la **prevención** del deadlock de la restricción de exclusión. Sin
    ella, dos `INSERT` simultáneos sobre el mismo hueco se esperan mutuamente
    mientras PostgreSQL comprueba la exclusión y el motor aborta a uno con
    SQLSTATE 40P01 — medido: ~1 de cada 10 corridas de la suite en paralelo.
    Con el lock tomado antes de escribir, el segundo entra cuando el primero ya
    confirmó, su pre-chequeo ve el hueco ocupado y responde `slot_taken` por la
    vía normal. La restricción sigue siendo la garantía; esto solo evita que la
    garantía se cobre en forma de avería.

    **Orden determinista por PK** (rule 2): cuando hay dos veterinarios en
    juego —un `PATCH` que reasigna la cita de un vet a otro— dos peticiones
    cruzadas (A→B y B→A) tomarían los locks en orden opuesto y volverían a
    hacer ABBA. Ordenando por PK, ambas los toman en la misma secuencia y la
    segunda simplemente espera.

    Se lockea de una en una y en orden explícito: un solo `filter(pk__in=...)`
    delega el orden de bloqueo al plan de ejecución, que no es un contrato.

    Los ids nulos se ignoran: una cita sin veterinario no reserva recurso y
    queda fuera del predicado de INV-D.
    """
    from apps.users.models import User

    for pk in sorted({pk for pk in veterinarian_ids if pk}):
        (
            User.objects
            .select_for_update()
            .filter(pk=pk, organization_id=organization_id)
            .first()
        )


# ---------------------------------------------------------------------------
# Bloqueador conocido de F0 — el veterinario a bloquear no puede venir de un
# snapshot pre-atomic (ADR p57)
#
# `PATCH` de detalle, `/status/` y `DELETE` resolvían el `Appointment` con
# `get_object()`/`resolve_public_id()` ANTES de abrir el `atomic()` que
# escribe — antes de RBAC, de instanciar el serializer, de todo lo que hace
# la vista antes de tocar la base. Luego llamaban a `lock_veterinarians` con
# el `veterinarian_id` de ESA lectura vieja. Si una reasignación concurrente
# de la MISMA cita confirmaba en esa ventana, el lock caía sobre el
# veterinario VIEJO: la escritura que seguía (aunque no tocara
# `veterinarian`, p.ej. un cambio de estado) quedaba SIN serializar contra el
# veterinario REAL — el hueco exacto por el que se cuela el deadlock de la
# restricción de exclusión (40P01) que `lock_veterinarians` existe para
# cerrar.
#
# La corrección: releer el veterinario vigente lo más cerca posible del
# lock — DENTRO de esta transacción — y verificar DESPUÉS de bloquear la
# cita (ya inmutable mientras dure el lock) que el veterinario real fue
# bloqueado. Sigue siendo una lectura optimista (el peek en sí no es la
# garantía), así que el chequeo posterior es lo que cierra el hueco: si no
# coincide, se señala con `VeterinarianLockRace` y el caller reintenta el
# intento COMPLETO desde una transacción limpia — nunca agrega el lock que
# falta sobre una cita que ya tiene el suyo, porque eso invertiría el orden
# global (veterinario(s) → cita) y dos reintentos simétricos sobre la MISMA
# cita podrían deadlockear esperándose el lock que a cada uno le falta.
# ---------------------------------------------------------------------------

class VeterinarianLockRace(Exception):
    """Señal interna: el peek de veterinario(s) perdió la carrera contra una
    reasignación concurrente de la MISMA cita, confirmada entre la lectura y
    el lock. Nunca se traduce a un resultado de negocio ni se atrapa
    silenciosamente — es una anomalía de timing, no un desenlace del
    dominio (mismo criterio que el deadlock 40P01: debe verse como error si
    persiste). El caller reintenta el intento completo con
    `retry_on_vet_lock_race`.
    """


def _peek_veterinarian_id(appointment_pk, organization_id):
    """Lectura PLANA (sin lock) del veterinario vigente de la cita.

    Deliberadamente optimista: solo decide qué locks pedir. La garantía la da
    `lock_appointment_and_veterinarians`, que verifica este valor contra la
    fila YA bloqueada.
    """
    return (
        Appointment.objects
        .filter(pk=appointment_pk, organization_id=organization_id)
        .values_list('veterinarian_id', flat=True)
        .first()
    )


def lock_appointment_and_veterinarians(appointment, organization_id, *extra_veterinarian_ids):
    """Bloquea, en el ORDEN GLOBAL correcto (veterinario(s) → cita), lo
    necesario para mutar `appointment` sin el riesgo de deadlock que
    `lock_veterinarians` existe para prevenir — sin fiarse de un
    `veterinarian_id` leído antes de esta transacción.

    `appointment` solo necesita `pk` y `organization_id` válidos: es el
    ancla de identidad (típicamente el resultado de `get_object()` /
    `resolve_public_id()` de la vista, potencialmente obsoleto). Nunca se lee
    `appointment.veterinarian_id` — el vigente se relee aquí dentro.

    `extra_veterinarian_ids` es para el veterinario NUEVO cuando la petición
    reasigna (viene del body de la request, no de una lectura previa de la
    cita, así que no tiene este problema).

    Devuelve la cita re-leída y bloqueada (`select_for_update()`), lista para
    escribir. Levanta `VeterinarianLockRace` si el veterinario real —ya
    inmutable mientras dure este lock— no quedó entre los bloqueados.
    """
    current_vet_id = _peek_veterinarian_id(appointment.pk, organization_id)
    candidates = {v for v in (current_vet_id, *extra_veterinarian_ids) if v}
    lock_veterinarians(organization_id, *candidates)

    locked = lock_appointment(appointment)

    if locked.veterinarian_id and locked.veterinarian_id not in candidates:
        raise VeterinarianLockRace(
            f'veterinarian_id cambió de {sorted(candidates)} a '
            f'{locked.veterinarian_id} entre el peek y el lock.'
        )
    return locked


MAX_VET_LOCK_ATTEMPTS = 2  # 1 intento + 1 reintento — mismo patrón que R3 (§5.6)


def retry_on_vet_lock_race(fn):
    """Reintenta `fn()` una vez si perdió la carrera de `VeterinarianLockRace`.

    `fn` debe abrir y cerrar SU PROPIA `transaction.atomic()` en cada
    llamada: un reintento tiene que partir de una transacción limpia, nunca
    de la misma con locks ya sostenidos (ver docstring de
    `VeterinarianLockRace` sobre por qué agregar un lock a medio camino sería
    peligroso).

    Al segundo fallo se deja propagar: dos peeks seguidos perdiendo la misma
    carrera es una anomalía, no un resultado de negocio — debe verse como
    error, igual que un deadlock 40P01 persistente.
    """
    last_exc = None
    for _ in range(MAX_VET_LOCK_ATTEMPTS):
        try:
            return fn()
        except VeterinarianLockRace as exc:
            last_exc = exc
            continue
    raise last_exc


# ---------------------------------------------------------------------------
# A2-1 — Idempotencia de creación de citas (ADR appointment-idempotency)
# ---------------------------------------------------------------------------

def get_idempotency_key(request):
    """Lee X-Idempotency-Key del header (opcional). Trunca a 64, o None."""
    key = (request.headers.get('X-Idempotency-Key') or '').strip()
    return key[:64] or None


def replay_appointment(organization, idempotency_key):
    """Cita ya creada con esta idempotency_key en la org (replay), o None.

    Sin key → None (crea normal). Con key → si ya existe una cita con esa
    key, es un reintento: se devuelve la original en vez de crear otra
    (patrón Payment, ADR p27)."""
    if not idempotency_key:
        return None
    return (
        Appointment.objects.for_organization(organization)
        .filter(idempotency_key=idempotency_key)
        .first()
    )


# `create_appointment(user, data)` se RETIRÓ en F0 (decisión §3.3).
#
# No tenía llamadores de producción y estaba roto de hecho (filtraba por un
# campo `datetime` que el modelo ya no tiene), pero conservaba el patrón
# `exists()` + `create()` que INV-D prohíbe: una vía read-then-write lista para
# reutilizarse por error. La creación de citas entra por
# `POST /api/appointments/` (o `create-with-patient` / `walk-in`), donde la
# restricción de exclusión es la garantía. Si alguna vez hiciera falta un
# helper, se reescribe delegando en el endpoint.


def complete_appointment_on_record_close(appointment, actor):
    """
    Finaliza la atención en agenda al cerrar la consulta médica vinculada.

    Sincroniza el ciclo de vida clínico (MedicalRecord open→closed) con el
    operativo (Appointment in_progress→done). El cierre del expediente ES el
    acto que termina la atención en una clínica veterinaria; sin esta
    sincronización la cita queda zombie en `in_progress` y la métrica
    `appointments_done` nunca refleja la consulta.

    Reglas (ver docs/system-module-operations.md §3):
      - appointment None → no-op (consulta sin cita: walk-in directo no aplica).
      - status != 'in_progress' → no-op (idempotente; respeta máquina de estados).
      - in_progress → done, registrando AppointmentStatusChange (append-only).

    NO toca Invoice ni pagos: `done` significa "la atención terminó", no
    "pagado". El cobro vive en billing (ADR p30).

    Debe invocarse DENTRO del `transaction.atomic()` del caller, que ya posee
    el lock del MedicalRecord. Usa un UPDATE condicional (no select_for_update)
    para no introducir un orden de locks Appointment↔MR que pudiera generar
    ABBA con assign_patient (que lockea Appt→MR). Appointment no está en la
    cadena canónica de locks (CashSession → MR → Invoice → Presentation →
    InvoiceItem → MRP).

    EXCLUIDA de INV-A con justificación (decisión §3.3, matriz de mutaciones):
    no es un llamador externo con una expectativa que declarar, sino una
    transición interna `in_progress → done` que YA falla cerrada — el UPDATE
    condicional no aplica si el estado cambió. Ponerle `select_for_update()`
    introduciría exactamente el orden de locks Appointment↔MedicalRecord que
    este diseño evita. Tampoco entra en INV-D: `done` sale del predicado de la
    restricción (libera el hueco), nunca lo ocupa.
    """
    if appointment is None:
        return None

    # Single source of truth de la máquina de estados (import diferido: evita
    # ciclo services↔views y mantiene una sola definición de ALLOWED_TRANSITIONS).
    from .views import ALLOWED_TRANSITIONS

    if 'done' not in ALLOWED_TRANSITIONS.get('in_progress', set()):
        # Defensa: si la máquina de estados cambia y deja de permitir la
        # transición, no forzarla.
        return appointment

    # UPDATE condicional atómico, gateado por status='in_progress'. Es:
    #   - idempotente: un segundo intento (o cita ya done/canceled) matchea 0
    #     filas → no se duplica la transición ni el AppointmentStatusChange.
    #   - libre de ABBA: no adquiere un lock explícito de fila Appointment
    #     dentro del atomic que ya posee el lock del MedicalRecord. El row lock
    #     implícito del UPDATE se libera al commit del caller.
    #   - consistente con update_status/assign_patient (UPDATE directo, sin clean()).
    updated = (
        Appointment.objects
        .for_organization(appointment.organization)
        .filter(pk=appointment.pk, status='in_progress')
        .update(status='done')
    )

    if not updated:
        # No-op: ya finalizada, cancelada, o nunca iniciada.
        return appointment

    AppointmentStatusChange.objects.create(
        appointment=appointment,
        from_status='in_progress',
        to_status='done',
        changed_by=actor,
        reason='Auto-completada al cerrar la consulta médica',
        organization=appointment.organization,
    )

    return appointment


# ---------------------------------------------------------------------------
# Lectura para Equipo (ADR p66): impacto antes de desactivar o cambiar de rol
# ---------------------------------------------------------------------------

UPCOMING_STATUSES = ('scheduled', 'confirmed')


def upcoming_for_veterinarian(organization, user, *, start_date=None, end_date=None):
    """Citas por atender (programadas o confirmadas, aún no empezadas) asignadas
    a ``user`` en ``organization``, opcionalmente entre dos fechas locales
    (incluidas). Solo lectura; la usa Equipo para avisar antes de desactivar a
    alguien, al registrar una ausencia y para reasignar (ADR p66, p67)."""
    from django.utils import timezone

    qs = Appointment.objects.for_organization(organization).filter(
        veterinarian=user,
        status__in=UPCOMING_STATUSES,
        start_datetime__gte=timezone.now(),
    )
    if start_date is not None:
        qs = qs.filter(date__gte=start_date)
    if end_date is not None:
        qs = qs.filter(date__lte=end_date)
    return qs.select_related('pet__owner').order_by('start_datetime', 'pk')


def count_upcoming_for_veterinarian(organization, user):
    """Cuántas citas devuelve ``upcoming_for_veterinarian`` sin rango."""
    return upcoming_for_veterinarian(organization, user).count()
