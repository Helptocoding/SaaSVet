"""Independent interpreter and PostgreSQL backend for B8E races/crashes."""
import json
import os
import sys
from contextlib import ExitStack
from dataclasses import asdict
from uuid import UUID, uuid4
from unittest.mock import patch


def barrier(name):
    print('B8E_' + name, flush=True)
    if sys.stdin.readline().strip() != 'go': os._exit(86)


def main():
    from .process_database import configure_test_database_environment
    config = configure_test_database_environment(allowed_prefixes=('test_b8e_', 'test_ci_'))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections, transaction
    connections.close_all()
    connections.databases['default'].update(config)
    settings.AGENT_B7B_CONSENT_ENABLED = True
    from apps.agent import durable, operation_execution as execution, matter_binding
    from apps.agent.models import Conversation, ConversationGoal, ContactIdentity, HumanHandoff
    from apps.agent.services import ingest_inbound_message
    from apps.patients import creation
    from apps.patients.models import Owner, Pet, PetRegistrationEffect
    from .b8e_support import enabled_registration
    mode, raw = sys.argv[1:]
    args = json.loads(raw)
    if django.get_version() != args['django_version']: raise RuntimeError('Worker version differs')
    raw_witness = args['witness']
    raw_witness['lease_token'] = UUID(raw_witness['lease_token'])
    witness = durable.OwnershipWitness(**raw_witness)
    context = execution.ExecutionContext(witness, args['contact_id'], 'register_pet_only')
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT set_config(%s,%s,false)', ['application_name', 'b8e_' + str(os.getpid())])
        cursor.execute('SELECT pg_backend_pid()')
        backend_pid = cursor.fetchone()[0]
    barrier('READY')
    result = {}
    action = mode.removeprefix('hold_')
    try:
        if action == 'owner_phone':
            from apps.agent.models import ConversationOperation
            from apps.patients.services import change_owner_phone
            owner_id = ConversationOperation.objects.get(operation_key=args['operation_key']).owner_id
            with transaction.atomic():
                owner = Owner.objects.select_for_update().get(pk=owner_id)
                if mode.startswith('hold_'): barrier('OWNER_EDIT_LOCKED')
                change_owner_phone(owner, '5512349999')
            result = {'changed': True}
        elif action == 'identity':
            with transaction.atomic():
                contact = ContactIdentity.objects.select_for_update().get(pk=args['contact_id'])
                contact.owner = None
                contact.verification_level, contact.verified_at = 'unknown', None
                contact.save()
                if mode.startswith('hold_'): barrier('CHANGED')
            result = {'changed': True}
        elif action in ('correction', 'revocation', 'takeover', 'binding', 'handoff'):
            with transaction.atomic():
                conv = Conversation.objects.select_for_update().get(pk=witness.conversation_id)
                if action == 'takeover':
                    durable.invalidate_ownership(conv, reason='test_takeover')
                    conv.state = Conversation.STATE_HUMAN_ACTIVE
                    conv.save(update_fields=['state'])
                elif action == 'handoff':
                    HumanHandoff.objects.create(organization=conv.organization, conversation=conv,
                        reason_code=HumanHandoff.REASON_EXPLICIT)
                else:
                    incoming = ingest_inbound_message(conv.channel_account, wamid='wamid.'+uuid4().hex,
                        wa_id=conv.contact.external_id, body='Perdón, se llama Sol' if action=='correction' else 'No, detén el registro')
                    if action in ('binding', 'correction'):
                        from apps.agent.turn_context import build_turn_context
                        goal = ConversationGoal.objects.get(pk=args['goal_id'])
                        ctx = build_turn_context(conv, [incoming])
                        if action == 'binding':
                            matter_binding.change(goal, conv, {'owner': None}, context=ctx,
                                message_id=incoming.pk, expected_revision=goal.binding_revision, correction=True)
                        else:
                            matter_binding.change(goal, conv, {'pet_name': 'Sol'}, context=ctx,
                                message_id=incoming.pk, expected_revision=goal.binding_revision,
                                correction=True)
                if mode.startswith('hold_'): barrier('CHANGED')
            result = {'changed': True}
        elif action == 'human':
            from rest_framework.test import APIRequestFactory, force_authenticate
            from apps.patients.views import PetViewSet
            from apps.users.models import User
            request = APIRequestFactory().post('/api/pets/', args['human_payload'], format='json')
            force_authenticate(request, user=User.objects.get(pk=args['human_id']))
            with transaction.atomic():
                response = PetViewSet.as_view({'post': 'create'}, basename='patient')(request)
                result = {'status_code': response.status_code, 'pet_id': response.data.get('id')}
                if mode.startswith('hold_'): barrier('CHANGED')
        elif action == 'evidence':
            # Compete for the same exact operation after the real adapter wrote
            # its ledger. The unique index must arbitrate across backends.
            from apps.agent.models import ConversationOperation
            from apps.agent.pet_execution import fields_for, definition_for
            op = ConversationOperation.objects.get(operation_key=args['operation_key'])
            with transaction.atomic():
                pet = creation.create_pet(organization_id=op.organization_id, owner_id=op.owner_id, fields=fields_for(op))
                PetRegistrationEffect.objects.create(operation=op, pet=pet, owner_id=op.owner_id,
                    organization_id=op.organization_id, parameters_digest=op.parameters_digest,
                    definition=definition_for(op), committed_at=durable.db_now())
            result = {'unexpected_effect': True}
        else:
            adapter = execution.REGISTRY['REGISTER_PET'].adapter
            validate, lock = adapter.validate_preconditions, creation.lock_creation_scope
            pet_save, evidence_save, record = Pet.save, PetRegistrationEffect.save, execution._record
            atomic_exit = transaction.Atomic.__exit__
            effect_recorded = False
            paused = False
            def validated(op, ctx):
                if mode == 'before_locks': barrier('BEFORE_LOCKS')
                return validate(op, ctx)
            def locked(*a, **kw):
                nonlocal paused
                value = lock(*a, **kw)
                if mode == 'after_owner' and not paused:
                    paused = True
                    barrier('OWNER_LOCKED')
                return value
            def saved(instance, *a, **kw):
                value = pet_save(instance, *a, **kw)
                if mode == 'after_insert': barrier('INSERTED')
                return value
            def evidenced(instance, *a, **kw):
                if mode == 'evidence_db_error':
                    with connections['default'].cursor() as cursor: cursor.execute('SELECT 1 / 0')
                value = evidence_save(instance, *a, **kw)
                if mode == 'after_evidence': barrier('EVIDENCE_PENDING')
                return value
            def recorded(op, status, *a, **kw):
                nonlocal effect_recorded
                record(op, status, *a, **kw)
                effect_recorded = status == 'SUCCEEDED'
                if status == 'SUCCEEDED' and mode == 'hold_effect': barrier('EFFECT_PENDING')
            def committed(block, *a):
                outer = not connections['default'].savepoint_ids
                value = atomic_exit(block, *a)
                if mode == 'commit_db_error' and outer and effect_recorded:
                    from django.db import OperationalError
                    raise OperationalError('Injected loss of COMMIT acknowledgement')
                return value
            with ExitStack() as stack:
                stack.enter_context(enabled_registration())
                for obj, attr, fn in ((adapter, 'validate_preconditions', validated),
                        (creation, 'lock_creation_scope', locked), (Pet, 'save', saved),
                        (PetRegistrationEffect, 'save', evidenced), (execution, '_record', recorded),
                        (transaction.Atomic, '__exit__', committed)):
                    stack.enter_context(patch.object(obj, attr, fn))
                print('B8E_ATTEMPTING', flush=True)
                result = asdict(execution.execute_authorized_operation(UUID(args['operation_key']), context))
            if mode == 'after_commit': barrier('COMMITTED')
    except Exception as exc:
        result = {'error': type(exc).__name__, 'detail': str(exc)[:300],
            'constraint': getattr(getattr(getattr(exc, '__cause__', None), 'diag', None), 'constraint_name', None)}
    result['backend_pid'] = backend_pid
    print('B8E_RESULT ' + json.dumps(result, default=str), flush=True)


if __name__ == '__main__': main()
