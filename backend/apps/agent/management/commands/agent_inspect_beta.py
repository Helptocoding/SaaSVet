"""Read-only release/organization gate inspection; never activates a tenant."""
import json

from django.core.management.base import BaseCommand, CommandError
from apps.agent.beta_release import inspect_organization
from apps.organizations.models import Organization


class Command(BaseCommand):
    help = 'Inspect beta approval and existing gates for one explicit organization (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--organization-id', type=int, required=True)

    def handle(self, *args, **options):
        organization_id = options['organization_id']
        if not Organization.objects.filter(pk=organization_id).exists():
            raise CommandError('Organization not found.')
        self.stdout.write(json.dumps(inspect_organization(organization_id), sort_keys=True))
