"""Lo que la agenda del personal lee de la clínica (ADR p70, plan F2.2/F2.3).

`GET /api/appointments/agenda-config/`, bajo `appointment.list` (decisión del PO,
27-11-2026): VET y ASSISTANT no tienen `organization.retrieve`, así que la agenda
no podía leer el horario, los cierres ni los ajustes (`/organizations/settings/`
les daba 403 y la página lo callaba). Este endpoint expone solo eso.
"""
from datetime import timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.datetime_utils import org_today_local
from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization, OrganizationClosure, OrganizationSettings
from apps.users.models import User

URL = '/api/appointments/agenda-config/'


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class AgendaConfigTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clínica Agenda', timezone='America/Mexico_City')
        cls.other = Organization.objects.create(name='Otra Clínica', timezone='America/Mexico_City')
        cls.vet = User.objects.create_user(username='ag_vet', password='p', organization=cls.org, role='VET')
        cls.assistant = User.objects.create_user(
            username='ag_asst', password='p', organization=cls.org, role='ASSISTANT')
        settings, _ = OrganizationSettings.objects.get_or_create(organization=cls.org)
        settings.default_appointment_duration_minutes = 45
        settings.show_status_change_history = False
        settings.allow_anonymous_walkin = True
        settings.save()
        today = org_today_local(cls.org)
        cls.today = today
        cls.upcoming = OrganizationClosure.objects.create(
            organization=cls.org, start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=11), reason='Inventario', created_by=cls.vet)
        cls.current = OrganizationClosure.objects.create(
            organization=cls.org, start_date=today - timedelta(days=1),
            end_date=today, reason='Día festivo', created_by=cls.vet)
        OrganizationClosure.objects.create(
            organization=cls.org, start_date=today - timedelta(days=5),
            end_date=today - timedelta(days=4), reason='Ya pasó', created_by=cls.vet)
        OrganizationClosure.objects.create(
            organization=cls.org, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=3), reason='Cancelado', created_by=cls.vet,
            cancelled_at=cls.upcoming.created_at, cancelled_by=cls.vet)
        other_vet = User.objects.create_user(username='ag_other', password='p',
                                             organization=cls.other, role='VET')
        OrganizationClosure.objects.create(
            organization=cls.other, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=2), reason='De otra clínica', created_by=other_vet)

    def test_vet_and_assistant_read_it(self):
        for user in (self.vet, self.assistant):
            response = _client(user).get(URL)
            self.assertEqual(response.status_code, 200, user.role)
            self.assertEqual(set(response.data), {'schedule', 'closures', 'settings'})

    def test_they_still_cannot_read_the_clinic_settings(self):
        # El motivo del endpoint: la lectura general sigue reservada.
        self.assertEqual(_client(self.vet).get('/api/organizations/settings/').status_code, 403)

    def test_settings_are_only_what_the_agenda_uses(self):
        data = _client(self.vet).get(URL).data
        self.assertEqual(data['settings'], {
            'default_appointment_duration_minutes': 45,
            'show_status_change_history': False,
            'allow_anonymous_walkin': True,
        })

    def test_schedule_has_the_seven_days(self):
        schedule = _client(self.vet).get(URL).data['schedule']
        self.assertEqual([day['weekday'] for day in schedule], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(set(schedule[0]), {
            'weekday', 'is_closed', 'opens_at', 'closes_at', 'has_break', 'break_start', 'break_end'})

    def test_closures_are_the_active_ones_not_finished_of_this_clinic(self):
        closures = _client(self.vet).get(URL).data['closures']
        self.assertEqual([c['reason'] for c in closures], ['Día festivo', 'Inventario'])
        self.assertEqual(set(closures[0]), {'public_id', 'start_date', 'end_date', 'reason'})

    def test_requires_appointment_list(self):
        role = Role.objects.create(name='Solo pacientes', organization=self.org, is_system_role=False)
        role.permissions.set([Permission.objects.get_or_create(code='patient.list')[0]])
        user = User.objects.create_user(username='ag_none', password='p', organization=self.org, role='VET')
        UserRole.objects.get_or_create(user=user, role=role)
        UserRole.objects.filter(user=user).exclude(role=role).delete()
        self.assertEqual(_client(user).get(URL).status_code, 403)

    def test_anonymous_is_rejected(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_it_is_read_only(self):
        client = _client(self.vet)
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(client, method)(URL, {}, format='json').status_code, 405, method)
