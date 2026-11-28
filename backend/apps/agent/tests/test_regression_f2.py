"""
test_regression_f2.py — Suite de regresión conversacional F2 (É-F2 PR-19).

Los 30 casos de escritura congelados (spec §9.4: INT-20..24 + TC-UX-05) corren
en CI contra el stub determinista, atravesando el pipeline REAL
(policy → planner → tools loopback con RBAC del AGENT). TC-INT20-06 (confirmación
vencida) y TC-SEC-03 (afirmativa con extra) son bloqueantes absolutos (§10).

Convención de scripting:
- tool tier-2 (create/cancel/reschedule/register) PROPONE → el planner cierra el
  turno con el parafraseo, sin 2ª llamada al LLM → se scripta [tool_call].
- tool tier-1 (confirm) y lecturas ejecutan y realimentan → [tool_call, text].
- la afirmativa ("sí") la resuelve el Policy Engine sin LLM → scripted vacío.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .harness import legacy_write_component
from apps.agent import executor as executor_module
from apps.agent import confirmations, matter_binding, matter_resolution, tools
from apps.agent.llm import LLMResult
from apps.agent.models import AgentSettings, ContactIdentity, Conversation
from apps.agent.tests.harness import run_turn, set_schedule_day
from apps.appointments.models import Appointment
from apps.channels.models import ChannelAccount
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



@legacy_write_component
class RegF2Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="RegF2 Org", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="regf2_vet", password="p", organization=cls.org, role="VET")
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana Torres", phone="5511995566")
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
        wd = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[d.weekday()]
        self.settings = create_enabled_agent_settings(self.org, agent_user=self.agent_user,
            default_veterinarian=self.vet)
        # Horario y contacto: fuente única = configuración de clínica (p53).
        set_schedule_day(self.org, d.weekday(), "09:00", "13:00")
        Organization.objects.filter(pk=self.org.pk).update(
            phone="55-1000-2000", address_line1="Av. Siempre Viva 123")
        self.org.refresh_from_db()
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="931931931")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511995566",
            owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            verified_at=timezone.now())
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)
        self.conv.flow["refs"] = {"mascota_1": str(self.pet.public_id)}
        self.conv.save(update_fields=["flow"])

    # -- helpers ------------------------------------------------------------
    def _turn(self, text, scripted):
        # F2 exercises the inactive legacy component: its scripted tool args
        # have no B6 message provenance. Do not turn that fixture into a bound
        # matter halfway through the test. Versioned fixtures retain real B6.
        resolve = matter_resolution.process_turn

        def resolve_versioned(conversation, context):
            goal = matter_binding.current_goal(conversation)
            if goal and matter_binding.metadata(goal):
                return resolve(conversation, context)
            return None

        with patch.object(matter_resolution, 'process_turn',
                          side_effect=resolve_versioned):
            return run_turn(self, self.conv, self.agent_user, text,
                            scripted_llm=scripted)

    def _propose(self, text, tool_name, tool_args):
        return self._turn(text, [LLMResult(
            kind="tool_call", tool_name=tool_name, tool_args=tool_args)])

    def _yes(self, text="sí"):
        self.conv.refresh_from_db()
        return self._turn(text, [])

    def _make_appt(self, hhmm="11:00", status="scheduled"):
        start = datetime.strptime(hhmm, "%H:%M").time()
        end = (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=30)).time()
        appt = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="control",
            status=status,
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc))
        tools._add_ref(self.conv, "cita", appt.public_id)
        tools._save_refs(self.conv)
        return appt

    def _book_slot(self, hhmm):
        """Ocupa un slot para el vet (simula la carrera B5)."""
        start = datetime.strptime(hhmm, "%H:%M").time()
        end = (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=30)).time()
        other = Pet.objects.create(
            organization=self.org, owner=self.owner, name="Otro",
            species="gato", birth_date="2020-01-01")
        Appointment.objects.create(
            organization=self.org, pet=other, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="x",
            status="scheduled",
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc))

    def _unknown_conv(self, wa="5215512345678"):
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id=wa,
            verification_level="unknown")
        return Conversation.objects.create(
            organization=self.org,
            channel_account=self.channel,
            contact=contact,
            # Los casos INT-21 parten de una primera visita ya clasificada;
            # representamos el hecho tipado de `set_client_path`.
            intake_path=Conversation.INTAKE_NEW_CLIENT,
        )


# ===========================================================================
# INT-20 · Agendar cita (cliente existente)
# ===========================================================================

class Int20Tests(RegF2Base):
    def _create_args(self, time="10:00"):
        return {"pet_handle": "mascota_1", "date": self.day.isoformat(),
                "time": time, "reason": "Vacunación"}

    def test_20_01_offer_then_create(self):
        # ofrece horarios (T9) y luego propone crear
        bodies, result, _ = self._turn("quiero agendar a Luna", [
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": self.day.isoformat()}),
            LLMResult(kind="text", text="Tengo 9:00, 9:30 o 10:00 🙂"),
        ])
        self.assertEqual(result["decision"], "planner_reply")
        # confirma agendando el 10:00
        _, r2, _ = self._propose("el de las 10", "create_appointment",
                                 self._create_args())
        self.assertEqual(r2["decision"], "awaiting_confirmation")
        _, r3, _ = self._yes()
        self.assertEqual(r3["decision"], "committed")
        self.assertEqual(Appointment.objects.filter(pet=self.pet).count(), 1)

    def test_20_02_all_slots_direct_to_confirm(self):
        _, r1, _ = self._propose("agéndame el jueves 10am", "create_appointment",
                                 self._create_args())
        self.assertEqual(r1["decision"], "awaiting_confirmation")
        _, r2, _ = self._yes()
        self.assertEqual(r2["decision"], "committed")
        self.assertEqual(Appointment.objects.count(), 1)

    def test_20_03_b5_race_slot_taken(self):
        self._propose("agenda 10am", "create_appointment", self._create_args())
        self._book_slot("10:00")            # otro cliente gana la carrera
        bodies, r2, _ = self._yes()
        self.assertEqual(r2["decision"], "commit_slot_taken")
        self.assertIn("ocup", bodies[-1].lower())
        self.assertEqual(Appointment.objects.filter(pet=self.pet).count(), 0)

    def test_20_04_modification_makes_new_pending(self):
        self._propose("10am", "create_appointment", self._create_args("10:00"))
        # en vez de "sí", modifica → nuevo pending, nada se ejecuta
        _, r2, _ = self._propose("mejor a las 12", "create_appointment",
                                 self._create_args("12:00"))
        self.assertEqual(r2["decision"], "awaiting_confirmation")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(
            confirmations.get_pending(self.conv)["args"]["start_time"], "12:00")

    def test_20_05_b3_past_date_blocked(self):
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        self._propose("agenda ayer", "create_appointment", {
            "pet_handle": "mascota_1", "date": past, "time": "10:00",
            "reason": "x"}, )
        self.assertIsNone(confirmations.get_pending(self.conv))
        self.assertEqual(Appointment.objects.count(), 0)

    def test_20_06_expired_confirmation_never_executes(self):
        """BLOQUEANTE ABSOLUTO (TC-INT20-06)."""
        self._propose("10am", "create_appointment", self._create_args())
        pending = confirmations.get_pending(self.conv)
        pending["expires_at"] = (
            timezone.now() - timedelta(minutes=1)).isoformat()
        self.conv.flow["pending_action"] = pending
        self.conv.save(update_fields=["flow"])
        bodies, r2, _ = self._yes()
        self.assertEqual(r2["decision"], "confirm_expired")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertIn("de nuevo", bodies[-1].lower())

    def test_20_08_no_vet_escalates(self):
        self.settings.default_veterinarian = None
        self.settings.save(update_fields=["default_veterinarian"])
        self.vet.is_active = False
        self.vet.save(update_fields=["is_active"])
        # sin vet resoluble → la tool falla; 2 fallos → handoff
        self._propose("agenda", "create_appointment", self._create_args())
        self._turn("agenda", [LLMResult(
            kind="tool_call", tool_name="create_appointment",
            tool_args=self._create_args())])
        self.assertEqual(Appointment.objects.count(), 0)

    def test_20_09_b6_fixed_vet_used(self):
        self._propose("10am", "create_appointment", self._create_args())
        self._yes()
        appt = Appointment.objects.get()
        self.assertEqual(appt.veterinarian, self.vet)   # default_veterinarian


class Int20IdempotencyTests(RegF2Base):
    def test_20_07_idempotent_commit_no_double_booking(self):
        """B7 (TC-INT20-07): reintentar el commit con la misma key = 1 cita."""
        from apps.agent.executor import ToolExecutor
        from apps.agent.tests.test_write_tools import HeaderForwardingTransport
        ex = ToolExecutor(self.conv, self.agent_user,
                          transport=HeaderForwardingTransport())
        tools.create_appointment(self.conv, ex, {
            "pet_handle": "mascota_1", "date": self.day.isoformat(),
            "time": "10:00", "reason": "x"})
        staged = confirmations.get_pending(self.conv)["args"]
        tools.commit_create_appointment(self.conv, ex, staged)
        tools.commit_create_appointment(self.conv, ex, staged)   # replay
        self.assertEqual(Appointment.objects.filter(pet=self.pet).count(), 1)


# ===========================================================================
# INT-21 · Alta de cliente nuevo (self-registration)
# ===========================================================================

class Int21Tests(RegF2Base):
    def _reg_args(self):
        return {"owner_name": "Carlos", "pet_name": "Rocky",
                "pet_species": "canino", "date": self.day.isoformat(),
                "time": "10:00", "reason": "Consulta"}

    def test_21_01_happy_registration(self):
        conv = self._unknown_conv()
        run_turn(self, conv, self.agent_user, "soy nuevo, quiero cita",
                 scripted_llm=[LLMResult(
                     kind="tool_call", tool_name="register_new_client_and_pet",
                     tool_args=self._reg_args())])
        conv.refresh_from_db()
        bodies, rc, _ = run_turn(self, conv, self.agent_user, "sí",
                                 scripted_llm=[])
        self.assertEqual(rc["decision"], "committed", (rc, bodies))
        owner = Owner.objects.get(phone="5512345678")
        self.assertEqual(owner.name, "Carlos")
        self.assertEqual(Appointment.objects.filter(pet__owner=owner).count(), 1)
        conv.contact.refresh_from_db()
        self.assertEqual(conv.contact.linked_via, "self_register")

    def test_21_02_b4_identity_conflict_no_write(self):
        # el contacto YA tiene owner (phone_match) → jamás auto-registra
        before = Owner.objects.count()
        self._turn("regístrame como nuevo", [
            LLMResult(kind="tool_call", tool_name="register_new_client_and_pet",
                      tool_args=self._reg_args()),
            LLMResult(kind="text", text="Veo visitas previas desde este número 🙂"),
        ])
        self.assertEqual(Owner.objects.count(), before)   # cero altas

    def test_21_03_b1_unknown_species_registers_blank(self):
        # El cliente suele decir la RAZA ("maltés") como especie. En vez de
        # fallar (400 → rebote), se normaliza: raza conocida → especie; raza
        # desconocida → vacío (pendiente). SIEMPRE registra.
        conv = self._unknown_conv("5215512345679")
        args = self._reg_args()
        args["pet_species"] = "maltés"   # raza, no especie
        run_turn(self, conv, self.agent_user, "nuevo", scripted_llm=[
            LLMResult(kind="tool_call", tool_name="register_new_client_and_pet",
                      tool_args=args)])
        conv.refresh_from_db()
        run_turn(self, conv, self.agent_user, "sí", scripted_llm=[])
        owner = Owner.objects.filter(phone="5512345679").first()
        self.assertIsNotNone(owner)               # se registró pese a la "raza"
        pet = Pet.objects.filter(owner=owner).first()
        self.assertEqual(pet.species, "")         # especie pendiente, sin error

    def test_21_03b_breed_phrase_maps_to_species(self):
        conv = self._unknown_conv("5215512345678")
        args = self._reg_args()
        args["pet_species"] = "una perrita maltés"
        run_turn(self, conv, self.agent_user, "nuevo", scripted_llm=[
            LLMResult(kind="tool_call", tool_name="register_new_client_and_pet",
                      tool_args=args)])
        conv.refresh_from_db()
        run_turn(self, conv, self.agent_user, "sí", scripted_llm=[])
        pet = Pet.objects.filter(owner__phone="5512345678").first()
        self.assertEqual(pet.species, "canino")   # detecta "perrita" → canino

    def test_21_04_b5_ambiguous_zero_registration(self):
        conv = self._unknown_conv("5215512345670")
        conv.contact.is_ambiguous = True
        conv.contact.save(update_fields=["is_ambiguous"])
        before = Owner.objects.count()
        run_turn(self, conv, self.agent_user, "nuevo", scripted_llm=[
            LLMResult(kind="tool_call", tool_name="register_new_client_and_pet",
                      tool_args=self._reg_args()),
            LLMResult(kind="text", text="Déjame validar tus datos con el equipo 🙂"),
        ])
        self.assertEqual(Owner.objects.count(), before)

    def test_21_05_bis_new_pet_existing_owner(self):
        self.skipTest(
            "INT-21-bis (mascota nueva de cliente existente) sin tool en "
            "PR-17a; el alta reusa create-with-patient — pendiente de PR futuro.")

    def test_21_06_b2_other_phone_ignored_g8(self):
        """El teléfono SIEMPRE sale del wa_id, jamás uno dictado (G8)."""
        conv = self._unknown_conv("5215512349999")
        run_turn(self, conv, self.agent_user, "mi tel es 5599999999",
                 scripted_llm=[LLMResult(
                     kind="tool_call", tool_name="register_new_client_and_pet",
                     tool_args=self._reg_args())])
        conv.refresh_from_db()
        self.assertEqual(
            confirmations.get_pending(conv)["args"]["owner_phone"], "5512349999")

    def test_unknown_number_reaches_the_model_without_escalating(self):
        """Número NO registrado que quiere agendar: ni handoff, ni asumir el
        alta, ni una plantilla — **llega al modelo**.

        Reescrito en É-F5 Fase 2. El tamiz determinista que lo interceptaba se
        retiró: nació para corregir el sobre-escalado del piloto y lo consiguió,
        pero al precio de responder por plantilla antes de que nadie leyera el
        mensaje. Lo que se conserva es el resultado que importaba —no escalar y
        no inventar un alta— con el modelo conduciendo.
        """
        conv = self._unknown_conv("5215512340000")
        bodies, r, _ = run_turn(
            self, conv, self.agent_user, "quiero agendar una cita",
            scripted_llm=[LLMResult(
                kind="text",
                text="¡Claro! ¿Cómo se llama tu peludo? 🐾")])

        self.assertEqual(r["decision"], "planner_reply")
        self.assertGreater(r["llm_calls"], 0, "el modelo no vio el turno")
        from apps.agent.models import HumanHandoff
        self.assertFalse(
            HumanHandoff.objects.filter(conversation=conv).exists(),
            "un número desconocido pidiendo cita no debe escalar")

    def test_ux05_prior_visit_no_registration(self):
        """TC-UX-05: 'ya nos han atendido' + contacto con owner → cero altas."""
        before = Owner.objects.count()
        self._turn("ya nos han atendido aquí, agéndame", [
            LLMResult(kind="tool_call", tool_name="register_new_client_and_pet",
                      tool_args={"owner_name": "X", "pet_name": "Y",
                                 "date": self.day.isoformat(), "time": "10:00",
                                 "reason": "z"}),
            LLMResult(kind="text", text="¡Claro! ¿Para cuál de tus mascotas? 🐾"),
        ])
        self.assertEqual(Owner.objects.count(), before)


# ===========================================================================
# INT-22 · Confirmar asistencia (tier-1, inmediato)
# ===========================================================================

class Int22Tests(RegF2Base):
    def test_22_01_confirm_happy(self):
        appt = self._make_appt(status="scheduled")
        self._turn("sí voy a asistir", [
            LLMResult(kind="tool_call", tool_name="confirm_appointment",
                      tool_args={"appointment_handle": "cita_1"}),
            LLMResult(kind="text", text="¡Perfecto, quedó confirmada! ✅"),
        ])
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")

    def test_22_02_confirm_already_confirmed_noop(self):
        appt = self._make_appt(status="confirmed")
        self._turn("confirmo", [
            LLMResult(kind="tool_call", tool_name="confirm_appointment",
                      tool_args={"appointment_handle": "cita_1"}),
            LLMResult(kind="text", text="Ya la tenías confirmada 🙂"),
        ])
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")

    def test_22_03_confirm_unknown_handle(self):
        bodies, _, _ = self._turn("confirmo", [
            LLMResult(kind="tool_call", tool_name="confirm_appointment",
                      tool_args={"appointment_handle": "cita_9"}),
            LLMResult(kind="text", text="No encuentro esa cita 🙂"),
        ])
        self.assertTrue(bodies)

    def test_22_04_confirm_canceled_is_noop(self):
        appt = self._make_appt(status="canceled")
        self._turn("confirmo", [
            LLMResult(kind="tool_call", tool_name="confirm_appointment",
                      tool_args={"appointment_handle": "cita_1"}),
            LLMResult(kind="text", text="Esa cita ya no está activa 🙂"),
        ])
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")   # no revive


# ===========================================================================
# INT-23 · Cancelar cita (tier-2)
# ===========================================================================

class Int23Tests(RegF2Base):
    def test_23_01_cancel_happy_with_retention(self):
        for weekday in range(7):          # abierta toda la semana
            set_schedule_day(self.org, weekday, "09:00", "13:00")
        appt = self._make_appt(status="confirmed")
        _, r1, _ = self._propose("cancela mi cita", "cancel_appointment",
                                 {"appointment_handle": "cita_1"})
        self.assertEqual(r1["decision"], "awaiting_confirmation")
        bodies, r2, _ = self._yes()
        self.assertEqual(r2["decision"], "committed")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")
        # UX-11: cancellation offers another appointment without booking it.
        self.assertIn("agendar otra", bodies[-1].lower())
        self.assertIn("¿te acomoda alguno?", bodies[-1].lower())
        self.assertEqual(Appointment.objects.filter(pet=self.pet).count(), 1)

    def test_23_02_cancel_requires_paraphrase(self):
        self._make_appt(status="scheduled")
        bodies, r1, _ = self._propose("cancela", "cancel_appointment",
                                      {"appointment_handle": "cita_1"})
        self.assertEqual(r1["decision"], "awaiting_confirmation")
        self.assertIn("cancelar", bodies[-1].lower())
        self.assertIn("Luna", bodies[-1])

    def test_23_03_cancel_done_not_cancelable(self):
        self._make_appt(status="done")
        self._propose("cancela", "cancel_appointment",
                      {"appointment_handle": "cita_1"})
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_23_04_negative_discards_pending(self):
        appt = self._make_appt(status="confirmed")
        self._propose("cancela", "cancel_appointment",
                      {"appointment_handle": "cita_1"})
        self.conv.refresh_from_db()
        self._turn("no, mejor déjala", [
            LLMResult(kind="text", text="¡De acuerdo, la dejo! 🙂")])
        self.assertIsNone(confirmations.get_pending(self.conv))
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")

    def test_23_05_cancel_unknown_handle(self):
        self._propose("cancela", "cancel_appointment",
                      {"appointment_handle": "cita_9"})
        self.assertIsNone(confirmations.get_pending(self.conv))


# ===========================================================================
# INT-24 · Reagendar cita (tier-2)
# ===========================================================================

class Int24Tests(RegF2Base):
    def test_24_01_reschedule_happy(self):
        appt = self._make_appt(hhmm="09:00", status="scheduled")
        _, r1, _ = self._propose("muévela a las 12", "reschedule_appointment",
                                 {"appointment_handle": "cita_1",
                                  "new_date": self.day.isoformat(),
                                  "new_time": "12:00"})
        self.assertEqual(r1["decision"], "awaiting_confirmation")
        _, r2, _ = self._yes()
        self.assertEqual(r2["decision"], "committed")
        appt.refresh_from_db()
        self.assertEqual(appt.start_time.strftime("%H:%M"), "12:00")

    def test_24_02_reschedule_to_past_blocked(self):
        self._make_appt(status="scheduled")
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        self._propose("muévela a ayer", "reschedule_appointment",
                      {"appointment_handle": "cita_1", "new_date": past,
                       "new_time": "10:00"})
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_24_03_reschedule_done_blocked(self):
        self._make_appt(status="done")
        self._propose("muévela", "reschedule_appointment",
                      {"appointment_handle": "cita_1",
                       "new_date": self.day.isoformat(), "new_time": "12:00"})
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_24_04_reschedule_race_slot_taken(self):
        appt = self._make_appt(hhmm="09:00", status="scheduled")
        self._propose("muévela a las 12", "reschedule_appointment",
                      {"appointment_handle": "cita_1",
                       "new_date": self.day.isoformat(), "new_time": "12:00"})
        self._book_slot("12:00")            # se ocupa el destino
        bodies, r2, _ = self._yes()
        self.assertEqual(r2["decision"], "commit_slot_taken")
        appt.refresh_from_db()
        self.assertEqual(appt.start_time.strftime("%H:%M"), "09:00")   # no movió

    def test_24_05_reschedule_unknown_handle(self):
        self._propose("muévela", "reschedule_appointment",
                      {"appointment_handle": "cita_9",
                       "new_date": self.day.isoformat(), "new_time": "12:00"})
        self.assertIsNone(confirmations.get_pending(self.conv))
