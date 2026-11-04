"""Preview/confirm/execute for exceptional platform-only physical deletion."""
import hashlib
import json
from uuid import UUID

from django.core import signing
from django.db import connection, transaction
from django.http import Http404
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.platform.deletion_guards import authorize_physical_deletion
from apps.platform.models import PhysicalDeletionReceipt


CONFIRM_TTL_SECONDS = 300
SALT = 'order2-platform-physical-delete-v1'
TARGETS = {'owner': Owner, 'pet': Pet, 'organization': Organization}
DETACHABLE = {
    'owner': {'billing.Invoice.owner', 'billing.Checkout.customer'},
    'pet': {'billing.Invoice.pet', 'billing.Checkout.pet',
            'medical_records.MedicalRecord.pet', 'prescriptions.Prescription.pet'},
    'organization': set(),
}
IMPACT_KEYS = {
    'billing.Invoice.owner': 'invoices', 'billing.Invoice.pet': 'invoices',
    'billing.Checkout.customer': 'checkouts', 'billing.Checkout.pet': 'checkouts',
    'medical_records.MedicalRecord.pet': 'medical_records',
    'prescriptions.Prescription.pet': 'prescriptions',
}


class PhysicalDeleteConflict(APIException):
    status_code = 409
    default_code = 'physical_delete_conflict'
    default_detail = 'El impacto cambió; solicita un preview nuevo.'


def _authorize(actor):
    if not (actor.is_authenticated and actor.is_active and actor.is_superuser
            and actor.is_staff and actor.role == 'ADMIN_SAAS'):
        raise PermissionDenied('Solo operadores de plataforma.')


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()


