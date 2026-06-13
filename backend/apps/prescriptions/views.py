from io import BytesIO
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes

from apps.core.permissions import HybridPermission, make_permission
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id

from .models import Prescription, PrescriptionItem
from .serializers import PrescriptionSerializer, PrescriptionItemWriteSerializer


class PrescriptionListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = PrescriptionSerializer
    permission_classes = [HybridPermission]
    resource_name = "prescription"

    def get_queryset(self):
        org = self.request.user.organization
        queryset = Prescription.objects.for_organization(org).select_related(
            'pet', 'veterinarian', 'medical_record'
        )
        pet_lookup = self.request.query_params.get('pet')
        if pet_lookup:
            # Día 6 Fase 3: resolver Pet por public_id antes del filtro
            from apps.patients.models import Pet
            pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
            queryset = queryset.filter(pet=pet)
        return queryset

    def perform_create(self, serializer):
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
        pet = resolve_public_id(
            Pet.objects.for_organization(self.request.user.organization),
            self.kwargs['pet_public_id'],
        )
        return Prescription.objects.for_organization(
            self.request.user.organization
        ).filter(pet=pet)


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
        pdf_filename, render_branded_pdf, safe_pdf_text, section,
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

    pet = prescription.pet
    vet = prescription.veterinarian
    vet_name = ""
    if vet:
        vet_name = f"{vet.first_name} {vet.last_name}".strip() or vet.username

    created_local = utc_to_local(prescription.organization, prescription.created_at)

    flow = []
    flow += title_block(
        st,
        title=f"Receta #{prescription.id}",
        meta_lines=[f"Fecha: {created_local.strftime('%d/%m/%Y') if created_local else ''}"],
    )

    flow += section(st, theme, "Paciente")
    patient_pairs = [
        ("Nombre", safe_pdf_text(pet.name)),
        ("Especie", safe_pdf_text(pet.species)),
        ("Raza", safe_pdf_text(pet.breed or '')),
    ]
    if pet.owner_id:
        patient_pairs += [
            ("Propietario", safe_pdf_text(pet.owner.name)),
            ("Teléfono", safe_pdf_text(pet.owner.phone)),
        ]
    flow += info_card(st, theme, patient_pairs, columns=3)

    if vet:
        spec = f" &nbsp;·&nbsp; {safe_pdf_text(vet.specialty)}" if vet.specialty else ""
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{safe_pdf_text(vet_name)}{spec}", st['body']))

    flow += section(st, theme, "Medicamentos")
    items_qs = prescription.items.select_related('product').prefetch_related('product__presentations').all()
    for i, item in enumerate(items_qs, 1):
        first_pres = next(iter(item.product.presentations.all()), None)
        unit = first_pres.get_base_unit_display() if first_pres else ''
        item_title = (
            f"{safe_pdf_text(item.product.name)} — "
            f"{item.quantity:g} {safe_pdf_text(unit)}"
        ).rstrip()
        details = [f"Dosis: {safe_pdf_text(item.dose)}"]
        if item.duration:
            details.append(f"Duración: {safe_pdf_text(item.duration)}")
        if item.instructions:
            details.append(f"Instrucciones: {safe_pdf_text(item.instructions)}")
        flow += numbered_item(st, i, item_title, details)

    if prescription.notes:
        flow += section(st, theme, "Notas")
        flow.append(Paragraph(
            safe_pdf_text(prescription.notes).replace('\n', '<br/>'), st['body'],
        ))

    if vet:
        flow += signature_block(
            st, theme, safe_pdf_text(vet_name),
            [safe_pdf_text(vet.specialty)] if vet.specialty else (),
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
        'receta', prescription.id, pet.name,
        created_local.date() if created_local else None,
    )
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
