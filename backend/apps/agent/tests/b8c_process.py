"""Independent PostgreSQL processes and real commit barriers for B8C."""
import json
import os
import sys
from contextlib import ExitStack
from dataclasses import asdict
from uuid import UUID, uuid4
from unittest.mock import patch


def barrier(name):
    print('B8C_' + name, flush=True)
    if sys.stdin.readline().strip() != 'go':
        os._exit(86)


def main():
    from .process_database import configure_test_database_environment
    config = configure_test_database_environment(allowed_prefixes=('test_b8c_', 'test_ci_'))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections, transaction
    connections.close_all()
    connections.databases['default'].update(config)
    settings.AGENT_B7B_CONSENT_ENABLED = True
    from apps.agent import durable, operation_execution as execution, matter_binding
    from apps.agent.models import Conversation, ConversationGoal
    from apps.agent.services import ingest_inbound_message
    from apps.agent import appointment_mutation_execution
    from apps.appointments import mutations
    from apps.appointments.models import Appointment, AppointmentMutationEffect
    from .b8c_support import enabled_mutations
    mode, raw = sys.argv[1:]
    args = json.loads(raw)
    if django.get_version() != args['django_version']:
        raise RuntimeError('Worker dependencies differ')
    witness = args['witness']
    witness['lease_token'] = UUID(witness['lease_token'])
    witness = durable.OwnershipWitness(**witness)
    context = execution.ExecutionContext(witness, args['contact_id'], args['capability'])
    with connections['default'].cursor() as c:
        c.execute('SELECT set_config(%s, %s, false)', ['application_name', 'b8c_' + str(os.getpid())])
    barrier('READY')
    result = {}
    try:
        if mode.removeprefix('hold_') in ('correction', 'revocation', 'takeover'):
            with transaction.atomic():
                conv = Conversation.objects.select_for_update().get(pk=witness.conversation_id)
                if mode.endswith('takeover'):
                    durable.invalidate_ownership(conv, reason='test_takeover')
                    conv.state = Conversation.STATE_HUMAN_ACTIVE
                    conv.save(update_fields=['state'])
                else:
                    incoming = ingest_inbound_message(conv.channel_account, wamid='wamid.' + uuid4().hex,
                        wa_id=conv.contact.external_id,
                        body='Mejor las 11' if mode.endswith('correction') else 'No, olvida la propuesta')
                    if mode.endswith('correction'):
                        from apps.agent.turn_context import build_turn_context
                        goal = ConversationGoal.objects.get(pk=args['goal_id'])
                        matter_binding.change(goal, conv, {'time': '11:00'},
                            context=build_turn_context(conv, [incoming]), message_id=incoming.pk,
                            expected_revision=goal.binding_revision, correction=True)
                if mode.startswith('hold_'):
                    barrier('CHANGED')
            result = {'changed': True}
        elif mode in ('raw_reschedule', 'hold_raw_reschedule'):
            # Deliberately bypass application checks to exercise GiST UPDATE.
            from apps.agent.models import ConversationOperation
            from apps.agent.appointment_mutation_execution import command_for
            from apps.appointments.creation import appointment_interval
            command = command_for(ConversationOperation.objects.get(operation_key=args['operation_key']))
            from types import SimpleNamespace
            start, end = appointment_interval(SimpleNamespace(timezone=command.clinic_timezone),
                command.date, command.start_time, command.end_time)
            print('B8C_ATTEMPTING', flush=True)
            with transaction.atomic():
                with connections['default'].cursor() as c:
                    c.execute('UPDATE appointments_appointment SET date=%s, start_time=%s, end_time=%s, '
                        'start_datetime=%s, end_datetime=%s WHERE id=%s',
                        [command.date, command.start_time, command.end_time, start, end, command.appointment_id])
                if mode == 'hold_raw_reschedule': barrier('MUTATED')
            result = {'mutated': True}
        elif mode in ('human', 'hold_human'):
            # Real human PATCH endpoint, including RBAC, serializer, locks and
            # expected_state captured before contention. No direct SQL mutation.
            from rest_framework.test import APIRequestFactory, force_authenticate
            from apps.appointments.views import AppointmentDetailView
            from apps.appointments.services import current_state
            from apps.users.models import User
            appointment = Appointment.objects.get(pk=args['appointment_id'])
            user = User.objects.get(pk=args['human_id'])
            request = APIRequestFactory().patch('/api/appointments/' + str(appointment.public_id) + '/',
                {**args['human_payload'], 'expected_state': current_state(appointment)}, format='json')
            force_authenticate(request, user=user)
            print('B8C_ATTEMPTING', flush=True)
            with transaction.atomic():
                response = AppointmentDetailView.as_view()(request, pk=str(appointment.public_id))
                result = {'status_code': response.status_code}
                if mode == 'hold_human':
                    barrier('CHANGED')
        else:
            adapter = execution.REGISTRY[args['kind']].adapter
            original_validate = adapter.validate_preconditions
            original_snapshot = mutations.appointment_snapshot
            original_save, original_effect_save = Appointment.save, AppointmentMutationEffect.save
            original_record = execution._record
            paused = False
            def validate(operation, ctx):
                if mode == 'before_locks': barrier('BEFORE_LOCKS')
                return original_validate(operation, ctx)
            def snapshot(appointment):
                nonlocal paused
                if mode == 'after_appointment' and not paused:
                    paused = True
                    barrier('APPOINTMENT_LOCKED')
                return original_snapshot(appointment)
            def save(instance, *a, **kw):
                value = original_save(instance, *a, **kw)
                if mode == 'after_mutation': barrier('MUTATED')
                return value
            def effect_save(instance, *a, **kw):
                if mode == 'evidence_db_error':
                    with connections['default'].cursor() as c: c.execute('SELECT 1 / 0')
                value = original_effect_save(instance, *a, **kw)
                if mode == 'after_evidence': barrier('EVIDENCE_PENDING')
                return value
            def record(operation, status, *a, **kw):
                original_record(operation, status, *a, **kw)
                if status == 'SUCCEEDED' and mode == 'hold_effect': barrier('EFFECT_PENDING')
            with ExitStack() as stack:
                stack.enter_context(enabled_mutations())
                stack.enter_context(patch.object(adapter, 'validate_preconditions', validate))
                stack.enter_context(patch.object(mutations, 'appointment_snapshot', snapshot))
                stack.enter_context(patch.object(Appointment, 'save', save))
                stack.enter_context(patch.object(AppointmentMutationEffect, 'save', effect_save))
                stack.enter_context(patch.object(execution, '_record', record))
                print('B8C_ATTEMPTING', flush=True)
                result = asdict(execution.execute_authorized_operation(UUID(args['operation_key']), context))
            if mode == 'after_commit': barrier('COMMITTED')
    except Exception as exc:
        result = {'error': type(exc).__name__, 'detail': str(exc)[:300],
            'constraint': getattr(getattr(getattr(exc, '__cause__', None), 'diag', None), 'constraint_name', None)}
    print('B8C_RESULT ' + json.dumps(result, default=str), flush=True)


if __name__ == '__main__':
    main()
