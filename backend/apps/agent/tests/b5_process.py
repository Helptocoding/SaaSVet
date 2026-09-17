"""B5 independent interpreter probe; synthetic PostgreSQL test DB only."""
import json
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections, transaction
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_'):
        raise RuntimeError('Requires isolated test database')
    connections.close_all()
    connections.databases['default'].update(config)
    settings.AGENT_SAFETY_AUTOMATION_ENABLED = True
    from apps.agent import durable, safety, worker
    from apps.agent.models import Conversation
    mode, conv_id = sys.argv[1], int(sys.argv[2])
    print('B3_READY', flush=True)
    sys.stdin.readline()
    if mode == 'takeover':
        with transaction.atomic():
            conv = Conversation.objects.select_for_update().get(pk=conv_id)
            if conv.state != Conversation.STATE_HUMAN_ACTIVE:
                durable.invalidate_ownership(conv, reason='b5_staff_takeover')
                conv.state = Conversation.STATE_HUMAN_ACTIVE
                conv.save(update_fields=['state'])
        result = {'takeover': True}
    elif mode == 'duplicate':
        from apps.agent.services import ingest_inbound_message
        conv = Conversation.objects.select_related('channel_account', 'contact').get(pk=conv_id)
        m = ingest_inbound_message(conv.channel_account, wamid='b5-process-duplicate',
            wa_id=conv.contact.external_id, body='está convulsionando')
        result = {'created': m is not None}
    else:
        witness = durable.claim_turn(conv_id)
        result = {'work': witness.turn_work_id if witness else None}
        if witness:
            if mode == 'detect_crash':
                conv = Conversation.objects.get(pk=conv_id)
                assessment = safety.assess_context(conv, durable.context_for_work(witness))
                if assessment.classification == safety.NO_SIGNAL:
                    raise RuntimeError('Did not detect injected safety')
                os._exit(17)
            if mode == 'handoff_crash':
                from unittest.mock import patch
                with patch('apps.agent.tier0.render_safety_guidance', side_effect=lambda *a: os._exit(17)):
                    worker._run_turn(witness)
            else:
                try:
                    worker._run_turn(witness)
                except durable.OwnershipLost:
                    result['fenced'] = True
    print('B3_RESULT ' + json.dumps(result), flush=True)
    connections.close_all()


if __name__ == '__main__':
    main()
