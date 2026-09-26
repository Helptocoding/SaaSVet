"""
agent_eval_conversations — Application E2E or legacy planner diagnostic.

--application-e2e uses the B9A signed HTTP/worker/sender scripts with committed
test fixtures and controlled external wire. B9 integral acceptance is pending.
The description below concerns the historical real-LLM component mode only.

`agent_eval` mide escenarios de UN mensaje. Todo lo que É-F5 cambió es
multi-turno: el fallo del piloto tardó cinco turnos en aparecer y la conv 12
necesitó cuatro repeticiones del mismo dato. Ninguna de las dos cosas cabe en
un escenario de un mensaje, así que hasta aquí el rediseño no tenía forma de
medirse contra un modelo real.

QUÉ MIDE, y por qué estas y no otras (plan É-F5 §9bis):

    % redactado por el agente   marcador directo de la tesis. Era ~5 %.
                                NO es un objetivo a maximizar: el techo lo
                                ponen las salvaguardas, que son plantilla por
                                diseño.
    palabras por mensaje        detector de DERIVA (p50/p90), no un límite.
                                Liberar al modelo mueve la artificialidad de
                                "15 palabras rígidas" a "180 amables".
    identify_client/conversación  el riesgo §11.4. La Fase 2 cambió la
                                verificación de garantizada-por-FSM a
                                dependiente-de-que-el-modelo-llame. Si esto
                                sale bajo, la regresión de servicio es real.
    salientes repetidos         C7 sobre texto que el modelo escribió de
                                verdad (en la suite lo escribe el guion).
    handoff por identidad       un cliente legítimo no debe acabar con una
                                persona por no saber contestar un reto.

EL GUION ES DEL CLIENTE, NO DEL AGENTE. Los turnos del cliente están fijos; el
agente responde con el modelo real. Es lo contrario de la suite, donde el guion
del stub es mío y afirmar sobre su texto sería circular.

Aislamiento: todo dentro de una transacción que revierte (igual que
`agent_eval`), con el transporte EN PROCESO para que los fixtures sean visibles
— ver `InProcessTransport` y el defecto que arregló.

Uso:
    python manage.py agent_eval_conversations
    python manage.py agent_eval_conversations --json
    python manage.py agent_eval_conversations --repeat 3
"""
import json as jsonlib
import statistics

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from .agent_eval import Command as EvalCommand
from .agent_eval import InProcessTransport, _Rollback


# Cada conversación: (nombre, cómo llega el contacto, [turnos del cliente]).
# `contact`: 'verified' (cliente conocido), 'unknown' (número sin registro).
CONVERSATIONS = [
    (
        "brief · da su nombre sin que se lo pidan",
        'unknown',
        ["hola", "quiero una cita para mi mascota"],
        ["ya he ido antes", "mi nombre es Ana Torres"],
        ["ya te dije, Ana Torres"],
        ["¿por qué me lo preguntas otra vez?"],
    ),
    (
        "conv 12 · el mismo dato pedido una y otra vez",
        'verified',
        ["quiero agendar una cita para Luna"],
        ["es para una revisión"],
        ["lo que tengas disponible"],
        ["cuando puedas, me da igual"],
    ),
    (
        "conv 13 · familiar con los tres factores",
        'unknown',
        ["hola, quiero agendar para Luna"],
        ["soy familiar de Ana Torres"],
        ["¿para qué necesitas eso?"],
        ["los últimos 4 son 0088"],
    ),
]


