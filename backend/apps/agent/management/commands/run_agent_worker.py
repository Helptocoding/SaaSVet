"""
run_agent_worker — Proceso worker del subsistema conversacional (É-F0 PR-5).

Loop: drena entrantes pendientes (inbox-como-cola, SKIP LOCKED) + entrega
salientes (outbox con reintentos). Stateless: N réplicas conviven sin
coordinación (el lock de fila reparte el trabajo).

Despliegue: servicio propio en docker-compose (PR-8), `restart: always`,
misma imagen que el backend. Deadman opcional: exporta
HEALTHCHECK_AGENT_WORKER_URL y el loop pinguea cada ~60 ciclos sanos.

Uso:
    python manage.py run_agent_worker              # loop infinito
    python manage.py run_agent_worker --once       # un ciclo (smoke/tests)
"""
import logging
import signal
import time

import requests
from django.conf import settings as django_settings
from django.core.management.base import BaseCommand

from apps.agent.worker import process_pending_conversations, send_pending_outbound

logger = logging.getLogger('agent.events')

_DEADMAN_EVERY_CYCLES = 60


class Command(BaseCommand):
    help = "Worker del agente: procesa entrantes y entrega salientes (loop)"

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true',
                            help='Un solo ciclo y salir (smoke/tests)')
        parser.add_argument('--poll', type=float, default=2.0,
                            help='Segundos de espera cuando no hay trabajo')
        parser.add_argument('--batch', type=int, default=10)

    def handle(self, *args, **options):
        self._stop = False

        def _graceful(signum, frame):
            self._stop = True

        # SIGTERM = docker stop; SIGINT = Ctrl+C. En Windows dev solo SIGINT.
        for sig_name in ('SIGTERM', 'SIGINT'):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    signal.signal(sig, _graceful)
                except (ValueError, OSError):
                    pass

        logger.info("AGENT_WORKER_STARTED", extra={
            "event": "AGENT_WORKER_STARTED", "once": options['once'],
        })

        cycles = 0
        while not self._stop:
            processed = process_pending_conversations(batch=options['batch'])
            sent = send_pending_outbound(batch=options['batch'] * 2)

            cycles += 1
            if cycles % _DEADMAN_EVERY_CYCLES == 0:
                self._ping_deadman()
                # Pasadas periódicas (baratas, poco frecuentes):
                from apps.agent.policy import (
                    close_inactive_conversations, nudge_abandoned_flows,
                )
                close_inactive_conversations()   # cierre por inactividad (§2.8)
                nudge_abandoned_flows()          # UX-08 recordatorio único

            if options['once']:
                self.stdout.write(
                    f"ciclo único: {processed} conversaciones, {sent} envíos"
                )
                break
            if processed == 0 and sent == 0:
                time.sleep(options['poll'])

        logger.info("AGENT_WORKER_STOPPED", extra={
            "event": "AGENT_WORKER_STOPPED",
        })

    def _ping_deadman(self):
        url = getattr(django_settings, 'HEALTHCHECK_AGENT_WORKER_URL', '')
        if not url:
            return
        try:
            requests.get(url, timeout=5)
        except requests.RequestException:
            # El deadman es telemetría: su caída jamás tumba el worker.
            pass
