"""
test_identity_evidence.py — El factor único y su régimen probatorio (F0).

Protege lo que el plan de continuidad (`docs/agent-continuity-plan.md`) cerró
tras trece revisiones. Los casos vienen de defectos REALES de producción, no de
hipótesis: la conv 18 verificó a un contacto contra un nombre que el propio
sistema le había filtrado, y la ruta pasiva promovía con «¿va a haber sol
mañana?» si la mascota se llamaba Sol.
"""
import re
from datetime import timedelta
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.agent import goals, identity, identity_evidence
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    ConversationGoal,
)
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet


class EvidenceTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Ev Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="900100900",
        )
        self.owner = Owner.objects.create(
            organization=self.org, name="Andrés Ruiz", phone="5511445566",
        )
        self.pet = Pet.objects.create(
            organization=self.org, owner=self.owner, name="Luna",
            species="perro", birth_date="2021-01-01",
        )
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511445566",
            owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_PHONE_MATCH,
        )
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact,
        )
        AgentSettings.objects.create(organization=self.org, enabled=True)

    def _in(self, text, **extra):
        return Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, body=text,
            status=Message.STATUS_PENDING, **extra,
        )

    def _out(self, text, *, status=Message.STATUS_SENT,
             author=Message.AUTHOR_AGENT):
        return Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_OUT,
            author_type=author, body=text, status=status,
        )

    def _resolve(self, *texts):
        messages = [self._in(text) for text in texts]
        return identity_evidence.resolve_pet_evidence(self.conv, messages)


class GrammarTests(EvidenceTestCase):
    """§2.3.1 · gramática cerrada. Lo que no reconoce, NO promueve."""

    def test_clinical_frame_is_evidence(self):
        resolution = self._resolve("quiero una cita para Luna")
        self.assertIsInstance(resolution, identity_evidence.SealedPetEvidence)
        self.assertEqual(resolution.registered_name, "Luna")

    def test_possessive_frame_is_evidence(self):
        self.assertIsInstance(self._resolve("mi perrita se llama Luna"),
                              identity_evidence.SealedPetEvidence)

    def test_state_verb_frame_is_evidence(self):
        self.assertIsInstance(self._resolve("Luna necesita revisión"),
                              identity_evidence.SealedPetEvidence)

    def test_clinical_negation_is_still_evidence(self):
        """«Luna no come» es de los mensajes clínicos más importantes que manda
        un cliente. Una regla ciega sobre `no` lo tiraba."""
        self.assertIsInstance(self._resolve("Luna no come desde ayer"),
                              identity_evidence.SealedPetEvidence)

    def test_bare_token_is_not_evidence(self):
        self.assertIsInstance(self._resolve("anoche vi la luna"),
                              identity_evidence.NoEvidence)

    def test_loose_para_without_clinical_noun_is_not_evidence(self):
        """El marco laxo aceptaba «¿venden lentes para sol?» con una mascota
        llamada Sol. «Match exacto» prueba qué palabra apareció, no por qué."""
        self.assertIsInstance(self._resolve("¿venden lentes para Luna?"),
                              identity_evidence.NoEvidence)

    def test_identity_negation_is_not_evidence(self):
        self.assertIsInstance(self._resolve("no es Luna"),
                              identity_evidence.NoEvidence)

    def test_metalinguistic_question_is_not_evidence(self):
        self.assertIsInstance(self._resolve("¿es luna llena?"),
                              identity_evidence.NoEvidence)

    def test_third_party_se_llama_is_not_evidence(self):
        """`se llama` suelto aceptaba «el producto se llama Luna»."""
        self.assertIsInstance(self._resolve("el producto se llama Luna"),
                              identity_evidence.NoEvidence)

    def test_punctuation_does_not_break_the_token(self):
        self.assertIsInstance(self._resolve("cita para Luna, por favor"),
                              identity_evidence.SealedPetEvidence)

    def test_short_name_of_a_compound_registered_pet(self):
        """Con «Luna Bella» registrada, «cita para Luna» tiene que funcionar: el
        reto rechazaba el nombre de pila y mandaba a handoff a quien decía la
        verdad."""
        self.pet.name = "Luna Bella"
        self.pet.save(update_fields=["name"])
        resolution = self._resolve("cita para Luna")
        self.assertIsInstance(resolution, identity_evidence.SealedPetEvidence)
        self.assertEqual(resolution.registered_name, "Luna Bella")

    def test_two_pets_with_the_same_name_do_not_invalidate(self):
        """Candidato único = un NOMBRE distinto, no una fila `Pet`."""
        Pet.objects.create(
            organization=self.org, owner=self.owner, name="Luna",
            species="gato", birth_date="2022-01-01",
        )
        self.assertIsInstance(self._resolve("cita para Luna"),
                              identity_evidence.SealedPetEvidence)

    def test_two_distinct_names_are_ambiguous(self):
        Pet.objects.create(
            organization=self.org, owner=self.owner, name="Toby",
            species="perro", birth_date="2022-01-01",
        )
        self.assertIsInstance(self._resolve("cita para Luna y para Toby"),
                              identity_evidence.NoEvidence)

    def test_typo_is_not_evidence_in_free_text(self):
        self.assertIsInstance(self._resolve("cita para Lunna"),
                              identity_evidence.NoEvidence)


