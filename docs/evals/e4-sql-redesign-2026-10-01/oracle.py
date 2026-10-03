"""Synthetic, deterministic old-vs-candidate selector oracle on isolated PostgreSQL."""
import json
import os
import random
import sys
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.db import connection, transaction
from django.utils import timezone
from apps.agent import worker
from apps.agent.models import ContactIdentity, Conversation, TurnWork
from apps.agent.tests.e4_sql_oracle import old_selector
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from candidates import selector_one_query, selector_two_queries, _selector


def main():
    assert connection.vendor == 'postgresql'
    assert connection.settings_dict['NAME'].startswith('test_e4_sql_redesign_')
    clock = timezone.now()
    orgs = Organization.objects.bulk_create([
        Organization(name=f'oracle-org-{j}', timezone='UTC') for j in range(5)])
    channels = ChannelAccount.objects.bulk_create([
        ChannelAccount(organization=org, external_account_id=f'oracle-account-{j}')
        for j, org in enumerate(orgs)])
    contacts = ContactIdentity.objects.bulk_create([
        ContactIdentity(organization=org, external_id=f'oracle-contact-{j}')
        for j, org in enumerate(orgs)])
    historical = Conversation.objects.bulk_create([
        Conversation(organization=orgs[j], channel_account=channels[j],
                     contact=contacts[j], last_activity_at=clock-timedelta(hours=2))
        for j in (0, 1, 3, 4)])
    anchors = Message.objects.bulk_create([
        Message(organization=orgs[j], channel_account=channels[j], contact=contacts[j],
                conversation=historical[k], direction='in', author_type='client',
                status='processed', available_at=clock-timedelta(hours=2))
        for k, j in enumerate((0, 1, 3, 4))])
    works = TurnWork.objects.bulk_create([
        TurnWork(organization=orgs[j], conversation=historical[k], anchor_message=anchors[k],
                 anchor_created_at=anchors[k].created_at, cursor_message_id=anchors[k].pk,
                 cursor_created_at=anchors[k].created_at, context_at=anchors[k].created_at,
                 clinic_timezone='UTC', status=TurnWork.COMPLETED,
                 claimed_at=clock-timedelta(minutes={0:2, 1:3, 3:1, 4:2}[j]),
                 completed_at=clock-timedelta(minutes=1), outcome_code='completed')
        for k, j in enumerate((0, 1, 3, 4))])
    conversations = Conversation.objects.bulk_create([
        Conversation(organization=orgs[j], channel_account=channels[j], contact=contacts[j],
                     last_activity_at=clock-timedelta(seconds=10-i))
        for j in range(5) for i in range(2)])
    messages = Message.objects.bulk_create([
        Message(organization=orgs[j], channel_account=channels[j], contact=contacts[j],
                conversation=conversations[j*2+i], direction='in', author_type='client',
                status='pending', available_at=clock+timedelta(seconds=2))
        for j in range(5) for i in range(2)])
    org_for_conversation = {c.pk: c.organization_id for c in conversations}
    cases = [
        ('healthy_ready', {0:'ready'}),
        ('two_healthy_ready', {0:'ready',2:'ready'}),
        ('healthy_noisy_ready', {0:'ready',1:'ready',2:'near'}),
        ('near_ready', {0:'ready',2:'near'}),
        ('far_future', {0:'ready',2:'far'}),
        ('busy_upcoming', {0:'ready',2:'near'}, {1}),
        ('busy_current', {0:'ready',2:'ready'}, {0}),
        ('never_claimed', {0:'ready',4:'near'}),
        ('less_recent_claim', {0:'ready',2:'near'}),
        ('more_recent_claim', {2:'ready',6:'near'}),
        ('same_claim_boundary', {0:'ready',8:'near'}),
        ('pending_safety', {0:'safety',2:'near'}),
        ('safety_after_w1', {0:'safety',2:'near',4:'ready'}),
        ('monotonic_ready_join', {0:'ready',1:'ready',2:'near'}),
        ('multiple_conversations_one_org', {0:'ready',1:'ready'}),
        ('multiple_orgs', {0:'ready',2:'ready',4:'ready',6:'ready',8:'ready'}),
        ('candidate_disappears', {0:'ready',2:'near'}, set(), {2}),
        ('stale_observation', {0:'ready',2:'near'}, {1}),
        ('deadline_before', {0:'ready',2:'near'}),
        ('deadline_after', {0:'ready',2:'near'}, set(), set(), 1),
        ('no_eligible_candidate', {}),
    ]
    rng = random.Random(20261001)
    for i in range(300):
        layout = {j:rng.choice(('ready','near','far','off','safety')) for j in range(10)}
        busy = {j for j in range(5) if rng.random() < .25}
        gone = {j for j in range(10) if rng.random() < .12}
        offset = rng.choice((0, .5, 1))
        cases.append((f'generated_{i:03}', layout, busy, gone, offset))
    mismatches = []
    manual = []
    selected_lengths = []
    statement_counts = []
    for case in cases:
        name, layout = case[:2]
        busy = case[2] if len(case) > 2 else set()
        gone = case[3] if len(case) > 3 else set()
        offset = case[4] if len(case) > 4 else 0
        with transaction.atomic():
            for j, message in enumerate(messages):
                state = layout.get(j, 'far')
                if state == 'ready' or state == 'safety':
                    available = clock-timedelta(seconds=1)
                elif state == 'near':
                    available = clock+timedelta(milliseconds=500)
                else:
                    available = clock+timedelta(seconds=2)
                Message.objects.filter(pk=message.pk).update(
                    status='processed' if j in gone or state == 'off' else 'pending',
                    available_at=available,
                    semantic_type=Message.SEMANTIC_SAFETY_SIGNAL if state == 'safety' else '')
            for k, work in enumerate(works):
                j = (0,1,3,4)[k]
                TurnWork.objects.filter(pk=work.pk).update(
                    status=TurnWork.PROCESSING if j in busy else TurnWork.COMPLETED,
                    attempts=1 if j in busy else 0,
                    lease_token=uuid.UUID(int=j+1) if j in busy else None,
                    lease_expires_at=clock+timedelta(minutes=5) if j in busy else None)
            now = clock+timedelta(seconds=offset)
            # Diagnostic control: an empty future relation disables only forecast.
            # An empty selection alone does not distinguish yield from no eligibility.
            without_forecast = list(_selector(now, (), []))
            old = list(old_selector(now=now))
            old_orgs = [org_for_conversation[x] for x in old]
            variants = (('NEW', worker._pending_conversation_candidates),) if '--post' in sys.argv else (
                ('A', selector_one_query), ('B', selector_two_queries))
            for label, candidate in variants:
                statements = []
                def observe(execute, query, params, many, context):
                    statements.append(query)
                    return execute(query, params, many, context)
                with connection.execute_wrapper(observe):
                    new = list(candidate(now=now))
                new_orgs = [org_for_conversation[x] for x in new]
                expected_queries = 2 if label == 'B' else 1
                if old != new or old_orgs != new_orgs or len(statements) != expected_queries:
                    mismatches.append(dict(case=name, variant=label, old=old, new=new,
                        old_orgs=old_orgs, new_orgs=new_orgs, statements=len(statements)))
                selected_lengths.append(len(new))
                statement_counts.append(len(statements))
                if not name.startswith('generated_'):
                    manual.append(dict(case=name, variant=label, old_conversation_ids=old,
                        new_conversation_ids=new, old_org_ids=old_orgs, new_org_ids=new_orgs,
                        selection_without_forecast=without_forecast,
                        selection_empty_old=len(old)==0, selection_empty_new=len(new)==0,
                        yield_old=old!=without_forecast, yield_new=new!=without_forecast,
                        query_count=len(statements)))
            transaction.set_rollback(True)
    output = dict(seed=20261001, manual_states=len(cases)-300, generated_states=300,
        states_tested=len(cases), variant_evaluations=len(cases)*(1 if '--post' in sys.argv else 2),
        phase='post' if '--post' in sys.argv else 'design',
        yield_definition='Advisory ordered selection differs from the same selector with an empty future organization relation',
        decision_mismatches=len(mismatches),
        mismatches=mismatches[:20], candidate_limit=max(selected_lengths),
        query_count_min=min(statement_counts), query_count_max=max(statement_counts),
        manual=manual)
    print(json.dumps(output, indent=2, default=str))
    if mismatches:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
