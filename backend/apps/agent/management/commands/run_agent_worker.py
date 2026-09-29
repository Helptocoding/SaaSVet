"""
run_agent_worker — Proceso worker del subsistema conversacional (É-F0 PR-5).

Loop B4: modo planner para TurnWork; modo sender para Message. Default both
conserva el comando anterior. Claims DB cortos, HTTP fuera de transacción,
incertidumbre durable y reintentos solo de rechazos conocidos seguros.

Despliegue: servicio propio en docker-compose (PR-8), `restart: always`,
misma imagen que el backend. Deadman opcional: exporta
HEALTHCHECK_AGENT_WORKER_URL y el loop pinguea cada ~60 ciclos sanos.

Uso:
    python manage.py run_agent_worker              # loop infinito
    python manage.py run_agent_worker --once       # un ciclo (smoke/tests)
    python manage.py run_agent_worker --mode sender # proceso independiente
"""
import logging
import signal
import time

import requests
from django.conf import settings as django_settings
from django.core.management.base import BaseCommand, CommandError

from apps.agent.worker import process_pending_conversations, send_pending_outbound

logger = logging.getLogger('agent.events')

_DEADMAN_EVERY_CYCLES = 60


class Command(BaseCommand):
    help = "Worker del agente: procesa entrantes y entrega salientes (loop)"

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true',
                            help='Un solo ciclo y salir (smoke/tests)')
        parser.add_argument('--poll', type=float, default=1.0,
                            help='Segundos de espera cuando no hay trabajo')
        parser.add_argument('--batch', type=int, default=10)
        parser.add_argument('--mode', choices=('planner', 'sender', 'both'), default='both',
                            help='B4: planner y sender pueden ejecutarse por separado')

    def handle(self, *args, **options):
        if not 1 <= options['batch'] <= 50 or not 0.1 <= options['poll'] <= 60:
            raise CommandError('batch debe ser 1..50 y poll 0.1..60 segundos')
        self._stop = False
        self._mode = options['mode']

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
            processed = (process_pending_conversations(batch=options['batch'])
                         if options['mode'] != 'sender' else 0)
            sent = (send_pending_outbound(batch=options['batch'] * 2)
                    if options['mode'] != 'planner' else 0)

            cycles += 1
            if cycles % _DEADMAN_EVERY_CYCLES == 0:
                self._ping_deadman()
                # Pasadas periódicas (baratas, poco frecuentes):
                if options['mode'] != 'sender':
                    from apps.agent.policy import close_inactive_conversations, nudge_abandoned_flows
                    close_inactive_conversations()
                    nudge_abandoned_flows()
                if options['mode'] != 'planner':
                    from apps.agent.sender import observe_outbound
                    observe_outbound()

            if options['once']:
                self.stdout.write(
                    f"ciclo único: {processed} conversaciones, {sent} envíos"
                )
                break
            time.sleep(options['poll'])  # bounded even under conflicts/backlog

        logger.info("AGENT_WORKER_STOPPED", extra={
            "event": "AGENT_WORKER_STOPPED",
        })

    def _ping_deadman(self):
        key = ('HEALTHCHECK_AGENT_SENDER_URL' if self._mode == 'sender'
               else 'HEALTHCHECK_AGENT_WORKER_URL')
        url = getattr(django_settings, key, '')
        if not url:
            return
        try:
            requests.get(url, timeout=5)
        except requests.RequestException:
            # El deadman es telemetría: su caída jamás tumba el worker.
            pass
