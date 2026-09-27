"""Read-only inspection for an explicitly selected tenant and TurnWork."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from apps.agent.llm_budget import inspect_turn
from apps.agent.models import TurnWork


class Command(BaseCommand):
    help = 'Inspect B9 operational budget (local authorized operator; no mutation).'

    def add_arguments(self, parser):
        parser.add_argument('--organization-id', type=int, required=True)
        parser.add_argument('--turn-work-id', type=int, required=True)

    def handle(self, *args, **options):
        try:
            result = inspect_turn(organization_id=options['organization_id'],
                                  turn_work_id=options['turn_work_id'])
        except TurnWork.DoesNotExist as exc:
            raise CommandError('TurnWork not found in organization') from exc
        self.stdout.write(json.dumps(result, cls=DjangoJSONEncoder, sort_keys=True))
