import logging
import re
from datetime import time as dt_time, timedelta

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.core.datetime_utils import filter_by_local_day, org_now_local, org_today_local, local_date_time_to_utc, get_context_timezone
from apps.core.permissions import HybridPermission, make_permission, user_has_permission
from apps.core.sanitize import sanitize_text
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id
from apps.organizations.utils import get_org_setting, SETTING_AUTO_MEDICAL_RECORD
from apps.patients.models import Pet, SPECIES_CHOICES
from apps.users.models import User

from .models import Appointment, AppointmentStatusChange
from .serializers import AppointmentSerializer, AppointmentStatusChangeSerializer
from .services import (
    ACTIVE_STATUSES,
    NO_OVERLAP_EXCEPTIONS,
    SlotTaken,
    enforce_expected_state,
    expected_state_from_request,
    is_no_overlap_violation,
    lock_appointment,
    lock_appointment_and_veterinarians,
    lock_veterinarians,
    reject_expected_state_on_create,
    retry_on_vet_lock_race,
)

_deprecation_logger = logging.getLogger('core.deprecation')

# RFC 8594 — `DELETE /api/appointments/<id>/` queda DEPRECADO a favor de
# `PATCH /<id>/status/` (decisión §3.3). Cancela la cita y escribe
# `AppointmentStatusChange`, así que tiene que entrar al contrato de INV-A;
# pero una segunda vía de cancelación con su propia semántica es deuda, no
# funcionalidad. Sunset a +90 días del release (patrón de ADR p15 §6). La
# retirada efectiva (`410 endpoint_sunset`) es trabajo de F5, junto con el
# corte del consumidor en el frontend.
_DELETE_SUNSET_DATE = 'Fri, 06 Nov 2026 23:59:59 GMT'

# Orden de display en dashboard — constante explícita, no derivada de
# ALLOWED_TRANSITIONS (que modela reglas de negocio, no orden visual).
DASHBOARD_STATUS_ORDER = [
    "scheduled", "confirmed", "in_progress", "done", "canceled", "no_show"
]

