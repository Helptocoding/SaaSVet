"""
test_w0_hardening.py — É-F3 W0: los cinco bloqueantes de la auditoría.

Cada clase ancla un hallazgo concreto que hoy se manifestaría en el piloto:

W0-1  los horarios se calculaban con el reloj del proceso (UTC) y no con el de
      la clínica → a las 10:00 en México solo se ofrecían huecos de 16:00 en
      adelante, y después de las 18:00 el día en curso se rechazaba como pasado.
W0-2  el detector de urgencia solo miraba el ÚLTIMO mensaje de la ráfaga →
      "mi perro convulsiona" + "ayúdenme" no escalaba.
W0-3  un turno que revienta mataba el worker de TODAS las clínicas y volvía a
      reventar al reiniciar (crash-loop).
W0-5  sin veterinario configurado se agendaba con "el primer VET por pk".
W0-6  el aviso de privacidad estaba escrito pero nunca se emitía.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import executor as executor_module
from apps.agent import policy, tools
from apps.agent.executor import ToolExecutor
from apps.agent.llm import LLMResult
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    HumanHandoff,
)
from apps.agent.services import ingest_inbound_message
from apps.agent.tests.harness import run_turn, set_schedule_day
from apps.agent.worker import MAX_PROCESS_ATTEMPTS, process_pending_conversations
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user

MX = ZoneInfo("America/Mexico_City")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        role.permissions.set([Permission.objects.get_or_create(code="*.*")[0]])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes])
    return role


class TestClientTransport:
    def __call__(self, method, path, *, headers, params=None, json=None):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=headers.get("Authorization", ""))
        r = getattr(client, method.lower())(path, data=params or {})
        try:
            return r.status_code, (r.json() if r.content else {})
        except ValueError:
            return r.status_code, {}


class AgentFixture(TestCase):
    """Clínica mexicana con agente provisionado y un cliente conocido."""

    tz_name = "America/Mexico_City"
    account_id = "900000001"

    def setUp(self):
        executor_module._token_cache.clear()
        self.org = Organization.objects.create(
            name="Clínica W0", timezone=self.tz_name)
        _seed_role(self.org, "AGENT")
        vet_role = _seed_role(self.org, "VET")
        self.vet = User.objects.create_user(
            username=f"w0vet{self.account_id}", password="p",
            organization=self.org, role="VET")
        UserRole.objects.get_or_create(user=self.vet, role=vet_role)
        self.agent_user, _ = ensure_agent_user(self.org)
        self.owner = Owner.objects.create(
            organization=self.org, name="Ana Torres", phone="5511110000")
        self.pet = Pet.objects.create(
            organization=self.org, owner=self.owner, name="Luna",
            species="perro", birth_date="2021-01-01")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id=self.account_id)
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511110000",
            phone_normalized="5511110000", owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_PHONE_MATCH)
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True, agent_user=self.agent_user,
            default_veterinarian=self.vet)

    def executor(self):
        return ToolExecutor(self.conv, self.agent_user,
                            transport=TestClientTransport())


class SlotsUseOrgClockTests(AgentFixture):
    """W0-1 — el reloj que manda es el de la clínica, no el del servidor."""

    account_id = "900000002"

    # 16:00 UTC = 10:00 en Ciudad de México. Con el reloj del proceso se
    # descartaban como "pasados" todos los huecos anteriores a las 16:00.
    FROZEN = datetime(2026, 7, 24, 16, 0, tzinfo=dt_timezone.utc)

    def _open_all_day(self, local_date):
        set_schedule_day(self.org, local_date.weekday(), "09:00", "19:00")

    def test_morning_slots_are_offered_at_local_morning(self):
        local_today = self.FROZEN.astimezone(MX).date()
        self._open_all_day(local_today)
        with mock.patch("django.utils.timezone.now", return_value=self.FROZEN):
            out = tools.find_available_slots(
                self.conv, self.executor(), {"date": local_today.isoformat()})
        self.assertTrue(out.ok, out.client_error)
        times = [s["iso_time"] for s in out.data]
        # Son las 10:00 locales: el siguiente hueco es 10:30, no 16:30.
        self.assertEqual(times[0], "10:30", times)

    def test_today_is_not_rejected_as_past_after_18h_local(self):
        # 02:00 UTC del 25 = 20:00 del 24 en México: el día local sigue siendo
        # el 24, pero el reloj UTC ya lo daba por vencido.
        frozen = datetime(2026, 7, 25, 2, 0, tzinfo=dt_timezone.utc)
        local_today = frozen.astimezone(MX).date()
        self._open_all_day(local_today)
        with mock.patch("django.utils.timezone.now", return_value=frozen):
            out = tools.find_available_slots(
                self.conv, self.executor(), {"date": local_today.isoformat()})
        self.assertNotEqual(out.client_error, "past_date")

    def test_yesterday_local_is_still_rejected(self):
        frozen = datetime(2026, 7, 25, 2, 0, tzinfo=dt_timezone.utc)
        local_yesterday = frozen.astimezone(MX).date() - timedelta(days=1)
        with mock.patch("django.utils.timezone.now", return_value=frozen):
            out = tools.find_available_slots(
                self.conv, self.executor(),
                {"date": local_yesterday.isoformat()})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "past_date")


class BurstSafetyTests(AgentFixture):
    """W0-2 — la seguridad se evalúa sobre la ráfaga, no sobre el último."""

    account_id = "900000003"

    def test_emergency_in_first_message_of_burst_escalates(self):
        decision = policy.evaluate(
            self.conv, "ayúdenme por favor",
            burst=["mi perro convulsiona", "ayúdenme por favor"],
            agent_settings=self.settings)
        self.assertEqual(decision.kind, policy.ESCALATE)
        self.assertEqual(decision.handoff_reason, HumanHandoff.REASON_EMERGENCY)
        self.assertEqual(decision.handoff_priority,
                         HumanHandoff.PRIORITY_URGENT)

    def test_emergency_only_in_last_message_still_escalates(self):
        decision = policy.evaluate(
            self.conv, "mi perro convulsiona",
            burst=["hola", "mi perro convulsiona"],
            agent_settings=self.settings)
        self.assertEqual(decision.kind, policy.ESCALATE)

    def test_human_request_in_first_message_of_burst_escalates(self):
        decision = policy.evaluate(
            self.conv, "gracias",
            burst=["quiero hablar con una persona", "gracias"],
            agent_settings=self.settings)
        self.assertEqual(decision.kind, policy.ESCALATE)
        self.assertEqual(decision.handoff_reason, HumanHandoff.REASON_EXPLICIT)

    def test_affirmative_followed_by_thanks_still_confirms(self):
        self.conv.flow["pending_action"] = {"tool": "create_appointment"}
        self.conv.save(update_fields=["flow"])
        decision = policy.evaluate(
            self.conv, "gracias", burst=["sí", "gracias"],
            agent_settings=self.settings)
        self.assertEqual(decision.kind, policy.RUN_PLANNER)
        self.assertEqual(decision.meta.get("confirm"), "affirmative")

    def test_single_message_behaviour_unchanged(self):
        # "gracias" dejó de ser plantilla (É-F5 Fase 5); este test mide el
        # camino de UN mensaje suelto, así que usa una que siga siéndolo.
        decision = policy.evaluate(self.conv, "¿eres una persona?",
                                   agent_settings=self.settings)
        self.assertEqual(decision.kind, policy.REPLY)
        self.assertEqual(decision.meta.get("reason"), "bot_question")


class WorkerFaultIsolationTests(AgentFixture):
    """W0-3 — un turno que revienta no puede tumbar el worker ni repetirse."""

    account_id = "900000004"

    def _inbound(self, wamid, body="hola"):
        return ingest_inbound_message(
            self.channel, wamid=wamid, wa_id="5215511110000", body=body)

    def _later(self):
        return timezone.now() + timedelta(seconds=10)

    def test_failing_turn_does_not_propagate_and_message_is_retried(self):
        message = self._inbound("wamid.F1")
        with mock.patch("apps.agent.planner.handle_inbound",
                        side_effect=RuntimeError("boom")):
            # No debe levantar: antes la excepción mataba el proceso worker.
            processed = process_pending_conversations(now=self._later())
        self.assertEqual(processed, 1)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_PENDING)
        self.assertEqual(message.process_attempts, 1)
        self.assertIsNotNone(message.available_at)

    def test_poison_message_is_dead_lettered_and_escalated(self):
        message = self._inbound("wamid.F2")
        Message.objects.filter(pk=message.pk).update(
            process_attempts=MAX_PROCESS_ATTEMPTS - 1)
        with mock.patch("apps.agent.planner.handle_inbound",
                        side_effect=RuntimeError("boom")):
            process_pending_conversations(now=self._later())

        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_DISCARDED)
        conv = message.conversation
        conv.refresh_from_db()
        self.assertEqual(conv.state, Conversation.STATE_HANDOFF_PENDING)
        self.assertTrue(HumanHandoff.objects.filter(conversation=conv).exists())
        # El cliente no queda mudo: recibe una disculpa honesta.
        self.assertTrue(
            Message.objects.filter(conversation=conv,
                                   direction=Message.DIRECTION_OUT).exists())

    def test_lease_prevents_a_second_worker_taking_the_same_turn(self):
        self._inbound("wamid.F3")
        conv = Conversation.objects.get(contact=self.contact)
        conv.processing_until = timezone.now() + timedelta(minutes=1)
        conv.save(update_fields=["processing_until"])
        processed = process_pending_conversations(now=self._later())
        self.assertEqual(processed, 0)

    def test_successful_turn_releases_the_lease(self):
        self._inbound("wamid.F4")
        with mock.patch("apps.agent.planner.handle_inbound",
                        return_value={"decision": "reply"}):
            process_pending_conversations(now=self._later())
        conv = Conversation.objects.get(contact=self.contact)
        self.assertIsNone(conv.processing_until)


class SchedulingVetTests(AgentFixture):
    """W0-5 (revisado por el PO 2026-07-25) — a la clínica le da igual QUIÉN
    atienda, así que se usa a quien esté LIBRE.

    El comportamiento viejo ("primer VET por pk") cargaba toda la agenda del
    bot sobre un solo veterinario y agotaba su día aunque los demás estuvieran
    libres. `no_vet` queda reservado para el único caso honesto: la clínica no
    tiene ningún veterinario activo.
    """

    account_id = "900000005"

    def _second_vet(self):
        vet = User.objects.create_user(
            username=f"w0vet2{self.account_id}", password="p",
            organization=self.org, role="VET")
        role = Role.objects.get(name="VET", organization=self.org)
        UserRole.objects.get_or_create(user=vet, role=role)
        return vet

    def test_without_default_vet_any_active_vet_serves(self):
        self.settings.default_veterinarian = None
        self.settings.save(update_fields=["default_veterinarian"])
        self.assertEqual(
            tools._scheduling_vets(self.org, self.settings), [self.vet])

    def test_all_active_vets_are_candidates(self):
        second = self._second_vet()
        self.settings.default_veterinarian = None
        self.settings.save(update_fields=["default_veterinarian"])
        self.assertCountEqual(
            tools._scheduling_vets(self.org, self.settings),
            [self.vet, second])

    def test_explicit_default_vet_is_respected(self):
        self.assertEqual(
            tools._scheduling_vets(self.org, self.settings), [self.vet])

    def test_inactive_vets_are_excluded(self):
        self.settings.default_veterinarian = None
        self.settings.save(update_fields=["default_veterinarian"])
        self.vet.is_active = False
        self.vet.save(update_fields=["is_active"])
        self.assertEqual(tools._scheduling_vets(self.org, self.settings), [])

    def test_no_active_vet_reports_no_vet(self):
        self.settings.default_veterinarian = None
        self.vet.is_active = False
        self.vet.save(update_fields=["is_active"])
        day = timezone.now().astimezone(MX).date() + timedelta(days=3)
        set_schedule_day(self.org, day.weekday(), "09:00", "19:00")
        self.settings.save(update_fields=["default_veterinarian"])
        out = tools.find_available_slots(
            self.conv, self.executor(), {"date": day.isoformat()})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "no_vet")

    def test_a_busy_vet_does_not_block_a_free_one(self):
        """El hueco sigue disponible porque el otro veterinario está libre:
        con 3 veterinarios la capacidad es la de 3, no la del primero."""
        from apps.appointments.models import Appointment
        second = self._second_vet()
        self.settings.default_veterinarian = None
        day = timezone.now().astimezone(MX).date() + timedelta(days=3)
        set_schedule_day(self.org, day.weekday(), "09:00", "11:00")
        self.settings.save(update_fields=["default_veterinarian"])
        Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=day, start_time="09:00", end_time="09:30", reason="x",
            status="scheduled",
            start_datetime=datetime(day.year, day.month, day.day, 9, 0,
                                    tzinfo=dt_timezone.utc),
            end_datetime=datetime(day.year, day.month, day.day, 9, 30,
                                  tzinfo=dt_timezone.utc))

        out = tools.find_available_slots(
            self.conv, self.executor(), {"date": day.isoformat()})
        self.assertTrue(out.ok, out.client_error)
        self.assertIn("09:00", [s["iso_time"] for s in out.data])
        # …y la cita se asigna al que está libre, no al ocupado.
        self.assertEqual(
            tools.pick_free_vet(self.org, self.executor(), day.isoformat(),
                                "09:00", [self.vet, second]),
            second)


class PrivacyNoticeTests(AgentFixture):
    """W0-6 — el aviso de privacidad se emite, una vez, antes de pedir datos."""

    account_id = "900000006"

    def _ask_for_personal_data(self):
        """El modelo pide las mascotas del cliente aún sin verificar → el
        sistema lanza el reto de identidad (primera recolección de datos)."""
        return run_turn(
            self, self.conv, self.agent_user, "¿qué citas tengo?",
            scripted_llm=[
                LLMResult(kind="tool_call",
                          tool_name="list_upcoming_appointments",
                          tool_args={}),
                # La tool rebota con `verification_required` y el modelo pide
                # el dato. Antes esta segunda vuelta no existía: el router
                # emitía la plantilla del reto y cerraba el turno (É-F5 F2).
                LLMResult(kind="text",
                          text="Para consultarlas necesito confirmar quién "
                               "eres. ¿Cómo se llama tu mascota? 🙂"),
            ],
            assert_clean=False)

    def test_privacy_notice_precedes_first_request_for_personal_data(self):
        """LFPDPPP just-in-time (spec §4): el aviso va ANTES de pedir datos.

        Reescrito en É-F5 Fase 2 — ya no hay «reto de identidad» que preceder,
        porque quien pide el dato es el modelo. Lo que se protege es lo mismo
        y es lo que importa: **el aviso encabeza el turno en el que el sistema
        decide que hace falta identificar a alguien**, y lo antepone el
        sistema, no el modelo (es un literal legal).

        Este test encontró una regresión real: al retirar el paso 12b del
        router desapareció el único productor del aviso para este caso, y
        pedir nombre o dígitos dejó de ir precedido de él.
        """
        bodies, result, _ = self._ask_for_personal_data()
        self.assertEqual(result["decision"], "planner_reply")
        self.assertIn("aviso de privacidad", bodies[-1].lower())
        self.contact.refresh_from_db()
        self.assertIsNotNone(self.contact.privacy_notice_sent_at)

    def test_privacy_notice_is_sent_only_once(self):
        self._ask_for_personal_data()
        first_sent_at = ContactIdentity.objects.get(
            pk=self.contact.pk).privacy_notice_sent_at
        # Segunda petición de datos en la misma conversación → sin repetir el
        # aviso (`privacy_notice_sent_at` es idempotente por contacto).
        bodies, _, _ = run_turn(
            self, self.conv, self.agent_user, "Firulais",
            scripted_llm=[
                LLMResult(kind="tool_call",
                          tool_name="list_upcoming_appointments",
                          tool_args={}),
                LLMResult(kind="text",
                          text="Mmm, ese no me coincide. ¿Me lo repites "
                               "tal como lo registraron? 🙂"),
            ],
            assert_clean=False)
        self.assertNotIn("aviso de privacidad", " ".join(bodies).lower())
        self.assertEqual(
            ContactIdentity.objects.get(pk=self.contact.pk).privacy_notice_sent_at,
            first_sent_at)
