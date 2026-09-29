"""Historical B8 domain races, independent of B9 planner admission tests.

Before B9, two conversations in one org could already own committed B3 claims.
Seed that legacy state explicitly so domain/constraint protections keep their
multi-process coverage. This is a test fixture, never a planner entry point.
"""
from django.db import transaction

from apps.agent import durable
from apps.agent.models import Conversation


def legacy_parallel_domain_claim(case, conversation):
    case.assertEqual(durable.active_org_work(conversation.organization_id).count(), 1)
    # The actual B9 entry point must refuse this second planner.
    case.assertIsNone(durable.claim_turn(conversation.pk))
    with transaction.atomic():
        locked = Conversation.objects.select_for_update().get(
            pk=conversation.pk, organization_id=conversation.organization_id)
        witness = durable._claim_turn_locked(locked)
    case.assertIsNotNone(witness)
    durable.assert_witness(witness)
    return witness
