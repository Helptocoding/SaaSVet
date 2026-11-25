from io import BytesIO
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes

from apps.core.permissions import HybridPermission, make_permission
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id
# La inmutabilidad post-cierre la define el dominio dueño de la consulta. Mismo
# precedente que `inventory/views.py`, que ya consume estas policies.
from apps.medical_records.policies import assert_can_modify_medical_record
from apps.users.professional import require_signer_license

from .models import Prescription, PrescriptionItem
from .serializers import PrescriptionSerializer, PrescriptionItemWriteSerializer


class PrescriptionListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = PrescriptionSerializer
    permission_classes = [HybridPermission]
    resource_name = "prescription"
    # P1-2: NO se pagina. La página /prescriptions filtra client-side por
    # especie/sexo/edad/texto sobre la lista completa (pages/prescriptions.jsx
    # `filtered = prescriptions.filter(...)`); paginar rompería esos filtros
    # (solo verían la página actual). Diferido junto con Pets/Appointments
    # hasta tener filtros server-side (evita "cambios UX grandes" — ver P1-2).

    def get_queryset(self):
        org = self.request.user.organization
        queryset = Prescription.objects.for_organization(org).select_related(
            'pet', 'veterinarian', 'medical_record'
        )
        pet_lookup = self.request.query_params.get('pet')
        if pet_lookup:
            # Día 6 Fase 3: resolver Pet por public_id antes del filtro
            from django.db.models import Q
            from uuid import UUID
            try:
                pet_uuid = str(UUID(str(pet_lookup)))
            except (ValueError, TypeError):
                from apps.patients.models import Pet
                pet_uuid = str(resolve_public_id(
                    Pet.all_objects.filter(organization=org), pet_lookup).public_id)
            queryset = queryset.filter(Q(pet__public_id=pet_uuid) |
                                       Q(subject_snapshot__pet__uuid=pet_uuid))
        return queryset

    def perform_create(self, serializer):
        # M01 (orden 7, ADR p64): quien emite la receta la firma; sin cédula no puede.
        require_signer_license(self.request.user, 'emitir la receta')
        serializer.save(
            organization=self.request.user.organization,
            veterinarian=self.request.user,
        )


class PrescriptionDetailView(PublicIdLookupMixin, TenantQueryMixin, generics.RetrieveUpdateAPIView):
    """PR-4B / ADR p16: DELETE removido por consistencia con motivación
    NOM-046 que justificó Prescription.pet PROTECT. La receta es documento
    legal entregado al paciente — borrarla destruye trazabilidad
    farmacológica. Para anular, PATCH notes o cancelar via UI separado."""
    serializer_class = PrescriptionSerializer
    permission_classes = [HybridPermission]
    resource_name = "prescription"
    lookup_url_kwarg = 'pk'
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        return Prescription.objects.for_organization(self.request.user.organization)


class PrescriptionByPetView(TenantQueryMixin, generics.ListAPIView):
    serializer_class = PrescriptionSerializer
    permission_classes = [HybridPermission]
    resource_name = "prescription"

    def get_queryset(self):
        # Día 6 Fase 1: resolver Pet por public_id antes del filtro
        from apps.patients.models import Pet
        from django.db.models import Q
        from uuid import UUID
        pet_lookup = self.kwargs['pet_public_id']
        try:
            pet_uuid = str(UUID(str(pet_lookup)))
        except (ValueError, TypeError):
            pet_uuid = str(resolve_public_id(
                Pet.all_objects.filter(organization=self.request.user.organization), pet_lookup,
            ).public_id)
        return Prescription.objects.for_organization(
            self.request.user.organization
        ).filter(Q(pet__public_id=pet_uuid) |
                 Q(subject_snapshot__pet__uuid=pet_uuid))


class PrescriptionItemCreateView(generics.CreateAPIView):
    serializer_class = PrescriptionItemWriteSerializer
    permission_classes = [HybridPermission]
    resource_name = "prescription"

    def perform_create(self, serializer):
        # Día 6 Fase 1: parent es UUID público (<str:prescription_pk>)
        prescription = resolve_public_id(
            Prescription.objects.for_organization(self.request.user.organization),
            self.kwargs['prescription_pk'],
        )
        # Inmutabilidad post-cierre: bloqueo DURO, no lista blanca. Añadir un
        # medicamento después de cerrar la consulta no tiene vía legítima, y
        # además ensancha el tope que limita la dispensación (el cap se calcula
        # sobre PrescriptionItem.quantity). Mismo guard que usan los cargos
        # clínicos; esta vista nunca se conectó a él (auditoría run-1).
        assert_can_modify_medical_record(
            self.request.user, prescription.medical_record, self.request,
        )
        serializer.save(prescription=prescription)


