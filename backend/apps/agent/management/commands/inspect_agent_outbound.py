"""Read-only operational visibility; never retries or rewrites uncertainty."""
import json
from django.core.management.base import BaseCommand
from apps.agent.sender import observe_outbound


class Command(BaseCommand):
    help = 'Cuenta outbounds por estado y muestra edades; no modifica mensajes'

    def add_arguments(self, parser):
        parser.add_argument('--safety', action='store_true', help='Cola handoff y estados de guía B5')

    def handle(self, *args, **options):
        if options['safety']:
            from apps.agent.safety_handoff import observe_handoffs
            self.stdout.write(json.dumps(observe_handoffs(), sort_keys=True))
            return
        self.stdout.write(json.dumps(observe_outbound(), sort_keys=True))
