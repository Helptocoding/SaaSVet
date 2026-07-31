"""É-F4 Fase 3 (ADR p55 §3, R7) — los retos de identidad dejan `flow`.

`identity_triage`, `family_challenge` e `identity_challenge` vivían como tres
dicts sueltos en `Conversation.flow`: un blob que no se agrega, no se mide y se
destruía con un `pop`. Pasan al modelo de compromisos, que ya tenía estado
explícito, ciclo de vida y embudo.

**Migración de las conversaciones vivas.** El plan (§3.2) daba dos opciones —
traducir lo que exista, o cerrar las conversaciones abiertas en la ventana de
despliegue. Se traduce: es igual de barato y no le corta la conversación a
nadie a media verificación. Son unidades, no miles.

El campo nuevo `working_state` recibe lo que era estado de trabajo del dict
(`candidate_ids`, `retried`, `asks`, `deviations`); `stage` pasa a `return_to`
(la dirección de retorno, que es lo que R4 necesitaba y el dict no tenía) y
`fails` a `attempts_failed`.

Reversible: `flow` no se toca al migrar hacia adelante, así que revertir el
código sin revertir el schema deja las conversaciones exactamente como estaban.
"""
from django.db import migrations, models

_KIND_TO_NAME = {
    'identity_triage': 'identity_triage',
    'family_challenge': 'family_challenge',
    'identity_challenge': 'identity_challenge',
}
_FIRST_FACTOR = {
    'identity_triage': 'client_kind',
    'family_challenge': 'pet',
    'identity_challenge': 'pet',
}


def _state_to_commitment(Goal, conversation, kind, state, *, suspended):
    """Traduce un dict de `flow` a una fila de compromiso."""
    state = state or {}
    stage = state.get('stage') or _FIRST_FACTOR[kind]
    # El tamiz usaba 'ask' como primera etapa; el factor se llama `client_kind`.
    if kind == 'identity_triage' and stage == 'ask':
        stage = 'client_kind'

    working = {}
    for key in ('candidate_ids', 'retried', 'asks'):
        if key in state:
            working[key] = state[key]

    slots = {}
    if state.get('titular'):
        slots['titular'] = {'value': state['titular'], 'confidence': 1.0}

    Goal.objects.create(
        organization_id=conversation.organization_id,
        conversation_id=conversation.id,
        name=_KIND_TO_NAME[kind],
        status='suspended' if suspended else 'active',
        return_to=stage[:32],
        attempts_failed=state.get('fails', 0) or 0,
        working_state=working,
        slots=slots,
        missing=[],
        supplanted_by='handoff' if suspended else '',
    )


def flow_to_commitments(apps, schema_editor):
    Conversation = apps.get_model('agent', 'Conversation')
    Goal = apps.get_model('agent', 'ConversationGoal')

    for conversation in Conversation.objects.exclude(state='closed').iterator():
        flow = conversation.flow or {}
        # Un reto AL FRENTE desplaza la tarea: el constraint solo admite uno.
        for kind in _KIND_TO_NAME:
            if flow.get(kind):
                Goal.objects.filter(
                    conversation_id=conversation.id,
                    status__in=('active', 'deviated'),
                ).update(status='suspended', supplanted_by=kind)
                _state_to_commitment(Goal, conversation, kind, flow[kind],
                                     suspended=False)
                break
        else:
            # Sin reto al frente: ¿había uno apartado por la Fase 1?
            parked = flow.get('suspended') or {}
            kind = parked.get('kind')
            if kind in _KIND_TO_NAME:
                # El slot de suspensión es único: la tarea que hubiera se va
                # con el humano, igual que hace `park_identity` en runtime.
                Goal.objects.filter(
                    conversation_id=conversation.id, status='suspended',
                ).update(status='handoff')
                _state_to_commitment(Goal, conversation, kind,
                                     parked.get('state'), suspended=True)


def noop(apps, schema_editor):
    """Sin vuelta atrás: `flow` nunca se vació, así que revertir el código
    basta. Las filas de compromiso quedan huérfanas y no molestan."""


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0012_commitment_lifecycle'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversationgoal',
            name='attempts_failed',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='conversationgoal',
            name='working_state',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(flow_to_commitments, noop),
    ]
