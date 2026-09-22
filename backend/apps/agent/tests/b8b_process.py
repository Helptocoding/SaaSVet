"""Independent OS workers against the real B8B adapter and PostgreSQL."""
import json
import os
import sys
from contextlib import ExitStack
from dataclasses import asdict
from uuid import UUID, uuid4
from unittest.mock import patch


def barrier(name):
    print('B8B_' + name, flush=True)
    if sys.stdin.readline().strip() != 'go':
        os._exit(86)


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections, transaction
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_b8b_'):
        raise RuntimeError('B8B workers require isolated test_b8b_ PostgreSQL')
    connections.close_all()
    connections.databases['default'].update(config)
    settings.AGENT_B7B_CONSENT_ENABLED = True
    from apps.agent import durable, operation_execution as execution, matter_binding
    from apps.agent.models import Conversation, ConversationGoal, ConversationOperation, ContactIdentity
    from apps.agent.services import ingest_inbound_message
    from apps.appointments import creation
    from apps.appointments.models import Appointment
    from apps.agent.appointment_execution import command_for
    from .b8b_support import enabled_create
    mode, raw = sys.argv[1:]
    args = json.loads(raw)
    if django.get_version() != args['django_version']:
        raise RuntimeError('Worker dependencies differ from coordinator')
    witness = args['witness']
    witness['lease_token'] = UUID(witness['lease_token'])
    witness = durable.OwnershipWitness(**witness)
    context = execution.ExecutionContext(witness, args['contact_id'], 'create_appointment')
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT set_config(%s, %s, false)', ['application_name', 'b8b_' + str(os.getpid())])
    barrier('READY')
    result = {}
    try:
        if mode.removeprefix('hold_') in ('correction', 'revocation', 'takeover', 'permission'):
            with transaction.atomic():
                if mode.endswith('permission'):
                    contact = ContactIdentity.all_objects.select_for_update().get(pk=args['contact_id'])
                    contact.is_blocked = True
                    contact.save(update_fields=['is_blocked'])
                else:
                    conv = Conversation.objects.select_for_update().get(pk=witness.conversation_id)
                    if mode.endswith('correction'):
                        from apps.agent.turn_context import build_turn_context
                        incoming = ingest_inbound_message(conv.channel_account, wamid='wamid.' + uuid4().hex,
                            wa_id=conv.contact.external_id, body='Mejor las 11', raw={})
                        goal = ConversationGoal.objects.get(pk=args['goal_id'])
                        matter_binding.change(goal, conv, {'time': '11:00'},
                            context=build_turn_context(conv, [incoming]), message_id=incoming.pk,
                            expected_revision=goal.binding_revision, correction=True)
                    elif mode.endswith('takeover'):
                        durable.invalidate_ownership(conv, reason='test_takeover')
                        conv.state = Conversation.STATE_HUMAN_ACTIVE
                        conv.save(update_fields=['state'])
                    else:
                        ingest_inbound_message(conv.channel_account, wamid='wamid.' + uuid4().hex,
                            wa_id=conv.contact.external_id, body='No, olvida la propuesta', raw={})
                if mode.startswith('hold_'):
                    barrier('CHANGED')
            result = {'changed': True}
        elif mode in ('raw_constraint', 'hold_raw_constraint'):
            # Deliberately bypass services AND model validation to prove GiST
            # independently of application locks/prechecks.
            operation = ConversationOperation.objects.get(operation_key=args['operation_key'])
            command = command_for(operation)
            org = operation.organization
            start, end = creation.appointment_interval(org, command.date, command.start_time, command.end_time)
            print('B8B_ATTEMPTING', flush=True)
            with transaction.atomic():
                appointment = Appointment(organization=org, pet_id=command.pet_id,
                    veterinarian_id=command.veterinarian_id, date=command.date,
                    start_time=command.start_time, end_time=command.end_time,
                    start_datetime=start, end_datetime=end, timezone_at_creation=org.timezone,
                    reason=command.reason)
                appointment.save(validate=False)
                if mode.startswith('hold_'):
                    barrier('INSERTED')
            result = {'created': True}
        else:
            adapter = execution.REGISTRY['CREATE_APPOINTMENT'].adapter
            original_validate = adapter.validate_preconditions
            original_lock = creation.lock_veterinarians
            original_save = Appointment.save
            original_record = execution._record
            lock_paused = False
            def validate(operation, ctx):
                if mode == 'before_availability':
                    barrier('BEFORE_AVAILABILITY')
                return original_validate(operation, ctx)
            def lock(*a, **kw):
                nonlocal lock_paused
                original_lock(*a, **kw)
                if mode == 'after_resource' and not lock_paused:
                    lock_paused = True
                    barrier('RESOURCE_LOCKED')
            def save(instance, *a, **kw):
                if mode == 'db_error':
                    with connections['default'].cursor() as cursor:
                        cursor.execute('SELECT 1 / 0')
                value = original_save(instance, *a, **kw)
                if instance.source_operation_id and mode == 'after_insert':
                    barrier('INSERTED')
                return value
            def record(operation, status, *a, **kw):
                original_record(operation, status, *a, **kw)
                if status == 'SUCCEEDED' and mode == 'hold_effect':
                    barrier('EFFECT_PENDING')
            with ExitStack() as stack:
                stack.enter_context(enabled_create())
                stack.enter_context(patch.object(adapter, 'validate_preconditions', validate))
                stack.enter_context(patch.object(creation, 'lock_veterinarians', lock))
                stack.enter_context(patch.object(Appointment, 'save', save))
                stack.enter_context(patch.object(execution, '_record', record))
                if mode == 'on_commit_crash':
                    stack.enter_context(patch('apps.dashboard.signals._invalidate_org_dashboard',
                        side_effect=lambda org_id: barrier('ON_COMMIT')))
                print('B8B_ATTEMPTING', flush=True)
                result = asdict(execution.execute_authorized_operation(UUID(args['operation_key']), context))
            if mode == 'after_commit':
                barrier('COMMITTED')
    except Exception as exc:
        result = {'error': type(exc).__name__,
                  'constraint': getattr(getattr(getattr(exc, '__cause__', None), 'diag', None), 'constraint_name', None)}
    print('B8B_RESULT ' + json.dumps(result, default=str), flush=True)


if __name__ == '__main__':
    main()
