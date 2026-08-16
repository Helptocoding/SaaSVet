"""
remediate_identity_f0 — Remediación de datos previa a F1a (plan de continuidad).

Dos cosas que el código nuevo NO arregla por sí solo, porque son filas que ya
existen:

1. **Contactos verificados por el bypass** (§0.2). Antes de F0, el nombre del
   titular viajaba al modelo con solo `phone_match`; el modelo lo pasaba a
   `identify_client` y el sistema lo verificaba contra el dato que él mismo había
   suministrado. En producción hay uno así. Se degrada a `phone_match`.

2. **Retos de identidad de la FSM retirada** (D37). `identity_triage` es
   maquinaria que É-F5 Fase 2 retiró, pero `policy` reanimaba cualquier
   suspendido que perteneciera a `IDENTITY_GOALS` — así que una fila de hace
   semanas volvía al frente arrastrando un `GoalSpec` que ya no conduce nadie.
   El código ya exige `is_resumable_identity_goal`; esto cierra las filas.

**Precondición de F1a, no limpieza posterior** (D16): F1a le dice al modelo que
confíe en `verificado: true` y lo use. Desplegarla antes de degradar consolidaría
un estado obtenido por el bypass.

Es **idempotente** y registra conteos antes/después: correrlo dos veces no cambia
nada más. El orden importa y no es intercambiable — primero el código impide la
resurrección (ya desplegado con F0), después se cierran las filas; al revés queda
una ventana en la que lo cerrado vuelve por otra vía.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.agent import goals
from apps.agent.models import ContactIdentity, ConversationGoal


class Command(BaseCommand):
    help = ('Degrada los contactos verificados por el bypass de identidad y '
            'cierra los retos de la FSM retirada (plan de continuidad, F0).')

    def add_arguments(self, parser):
        parser.add_argument(
            '--org', type=int, default=None,
            help='Limitar a una organización (por PK).')
        parser.add_argument(
            '--apply', action='store_true',
            help='Escribir. Sin esto solo informa (dry-run por defecto).')

    def handle(self, *args, **options):
        org_id = options['org']
        apply_changes = options['apply']

        contacts = ContactIdentity.objects.filter(
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            linked_via='',            # ni familiar, ni staff, ni auto-registro
        )
        stale_goals = ConversationGoal.objects.filter(
            name__in=goals.HISTORICAL_IDENTITY_GOALS,
            status__in=ConversationGoal.OPEN_STATUSES,
        )
        if org_id:
            contacts = contacts.filter(organization_id=org_id)
            stale_goals = stale_goals.filter(organization_id=org_id)

        # Solo los que quedaron verificados SIN una vía auditada. `linked_via`
        # distingue: `family_challenge`/`staff`/`self_register` pasaron por un
        # guard propio; el vacío con `confirmed_in_chat` es el reto conversacional
        # — el que el bypass podía superar con un nombre filtrado.
        suspects = list(contacts)
        orphans = [goal for goal in stale_goals
                   if goals.is_orphan_identity_goal(goal)]

        self.stdout.write(f'ANTES  · contactos a degradar: {len(suspects)}')
        for contact in suspects:
            self.stdout.write(
                f'         contacto {contact.pk} org={contact.organization_id} '
                f'verified_at={contact.verified_at}')
        self.stdout.write(f'ANTES  · retos huérfanos: {len(orphans)}')
        for goal in orphans:
            self.stdout.write(
                f'         goal {goal.pk} {goal.name} status={goal.status} '
                f'conv={goal.conversation_id}')

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                'DRY-RUN · nada escrito. Re-ejecutar con --apply.'))
            return

        with transaction.atomic():
            for contact in suspects:
                contact.verification_level = (
                    ContactIdentity.VERIFICATION_PHONE_MATCH)
                contact.verified_at = None
                contact.save(update_fields=['verification_level',
                                            'verified_at'])
            for goal in orphans:
                goals.close(goal, ConversationGoal.STATUS_ABANDONED,
                            'retired_machinery')

        remaining = ContactIdentity.objects.filter(
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            linked_via='',
        )
        if org_id:
            remaining = remaining.filter(organization_id=org_id)
        self.stdout.write(self.style.SUCCESS(
            f'DESPUÉS · contactos con verificación conversacional: '
            f'{remaining.count()} · retos huérfanos cerrados: {len(orphans)}'))