class AntiEchoTests(EvidenceTestCase):
    """D7c/D6 · primera mención gana, y la revelación se busca TOLERANTE."""

    def test_staff_saying_the_name_first_is_an_echo(self):
        self._out("¿Cómo sigue Luna?", author=Message.AUTHOR_HUMAN)
        resolution = self._resolve("cita para Luna")
        self.assertIsInstance(resolution, identity_evidence.EchoRejected)

    def test_echo_detection_tolerates_a_typo_in_the_disclosure(self):
        """Staff escribe «Lunna»; con el matcher estricto el eco no se detectaba
        y «Luna» del cliente promovía sobre un factor sembrado."""
        self._out("¿Cómo sigue Lunna?", author=Message.AUTHOR_HUMAN)
        self.assertIsInstance(self._resolve("cita para Luna"),
                              identity_evidence.EchoRejected)

    def test_client_first_then_system_is_not_an_echo(self):
        self._in("cita para Luna")
        self._out("Claro, ¿para qué día quieres la cita de Luna?")
        self.assertIsInstance(self._resolve("mañana, cita para Luna"),
                              identity_evidence.SealedPetEvidence)

    def test_a_failed_outbound_is_not_a_disclosure(self):
        """El cliente nunca lo vio: contarlo rechazaría un factor legítimo."""
        self._out("¿Cómo sigue Luna?", status=Message.STATUS_FAILED)
        self.assertIsInstance(self._resolve("cita para Luna"),
                              identity_evidence.SealedPetEvidence)

    def test_a_pending_outbound_is_not_a_disclosure(self):
        self._out("¿Cómo sigue Luna?", status=Message.STATUS_PENDING)
        self.assertIsInstance(self._resolve("cita para Luna"),
                              identity_evidence.SealedPetEvidence)

    def test_echo_rejected_cannot_be_verified(self):
        """D33 · no es algo que haya que acordarse de no hacer."""
        self._out("¿Cómo sigue Luna?", author=Message.AUTHOR_HUMAN)
        resolution = self._resolve("cita para Luna")
        self.assertFalse(hasattr(resolution, 'sealed'))
        with self.assertRaises(TypeError):
            identity_evidence.verify_pet_evidence(self.conv, resolution)

    def test_echo_never_mutates_identity(self):
        self._out("¿Cómo sigue Luna?", author=Message.AUTHOR_HUMAN)
        self._resolve("cita para Luna")
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_PHONE_MATCH)
        self.conv.refresh_from_db()
        self.assertNotIn(identity_evidence.FLOW_KEY, self.conv.flow)


