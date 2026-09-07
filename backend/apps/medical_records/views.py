import logging
from datetime import date

from apps.core.datetime_utils import org_today_local

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.permissions import HybridPermission, make_permission
from apps.core.sanitize import sanitize_text
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id

from .models import MedicalRecord, MedicalRecordService, VaccineRecord, VitalSigns
from .models import get_current_weight
from .policies import (
    assert_can_modify_charges,
    assert_can_modify_medical_record,
    can_close_medical_record,
    log_ownership_denied,
)
from .serializers import (
    MedicalRecordSerializer,
    MedicalRecordDetailSerializer,
    MedicalRecordServiceSerializer,
    VaccineRecordSerializer,
    VitalSignsSerializer,
)


events_logger = logging.getLogger("medical_records.events")


def _warn_if_late_closed_at(organization, closed_at):
    """
    Late-arrival observability for MedicalRecord.closed_at (ADR p17 Día 5,
    warn-only phase).

    Emits an ``ANCHOR_LATE_ARRIVAL`` warning on the ``analytics.events``
    logger when ``closed_at`` falls in a bucket already considered frozen
    for the ``clinical`` metric class. Side-effect free if the bucket is
    still in the open window.

    TEMPORAL: this helper lives in ``views.py`` because there is no
    ``medical_records/services.py::close_medical_record_service()`` yet
    (ADR p9 violation acknowledged in ADR p17 §Deuda). When that service
    exists, this helper migrates there.
    """
    from apps.analytics.services import is_bucket_frozen
    from apps.core.datetime_utils import org_today_local

    closed_date = org_today_local(organization, now=closed_at)
    if not is_bucket_frozen('clinical', closed_date, organization):
        return
    today = org_today_local(organization)
    age_days = max(0, (today - closed_date).days)
    logging.getLogger('analytics.events').warning(
        'ANCHOR_LATE_ARRIVAL',
        extra={
            'event': 'ANCHOR_LATE_ARRIVAL',
            'anchor_field': 'closed_at',
            'anchor_value_iso': closed_at.isoformat(),
            'bucket_date_local_iso': closed_date.isoformat(),
            'frozen_threshold_days': 2,
            'age_days': age_days,
            'organization_id': organization.pk,
            'writer': 'close_medical_record',
            'metric_class': 'clinical',
        },
    )


class MedicalRecordPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class MedicalRecordListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = MedicalRecordSerializer
    permission_classes = [HybridPermission]
    pagination_class = MedicalRecordPagination
    resource_name = "medicalrecord"

    def get_queryset(self):
        org = self.request.user.organization
        pet_lookup = self.request.query_params.get('pet')
        queryset = MedicalRecord.objects.for_organization(org).select_related(
            'pet', 'veterinarian', 'appointment', 'prescription'
        ).prefetch_related(
            'products_used__presentation__product',
            'services_used__service',
            'prescription__items__product__presentations',
            'vital_signs',
            'consultation_assessments', 'surgery_records', 'emergency_records',
        )

        if pet_lookup:
            # Día 6 Fase 3: resolver Pet por public_id antes del filtro
            from apps.patients.models import Pet
            pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
            queryset = queryset.filter(pet=pet)

        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization,
            veterinarian=self.request.user
        )


