"""
test_slots.py — É-F2 PR-15: find_available_slots (T9) contra la API real.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import executor as executor_module
from apps.agent.executor import ToolExecutor
from apps.agent.models import AgentSettings, ContactIdentity, Conversation
from apps.agent.tools import run_tool
from apps.appointments.models import Appointment
from apps.channels.models import ChannelAccount
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        w, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([w])
    else:
        role.permissions.set([Permission.objects.get_or_create(code=c)[0] for c in codes])
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


class SlotsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Slot Org", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="slot_vet", password="p", organization=cls.org, role="VET")
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)
        cls.owner = Owner.objects.create(organization=cls.org, name="Ana", phone="5511110000")
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Luna",
            species="perro", birth_date="2021-01-01")

    def setUp(self):
        executor_module._token_cache.clear()
        self.agent_user, _ = ensure_agent_user(self.org)
        # Un día futuro que caiga en día hábil (lun-vie): usar +7 y ajustar.
        d = timezone.localdate() + timedelta(days=7)
        while d.weekday() > 4:  # sáb/dom → mover a lunes
            d += timedelta(days=1)
        self.day = d
        wd = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[d.weekday()]
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True, agent_user=self.agent_user,
            default_veterinarian=self.vet,
            business_hours={wd: [["09:00", "13:00"]]},
        )
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770100770")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511110000", owner=self.owner)
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel, contact=self.contact)
        self.executor = ToolExecutor(self.conv, self.agent_user, transport=TestClientTransport())

    def _run(self, args):
        return run_tool("find_available_slots", args,
                        conversation=self.conv, executor=self.executor)

    def _book(self, hhmm):
        from datetime import datetime
        from datetime import timezone as dt_tz
        start = datetime.strptime(hhmm, "%H:%M").time()
        end = (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=30)).time()
        Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="x",
            status="scheduled",
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc),
        )

    def test_offers_slots_within_business_hours(self):
        out = self._run({"date": self.day.isoformat()})
        self.assertTrue(out.ok, out.client_error)
        self.assertEqual(len(out.data), 3)  # cap ≤3
        # primeros huecos de 09:00 en pasos de 30 min
        self.assertEqual(out.data[0]["iso_time"], "09:00")
        self.assertIn("hora", out.data[0])
        self.assertIn("de", out.data[0]["fecha"])  # "... de julio"

    def test_excludes_occupied_slot(self):
        self._book("09:00")
        out = self._run({"date": self.day.isoformat()})
        times = [s["iso_time"] for s in out.data]
        self.assertNotIn("09:00", times)
        self.assertIn("09:30", times)

    def test_closed_day_returns_empty(self):
        # domingo (sin business_hours) → vacío, no error
        sunday = self.day
        while sunday.weekday() != 6:
            sunday += timedelta(days=1)
        out = self._run({"date": sunday.isoformat()})
        self.assertTrue(out.ok)
        self.assertEqual(out.data, [])

    def test_past_date_rejected(self):
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        out = self._run({"date": past})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "past_date")

    def test_preferred_time_filter(self):
        # rango 09-13; preferimos "tarde" (12+) → solo 12:00, 12:30
        out = self._run({"date": self.day.isoformat(), "preferred_time": "tarde"})
        times = [s["iso_time"] for s in out.data]
        self.assertTrue(all(t >= "12:00" for t in times), times)

    def test_bad_date_format(self):
        out = self._run({"date": "mañana"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "bad_date")
