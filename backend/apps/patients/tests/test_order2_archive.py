from datetime import timedelta, time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.utils import timezone
from django.test import TransactionTestCase
from django.db import close_old_connections
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.appointments.models import Appointment
from apps.appointments.creation import AppointmentCommand, CreationRejected, create_appointment
from apps.patients.archive import ArchiveBlocked, change_archive_state
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization, OrganizationStateAudit
from apps.patients.models import Owner, Pet
from apps.users.models import User


class ArchiveContractTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Archivo A')
        cls.other = Organization.objects.create(name='Archivo B')
        cls.admin = User.objects.create_user(username='archadmin', password='test',
                                              organization=cls.org, role='ADMIN')
        cls.vet = User.objects.create_user(username='archvet', password='test',
                                            organization=cls.org, role='VET')
        cls.foreign = User.objects.create_user(username='archforeign', password='test',
                                                organization=cls.other, role='ADMIN')
        cls.platform = User.objects.create_superuser(username='archplatform', password='test',
                                                      role='ADMIN_SAAS')

    def setUp(self):
        self.owner = Owner.objects.create(organization=self.org, name='Cliente')
        self.pet = Pet.objects.create(organization=self.org, owner=self.owner, name='Mascota')

    def _url(self, kind, subject, action):
        return f'/api/{kind}/{subject.public_id}/{action}/'

    def test_archive_owner_cascades_active_pets_but_restore_is_selective(self):
        self.client.force_authenticate(self.admin)
        second = Pet.objects.create(organization=self.org, owner=self.owner, name='Otra')
        url = self._url('owners', self.owner, 'archive')
        self.assertEqual(self.client.post(url).status_code, 200)
        self.owner.refresh_from_db()
        self.pet.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.assertFalse(self.pet.is_active)
        stamp = self.owner.archived_at
        self.assertEqual(self.client.post(url).status_code, 200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.archived_at, stamp)
        self.assertEqual(self.client.post(self._url('pets', self.pet, 'restore')).status_code, 409)
        self.assertEqual(self.client.post(self._url('owners', self.owner, 'restore')).status_code, 200)
        self.assertFalse(Pet.all_objects.get(pk=second.pk).is_active)
        self.assertEqual(self.client.post(self._url('pets', self.pet, 'restore')).status_code, 200)
        self.assertTrue(Pet.all_objects.get(pk=self.pet.pk).is_active)

    def test_open_record_and_past_pending_appointment_block_every_pet(self):
        other = Pet.objects.create(organization=self.org, owner=self.owner, name='Otra')
        MedicalRecord.objects.create(organization=self.org, pet=other)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(self._url('owners', self.owner, 'archive')).status_code, 409)
        self.assertTrue(Owner.all_objects.get(pk=self.owner.pk).is_active)
        self.assertTrue(Pet.all_objects.get(pk=self.pet.pk).is_active)
        self.assertTrue(Pet.all_objects.get(pk=other.pk).is_active)
        now = (timezone.now() - timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)
        Appointment.objects.create(organization=self.org, pet=self.pet,
            date=now.date(), start_time=now.time().replace(tzinfo=None),
            end_time=(now + timedelta(minutes=30)).time().replace(tzinfo=None),
            reason='Pendiente', status='scheduled')
        self.assertEqual(self.client.post(self._url('pets', self.pet, 'archive')).status_code, 409)

    def test_tenant_scope_and_admin_only(self):
        url = self._url('owners', self.owner, 'archive')
        self.client.force_authenticate(self.vet)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_authenticate(self.foreign)
        self.assertNotEqual(self.client.post(url).status_code, 200)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(f'/api/owners/{self.owner.public_id}/').status_code, 204)
        self.assertTrue(Owner.all_objects.filter(pk=self.owner.pk).exists())

    def test_disabled_org_denies_existing_access_and_refresh_then_reactivation_keeps_staff_state(self):
        self.client.force_authenticate(self.platform)
        state = f'/api/platform/organizations/{self.org.public_id}/'
        token = RefreshToken.for_user(self.admin)
        self.assertEqual(self.client.post(state + 'deactivate/', {'reason': 'Prueba aislada'}).status_code, 200)
        self.assertEqual(OrganizationStateAudit.objects.filter(organization=self.org).count(), 1)
        history = self.client.get(f'/api/platform/organizations/{self.org.public_id}/history/')
        self.assertEqual(history.status_code, 200)
        self.assertFalse(history.data['is_active'])
        self.assertEqual(history.data['organization_id'], str(self.org.public_id))
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        self.assertEqual(self.client.get('/api/me/').status_code, 401)
        self.client.credentials()
        self.assertEqual(self.client.post('/api/token/refresh/', {'refresh': str(token)}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/api/me/').status_code, 403)
        self.client.logout()
        self.vet.is_active = False
        self.vet.save(update_fields=['is_active'])
        self.client.force_authenticate(self.platform)
        self.assertEqual(self.client.post(state + 'reactivate/', {'reason': 'Prueba terminada'}).status_code, 200)
        self.vet.refresh_from_db()
        self.assertFalse(self.vet.is_active)

    def test_login_denied_for_disabled_org(self):
        self.client.force_authenticate(self.platform)
        state = f'/api/platform/organizations/{self.org.public_id}/deactivate/'
        self.assertEqual(self.client.post(state, {'reason': 'Prueba login aislado'}).status_code, 200)
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/token/', {'username': 'archadmin', 'password': 'test'})
        self.assertNotEqual(response.status_code, 200)


class ArchiveCreationRaceTests(TransactionTestCase):
    def test_archive_and_appointment_cannot_both_commit(self):
        org = Organization.objects.create(name='Carrera archivo')
        owner = Owner.objects.create(organization=org, name='Cliente carrera')
        pet = Pet.objects.create(organization=org, owner=owner, name='Mascota carrera')
        admin = User.objects.create_user(username='race_arch_admin', password='synthetic',
                                          organization=org, role='ADMIN')
        day = (timezone.now() + timedelta(days=3)).date()
        command = AppointmentCommand(org.pk, pet.pk, None, day,
                                     time(11), time(11, 30), 'Prueba de carrera')
        gate = Barrier(2)

        def archive():
            close_old_connections()
            gate.wait(timeout=15)
            try:
                change_archive_state(actor=admin, organization_id=org.pk,
                                     kind='owner', public_id=owner.public_id, archive=True)
                return 'archived'
            except ArchiveBlocked:
                return 'blocked'
            finally:
                close_old_connections()

        def create():
            close_old_connections()
            gate.wait(timeout=15)
            try:
                create_appointment(command)
                return 'created'
            except CreationRejected:
                return 'rejected'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(archive), pool.submit(create)
            results = a.result(timeout=30), b.result(timeout=30)
        self.assertIn(results, (('archived', 'rejected'), ('blocked', 'created')))
        if results[0] == 'archived':
            self.assertFalse(Appointment.objects.filter(pet_id=pet.pk).exists())
        else:
            self.assertTrue(Owner.all_objects.get(pk=owner.pk).is_active)
