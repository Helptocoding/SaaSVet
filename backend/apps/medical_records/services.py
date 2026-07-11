"""
Services de medical_records: efectos de dominio con lock/atomicidad.

Materializacion de los protocolos clinicos al cerrar la consulta. El writer de
`closed_at` sigue en views.py (deuda A3); estas funciones son efectos-de-cierre
mas, invocados dentro del mismo `transaction.atomic()`.

PRINCIPIO (binding, ADR p50): un protocolo NUNCA modifica MedicalRecord; solo
crea o actualiza sus PROPIOS registros de dominio (VaccineRecord,
ConsultationAssessment, ...). El scratchpad `consultation_draft` es borrador de
UI; los registros materializados son la fuente de verdad.

Despacho por `consultation_type` con `if/elif` incremental. Cuando llegue el 3er
protocolo (Cirugia) se extrae un registry backend de materializadores
`{type: fn}` y un `close_medical_record_service()` (ver
docs/plan-implementacion-protocolos-clinicos-2026-07-09.md, Slice C). No abstraer
antes de tiempo.
"""
import logging

from .models import ConsultationAssessment, MedicalRecord

logger = logging.getLogger("medical_records.events")


def apply_consultation_draft_on_close(medical_record, request):
    """
    Materializa el registro de dominio del protocolo capturado en el scratchpad
    `consultation_draft`, al finalizar la consulta.

    Debe invocarse DENTRO del `transaction.atomic()` de close_medical_record, con
    el MedicalRecord ya lockeado (select_for_update). Idempotente por diseno: el
    caller solo llega aqui en la rama "estaba open -> se cierra", asi que corre
    una sola vez por consulta.

    Si el draft del protocolo es invalido, el serializer levanta ValidationError
    -> rollback del cierre completo (defensa en profundidad; el frontend ya valida
    antes de finalizar).
    """
    ctype = medical_record.consultation_type
    if ctype == MedicalRecord.ConsultationType.VACCINE:
        return _materialize_vaccine(medical_record, request)
    if ctype == MedicalRecord.ConsultationType.GENERAL:
        return _materialize_general(medical_record, request)
    return None


def add_medical_record_product(medical_record, presentation, quantity, cost_behavior, lot, user):
    """
    **Fuente única** para agregar (o incrementar) un producto consumido en la
    consulta: crea/incrementa el `MedicalRecordProduct` (descuenta stock del lote,
    B2a) y sincroniza el `InvoiceItem` en la factura draft si `cost_behavior='charge'`.
    La usan la view de Cargos (`MedicalRecordProductListCreateView`) y la
    materialización del protocolo Vacuna (A2) — se extrajo al aparecer el 2º caller.

    Debe correr dentro de `transaction.atomic()` con el MedicalRecord ya lockeado.
    Devuelve el `MedicalRecordProduct`.
    """
    from apps.inventory.models import Presentation, MedicalRecordProduct
    from apps.billing.models import InvoiceItem
    from apps.billing.services import (
        apply_invoice_item_quantity_delta,
        get_or_create_invoice_for_medical_record,
    )

    invoice = get_or_create_invoice_for_medical_record(medical_record)
    locked_pres = Presentation.objects.select_for_update().get(pk=presentation.pk)

    mrp = MedicalRecordProduct.objects.select_for_update().filter(
        medical_record=medical_record, presentation=locked_pres,
    ).first()
    # cost_behavior inmutable: al incrementar se usa el del MRP existente.
    effective_cost_behavior = mrp.cost_behavior if mrp is not None else cost_behavior

    if invoice.status == 'draft' and effective_cost_behavior == 'charge':
        item = InvoiceItem.objects.select_for_update().filter(
            invoice=invoice, presentation=locked_pres, is_active=True,
        ).first()
        if item is None:
            InvoiceItem.objects.create(
                invoice=invoice, presentation=locked_pres, description=str(locked_pres),
                quantity=quantity, unit_price=locked_pres.sale_price,
                organization=invoice.organization,
            )
        else:
            apply_invoice_item_quantity_delta(item, quantity)

    if mrp is not None:
        previous_quantity = mrp.quantity
        mrp.quantity = previous_quantity + quantity
        mrp.save(locked_presentation=locked_pres, previous_quantity=previous_quantity)
    else:
        mrp = MedicalRecordProduct(
            medical_record=medical_record, presentation=locked_pres,
            quantity=quantity, cost_behavior=cost_behavior, lot=lot,
        )
        mrp.save(locked_presentation=locked_pres)
    return mrp