class MatchModeTests(EvidenceTestCase):
    """D35 · el régimen probatorio lo deriva el SERVIDOR, nunca el caller."""

    def _challenge(self, *, asked_state='emitted', pet_pending=True,
                   clause=True, status=Message.STATUS_SENT, asked_at=None):
        commitment = goals.start_identity(
            self.conv, goals.TITULAR_CHALLENGE, first_factor='pet')
        question = self._out("¿cómo se llama tu mascota?", status=status)
        commitment.working_state = {'identity_question': {
            'message_id': question.pk,
            'asked_state': asked_state,
            'pet_pending': pet_pending,
            'deterministic_clause': clause,
            'asked_at': (asked_at or timezone.now()).isoformat(),
        }}
        commitment.save(update_fields=['working_state'])
        return commitment, question

    def test_without_challenge_the_mode_is_passive(self):
        message = self._in("¿es luna llena?")
        self.assertEqual(
            identity_evidence.derive_match_mode(self.conv, message),
            identity_evidence.MODE_PASSIVE,
        )

    def test_emitted_question_enables_the_tolerant_mode(self):
        self._challenge()
        message = self._in("Lunna")
        self.assertEqual(
            identity_evidence.derive_match_mode(self.conv, message),
            identity_evidence.MODE_CHALLENGE,
        )

    def test_a_question_that_never_went_out_stays_passive(self):
        """Un `pet_asked_at` suelto solo probaría la INTENCIÓN de preguntar."""
        self._challenge(asked_state='enqueued', status=Message.STATUS_PENDING)
        message = self._in("Lunna")
        self.assertEqual(
            identity_evidence.derive_match_mode(self.conv, message),
            identity_evidence.MODE_PASSIVE,
        )

    def test_a_failed_question_stays_passive(self):
        self._challenge(status=Message.STATUS_FAILED)
        message = self._in("Lunna")
        self.assertEqual(
            identity_evidence.derive_match_mode(self.conv, message),
            identity_evidence.MODE_PASSIVE,
        )

    def test_a_question_without_the_deterministic_clause_stays_passive(self):
        """El modelo preguntando por los dígitos por su cuenta no sella el reto
        de la mascota."""
        self._challenge(clause=False)
        message = self._in("Lunna")
        self.assertEqual(
            identity_evidence.derive_match_mode(self.conv, message),
            identity_evidence.MODE_PASSIVE,
        )

    def test_an_answer_older_than_the_question_stays_passive(self):
        message = self._in("Lunna")
        self._challenge(asked_at=timezone.now() + timedelta(minutes=1))
        self.assertEqual(
            identity_evidence.derive_match_mode(self.conv, message),
            identity_evidence.MODE_PASSIVE,
        )

    def test_an_expired_question_stays_passive(self):
        self._challenge(
            asked_at=timezone.now()
            - identity_evidence.IDENTITY_EVIDENCE_TTL - timedelta(minutes=1))
        message = self._in("Lunna")
        self.assertEqual(
            identity_evidence.derive_match_mode(self.conv, message),
            identity_evidence.MODE_PASSIVE,
        )

    def test_a_fresh_challenge_reports_pet_as_pending(self):
        """`ConversationGoal.missing` nace `[]` (default del modelo) y solo lo
        escribe `satisfy`. Leerlo del campo en vez de derivarlo del spec dejaba
        `pet_pending=False` justo cuando se hace la pregunta — y con eso el modo
        tolerante era inalcanzable para siempre."""
        commitment = goals.start_identity(
            self.conv, goals.TITULAR_CHALLENGE, first_factor='pet')
        self.assertEqual(commitment.missing, [])
        self.assertIn('pet', goals.missing_slots(commitment))

    def test_the_tool_cannot_choose_the_regime(self):
        """El modelo no elige `from_message`… pero tampoco puede elegir con qué
        reglas se le juzga. Sin reto, «¿es luna llena?» no verifica ni aunque la
        llamada venga de `identify_client`."""
        resolution = self._resolve("¿es luna llena?")
        self.assertIsInstance(resolution, identity_evidence.NoEvidence)