class Command(BaseCommand):
    help = "Evaluación conversacional MULTI-TURNO con LLM real (É-F5)"

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        from ..e2e_evaluation import add_arguments
        add_arguments(parser)
        parser.add_argument('--repeat', type=int, default=1,
                            help='corridas por conversación (el modelo varía)')

    def handle(self, *args, **options):
        from ..e2e_evaluation import run
        if run(self, options, conversations=True):
            return
        if not getattr(settings, 'AGENT_LLM_API_KEY', ''):
            msg = "agent_eval_conversations: LLM no configurado — skip."
            self.stdout.write(msg if not options['json']
                              else jsonlib.dumps({"skipped": True, "scope": "planner_component", "beta_acceptance": "PENDING"}))
            return

        runs = []
        try:
            with transaction.atomic():
                # UNA sola siembra para todas las conversaciones: `_seed` crea
                # un ChannelAccount con `external_account_id` fijo, que es
                # único global — sembrar por conversación choca en la segunda.
                ctx = EvalCommand()._seed()
                for index, scenario in enumerate(CONVERSATIONS):
                    for run in range(options['repeat']):
                        runs.append(self._run(ctx, scenario,
                                              tag=f"{index}-{run}"))
                raise _Rollback()
        except _Rollback:
            pass

        report = self._aggregate(runs)
        if options['json']:
            self.stdout.write(jsonlib.dumps(
                {'scope': 'planner_component', 'beta_acceptance': 'PENDING',
                 'conversaciones': runs, 'global': report},
                ensure_ascii=False, default=str))
            return
        self._render(runs, report)

    # -- ejecución ---------------------------------------------------------

    def _run(self, ctx, scenario, *, tag):
        from apps.agent import planner
        from apps.agent.executor import ToolExecutor
        from apps.agent.models import (
            AgentSettings, ContactIdentity, Conversation, HumanHandoff,
            ToolExecution,
        )
        from apps.channels.models import Message

        name, contact_kind, *client_turns = scenario

        if contact_kind == 'verified':
            contact = ctx['contact']
        else:
            contact = ContactIdentity.objects.create(
                organization=ctx['org'], external_id=f'52155999{tag}',
                owner=None,
                verification_level=ContactIdentity.VERIFICATION_UNKNOWN,
            )
        conv = Conversation.objects.create(
            organization=ctx['org'], channel_account=ctx['channel'],
            contact=contact,
            flow={'refs': {'mascota_1': str(ctx['pet'].public_id),
                           'cita_1': str(ctx['appt'].public_id)}},
        )
        agent_settings = AgentSettings.objects.get(organization=ctx['org'])

        transcript = []
        for burst in client_turns:
            for body in burst:
                Message.objects.create(
                    organization=ctx['org'], channel_account=ctx['channel'],
                    conversation=conv, direction=Message.DIRECTION_IN,
                    author_type=Message.AUTHOR_CLIENT, body=body,
                    status=Message.STATUS_PROCESSED,
                )
            before = set(Message.objects.filter(
                conversation=conv, direction=Message.DIRECTION_OUT,
            ).values_list('id', flat=True))
            try:
                planner.handle_inbound(
                    conv, agent_settings=agent_settings, burst=list(burst),
                    executor=ToolExecutor(conv, ctx['agent_user'],
                                          transport=InProcessTransport()),
                )
            except Exception as exc:                      # el LLM real falla
                transcript.append(('ERROR', f"{exc.__class__.__name__}: {exc}"))
                break
            salientes = list(Message.objects.filter(
                conversation=conv, direction=Message.DIRECTION_OUT,
            ).exclude(id__in=before).exclude(status=Message.STATUS_DISCARDED)
                .order_by('id').values_list('author_type', 'body'))
            transcript.append(('C', ' | '.join(burst)))
            transcript.extend(salientes)

        return {
            'nombre': name,
            'transcript': [list(t) for t in transcript],
            **self._measure(conv, ctx, ToolExecution, HumanHandoff, Message),
        }

    # -- medición ----------------------------------------------------------

    def _measure(self, conv, ctx, ToolExecution, HumanHandoff, Message):
        salientes = list(Message.objects.filter(
            conversation=conv, direction=Message.DIRECTION_OUT,
        ).exclude(status=Message.STATUS_DISCARDED)
            .order_by('id').values_list('author_type', 'body'))

        del_agente = [b for a, b in salientes if a == 'agent']
        repetidos = sum(1 for i in range(1, len(salientes))
                        if (salientes[i][1] or '').strip()
                        == (salientes[i - 1][1] or '').strip())
        palabras = [len((b or '').split()) for b in del_agente]

        return {
            'salientes': len(salientes),
            'redactados_por_el_agente': len(del_agente),
            'pct_redactado': (round(len(del_agente) / len(salientes), 3)
                              if salientes else 0.0),
            'palabras': palabras,
            'salientes_repetidos': repetidos,
            'identify_client': ToolExecution.objects.filter(
                conversation=conv, tool_name='identify_client').count(),
            'verificado_al_final': conv.contact.verification_level in (
                'confirmed_in_chat', 'staff_verified'),
            'handoff_identidad': HumanHandoff.objects.filter(
                conversation=conv,
                reason_code=HumanHandoff.REASON_IDENTITY).exists(),
        }

    def _aggregate(self, runs):
        salientes = sum(r['salientes'] for r in runs)
        agente = sum(r['redactados_por_el_agente'] for r in runs)
        palabras = [w for r in runs for w in r['palabras']]
        return {
            'pct_redactado_por_agente': (round(agente / salientes, 3)
                                         if salientes else 0.0),
            'palabras_p50': (round(statistics.median(palabras), 1)
                             if palabras else None),
            'palabras_p90': (sorted(palabras)[int(len(palabras) * 0.9) - 1]
                             if len(palabras) >= 2 else None),
            'salientes_repetidos': sum(r['salientes_repetidos'] for r in runs),
            'identify_client_total': sum(r['identify_client'] for r in runs),
            'handoffs_identidad': sum(1 for r in runs
                                      if r['handoff_identidad']),
        }

    def _render(self, runs, g):
        for r in runs:
            self.stdout.write(f"\n=== {r['nombre']} ===")
            for autor, texto in r['transcript']:
                etiqueta = {'C': 'cliente ', 'agent': 'AGENTE  ',
                            'system': 'plantilla'}.get(autor, autor)
                self.stdout.write(f"  {etiqueta} | {(texto or '')[:150]}")
            self.stdout.write(
                f"  → redactó {r['redactados_por_el_agente']}/{r['salientes']}"
                f" · identify_client x{r['identify_client']}"
                f" · verificado={r['verificado_al_final']}"
                f" · repetidos={r['salientes_repetidos']}"
                f" · handoff_identidad={r['handoff_identidad']}")

        self.stdout.write("\n=== GLOBAL (plan É-F5 §9bis) ===")
        self.stdout.write(
            f"  redactado por el agente   {g['pct_redactado_por_agente'] * 100:.1f}%"
            f"   (línea base É-F5: ~5%; el 100% NO es la meta)")
        self.stdout.write(
            f"  palabras por mensaje      p50 {g['palabras_p50']} · "
            f"p90 {g['palabras_p90']}   → vigilar la PENDIENTE")
        self.stdout.write(
            f"  identify_client           {g['identify_client_total']} llamadas"
            f"   ← si es 0, la regresión de servicio de Fase 2 es real")
        self.stdout.write(f"  salientes repetidos       {g['salientes_repetidos']}")
        self.stdout.write(f"  handoffs por identidad    {g['handoffs_identidad']}")
