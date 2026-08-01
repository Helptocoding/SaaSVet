"""
agent_quality — Revisión semanal de calidad conversacional (É-F3 W3).

El piloto se juega en una pregunta que ninguna métrica de negocio contesta:
**¿esto se siente como una buena recepcionista?** Este comando produce las dos
mitades de la respuesta:

1. Los números (latencia real, turnos por resolución, repregunta, handoff,
   % de audio) — derivados de tablas existentes, sin campos nuevos.
2. La **muestra para leer**: sin lectura humana de transcripts no hay ciclo de
   mejora, solo intuición. Escoge conversaciones de perfiles distintos
   (completadas, escaladas, abandonadas) para no leer siempre las felices.

Uso:
    python manage.py agent_quality                # últimos 7 días, todas las orgs
    python manage.py agent_quality --days 14 --sample 20
    python manage.py agent_quality --org <public_id> --json
"""
import json
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.agent.metrics import (
    compute_conversation_metrics,
    compute_goal_metrics,
    compute_quality_metrics,
)
from apps.agent.models import Conversation, ConversationGoal, HumanHandoff
from apps.organizations.models import Organization

SAMPLE_DEFAULT = 20


class Command(BaseCommand):
    help = "Métricas de calidad conversacional + muestra de transcripts a revisar"

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--sample', type=int, default=SAMPLE_DEFAULT)
        parser.add_argument('--org', type=str, default='',
                            help='public_id de una organización (default: todas)')
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        date_to = timezone.now()
        date_from = date_to - timedelta(days=options['days'])

        orgs = Organization.objects.all()
        if options['org']:
            orgs = orgs.filter(public_id=options['org'])

        report = []
        for org in orgs:
            if not Conversation.objects.filter(
                organization=org,
                created_at__gte=date_from, created_at__lt=date_to,
            ).exists():
                continue
            report.append({
                'organizacion': org.name,
                'conversacion': compute_conversation_metrics(
                    org, date_from, date_to),
                'calidad': compute_quality_metrics(org, date_from, date_to),
                'objetivos': compute_goal_metrics(org, date_from, date_to),
                'revisar': self._sample(org, date_from, date_to,
                                        options['sample']),
            })

        if options['json']:
            self.stdout.write(json.dumps({
                'desde': date_from.isoformat(), 'hasta': date_to.isoformat(),
                'organizaciones': report,
            }, ensure_ascii=False, default=str))
            return

        if not report:
            self.stdout.write("Sin conversaciones en el periodo.")
            return
        for item in report:
            self._render(item, options['days'])

    def _sample(self, org, date_from, date_to, size):
        """Muestra estratificada: escaladas, abandonadas y completadas.

        Leer solo conversaciones felices no enseña nada — las que duelen son
        las que se escalaron y las que se quedaron a medias.
        """
        base = Conversation.objects.filter(
            organization=org,
            created_at__gte=date_from, created_at__lt=date_to,
        )
        escaladas = set(
            HumanHandoff.objects.filter(
                organization=org,
                created_at__gte=date_from, created_at__lt=date_to,
            ).values_list('conversation_id', flat=True)
        )
        abandonadas = set(
            ConversationGoal.objects.filter(
                organization=org,
                created_at__gte=date_from, created_at__lt=date_to,
            ).exclude(status=ConversationGoal.STATUS_COMPLETED)
            .values_list('conversation_id', flat=True)
        ) - escaladas
        resto = set(base.values_list('id', flat=True)) - escaladas - abandonadas

        per_bucket = max(size // 3, 1)
        picked = []
        for bucket in (escaladas, abandonadas, resto):
            ids = list(bucket)
            random.shuffle(ids)
            picked.extend(ids[:per_bucket])

        return [
            {'conversacion': str(pid), 'estado': state}
            for pid, state in Conversation.objects
            .filter(id__in=picked[:size])
            .values_list('public_id', 'state')
        ]

    def _render(self, item, days):
        quality = item['calidad']
        goals = item['objetivos']
        conv = item['conversacion']
        latency = quality['latencia_respuesta_ms']
        turns = quality['turnos_por_resolucion']
        words = conv['palabras_por_mensaje_agente']
        recovered = conv['interrupciones_recuperadas']

        self.stdout.write(f"\n=== {item['organizacion']} — últimos {days} días ===")

        # --- Conversación (É-F5 §9bis): va PRIMERO a propósito ---------------
        # Estas cifras hablan de lo que vive el cliente; las de abajo, del
        # motor. El orden del informe es el mismo argumento del plan.
        self.stdout.write("  · conversación")
        self.stdout.write(
            f"    redactado por el agente {_pct(conv['pct_redactado_por_agente'])}"
            f"   (el resto son plantillas; el 100% NO es la meta)")
        self.stdout.write(
            f"    palabras por mensaje    p50 {words['p50'] or '—'} · "
            f"p90 {words['p90'] or '—'} ({words['muestras']} mensajes)"
            f"   → vigilar la PENDIENTE, no el valor")
        self.stdout.write(
            f"    turnos sin modelo       {_pct(conv['pct_turnos_sin_modelo'])}")
        self.stdout.write(
            f"    salientes repetidos     {conv['salientes_repetidos']}"
            f"{'   ⚠ el agente se repitió palabra por palabra' if conv['salientes_repetidos'] else ''}")
        self.stdout.write(
            f"    interrupciones          {recovered['recuperadas']}/"
            f"{recovered['total']} recuperadas ({_pct(recovered['tasa'])})")

        self.stdout.write("  · motor")
        self.stdout.write(
            f"    latencia de respuesta   p50 {_ms(latency['p50'])} · "
            f"p95 {_ms(latency['p95'])} ({latency['muestras']} respuestas)"
            f"   → es un UMBRAL, no algo a minimizar")
        self.stdout.write(
            f"    turnos por resolución   prom {turns['promedio'] or '—'} · "
            f"p95 {turns['p95'] or '—'} ({turns['muestras']} objetivos)")
        self.stdout.write(
            f"    tasa de repregunta      {_pct(quality['tasa_repregunta'])}"
            f"   (ciega a las plantillas — ver «salientes repetidos»)")
        self.stdout.write(
            f"    tasa de handoff         {_pct(quality['tasa_handoff'])}"
            f"   → diagnóstico, NUNCA un KPI a bajar")
        self.stdout.write(
            f"    audio entrante          {_pct(quality['pct_audio'])}"
            f"{'   ⚠ supera 15%: toca transcripción (UX-14)' if quality['pct_audio'] > 0.15 else ''}")
        self.stdout.write(f"    respuestas descartadas  {quality['respuestas_descartadas']}")
        self.stdout.write(
            f"    objetivos               {goals['completados']}/{goals['abiertos']} "
            f"completados ({_pct(goals['tasa_completado'])})")
        if goals['slots_atorados']:
            atorados = ', '.join(f"{k}×{v}" for k, v in goals['slots_atorados'].items())
            self.stdout.write(f"    se atoran en            {atorados}")

        self.stdout.write("\n  Para leer en /inbox (muestra estratificada):")
        for row in item['revisar']:
            self.stdout.write(f"    {row['conversacion']}  [{row['estado']}]")


def _ms(value):
    return f"{value / 1000:.1f}s" if value is not None else "—"


def _pct(value):
    return f"{(value or 0) * 100:.1f}%"