class VerificationTransactionTests(EvidenceTestCase):
    """D25/D32 · promoción, flow, slot y cierre del reto en un solo commit."""

    def test_verification_closes_the_challenge_and_resumes_the_task(self):
        task = goals.open_goal(self.conv, goals.SCHEDULE)
        commitment = goals.start_identity(
            self.conv, goals.TITULAR_CHALLENGE, first_factor='pet')
        resolution = self._resolve("cita para Luna")
        result = identity_evidence.verify_pet_evidence(self.conv, resolution)

        commitment.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(commitment.status, ConversationGoal.STATUS_COMPLETED)
        self.assertIn(task.status, ConversationGoal.FOREGROUND_STATUSES)
        self.assertTrue(result.goal_satisfied)

    def test_a_suspended_identity_goal_is_never_resumed(self):
        """Los constraints resuelven cardinalidad, no significado: reanudar otro
        reto aquí sería volver a pedir identidad justo después de verificarla."""
        stale = ConversationGoal.objects.create(
            organization=self.org, conversation=self.conv,
            name=goals.FAMILY, status=ConversationGoal.STATUS_SUSPENDED,
        )
        commitment = goals.start_identity(
            self.conv, goals.TITULAR_CHALLENGE, first_factor='pet')
        # `start_identity` ya limpia los suyos; se reintroduce a mano para
        # reproducir la fila que la resurrección de `policy` traía al frente.
        stale.status = ConversationGoal.STATUS_SUSPENDED
        stale.save(update_fields=['status'])

        resolution = self._resolve("cita para Luna")
        result = identity_evidence.verify_pet_evidence(self.conv, resolution)

        stale.refresh_from_db()
        commitment.refresh_from_db()
        self.assertEqual(stale.status, ConversationGoal.STATUS_ABANDONED)
        self.assertIsNone(result.resumed_goal)

    def test_result_carries_everything_that_mutated(self):
        resolution = self._resolve("cita para Luna")
        result = identity_evidence.verify_pet_evidence(self.conv, resolution)
        self.assertEqual(result.contact_identity.verification_level,
                         ContactIdentity.VERIFICATION_CONFIRMED)
        self.assertIn('pet_name',
                      result.conversation_flow[identity_evidence.FLOW_KEY])
        self.assertEqual(result.source_message_id, resolution.from_message_id)


class ExpiryTests(EvidenceTestCase):
    """D18/D26 · reducer PURO + reconciliador con efectos."""

    def _seal(self, *, age):
        resolution = self._resolve("cita para Luna")
        identity_evidence.verify_pet_evidence(self.conv, resolution)
        self.conv.refresh_from_db()
        stale = timezone.now() - age
        self.conv.flow[identity_evidence.FLOW_KEY]['pet_name'][
            'captured_at'] = stale.isoformat()
        self.conv.save(update_fields=['flow'])

    def test_the_reducer_does_not_write(self):
        self._seal(age=identity_evidence.IDENTITY_EVIDENCE_TTL
                   + timedelta(minutes=1))
        valid, expired = identity_evidence.reduce_identity_facts(self.conv)
        self.assertEqual(list(expired), ['pet_name'])
        self.assertEqual(valid, {})
        self.conv.refresh_from_db()
        self.assertIn('pet_name',
                      self.conv.flow[identity_evidence.FLOW_KEY])

    def test_reconcile_clears_expired_evidence(self):
        self._seal(age=identity_evidence.IDENTITY_EVIDENCE_TTL
                   + timedelta(minutes=1))
        identity_evidence.reconcile_identity_facts(self.conv)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.flow[identity_evidence.FLOW_KEY], {})

    def test_fresh_evidence_survives(self):
        self._seal(age=timedelta(minutes=1))
        identity_evidence.reconcile_identity_facts(self.conv)
        self.conv.refresh_from_db()
        self.assertIn('pet_name',
                      self.conv.flow[identity_evidence.FLOW_KEY])

    def test_reconcile_returns_the_fresh_flow(self):
        """D31 · el caller reasigna lo que mutó; si no, `anchored_identity_facts`
        republica en el mismo turno lo que se acaba de borrar."""
        self._seal(age=identity_evidence.IDENTITY_EVIDENCE_TTL
                   + timedelta(minutes=1))
        result = identity_evidence.reconcile_identity_facts(self.conv)
        self.assertEqual(result.conversation_flow[identity_evidence.FLOW_KEY],
                         {})


class AlreadyVerifiedTests(EvidenceTestCase):
    def test_identify_client_reports_an_already_verified_contact(self):
        """La evidencia se sella al capturarla, no se re-presenta cada turno.

        Sin esta rama, un cliente ya verificado —típicamente en el turno en que
        nombró a su mascota, por la ruta pasiva— recibía `verificado: False` al
        turno siguiente y el modelo volvía a pedirle el nombre: exactamente el
        bucle que este trabajo cierra.
        """
        from apps.agent import tools
        from apps.agent.executor import ToolExecutor
        from apps.users.services import ensure_agent_user

        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_CONFIRMED)
        self.contact.verified_at = timezone.now()
        self.contact.save(update_fields=['verification_level', 'verified_at'])
        self.conv.contact = self.contact

        agent_user, _ = ensure_agent_user(self.org)
        outcome = tools.identify_client(
            self.conv, ToolExecutor(self.conv, agent_user), {},
            triggered_by=self._in("¿me confirmas mi cita?"),
        )
        self.assertTrue(outcome.data['verificado'])
        self.assertEqual(outcome.data['falta'], [])