def _normalize(actor, *, organization_id, target_type, target_id, reason):
    _authorize(actor)
    if target_type not in TARGETS:
        raise ValidationError({'target_type': 'Tipo fuera de la lista permitida.'})
    try:
        organization_id, target_id = UUID(str(organization_id)), UUID(str(target_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError({'target_id': 'UUID inválido.'}) from exc
    reason = reason.strip() if isinstance(reason, str) else ''
    if not (8 <= len(reason) <= 255):
        raise ValidationError({'reason': 'Indica un motivo de 8 a 255 caracteres.'})
    return {'actor': str(actor.public_id), 'organization': str(organization_id),
            'type': target_type, 'target': str(target_id), 'action': 'physical_delete',
            'reason': reason}


def _get_target(org, target_type, target_id, *, lock=False):
    model = TARGETS[target_type]
    qs = (model.objects if target_type == 'organization' else model.all_objects.filter(organization=org))
    if lock:
        qs = qs.select_for_update()
    target = qs.filter(public_id=target_id).first()
    if target is None or target_type == 'organization' and target.pk != org.pk:
        raise Http404
    return target


def _inspect(org, target, target_type):
    blockers = set()
    state = {'target': str(target.public_id), 'is_active': target.is_active,
             'archived_at': str(getattr(target, 'archived_at', None)), 'references': {}}
    if target.is_active:
        blockers.add('target_not_archived')
    if getattr(target, 'is_generic', False):
        blockers.add('generic_resource')
    if getattr(target, 'legacy_id', '') or getattr(target, 'extra_data', []):
        # El importador conserva procedencia/atributos no representados por el
        # snapshot mínimo de documentos; no perderlos por una excepción física.
        blockers.add('unsupported_import_provenance')
    from django.contrib.admin.models import LogEntry
    from django.contrib.contenttypes.models import ContentType
    model_type = ContentType.objects.filter(
        app_label=target._meta.app_label, model=target._meta.model_name,
    ).first()
    if model_type and LogEntry.objects.filter(content_type=model_type,
                                               object_id=str(target.pk)).exists():
        blockers.add('unsupported_reference')
    impact = {}
    for relation in target._meta.related_objects:
        field = relation.field
        if not field.many_to_one and not field.one_to_one:
            blockers.add('unsupported_reference')
            continue
        key = f'{relation.related_model._meta.label}.{field.name}'
        rows = relation.related_model._base_manager.filter(**{field.attname: target.pk})
        if not rows.exists():
            continue
        if key not in DETACHABLE[target_type]:
            blockers.add('unsupported_reference')
            state['references'][key] = sorted(str(i) for i in rows.values_list('pk', flat=True))
            continue
        kind = 'owner' if target_type == 'owner' else 'pet'
        evidence = []
        for row in rows.order_by('pk'):
            identity = (row.subject_snapshot or {}).get(kind) or {}
            snapshot = row.subject_snapshot or {}
            if (snapshot.get('version') != 1 or snapshot.get('organization') != str(org.public_id)
                    or identity.get('uuid') != str(target.public_id)
                    or not identity.get('name') or snapshot.get('source') not in ('captured', 'reconstructed')
                    or not snapshot.get('recorded_at') or row.organization_id != org.pk):
                blockers.add('identity_not_preserved')
            if kind == 'pet' and not {'sex', 'birth_date'} <= identity.keys():
                blockers.add('identity_not_preserved')
            status = getattr(row, 'status', getattr(row, 'lifecycle', ''))
            if key.startswith('medical_records.') and status != 'closed':
                blockers.add('open_medical_record')
            if key.startswith('billing.Checkout') and status != 'completed':
                blockers.add('open_checkout')
            if key.startswith('billing.Invoice') and (
                    status not in ('paid', 'voided') or status == 'paid' and row.remaining_balance != 0):
                blockers.add('pending_payment')
            evidence.append((row.pk, status, snapshot.get('recorded_at'),
                             str(row.remaining_balance) if key.startswith('billing.Invoice') else ''))
            impact[IMPACT_KEYS[key]] = impact.get(IMPACT_KEYS[key], 0) + 1
        state['references'][key] = evidence
    return {'blockers': sorted(blockers), 'impact': impact,
            'digest': _digest(state)}


def preview(*, actor, organization_id, target_type, target_id, reason):
    scope = _normalize(actor, organization_id=organization_id, target_type=target_type,
                       target_id=target_id, reason=reason)
    org = Organization.objects.filter(public_id=scope['organization']).first()
    if org is None:
        raise Http404
    target = _get_target(org, scope['type'], scope['target'])
    observed = _inspect(org, target, scope['type'])
    token = None
    if not observed['blockers']:
        token = signing.dumps({**scope, 'impact_digest': observed['digest']}, salt=SALT)
    return {'target_type': scope['type'], 'target_id': scope['target'],
            'organization_id': scope['organization'], 'eligible': not observed['blockers'],
            'blockers': observed['blockers'], 'impact': observed['impact'],
            'confirmation': token, 'expires_in_seconds': CONFIRM_TTL_SECONDS if token else None}


def execute(*, actor, organization_id, target_type, target_id, reason,
            confirmation, idempotency_key):
    scope = _normalize(actor, organization_id=organization_id, target_type=target_type,
                       target_id=target_id, reason=reason)
    try:
        key = UUID(str(idempotency_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError({'idempotency_key': 'UUID obligatorio.'}) from exc
    payload_hash = _digest(scope)

    def receipt_result(receipt):
        if receipt.actor_id != actor.public_id or receipt.organization_id != UUID(scope['organization']):
            raise PermissionDenied('Operación fuera de tu alcance.')
        if receipt.payload_digest != payload_hash:
            raise PhysicalDeleteConflict('Clave de idempotencia reutilizada con otro payload.')
        return {'operation_id': receipt.pk, 'outcome': receipt.outcome,
                'target_type': receipt.target_type, 'target_id': str(receipt.target_id),
                'organization_id': str(receipt.organization_id), 'impact': receipt.impact,
                'occurred_at': receipt.occurred_at}

    with transaction.atomic():
        # Serializar este key antes del primer lookup, incluso si dos requests
        # apuntan a organizaciones distintas (no comparten lock de org).
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [key.int & ((1 << 63) - 1)])
        receipt = PhysicalDeletionReceipt.objects.select_for_update().filter(idempotency_key=key).first()
        if receipt:
            return receipt_result(receipt)
        if not isinstance(confirmation, str):
            raise ValidationError({'confirmation': 'Confirma un preview vigente.'})
        try:
            signed = signing.loads(confirmation, salt=SALT, max_age=CONFIRM_TTL_SECONDS)
        except (signing.BadSignature, signing.SignatureExpired) as exc:
            raise PhysicalDeleteConflict('Confirmación inválida o vencida.') from exc
        if any(signed.get(k) != v for k, v in scope.items()):
            raise PhysicalDeleteConflict('La confirmación no corresponde a este actor y objetivo.')
        confirmation_hash = hashlib.sha256(confirmation.encode()).hexdigest()
        if PhysicalDeletionReceipt.objects.filter(confirmation_digest=confirmation_hash).exists():
            raise PhysicalDeleteConflict('Confirmación ya consumida.')
        org = Organization.objects.select_for_update().filter(public_id=scope['organization']).first()
        if org is None:
            receipt = PhysicalDeletionReceipt.objects.filter(idempotency_key=key).first()
            if receipt:
                return receipt_result(receipt)
            raise PhysicalDeleteConflict('El objetivo ya no está disponible.')
        try:
            target = _get_target(org, scope['type'], scope['target'], lock=True)
        except Http404:
            receipt = PhysicalDeletionReceipt.objects.filter(idempotency_key=key).first()
            if receipt:
                return receipt_result(receipt)
            raise PhysicalDeleteConflict('El objetivo ya no está disponible.')
        current = _inspect(org, target, scope['type'])
        if current['blockers'] or current['digest'] != signed.get('impact_digest'):
            raise PhysicalDeleteConflict('El impacto cambió; solicita un preview nuevo.')
        with authorize_physical_deletion(target):
            target.delete()
        receipt = PhysicalDeletionReceipt.objects.create(
            idempotency_key=key, confirmation_digest=confirmation_hash,
            actor_id=actor.public_id, actor_role='ADMIN_SAAS',
            organization_id=UUID(scope['organization']), target_type=scope['type'],
            target_id=UUID(scope['target']), reason=scope['reason'],
            payload_digest=payload_hash, impact_digest=current['digest'],
            impact=current['impact'], outcome='deleted',
        )
        return receipt_result(receipt)
