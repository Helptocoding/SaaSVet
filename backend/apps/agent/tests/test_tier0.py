"""
test_tier0.py — É-F0 PR-5: plantillas tier-0 (LITERALES, spec §1.3) y horario.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from apps.agent.models import AgentSettings
from apps.agent.tier0 import (
    T0_AFTER_HOURS_SUFFIX,
    T0_DISABLED,
    T0_GREET,
    is_open_now,
    render_first_reply,
)
from apps.organizations.models import Organization
from apps.agent.tests.harness import set_schedule_day
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings

HOURS = {
    "mon": [["09:00", "19:00"]],
    "tue": [["09:00", "19:00"]],
    "wed": [["09:00", "14:00"], ["16:00", "19:00"]],
    "sat": [["09:00", "14:00"]],
    "sun": [],
}


def _cdmx(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute,
                    tzinfo=ZoneInfo("America/Mexico_City"))


class IsOpenNowTests(SimpleTestCase):
    def test_open_within_range(self):
        # 2026-07-13 es lunes.
        self.assertTrue(is_open_now(HOURS, "America/Mexico_City",
                                    now=_cdmx(2026, 7, 13, 10)))

    def test_closed_outside_range(self):
        self.assertFalse(is_open_now(HOURS, "America/Mexico_City",
                                     now=_cdmx(2026, 7, 13, 20)))

    def test_split_shift_gap_is_closed(self):
        # Miércoles 15:00 — entre los dos turnos.
        self.assertFalse(is_open_now(HOURS, "America/Mexico_City",
                                     now=_cdmx(2026, 7, 15, 15)))

    def test_day_without_ranges_is_closed(self):
        # Domingo 2026-07-19.
        self.assertFalse(is_open_now(HOURS, "America/Mexico_City",
                                     now=_cdmx(2026, 7, 19, 11)))

    def test_unconfigured_returns_none(self):
        self.assertIsNone(is_open_now({}, "America/Mexico_City"))
        self.assertIsNone(is_open_now(None, "America/Mexico_City"))

    def test_bad_timezone_returns_none(self):
        self.assertIsNone(is_open_now(HOURS, "No/Existe"))

    def test_timezone_is_respected(self):
        """Mismo instante: abierto en CDMX, y la evaluación usa la tz de la
        ORG, no la del servidor — 18:30 CDMX = 00:30 UTC del día siguiente."""
        instant = _cdmx(2026, 7, 13, 18, 30)  # lunes 18:30 local → abierto
        self.assertTrue(is_open_now(HOURS, "America/Mexico_City", now=instant))


class RenderFirstReplyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(
            name="Clínica Patitas", timezone="America/Mexico_City",
        )

    def setUp(self):
        # El alta de organización siembra 7 filas de horario; estos tests
        # parten de "sin horario" y lo fijan cuando lo necesitan.
        from apps.organizations.models import OrganizationSchedule
        OrganizationSchedule.objects.filter(organization=self.org).delete()

    def test_disabled_settings_renders_t0_disabled(self):
        settings_obj = AgentSettings.objects.create(organization=self.org)
        text = render_first_reply(settings_obj, self.org)
        self.assertEqual(text, T0_DISABLED.format(clinic="Clínica Patitas"))

    def test_missing_settings_renders_t0_disabled(self):
        text = render_first_reply(None, self.org)
        self.assertEqual(text, T0_DISABLED.format(clinic="Clínica Patitas"))

    def test_enabled_without_hours_renders_plain_greet(self):
        settings_obj = create_enabled_agent_settings(self.org,
        )
        text = render_first_reply(settings_obj, self.org)
        self.assertEqual(text, T0_GREET.format(clinic="Clínica Patitas"))
        self.assertNotIn(T0_AFTER_HOURS_SUFFIX, text)

    def test_enabled_after_hours_appends_suffix(self):
        settings_obj = create_enabled_agent_settings(self.org,
        )
        # 2026-07-13 es lunes: abierto 09-19, así que a las 22:00 está cerrado.
        set_schedule_day(self.org, 0, "09:00", "19:00")
        text = render_first_reply(
            settings_obj, self.org, now=_cdmx(2026, 7, 13, 22),
        )
        self.assertTrue(text.startswith(T0_GREET.format(clinic="Clínica Patitas")))
        self.assertIn(T0_AFTER_HOURS_SUFFIX, text)

    def test_greet_has_no_links_and_no_persona_name(self):
        """Decisiones UX-01/§2.1: saludo institucional — sin URL, sin 'Soy'."""
        text = T0_GREET.format(clinic="X")
        self.assertNotIn("http", text)
        self.assertNotIn("Soy ", text)
