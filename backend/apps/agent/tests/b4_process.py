"""Independent interpreter exercising real B4 sender; only isolated test DBs."""
import json
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections, connection
    config = json.loads(os.environ['B4_TEST_DATABASE'])
    if not config['NAME'].startswith('test_'):
        raise RuntimeError('B4 probe requires isolated test database')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent import sender
    from apps.channels.models import Message
    from apps.channels.providers import SendResult
    mode, message_id = sys.argv[1], int(sys.argv[2])
    message = Message.objects.get(pk=message_id)
    print('B4_READY', flush=True)
    sys.stdin.readline()
    claim = sender.claim_message(message_id, organization_id=message.organization_id,
                                 channel_account_id=message.channel_account_id)
    if claim and mode == 'crash_claim':
        os._exit(17)
    if claim and mode == 'before_http':
        print('B4_CLAIMED', flush=True)
        sys.stdin.readline()
    calls = 0
    class Provider:
        def send_text(self, *args):
            nonlocal calls
            calls += 1
            if connection.in_atomic_block:
                raise AssertionError('HTTP under transaction')
            if mode == 'during_http':
                print('B4_HTTP', flush=True)
                sys.stdin.readline()
            return SendResult('accepted', f'wamid.B4process{message_id}')
    if mode == 'crash_accepted':
        def crash(*args):
            os._exit(19)  # valid acceptance already returned; no final DB write
        sender.finalize_dispatch = crash
    if claim:
        sender.dispatch_claim(claim, lambda channel: Provider())
    print('B4_RESULT ' + json.dumps({'claimed': claim is not None, 'http_calls': calls}), flush=True)
    connections.close_all()


if __name__ == '__main__':
    main()
