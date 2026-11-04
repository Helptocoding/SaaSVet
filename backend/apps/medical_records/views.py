import logging
from datetime import date

from apps.core.datetime_utils import org_today_local

from django.db import transaction
from django.http import Http404
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
            from uuid import UUID
            from django.db.models import Q
            from apps.patients.models import Pet
            try:
                pet_uuid = str(UUID(str(pet_lookup)))
            except (ValueError, TypeError):
                # No es un UUID: puede ser un id legacy. resolve_public_id lo
                # valida dentro de la organización y lanza 404 si no existe.
                pet = resolve_public_id(Pet.all_objects.filter(organization=org), pet_lookup)
                pet_uuid = str(pet.public_id)

            # La identidad se verifica SIEMPRE contra esta organización, también
            # cuando el valor ya venía con forma de UUID.
            #
            # Antes el `try` devolvía el UUID parseado y saltaba la verificación,
            # de modo que ésta solo corría en el camino del `except` — el único
            # donde no puede importar. Un UUID válido de OTRA clínica parseaba
            # bien, no se verificaba, y caía al filtro de abajo: como el queryset
            # ya es `for_organization(org)`, no devolvía expedientes ajenos, pero
            # respondía 200 con lista vacía donde un UUID inexistente responde
            # 404. Esa diferencia es un oráculo de existencia cross-tenant, y el
            # invariante del proyecto lo prohíbe por nombre: «cross-tenant
            # retorna 404, nunca []» (docs/system-reference.md §3.1). Lo cazó
            # `test_day6_invariants.test_cross_tenant_pet_returns_404` con
            # `200 != 404`.
            #
            # Se admite la mascota VIVA de la organización y también la que solo
            # existe como sujeto histórico: `subject_snapshot` se busca sobre el
            # queryset ya acotado por organización, así que encontrarlo ahí es
            # prueba de pertenencia. Resolver únicamente contra `Pet` vivo
            # rompería la continuidad histórica.
            scoped = queryset.filter(Q(pet__public_id=pet_uuid) |
                                     Q(subject_snapshot__pet__uuid=pet_uuid))
            if not (
                Pet.all_objects.filter(organization=org, public_id=pet_uuid).exists()
                or scoped.exists()
            ):
                raise Http404('No existe una mascota con ese identificador.')
            queryset = scoped

        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        from apps.organizations.models import Organization
        from apps.patients.models import Owner, Pet
        from rest_framework.exceptions import ValidationError
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=self.request.user.organization_id)
            pet_id = serializer.validated_data['pet'].pk
            owner_id = Pet.all_objects.filter(pk=pet_id, organization=org).values_list(
                'owner_id', flat=True,
            ).first()
            owner = Owner.all_objects.select_for_update().filter(pk=owner_id, organization=org).first()
            pet = Pet.all_objects.select_for_update().filter(pk=pet_id, organization=org).first()
            if not org.is_active or not owner or not owner.is_active or not pet or not pet.is_active:
                raise ValidationError({'pet': 'La mascota o su cliente no están activos.'})
            serializer.save(organization=org, veterinarian=self.request.user, pet=pet)


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
        pet_uuid = self.kwargs['pet_public_id']
        from uuid import UUID
        from django.db.models import Q
        try:
            pet_uuid = str(UUID(str(pet_uuid)))
        except (ValueError, TypeError):
            pet = resolve_public_id(Pet.all_objects.filter(organization=self.request.user.organization),
                                    pet_uuid)
            pet_uuid = str(pet.public_id)
        return MedicalRecord.objects.for_organization(
            self.request.user.organization
        ).filter(Q(pet__public_id=pet_uuid) | Q(subject_snapshot__pet__uuid=pet_uuid)).select_related(
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

        from apps.core.subject_history import identity
        prior_pet = identity(mr, 'pet')
        live_pet = mr.pet if mr.pet_id else None
        data = {
            "patient": {
                "name": prior_pet.get('name') or (live_pet.name if live_pet else 'Desconocido'),
                "species": prior_pet.get('species') or (live_pet.species if live_pet else ''),
                "breed": prior_pet.get('breed') or (live_pet.breed if live_pet else ''),
                "birth_date": prior_pet.get('birth_date') or (live_pet.birth_date if live_pet else None),
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
    from .services import close_medical_record_service
    medical_record = close_medical_record_service(request, pk)
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
            pet = resolve_public_id(Pet.all_objects.filter(organization=org), pet_lookup)
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
        pdf_markup, section, title_block,
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

    if record.status == MedicalRecord.Status.CLOSED or record.veterinarian_id:
        vet = record.veterinarian if record.status != MedicalRecord.Status.CLOSED else None
        vet_name = (record.vet_name_at_close or 'Desconocido') if vet is None else (
            f"{vet.first_name} {vet.last_name}".strip() or vet.username)
        specialty = record.vet_specialty_at_close if vet is None else vet.specialty
        spec = f" &nbsp;·&nbsp; {pdf_markup(specialty)}" if specialty else ""
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{pdf_markup(vet_name)}{spec}", st['body']))

    from apps.core.subject_history import identity
    old_pet = identity(record, 'pet')
    old_owner = identity(record, 'owner')
    pet = record.pet if record.pet_id else None
    flow += section(st, theme, "Paciente")
    patient_pairs = [
        ("Nombre", pdf_markup(old_pet.get('name') or (pet.name if pet else 'Desconocido'))),
        ("Especie", pdf_markup(old_pet.get('species') or (pet.species if pet else ''))),
        ("Raza", pdf_markup(old_pet.get('breed') or (pet.breed if pet else ''))),
    ]
    if old_owner or (pet and pet.owner_id):
        patient_pairs += [
            ("Dueño", pdf_markup(old_owner.get('name') or (pet.owner.name if pet else 'Desconocido'))),
            ("Teléfono", pdf_markup(old_owner.get('phone') or (pet.owner.phone if pet else ''))),
        ]
    flow += info_card(st, theme, patient_pairs, columns=3)

    # Motivo (SOAP·S): motivo principal del assessment; fallback al motivo de la cita.
    motivo = (assessment.chief_complaint if assessment else '') or (
        record.appointment.reason
        if record.appointment_id and getattr(record.appointment, 'reason', '') else ''
    )
    if motivo:
        flow += section(st, theme, "Motivo de consulta")
        flow.append(Paragraph(pdf_markup(motivo), st['body']))

    if assessment and assessment.history:
        flow += section(st, theme, "Historia clínica")
        flow.append(Paragraph(
            pdf_markup(assessment.history, linebreaks=True), st['body'],
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
                [Paragraph(pdf_markup(str(s)), st['cell']),
                 Paragraph(pdf_markup(f or 'Alterado'), st['cell'])]
                for s, f in abnormal
            ]
            flow += data_table(
                st, theme, ["Sistema", "Hallazgo"], rows,
                col_widths=[5 * cm, CONTENT_WIDTH - 5 * cm],
            )

    if record.diagnosis:
        flow += section(st, theme, "Diagnóstico")
        flow.append(Paragraph(
            pdf_markup(record.diagnosis, linebreaks=True), st['body'],
        ))

    if assessment and assessment.differentials:
        flow += section(st, theme, "Diagnósticos diferenciales")
        flow.append(Paragraph(
            pdf_markup(assessment.differentials, linebreaks=True), st['body'],
        ))

    if record.treatment:
        flow += section(st, theme, "Tratamiento")
        flow.append(Paragraph(
            pdf_markup(record.treatment, linebreaks=True), st['body'],
        ))

    if assessment and assessment.recheck_date:
        flow += section(st, theme, "Próxima revisión")
        flow.append(Paragraph(assessment.recheck_date.strftime('%d/%m/%Y'), st['body']))

    # Informe quirúrgico (protocolo Cirugía, A3).
    surgery = next(iter(record.surgery_records.all()), None)
    if surgery:
        flow += section(st, theme, "Informe quirúrgico")
        sg_pairs = [
            ("Tipo", pdf_markup(surgery.get_surgery_type_display())),
            ("ASA", "ASA " + surgery.asa_class + ("E" if surgery.asa_emergency else "")),
            ("Anestesia", pdf_markup(surgery.get_anesthesia_type_display())),
        ]
        if surgery.wound_class:
            sg_pairs.append(("Herida", pdf_markup(surgery.get_wound_class_display())))
        flow += info_card(st, theme, sg_pairs, columns=3)
        if surgery.preop_diagnosis:
            flow.append(Paragraph("<b>Dx prequirúrgico:</b> " + pdf_markup(surgery.preop_diagnosis), st['body']))
        flow.append(Paragraph("<b>Procedimiento:</b> " + pdf_markup(surgery.procedure, linebreaks=True), st['body']))
        if surgery.findings:
            flow.append(Paragraph("<b>Hallazgos:</b> " + pdf_markup(surgery.findings, linebreaks=True), st['body']))
        if surgery.complications:
            flow.append(Paragraph("<b>Complicaciones:</b> " + pdf_markup(surgery.complications), st['body']))
        flow.append(Paragraph("<b>Indicaciones postoperatorias:</b> " + pdf_markup(surgery.postop_instructions, linebreaks=True), st['body']))
        if surgery.suture_removal_date:
            flow.append(Paragraph("<b>Retiro de puntos:</b> " + surgery.suture_removal_date.strftime('%d/%m/%Y'), st['body']))

    # Informe de urgencia (protocolo Urgencia, A3).
    emergency = next(iter(record.emergency_records.all()), None)
    if emergency:
        flow += section(st, theme, "Informe de urgencia")
        em_pairs = [
            ("Triage", pdf_markup(emergency.get_triage_level_display())),
            ("Llegada", fmt_dt(emergency.arrived_at)),
            ("Hora triage", fmt_dt(emergency.triage_at)),
        ]
        if emergency.discharged_at:
            em_pairs.append(("Egreso", fmt_dt(emergency.discharged_at)))
        flow += info_card(st, theme, em_pairs, columns=3)
        abc = ("A: " + emergency.get_airway_status_display()
               + " · B: " + emergency.get_breathing_status_display()
               + " · C: " + emergency.get_circulation_status_display())
        flow.append(Paragraph("<b>Evaluación rápida (ABC):</b> " + pdf_markup(abc), st['body']))
        flow.append(Paragraph("<b>Problema principal:</b> " + pdf_markup(emergency.chief_complaint), st['body']))
        flow.append(Paragraph("<b>Acciones de estabilización:</b> " + pdf_markup(emergency.stabilization_actions, linebreaks=True), st['body']))
        if emergency.response:
            flow.append(Paragraph("<b>Respuesta:</b> " + pdf_markup(emergency.response), st['body']))
        flow.append(Paragraph("<b>Estado al egreso:</b> " + pdf_markup(emergency.get_discharge_status_display()), st['body']))
        if emergency.reassessment_date:
            flow.append(Paragraph("<b>Revaloración:</b> " + emergency.reassessment_date.strftime('%d/%m/%Y'), st['body']))

    services = list(record.services_used.all())
    if services:
        flow += section(st, theme, "Servicios aplicados")
        rows = [
            [Paragraph(pdf_markup(s.service.name if s.service_id else "-"), st['cell']),
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
            prod_name = pdf_markup(pres.product.name if pres and pres.product_id else "-")
            pres_name = pdf_markup(pres.name if pres else "-")
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
            pdf_markup(record.notes, linebreaks=True), st['body'],
        ))

    prescription = getattr(record, 'prescription', None)
    if prescription:
        flow += section(st, theme, "Receta")
        for i, item in enumerate(prescription.items.all(), 1):
            first_pres = next(iter(item.product.presentations.all()), None)
            unit = first_pres.get_base_unit_display() if first_pres else ""
            item_title = (
                f"{pdf_markup(item.product.name)} — "
                f"{item.quantity:g} {pdf_markup(unit)}"
            ).rstrip()
            detail_parts = [f"Dosis: {pdf_markup(item.dose)}"]
            if item.duration:
                detail_parts.append(f"Duración: {pdf_markup(item.duration)}")
            if item.instructions:
                detail_parts.append(f"Instrucciones: {pdf_markup(item.instructions)}")
            flow += numbered_item(st, i, item_title, detail_parts)
        if prescription.notes:
            flow.append(Paragraph(
                f"Notas de receta: {pdf_markup(prescription.notes)}",
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
        'consulta', record.id, old_pet.get('name') or (pet.name if pet else 'paciente-historico'),
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