def _materialize_vaccine(medical_record, request):
    """
    Protocolo Vacuna. Gate: el draft trae `vaccine_name`. Si no, la consulta de
    vacuna se finaliza sin materializar registro legal (decision de negocio).

    A2: si el draft liga un `product_id` de inventario, se consume 1 dosis del lote
    (auto-alta de MedicalRecordProduct qty=1, modo = `product.default_cost_behavior`,
    editable luego en Cargos) y el VaccineRecord guarda product+lot+snapshot
    (lot_number/expiry/manufacturer, inmutable). Sin producto → texto libre (fallback).
    Si el vet YA agregó el producto en Cargos, se reusa ese MRP/lote (no doble consumo).
    """
    from decimal import Decimal
    from rest_framework.exceptions import ValidationError
    from .serializers import VaccineRecordSerializer
    from apps.inventory.models import Product, StockLot, MedicalRecordProduct

    draft = medical_record.consultation_draft or {}
    vaccine = draft.get("vaccine") or {}
    vaccine_name = (vaccine.get("vaccine_name") or "").strip()
    if not vaccine_name:
        return None

    org = medical_record.organization
    product = None
    lot = None
    product_id = vaccine.get("product_id")

    if product_id:
        product = Product.objects.for_organization(org).filter(pk=product_id).first()
        if product is None:
            raise ValidationError({"vaccine": "Producto de vacuna inválido."})
        presentation = product.presentations.first()
        if presentation is None:
            raise ValidationError({"vaccine": "El producto de vacuna no tiene presentación."})

        existing_mrp = MedicalRecordProduct.objects.filter(
            medical_record=medical_record, presentation=presentation,
        ).first()
        if existing_mrp is not None:
            # El vet ya lo agregó en Cargos → reusar su lote, no consumir de nuevo.
            lot = existing_mrp.lot
        else:
            if product.tracks_lots:
                lot_id = vaccine.get("lot_id")
                lot = (
                    StockLot.objects.for_organization(org)
                    .filter(pk=lot_id, product=product).first() if lot_id else None
                )
                if lot is None:
                    raise ValidationError({"vaccine": "Selecciona el lote de la vacuna aplicada."})
                if not lot.is_consumable:
                    raise ValidationError(
                        {"vaccine": f"El lote {lot.lot_number} no está disponible."}
                    )
            add_medical_record_product(
                medical_record, presentation, Decimal('1'),
                product.default_cost_behavior, lot, request.user,
            )

    schedule_booster = bool(vaccine.get("scheduleBooster", True))
    payload = {
        "pet": medical_record.pet_id,
        "vaccine_name": vaccine_name,
        "application_date": vaccine.get("application_date"),
        "next_due_date": vaccine.get("next_due_date") if schedule_booster else None,
        "notes": vaccine.get("notes") or "",
    }
    serializer = VaccineRecordSerializer(data=payload, context={"request": request})
    serializer.is_valid(raise_exception=True)
    vaccine_record = serializer.save(
        organization=org,
        medical_record=medical_record,
        applied_by=request.user,
        product=product,
        lot=lot,
        lot_number=(lot.lot_number if lot else ''),
        lot_expiry=(lot.expiry_date if lot else None),
        manufacturer=(product.manufacturer if product else ''),
    )

    logger.info(
        "VACCINE_RECORD_MATERIALIZED_ON_CLOSE",
        extra={
            "user_id": request.user.id,
            "organization_id": request.user.organization_id,
            "medical_record_id": medical_record.id,
            "vaccine_record_id": vaccine_record.id,
            "product_id": product.id if product else None,
            "lot_id": lot.id if lot else None,
        },
    )
    return vaccine_record


def _materialize_general(medical_record, request):
    """
    Protocolo General (familia diagnostica). Gate: el draft `general` trae algo
    de contenido estructurado (SOAP S/O). Una consulta general "clasica" que solo
    llena diagnostico/tratamiento en MedicalRecord no genera assessment (aditivo,
    retrocompatible con el flujo previo).
    """
    draft = medical_record.consultation_draft or {}
    general = draft.get("general") or {}

    has_content = any([
        (general.get("chief_complaint") or "").strip(),
        (general.get("history") or "").strip(),
        (general.get("differentials") or "").strip(),
        bool(general.get("exam")),
        general.get("recheck_date"),
    ])
    if not has_content:
        return None

    from .serializers import ConsultationAssessmentSerializer

    payload = {
        "chief_complaint": general.get("chief_complaint") or "",
        "history": general.get("history") or "",
        "exam": general.get("exam") or {},
        "differentials": general.get("differentials") or "",
        "recheck_date": general.get("recheck_date"),
    }
    serializer = ConsultationAssessmentSerializer(data=payload, context={"request": request})
    serializer.is_valid(raise_exception=True)
    assessment = serializer.save(
        organization=medical_record.organization,
        medical_record=medical_record,
        pet=medical_record.pet,
        assessed_by=request.user,
        protocol_version=ConsultationAssessment.PROTOCOL_VERSION,
    )

    logger.info(
        "CONSULTATION_ASSESSMENT_MATERIALIZED_ON_CLOSE",
        extra={
            "user_id": request.user.id,
            "organization_id": request.user.organization_id,
            "medical_record_id": medical_record.id,
            "consultation_assessment_id": assessment.id,
        },
    )
    return assessment
