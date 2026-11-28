"""
test_identity_evidence.py — El factor único y su régimen probatorio (F0).

Protege lo que el plan de continuidad (`docs/agent-continuity-plan.md`) cerró
tras trece revisiones. Los casos vienen de defectos REALES de producción, no de
hipótesis: la conv 18 verificó a un contacto contra un nombre que el propio
sistema le había filtrado, y la ruta pasiva promovía con «¿va a haber sol
mañana?» si la mascota se llamaba Sol.
"""
import re
from datetime import datetime, timedelta, timezone as dt_timezone
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
from apps.platform.deletion_guards import authorize_physical_deletion
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings


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
        create_enabled_agent_settings(self.org)

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

    def _resolve(self, *texts, claimed='Luna'):
        """Persiste lo que dijo el cliente y pregunta por la LECTURA del modelo.

        `claimed` es lo que el modelo afirma haber entendido; los `texts` son lo
        que el cliente escribió de verdad. Separarlos es el contrato de p59: el
        servidor comprueba la propuesta contra el texto, no al revés.
        """
        for text in texts:
            self._in(text)
        return identity_evidence.resolve_pet_evidence(self.conv, claimed)


class ModelClaimTests(EvidenceTestCase):
    """ADR p59 · el modelo propone la lectura, el servidor la comprueba.

    Aquí vivían 14 casos de gramática cerrada (marcos clínicos, posesivos,
    negaciones de identidad, metalingüísticas). Se retiraron con la gramática:
    enumeraban formas de nombrar una mascota y formas de negar identidad, dos
    espacios sin fondo, y en producción rechazaron a un cliente legítimo que
    había contestado bien.

    La barrera ya no es «¿venía enmarcado?» sino **«¿lo dijo el cliente?»**.
    """

    # ── la barrera ──────────────────────────────────────────────────────────
    def test_the_model_cannot_invent_the_contribution(self):
        """LA prueba. El modelo puede leer mal; no puede inventar el aporte."""
        resolution = self._resolve("quiero una cita", claimed='Luna')
        self.assertIsInstance(resolution, identity_evidence.NoEvidence)
        self.assertEqual(resolution.reason, 'el cliente no lo dijo')

    def test_a_name_that_is_not_a_registered_pet_is_rejected(self):
        resolution = self._resolve("mi mascota es Rocky", claimed='Rocky')
        self.assertIsInstance(resolution, identity_evidence.NoEvidence)
        self.assertEqual(resolution.reason, 'no es una de sus mascotas')

    def test_an_empty_claim_is_rejected(self):
        self.assertIsInstance(self._resolve("Luna", claimed=''),
                              identity_evidence.NoEvidence)

    def test_the_source_message_is_the_client_message_that_said_it(self):
        said = self._in("Luna")
        resolution = identity_evidence.resolve_pet_evidence(self.conv, 'Luna')
        self.assertIsInstance(resolution, identity_evidence.SealedPetEvidence)
        self.assertEqual(resolution.from_message_id, said.pk)

    def test_an_outbound_mention_is_not_a_client_contribution(self):
        """Que el nombre esté en la conversación no basta: tiene que haberlo
        dicho ÉL. Es la mitad de procedencia que el bypass de p58 saltaba.

        Y el desenlace es `NoEvidence`, **no** `EchoRejected`: el eco escala a una
        persona, y aquí no hay nada que escalar — el cliente no ha dicho nada, el
        modelo leyó su propio mensaje. Se le pregunta y sigue. El escalado se
        reserva para cuando el CLIENTE repite un dato que nosotros filtramos, que
        es el caso con consecuencia de seguridad."""
        self._out("¿Cómo sigue Luna?")
        resolution = self._resolve(claimed='Luna')
        self.assertIsInstance(resolution, identity_evidence.NoEvidence)
        self.assertEqual(resolution.reason, 'el cliente no lo dijo')

    # ── lo que p59 desbloquea, y era el fallo de conv 21 ────────────────────
    def test_a_bare_name_is_evidence(self):
        """El caso literal de producción: se le preguntó el nombre de su
        mascota, contestó «koler», y la gramática lo rechazó por venir «sin
        marco». Seis mensajes y 18 minutos, y se fue sin su cita."""
        self.assertIsInstance(self._resolve("Luna"),
                              identity_evidence.SealedPetEvidence)

    def test_an_identity_negation_that_reveals_the_pet_is_evidence(self):
        """«yo no soy koler» — el cliente corrige al agente y de paso demuestra
        que conoce a su mascota. La lista de negaciones no cubría `no soy`, y
        añadirlo habría sido repetir el método que produjo el problema."""
        self.assertIsInstance(self._resolve("yo no soy Luna, Luna es mi perra"),
                              identity_evidence.SealedPetEvidence)

    def test_a_clinical_negation_is_still_evidence(self):
        self.assertIsInstance(self._resolve("Luna no come"),
                              identity_evidence.SealedPetEvidence)

    def test_a_framed_mention_still_works(self):
        self.assertIsInstance(self._resolve("cita para Luna, por favor"),
                              identity_evidence.SealedPetEvidence)

    def test_a_typo_from_the_client_still_matches(self):
        self.assertIsInstance(self._resolve("mi perrita Lunna"),
                              identity_evidence.SealedPetEvidence)

    def test_the_short_name_of_a_compound_pet_works(self):
        self.pet.name = "Luna Bella"
        self.pet.save(update_fields=['name'])
        resolution = self._resolve("cita para Luna")
        self.assertIsInstance(resolution, identity_evidence.SealedPetEvidence)
        self.assertEqual(resolution.registered_name, "Luna Bella")

    # ── lo que sigue sin elegirse ───────────────────────────────────────────
    def test_two_distinct_registered_names_are_not_resolved(self):
        """Si la propuesta encaja con dos mascotas distintas, no se elige: sería
        la decisión automática entre candidatos que INV-C prohíbe."""
        Pet.objects.create(organization=self.org, owner=self.owner,
                           name="Luna Clara", species="gato",
                           birth_date="2022-01-01")
        self.pet.name = "Luna Bella"
        self.pet.save(update_fields=['name'])
        self.assertIsInstance(self._resolve("Luna", claimed='Luna'),
                              identity_evidence.NoEvidence)

    def test_two_pets_with_the_same_name_do_not_invalidate(self):
        Pet.objects.create(organization=self.org, owner=self.owner,
                           name="Luna", species="gato",
                           birth_date="2022-01-01")
        self.assertIsInstance(self._resolve("Luna"),
                              identity_evidence.SealedPetEvidence)

    def test_an_owner_without_pets_has_no_factor(self):
        with authorize_physical_deletion(self.pet):
            self.pet.delete()
        resolution = self._resolve("Luna")
        self.assertIsInstance(resolution, identity_evidence.NoEvidence)
        self.assertEqual(resolution.reason, 'owner sin mascotas')

    def test_the_sealed_evidence_records_who_proposed_it(self):
        resolution = self._resolve("Luna")
        self.assertEqual(resolution.match_mode,
                         identity_evidence.MATCHED_BY_MODEL_CLAIM)


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

    def test_a_pending_staff_outbound_is_not_a_disclosure(self):
        """El outbox ya es visible al staff, pero aún no reveló nada al cliente."""
        self._out("¿Cómo sigue Luna?", status=Message.STATUS_PENDING,
                  author=Message.AUTHOR_HUMAN)
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
    """D16/D37 · precondición de F1a, idempotente y **acotada en el tiempo**.

    La versión anterior de esta clase daba por bueno el bug: afirmaba que un
    contacto con `verified_at = now()` se degradaba. Eso es justo lo que NO debe
    pasar — `linked_via=''` es el resultado normal del reto conversacional, no la
    huella del bypass, así que sin frontera temporal el comando borra las
    verificaciones legítimas. En producción lo hizo cada 30 minutos.
    """

    F0_DEPLOY = '2026-08-17T02:35:51Z'
    F0_DEPLOY_AT = datetime(2026, 8, 17, 2, 35, 51, tzinfo=dt_timezone.utc)

    @classmethod
    def _before_cutoff(cls):
        """Instante legacy fijo; nunca depende del día que corra CI."""
        return cls.F0_DEPLOY_AT - timedelta(seconds=1)

    @classmethod
    def _after_cutoff(cls):
        return cls.F0_DEPLOY_AT + timedelta(seconds=1)

    def _confirmed(self, verified_at):
        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_CONFIRMED)
        self.contact.verified_at = verified_at
        self.contact.save(update_fields=['verification_level', 'verified_at'])

    def _run(self, *extra):
        from django.core.management import call_command
        call_command('remediate_identity_f0', '--org', str(self.org.pk),
                     *extra, verbosity=0)

    def _level(self):
        self.contact.refresh_from_db()
        return self.contact.verification_level

    # ── la frontera temporal ────────────────────────────────────────────────
    def test_a_verification_after_the_cutoff_survives(self):
        """EL test que faltaba. El bypass murió al desplegar F0: lo verificado
        después salió del servicio único, con anti-eco y procedencia."""
        self._confirmed(self._after_cutoff())
        self._run('--apply', '--before', self.F0_DEPLOY)
        self.assertEqual(self._level(), ContactIdentity.VERIFICATION_CONFIRMED)
        self.assertIsNotNone(self.contact.verified_at)

    def test_a_verification_before_the_cutoff_is_degraded(self):
        self._confirmed(self._before_cutoff())
        self._run('--apply', '--before', self.F0_DEPLOY)
        self.assertEqual(self._level(),
                         ContactIdentity.VERIFICATION_PHONE_MATCH)
        self.assertIsNone(self.contact.verified_at)

    def test_a_confirmed_row_without_date_counts_as_legacy(self):
        """`_promote` siempre estampa `verified_at`, así que un nulo con
        `confirmed_in_chat` no lo produce el código nuevo."""
        self._confirmed(None)
        self._run('--apply', '--before', self.F0_DEPLOY)
        self.assertEqual(self._level(),
                         ContactIdentity.VERIFICATION_PHONE_MATCH)

    def test_without_the_cutoff_nothing_is_degraded(self):
        """Correrlo por accidente —o desde un script que corre cada 30 min— ya
        no puede tocar una verificación vigente."""
        self._confirmed(self._before_cutoff())
        self._run('--apply')
        self.assertEqual(self._level(), ContactIdentity.VERIFICATION_CONFIRMED)

    def test_a_malformed_cutoff_is_an_error_not_a_silent_none(self):
        from django.core.management import CommandError
        self._confirmed(self._before_cutoff())
        for bad in ('ayer', '2026-13-45T99:99:99Z'):
            with self.assertRaises(CommandError):
                self._run('--apply', '--before', bad)

    def test_a_naive_cutoff_is_rejected(self):
        """Sin zona, la frontera se mueve con el reloj del contenedor."""
        from django.core.management import CommandError
        with self.assertRaises(CommandError):
            self._run('--apply', '--before', '2026-08-17T02:35:51')

    # ── lo que no cambió ────────────────────────────────────────────────────
    def test_leaves_audited_links_alone(self):
        """Familiar, staff y auto-registro pasaron por su propio guard."""
        self._confirmed(self.F0_DEPLOY_AT - timedelta(days=30))
        self.contact.linked_via = ContactIdentity.LINKED_STAFF
        self.contact.save(update_fields=['linked_via'])
        self._run('--apply', '--before', self.F0_DEPLOY)
        self.assertEqual(self._level(), ContactIdentity.VERIFICATION_CONFIRMED)

    def test_closes_retired_machinery_goals_without_any_cutoff(self):
        """El predicado de orfandad es intrínseco (maquinaria retirada), no
        histórico: no necesita frontera y no puede alcanzar un reto vigente."""
        stale = ConversationGoal.objects.create(
            organization=self.org, conversation=self.conv,
            name=goals.TRIAGE, status=ConversationGoal.STATUS_SUSPENDED,
        )
        self._run('--apply')
        stale.refresh_from_db()
        self.assertEqual(stale.status, ConversationGoal.STATUS_ABANDONED)

    def test_is_idempotent(self):
        ConversationGoal.objects.create(
            organization=self.org, conversation=self.conv,
            name=goals.TRIAGE, status=ConversationGoal.STATUS_SUSPENDED,
        )
        self._confirmed(self._before_cutoff())
        self._run('--apply', '--before', self.F0_DEPLOY)
        snapshot = (self._level(),
                    list(ConversationGoal.objects
                         .values_list('status', flat=True)))
        self._run('--apply', '--before', self.F0_DEPLOY)
        self.assertEqual(
            (self._level(),
             list(ConversationGoal.objects.values_list('status', flat=True))),
            snapshot)

    def test_dry_run_writes_nothing(self):
        self._confirmed(self._before_cutoff())
        self._run('--before', self.F0_DEPLOY)
        self.assertEqual(self._level(), ContactIdentity.VERIFICATION_CONFIRMED)


