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

---

## `--before` es OBLIGATORIO para degradar (corrección 2026-08-17)

La primera versión degradaba **todo** `confirmed_in_chat` con `linked_via=''`, y
ese predicado **no describe el estado comprometido: describe el estado CORRECTO**.
`identity._promote` —la única vía del reto conversacional— escribe
`verification_level`, `verified_at` y `auto_rematch_blocked`, y **nunca**
`linked_via`; solo lo escriben la vía familiar y la de staff. Así que toda
verificación legítima por nombre de mascota caía en el predicado.

Lo que pasó en producción el mismo día del deploy: el comando quedó en
`release.sh`, el cron de la demo (`10,40 * * * *`) invoca
`docker compose run --rm backend`, y `run` **arranca las dependencias** — entre
ellas el servicio `release`. Resultado: esto corría **cada 30 minutos**. Log
literal de la corrida de las 17:40:

    ANTES  · contactos a degradar: 1
             contacto 1 org=3 verified_at=2026-08-17 17:27:41.865888+00:00

Ese `17:27:41` es el instante en que un cliente se había verificado bien, por el
servicio único, con evidencia sellada en `challenge_response`. Se destruyó 13
minutos después. Y como el historial cruzado se gatea en
`is_verification_current` (D19), la amnesia que este trabajo arregló volvía cada
media hora.

La corrección no es afinar el predicado por contenido —no hay campo que
distinga «verificado por el bypass» de «verificado bien»— sino acotarlo **en el
tiempo**: el bypass dejó de existir al desplegar F0, así que solo es sospechoso
lo verificado ANTES de ese instante. `--before` es esa frontera, y es un dato
del despliegue, no una constante inventada.

Sin `--before` el comando **no degrada nada** (sí cierra retos huérfanos, cuyo
predicado sí es intrínseco). Correrlo por accidente ya no puede borrar una
verificación vigente.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_datetime

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
        parser.add_argument(
            '--before', default=None,
            help='Instante ISO 8601 del despliegue de F0. Solo se degradan las '
                 'verificaciones ANTERIORES. Sin esto no se degrada nada: el '
                 'predicado sin acotar borra las verificaciones legítimas.')

    def handle(self, *args, **options):
        org_id = options['org']
        apply_changes = options['apply']
        cutoff = self._parse_cutoff(options['before'])

        contacts = ContactIdentity.objects.filter(
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            linked_via='',            # ni familiar, ni staff, ni auto-registro
        )
        if cutoff is not None:
            # `verified_at` nulo con `confirmed_in_chat` es un estado que el
            # código nuevo no produce (`_promote` siempre lo estampa): es una
            # fila legacy sin fecha, y por tanto anterior a la frontera.
            contacts = contacts.filter(
                Q(verified_at__lt=cutoff) | Q(verified_at__isnull=True))
        else:
            contacts = contacts.none()
        stale_goals = ConversationGoal.objects.filter(
            name__in=goals.HISTORICAL_IDENTITY_GOALS,
            status__in=ConversationGoal.OPEN_STATUSES,
        )
        if org_id:
            contacts = contacts.filter(organization_id=org_id)
            stale_goals = stale_goals.filter(organization_id=org_id)

        # `linked_via=''` NO identifica al comprometido: es el resultado normal
        # del reto conversacional, porque `_promote` no escribe ese campo. Lo que
        # separa una cosa de la otra es el RELOJ — el bypass murió al desplegar
        # F0 — y de ahí que `--before` sea obligatorio (ver docstring).
        suspects = list(contacts)
        orphans = [goal for goal in stale_goals
                   if goals.is_orphan_identity_goal(goal)]

        if cutoff is None:
            self.stdout.write(self.style.WARNING(
                'SIN --before · no se degrada ningún contacto. El predicado sin '
                'acotar alcanza las verificaciones legítimas (ver docstring).'))
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
            from apps.agent.durable import invalidate_ownership
            from apps.agent.models import Conversation
            affected = Conversation.objects.select_for_update().filter(
                Q(contact_id__in=[c.pk for c in suspects]) |
                Q(pk__in=[g.conversation_id for g in orphans])).order_by('pk')
            for conversation in affected:
                invalidate_ownership(conversation, reason='identity_remediation')
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
        if cutoff is not None:
            remaining = remaining.filter(
                Q(verified_at__lt=cutoff) | Q(verified_at__isnull=True))
        else:
            remaining = remaining.none()
        if org_id:
            remaining = remaining.filter(organization_id=org_id)
        # Se cuenta lo que QUEDA POR REMEDIAR, no «las verificaciones
        # conversacionales que existen». La etiqueta anterior invitaba a leer un
        # estado legítimo como pendiente de limpiar.
        self.stdout.write(self.style.SUCCESS(
            f'DESPUÉS · contactos pendientes de degradar: {remaining.count()} '
            f'· retos huérfanos cerrados: {len(orphans)}'))

    def _parse_cutoff(self, raw):
        """`--before` como instante aware. Un valor inválido es un error, jamás
        un `None` silencioso: caer a «sin frontera» significaría degradar todo."""
        if raw is None:
            return None
        try:
            parsed = parse_datetime(raw)
        except ValueError:
            # `parse_datetime` devuelve None si el FORMATO no encaja, pero
            # propaga ValueError si encaja y el valor es imposible
            # (`2026-13-45T…`). Las dos son lo mismo para el caller.
            parsed = None
        if parsed is None:
            raise CommandError(
                f'--before no es un instante ISO 8601 válido: {raw!r}')
        if parsed.tzinfo is None:
            raise CommandError(
                '--before necesita zona explícita (p.ej. '
                '2026-08-17T02:35:51Z): sin ella la frontera se mueve con el '
                'reloj del contenedor.')
        return parsed