def _raw_pk(value):
    """PK entero de un campo FK crudo del body, o `None` si no lo es.

    Se usa para tomar el lock del veterinario ANTES de que el serializer
    valide: el lock tiene que ir primero (orden global), y si el valor
    resultara inválido el serializer lo rechazará después — bloquear un pk
    inexistente es un no-op.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


ALLOWED_TRANSITIONS = {
    'scheduled':   {'confirmed', 'in_progress', 'canceled', 'no_show'},
    'confirmed':   {'in_progress', 'canceled', 'no_show'},
    'in_progress': {'done', 'canceled'},
    'done':        set(),
    'canceled':    {'scheduled'},
    'no_show':     {'scheduled'},
}


class AppointmentListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [HybridPermission]
    resource_name = "appointment"

    def get_queryset(self):
        org = self.request.user.organization
        queryset = Appointment.objects.for_organization(org).select_related('pet__owner', 'veterinarian')

        veterinarian_lookup = self.request.query_params.get('veterinarian')
        date = self.request.query_params.get('date')
        pet_lookup = self.request.query_params.get('pet')

        if veterinarian_lookup:
            # Día 6 M1: User tiene public_id (Fase 5). Resolver via
            # resolve_public_id sobre queryset filtrado por org. User no es
            # OrganizationalModel → filter manual en lugar de for_organization().
            from django.contrib.auth import get_user_model
            User = get_user_model()
            vet = resolve_public_id(
                User.objects.filter(organization=org, is_active=True),
                veterinarian_lookup,
            )
            queryset = queryset.filter(veterinarian=vet)
        if date:
            parsed = parse_date(date)
            if parsed:
                queryset = filter_by_local_day(queryset, 'start_datetime', org, parsed)
        if pet_lookup:
            # Día 6 Fase 3: resolver Pet por public_id antes del filtro (anexo seguridad)
            from apps.patients.models import Pet
            pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
            queryset = queryset.filter(pet=pet)

        return queryset.order_by('start_datetime', 'id')

    def create(self, request, *args, **kwargs):
        # A2-1: idempotencia opcional por X-Idempotency-Key. Un reintento (red
        # o doble-click) con la misma key devuelve la cita original en vez de
        # crear otra. Sin key → comportamiento actual intacto.
        from .services import get_idempotency_key, replay_appointment

        org = request.user.organization
        key = get_idempotency_key(request)
        existing = replay_appointment(org, key)
        if existing is not None:
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vet = serializer.validated_data.get('veterinarian')
        try:
            with transaction.atomic():
                # INV-D: serializar por veterinario ANTES de escribir. Sin esto,
                # dos creaciones al mismo hueco hacen deadlock comprobando la
                # exclusión y el perdedor se lleva un 500 en vez de slot_taken.
                lock_veterinarians(org.pk, getattr(vet, 'pk', None))
                serializer.save(organization=org, idempotency_key=key)
        except NO_OVERLAP_EXCEPTIONS as exc:
            # INV-D: el pre-chequeo del serializer perdió la carrera y la
            # restricción de exclusión rechazó. Mismo desenlace de negocio que
            # si lo hubiera detectado el pre-chequeo (§3.4).
            if is_no_overlap_violation(exc):
                raise SlotTaken() from exc
            # Carrera real de idempotencia: otro request con la misma key ganó
            # el INSERT. Solo aplica a IntegrityError — una ValidationError de
            # modelo no es una carrera, es un payload inválido.
            if isinstance(exc, IntegrityError):
                existing = replay_appointment(org, key)
                if existing is not None:
                    return Response(self.get_serializer(existing).data,
                                    status=status.HTTP_200_OK)
            raise
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AppointmentDetailView(PublicIdLookupMixin, TenantQueryMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [HybridPermission]
    resource_name = "appointment"
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Appointment.objects.for_organization(self.request.user.organization).select_related('pet__owner', 'veterinarian')

    def update(self, request, *args, **kwargs):
        """PATCH/PUT de detalle — INV-A + INV-D (matriz §3.3).

        La fila se toma con `select_for_update()` DENTRO de la transacción que
        escribe, y el serializer recibe esa instancia bloqueada: la comparación
        de `expected_state` queda en la misma transacción que el UPDATE. Antes
        este endpoint era último-escritor-gana sin lock alguno.
        """
        partial = kwargs.pop('partial', False)
        # get_object() resuelve public_id + tenant + permisos de objeto. La
        # lectura AUTORITATIVA es la de dentro del atomic, no ésta — ni
        # siquiera para decidir qué veterinario bloquear (ver
        # `lock_appointment_and_veterinarians`: el bug conocido de F0 era
        # justo usar `instance.veterinarian_id`, un snapshot de ESTA línea,
        # como target del lock).
        instance = self.get_object()
        org = request.user.organization
        # El veterinario NUEVO sí viene del body de ESTA request, no de una
        # lectura previa de la cita — no tiene el problema de snapshot.
        requested_vet = _raw_pk(request.data.get('veterinarian'))

        def _do():
            try:
                with transaction.atomic():
                    # ORDEN GLOBAL: veterinario(s) → cita. Con reasignación
                    # hay DOS veterinarios en juego; `lock_veterinarians` los
                    # toma por PK, así que dos PATCH cruzados (A→B y B→A) los
                    # piden en la misma secuencia y no hacen ABBA.
                    locked = lock_appointment_and_veterinarians(
                        instance, org.pk, requested_vet,
                    )
                    serializer = self.get_serializer(locked, data=request.data, partial=partial)
                    serializer.is_valid(raise_exception=True)
                    self.perform_update(serializer)
            except NO_OVERLAP_EXCEPTIONS as exc:
                if is_no_overlap_violation(exc):
                    raise SlotTaken() from exc
                raise
            return serializer

        serializer = retry_on_vet_lock_race(_do)

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """DELETE — cancela la cita. DEPRECADO a favor de `/status/` (§3.3).

        Entra al contrato de INV-A porque muta la cita y escribe auditoría:
        mientras exista, no puede ser una vía último-escritor-gana ni producir
        una segunda `AppointmentStatusChange` bajo conflicto (P1-23).
        """
        instance = self.get_object()
        expected = expected_state_from_request(request)

        def _do():
            with transaction.atomic():
                # Cancelar SACA la cita del predicado de INV-D: cambia el
                # estado activo, así que entra en la serialización por
                # veterinario igual que las que lo ocupan (orden global:
                # veterinario → cita). El veterinario a bloquear se relee
                # DENTRO de la transacción, no desde `instance` (snapshot
                # pre-atomic, ver `lock_appointment_and_veterinarians`).
                locked = lock_appointment_and_veterinarians(
                    instance, instance.organization_id,
                )
                # Bajo lock y ANTES de cualquier escritura: un 409 no deja
                # rastro (regla R1 de §5.1).
                enforce_expected_state(locked, expected)

                if locked.status not in ('scheduled', 'confirmed'):
                    return self._deprecated(Response(
                        {'error': 'Solo se pueden cancelar citas programadas o confirmadas'},
                        status=status.HTTP_400_BAD_REQUEST,
                    ), request)

                # Authoritative event lineage: la cancelación vía DELETE debe
                # quedar registrada en AppointmentStatusChange igual que la
                # cancelación vía PATCH /update-status. Sin esto las
                # cancelaciones por DELETE quedan invisibles a cualquier
                # métrica analítica derivada del audit log.
                # Ver docs/analytics-schema-audit.md §2.1.
                previous_status = locked.status
                locked.status = 'canceled'
                locked.save(update_fields=['status'])
                AppointmentStatusChange.objects.create(
                    appointment=locked,
                    from_status=previous_status,
                    to_status='canceled',
                    changed_by=request.user,
                    reason='Cancelación por DELETE /appointments/<id>/',
                    organization=locked.organization,
                )
            return self._deprecated(Response(status=status.HTTP_200_OK), request)

        return retry_on_vet_lock_race(_do)

    def _deprecated(self, response, request):
        """Cabeceras RFC 8594 + log de adopción, solo para DELETE.

        El log mide si alguien sigue llamando al endpoint: es el gate para
        cortarlo a `410` en F5, no un adorno.
        """
        # `Link` lleva la URI REAL del sucesor para ESTA cita, no una plantilla:
        # una cabecera Link (RFC 8288) con `{id}` dentro no es dereferenciable y
        # no le sirve a ningún cliente.
        successor = f"{request.path}status/"
        response['Deprecation'] = 'true'
        response['Sunset'] = _DELETE_SUNSET_DATE
        response['Link'] = f'<{successor}>; rel="successor-version"'
        _deprecation_logger.warning(
            "DEPRECATED_ENDPOINT_HIT",
            extra={
                "event": "DEPRECATED_ENDPOINT_HIT",
                "endpoint": request.path,
                "method": request.method,
                "user_id": getattr(request.user, 'pk', None),
                "org_id": getattr(request.user, 'organization_id', None),
                "successor": f"PATCH {successor}",
                "sunset": _DELETE_SUNSET_DATE,
            },
        )
        return response


@api_view(['PATCH'])
@permission_classes([make_permission("appointment.update")])
def update_status(request, pk):
    """PATCH /status/ — INV-A + INV-D (matriz §3.3).

    TODA la decisión (precondición, máquina de estados, toggles, guard de fecha)
    se toma sobre la fila BLOQUEADA, dentro del `atomic()` que escribe. Antes la
    cita se leía fuera de la transacción: dos peticiones concurrentes podían
    validar la misma transición y ambas escribir su `AppointmentStatusChange`.
    """
    if not request.user.organization:
        raise PermissionDenied("User has no organization assigned")
    appointment = resolve_public_id(
        Appointment.objects.for_organization(request.user.organization),
        pk,
    )

    new_status = request.data.get('status')
    valid_statuses = set(ALLOWED_TRANSITIONS.keys())
    if new_status not in valid_statuses:
        return Response({'error': 'Estado inválido'}, status=status.HTTP_400_BAD_REQUEST)

    expected = expected_state_from_request(request)

    from apps.core.sanitize import sanitize_text
    cancellation_reason = ''
    if new_status == 'canceled':
        cancellation_reason = sanitize_text(request.data.get('cancellation_reason') or '', max_length=100)

    def _do():
        try:
            # Atomic: el log de estado y el save van juntos; si uno falla, el otro se revierte
            with transaction.atomic():
                # ORDEN GLOBAL: veterinario → cita. Toda transición de estado
                # entra o sale del predicado de INV-D (o reescribe la entrada
                # del índice parcial al quedarse dentro), así que todas se
                # serializan por veterinario, no solo la reactivación. El
                # veterinario a bloquear se relee DENTRO de la transacción, no
                # desde `appointment` (snapshot pre-atomic tomado por
                # `resolve_public_id` antes de RBAC y de todo lo demás — ver
                # `lock_appointment_and_veterinarians`).
                locked = lock_appointment_and_veterinarians(
                    appointment, appointment.organization_id,
                )

                # INV-A primero: un conflicto no debe producir ni siquiera el 400 de
                # una transición evaluada sobre un estado que ya no es el que el
                # llamador vio.
                enforce_expected_state(locked, expected)

                from_status = locked.status
                allowed = ALLOWED_TRANSITIONS.get(from_status, set())
                if new_status not in allowed:
                    return Response(
                        {'error': f'No se puede pasar de "{from_status}" a "{new_status}"'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Toggle: require_confirmation_before_start
                # Aplica a CUALQUIER transición hacia in_progress, no solo desde scheduled
                if new_status == 'in_progress':
                    if get_org_setting(locked.organization, 'require_confirmation_before_start'):
                        if from_status != 'confirmed':
                            raise ValidationError({
                                "status": "Esta clínica requiere confirmar la cita antes de iniciarla. "
                                          "Cambia el estado a 'confirmed' primero."
                            })

                if new_status == 'scheduled' and from_status in ('canceled', 'no_show'):
                    today = org_today_local(request.user.organization)
                    if locked.date < today:
                        return Response(
                            {'error': 'La fecha original ya pasó. Crea una nueva cita.'},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    # INV-D — reactivación (§9.15, comportamiento APROBADO). Esta
                    # transición devuelve la cita al predicado de la restricción:
                    # si el hueco se reasignó mientras estaba cancelada, la base
                    # rechaza y la cita SIGUE `canceled`/`no_show`. Nada se desplaza
                    # ni se reubica automáticamente; hay que programar de nuevo.
                    # El pre-chequeo aquí solo produce el mensaje: la garantía es la
                    # restricción, que también cubre la carrera.
                    _reject_if_slot_taken(locked)

                update_fields = ['status']
                locked.status = new_status
                if new_status == 'canceled' and cancellation_reason:
                    locked.cancellation_reason = cancellation_reason
                    update_fields.append('cancellation_reason')

                # Toggle: auto_create_medical_record — debe ejecutarse ANTES de save()
                # para que el signal create_draft_invoice_on_done encuentre el MR y lo linkee.
                if new_status == 'done':
                    if get_org_setting(locked.organization, SETTING_AUTO_MEDICAL_RECORD):
                        from apps.medical_records.models import MedicalRecord
                        MedicalRecord.objects.get_or_create(
                            appointment=locked,
                            defaults={
                                'pet': locked.pet,
                                'veterinarian': locked.veterinarian,
                                'organization': locked.organization,
                                'diagnosis': '',
                                'treatment': '',
                            }
                        )

                locked.save(update_fields=update_fields)

                AppointmentStatusChange.objects.create(
                    appointment=locked,
                    from_status=from_status,
                    to_status=new_status,
                    changed_by=request.user,
                    reason=cancellation_reason,
                    organization=locked.organization,
                )
        except NO_OVERLAP_EXCEPTIONS as exc:
            if is_no_overlap_violation(exc):
                raise SlotTaken() from exc
            raise
        return Response(AppointmentSerializer(locked, context={'request': request}).data)

    return retry_on_vet_lock_race(_do)


def _reject_if_slot_taken(appointment):
    """Pre-chequeo de INV-D para una cita que vuelve a estado activo.

    Solo produce el mensaje legible: la GARANTÍA es la restricción de exclusión
    (§3.4). No existe —ni se añade— ninguna bandera de forzado.
    """
    # Mismas exclusiones que el predicado de la restricción: sin veterinario no
    # hay recurso que reservar, y las filas legacy sin instantes UTC quedan
    # fuera. Comprobarlo ANTES de construir el queryset — `__lt=None` es un
    # ValueError en Django, no un filtro vacío.
    if not (appointment.veterinarian_id
            and appointment.start_datetime and appointment.end_datetime):
        return

    conflicts = (
        Appointment.objects
        .for_organization(appointment.organization_id)
        .filter(
            veterinarian_id=appointment.veterinarian_id,
            status__in=ACTIVE_STATUSES,
            start_datetime__lt=appointment.end_datetime,
            end_datetime__gt=appointment.start_datetime,
        )
        .exclude(pk=appointment.pk)
    )
    if conflicts.exists():
        raise SlotTaken()


@api_view(['GET'])
@permission_classes([make_permission("appointment.retrieve")])
def appointment_history(request, pk):
    appointment = resolve_public_id(
        Appointment.objects.for_organization(request.user.organization),
        pk,
    )
    changes = appointment.status_changes.select_related('changed_by').all()
    return Response(AppointmentStatusChangeSerializer(changes, many=True).data)


@api_view(['PATCH'])
@permission_classes([make_permission("appointment.update")])
def assign_patient(request, pk):
    """
    Vincula una cita con paciente genérico a un paciente real.
    Solo válido cuando appointment.pet.is_generic=True.
    Propaga a MedicalRecord asociado si está abierto.
    Registra el cambio en AppointmentStatusChange.

    INV-A: entra al contrato (matriz §3.3) porque muta la cita y escribe
    auditoría — sin lock competiría con un PATCH condicionado y ganaría el
    último. Fuera de INV-D: no toca `veterinarian`, `date`, `start_time` ni
    `end_time`, así que no mueve la tupla de agenda.
    """
    # `for_organization` es método del MANAGER, no del queryset: encadenarlo
    # después de `select_related()` lanzaba AttributeError → 500 en cada
    # llamada a este endpoint. Es la regla del proyecto («jamás for_organization
    # después de select_related»), aquí en su forma literal.
    appointment = resolve_public_id(
        Appointment.objects.for_organization(request.user.organization).select_related('pet'),
        pk,
    )

    expected = expected_state_from_request(request)

    pet_id = request.data.get('pet')
    if not pet_id:
        return Response({'error': 'Se requiere pet_id.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        new_pet = Pet.objects.for_organization(request.user.organization).get(pk=pet_id)
    except Pet.DoesNotExist:
        return Response({'error': 'Mascota no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

    if new_pet.is_generic:
        return Response(
            {'error': 'No se puede vincular al paciente genérico.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        appointment = lock_appointment(appointment)
        # Bajo lock, antes de escribir nada (regla R1 de §5.1).
        enforce_expected_state(appointment, expected)

        # La comprobación del paciente genérico se re-evalúa sobre la fila
        # bloqueada: entre la lectura inicial y el lock, otro actor pudo haber
        # vinculado ya el paciente real.
        if not appointment.pet.is_generic:
            raise ValidationError(
                "Solo se puede reasignar paciente cuando la cita tiene un paciente genérico asignado."
            )

        old_pet_name = appointment.pet.name
        appointment.pet = new_pet
        appointment.save(update_fields=['pet'])

        from apps.medical_records.models import MedicalRecord
        MedicalRecord.objects.filter(
            appointment=appointment,
            organization=appointment.organization,
            status=MedicalRecord.Status.OPEN,
        ).update(pet=new_pet)

        AppointmentStatusChange.objects.create(
            appointment=appointment,
            from_status=appointment.status,
            to_status=appointment.status,
            changed_by=request.user,
            reason=f"Paciente reasignado de '{old_pet_name}' a '{new_pet.name}'",
            organization=appointment.organization,
        )

    return Response(AppointmentSerializer(appointment, context={'request': request}).data)


def _parse_require_new_owner(raw):
    """`require_new_owner` del body → bool. Ausente = `False` (opt-in).

    **Fail-closed a propósito**: un valor que no se reconoce es un `400`, nunca
    un `False` silencioso. Interpretar `"yes"` o `1` como «no exijas expediente
    nuevo» relajaría INV-B justo para el llamador que la necesita —quien no
    tiene identidad verificada— y el fallo sería invisible: la mascota quedaría
    colgada de un expediente ajeno y nadie vería un error.
    """
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    # Los formularios (multipart / form-urlencoded) no tienen tipo booleano.
    if isinstance(raw, str) and raw.strip().lower() in ('true', 'false'):
        return raw.strip().lower() == 'true'
    raise ValueError('Debe ser true o false.')


@api_view(['POST'])
@permission_classes([make_permission("appointment.create")])
def create_with_patient(request):
    """
    Crea atómicamente: owner (por el servicio único de `patients`) + pet + cita.
    Cualquier error revierte toda la transacción: no quedan registros huérfanos.

    **Resolución del expediente (INV-C, ADR p57)**. El teléfono lo resuelve
    `patients.services.resolve_owner_for_phone`, bajo el lock de deduplicación
    `(organización, teléfono normalizado)` y dentro de la MISMA transacción que
    escribe. Cuatro desenlaces, sin rama que elija:

    | Expedientes con ese teléfono | `require_new_owner` | Resultado |
    |---|---|---|
    | 0 | cualquiera | crea Owner + Pet + cita |
    | 1 | ausente / `false` | **reutiliza** el expediente y crea Pet + cita |
    | 1 | `true` | **409 `owner_exists`** con el candidato, cero escrituras |
    | ≥ 2 | cualquiera | **409 `owner_ambiguous`**, cero escrituras |

    `require_new_owner` es **INV-B aplicado** (el teléfono localiza, no
    autoriza): lo envía quien NO tiene identidad verificada —el agente— para
    que el dominio se niegue a colgar una mascota nueva de un expediente ajeno.
    Es **opt-in**: sin el flag, recepción sigue reutilizando el expediente del
    cliente que vuelve con otra mascota, que es el flujo aprobado y el que
    protege P2-14.

    `owner_ambiguous` **no** es opt-in: si el dominio no sabe cuál es el
    expediente, ningún actor puede fingir que sí.
    """
    org = request.user.organization
    if not org:
        raise PermissionDenied("User has no organization assigned")

    # Vía de creación: sin precondición de estado (matriz §3.3).
    reject_expected_state_on_create(request)

    # A2-1: replay idempotente (mismo patrón que POST /appointments/).
    from .services import get_idempotency_key, replay_appointment
    idem_key = get_idempotency_key(request)
    replay = replay_appointment(org, idem_key)
    if replay is not None:
        return Response(
            AppointmentSerializer(replay, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )

    owner_name     = request.data.get('owner_name', '').strip()
    owner_phone    = request.data.get('owner_phone', '').strip()
    pet_name       = request.data.get('pet_name', '').strip()
    pet_species    = request.data.get('pet_species', '').strip()
    pet_sex        = request.data.get('pet_sex', 'unknown')
    pet_birth_date = request.data.get('pet_birth_date') or None

    errors = {}
    if not owner_name:
        errors['owner_name'] = 'El nombre del dueño es requerido.'
    if not re.match(r'^\d{10}$', owner_phone):
        errors['owner_phone'] = 'El teléfono debe tener exactamente 10 dígitos.'
    try:
        require_new_owner = _parse_require_new_owner(request.data.get('require_new_owner'))
    except ValueError as exc:
        errors['require_new_owner'] = str(exc)
        require_new_owner = True  # irrelevante: `errors` ya aborta abajo
    if not pet_name:
        errors['pet_name'] = 'El nombre de la mascota es requerido.'
    # Especie OPCIONAL (datos mínimos): vacía => '' ("pendiente"). Si se captura,
    # debe ser válida. Consistente con el alta manual de /pets (PetSerializer).
    if pet_species and pet_species not in SPECIES_CHOICES:
        errors['pet_species'] = f'Especie inválida. Opciones: {", ".join(SPECIES_CHOICES)}'
    if not request.data.get('veterinarian'):
        errors['veterinarian'] = 'El veterinario es requerido.'
    if not request.data.get('date'):
        errors['date'] = 'La fecha es requerida.'
    if not request.data.get('start_time'):
        errors['start_time'] = 'La hora de inicio es requerida.'
    if not request.data.get('end_time'):
        errors['end_time'] = 'La hora de fin es requerida.'
    if not request.data.get('reason', '').strip():
        errors['reason'] = 'El motivo es requerido.'
    if errors:
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)

    appt_fields = {
        'veterinarian': request.data.get('veterinarian'),
        'date':         request.data.get('date'),
        'start_time':   request.data.get('start_time'),
        'end_time':     request.data.get('end_time'),
        'reason':       request.data.get('reason', '').strip(),
        'notes':        request.data.get('notes', ''),
        'status':       'scheduled',
    }

    from apps.patients.services import resolve_owner_for_phone
    try:
        with transaction.atomic():
            # INV-C (ADR p57): el expediente lo resuelve el servicio único de
            # `patients`, bajo el lock de deduplicación `(org, teléfono
            # normalizado)`. Antes esta vía usaba `get_or_create(phone=…)`: sin
            # lock, dos altas concurrentes del mismo número creaban dos
            # expedientes, y un teléfono con duplicados históricos elegía uno.
            #
            # El lock de aviso va ANTES del lock de fila del veterinario, como
            # manda el orden global (`system-reference.md` §2). No introduce un
            # ABBA: ninguna otra vía toma ambos recursos, y las que tocan el
            # veterinario no resuelven expedientes.
            owner, _outcome = resolve_owner_for_phone(
                org,
                phone=owner_phone,
                name=owner_name,
                require_new=require_new_owner,
            )
            # INV-D: serializar por veterinario antes de crear nada. Sigue
            # dentro del atomic, así que el rollback por cupo tampoco deja
            # Owner/Pet huérfanos.
            lock_veterinarians(org.pk, _raw_pk(request.data.get('veterinarian')))
            pet = Pet.objects.create(
                name=pet_name,
                species=pet_species,
                sex=pet_sex,
                birth_date=pet_birth_date,
                owner=owner,
                organization=org,
            )
            serializer = AppointmentSerializer(
                data={**appt_fields, 'pet': pet.id},
                context={'request': request},
            )
            serializer.is_valid(raise_exception=True)
            appt = serializer.save(organization=org, idempotency_key=idem_key)
    except NO_OVERLAP_EXCEPTIONS as exc:
        # INV-D: perdió la carrera del cupo. El rollback ya deshizo el
        # Owner/Pet de esta transacción — cero huérfanos, cero citas.
        if is_no_overlap_violation(exc):
            raise SlotTaken() from exc
        # Carrera: otro request con la misma key ya creó todo (rollback del
        # owner/pet de este request — sin huérfanos). Devolver la original.
        if isinstance(exc, IntegrityError):
            replay = replay_appointment(org, idem_key)
            if replay is not None:
                return Response(
                    AppointmentSerializer(replay, context={'request': request}).data,
                    status=status.HTTP_200_OK,
                )
        raise

    return Response(AppointmentSerializer(appt, context={'request': request}).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([make_permission("appointment.create")])
def walk_in(request):
    org = request.user.organization
    if not org:
        raise PermissionDenied("User has no organization assigned")

    # Vía de creación: sin precondición de estado (matriz §3.3).
    reject_expected_state_on_create(request)

    pet_id = request.data.get('pet')
    vet_id = request.data.get('veterinarian')
    reason = sanitize_text(request.data.get('reason') or '', max_length=255)
    notes = sanitize_text(request.data.get('notes') or '', max_length=5000)

    if not reason.strip():
        raise ValidationError({'reason': 'El motivo de la consulta es requerido.'})
    if not vet_id:
        raise ValidationError({'veterinarian': 'El veterinario es requerido.'})

    # Toggle: allow_anonymous_walkin
    if not pet_id:
        if not get_org_setting(org, 'allow_anonymous_walkin'):
            raise ValidationError('Walk-in anónimo no está configurado.')

        from apps.patients.utils import get_or_create_generic_patient
        _, pet = get_or_create_generic_patient(org)
    else:
        try:
            pet = Pet.objects.for_organization(org).get(pk=pet_id)
        except Pet.DoesNotExist:
            raise NotFound('Mascota no encontrada.')

    try:
        vet = User.objects.get(pk=vet_id, organization=org, is_active=True)
    except User.DoesNotExist:
        raise NotFound('Veterinario no encontrado.')

    # RBAC validation: assigned veterinarian must have granular permission to create walk-in appointments
    # Use singular 'appointment.create_walkin' (canonical permission code).
    # Prefer DB-only check when validating another user's permissions (avoid legacy role fallback)
    # Use the strict DB-only permission check for validating another user's permissions
    from apps.core.permissions import user_has_permission_strict
    if not user_has_permission_strict(vet, 'appointment.create_walkin'):
        # Keep message generic for security but clear enough for tests
        raise PermissionDenied('El veterinario asignado no tiene permiso para crear citas walk-in.')

    now_local = org_now_local(org)
    today = now_local.date()
    start_time = now_local.time().replace(second=0, microsecond=0)
    end_local = now_local + timedelta(minutes=30)
    # Walk-in cerca de medianoche: si los 30 min nominales cruzan al día
    # siguiente, end_time (00:0X) quedaría MENOR que start_time y violaría el
    # CHECK appointment_end_after_start (500), además de un end_datetime ~24h
    # antes del start. El schema es date + start/end del mismo día → se recorta
    # al fin del día; la duración es nominal, la consulta real puede continuar.
    if end_local.date() != today:
        end_time = dt_time(23, 59, 59)
    else:
        end_time = end_local.time().replace(second=0, microsecond=0)

    start_utc = local_date_time_to_utc(org, today, start_time)
    end_utc = local_date_time_to_utc(org, today, end_time)

    # INV-D SIN EXCEPCIÓN (§9.14, comportamiento APROBADO): la atención sin
    # cita también reserva al veterinario. Si tiene una cita activa solapada, la
    # restricción rechaza, NO se crea nada y recepción escoge alternativa (otro
    # veterinario u otro horario). No existe —ni se añade— bandera de forzado
    # (`force`, `allow_overlap`) ni permiso que lo salte. Sobrecupo, espera y
    # múltiples recursos son una feature separada con su propio ADR.
    try:
        with transaction.atomic():
            # Lock en la fila del vet: serializa walk-ins concurrentes del mismo
            # veterinario (ya existía) Y, desde INV-D, también contra las demás
            # vías de escritura de agenda. Ahora pasa por el helper compartido
            # para que el orden sea el mismo en todas partes.
            lock_veterinarians(org.pk, vet.pk)
            existing = Appointment.objects.filter(
                organization=org,
                veterinarian=vet,
                pet=pet,
                walk_in=True,
                created_at__gte=timezone.now() - timedelta(seconds=10),
                status='in_progress',
            ).first()
            if existing:
                serializer = AppointmentSerializer(existing, context={'request': request})
                return Response(serializer.data, status=status.HTTP_200_OK)

            appointment = Appointment.objects.create(
                organization=org,
                pet=pet,
                veterinarian=vet,
                date=today,
                start_time=start_time,
                end_time=end_time,
                start_datetime=start_utc,
                end_datetime=end_utc,
                timezone_at_creation=str(get_context_timezone(org)),
                reason=reason,
                notes=notes,
                status='in_progress',
                walk_in=True,
                created_by=request.user,
            )
    except NO_OVERLAP_EXCEPTIONS as exc:
        if is_no_overlap_violation(exc):
            raise SlotTaken() from exc
        raise

    serializer = AppointmentSerializer(appointment, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)


# ── Dashboard status-breakdown ──────────────────────────────────────────────
# Endpoint que alimenta el PieChart + Breakdown table del Dashboard v2.
# Un solo queryset con start_datetime__date__range — sin iterar días en Python.
# Agrupa en memoria. Límite de 3 items por status + flag has_more.
# status_order es constante explícita (DASHBOARD_STATUS_ORDER), no deriva
# de ALLOWED_TRANSITIONS.

STATUS_BREAKDOWN_LIMIT = 3


@api_view(['GET'])
@permission_classes([make_permission("appointment.list")])
def status_breakdown(request):
    org = request.user.organization
    if not org:
        raise PermissionDenied("User has no organization assigned")

    raw_from = request.query_params.get('from', '')
    raw_to = request.query_params.get('to', '')
    from_date = parse_date(raw_from)
    to_date = parse_date(raw_to)
    if not from_date or not to_date:
        return Response(
            {'error': 'Parámetros from y to requeridos (YYYY-MM-DD).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if from_date > to_date:
        return Response(
            {'error': 'from debe ser <= to.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Un solo queryset con range lookup. .only() mantiene la serialización
    # contenida — no acceder a campos fuera de esta lista en el loop.
    qs = (
        Appointment.objects
        .for_organization(org)
        .filter(start_datetime__date__range=(from_date, to_date))
        .select_related('pet', 'veterinarian')
        .only(
            'id', 'public_id', 'status', 'date', 'start_time', 'reason',
            'pet__name',
            'veterinarian__first_name', 'veterinarian__last_name',
        )
        .order_by('start_datetime', 'id')
    )

    by_status = {s: [] for s in DASHBOARD_STATUS_ORDER}
    totals = {s: 0 for s in DASHBOARD_STATUS_ORDER}

    for appt in qs:
        s = appt.status
        if s not in by_status:
            continue
        totals[s] += 1
        if len(by_status[s]) < STATUS_BREAKDOWN_LIMIT:
            # Serialización plana — sin objetos anidados.
            # Solo accedemos a campos incluidos en .only().
            by_status[s].append({
                'public_id': str(appt.public_id),
                'pet_name': appt.pet.name,
                'veterinarian_name': (
                    f"{appt.veterinarian.first_name or ''} "
                    f"{appt.veterinarian.last_name or ''}"
                ).strip(),
                'date': appt.date.isoformat(),
                'start_time': appt.start_time.strftime('%H:%M') if appt.start_time else '',
                'reason': appt.reason or '',
            })

    result_by_status = {}
    for s in DASHBOARD_STATUS_ORDER:
        items = by_status[s]
        total = totals[s]
        remaining = total - len(items)
        result_by_status[s] = {
            'items': items,
            'has_more': remaining > 0,
            'remaining': remaining,
        }

    return Response({
        'from': from_date.isoformat(),
        'to': to_date.isoformat(),
        'totals': totals,
        'by_status': result_by_status,
        'status_order': DASHBOARD_STATUS_ORDER,
    })