class ReleaseScriptTests(SimpleTestCase):
    """El incidente no fue solo del predicado: fue de DÓNDE corría.

    `release.sh` no corre «una vez por deploy». El cron de la demo invoca
    `docker compose run --rm backend`, y `run` arranca las dependencias del
    servicio — entre ellas `release`. En producción eso son 48 corridas al día.
    """

    def _release_sh(self):
        from pathlib import Path
        path = (Path(__file__).resolve().parents[3]
                / 'scripts' / 'release.sh')
        return path.read_text(encoding='utf-8')

    def test_no_data_remediation_runs_on_release(self):
        body = [line for line in self._release_sh().splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
        offenders = [line for line in body if 'remediate' in line]
        self.assertEqual(offenders, [], (
            'Una remediación es de un solo uso y este script corre cada 30 min. '
            'Va a mano, con --before y dry-run previo.'))

    def test_it_still_runs_the_convergent_steps(self):
        body = self._release_sh()
        for command in ('migrate', 'collectstatic', 'seed_permissions'):
            self.assertIn(command, body)


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

    def test_the_pet_matcher_is_pure(self):
        """Uno solo desde p59: `matches_pet_name_exact` era del régimen pasivo."""
        source = (Path(__file__).resolve().parent.parent
                  / 'identity.py').read_text(encoding='utf-8')
        body = source.split('def matches_pet_name_tolerant(')[1].split('\ndef ')[0]
        for mutation in ('.save(', '.update(', '_promote('):
            self.assertNotIn(
                mutation, body,
                f'el matcher tiene que ser PURO: sin {mutation}',
            )

    def test_the_retired_grammar_does_not_come_back(self):
        """p59 · la gramática cerrada y los dos regímenes se retiraron porque
        enumeraban espacios infinitos. Reponer una pieza con otro nombre
        reintroduce el fallo: un fraseo nuevo vuelve a ser un bug nuevo."""
        source = (Path(__file__).resolve().parent.parent
                  / 'identity_evidence.py').read_text(encoding='utf-8')
        for gone in ('def extract_pet_candidate', 'def derive_match_mode',
                     '_IDENTITY_NEGATIONS', '_CLINICAL_NOUNS', '_STATE_STARTS'):
            self.assertNotIn(gone, source, f'{gone} volvió: ver ADR p59')
