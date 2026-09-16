"""Read-only operational visibility; never retries or rewrites uncertainty."""
import json
from django.core.management.base import BaseCommand
from apps.agent.sender import observe_outbound


class Command(BaseCommand):
    help = 'Cuenta outbounds por estado y muestra edades; no modifica mensajes'

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(observe_outbound(), sort_keys=True))
