"""Authoritative application services for Checkout -> Billing.

Checkout owns mutable commercial intent. Invoice is created once, at posting,
and is never used as a cart.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.permissions import user_has_permission
from apps.inventory.models import Presentation, StockLot
from apps.inventory.services import consume_product
from apps.inventory.units import (
    presentation_conversion_factor,
    presentation_quantity_to_base,
)

from .models import (
    Checkout, CheckoutDispute, CheckoutEstimate, CheckoutEvent, CheckoutItem, CheckoutPrescriptionSelection,
    ClinicalChargeEntry, ClinicalChargeQuantityEvent, ClinicalChargeSnapshot,
    CollectionCase, CommandReceipt, ExternalPrescriptionAttestation, Invoice,
    InvoiceAuditLog, InvoiceItem, MedicalRecordBillingContext, ObligationEvidence,
    Payment, PrescriptionFulfillmentEvent, ReplacementWaiver, StockAllocation,
    StockDispositionEvent,
)
from .money import invoice_totals
from .prescription_availability import (
    build_checkout_prescription_suggestions,
    presentation_units_to_base,
    validated_presentation_quantity,
)
from .stock_returns import record_invoice_item_disposition
from .services import (
    _legacy_single_line, _pay_locked_invoice, _resolve_cash_session_for_payment,
    _validate_payment_lines,
)


_CANONICAL_DECIMAL_KEYS = {
    'amount', 'quantity', 'new_unit_price', 'expected_quantity',
    'discount_value', 'accepted_total',
}


class CheckoutVersionConflict(ValidationError):
    """Optimistic-concurrency conflict with a stable API classification."""


def _assert_rx_dispense_permission(user):
    if not user_has_permission(user, 'billing.rx_dispense'):
        raise PermissionDenied('No tienes permiso para modificar una dispensación de receta.')


def _canonicalize_payload(value, *, field_name=''):
    if isinstance(value, dict):
        return {
            key: _canonicalize_payload(value[key], field_name=key)
            for key in sorted(value)
        }
    if isinstance(value, (list, tuple)):
        normalized = [_canonicalize_payload(item, field_name=field_name) for item in value]
        if all(isinstance(item, dict) for item in normalized):
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(',', ':')),
            )
        return normalized
    if isinstance(value, Decimal) or (
        field_name in _CANONICAL_DECIMAL_KEYS and isinstance(value, (str, int, float))
    ):
        try:
            number = Decimal(str(value))
            return format(number.normalize(), 'f')
        except Exception:
            pass
    return value


def _payload_hash(payload) -> str:
    canonical = json.dumps(
        _canonicalize_payload(payload or {}),
        sort_keys=True, separators=(',', ':'), default=str,
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _claim_receipt(*, organization, user, command_kind, idempotency_key, payload,
                   aggregate_type=None, aggregate_public_id=None):
    if not idempotency_key:
        raise ValidationError({'idempotency_key': 'X-Idempotency-Key es obligatorio.'})
    digest = _payload_hash(payload)
    if aggregate_type is None or aggregate_public_id is None:
        for candidate in ('checkout', 'invoice', 'source_pk'):
            if payload.get(candidate) not in (None, ''):
                aggregate_type = aggregate_type or candidate
                aggregate_public_id = aggregate_public_id or payload[candidate]
                break
    aggregate_type = str(aggregate_type or command_kind)[:40]
    aggregate_public_id = str(aggregate_public_id or idempotency_key)[:100]
    existing = CommandReceipt.all_objects.select_for_update().filter(
        organization=organization, command_kind=command_kind,
        idempotency_key=idempotency_key,
    ).first()
    if existing is not None:
        if existing.actor_id != getattr(user, 'pk', None):
            raise ValidationError({'idempotency_key': 'La clave pertenece a otro actor.'})
        if existing.request_hash != digest:
            raise ValidationError({'idempotency_key': 'La clave ya se usó con otro payload.'})
        if existing.status == 'succeeded':
            return existing, True
        raise ValidationError({'idempotency_key': 'El comando con esta clave sigue en proceso.'})
    try:
        with transaction.atomic():
            receipt = CommandReceipt.objects.create(
                organization=organization, command_kind=command_kind,
                idempotency_key=idempotency_key, request_hash=digest,
                aggregate_type=aggregate_type,
                aggregate_public_id=aggregate_public_id,
                actor=user, created_by=user,
            )
        return receipt, False
    except (IntegrityError, ValidationError):
        receipt = CommandReceipt.all_objects.select_for_update().get(
            organization=organization, command_kind=command_kind,
            idempotency_key=idempotency_key,
        )
        if receipt.actor_id != getattr(user, 'pk', None):
            raise ValidationError({'idempotency_key': 'La clave pertenece a otro actor.'})
        if receipt.request_hash != digest:
            raise ValidationError({'idempotency_key': 'La clave ya se usó con otro payload.'})
        if receipt.status == 'succeeded':
            return receipt, True
        raise ValidationError({'idempotency_key': 'El comando con esta clave sigue en proceso.'})


def _complete_receipt(receipt, **response):
    receipt.status = 'succeeded'
    receipt.response_data = response
    receipt.completed_at = timezone.now()
    receipt.save(update_fields=['status', 'response_data', 'completed_at', 'updated_at'])


def _assert_open(checkout, expected_version=None, *, require_version=False):
    if checkout.lifecycle != 'open':
        raise ValidationError('El Checkout ya no está abierto.')
    if require_version and expected_version is None:
        raise ValidationError({'expected_version': 'La versión esperada es obligatoria.'})
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise ValidationError({'expected_version': 'La versión esperada no es válida.'})
        if checkout.version != expected_version:
            raise CheckoutVersionConflict({
                'expected_version': 'El Checkout cambió; vuelve a cargarlo.',
                'current_version': checkout.version,
            })
    if checkout.operational_hold:
        raise ValidationError({'operational_hold': checkout.operational_hold})


def _replay_dispute(receipt):
    dispute_id = receipt.response_data.get('dispute_id')
    if not dispute_id:
        raise ValidationError('El receipt no contiene una disputa reproducible.')
    return CheckoutDispute.all_objects.get(pk=dispute_id)


@transaction.atomic
def open_checkout_dispute(checkout, user, *, item_ids, statement, owner,
                          review_due_at, evidence=None, expected_version=None,
                          idempotency_key):
    item_ids = sorted({int(pk) for pk in item_ids or []})
    payload = {
        'checkout': str(checkout.public_id), 'item_ids': item_ids,
        'statement': statement, 'owner': getattr(owner, 'pk', owner),
        'review_due_at': str(review_due_at), 'evidence': evidence or {},
        'expected_version': expected_version,
    }
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user,
        command_kind='open_checkout_dispute', idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay:
        return _replay_dispute(receipt)
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if not statement or not str(statement).strip():
        raise ValidationError({'statement': 'Describe el cargo o importe disputado.'})
    if not item_ids:
        raise ValidationError({'item_ids': 'Selecciona al menos una línea disputada.'})
    if getattr(owner, 'organization_id', None) != checkout.organization_id:
        raise ValidationError({'owner': 'El responsable debe pertenecer a la organización.'})
    if isinstance(review_due_at, str):
        review_due_at = parse_datetime(review_due_at)
    if review_due_at is None or review_due_at <= timezone.now():
        raise ValidationError({'review_due_at': 'La revisión debe vencer en el futuro.'})
    items = list(CheckoutItem.all_objects.select_for_update().filter(
        checkout=checkout, pk__in=item_ids, is_active=True,
    ).order_by('pk'))
    if len(items) != len(item_ids):
        raise ValidationError({'item_ids': 'Una o más líneas no pertenecen al Checkout.'})
    disputed_amount = sum((item.subtotal for item in items), Decimal('0.00'))
    if disputed_amount <= 0:
        raise ValidationError('La exposición disputada debe ser mayor a cero.')
    now = timezone.now()
    dispute = CheckoutDispute.objects.create(
        organization=checkout.organization, checkout=checkout,
        disputed_item_ids=item_ids, disputed_amount=disputed_amount,
        statement=str(statement).strip(), evidence=evidence or {}, owner=owner,
        opened_by=user, opened_at=now, review_due_at=review_due_at,
        created_by=user,
    )
    checkout.operational_hold = 'dispute'
    checkout.version += 1
    checkout.save(update_fields=['operational_hold', 'version', 'updated_at'])
    CheckoutEvent.objects.create(
        organization=checkout.organization, checkout=checkout, kind='dispute_opened',
        before={}, after={'dispute_id': dispute.pk, 'amount': str(disputed_amount)},
        reason_code='customer_dispute', evidence=evidence or {}, actor=user,
        occurred_at=now, created_by=user,
    )
    _complete_receipt(
        receipt, dispute_id=dispute.pk, dispute_public_id=str(dispute.public_id),
        checkout_id=checkout.pk,
    )
    return dispute


@transaction.atomic
def resolve_checkout_dispute(dispute, user, *, resolution, reason,
                             resolution_evidence=None, adjustments=None,
                             due_at=None, obligation_evidence=None,
                             expected_version=None, idempotency_key):
    payload = {
        'dispute': str(dispute.public_id), 'resolution': resolution,
        'reason': reason, 'resolution_evidence': resolution_evidence or {},
        'adjustments': adjustments or [], 'due_at': str(due_at or ''),
        'obligation_evidence': obligation_evidence or {},
        'expected_version': expected_version,
    }
    receipt, replay = _claim_receipt(
        organization=dispute.organization, user=user,
        command_kind='resolve_checkout_dispute', idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay:
        return _replay_dispute(receipt)
    dispute = CheckoutDispute.all_objects.select_for_update().get(pk=dispute.pk)
    checkout = Checkout.all_objects.select_for_update().get(pk=dispute.checkout_id)
    if dispute.status != 'open' or checkout.lifecycle != 'open' or checkout.operational_hold != 'dispute':
        raise ValidationError('La disputa ya no está abierta.')
    if expected_version is not None and checkout.version != int(expected_version):
        raise ValidationError({'expected_version': 'El Checkout cambió; vuelve a cargarlo.'})
    if resolution not in dict(CheckoutDispute.RESOLUTION_CHOICES):
        raise ValidationError({'resolution': 'Resultado de disputa inválido.'})
    if not reason or not str(reason).strip():
        raise ValidationError({'reason': 'La resolución requiere una justificación.'})

    before = {'total': str(checkout.total), 'hold': checkout.operational_hold}
    if resolution == 'adjusted_or_waived':
        adjustment_rows = adjustments or []
        if not adjustment_rows:
            raise ValidationError({'adjustments': 'Indica los ajustes autorizados por línea.'})
        allowed_ids = set(dispute.disputed_item_ids)
        seen = set()
        for row in adjustment_rows:
            item_id = int(row.get('item_id'))
            amount = Decimal(str(row.get('amount', '0')))
            if item_id in seen or item_id not in allowed_ids or amount <= 0:
                raise ValidationError({'adjustments': 'Cada ajuste debe ser positivo, único y disputado.'})
            seen.add(item_id)
            item = CheckoutItem.all_objects.select_for_update().get(
                pk=item_id, checkout=checkout, is_active=True,
            )
            gross = (item.quantity * item.unit_price).quantize(Decimal('0.01'))
            current_discount = gross - item.subtotal
            if current_discount + amount > gross:
                raise ValidationError({'adjustments': f'El ajuste de {item.description} excede su importe.'})
            item.discount_type = 'fixed'
            item.discount_value = current_discount + amount
            item.save(update_fields=['discount_type', 'discount_value', 'subtotal', 'updated_at'])
        checkout.refresh_from_db()

    now = timezone.now()
    dispute.status = 'resolved'
    dispute.resolution = resolution
    dispute.resolution_reason = str(reason).strip()
    dispute.resolution_evidence = resolution_evidence or {}
    dispute.resolved_by = user
    dispute.resolved_at = now
    dispute.save(update_fields=[
        'status', 'resolution', 'resolution_reason', 'resolution_evidence',
        'resolved_by', 'resolved_at', 'updated_at',
    ])
    checkout.operational_hold = ''
    checkout.version += 1
    checkout.save(update_fields=['operational_hold', 'version', 'updated_at'])

    invoice = None
    if resolution == 'adjusted_or_waived' and checkout.total == 0:
        if checkout.kind == 'replacement':
            raise ValidationError('Un replacement en cero requiere waive_replacement_exposure.')
        checkout.lifecycle = 'completed'
        checkout.completion_kind = 'no_charge'
        checkout.completed_at = now
        checkout.version += 1
        checkout.save(update_fields=[
            'lifecycle', 'completion_kind', 'completed_at', 'version', 'updated_at',
        ])
    elif resolution == 'enforced_under_terms':
        evidence_data = obligation_evidence or {}
        if evidence_data.get('basis') != 'preauthorized_terms' or not evidence_data.get('reference'):
            raise ValidationError({'obligation_evidence': 'Se requieren términos preautorizados verificables.'})
        invoice = post_checkout(
            checkout, user, expected_version=checkout.version,
            idempotency_key=f'{idempotency_key}:post', due_at=due_at,
            credit_reason='dispute_enforced_under_terms',
            obligation_evidence=evidence_data,
        )
        dispute.invoice = invoice
        dispute.save(update_fields=['invoice', 'updated_at'])
        CollectionCase.all_objects.filter(invoice=invoice, status='open').update(
            owner=dispute.owner, review_due_at=dispute.review_due_at,
            updated_at=now,
        )

    CheckoutEvent.objects.create(
        organization=checkout.organization, checkout=checkout, kind='dispute_resolved',
        before=before,
        after={'total': str(checkout.total), 'resolution': resolution,
               'invoice_id': getattr(invoice, 'pk', None)},
        reason_code=resolution, evidence=resolution_evidence or {}, actor=user,
        occurred_at=now, created_by=user,
    )
    _complete_receipt(
        receipt, dispute_id=dispute.pk, dispute_public_id=str(dispute.public_id),
        checkout_id=checkout.pk, invoice_id=getattr(invoice, 'pk', None),
    )
    return dispute


@transaction.atomic
def resolve_collection_case(case, user, *, resolution, reason,
                            evidence=None, idempotency_key):
    """Retira una disputa post-emisión; pago/void/replacement la cierran aparte."""
    payload = {
        'collection_case': str(case.public_id), 'resolution': resolution,
        'reason': reason, 'evidence': evidence or {},
    }
    receipt, replay = _claim_receipt(
        organization=case.organization, user=user,
        command_kind='resolve_collection_case', idempotency_key=idempotency_key,
        payload=payload, aggregate_type='collection_case',
        aggregate_public_id=str(case.public_id),
    )
    if replay:
        return CollectionCase.all_objects.get(
            pk=receipt.response_data['collection_case_id'],
        )
    if resolution != 'customer_withdrew':
        raise ValidationError({
            'resolution': 'Usa pay, void o replacement para los demás resultados.',
        })
    if not reason or not str(reason).strip():
        raise ValidationError({'reason': 'La resolución requiere una justificación.'})

    invoice = Invoice.all_objects.select_for_update().get(pk=case.invoice_id)
    case = CollectionCase.all_objects.select_for_update().get(
        pk=case.pk, invoice=invoice,
    )
    if case.status != 'open' or invoice.status != 'posted':
        raise ValidationError('El caso de cobranza ya no está abierto.')
    now = timezone.now()
    case.status = 'resolved'
    case.resolution = resolution
    case.resolved_at = now
    case.save(update_fields=['status', 'resolution', 'resolved_at', 'updated_at'])
    InvoiceAuditLog.objects.create(
        invoice=invoice, previous_status='posted', new_status='posted',
        changed_by=user,
        notes=f'collection:{resolution}: {str(reason).strip()}'[:255],
    )
    _complete_receipt(
        receipt, collection_case_id=case.pk,
        collection_case_public_id=str(case.public_id),
        invoice_id=invoice.pk,
    )
    return case


@transaction.atomic
def adjust_replacement_exposure(checkout, user, *, item_id, amount, reason_code,
                                note, evidence=None, expected_version=None,
                                idempotency_key):
    amount = Decimal(str(amount))
    payload = {
        'checkout': str(checkout.public_id), 'item_id': int(item_id),
        'amount': amount, 'reason_code': reason_code, 'note': note,
        'evidence': evidence or {}, 'expected_version': expected_version,
    }
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user,
        command_kind='adjust_replacement_exposure', idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay:
        return Checkout.all_objects.get(pk=receipt.response_data['checkout_id'])
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if checkout.kind != 'replacement':
        raise ValidationError('Solo un replacement admite ajuste de exposición.')
    if amount <= 0 or not reason_code or not note or not str(note).strip():
        raise ValidationError('El ajuste requiere monto positivo, razón y nota.')
    item = CheckoutItem.all_objects.select_for_update().get(
        pk=item_id, checkout=checkout, is_active=True,
        required_replacement_baseline=True,
    )
    before = {
        'total': str(checkout.total), 'item_id': item.pk,
        'item_subtotal': str(item.subtotal), 'discount_value': str(item.discount_value),
    }
    gross = (item.quantity * item.unit_price).quantize(Decimal('0.01'))
    current_discount = gross - item.subtotal
    if current_discount + amount >= gross or checkout.total - amount <= 0:
        raise ValidationError('El ajuste debe conservar una exposición exigible positiva; usa waiver para cero.')
    item.discount_type = 'fixed'
    item.discount_value = current_discount + amount
    item.save(update_fields=['discount_type', 'discount_value', 'subtotal', 'updated_at'])
    checkout.refresh_from_db()
    CheckoutEvent.objects.create(
        organization=checkout.organization, checkout=checkout,
        kind='replacement_exposure_adjusted', before=before,
        after={
            'total': str(checkout.total), 'item_id': item.pk,
            'item_subtotal': str(item.subtotal), 'discount_value': str(item.discount_value),
        },
        reason_code=str(reason_code)[:50],
        evidence={'note': str(note).strip(), **(evidence or {})},
        actor=user, occurred_at=timezone.now(), created_by=user,
    )
    _complete_receipt(receipt, checkout_id=checkout.pk, checkout_public_id=str(checkout.public_id))
    return checkout


@transaction.atomic
def assign_replacement_owner(checkout, user, *, owner, correction_due_at,
                             reason_code, expected_version=None, idempotency_key):
    payload = {
        'checkout': str(checkout.public_id), 'owner': getattr(owner, 'pk', owner),
        'correction_due_at': str(correction_due_at), 'reason_code': reason_code,
        'expected_version': expected_version,
    }
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user,
        command_kind='assign_replacement_owner', idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay:
        return Checkout.all_objects.get(pk=receipt.response_data['checkout_id'])
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if checkout.kind != 'replacement':
        raise ValidationError('Solo un replacement admite gestión de responsable.')
    if getattr(owner, 'organization_id', None) != checkout.organization_id:
        raise ValidationError({'owner': 'El responsable debe pertenecer a la organización.'})
    if isinstance(correction_due_at, str):
        correction_due_at = parse_datetime(correction_due_at)
    if correction_due_at is None or correction_due_at <= timezone.now():
        raise ValidationError({'correction_due_at': 'El SLA debe vencer en el futuro.'})
    if not reason_code:
        raise ValidationError({'reason_code': 'La reasignación requiere una razón.'})
    before = {
        'owner_id': checkout.owner_id,
        'correction_due_at': str(checkout.correction_due_at or ''),
    }
    checkout.owner = owner
    checkout.correction_due_at = correction_due_at
    checkout.version += 1
    checkout.save(update_fields=['owner', 'correction_due_at', 'version', 'updated_at'])
    CheckoutEvent.objects.create(
        organization=checkout.organization, checkout=checkout,
        kind='replacement_owner_assigned', before=before,
        after={'owner_id': owner.pk, 'correction_due_at': correction_due_at.isoformat()},
        reason_code=str(reason_code)[:50], evidence={}, actor=user,
        occurred_at=timezone.now(), created_by=user,
    )
    _complete_receipt(receipt, checkout_id=checkout.pk, checkout_public_id=str(checkout.public_id))
    return checkout


def _line_fingerprint(item) -> str:
    quantity = format(Decimal(str(item.quantity)).normalize(), 'f')
    raw = '|'.join([
        str(item.organization_id), str(item.pk), str(item.regulatory_revision),
        str(item.presentation_id), quantity,
        format(Decimal(str(item.conversion_factor_snapshot)).normalize(), 'f'),
    ])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _clinical_source(source):
    from apps.medical_records.models import MedicalRecordService
    if isinstance(source, MedicalRecordService):
        return {
            'source_kind': 'service', 'medical_record_service': source,
            'medical_record_product': None, 'medical_record': source.medical_record,
            'description': source.service.name, 'unit_price': source.service.base_price,
        }
    return {
        'source_kind': 'product', 'medical_record_service': None,
        'medical_record_product': source, 'medical_record': source.medical_record,
        'description': str(source.presentation), 'unit_price': source.presentation.sale_price,
    }


def _billing_context(medical_record, user):
    context, _ = MedicalRecordBillingContext.all_objects.get_or_create(
        medical_record=medical_record,
        defaults={
            'organization': medical_record.organization,
            'tax_rate': medical_record.organization.tax_rate,
            'tax_effective_at': timezone.now(),
            'provenance': 'first_billable',
            'created_by': user,
        },
    )
    return context


def record_clinical_charge_delta(source, *, delta, user, mutation_key, reason='clinical_update'):
    """Append a quantity event while preserving the first price of the cycle."""
    delta = Decimal(str(delta))
    if delta == 0:
        raise ValidationError('El cambio de cantidad clínica no puede ser cero.')
    data = _clinical_source(source)
    medical_record = data['medical_record']
    if medical_record.status != 'open':
        raise ValidationError('No se pueden cambiar cargos de una consulta cerrada.')
    if data['source_kind'] == 'product' and source.cost_behavior != 'charge':
        return None
    _billing_context(medical_record, user)
    source_filter = {f"medical_record_{data['source_kind']}": source}
    entry = ClinicalChargeEntry.all_objects.select_for_update().filter(
        lifecycle='active', **source_filter,
    ).first()
    if entry is None:
        if delta < 0:
            raise ValidationError('No existe un ciclo cobrable activo que reducir.')
        prior = ClinicalChargeEntry.all_objects.filter(
            source_kind=data['source_kind'], source_pk=source.pk,
        ).order_by('-cycle_number').first()
        entry = ClinicalChargeEntry.objects.create(
            organization=medical_record.organization,
            medical_record=medical_record,
            medical_record_service=data['medical_record_service'],
            medical_record_product=data['medical_record_product'],
            source_kind=data['source_kind'], source_pk=source.pk,
            cycle_number=(prior.cycle_number + 1 if prior else 1),
            description=data['description'], unit_price=data['unit_price'],
            price_effective_at=timezone.now(), current_quantity=Decimal('0'),
            supersedes_entry=prior if prior and prior.lifecycle == 'closed' else None,
            created_by=user,
        )
    replay = ClinicalChargeQuantityEvent.all_objects.filter(
        entry=entry, mutation_key=mutation_key,
    ).first()
    if replay is not None:
        return entry
    resulting = entry.current_quantity + delta
    if resulting < 0:
        raise ValidationError('La cantidad cobrable clínica no puede quedar negativa.')
    ClinicalChargeQuantityEvent.objects.create(
        organization=entry.organization, entry=entry, delta=delta,
        resulting_quantity=resulting, mutation_key=mutation_key,
        reason=reason, actor=user, occurred_at=timezone.now(), created_by=user,
    )
    entry.current_quantity = resulting
    if resulting == 0:
        entry.lifecycle = 'closed'
        entry.closed_at = timezone.now()
        entry.closed_reason = reason
        entry.save(update_fields=[
            'current_quantity', 'lifecycle', 'closed_at', 'closed_reason', 'updated_at',
        ])
    else:
        entry.save(update_fields=['current_quantity', 'updated_at'])
    return entry


@transaction.atomic
def reprice_clinical_charge(source, user, *, new_unit_price, reason, expected_quantity,
                            idempotency_key):
    """Close the current price cycle and atomically open its priced successor."""
    new_unit_price = Decimal(str(new_unit_price))
    if new_unit_price <= 0:
        raise ValidationError({'new_unit_price': 'El precio debe ser mayor a cero.'})
    data = _clinical_source(source)
    receipt, replay = _claim_receipt(
        organization=data['medical_record'].organization, user=user,
        command_kind='reprice_clinical_charge', idempotency_key=idempotency_key,
        payload={
            'source_kind': data['source_kind'], 'source_pk': source.pk,
            'new_unit_price': str(new_unit_price), 'reason': reason,
            'expected_quantity': str(expected_quantity),
        },
    )
    if replay:
        return ClinicalChargeEntry.all_objects.get(pk=receipt.response_data['entry_id'])
    source_filter = {f"medical_record_{data['source_kind']}": source}
    old = ClinicalChargeEntry.all_objects.select_for_update().get(
        lifecycle='active', **source_filter,
    )
    quantity = Decimal(str(expected_quantity))
    if old.current_quantity != quantity or quantity <= 0:
        raise ValidationError({'expected_quantity': 'La cantidad clínica cambió; recarga.'})
    now = timezone.now()
    ClinicalChargeQuantityEvent.objects.create(
        organization=old.organization, entry=old, delta=-quantity,
        resulting_quantity=Decimal('0'), mutation_key=f'reprice-close:{receipt.pk}',
        reason=reason, actor=user, occurred_at=now, created_by=user,
    )
    old.current_quantity = Decimal('0')
    old.lifecycle = 'closed'
    old.closed_at = now
    old.closed_reason = 'repriced'
    old.save(update_fields=['current_quantity', 'lifecycle', 'closed_at', 'closed_reason', 'updated_at'])
    successor = ClinicalChargeEntry.objects.create(
        organization=old.organization, medical_record=old.medical_record,
        medical_record_service=data['medical_record_service'],
        medical_record_product=data['medical_record_product'],
        source_kind=old.source_kind, source_pk=old.source_pk,
        cycle_number=old.cycle_number + 1, description=old.description,
        unit_price=new_unit_price, price_effective_at=now,
        current_quantity=quantity, supersedes_entry=old, created_by=user,
    )
    ClinicalChargeQuantityEvent.objects.create(
        organization=old.organization, entry=successor, delta=quantity,
        resulting_quantity=quantity, mutation_key=f'reprice-open:{receipt.pk}',
        reason=reason, actor=user, occurred_at=now, created_by=user,
    )
    _complete_receipt(receipt, entry_id=successor.pk)
    return successor


@transaction.atomic
def create_direct_sale_checkout(*, organization, customer, pet, user, notes=''):
    if customer.organization_id != organization.id:
        raise ValidationError({'customer': 'Cliente fuera de la organización.'})
    if pet is not None and (pet.organization_id != organization.id or pet.owner_id != customer.id):
        raise ValidationError({'pet': 'La mascota no pertenece al cliente.'})
    checkout = Checkout(
        organization=organization, origin='direct_sale', kind='direct_sale',
        customer=customer, pet=pet, owner=user, tax_rate=organization.tax_rate,
        notes=notes, created_by=user,
    )
    checkout.full_clean()
    checkout.save()
    return checkout


@transaction.atomic
def add_checkout_item(
    checkout, user, *, service=None, presentation=None,
    quantity=Decimal('1'), lot=None, discount_type=None,
    discount_value=Decimal('0'), rx_attested=False, prescriber_name='',
    prescription_folio='', expected_version=None,
):
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if checkout.kind == 'primary_consultation':
        raise ValidationError('Los cargos clínicos no se agregan manualmente desde Cobros.')
    if bool(service) == bool(presentation):
        raise ValidationError('Selecciona exactamente un servicio o una presentación.')
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise ValidationError({'quantity': 'La cantidad debe ser mayor a cero.'})
    source = service or presentation
    if source.organization_id != checkout.organization_id:
        raise ValidationError('La línea pertenece a otra organización.')
    if presentation is not None:
        quantity = validated_presentation_quantity(quantity)
        presentation = Presentation.objects.select_related('product').select_for_update().get(
            pk=presentation.pk, organization=checkout.organization,
        )
        factor = presentation_conversion_factor(presentation)
        if presentation.product.requires_prescription:
            _assert_rx_dispense_permission(user)
        if presentation.product.tracks_lots:
            if lot is not None:
                lot = StockLot.objects.for_organization(checkout.organization).select_for_update().filter(
                    pk=lot.pk, product=presentation.product,
                ).first()
                if lot is None or not lot.is_consumable:
                    raise ValidationError({'lot': 'Selecciona un lote disponible.'})
        elif lot is not None:
            raise ValidationError({'lot': 'Este producto no usa lotes.'})
        existing = CheckoutItem.all_objects.select_for_update().filter(
            checkout=checkout, presentation=presentation,
            source_kind='direct_sale_product', is_active=True,
        ).first()
        if existing:
            if existing.conversion_factor_snapshot != factor:
                raise ValidationError({
                    'presentation': (
                        'El factor comercial cambió después de abrir la línea; '
                        'retírala y agrégala de nuevo para aceptar el contrato nuevo.'
                    )
                })
            if existing.lot_id != getattr(lot, 'pk', None):
                raise ValidationError({
                    'lot': 'No se pueden mezclar lotes explícitos en una misma línea.'
                })
            existing.quantity += quantity
            existing.regulatory_revision += 1
            existing.save()
            item = existing
        else:
            item = CheckoutItem.objects.create(
                organization=checkout.organization, checkout=checkout,
                presentation=presentation, lot=lot, description=str(presentation),
                conversion_factor_snapshot=factor,
                quantity=quantity, unit_price=presentation.sale_price,
                source_kind='direct_sale_product', discount_type=discount_type,
                discount_value=discount_value, rx_attested=bool(rx_attested),
                prescriber_name=prescriber_name, prescription_folio=prescription_folio,
                created_by=user,
            )
        if presentation.product.requires_prescription:
            if not rx_attested or not prescriber_name.strip():
                raise ValidationError({'rx_attested': 'El producto requiere receta externa válida.'})
            ExternalPrescriptionAttestation.objects.create(
                organization=checkout.organization, checkout_item=item,
                presentation=presentation, quantity=item.quantity,
                regulatory_revision=item.regulatory_revision,
                line_fingerprint=_line_fingerprint(item), attested_by=user,
                prescriber_name=prescriber_name.strip(),
                prescription_folio=prescription_folio.strip(), created_by=user,
            )
    else:
        item = CheckoutItem.objects.create(
            organization=checkout.organization, checkout=checkout, service=service,
            description=service.name, quantity=quantity, unit_price=service.base_price,
            source_kind='direct_sale_service', discount_type=discount_type,
            discount_value=discount_value, created_by=user,
        )
    return item


@transaction.atomic
def attest_external_prescription(
    item, user, *, prescriber_name, prescription_folio='', notes='',
    correction_reason='', expected_version=None, idempotency_key,
):
    """Registra evidencia Rx append-only para la revisión exacta de una línea."""
    checkout_ref = item.checkout
    payload = {
        'checkout': str(checkout_ref.public_id), 'item': item.pk,
        'prescriber_name': prescriber_name, 'prescription_folio': prescription_folio,
        'notes': notes, 'correction_reason': correction_reason,
        'expected_version': expected_version,
    }
    receipt, replay = _claim_receipt(
        organization=checkout_ref.organization, user=user,
        command_kind='attest_external_prescription',
        idempotency_key=idempotency_key, payload=payload,
        aggregate_type='checkout', aggregate_public_id=str(checkout_ref.public_id),
    )
    if replay:
        return ExternalPrescriptionAttestation.all_objects.get(
            pk=receipt.response_data['attestation_id'],
        )

    checkout = Checkout.all_objects.select_for_update().get(pk=item.checkout_id)
    _assert_open(checkout, expected_version)
    item = CheckoutItem.all_objects.select_related(
        'presentation__product',
    ).select_for_update(of=('self',)).get(
        pk=item.pk, checkout=checkout, is_active=True,
    )
    if checkout.kind != 'direct_sale' or item.prescription_item_id:
        raise ValidationError('La atestación externa solo aplica a venta directa.')
    if not item.presentation_id or not item.presentation.product.requires_prescription:
        raise ValidationError('La línea no requiere receta externa.')
    prescriber_name = (prescriber_name or '').strip()
    if not prescriber_name:
        raise ValidationError({'prescriber_name': 'Indica el prescriptor.'})

    fingerprint = _line_fingerprint(item)
    prior = ExternalPrescriptionAttestation.all_objects.select_for_update().filter(
        checkout_item=item, regulatory_revision=item.regulatory_revision,
        line_fingerprint=fingerprint,
    ).order_by('-attested_at', '-pk').first()
    if prior is not None:
        if not correction_reason:
            raise ValidationError({'correction_reason': 'La corrección requiere una razón.'})
        CheckoutItem.all_objects.filter(pk=item.pk).update(
            regulatory_revision=F('regulatory_revision') + 1,
        )
        item.refresh_from_db(fields=['regulatory_revision'])
        fingerprint = _line_fingerprint(item)

    attestation = ExternalPrescriptionAttestation.objects.create(
        organization=checkout.organization, checkout_item=item,
        presentation=item.presentation, quantity=item.quantity,
        regulatory_revision=item.regulatory_revision,
        line_fingerprint=fingerprint, attested_by=user,
        prescriber_name=prescriber_name[:255],
        prescription_folio=(prescription_folio or '').strip()[:100],
        notes=(notes or '')[:1000], supersedes_attestation=prior,
        correction_reason=(correction_reason or '')[:100], created_by=user,
    )
    Checkout.all_objects.filter(pk=checkout.pk).update(
        version=F('version') + 1, updated_at=timezone.now(),
    )
    _complete_receipt(
        receipt, attestation_id=attestation.pk,
        attestation_public_id=str(attestation.public_id),
        regulatory_revision=attestation.regulatory_revision,
    )
    return attestation


@transaction.atomic
def update_checkout_item(item, user, *, quantity=None, expected_version=None):
    checkout = Checkout.all_objects.select_for_update().get(pk=item.checkout_id)
    _assert_open(checkout, expected_version)
    item = CheckoutItem.all_objects.select_related(
        'presentation__product',
    ).select_for_update(of=('self',)).get(pk=item.pk, checkout=checkout)
    if item.required_replacement_baseline or item.source_kind.startswith('clinical_'):
        raise ValidationError('La línea baseline solo cambia mediante ajuste de exposición.')
    if item.prescription_item_id or (
        item.presentation_id and item.presentation.product.requires_prescription
    ):
        _assert_rx_dispense_permission(user)
    if quantity is not None:
        quantity = (
            validated_presentation_quantity(quantity)
            if item.presentation_id else Decimal(str(quantity))
        )
        if quantity <= 0:
            raise ValidationError({'quantity': 'La cantidad debe ser mayor a cero.'})
        if item.presentation_id:
            if item.conversion_factor_snapshot is None:
                raise ValidationError('La línea no conserva su factor de conversión.')
        if quantity != item.quantity and item.presentation_id:
            item.regulatory_revision += 1
        item.quantity = quantity
    item.updated_by = user
    item.save()
    return item


@transaction.atomic
def delete_checkout_item(item, user, *, expected_version=None):
    checkout = Checkout.all_objects.select_for_update().get(pk=item.checkout_id)
    _assert_open(checkout, expected_version)
    item = CheckoutItem.all_objects.select_related(
        'presentation__product',
    ).select_for_update(of=('self',)).get(pk=item.pk, checkout=checkout)
    if item.required_replacement_baseline or item.source_kind.startswith('clinical_'):
        raise ValidationError('No se puede eliminar valor ya entregado del replacement.')
    if item.prescription_item_id or (
        item.presentation_id and item.presentation.product.requires_prescription
    ):
        _assert_rx_dispense_permission(user)
    item.delete()


@transaction.atomic
def get_or_create_primary_checkout_for_medical_record(medical_record, *, owner=None):
    """Materializa una sola preparación comercial al cerrar la consulta."""
    context = MedicalRecordBillingContext.all_objects.filter(
        medical_record=medical_record,
    ).first()
    checkout = Checkout.all_objects.select_for_update().filter(
        organization=medical_record.organization, medical_record=medical_record,
        kind='primary_consultation',
    ).first()
    if checkout is None:
        checkout = Checkout.objects.create(
            organization=medical_record.organization, medical_record=medical_record,
            origin='consultation', kind='primary_consultation', owner=owner,
            customer=medical_record.pet.owner, pet=medical_record.pet,
            tax_rate=(context.tax_rate if context else medical_record.organization.tax_rate),
            created_by=owner,
        )
    if checkout.lifecycle != 'open':
        return checkout
    entries = list(
        ClinicalChargeEntry.all_objects.select_for_update(of=('self',))
        .select_related('medical_record_service__service', 'medical_record_product__presentation__product')
        .filter(medical_record=medical_record, lifecycle='active', current_quantity__gt=0)
        .order_by('pk')
    )
    if entries and context is None:
        raise ValidationError('Falta el contexto tributario de los cargos clínicos.')
    for entry in entries:
        snapshot, _ = ClinicalChargeSnapshot.all_objects.get_or_create(
            entry=entry,
            defaults={
                'organization': entry.organization, 'billing_context': context,
                'description': entry.description, 'quantity': entry.current_quantity,
                'unit_price': entry.unit_price, 'currency': entry.currency,
                'snapshotted_at': timezone.now(), 'created_by': owner,
            },
        )
        CheckoutItem.all_objects.get_or_create(
            checkout=checkout, clinical_charge_snapshot=snapshot,
            defaults={
                'organization': checkout.organization,
                'service': (
                    entry.medical_record_service.service
                    if entry.medical_record_service_id else None
                ),
                'presentation': (
                    entry.medical_record_product.presentation
                    if entry.medical_record_product_id else None
                ),
                'conversion_factor_snapshot': (
                    entry.medical_record_product.conversion_factor_snapshot
                    if entry.medical_record_product_id else None
                ),
                'lot': (
                    entry.medical_record_product.lot
                    if entry.medical_record_product_id else None
                ),
                'medical_record_service': entry.medical_record_service,
                'medical_record_product': entry.medical_record_product,
                'description': snapshot.description, 'quantity': snapshot.quantity,
                'unit_price': snapshot.unit_price,
                'source_kind': (
                    'clinical_service' if entry.source_kind == 'service'
                    else 'clinical_consumable'
                ),
                'fulfillment_source': (
                    'new' if entry.source_kind == 'service' else 'already_fulfilled'
                ),
                'created_by': owner,
            },
        )
    prescription = getattr(medical_record, 'prescription', None)
    if prescription is not None:
        for rx_item in prescription.items.all():
            fulfilled = PrescriptionFulfillmentEvent.all_objects.filter(
                prescription_item=rx_item,
            ).aggregate(total=Sum('quantity_delta'))['total'] or Decimal('0')
            CheckoutPrescriptionSelection.all_objects.get_or_create(
                checkout=checkout, prescription_item=rx_item,
                defaults={
                    'organization': checkout.organization,
                    'eligible_remaining_at_open': max(rx_item.quantity - fulfilled, Decimal('0')),
                    'created_by': owner,
                },
            )
    return Checkout.all_objects.get(pk=checkout.pk)


@transaction.atomic
def create_prescription_supplement(medical_record, user, *, idempotency_key):
    """Abre un Checkout nuevo solo por el remanente dispensable de una receta."""
    receipt, replay = _claim_receipt(
        organization=medical_record.organization, user=user,
        command_kind='create_prescription_supplement',
        idempotency_key=idempotency_key,
        payload={'medical_record': str(medical_record.public_id)},
        aggregate_type='medical_record',
        aggregate_public_id=str(medical_record.public_id),
    )
    if replay:
        return Checkout.all_objects.get(pk=receipt.response_data['checkout_id'])

    from apps.medical_records.models import MedicalRecord
    from apps.prescriptions.models import Prescription

    medical_record = MedicalRecord.objects.select_for_update().get(pk=medical_record.pk)
    if medical_record.status != MedicalRecord.Status.CLOSED:
        raise ValidationError('La consulta debe estar cerrada para crear un suplemento.')
    prescription = Prescription.objects.select_for_update().filter(
        medical_record=medical_record, organization=medical_record.organization,
    ).first()
    if prescription is None:
        raise ValidationError('La consulta no tiene una receta interna.')
    primary = Checkout.all_objects.select_for_update().filter(
        medical_record=medical_record, kind='primary_consultation',
    ).first()
    if primary is None or primary.lifecycle == 'open':
        raise ValidationError('Finaliza primero el Checkout primario de la consulta.')
    if Checkout.all_objects.select_for_update().filter(
        medical_record=medical_record, kind='prescription_supplement', lifecycle='open',
    ).exists():
        raise ValidationError('Ya existe un suplemento de receta abierto para la consulta.')

    rx_items = list(prescription.items.select_for_update().order_by('pk'))
    remaining = []
    for rx_item in rx_items:
        fulfilled = PrescriptionFulfillmentEvent.all_objects.filter(
            prescription_item=rx_item,
        ).aggregate(total=Sum('quantity_delta'))['total'] or Decimal('0')
        available = max(rx_item.quantity - fulfilled, Decimal('0'))
        if available > 0:
            remaining.append((rx_item, available))
    if not remaining:
        raise ValidationError('La receta no tiene cantidad pendiente por dispensar.')

    context = MedicalRecordBillingContext.all_objects.filter(
        medical_record=medical_record,
    ).first()
    checkout = Checkout.objects.create(
        organization=medical_record.organization, medical_record=medical_record,
        origin='consultation', kind='prescription_supplement', owner=user,
        customer=medical_record.pet.owner, pet=medical_record.pet,
        tax_rate=(context.tax_rate if context else medical_record.organization.tax_rate),
        created_by=user,
    )
    CheckoutPrescriptionSelection.objects.bulk_create([
        CheckoutPrescriptionSelection(
            organization=checkout.organization, checkout=checkout,
            prescription_item=rx_item, eligible_remaining_at_open=available,
            created_by=user,
        )
        for rx_item, available in remaining
    ])
    _complete_receipt(
        receipt, checkout_id=checkout.pk,
        checkout_public_id=str(checkout.public_id), result='created',
    )
    return checkout


@transaction.atomic
def decide_prescription_item(checkout, prescription_item, user, *, decision,
                             decline_reason='', expected_version=None):
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if decision not in {'pending', 'declined'}:
        raise ValidationError({'decision': 'Usa dispensar para aceptar; aquí solo puedes rechazar o reabrir.'})
    selection = CheckoutPrescriptionSelection.all_objects.select_for_update().get(
        checkout=checkout, prescription_item=prescription_item,
    )
    if decision == 'declined' and checkout.items.filter(
        prescription_item=prescription_item, is_active=True,
    ).exists():
        raise ValidationError('Elimina primero las líneas seleccionadas de este medicamento.')
    selection.decision = decision
    selection.decline_reason = (decline_reason or '')[:30] if decision == 'declined' else ''
    selection.decided_at = timezone.now() if decision == 'declined' else None
    selection.decided_by = user if decision == 'declined' else None
    selection.save(update_fields=[
        'decision', 'decline_reason', 'decided_at', 'decided_by', 'updated_at',
    ])
    checkout.version += 1
    checkout.save(update_fields=['version', 'updated_at'])
    return selection


@transaction.atomic
def dispense_prescription_into_checkout(
    prescription, lines, user, *, expected_version, idempotency_key,
):
    if not prescription.medical_record_id:
        raise ValidationError('La receta no está ligada a una consulta.')
    _assert_rx_dispense_permission(user)
    checkout = Checkout.all_objects.select_for_update().filter(
        organization=prescription.organization,
        medical_record_id=prescription.medical_record_id,
        kind__in=('primary_consultation', 'prescription_supplement', 'replacement'),
        lifecycle='open',
    ).order_by('-pk').first()
    if checkout is None:
        raise ValidationError('La consulta debe estar cerrada y disponible en Cobros.')
    payload = {
        'checkout': str(checkout.public_id),
        'prescription': str(prescription.public_id),
        'expected_version': expected_version,
        'lines': lines,
    }
    receipt, replay = _claim_receipt(
        organization=checkout.organization,
        user=user,
        command_kind='dispense_prescription',
        idempotency_key=idempotency_key,
        payload=payload,
        aggregate_type='checkout',
        aggregate_public_id=str(checkout.public_id),
    )
    if replay:
        return Checkout.all_objects.get(pk=receipt.response_data['checkout_id'])
    _assert_open(checkout, expected_version, require_version=True)
    rx_items = {item.pk: item for item in prescription.items.select_related('product')}
    if not lines:
        raise ValidationError('Selecciona al menos un producto a dispensar.')
    for line in lines:
        quantity = validated_presentation_quantity(line['quantity'])
        presentation = Presentation.objects.select_related('product').select_for_update().filter(
            pk=line['presentation_id'], organization=checkout.organization, is_active=True,
        ).first()
        if presentation is None:
            raise ValidationError({'presentation': 'La presentación no está disponible.'})
        factor = presentation_conversion_factor(presentation)
        quantity_base = presentation_quantity_to_base(quantity, factor)
        rx_item = rx_items.get(line.get('prescription_item_id'))
        if rx_item is None or rx_item.product_id != presentation.product_id:
            raise ValidationError('La presentación no corresponde al medicamento recetado.')
        selection = CheckoutPrescriptionSelection.all_objects.select_for_update().filter(
            checkout=checkout, prescription_item=rx_item,
        ).first()
        if selection is None:
            fulfilled_at_open = PrescriptionFulfillmentEvent.all_objects.filter(
                prescription_item=rx_item,
            ).aggregate(total=Sum('quantity_delta'))['total'] or Decimal('0')
            selection = CheckoutPrescriptionSelection.objects.create(
                organization=checkout.organization, checkout=checkout,
                prescription_item=rx_item,
                eligible_remaining_at_open=max(rx_item.quantity - fulfilled_at_open, Decimal('0')),
                created_by=user,
            )

        suggestion = next(
            row for row in build_checkout_prescription_suggestions(checkout)
            if row['prescription_item_id'] == rx_item.pk
        )
        presentation_availability = next(
            row for row in suggestion['presentations']
            if row['id'] == presentation.pk
        )
        if quantity > presentation_availability['max_selectable_quantity']:
            reasons = ', '.join(presentation_availability['blocking_reasons'])
            raise ValidationError({
                'quantity': (
                    f"La cantidad de {presentation.product.name} excede el máximo "
                    f"seleccionable ({presentation_availability['max_selectable_quantity']})."
                ),
                'blocking_reasons': reasons,
            })

        lot = None
        if presentation.product.tracks_lots:
            lot_id = line.get('lot_id')
            lot = StockLot.objects.for_organization(checkout.organization).select_for_update().filter(
                pk=lot_id, product=presentation.product,
            ).first() if lot_id else None
            if lot_id and (lot is None or not lot.is_consumable):
                raise ValidationError('El lote seleccionado no está disponible para dispensar.')
            if lot is not None and Decimal(lot.quantity_on_hand) < quantity_base:
                raise ValidationError('El lote seleccionado no cubre la cantidad solicitada.')
        CheckoutItem.objects.create(
            organization=checkout.organization, checkout=checkout,
            presentation=presentation, lot=lot, prescription_item=rx_item,
            conversion_factor_snapshot=factor,
            description=str(presentation), quantity=quantity,
            unit_price=presentation.sale_price, source_kind='prescription_retail',
            fulfillment_source=('redelivery' if checkout.kind == 'replacement' else 'new'),
            created_by=user,
        )
        selection.decision = 'accepted'
        selection.decided_at = timezone.now()
        selection.decided_by = user
        selection.decline_reason = ''
        selection.save(update_fields=[
            'decision', 'decided_at', 'decided_by', 'decline_reason', 'updated_at',
        ])
    checkout = Checkout.all_objects.get(pk=checkout.pk)
    _complete_receipt(
        receipt,
        checkout_id=checkout.pk,
        checkout_public_id=str(checkout.public_id),
        checkout_version=checkout.version,
    )
    return checkout


def _current_attestation(item):
    if not item.presentation_id or not item.presentation.product.requires_prescription:
        return None
    if item.prescription_item_id:
        return None
    attestation = item.rx_attestations.filter(
        regulatory_revision=item.regulatory_revision,
        line_fingerprint=_line_fingerprint(item),
    ).order_by('-attested_at').first()
    if attestation is None:
        raise ValidationError(f"'{item.description}' requiere una atestación externa vigente.")
    return attestation


def checkout_readiness_snapshot(checkout):
    """Proyección de lectura; nunca sustituye la revalidación del comando final."""
    now = timezone.now()
    items = list(
        checkout.items.filter(is_active=True)
        .select_related(
            'service', 'presentation__product', 'lot', 'prescription_item',
            'clinical_charge_snapshot', 'source_invoice_item',
        )
        .prefetch_related('rx_attestations')
        .order_by('pk')
    )
    selections = list(checkout.prescription_selections.all())
    disputes = list(checkout.disputes.all())

    def blocker(code, message):
        return {'code': code, 'message': message}

    structural = []
    if checkout.lifecycle != 'open':
        structural.append(blocker('checkout_not_open', 'El Checkout ya no está abierto.'))
    if not checkout.customer_id:
        structural.append(blocker('customer_missing', 'Falta el cliente.'))
    elif checkout.customer.organization_id != checkout.organization_id:
        structural.append(blocker('customer_inconsistent', 'El cliente pertenece a otra organización.'))
    if checkout.pet_id and (
        checkout.pet.organization_id != checkout.organization_id
        or checkout.pet.owner_id != checkout.customer_id
    ):
        structural.append(blocker('pet_inconsistent', 'La mascota no corresponde al cliente.'))
    if checkout.origin == 'consultation':
        if not checkout.medical_record_id or checkout.medical_record.status != 'closed':
            structural.append(blocker(
                'medical_record_not_closed', 'La consulta clínica no está cerrada.',
            ))
    elif checkout.origin == 'direct_sale' and not items:
        structural.append(blocker('empty_checkout', 'La venta directa no tiene líneas.'))

    active_rx_ids = {item.prescription_item_id for item in items if item.prescription_item_id}
    for selection in selections:
        if selection.decision == 'pending':
            structural.append(blocker(
                'prescription_selection_pending',
                'Hay medicamentos recetados pendientes de aceptar o rechazar.',
            ))
            break
    if any(
        selection.decision == 'accepted'
        and selection.prescription_item_id not in active_rx_ids
        for selection in selections
    ):
        structural.append(blocker(
            'accepted_prescription_without_item',
            'Una selección aceptada ya no tiene una línea activa.',
        ))

    missing_external_rx = False
    for item in items:
        if item.quantity <= 0 or item.unit_price < 0 or item.subtotal < 0:
            structural.append(blocker(
                'invalid_item_amount', 'Existe una línea con cantidad o importe inválido.',
            ))
            break
        if item.source_kind.startswith('clinical_') and not item.clinical_charge_snapshot_id:
            structural.append(blocker(
                'clinical_snapshot_missing', 'Un cargo clínico no tiene snapshot de cierre.',
            ))
            break
    for item in items:
        if (
            item.presentation_id
            and item.presentation.product.requires_prescription
            and not item.prescription_item_id
        ):
            fingerprint = _line_fingerprint(item)
            if not any(
                attestation.regulatory_revision == item.regulatory_revision
                and attestation.line_fingerprint == fingerprint
                for attestation in item.rx_attestations.all()
            ):
                missing_external_rx = True
                structural.append(blocker(
                    'external_rx_attestation_missing',
                    f"'{item.description}' requiere una atestación externa vigente.",
                ))

    expected_subtotal, expected_tax, expected_total = invoice_totals(
        sum((item.subtotal for item in items), Decimal('0.00')),
        checkout.tax_rate,
    )
    if (
        checkout.subtotal != expected_subtotal
        or checkout.tax_amount != expected_tax
        or checkout.total != expected_total
        or checkout.total < 0
    ):
        structural.append(blocker(
            'totals_inconsistent', 'Los totales no coinciden con las líneas activas.',
        ))

    if checkout.kind == 'replacement':
        baseline = [item for item in items if item.required_replacement_baseline]
        if not baseline or any(not item.source_invoice_item_id for item in baseline):
            structural.append(blocker(
                'replacement_baseline_invalid', 'El replacement no conserva su baseline obligatorio.',
            ))
        if not checkout.replaces_invoice_id:
            structural.append(blocker(
                'replacement_lineage_missing', 'Falta la factura origen del replacement.',
            ))
        if not checkout.owner_id or not checkout.correction_due_at:
            structural.append(blocker(
                'replacement_assignment_missing', 'Faltan responsable o SLA de corrección.',
            ))

    # Evita repetir el mismo blocker por varias líneas/selecciones sin perder
    # el primer mensaje explicativo estable.
    unique = {}
    for row in structural:
        unique.setdefault(row['code'], row)
    structural = list(unique.values())

    def required(name, schema, reason):
        return {'name': name, 'schema': schema, 'reason': reason}

    def action(blockers, required_inputs):
        deduped = {}
        for row in blockers:
            deduped.setdefault(row['code'], row)
        rows = list(deduped.values())
        return {
            'allowed': not rows,
            'blockers': rows,
            'required_inputs': required_inputs,
        }

    positive_total = [] if checkout.total > 0 else [blocker(
        'positive_total_required', 'La emisión financiera requiere total mayor a cero.',
    )]
    dispute_block = []
    if checkout.operational_hold == 'dispute' or any(
        dispute.status == 'open' for dispute in disputes
    ):
        dispute_block = [blocker('open_dispute', 'Resuelve la disputa antes de emitir o cobrar.')]

    from apps.organizations.utils import get_org_setting
    credit_block = [] if get_org_setting(
        checkout.organization, 'allow_post_unpaid',
    ) else [blocker('credit_disabled', 'La organización no permite dejar cobros pendientes.')]
    replacement_resolution = [blocker(
        'replacement_requires_resolution',
        'Un replacement solo termina con una nueva factura o un waiver autorizado.',
    )] if checkout.kind == 'replacement' else []
    consultation_abandon = [blocker(
        'consultation_cannot_abandon',
        'Un Checkout clínico debe emitirse o resolverse sin cargo.',
    )] if checkout.origin == 'consultation' else []

    open_only = [] if checkout.lifecycle == 'open' else [blocker(
        'checkout_not_open', 'El Checkout ya no está abierto.',
    )]
    attestation_base = [
        row for row in structural if row['code'] != 'external_rx_attestation_missing'
    ]
    actions = {
        'pay': action(structural + positive_total + dispute_block, [
            required('payment_lines', 'array<PaymentLine>', 'Define cómo se recibe el total.'),
            required('expected_version', 'integer', 'Evita cobrar una versión desactualizada.'),
            required('idempotency_key', 'string', 'Evita mover dinero dos veces.'),
        ]),
        'post_unpaid': action(structural + positive_total + dispute_block + credit_block, [
            required('due_at', 'datetime', 'Define el vencimiento de la deuda.'),
            required('credit_reason', 'string', 'Justifica la excepción de crédito.'),
            required('obligation_evidence', 'object', 'Prueba aceptación o términos.'),
            required('expected_version', 'integer', 'Evita emitir una versión desactualizada.'),
            required('idempotency_key', 'string', 'Evita emitir dos veces.'),
        ]),
        'complete_no_charge': action(
            structural
            + ([] if checkout.total == 0 else [blocker(
                'zero_total_required', 'Solo un Checkout en cero termina sin factura.',
            )])
            + replacement_resolution,
            [required('reason', 'string', 'Explica por qué no existe cargo.')],
        ),
        'abandon': action(open_only + replacement_resolution + consultation_abandon, [
            required('reason', 'string', 'Registra la causa del abandono.'),
        ]),
        'open_dispute': action(
            open_only
            + ([] if checkout.origin == 'consultation' else [blocker(
                'consultation_required', 'La disputa clínica requiere una consulta.',
            )])
            + ([] if checkout.total > 0 else positive_total)
            + dispute_block,
            [
                required('item_ids', 'array<integer>', 'Identifica los cargos disputados.'),
                required('statement', 'string', 'Registra la declaración del cliente.'),
                required('owner', 'user', 'Asigna responsable y SLA.'),
            ],
        ),
        'attest_external_rx': action(
            attestation_base
            + ([] if missing_external_rx else [blocker(
                'no_external_rx_pending', 'No hay una línea regulada pendiente de atestar.',
            )]),
            [
                required('item', 'integer', 'Liga la evidencia a la revisión exacta.'),
                required('prescriber_name', 'string', 'Identifica al prescriptor externo.'),
                required('idempotency_key', 'string', 'Evita duplicar la evidencia.'),
            ],
        ),
        'adjust_replacement': action(
            open_only + ([] if checkout.kind == 'replacement' else [blocker(
                'replacement_required', 'La acción solo aplica a replacements.',
            )]),
            [
                required('amount', 'decimal', 'Define el ajuste sin eliminar el baseline.'),
                required('reason_code', 'string', 'Justifica el ajuste.'),
                required('evidence', 'object', 'Conserva evidencia de la corrección.'),
            ],
        ),
        'waive_replacement': action(
            open_only + ([] if checkout.kind == 'replacement' else [blocker(
                'replacement_required', 'La acción solo aplica a replacements.',
            )]),
            [
                required('reason_code', 'string', 'Justifica la condonación.'),
                required('evidence', 'object', 'Conserva la autorización.'),
            ],
        ),
    }
    return {
        'preparation_readiness': {
            'ready': not structural,
            'blockers': structural,
            'checkout_version': checkout.version,
            'evaluated_at': now,
        },
        'actions': actions,
    }


def _assert_prescription_resolved(checkout, items):
    pending = checkout.prescription_selections.filter(decision='pending')
    if pending.exists():
        raise ValidationError('Resuelve cada medicamento recetado como aceptado o rechazado.')
    selected_ids = {item.prescription_item_id for item in items if item.prescription_item_id}
    invalid = checkout.prescription_selections.filter(decision='accepted').exclude(
        prescription_item_id__in=selected_ids,
    )
    if invalid.exists():
        raise ValidationError('Una selección aceptada debe conservar al menos una línea de producto.')


def _assert_prescription_fulfillment_cap(checkout, items):
    """Revalida el remanente Rx al postear, no solo al preparar la selección."""
    grouped = {}
    for item in items:
        if not item.prescription_item_id or item.fulfillment_source == 'already_fulfilled':
            continue
        grouped[item.prescription_item_id] = grouped.get(
            item.prescription_item_id, Decimal('0'),
        ) + presentation_quantity_to_base(
            item.quantity, item.conversion_factor_snapshot,
        )
    if not grouped:
        return

    from apps.prescriptions.models import PrescriptionItem
    rx_items = {
        row.pk: row
        for row in PrescriptionItem.objects.select_for_update().filter(
            pk__in=sorted(grouped), organization=checkout.organization,
        ).order_by('pk')
    }
    if len(rx_items) != len(grouped):
        raise ValidationError('Una línea de receta ya no está disponible.')
    for rx_id, requested in grouped.items():
        fulfilled = PrescriptionFulfillmentEvent.all_objects.filter(
            prescription_item_id=rx_id,
        ).aggregate(total=Sum('quantity_delta'))['total'] or Decimal('0')
        neutral_allowance = Decimal('0')
        if checkout.kind == 'replacement':
            returned = PrescriptionFulfillmentEvent.all_objects.filter(
                prescription_item_id=rx_id, kind='returned',
            ).aggregate(total=Sum('physical_quantity'))['total'] or Decimal('0')
            redelivered = PrescriptionFulfillmentEvent.all_objects.filter(
                prescription_item_id=rx_id, kind='redelivered',
            ).aggregate(total=Sum('physical_quantity'))['total'] or Decimal('0')
            neutral_allowance = max(returned - redelivered, Decimal('0'))
        if fulfilled + requested > rx_items[rx_id].quantity + neutral_allowance:
            raise ValidationError('La selección excede el remanente vigente de la receta.')


def _settle_stock(checkout, invoice, invoice_items, user):
    now = timezone.now()
    for checkout_item, invoice_item in invoice_items:
        if not checkout_item.presentation_id or checkout_item.fulfillment_source == 'already_fulfilled':
            continue
        presentation = Presentation.objects.select_related('product').select_for_update().get(
            pk=checkout_item.presentation_id,
        )
        quantity_base = presentation_quantity_to_base(
            checkout_item.quantity, checkout_item.conversion_factor_snapshot,
        ).quantize(Decimal('0.0001'))
        committed = consume_product(
            presentation=presentation, quantity_base=quantity_base,
            organization=checkout.organization, lot=checkout_item.lot,
            reason=f'Entrega al emitir factura #{invoice.pk}', created_by=user,
            invoice=invoice,
        )
        allocations = []
        for _movement, committed_lot, committed_quantity in committed:
            allocation = StockAllocation.objects.create(
                organization=checkout.organization, invoice_item=invoice_item,
                checkout_item=checkout_item, presentation=presentation,
                lot=committed_lot, quantity_base=committed_quantity,
                allocated_at=now, created_by=user,
            )
            StockDispositionEvent.objects.create(
                organization=checkout.organization, allocation=allocation,
                kind='delivered', quantity_base=committed_quantity,
                stock_delta=-committed_quantity, custody='customer', occurred_at=now,
                created_by=user,
            )
            allocations.append(allocation)
        if not allocations or sum(
            (row.quantity_base for row in allocations), Decimal('0')
        ) != quantity_base:
            raise ValidationError('La asignación física no coincide con la cantidad facturada.')
        # El evento Rx representa la entrega legal de la línea completa. Las
        # asignaciones individuales conservan el detalle físico multi-lote.
        allocation = allocations[0]
        if checkout_item.prescription_item_id:
            fulfilled = PrescriptionFulfillmentEvent.all_objects.filter(
                prescription_item_id=checkout_item.prescription_item_id,
            ).aggregate(total=Sum('quantity_delta'))['total'] or Decimal('0')
            returned = PrescriptionFulfillmentEvent.all_objects.filter(
                prescription_item_id=checkout_item.prescription_item_id, kind='returned',
            ).aggregate(total=Sum('physical_quantity'))['total'] or Decimal('0')
            redelivered = PrescriptionFulfillmentEvent.all_objects.filter(
                prescription_item_id=checkout_item.prescription_item_id, kind='redelivered',
            ).aggregate(total=Sum('physical_quantity'))['total'] or Decimal('0')
            neutral_available = max(returned - redelivered, Decimal('0'))
            neutral_quantity = (
                min(quantity_base, neutral_available)
                if checkout_item.fulfillment_source == 'redelivery' else Decimal('0')
            )
            cap_quantity = quantity_base - neutral_quantity
            prescribed = checkout_item.prescription_item.quantity
            if fulfilled + cap_quantity > prescribed:
                raise ValidationError('La dispensación excede el remanente autorizado por la receta.')
            if neutral_quantity:
                PrescriptionFulfillmentEvent.objects.create(
                    organization=checkout.organization,
                    prescription_item=checkout_item.prescription_item,
                    invoice_item=invoice_item, allocation=allocation,
                    kind='redelivered', quantity_delta=Decimal('0'),
                    physical_quantity=neutral_quantity,
                    occurred_at=now, created_by=user,
                )
            if cap_quantity:
                PrescriptionFulfillmentEvent.objects.create(
                    organization=checkout.organization,
                    prescription_item=checkout_item.prescription_item,
                    invoice_item=invoice_item, allocation=allocation,
                    kind='dispensed', quantity_delta=cap_quantity,
                    physical_quantity=cap_quantity,
                    occurred_at=now, created_by=user,
                )


def _replay_invoice(receipt):
    invoice_id = receipt.response_data.get('invoice_id')
    if not invoice_id:
        raise ValidationError('El receipt no contiene una factura reproducible.')
    return Invoice.all_objects.get(pk=invoice_id)


@transaction.atomic
def issue_checkout_estimate(checkout, user, *, expected_version=None, idempotency_key):
    payload = {'checkout': str(checkout.public_id), 'expected_version': expected_version}
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user,
        command_kind='issue_checkout_estimate', idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay:
        return CheckoutEstimate.all_objects.get(pk=receipt.response_data['estimate_id'])
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    items = list(checkout.items.filter(is_active=True).order_by('pk'))
    snapshot = {
        'document_kind': 'commercial_estimate',
        'watermark': 'ESTIMADO — NO ES FACTURA',
        'checkout_public_id': str(checkout.public_id),
        'checkout_version': checkout.version,
        'customer': str(checkout.customer),
        'pet': str(checkout.pet) if checkout.pet_id else None,
        'items': [
            {
                'description': item.description, 'quantity': str(item.quantity),
                'unit_price': str(item.unit_price), 'subtotal': str(item.subtotal),
            }
            for item in items
        ],
        'subtotal': str(checkout.subtotal), 'tax_rate': str(checkout.tax_rate),
        'tax_amount': str(checkout.tax_amount), 'total': str(checkout.total),
    }
    content_hash = _payload_hash(snapshot)
    estimate, _ = CheckoutEstimate.all_objects.get_or_create(
        checkout=checkout, checkout_version=checkout.version,
        defaults={
            'organization': checkout.organization, 'snapshot': snapshot,
            'content_hash': content_hash, 'generated_at': timezone.now(),
            'generated_by': user, 'created_by': user,
        },
    )
    _complete_receipt(receipt, estimate_id=estimate.pk, estimate_public_id=str(estimate.public_id))
    return estimate


@transaction.atomic
def post_checkout(
    checkout, user, *, payment_lines=None, payment_method=None,
    expected_version=None, idempotency_key, due_at=None,
    credit_reason='', obligation_evidence=None,
):
    """Freeze Checkout, emit Invoice, settle stock and optionally pay."""
    paying = bool(payment_lines or payment_method)
    payload = {
        'checkout': str(checkout.public_id), 'expected_version': expected_version,
        'payment_lines': payment_lines, 'payment_method': payment_method,
        'due_at': str(due_at or ''), 'credit_reason': credit_reason,
        'obligation_evidence': obligation_evidence or {},
    }
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user,
        command_kind='pay_checkout' if paying else 'post_checkout',
        idempotency_key=idempotency_key, payload=payload,
    )
    if replay:
        return _replay_invoice(receipt)
    cash_session = _resolve_cash_session_for_payment(user, checkout.organization) if paying else None
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version, require_version=True)
    items = list(
        CheckoutItem.all_objects.select_for_update(of=('self',))
        .select_related('service', 'presentation__product', 'lot', 'prescription_item')
        .filter(checkout=checkout, is_active=True).order_by('pk')
    )
    if not items:
        raise ValidationError('Usa completar-sin-cargo para un Checkout sin líneas.')
    _assert_prescription_resolved(checkout, items)
    _assert_prescription_fulfillment_cap(checkout, items)
    if checkout.total <= 0:
        raise ValidationError('Un documento financiero debe tener total mayor a cero.')
    lines = None
    if paying:
        raw = payment_lines if payment_lines else _legacy_single_line(payment_method, checkout.total)
        lines = _validate_payment_lines(raw)
        if sum((line['amount'] for line in lines), Decimal('0')) != checkout.total:
            raise ValidationError('El pago debe cubrir exactamente el total del Checkout.')
    else:
        from apps.organizations.utils import get_org_setting
        if not get_org_setting(checkout.organization, 'allow_post_unpaid'):
            raise ValidationError('La organización no permite dejar cobros pendientes.')
        if not due_at:
            raise ValidationError({'due_at': 'El vencimiento es obligatorio para dejar pendiente.'})
        if isinstance(due_at, str):
            due_at = parse_datetime(due_at)
        if due_at is None or due_at <= timezone.now() or due_at > timezone.now() + timedelta(days=365):
            raise ValidationError({'due_at': 'El vencimiento debe estar entre 1 y 365 días.'})
        evidence_data = obligation_evidence or {}
        if evidence_data.get('basis') not in {'customer_acknowledgement', 'preauthorized_terms'}:
            raise ValidationError({'obligation_evidence': 'La deuda requiere aceptación o términos preautorizados.'})
        if not evidence_data.get('accepting_party') or not evidence_data.get('channel'):
            raise ValidationError({'obligation_evidence': 'Indica parte aceptante y canal.'})
    now = timezone.now()
    invoice = Invoice.objects.create(
        organization=checkout.organization, checkout=checkout,
        invoice_type=checkout.origin, medical_record=checkout.medical_record,
        appointment=(checkout.medical_record.appointment if checkout.medical_record_id else None),
        owner=checkout.customer, pet=checkout.pet, created_by=user,
        supersedes_invoice=checkout.replaces_invoice, status='posted', posted_at=now,
        tax_rate=checkout.tax_rate, notes=checkout.notes,
        due_at=(None if paying else due_at),
        credit_reason=('' if paying else (credit_reason or '')[:80]),
    )
    copied = []
    for item in items:
        attestation = _current_attestation(item)
        invoice_item = InvoiceItem.objects.create(
            organization=checkout.organization, invoice=invoice, service=item.service,
            presentation=item.presentation,
            conversion_factor_snapshot=item.conversion_factor_snapshot,
            dispensed_from_prescription_item=item.prescription_item, lot=item.lot,
            external_rx_attestation=attestation, description=item.description,
            quantity=item.quantity, unit_price=item.unit_price,
            discount_type=item.discount_type, discount_value=item.discount_value,
            created_by=user,
        )
        copied.append((item, invoice_item))
    invoice.refresh_from_db()
    if invoice.total != checkout.total:
        raise ValidationError('Los totales cambiaron al emitir; recarga el Checkout.')
    _settle_stock(checkout, invoice, copied, user)
    if paying:
        evidence_data = {
            'basis': 'payment_authorization', 'accepting_party': str(checkout.customer),
            'channel': 'in_person', 'reference': '',
        }
    ObligationEvidence.objects.create(
        organization=checkout.organization, checkout=checkout, invoice=invoice,
        basis=evidence_data['basis'], checkout_version=checkout.version,
        accepted_total=checkout.total,
        accepting_party=str(evidence_data['accepting_party'])[:255],
        captured_by=user, channel=str(evidence_data['channel'])[:20],
        reference=str(evidence_data.get('reference') or '')[:255],
        accepted_at=now, credit_authorized_by=(None if paying else user),
        created_by=user,
    )
    InvoiceAuditLog.objects.create(
        invoice=invoice, previous_status='', new_status='posted', changed_by=user,
        notes='Emitida desde Checkout',
    )
    if paying:
        invoice = _pay_locked_invoice(
            invoice, user, lines, require_full=True,
            command_receipt=receipt, cash_session=cash_session,
        )
        completion = 'posted_paid'
    else:
        completion = 'posted_unpaid'
        if credit_reason == 'dispute_enforced_under_terms':
            CollectionCase.objects.create(
                organization=checkout.organization, invoice=invoice, owner=user,
                review_due_at=due_at, opened_at=now, created_by=user,
            )
    checkout.lifecycle = 'completed'
    checkout.completion_kind = completion
    checkout.completed_at = timezone.now()
    checkout.version += 1
    checkout.save(update_fields=['lifecycle', 'completion_kind', 'completed_at', 'version', 'updated_at'])
    _complete_receipt(receipt, invoice_id=invoice.pk, invoice_public_id=str(invoice.public_id))
    return invoice


@transaction.atomic
def complete_no_charge(checkout, user, *, reason, expected_version=None, idempotency_key):
    payload = {'checkout': str(checkout.public_id), 'reason': reason, 'expected_version': expected_version}
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user, command_kind='complete_no_charge',
        idempotency_key=idempotency_key, payload=payload,
    )
    if replay:
        return Checkout.all_objects.get(pk=receipt.response_data['checkout_id'])
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if checkout.kind == 'replacement':
        raise ValidationError('Un replacement requiere reemisión o waiver explícito.')
    if checkout.total != Decimal('0.00'):
        raise ValidationError('Solo un Checkout con total $0 puede completarse sin cargo.')
    checkout.lifecycle = 'completed'
    checkout.completion_kind = 'no_charge'
    checkout.completed_at = timezone.now()
    checkout.abandoned_reason = (reason or '')[:100]
    checkout.version += 1
    checkout.save(update_fields=['lifecycle', 'completion_kind', 'completed_at', 'abandoned_reason', 'version', 'updated_at'])
    _complete_receipt(receipt, checkout_id=checkout.pk, checkout_public_id=str(checkout.public_id))
    return checkout


@transaction.atomic
def abandon_checkout(checkout, user, *, reason, expected_version=None, idempotency_key):
    payload = {'checkout': str(checkout.public_id), 'reason': reason, 'expected_version': expected_version}
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user, command_kind='abandon_checkout',
        idempotency_key=idempotency_key, payload=payload,
    )
    if replay:
        return Checkout.all_objects.get(pk=receipt.response_data['checkout_id'])
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if checkout.kind == 'replacement' or checkout.items.filter(required_replacement_baseline=True).exists():
        raise ValidationError('Un replacement no puede abandonarse.')
    if checkout.origin == 'consultation':
        raise ValidationError('Un Checkout clínico debe emitirse o resolverse sin cargo.')
    checkout.lifecycle = 'abandoned'
    checkout.abandoned_at = timezone.now()
    checkout.abandoned_reason = (reason or '')[:100]
    checkout.version += 1
    checkout.save(update_fields=['lifecycle', 'abandoned_at', 'abandoned_reason', 'version', 'updated_at'])
    _complete_receipt(receipt, checkout_id=checkout.pk, checkout_public_id=str(checkout.public_id))
    return checkout


@transaction.atomic
def void_and_prepare_replacement(invoice, user, *, reason='correction', correction_due_at=None,
                                 dispositions=None, idempotency_key):
    dispositions = dispositions or []
    receipt, replay = _claim_receipt(
        organization=invoice.organization, user=user,
        command_kind='void_and_prepare_replacement', idempotency_key=idempotency_key,
        payload={
            'invoice': str(invoice.public_id), 'reason': reason,
            'correction_due_at': str(correction_due_at or ''),
            'dispositions': dispositions,
        },
    )
    if replay:
        return Checkout.all_objects.get(pk=receipt.response_data['checkout_id'])
    locked = Invoice.all_objects.select_for_update().get(pk=invoice.pk)
    if locked.organization_id != user.organization_id:
        raise ValidationError('La factura pertenece a otra organización.')
    if locked.status != 'posted' or Payment.all_objects.filter(invoice=locked).exists():
        raise ValidationError('Solo una factura emitida sin pagos puede corregirse por replacement.')
    disposition_by_item = {
        int(row['invoice_item']): row.get('outcome')
        for row in dispositions if row.get('invoice_item') is not None
    }
    product_items = list(
        locked.items.filter(
            is_active=True, presentation__isnull=False,
            stock_allocations__isnull=False,
        ).distinct()
        .select_related('presentation', 'dispensed_from_prescription_item')
        .order_by('pk')
    )
    expected_product_ids = {item.pk for item in product_items}
    if set(disposition_by_item) != expected_product_ids:
        raise ValidationError({
            'dispositions': 'Debe indicar exactamente una disposición para cada producto emitido.'
        })
    allowed_outcomes = {'goods_retained', 'returned_restocked', 'returned_discarded'}
    if any(value not in allowed_outcomes for value in disposition_by_item.values()):
        raise ValidationError({'dispositions': 'Disposición de producto inválida.'})
    existing = Checkout.all_objects.filter(replaces_invoice=locked).first()
    if existing:
        _complete_receipt(receipt, checkout_id=existing.pk, checkout_public_id=str(existing.public_id))
        return existing
    now = timezone.now()
    if isinstance(correction_due_at, str):
        correction_due_at = parse_datetime(correction_due_at)
        if correction_due_at is None:
            raise ValidationError({'correction_due_at': 'Fecha inválida.'})
    locked.status = 'voided'
    locked.voided_at = now
    locked.voided_at_source = 'service'
    locked.save(update_fields=['status', 'voided_at', 'voided_at_source', 'updated_at'])
    InvoiceAuditLog.objects.create(
        invoice=locked, previous_status='posted', new_status='voided',
        changed_by=user, notes=(reason or 'correction')[:255],
    )
    checkout = Checkout.objects.create(
        organization=locked.organization, origin=locked.invoice_type,
        kind='replacement', medical_record=locked.medical_record,
        replaces_invoice=locked, owner=user, customer=locked.owner, pet=locked.pet,
        tax_rate=locked.tax_rate,
        correction_due_at=correction_due_at or now + timedelta(days=2),
        created_by=user,
    )
    now = timezone.now()
    for item in locked.items.filter(is_active=True).select_related(
        'presentation', 'dispensed_from_prescription_item',
    ).order_by('pk'):
        outcome = disposition_by_item.get(item.pk)
        has_allocations = item.presentation_id and item.stock_allocations.exists()
        if has_allocations and outcome != 'goods_retained':
            record_invoice_item_disposition(
                invoice_item=item,
                outcome=outcome,
                organization=locked.organization,
                user=user,
                reason=f'Corrección de factura #{locked.pk}',
                occurred_at=now,
            )
            continue
        CheckoutItem.objects.create(
            organization=locked.organization, checkout=checkout,
            service=item.service, presentation=item.presentation, lot=item.lot,
            conversion_factor_snapshot=item.conversion_factor_snapshot,
            prescription_item=item.dispensed_from_prescription_item,
            description=item.description, quantity=item.quantity,
            unit_price=item.unit_price, discount_type=item.discount_type,
            discount_value=item.discount_value, source_kind='replacement_baseline',
            source_invoice_item=item,
            baseline_kind=(
                'performed_service' if not item.presentation_id else
                ('goods_retained' if has_allocations else 'clinical_consumed')
            ),
            required_replacement_baseline=True, fulfillment_source='already_fulfilled',
            created_by=user,
        )
    if not checkout.items.filter(required_replacement_baseline=True).exists():
        raise ValidationError('La factura no contiene exposición que reemplazar.')
    checkout = Checkout.all_objects.get(pk=checkout.pk)
    _complete_receipt(receipt, checkout_id=checkout.pk, checkout_public_id=str(checkout.public_id))
    return checkout


@transaction.atomic
def void_invoice_terminal(invoice, user, *, reason_code, reason_notes='', dispositions=None,
                          idempotency_key):
    """Anula una obligación sin continuidad únicamente cuando el resultado es terminal."""
    dispositions = dispositions or []
    allowed_reasons = {
        'duplicate', 'invalid_obligation', 'full_return',
        'authorized_waiver', 'legal_cancellation',
    }
    if reason_code not in allowed_reasons:
        raise ValidationError({'reason_code': 'Motivo de anulación terminal inválido.'})
    if not str(reason_notes or '').strip():
        raise ValidationError({'reason_notes': 'La anulación terminal requiere una justificación.'})
    receipt, replay = _claim_receipt(
        organization=invoice.organization, user=user, command_kind='void_invoice_terminal',
        idempotency_key=idempotency_key, aggregate_type='invoice',
        aggregate_public_id=invoice.public_id,
        payload={
            'invoice': str(invoice.public_id), 'reason_code': reason_code,
            'reason_notes': reason_notes, 'dispositions': dispositions,
        },
    )
    if replay:
        return Invoice.all_objects.get(pk=receipt.response_data['invoice_id'])
    locked = Invoice.all_objects.select_for_update().get(pk=invoice.pk)
    if locked.organization_id != user.organization_id:
        raise ValidationError('La factura pertenece a otra organización.')
    if locked.status != 'posted' or Payment.all_objects.filter(invoice=locked).exists():
        raise ValidationError('Solo una factura emitida sin pagos puede anularse terminalmente.')
    allocated_items = list(
        locked.items.filter(is_active=True, stock_allocations__isnull=False)
        .select_related('presentation', 'dispensed_from_prescription_item').distinct()
        .order_by('pk')
    )
    disposition_by_item = {
        int(row['invoice_item']): row.get('outcome')
        for row in dispositions if row.get('invoice_item') is not None
    }
    if set(disposition_by_item) != {item.pk for item in allocated_items}:
        raise ValidationError({
            'dispositions': 'Debe indicar exactamente una disposición para cada producto entregado.'
        })
    if any(
        outcome not in {'returned_restocked', 'returned_discarded'}
        for outcome in disposition_by_item.values()
    ):
        raise ValidationError({
            'dispositions': 'Una anulación terminal no permite mercancía retenida.'
        })
    now = timezone.now()
    for item in allocated_items:
        outcome = disposition_by_item[item.pk]
        record_invoice_item_disposition(
            invoice_item=item,
            outcome=outcome,
            organization=locked.organization,
            user=user,
            reason=f'Anulación terminal de factura #{locked.pk}',
            occurred_at=now,
        )
    locked.status = 'voided'
    locked.voided_at = now
    locked.voided_at_source = 'service'
    locked.save(update_fields=['status', 'voided_at', 'voided_at_source', 'updated_at'])
    InvoiceAuditLog.objects.create(
        invoice=locked, previous_status='posted', new_status='voided',
        changed_by=user, notes=f'{reason_code}: {reason_notes}'[:255],
    )
    CollectionCase.all_objects.filter(invoice=locked, status='open').update(
        status='resolved', resolution='voided_terminal', resolved_at=now,
    )
    _complete_receipt(
        receipt, invoice_id=locked.pk, invoice_public_id=str(locked.public_id),
    )
    return locked


@transaction.atomic
def waive_replacement_exposure(checkout, user, *, reason_code, evidence=None,
                                expected_version=None, idempotency_key):
    receipt, replay = _claim_receipt(
        organization=checkout.organization, user=user,
        command_kind='waive_replacement_exposure', idempotency_key=idempotency_key,
        payload={
            'checkout': str(checkout.public_id), 'reason_code': reason_code,
            'evidence': evidence or {}, 'expected_version': expected_version,
        },
    )
    if replay:
        return ReplacementWaiver.all_objects.get(pk=receipt.response_data['waiver_id'])
    checkout = Checkout.all_objects.select_for_update().get(pk=checkout.pk)
    _assert_open(checkout, expected_version)
    if checkout.kind != 'replacement':
        raise ValidationError('El waiver solo aplica a un replacement.')
    allowed_reasons = {'authorized_waiver', 'billing_error', 'clinical_resolution', 'goodwill'}
    if reason_code not in allowed_reasons:
        raise ValidationError({'reason_code': 'Motivo de condonación inválido.'})
    if not evidence or not str(evidence.get('note') or '').strip():
        raise ValidationError({'evidence': 'La condonación requiere evidencia y una nota.'})
    baseline = checkout.items.filter(required_replacement_baseline=True)
    if not baseline.exists():
        raise ValidationError('El replacement no tiene baseline exigible.')
    amount = checkout.total
    waiver = ReplacementWaiver.objects.create(
        organization=checkout.organization, checkout=checkout, amount=amount,
        reason_code=(reason_code or '')[:50], evidence=evidence or {},
        baseline_hash=_payload_hash(list(baseline.values('pk', 'quantity', 'unit_price'))),
        waived_by=user, occurred_at=timezone.now(), created_by=user,
    )
    checkout.lifecycle = 'completed'
    checkout.completion_kind = 'replacement_waived'
    checkout.completed_at = timezone.now()
    checkout.version += 1
    checkout.save(update_fields=['lifecycle', 'completion_kind', 'completed_at', 'version', 'updated_at'])
    _complete_receipt(receipt, waiver_id=waiver.pk, checkout_id=checkout.pk)
    return waiver
