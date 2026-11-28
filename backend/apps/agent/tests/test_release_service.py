"""F3 — el release aplica su veredicto solo sobre el mundo que verificó.

Item 2, fase F3 (ADR p57 §2, §3.1, §5.6, §7). Liberar una conversación no es
«poner state=active»: es aplicar un VEREDICTO sobre una propuesta que el
cliente dejó a medias, y hacerlo sin pisar a nadie.

Lo que se ancla:

  · **Solo el match exacto descarta** (§7). Ambigüedad, error, timeout o
    «tercer horario» restauran; el alta NUNCA se descarta sola.
  · **Restaurado vencido** (D1): el primer «sí» posterior re-parafrasea y no
    escribe. Ningún «sí» viejo ejecuta nada por su cuenta.
  · **Compare-and-set** (§5.6): si el testigo cambió entre R1 y R3 no se muta
    NADA — ni flow, ni state, ni claim, ni hand-off.
  · **Sin reintentos silenciosos**: un solo reintento y después
    `409 release_conflict`, para que lo decida una persona.
  · **`deferred_at` se conserva** (D7) y `nudge_sent` solo se limpia sin él.
  · Las tres decisiones de producto de esta fase: sin TTL nuevo, sin mensaje
    proactivo al descartar, y `deferred_at` intacto.

Los interleavings usan un hook en R2 para mover el mundo justo en la ventana
donde el lock está suelto — que es exactamente cuando el bug ocurriría.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import confirmations, services
from apps.agent import executor as executor_module
from apps.agent.executor import ToolExecutor
from apps.agent.models import (
    AgentSettings, ContactIdentity, Conversation, HumanHandoff,
)
from apps.agent.tests.harness import set_schedule_day
from apps.appointments.models import Appointment
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        w, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([w])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes])
    return role


class HeaderForwardingTransport:
    def __call__(self, method, path, *, headers, params=None, json=None):
        client = APIClient()
        extra = {}
        for key, value in (headers or {}).items():
            if key.lower() == "authorization":
                extra["HTTP_AUTHORIZATION"] = value
            else:
                extra["HTTP_" + key.upper().replace("-", "_")] = value
        if method.upper() == "GET":
            r = client.get(path, data=params or {}, **extra)
        else:
            r = getattr(client, method.lower())(
                path, data=json or {}, format="json", **extra)
        try:
            return r.status_code, (r.json() if r.content else {})
        except ValueError:
            return r.status_code, {}


class ReleaseServiceBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="F3 Org", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        admin_role = _seed_role(cls.org, "ADMIN")
        cls.vet = User.objects.create_user(
            username="f3_vet", password="p", organization=cls.org, role="VET")
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)
        cls.staff = User.objects.create_user(
            username="f3_staff", password="p", organization=cls.org, role="ADMIN")
        UserRole.objects.get_or_create(user=cls.staff, role=admin_role)
        cls.other_staff = User.objects.create_user(
            username="f3_other", password="p", organization=cls.org, role="ADMIN")
        UserRole.objects.get_or_create(user=cls.other_staff, role=admin_role)
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana", phone="5511110000")
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Luna",
            species="perro", birth_date="2021-01-01")

    def setUp(self):
        executor_module._token_cache.clear()
        self.agent_user, _ = ensure_agent_user(self.org)
        d = timezone.localdate() + timedelta(days=7)
        while d.weekday() > 4:
            d += timedelta(days=1)
        self.day = d
        create_enabled_agent_settings(self.org, agent_user=self.agent_user,
            default_veterinarian=self.vet)
        set_schedule_day(self.org, d.weekday(), "09:00", "13:00")
        from apps.channels.models import ChannelAccount
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770300770")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511110000",
            owner=self.owner, verification_level="confirmed_in_chat")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state=Conversation.STATE_HANDOFF_PENDING,
            claimed_by=self.staff, claimed_at=timezone.now())
        self.executor = ToolExecutor(
            self.conv, self.agent_user, transport=HeaderForwardingTransport())
        # El transporte de test también para el executor que arma el servicio.
        self._patch_executor = mock.patch.object(
            services, '_release_executor',
            side_effect=lambda convo: ToolExecutor(
                convo, self.agent_user, transport=HeaderForwardingTransport()))
        self._patch_executor.start()
        self.addCleanup(self._patch_executor.stop)

    # -- helpers -----------------------------------------------------------
    def _appt(self, hhmm="11:00", status="scheduled"):
        start = datetime.strptime(hhmm, "%H:%M").time()
        end = (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=30)).time()
        return Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="control",
            status=status,
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc))

    def _suspend(self, tool, args, *, legacy=False, paraphrase="¿Confirmas?"):
        state = {'tool': tool, 'args': args, 'paraphrase': paraphrase,
                 'idempotency_key': 'k1',
                 'expires_at': (timezone.now() + timedelta(minutes=30)).isoformat()}
        suspension = {'kind': 'pending_action', 'state': state}
        if not legacy:
            suspension.update({
                'suspension_id': 'susp-1',
                'suspended_at': timezone.now().isoformat(),
                'handoff_reason': 'identity',
            })
        self.conv.flow['suspended'] = suspension
        self.conv.save(update_fields=['flow'])
        return suspension

    def _handoff(self):
        return HumanHandoff.objects.create(
            organization=self.org, conversation=self.conv,
            reason_code=HumanHandoff.REASON_IDENTITY, priority='normal')

    def _release(self):
        return services.release_conversation(self.conv, self.staff)

    def _claim_durable_turn(self):
        from apps.agent.durable import claim_turn
        from apps.channels.models import Message
        Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, contact=self.contact, direction='in',
            author_type=Message.AUTHOR_CLIENT, body='nuevo input')
        return claim_turn(self.conv.pk)

    def _flow(self):
        self.conv.refresh_from_db()
        return self.conv.flow


class VerdictTests(ReleaseServiceBase):
    """§3.1 / §7 — solo el match exacto descarta."""

    def test_cancel_already_done_is_discarded_silently(self):
        """§9.5 (decisión de producto): NO se avisa al cliente."""
        appt = self._appt(status="canceled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        from apps.channels.models import Message
        before = Message.objects.filter(conversation=self.conv).count()

        result = self._release()
        self.assertEqual(result['verdict'], services.RELEASE_DISCARD)
        self.assertNotIn('pending_action', self._flow())
        self.assertNotIn('suspended', self._flow())
        # Silencio: ni un mensaje proactivo al cliente.
        self.assertEqual(
            Message.objects.filter(conversation=self.conv).count(), before)

    def test_still_pending_is_restored_expired(self):
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})

        result = self._release()
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)
        pending = self._flow()['pending_action']
        # D1: restaurado VENCIDO — el primer «sí» re-parafrasea, no ejecuta.
        self.assertTrue(confirmations.is_expired(pending))
        self.assertEqual(pending['tool'], 'cancel_appointment')
        self.assertEqual(pending['paraphrase'], "¿Confirmas?")

    def test_the_third_slot_restores_instead_of_guessing(self):
        """El humano la movió a OTRO horario: el cliente debe enterarse."""
        appt = self._appt("11:00")
        self._suspend('reschedule_appointment', {
            'appointment_public_id': str(appt.public_id),
            'date': self.day.isoformat(), 'start_time': '12:00'})
        # Ni el origen ni el destino: un tercer horario.
        appt.start_time = datetime.strptime("09:30", "%H:%M").time()
        appt.end_time = datetime.strptime("10:00", "%H:%M").time()
        appt.start_datetime = datetime.combine(
            self.day, appt.start_time, tzinfo=dt_tz.utc)
        appt.end_datetime = datetime.combine(
            self.day, appt.end_time, tzinfo=dt_tz.utc)
        appt.save()

        self.assertEqual(self._release()['verdict'], services.RELEASE_RESTORE)

    def test_reschedule_already_at_destination_is_discarded(self):
        appt = self._appt("12:00")
        self._suspend('reschedule_appointment', {
            'appointment_public_id': str(appt.public_id),
            'date': self.day.isoformat(), 'start_time': '12:00'})
        self.assertEqual(self._release()['verdict'], services.RELEASE_DISCARD)

    def test_register_is_never_discarded_automatically(self):
        """§3.1: sus controles son de identidad; ninguna lectura los prueba."""
        self._suspend('register_new_client_and_pet', {
            'owner_name': 'Carlos', 'owner_phone': '5512345678',
            'pet_name': 'Rocky'})
        result = self._release()
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)

    def test_missing_appointment_is_consumed_not_restored(self):
        """404: restaurar garantizaría un fallo posterior ante el cliente."""
        self._suspend('cancel_appointment', {
            'appointment_public_id': '00000000-0000-4000-8000-000000000000'})
        result = self._release()
        self.assertEqual(result['verdict'], services.RELEASE_DISCARD)
        self.assertEqual(result['reason'], 'unresolvable')
        self.assertNotIn('pending_action', self._flow())

    def test_domain_error_restores(self):
        """Falla segura: un error del chequeo nunca descarta la intención."""
        appt = self._appt(status="canceled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        with mock.patch.object(services, '_check_resolved',
                               side_effect=RuntimeError("boom")):
            result = self._release()
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)
        self.assertEqual(result['reason'], 'domain_check_failed')

    def test_corrupt_suspension_is_consumed_without_calling_the_domain(self):
        self.conv.flow['suspended'] = {'kind': 'pending_action',
                                       'state': {'tool': 'nope'}}
        self.conv.save(update_fields=['flow'])
        with mock.patch.object(services, '_release_executor') as spy:
            result = self._release()
        spy.assert_not_called()
        self.assertEqual(result['reason'], 'suspension_invalid')
        self.assertNotIn('pending_action', self._flow())
        self.assertNotIn('suspended', self._flow())

    def test_legacy_suspension_is_restored_not_judged_stale(self):
        """Sin `suspended_at` el dato es VIEJO, no inválido (§7)."""
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)},
                      legacy=True)
        result = self._release()
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)
        self.assertEqual(result['reason'], 'legacy')
        self.assertIn('pending_action', self._flow())

    def test_release_without_any_suspension_still_releases(self):
        result = self._release()
        self.assertEqual(result['verdict'], 'none')
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_ACTIVE)
        self.assertIsNone(self.conv.claimed_by_id)


class DeferredAndNudgeTests(ReleaseServiceBase):
    """D7 — una promesa hecha al cliente no la revoca un botón de staff."""

    def test_deferred_at_survives_the_release(self):
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        self.conv.flow['deferred_at'] = timezone.now().isoformat()
        self.conv.flow['nudge_sent'] = True
        self.conv.save(update_fields=['flow'])

        self._release()
        flow = self._flow()
        self.assertIn('deferred_at', flow)      # intacto
        self.assertTrue(flow['nudge_sent'])     # no se rearma con deferred_at

    def test_nudge_is_rearmed_when_nothing_was_promised(self):
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        self.conv.flow['nudge_sent'] = True
        self.conv.save(update_fields=['flow'])

        self._release()
        self.assertNotIn('nudge_sent', self._flow())

    def test_release_adds_no_new_ttl(self):
        """§9.4: F3 no introduce vencimiento propio de la suspensión."""
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        self._release()
        pending = self._flow()['pending_action']
        # El único TTL es el del pending, y llega ya vencido a propósito.
        self.assertEqual(
            set(pending) - {'tool', 'args', 'paraphrase', 'idempotency_key'},
            {'expires_at'})


class WitnessTests(ReleaseServiceBase):
    """§5.6 — compare-and-set: o el mundo es el que se verificó, o nada."""

    def _release_with_interference(self, meddle):
        """Ejecuta el release moviendo el mundo dentro de la ventana de R2.

        Es la ventana real: R2 corre fuera del lock a propósito (una llamada de
        red dentro de una transacción la mantiene abierta lo que tarde el otro
        extremo).
        """
        original = services._domain_verdict
        calls = {'n': 0}

        def hooked(conversation, suspension):
            verdict = original(conversation, suspension)
            calls['n'] += 1
            if calls['n'] == 1:
                meddle()
            return verdict

        with mock.patch.object(services, '_domain_verdict', side_effect=hooked):
            return self._release()

    def test_a_new_suspension_between_r1_and_r3_is_not_clobbered(self):
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        handoff = self._handoff()

        def meddle():
            convo = Conversation.objects.get(pk=self.conv.pk)
            convo.flow['suspended']['suspension_id'] = 'susp-2'
            convo.save(update_fields=['flow'])

        # Reintenta una vez y, con el mundo ya quieto, aplica sobre lo nuevo.
        result = self._release_with_interference(meddle)
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)
        # El hand-off observado se resolvió: el ciclo completo se rehízo.
        handoff.refresh_from_db()
        self.assertIsNotNone(handoff.resolved_at)

    def test_persistent_interference_ends_in_conflict_without_mutating(self):
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        handoff = self._handoff()
        counter = {'n': 0}

        def always_move(conversation, suspension):
            counter['n'] += 1
            convo = Conversation.objects.get(pk=self.conv.pk)
            convo.flow['suspended']['suspension_id'] = f'susp-{counter["n"] + 1}'
            convo.save(update_fields=['flow'])
            return services.RELEASE_RESTORE, 'not_resolved'

        with mock.patch.object(services, '_domain_verdict',
                               side_effect=always_move):
            with self.assertRaises(services.ReleaseConflict) as ctx:
                self._release()

        self.assertEqual(ctx.exception.reason, services.CONFLICT_SUSPENSION)
        # CERO mutaciones: ni flow restaurado, ni claim, ni state, ni hand-off.
        self.conv.refresh_from_db()
        self.assertNotIn('pending_action', self.conv.flow)
        self.assertIn('suspended', self.conv.flow)
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)
        self.assertEqual(self.conv.claimed_by_id, self.staff.pk)
        handoff.refresh_from_db()
        self.assertIsNone(handoff.resolved_at)
        # Solo DOS vueltas: un reintento, no un bucle.
        self.assertEqual(counter['n'], 2)

    def test_a_claim_taken_in_the_window_forces_a_retry(self):
        """El claim que aparece entre R1 y R3 aborta ESE intento (§5.6)."""
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        handoff = self._handoff()
        seen = {'n': 0}

        def steal_once():
            seen['n'] += 1
            Conversation.objects.filter(pk=self.conv.pk).update(
                claimed_by=self.other_staff)

        result = self._release_with_interference(steal_once)
        # El primer ciclo no mutó nada; el segundo aplicó sobre el mundo nuevo.
        self.assertEqual(seen['n'], 1)
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)
        handoff.refresh_from_db()
        self.assertIsNotNone(handoff.resolved_at)

    def test_a_pre_existing_foreign_claim_is_still_released(self):
        """El claim ajeno PREEXISTENTE se libera. **Decisión, no omisión.**

        El testigo protege la ventana R1–R3, no la propiedad del claim: si otra
        persona ya tenía la conversación reclamada ANTES de pulsar liberar, el
        release se la quita.

        Ratificado para el piloto (producto, 2026-08-12) por un motivo
        operativo: si quien reclamó se ausenta, la conversación no puede quedar
        bloqueada para el resto del equipo. Es además el comportamiento previo
        a F3, que no miraba el claim en absoluto.

        La evolución prevista es «solo el titular o un supervisor libera» — no
        un 409 a secas, que reintroduciría el bloqueo por ausencia sin salida.
        Este test es el que hay que cambiar cuando eso se decida; que falle
        entonces es la señal de que la política nueva está entrando de verdad.
        """
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        Conversation.objects.filter(pk=self.conv.pk).update(
            claimed_by=self.other_staff)

        result = self._release()
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)
        self.conv.refresh_from_db()
        self.assertIsNone(self.conv.claimed_by_id)

    def test_a_turn_taken_mid_flight_is_not_stomped(self):
        """El worker toma el turno en la ventana: el 2º ciclo lo respeta.

        No se muta nada. El desenlace es `turn_in_progress` —lo detecta R1 del
        reintento, antes incluso de volver a preguntar al dominio— y el staff
        reintenta en segundos.
        """
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        handoff = self._handoff()

        def worker_takes_turn():
            self._claim_durable_turn()

        with self.assertRaises(services.TurnInProgress):
            self._release_with_interference(worker_takes_turn)

        self.conv.refresh_from_db()
        self.assertNotIn('pending_action', self.conv.flow)
        self.assertIn('suspended', self.conv.flow)
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)
        handoff.refresh_from_db()
        self.assertIsNone(handoff.resolved_at)

    def test_turn_in_progress_is_rejected_up_front(self):
        self._claim_durable_turn()
        with self.assertRaises(services.TurnInProgress):
            self._release()

    def test_closed_conversation_is_not_released(self):
        self.conv.state = Conversation.STATE_CLOSED
        self.conv.save(update_fields=['state'])
        with self.assertRaises(services.ConversationClosed):
            self._release()

    def test_only_the_observed_handoff_is_resolved(self):
        """No «el último abierto»: pueden no ser el mismo (§5.6)."""
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        observed = self._handoff()

        # Otra escalada aparece DESPUÉS de R1 → el testigo difiere y el ciclo
        # se rehace; nunca se resuelve un caso que nadie verificó.
        def new_handoff():
            HumanHandoff.objects.create(
                organization=self.org, conversation=self.conv,
                reason_code=HumanHandoff.REASON_TOOL_FAILURE, priority='normal')

        self._release_with_interference(new_handoff)
        observed.refresh_from_db()
        # El segundo ciclo observó el hand-off nuevo y resolvió ESE; el
        # primero, ya no vigente, no se toca a ciegas.
        newest = HumanHandoff.objects.filter(
            conversation=self.conv).order_by('-id').first()
        self.assertIsNotNone(newest.resolved_at)


class ReleaseEndpointTests(ReleaseServiceBase):
    """El transporte traduce los desenlaces del servicio a HTTP."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.staff)
        self.url = f'/api/inbox/conversations/{self.conv.public_id}/release/'

    def test_restore_returns_the_verdict(self):
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['release']['verdict'], 'restore')

    def test_turn_in_progress_is_409(self):
        self._claim_durable_turn()
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'turn_in_progress')

    def test_conflict_is_409_with_its_reason(self):
        appt = self._appt(status="scheduled")
        self._suspend('cancel_appointment',
                      {'appointment_public_id': str(appt.public_id)})
        counter = {'n': 0}

        def always_move(conversation, suspension):
            # El mundo sigue moviéndose en las DOS vueltas: hay alguien más
            # operando y la respuesta correcta es decírselo a quien pulsó.
            counter['n'] += 1
            convo = Conversation.objects.get(pk=self.conv.pk)
            convo.flow['suspended']['suspension_id'] = f'susp-{counter["n"] + 1}'
            convo.save(update_fields=['flow'])
            return services.RELEASE_RESTORE, 'not_resolved'

        with mock.patch.object(services, '_domain_verdict',
                               side_effect=always_move):
            resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'release_conflict')
        self.assertEqual(resp.data['reason'], services.CONFLICT_SUSPENSION)

    def test_closed_conversation_is_400(self):
        self.conv.state = Conversation.STATE_CLOSED
        self.conv.save(update_fields=['state'])
        resp = self.client.post(self.url, format='json')
        self.assertEqual(resp.status_code, 400)