class RemediationCommandTests(EvidenceTestCase):
    """D16/D37 · precondición de F1a, e idempotente."""

    def test_degrades_a_contact_verified_by_the_bypass(self):
        from django.core.management import call_command
        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_CONFIRMED)
        self.contact.verified_at = timezone.now()
        self.contact.save(update_fields=['verification_level', 'verified_at'])

        call_command('remediate_identity_f0', '--org', str(self.org.pk),
                     '--apply', verbosity=0)

        self.contact.refresh_from_db()
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_PHONE_MATCH)
        self.assertIsNone(self.contact.verified_at)

    def test_leaves_audited_links_alone(self):
        """Familiar, staff y auto-registro pasaron por su propio guard."""
        from django.core.management import call_command
        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_CONFIRMED)
        self.contact.linked_via = ContactIdentity.LINKED_STAFF
        self.contact.save(update_fields=['verification_level', 'linked_via'])

        call_command('remediate_identity_f0', '--org', str(self.org.pk),
                     '--apply', verbosity=0)

        self.contact.refresh_from_db()
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_CONFIRMED)

    def test_closes_retired_machinery_goals(self):
        from django.core.management import call_command
        stale = ConversationGoal.objects.create(
            organization=self.org, conversation=self.conv,
            name=goals.TRIAGE, status=ConversationGoal.STATUS_SUSPENDED,
        )
        call_command('remediate_identity_f0', '--org', str(self.org.pk),
                     '--apply', verbosity=0)
        stale.refresh_from_db()
        self.assertEqual(stale.status, ConversationGoal.STATUS_ABANDONED)

    def test_is_idempotent(self):
        from django.core.management import call_command
        ConversationGoal.objects.create(
            organization=self.org, conversation=self.conv,
            name=goals.TRIAGE, status=ConversationGoal.STATUS_SUSPENDED,
        )
        call_command('remediate_identity_f0', '--org', str(self.org.pk),
                     '--apply', verbosity=0)
        before = list(ConversationGoal.objects.values_list('status', flat=True))
        call_command('remediate_identity_f0', '--org', str(self.org.pk),
                     '--apply', verbosity=0)
        self.assertEqual(
            list(ConversationGoal.objects.values_list('status', flat=True)),
            before)

    def test_dry_run_writes_nothing(self):
        from django.core.management import call_command
        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_CONFIRMED)
        self.contact.save(update_fields=['verification_level'])
        call_command('remediate_identity_f0', '--org', str(self.org.pk),
                     verbosity=0)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_CONFIRMED)


class PromoteSingleCallerGateTests(SimpleTestCase):
    """D28 · gate estático: `_promote` tiene EXACTAMENTE un llamador.

    Más robusto que enumerar funciones prohibidas, que envejece mal: cualquier
    vía nueva que promueva por su cuenta —y con ella su falta de anti-eco— hace
    fallar este test.
    """

    def test_promote_has_a_single_production_caller(self):
        agent_dir = Path(__file__).resolve().parent.parent
        callers = []
        for path in agent_dir.glob('*.py'):
            source = path.read_text(encoding='utf-8')
            for match in re.finditer(r'(?<!def )_promote\(', source):
                line = source[:match.start()].count('\n') + 1
                callers.append(f'{path.name}:{line}')
        message = (f'`identity._promote` debe tener un solo llamador productivo '
                   f'(el servicio de evidencia). Encontrados: {callers}')
        self.assertEqual(len(callers), 1, message)
        self.assertTrue(callers[0].startswith('identity_evidence.py'), message)

    def test_the_pet_matchers_are_pure(self):
        source = (Path(__file__).resolve().parent.parent
                  / 'identity.py').read_text(encoding='utf-8')
        for name in ('matches_pet_name_exact', 'matches_pet_name_tolerant'):
            body = source.split(f'def {name}(')[1].split('\ndef ')[0]
            for mutation in ('.save(', '.update(', '_promote('):
                self.assertNotIn(
                    mutation, body,
                    f'{name} tiene que ser un matcher PURO: sin {mutation}',
                )
