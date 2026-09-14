"""
test_clinic_context.py — El agente lee la config de clínica de la fuente única
(Organization + OrganizationSchedule, ADR p53), con fallback legacy.

Nota: el signal initialize_organization siembra 7 filas de horario por defecto
al crear una org (L-V 9-18, Sáb 9-14, Dom cerrado). Los tests que aíslan la
lógica de horario LIMPIAN ese seed primero.
"""
from datetime import time

from django.test import TestCase

from apps.agent import clinic_context
from apps.agent.models import AgentSettings, ContactIdentity, Conversation
from apps.agent.tools import get_clinic_info
from apps.channels.models import ChannelAccount
from apps.organizations.models import Organization, OrganizationSchedule


class _FakeExecutor:
    """get_clinic_info es una tool LOCAL: audita vía executor.record_local."""
    def record_local(self, **kwargs):
        return None


class ClinicFactsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Clinic Org", timezone="America/Mexico_City",
            phone="5555550000", email="hola@clinica.mx",
            address_line1="Av. Reforma 100", city="CDMX",
            google_maps_url="https://maps.google.com/?q=clinica",
            arrival_instructions="Timbre azul, segundo piso.")

    def test_clinic_facts_from_organization(self):
        facts = clinic_context.clinic_facts(self.org)
        self.assertEqual(facts["teléfono"], "5555550000")
        self.assertEqual(facts["correo"], "hola@clinica.mx")
        self.assertIn("Av. Reforma 100", facts["dirección"])
        self.assertIn("CDMX", facts["dirección"])
        self.assertIn("maps.google", facts["mapa"])
        self.assertIn("Timbre azul", facts["indicaciones"])

    def test_empty_fields_absent(self):
        bare = Organization.objects.create(name="Bare", timezone="UTC")
        self.assertEqual(clinic_context.clinic_facts(bare), {})


class EffectiveHoursTests(TestCase):
    """"¿Estamos abiertos?" y "¿qué huecos hay?" leen la MISMA fuente.

    El aviso de fuera de horario miraba `AgentSettings.business_hours` mientras
    los slots ya usaban `OrganizationSchedule`: una clínica ofertaba huecos
    correctos y jamás decía que estaba cerrada. `business_hours` se eliminó.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Hours Org", timezone="UTC")
        OrganizationSchedule.objects.filter(organization=self.org).delete()
        self.settings = AgentSettings.objects.create(organization=self.org)

    def test_hours_come_from_the_schedule(self):
        OrganizationSchedule.objects.create(
            organization=self.org, weekday=1,
            opens_at=time(8), closes_at=time(16))
        hours = clinic_context.effective_business_hours(self.org, self.settings)
        self.assertEqual(hours["mon"], [["08:00", "16:00"]])

    def test_break_produces_two_windows(self):
        OrganizationSchedule.objects.create(
            organization=self.org, weekday=2,
            opens_at=time(9), closes_at=time(18), has_break=True,
            break_start=time(13), break_end=time(15))
        hours = clinic_context.effective_business_hours(self.org, self.settings)
        self.assertEqual(hours["tue"], [["09:00", "13:00"], ["15:00", "18:00"]])

    def test_no_schedule_is_empty(self):
        self.assertEqual(
            clinic_context.effective_business_hours(self.org, self.settings), {})

    def test_closed_all_week_is_not_the_same_as_unconfigured(self):
        """"Cerrado hoy" debe avisar; "sin configurar" no debe inventar nada."""
        from apps.agent.tier0 import is_open_now
        for weekday in range(1, 8):
            OrganizationSchedule.objects.create(
                organization=self.org, weekday=weekday, is_closed=True)
        hours = clinic_context.effective_business_hours(self.org, self.settings)
        self.assertTrue(hours)                      # el horario EXISTE…
        self.assertFalse(is_open_now(hours, "UTC"))  # …y dice que está cerrado
        self.assertIsNone(is_open_now({}, "UTC"))    # sin configurar → None

    def test_open_now_reads_the_new_schedule(self):
        from apps.agent.tier0 import is_open_now
        for weekday in range(1, 8):
            OrganizationSchedule.objects.create(
                organization=self.org, weekday=weekday,
                opens_at=time(0), closes_at=time(23, 59))
        hours = clinic_context.effective_business_hours(self.org, self.settings)
        self.assertTrue(is_open_now(hours, "UTC"))


class ClinicPhoneTests(TestCase):
    """El teléfono de urgencias sale de la configuración de clínica."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Phone Org", timezone="UTC", phone="5511112222")
        self.settings = AgentSettings.objects.create(organization=self.org)

    def test_phone_comes_from_the_organization(self):
        self.assertEqual(
            clinic_context.clinic_phone(self.org, self.settings), "5511112222")

    def test_without_phone_returns_empty(self):
        Organization.objects.filter(pk=self.org.pk).update(phone="")
        self.org.refresh_from_db()
        self.assertEqual(
            clinic_context.clinic_phone(self.org, self.settings), "")

    def test_emergency_template_uses_the_configured_phone(self):
        from apps.agent.tier0 import render_emergency
        text = render_emergency(self.settings, self.org)
        self.assertIn("5511112222", text)

    def test_emergency_without_any_phone_omits_it(self):
        from apps.agent.tier0 import render_emergency
        bare = Organization.objects.create(name="Bare Phone", timezone="UTC")
        text = render_emergency(None, bare)
        self.assertIn("atención veterinaria presencial disponible", text)
        self.assertIn("no esperes una respuesta por este chat", text)
        self.assertNotIn("llámanos al", text)


class ScheduleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Sched Org", timezone="UTC")
        # Aislar la lógica: partir de cero (sin el seed del signal).
        OrganizationSchedule.objects.filter(organization=self.org).delete()

    def _day(self, weekday, **kw):
        return OrganizationSchedule.objects.create(
            organization=self.org, weekday=weekday, **kw)

    def test_ranges_with_break_gives_two_windows(self):
        self._day(1, opens_at=time(9), closes_at=time(14), has_break=True,
                  break_start=time(12), break_end=time(13))
        ranges = clinic_context.weekday_ranges(self.org, 0)  # 0 = lunes
        self.assertEqual(ranges, [["09:00", "12:00"], ["13:00", "14:00"]])

    def test_closed_day_empty(self):
        self._day(2, is_closed=True)
        self.assertEqual(clinic_context.weekday_ranges(self.org, 1), [])

    def test_schedule_present_but_missing_weekday_is_closed(self):
        self._day(1, opens_at=time(9), closes_at=time(17))
        self.assertEqual(clinic_context.weekday_ranges(self.org, 6), [])  # dom

    def test_no_schedule_means_closed(self):
        """Sin fila de horario el agente no ofrece huecos; jamás inventa uno
        (ya no existe un `business_hours` del que tirar)."""
        self.assertEqual(clinic_context.weekday_ranges(self.org, 0), [])

    def test_humanize_schedule(self):
        self._day(1, opens_at=time(9), closes_at=time(14))
        self._day(3, is_closed=True)
        human = clinic_context.humanize_schedule(self.org)
        self.assertIn("lun 09:00 a 14:00", human)
        self.assertNotIn("mié", human)

    def test_default_seed_is_source_of_truth(self):
        # Una org recién creada (con el seed del signal) → lunes 09-18.
        fresh = Organization.objects.create(name="Seeded", timezone="UTC")
        self.assertEqual(clinic_context.weekday_ranges(fresh, 0),
                         [["09:00", "18:00"]])
        self.assertEqual(clinic_context.weekday_ranges(fresh, 6), [])  # dom cerrado


class GetClinicInfoIntegrationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Info Org", timezone="UTC", phone="5544332211")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="123123123")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500000000")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)
        self.ex = _FakeExecutor()

    def test_org_overrides_legacy_faq(self):
        AgentSettings.objects.create(
            organization=self.org, enabled=True,
            faq_facts={"teléfono": "0000000000", "estacionamiento": "Sí"})
        out = get_clinic_info(self.conv, self.ex, {})
        self.assertEqual(out.data["teléfono"], "5544332211")   # config nueva gana
        self.assertEqual(out.data["estacionamiento"], "Sí")    # legacy se conserva

    def test_schedule_is_the_only_source_of_hours(self):
        AgentSettings.objects.create(organization=self.org, enabled=True)
        # Ajustar el horario sembrado del lunes a 09-18.
        OrganizationSchedule.objects.filter(
            organization=self.org, weekday=1).update(
            opens_at=time(9), closes_at=time(18), is_closed=False)
        out = get_clinic_info(self.conv, self.ex, {})
        self.assertIn("09:00 a 18:00", out.data["horario"])
        self.assertNotIn("06:00", out.data["horario"])