class PrescriptionItemDeleteView(generics.DestroyAPIView):
    permission_classes = [HybridPermission]
    resource_name = "prescription"

    def get_object(self):
        # Día 6 Fase 1: parent es UUID público, item child es PK interno
        prescription = resolve_public_id(
            Prescription.objects.for_organization(self.request.user.organization),
            self.kwargs['prescription_pk'],
        )
        # Inmutabilidad post-cierre: retirar un medicamento de una receta ya
        # entregada destruye la trazabilidad farmacológica que motivó quitar el
        # DELETE de la receta completa (NOM-046). Se comprueba al RESOLVER, de
        # modo que cubre también cualquier método futuro de esta vista.
        assert_can_modify_medical_record(
            self.request.user, prescription.medical_record, self.request,
        )
        return get_object_or_404(
            PrescriptionItem,
            pk=self.kwargs['pk'],
            prescription=prescription,
        )


@api_view(['GET'])
@permission_classes([make_permission("prescription.retrieve")])
def prescription_pdf(request, pk):
    """Genera y retorna la receta como archivo PDF."""
    from reportlab.platypus import Paragraph

    from apps.core.datetime_utils import utc_to_local
    from apps.core.pdf import (
        build_styles, get_theme_for_organization, info_card, numbered_item,
        pdf_filename, render_branded_pdf, pdf_markup, section,
        signature_block, title_block,
    )

    prescription = resolve_public_id(
        Prescription.objects
            .for_organization(request.user.organization)
            .select_related('pet__owner', 'veterinarian', 'organization'),
        pk,
    )

    theme = get_theme_for_organization(prescription.organization)
    st = build_styles(theme)

    from apps.core.subject_history import identity
    old_pet = identity(prescription, 'pet')
    old_owner = identity(prescription, 'owner')
    pet = prescription.pet if prescription.pet_id else None
    vet = prescription.veterinarian
    vet_name = (prescription.medical_record.vet_name_at_close or 'Desconocido') if (
        prescription.medical_record.status == 'closed') else (
        f"{vet.first_name} {vet.last_name}".strip() or vet.username if vet else 'Desconocido')

    created_local = utc_to_local(prescription.organization, prescription.created_at)

    flow = []
    flow += title_block(
        st,
        title=f"Receta #{prescription.id}",
        meta_lines=[f"Fecha: {created_local.strftime('%d/%m/%Y') if created_local else ''}"],
    )

    flow += section(st, theme, "Paciente")
    patient_pairs = [
        ("Nombre", pdf_markup(old_pet.get('name') or (pet.name if pet else 'Desconocido'))),
        ("Especie", pdf_markup(old_pet.get('species') or (pet.species if pet else ''))),
        ("Raza", pdf_markup(old_pet.get('breed') or (pet.breed if pet else ''))),
    ]
    if old_owner or (pet and pet.owner_id):
        patient_pairs += [
            ("Propietario", pdf_markup(old_owner.get('name') or (pet.owner.name if pet else 'Desconocido'))),
            ("Teléfono", pdf_markup(old_owner.get('phone') or (pet.owner.phone if pet else ''))),
        ]
    flow += info_card(st, theme, patient_pairs, columns=3)

    if vet or prescription.medical_record.status == 'closed':
        specialty = (prescription.medical_record.vet_specialty_at_close
                     if prescription.medical_record.status == 'closed' else vet.specialty_label)
        # M01 (orden 7): cédula congelada al cierre; la del usuario mientras está abierta.
        license_number = (prescription.medical_record.vet_license_at_close
                          if prescription.medical_record.status == 'closed'
                          else vet.license_number)
        spec = f" &nbsp;·&nbsp; {pdf_markup(specialty)}" if specialty else ""
        if license_number:
            spec += f" &nbsp;·&nbsp; Céd. Prof. {pdf_markup(license_number)}"
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{pdf_markup(vet_name)}{spec}", st['body']))

    flow += section(st, theme, "Medicamentos")
    items_qs = prescription.items.select_related('product').prefetch_related('product__presentations').all()
    for i, item in enumerate(items_qs, 1):
        first_pres = next(iter(item.product.presentations.all()), None)
        unit = first_pres.get_base_unit_display() if first_pres else ''
        item_title = (
            f"{pdf_markup(item.product.name)} — "
            f"{item.quantity:g} {pdf_markup(unit)}"
        ).rstrip()
        details = [f"Dosis: {pdf_markup(item.dose)}"]
        if item.duration:
            details.append(f"Duración: {pdf_markup(item.duration)}")
        if item.instructions:
            details.append(f"Instrucciones: {pdf_markup(item.instructions)}")
        flow += numbered_item(st, i, item_title, details)

    if prescription.notes:
        flow += section(st, theme, "Notas")
        flow.append(Paragraph(
            pdf_markup(prescription.notes, linebreaks=True), st['body'],
        ))

    if vet or prescription.medical_record.status == 'closed':
        flow += signature_block(
            st, theme, pdf_markup(vet_name),
            [pdf_markup(specialty) if specialty else '',
             f"Cédula profesional {pdf_markup(license_number)}" if license_number else ''],
        )

    buffer = BytesIO()
    render_branded_pdf(
        buffer, flow,
        organization=prescription.organization,
        doc_kicker="Receta médica veterinaria",
        pdf_title=f"Receta #{prescription.id}",
    )
    buffer.seek(0)

    filename = pdf_filename(
        'receta', prescription.id, old_pet.get('name') or (pet.name if pet else 'paciente-historico'),
        created_local.date() if created_local else None,
    )
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