class MedicalRecordDetailView(PublicIdLookupMixin, TenantQueryMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MedicalRecordDetailSerializer
    permission_classes = [HybridPermission]
    resource_name = "medicalrecord"
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return MedicalRecord.objects.for_organization(self.request.user.organization).select_related(
            'pet', 'veterinarian', 'appointment', 'prescription'
        ).prefetch_related(
            'products_used__presentation__product',
            'services_used__service',
            'prescription__items__product__presentations',
            'vital_signs',
            'consultation_assessments', 'surgery_records', 'emergency_records',
        )

    def _check_not_closed(self, instance):
        if instance.status == MedicalRecord.Status.CLOSED:
            from .policies import log_closed_denied
            log_closed_denied(user=self.request.user, medical_record=instance, request=self.request)
            raise PermissionDenied("La consulta está cerrada y no puede modificarse.")

    def update(self, request, *args, **kwargs):
        self._check_not_closed(self.get_object())
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self._check_not_closed(instance)
        from apps.billing.models import Invoice
        if Invoice.objects.filter(medical_record=instance).exists():
            raise PermissionDenied("No se puede eliminar una consulta con factura asociada.")
        from .policies import medical_record_has_clinical_content
        if medical_record_has_clinical_content(instance):
            raise PermissionDenied(
                "No se puede eliminar una consulta con contenido clínico registrado. "
                "Si es un error, contacta al administrador."
            )
        events_logger.info(
            "MEDICAL_RECORD_DELETED",
            extra={
                "user_id": request.user.id,
                "organization_id": request.user.organization_id,
                "medical_record_id": instance.id,
                "public_id": str(instance.public_id),
                "endpoint": request.path,
                "method": request.method,
            },
        )
        return super().destroy(request, *args, **kwargs)


class MedicalRecordByPetView(TenantQueryMixin, generics.ListAPIView):
    serializer_class = MedicalRecordSerializer
    permission_classes = [HybridPermission]
    pagination_class = MedicalRecordPagination
    resource_name = "medicalrecord"

    def get_queryset(self):
        # Día 6 Fase 1: resolver Pet por public_id ANTES del filtro
        # (anexo seguridad — evita enumeration por PK secuencial)
        from apps.patients.models import Pet
        pet = resolve_public_id(
            Pet.objects.for_organization(self.request.user.organization),
            self.kwargs['pet_public_id'],
        )
        return MedicalRecord.objects.for_organization(
            self.request.user.organization
        ).filter(pet=pet).select_related(
            'pet', 'veterinarian', 'appointment', 'prescription'
        ).prefetch_related(
            'products_used__presentation__product',
            'services_used__service',
            'prescription__items__product__presentations',
            'vital_signs',
            'consultation_assessments', 'surgery_records', 'emergency_records',
        ).order_by('-created_at')


class MedicalRecordServiceListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = MedicalRecordServiceSerializer
    permission_classes = [HybridPermission]
    resource_name = "medicalrecord"

    def initial(self, request, *args, **kwargs):
        if request.method == 'GET':
            self.required_permission = 'medicalrecord.retrieve'
        else:
            self.required_permission = 'medicalrecord.update'
        return super().initial(request, *args, **kwargs)

    def _get_medical_record(self):
        return resolve_public_id(
            MedicalRecord.objects.for_organization(self.request.user.organization),
            self.kwargs['medical_record_pk'],
        )

    def get_queryset(self):
        mr = self._get_medical_record()
        return MedicalRecordService.objects.filter(
            medical_record=mr
        ).select_related('service')

    def perform_create(self, serializer):
        import uuid
        from apps.billing.checkout_services import record_clinical_charge_delta

        with transaction.atomic():
            mr = resolve_public_id(
                MedicalRecord.objects.for_organization(self.request.user.organization).select_for_update(),
                self.kwargs['medical_record_pk'],
            )
            assert_can_modify_charges(self.request.user, mr, self.request)
            service = serializer.validated_data['service']
            quantity = serializer.validated_data['quantity']
            if service.organization_id != self.request.user.organization_id:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({'service': 'Servicio fuera de tu organización'})

            existing = MedicalRecordService.all_objects.select_for_update().filter(
                medical_record=mr, service=service,
            ).first()
            if existing is None:
                source = serializer.save(medical_record=mr)
            else:
                existing.quantity += quantity
                existing.updated_by = self.request.user
                existing.save(update_fields=['quantity', 'updated_by', 'updated_at'])
                serializer.instance = existing
                source = existing
            mutation_key = (
                self.request.headers.get('X-Idempotency-Key')
                or f'mrs:{source.pk}:{uuid.uuid4()}'
            )
            record_clinical_charge_delta(
                source, delta=quantity, user=self.request.user,
                mutation_key=mutation_key, reason='service_recorded',
            )


class MedicalRecordServiceDeleteView(generics.DestroyAPIView):
    permission_classes = [HybridPermission]
    resource_name = "medicalrecord"
    required_permission = 'medicalrecord.update'

    def get_object(self):
        mr = resolve_public_id(
            MedicalRecord.objects.for_organization(self.request.user.organization),
            self.kwargs['medical_record_pk'],
        )
        return get_object_or_404(
            MedicalRecordService,
            pk=self.kwargs['pk'],
            medical_record=mr,
        )

    def perform_destroy(self, instance):
        import uuid
        from apps.billing.checkout_services import record_clinical_charge_delta

        with transaction.atomic():
            mr = resolve_public_id(
                MedicalRecord.objects.for_organization(self.request.user.organization).select_for_update(),
                self.kwargs['medical_record_pk'],
            )
            assert_can_modify_charges(self.request.user, mr, self.request)
            fresh_instance = MedicalRecordService.objects.select_for_update().get(
                pk=instance.pk,
                medical_record=mr,
            )
            record_clinical_charge_delta(
                fresh_instance, delta=-fresh_instance.quantity,
                user=self.request.user,
                mutation_key=f'mrs-delete:{fresh_instance.pk}:{uuid.uuid4()}',
                reason='service_removed',
            )
            fresh_instance.delete()


class VitalSignsListCreateView(generics.ListCreateAPIView):
    serializer_class = VitalSignsSerializer
    permission_classes = [HybridPermission]
    pagination_class = MedicalRecordPagination
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'vitals'

    def initial(self, request, *args, **kwargs):
        # HybridPermission infiere "retrieve" cuando hay "pk" en kwargs — evitar
        if request.method == 'GET':
            self.required_permission = 'medicalrecord.vitals.list'
        else:
            self.required_permission = 'medicalrecord.vitals.create'
        return super().initial(request, *args, **kwargs)

    def _get_medical_record(self):
        return resolve_public_id(
            MedicalRecord.objects.for_organization(self.request.user.organization),
            self.kwargs['pk'],
        )

    def get_queryset(self):
        mr = self._get_medical_record()
        return (
            VitalSigns.objects
            .for_organization(self.request.user.organization)
            .filter(medical_record=mr)
            .order_by('-recorded_at', '-created_at')
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['pet'] = self._get_medical_record().pet
        return ctx

    def perform_create(self, serializer):
        mr = self._get_medical_record()
        assert_can_modify_medical_record(self.request.user, mr, self.request)
        serializer.save(
            medical_record=mr,
            organization=mr.organization,
            recorded_by=self.request.user,
        )
        events_logger.info(
            "VITAL_SIGNS_CREATED",
            extra={
                "user_id": self.request.user.id,
                "organization_id": self.request.user.organization_id,
                "medical_record_id": mr.id,
            },
        )


class MedicalRecordSummaryView(generics.GenericAPIView):
    permission_classes = [make_permission("medicalrecord.summary.retrieve")]

    def get(self, request, pk):
        mr = resolve_public_id(
            MedicalRecord.objects
                .for_organization(request.user.organization)
                .select_related('pet__owner', 'appointment')
                .prefetch_related('vital_signs'),
            pk,
        )

        last_vital = mr.vital_signs.order_by('-recorded_at', '-created_at').first()
        weight = get_current_weight(mr)

        invoice = None
        if mr.invoice_id:
            from apps.billing.models import Invoice
            invoice = (
                Invoice.objects
                .filter(pk=mr.invoice_id)
                .only('status', 'subtotal', 'tax_amount', 'total')
                .first()
            )
        checkout = None
        if invoice is None:
            from apps.billing.models import Checkout
            checkout = Checkout.objects.for_organization(request.user.organization).filter(
                medical_record=mr, kind='primary_consultation',
            ).only('lifecycle', 'subtotal', 'tax_amount', 'total').first()

        next_vaccine = (
            VaccineRecord.objects
            .for_organization(request.user.organization)
            .filter(pet=mr.pet,
                    next_due_date__gte=org_today_local(
                        request.user.organization))
            .order_by('next_due_date')
            .first()
        )

        data = {
            "patient": {
                "name": mr.pet.name,
                "species": mr.pet.species,
                "breed": mr.pet.breed,
                "birth_date": mr.pet.birth_date,
            },
            "last_vitals": {
                "weight": weight,
                "temperature": last_vital.temperature if last_vital else None,
                "heart_rate": last_vital.heart_rate if last_vital else None,
                "respiratory_rate": last_vital.respiratory_rate if last_vital else None,
                "recorded_at": last_vital.recorded_at if last_vital else None,
                "has_vitals": last_vital is not None,
            },
            "diagnosis": mr.diagnosis,
            "consultation_type": mr.consultation_type,
            "status": mr.status,
            "totals": {
                "subtotal": (invoice or checkout).subtotal,
                "tax_amount": (invoice or checkout).tax_amount,
                "total": (invoice or checkout).total,
                "status": invoice.status if invoice else f"checkout_{checkout.lifecycle}",
            } if (invoice or checkout) else None,
            "next_vaccine_date": next_vaccine.next_due_date if next_vaccine else None,
        }
        return Response(data)


@api_view(['POST'])
@permission_classes([make_permission("medicalrecord.close")])
def close_medical_record(request, pk):
    with transaction.atomic():
        # El cierre es un comando durable. La clave estable por actor mantiene
        # compatibilidad con clientes anteriores al header y, a la vez, evita
        # repetir materialización clínica/comercial ante retries de red.
        from apps.billing.checkout_services import _claim_receipt, _complete_receipt
        idempotency_key = (
            request.headers.get('X-Idempotency-Key')
            or request.data.get('idempotency_key')
            or f'close:{pk}:actor:{request.user.pk}'
        )
        receipt, replay = _claim_receipt(
            organization=request.user.organization,
            user=request.user,
            command_kind='close_medical_record',
            idempotency_key=idempotency_key,
            payload={'medical_record': str(pk)},
            aggregate_type='medical_record',
            aggregate_public_id=str(pk),
        )
        medical_record = resolve_public_id(
            MedicalRecord.objects.select_for_update().filter(
                organization=request.user.organization,
            ),
            pk,
        )

        if replay:
            return Response(MedicalRecordDetailSerializer(
                medical_record, context={"request": request},
            ).data)

        # Idempotencia PRIMERO: una consulta ya cerrada retorna 200 sin re-validar
        # ni re-checar ownership. can_close_medical_record() devuelve False para
        # registros CLOSED (refleja "acción disponible" para el botón del Timeline),
        # así que checarlo antes bloqueaba el cierre idempotente con 403. El queryset
        # ya está scopeado a la organización y el permiso `medicalrecord.close` lo
        # gatea permission_classes → el no-op idempotente es seguro (mismo-tenant,
        # con permiso, sobre datos que ese usuario ya puede leer con un GET).
        if medical_record.status == MedicalRecord.Status.CLOSED:
            events_logger.info(
                "MEDICAL_RECORD_CLOSE_IDEMPOTENT",
                extra={
                    "user_id": request.user.id,
                    "organization_id": request.user.organization_id,
                    "medical_record_id": medical_record.id,
                    "endpoint": request.path,
                    "method": request.method,
                },
            )
            _complete_receipt(
                receipt,
                medical_record_id=medical_record.pk,
                medical_record_public_id=str(medical_record.public_id),
                result='already_closed',
            )
            return Response(MedicalRecordDetailSerializer(medical_record, context={"request": request}).data)

        if not can_close_medical_record(request.user, medical_record):
            log_ownership_denied(user=request.user, medical_record=medical_record, request=request)
            raise PermissionDenied("No puedes finalizar esta consulta")

        # Validación de campos requeridos para cierre. El diagnóstico es obligatorio
        # salvo en Urgencia (diagnóstico presuntivo permitido — el protocolo captura
        # triage/ABC/egreso; diseño A3). Delegación al protocolo activo.
        diagnosis = sanitize_text(medical_record.diagnosis or '', max_length=400)
        if (medical_record.consultation_type != MedicalRecord.ConsultationType.EMERGENCY
                and not diagnosis.strip()):
            events_logger.warning(
                "MEDICAL_RECORD_CLOSE_VALIDATION_FAILED",
                extra={
                    "record_id": str(medical_record.public_id),
                    "field": "diagnosis",
                    "user_id": request.user.id,
                    "organization_id": request.user.organization_id,
                },
            )
            raise ValidationError({"diagnosis": "El diagnóstico es obligatorio."})

        # El tratamiento del MedicalRecord no es obligatorio para protocolos que
        # capturan su plan en su propio registro: Vacuna (VaccineRecord) y
        # Cirugía (SurgeryRecord.postop_instructions). Delegación de validación al
        # protocolo activo (diseño A3).
        _treatment_exempt = {
            MedicalRecord.ConsultationType.VACCINE,
            MedicalRecord.ConsultationType.SURGERY,
            MedicalRecord.ConsultationType.EMERGENCY,
        }
        if medical_record.consultation_type not in _treatment_exempt:
            treatment = sanitize_text(medical_record.treatment or '', max_length=400)
            if not treatment.strip():
                events_logger.warning(
                    "MEDICAL_RECORD_CLOSE_VALIDATION_FAILED",
                    extra={
                        "record_id": str(medical_record.public_id),
                        "field": "treatment",
                        "user_id": request.user.id,
                        "organization_id": request.user.organization_id,
                    },
                )
                raise ValidationError({"treatment": "El tratamiento es obligatorio."})

        medical_record.status = MedicalRecord.Status.CLOSED
        medical_record.closed_at = timezone.now()
        medical_record.closed_at_source = 'service'
        medical_record.closed_by = request.user
        medical_record.save(update_fields=[
            'status', 'closed_at', 'closed_at_source', 'closed_by',
        ])

        # Sincroniza la agenda: cerrar la consulta finaliza la cita vinculada
        # (in_progress→done). Cross-domain vía service (no mutar Appointment
        # directamente desde medical_records). No-op si no hay cita o si la
        # cita no está en in_progress. NO toca Invoice/pagos.
        from apps.appointments.services import complete_appointment_on_record_close
        complete_appointment_on_record_close(medical_record.appointment, request.user)

        # Protocolos clínicos (ADR p50): materializa los registros de dominio
        # capturados en el scratchpad consultation_draft (hoy solo Vacuna →
        # VaccineRecord), dentro del MISMO atomic. Finalizar es una sola operación:
        # o se cierra la consulta Y se crea el registro legal, o nada. El frontend
        # NO hace un POST aparte. Un protocolo NUNCA muta MedicalRecord (principio
        # binding). Draft inválido → ValidationError → rollback del cierre.
        from .services import apply_consultation_draft_on_close
        apply_consultation_draft_on_close(medical_record, request)

        # El cierre crea la preparación comercial, nunca una Invoice draft.
        # Se ejecuta después de materializar protocolos para que cualquier
        # insumo clínico generado por ellos quede incluido en el snapshot.
        from apps.billing.checkout_services import get_or_create_primary_checkout_for_medical_record
        get_or_create_primary_checkout_for_medical_record(medical_record, owner=request.user)

        # Late-arrival observability (ADR p17 Día 5, warn-only).
        # Call lives inside the active transaction so the log only emits
        # if commit succeeds (a rollback unwinds before the helper runs).
        _warn_if_late_closed_at(medical_record.organization, medical_record.closed_at)

        events_logger.info(
            "MEDICAL_RECORD_CLOSED",
            extra={
                "user_id": request.user.id,
                "organization_id": request.user.organization_id,
                "medical_record_id": medical_record.id,
                "endpoint": request.path,
                "method": request.method,
            },
        )
        _complete_receipt(
            receipt,
            medical_record_id=medical_record.pk,
            medical_record_public_id=str(medical_record.public_id),
            result='closed',
        )
        return Response(MedicalRecordDetailSerializer(medical_record, context={"request": request}).data)


class VaccineRecordListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = VaccineRecordSerializer
    permission_classes = [HybridPermission]
    resource_name = "vaccinerecord"

    def get_queryset(self):
        org = self.request.user.organization
        qs = VaccineRecord.objects.for_organization(org).select_related(
            'pet', 'applied_by', 'medical_record'
        )
        pet_lookup = self.request.query_params.get('pet')
        if pet_lookup:
            # Día 6 Fase 3: resolver Pet por public_id antes del filtro
            from apps.patients.models import Pet
            pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
            qs = qs.filter(pet=pet)
        return qs

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization,
            applied_by=self.request.user,
        )


class VaccineRecordDetailView(PublicIdLookupMixin, TenantQueryMixin, generics.RetrieveUpdateAPIView):
    """PR-4B / ADR p16: DELETE removido por consistencia con la motivación
    NOM-007/NOM-046 que justificó VaccineRecord.pet PROTECT. Permitir borrar
    el registro vacunal directamente contradice "vacuna es documento legal
    retenido 5 años". Para anular un registro creado por error, usar PATCH
    (campo notes / status) — soft-delete real es deuda A5 (Fase 2).

    Día 6 Fase 5: lookup ahora por public_id (UUID) — antes <int:pk> exponía
    enumeration cross-org via probe 404 vs 200."""
    serializer_class = VaccineRecordSerializer
    permission_classes = [HybridPermission]
    resource_name = "vaccinerecord"
    lookup_url_kwarg = 'pk'
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        return VaccineRecord.objects.for_organization(
            self.request.user.organization
        ).select_related('pet', 'applied_by', 'medical_record')


_MR_STATUS_LABEL = dict(MedicalRecord.Status.choices)
_MR_TYPE_LABEL = dict(MedicalRecord.ConsultationType.choices)


@api_view(['GET'])
@permission_classes([make_permission("medicalrecord.retrieve")])
def medical_record_pdf(request, pk):
    """Genera el resumen clínico del registro como archivo PDF."""
    from io import BytesIO

    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph

    from django.http import HttpResponse

    from apps.core.datetime_utils import utc_to_local
    from apps.core.pdf import (
        CONTENT_WIDTH, build_styles, data_table, get_theme_for_organization,
        info_card, numbered_item, pdf_filename, render_branded_pdf,
        safe_pdf_text, section, title_block,
    )

    record = resolve_public_id(
        MedicalRecord.objects
            .for_organization(request.user.organization)
            .select_related('pet__owner', 'veterinarian', 'appointment', 'organization')
            .prefetch_related(
                'vital_signs',
                'services_used__service',
                'products_used__presentation__product',
                'prescription__items__product',
                'consultation_assessments', 'surgery_records', 'emergency_records',
            ),
        pk,
    )
    assessment = next(iter(record.consultation_assessments.all()), None)

    org = record.organization
    theme = get_theme_for_organization(org)
    st = build_styles(theme)

    def fmt_dt(value):
        local = utc_to_local(org, value)
        return local.strftime('%d/%m/%Y %H:%M') if local else ''

    meta_lines = [
        f"Estado: <b>{_MR_STATUS_LABEL.get(record.status, record.status)}</b> "
        f"&nbsp;·&nbsp; Tipo: {_MR_TYPE_LABEL.get(record.consultation_type, record.consultation_type)}",
        f"Fecha: {fmt_dt(record.created_at)}",
    ]
    if record.closed_at:
        meta_lines.append(f"Cerrada: {fmt_dt(record.closed_at)}")

    flow = []
    flow += title_block(st, title=f"Consulta #{record.id}", meta_lines=meta_lines)

    if record.veterinarian_id:
        vet = record.veterinarian
        vet_name = f"{vet.first_name} {vet.last_name}".strip() or vet.username
        spec = f" &nbsp;·&nbsp; {safe_pdf_text(vet.specialty)}" if getattr(vet, 'specialty', '') else ""
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{safe_pdf_text(vet_name)}{spec}", st['body']))

    pet = record.pet
    flow += section(st, theme, "Paciente")
    patient_pairs = [
        ("Nombre", safe_pdf_text(pet.name)),
        ("Especie", safe_pdf_text(pet.species)),
        ("Raza", safe_pdf_text(pet.breed or '')),
    ]
    if pet.owner_id:
        patient_pairs += [
            ("Dueño", safe_pdf_text(pet.owner.name)),
            ("Teléfono", safe_pdf_text(pet.owner.phone)),
        ]
    flow += info_card(st, theme, patient_pairs, columns=3)

    # Motivo (SOAP·S): motivo principal del assessment; fallback al motivo de la cita.
    motivo = (assessment.chief_complaint if assessment else '') or (
        record.appointment.reason
        if record.appointment_id and getattr(record.appointment, 'reason', '') else ''
    )
    if motivo:
        flow += section(st, theme, "Motivo de consulta")
        flow.append(Paragraph(safe_pdf_text(motivo), st['body']))

    if assessment and assessment.history:
        flow += section(st, theme, "Historia clínica")
        flow.append(Paragraph(
            safe_pdf_text(assessment.history).replace('\n', '<br/>'), st['body'],
        ))

    last_vital = None
    for v in record.vital_signs.all():
        if last_vital is None or (v.recorded_at and v.recorded_at > last_vital.recorded_at):
            last_vital = v
    vital_pairs = []
    if last_vital:
        if last_vital.weight is not None:
            vital_pairs.append(("Peso", f"{last_vital.weight} kg"))
        if last_vital.temperature is not None:
            vital_pairs.append(("Temperatura", f"{last_vital.temperature} °C"))
        if last_vital.heart_rate is not None:
            vital_pairs.append(("Frec. cardiaca", f"{last_vital.heart_rate} lpm"))
        if last_vital.respiratory_rate is not None:
            vital_pairs.append(("Frec. respiratoria", f"{last_vital.respiratory_rate} rpm"))
    elif record.weight is not None:
        vital_pairs.append(("Peso", f"{record.weight} kg"))
    if vital_pairs:
        flow += section(st, theme, "Signos vitales")
        flow += info_card(st, theme, vital_pairs, columns=4)

    # Exploración física por sistemas (SOAP·O). Contrato del campo `exam`:
    #   {"<sistema>": {"status": "normal"|"altered", "finding": "<texto>"}}
    # Solo se imprimen los sistemas alterados o con hallazgo (los normales no
    # aportan al documento). Defensivo: `exam` puede venir vacío o con otra forma.
    if assessment and isinstance(assessment.exam, dict) and assessment.exam:
        abnormal = []
        for system, val in assessment.exam.items():
            if isinstance(val, dict):
                finding = (val.get('finding') or '').strip()
                if val.get('status') == 'altered' or finding:
                    abnormal.append((system, finding))
        if abnormal:
            flow += section(st, theme, "Exploración física")
            rows = [
                [Paragraph(safe_pdf_text(str(s)), st['cell']),
                 Paragraph(safe_pdf_text(f or 'Alterado'), st['cell'])]
                for s, f in abnormal
            ]
            flow += data_table(
                st, theme, ["Sistema", "Hallazgo"], rows,
                col_widths=[5 * cm, CONTENT_WIDTH - 5 * cm],
            )

    if record.diagnosis:
        flow += section(st, theme, "Diagnóstico")
        flow.append(Paragraph(
            safe_pdf_text(record.diagnosis).replace('\n', '<br/>'), st['body'],
        ))

    if assessment and assessment.differentials:
        flow += section(st, theme, "Diagnósticos diferenciales")
        flow.append(Paragraph(
            safe_pdf_text(assessment.differentials).replace('\n', '<br/>'), st['body'],
        ))

    if record.treatment:
        flow += section(st, theme, "Tratamiento")
        flow.append(Paragraph(
            safe_pdf_text(record.treatment).replace('\n', '<br/>'), st['body'],
        ))

    if assessment and assessment.recheck_date:
        flow += section(st, theme, "Próxima revisión")
        flow.append(Paragraph(assessment.recheck_date.strftime('%d/%m/%Y'), st['body']))

    # Informe quirúrgico (protocolo Cirugía, A3).
    surgery = next(iter(record.surgery_records.all()), None)
    if surgery:
        flow += section(st, theme, "Informe quirúrgico")
        sg_pairs = [
            ("Tipo", safe_pdf_text(surgery.get_surgery_type_display())),
            ("ASA", "ASA " + surgery.asa_class + ("E" if surgery.asa_emergency else "")),
            ("Anestesia", safe_pdf_text(surgery.get_anesthesia_type_display())),
        ]
        if surgery.wound_class:
            sg_pairs.append(("Herida", safe_pdf_text(surgery.get_wound_class_display())))
        flow += info_card(st, theme, sg_pairs, columns=3)
        if surgery.preop_diagnosis:
            flow.append(Paragraph("<b>Dx prequirúrgico:</b> " + safe_pdf_text(surgery.preop_diagnosis), st['body']))
        flow.append(Paragraph("<b>Procedimiento:</b> " + safe_pdf_text(surgery.procedure).replace('\n', '<br/>'), st['body']))
        if surgery.findings:
            flow.append(Paragraph("<b>Hallazgos:</b> " + safe_pdf_text(surgery.findings).replace('\n', '<br/>'), st['body']))
        if surgery.complications:
            flow.append(Paragraph("<b>Complicaciones:</b> " + safe_pdf_text(surgery.complications), st['body']))
        flow.append(Paragraph("<b>Indicaciones postoperatorias:</b> " + safe_pdf_text(surgery.postop_instructions).replace('\n', '<br/>'), st['body']))
        if surgery.suture_removal_date:
            flow.append(Paragraph("<b>Retiro de puntos:</b> " + surgery.suture_removal_date.strftime('%d/%m/%Y'), st['body']))

    # Informe de urgencia (protocolo Urgencia, A3).
    emergency = next(iter(record.emergency_records.all()), None)
    if emergency:
        flow += section(st, theme, "Informe de urgencia")
        em_pairs = [
            ("Triage", safe_pdf_text(emergency.get_triage_level_display())),
            ("Llegada", fmt_dt(emergency.arrived_at)),
            ("Hora triage", fmt_dt(emergency.triage_at)),
        ]
        if emergency.discharged_at:
            em_pairs.append(("Egreso", fmt_dt(emergency.discharged_at)))
        flow += info_card(st, theme, em_pairs, columns=3)
        abc = ("A: " + emergency.get_airway_status_display()
               + " · B: " + emergency.get_breathing_status_display()
               + " · C: " + emergency.get_circulation_status_display())
        flow.append(Paragraph("<b>Evaluación rápida (ABC):</b> " + safe_pdf_text(abc), st['body']))
        flow.append(Paragraph("<b>Problema principal:</b> " + safe_pdf_text(emergency.chief_complaint), st['body']))
        flow.append(Paragraph("<b>Acciones de estabilización:</b> " + safe_pdf_text(emergency.stabilization_actions).replace('\n', '<br/>'), st['body']))
        if emergency.response:
            flow.append(Paragraph("<b>Respuesta:</b> " + safe_pdf_text(emergency.response), st['body']))
        flow.append(Paragraph("<b>Estado al egreso:</b> " + safe_pdf_text(emergency.get_discharge_status_display()), st['body']))
        if emergency.reassessment_date:
            flow.append(Paragraph("<b>Revaloración:</b> " + emergency.reassessment_date.strftime('%d/%m/%Y'), st['body']))

    services = list(record.services_used.all())
    if services:
        flow += section(st, theme, "Servicios aplicados")
        rows = [
            [Paragraph(safe_pdf_text(s.service.name if s.service_id else "-"), st['cell']),
             f"{s.quantity:g}"]
            for s in services
        ]
        flow += data_table(
            st, theme, ["Servicio", "Cantidad"], rows,
            col_widths=[CONTENT_WIDTH - 4.3 * cm, 4.3 * cm], align_right=(1,),
        )

    products = list(record.products_used.all())
    if products:
        flow += section(st, theme, "Productos utilizados")
        rows = []
        for p in products:
            pres = p.presentation
            prod_name = safe_pdf_text(pres.product.name if pres and pres.product_id else "-")
            pres_name = safe_pdf_text(pres.name if pres else "-")
            rows.append([
                Paragraph(prod_name, st['cell']),
                Paragraph(pres_name, st['cell']),
                f"{p.quantity:g}",
            ])
        flow += data_table(
            st, theme, ["Producto", "Presentación", "Cantidad"], rows,
            col_widths=[CONTENT_WIDTH - 8.8 * cm, 6 * cm, 2.8 * cm], align_right=(2,),
        )

    if record.notes:
        flow += section(st, theme, "Notas")
        flow.append(Paragraph(
            safe_pdf_text(record.notes).replace('\n', '<br/>'), st['body'],
        ))

    prescription = getattr(record, 'prescription', None)
    if prescription:
        flow += section(st, theme, "Receta")
        for i, item in enumerate(prescription.items.all(), 1):
            first_pres = next(iter(item.product.presentations.all()), None)
            unit = first_pres.get_base_unit_display() if first_pres else ""
            item_title = (
                f"{safe_pdf_text(item.product.name)} — "
                f"{item.quantity:g} {safe_pdf_text(unit)}"
            ).rstrip()
            detail_parts = [f"Dosis: {safe_pdf_text(item.dose)}"]
            if item.duration:
                detail_parts.append(f"Duración: {safe_pdf_text(item.duration)}")
            if item.instructions:
                detail_parts.append(f"Instrucciones: {safe_pdf_text(item.instructions)}")
            flow += numbered_item(st, i, item_title, detail_parts)
        if prescription.notes:
            flow.append(Paragraph(
                f"Notas de receta: {safe_pdf_text(prescription.notes)}",
                st['note_italic'],
            ))

    buffer = BytesIO()
    render_branded_pdf(
        buffer, flow,
        organization=org,
        doc_kicker="Resumen de consulta",
        pdf_title=f"Consulta #{record.id}",
    )
    buffer.seek(0)

    created_local = utc_to_local(org, record.created_at)
    filename = pdf_filename(
        'consulta', record.id, pet.name,
        created_local.date() if created_local else None,
    )
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@api_view(['GET'])
@permission_classes([make_permission("medicalrecord.list")])
def protocol_analytics(request):
    """
    Analítica por protocolo — versión **LITE** (A3): agregación read-only AL VUELO
    sobre SurgeryRecord/EmergencyRecord/VaccineRecord por rango de fechas. NO usa
    snapshots `DailyOrgMetrics` ni bumpea `METRICS_SCHEMA_VERSION`. Deuda de
    migración a snapshot formal documentada en docs/modules/analytics.md.

    GET /api/medical-records/protocol-analytics/?from=YYYY-MM-DD&to=YYYY-MM-DD
    Default: últimos 30 días. Anchors: cirugía=created_at, urgencia=arrived_at,
    vacuna=application_date.
    """
    from datetime import timedelta
    from .models import SurgeryRecord, EmergencyRecord

    org = request.user.organization
    today = timezone.localdate()

    def parse_date(value, default):
        try:
            return date.fromisoformat(value) if value else default
        except (TypeError, ValueError):
            return default

    date_to = parse_date(request.query_params.get('to'), today)
    date_from = parse_date(request.query_params.get('from'), today - timedelta(days=30))

    def bump(d, key):
        d[key] = d.get(key, 0) + 1

    # ── Cirugía (anchor: created_at) ──
    _NONE = {'', 'ninguna', 'ninguno', 'sin complicaciones', 'no', 'n/a', 's/c'}
    s_total = 0
    s_by_type, s_by_asa, s_by_wound, s_compl = {}, {}, {}, 0
    for s in SurgeryRecord.objects.for_organization(org).filter(
        created_at__date__gte=date_from, created_at__date__lte=date_to,
    ).values('surgery_type', 'asa_class', 'asa_emergency', 'wound_class', 'complications'):
        s_total += 1
        bump(s_by_type, s['surgery_type'] or '—')
        bump(s_by_asa, 'ASA ' + (s['asa_class'] or '?') + ('E' if s['asa_emergency'] else ''))
        if s['wound_class']:
            bump(s_by_wound, s['wound_class'])
        c = (s['complications'] or '').strip().lower()
        if c and c not in _NONE:
            s_compl += 1
    surgery = {
        'total': s_total,
        'by_type': s_by_type,
        'by_asa': s_by_asa,
        'by_wound_class': s_by_wound,
        'complications_count': s_compl,
        'complication_rate': round(s_compl / s_total, 3) if s_total else 0,
    }

    # ── Urgencia (anchor: arrived_at) ──
    e_total = 0
    e_by_triage, e_by_discharge = {}, {}
    door_to_triage, length_of_stay = [], []
    for e in EmergencyRecord.objects.for_organization(org).filter(
        arrived_at__date__gte=date_from, arrived_at__date__lte=date_to,
    ).values('triage_level', 'discharge_status', 'arrived_at', 'triage_at', 'discharged_at'):
        e_total += 1
        bump(e_by_triage, e['triage_level'] or '—')
        bump(e_by_discharge, e['discharge_status'] or '—')
        if e['arrived_at'] and e['triage_at']:
            door_to_triage.append((e['triage_at'] - e['arrived_at']).total_seconds() / 60)
        if e['arrived_at'] and e['discharged_at']:
            length_of_stay.append((e['discharged_at'] - e['arrived_at']).total_seconds() / 60)

    def avg(values):
        return round(sum(values) / len(values), 1) if values else None

    emergency = {
        'total': e_total,
        'by_triage_level': e_by_triage,
        'by_discharge_status': e_by_discharge,
        'avg_door_to_triage_min': avg(door_to_triage),
        'avg_length_of_stay_min': avg(length_of_stay),
    }

    # ── Vacuna (anchor: application_date) ──
    vaccine = {
        'total': VaccineRecord.objects.for_organization(org).filter(
            application_date__gte=date_from, application_date__lte=date_to,
        ).count(),
        'upcoming_boosters_30d': VaccineRecord.objects.for_organization(org).filter(
            next_due_date__gte=today, next_due_date__lte=today + timedelta(days=30),
        ).count(),
    }

    return Response({
        'from': date_from.isoformat(),
        'to': date_to.isoformat(),
        'surgery': surgery,
        'emergency': emergency,
        'vaccine': vaccine,
    })
