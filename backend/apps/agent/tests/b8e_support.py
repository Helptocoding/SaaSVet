"""B8E uses real B6 definition, B7B emission/consent and B8A entry."""
from contextlib import contextmanager
from unittest.mock import patch
from django.test import override_settings
from apps.agent import durable, goals, matter_binding, operation_execution as execution
from apps.patients.models import Pet, PetRegistrationEffect
from .b8b_support import AppointmentExecutionFixtures


@contextmanager
def enabled_registration():
    from .b9d_support import approved_test_release
    with approved_test_release(), patch('apps.agent.intake.write_is_contained', return_value=False), override_settings(
            AGENT_B7B_CONSENT_ENABLED=True, AGENT_OPERATION_EXECUTION_ENABLED={'REGISTER_PET': True}):
        yield


class RegistrationFixtures(AppointmentExecutionFixtures):
    capability = 'register_pet_only'

    def setUp(self):
        super().setUp()
        self.goal.name = goals.ADD_PET_ONLY
        self.goal.save(update_fields=['name'])
        self.change({'owner': self.owner.pk, 'pet': None, 'appointment': None})
        self.pet_data(name='Nala')
        self.initial_pets = Pet.all_objects.count()
        self.non_agent_pet_ids = set(Pet.all_objects.values_list('pk', flat=True))

    def pet_data(self, source_type='USER_EXPLICIT', **values):
        if source_type in ('USER_EXPLICIT', 'USER_CORRECTION'):
            return matter_binding.change(self.goal, self.conv,
                {'pet_' + key: value for key, value in values.items()},
                context=self.ctx, message_id=self.ctx.anchor.message_id,
                expected_revision=self.goal.binding_revision,
                correction=source_type == 'USER_CORRECTION')
        for field, value in values.items():
            matter_binding.record_derived(self.goal, self.conv, 'pet_' + field, value,
                context=self.ctx, message_id=self.ctx.anchor.message_id,
                expected_snapshot=matter_binding.snapshot(self.goal), source_type=source_type)

    def prepare(self, **kwargs):
        return super().prepare(capability=self.capability, **kwargs)

    def authorized(self):
        self.proposal()
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        return self.op

    def run_registration(self):
        with enabled_registration():
            return self.execute()

    def assert_no_effect(self, result):
        self.assertNotEqual(result.status, 'SUCCEEDED', result)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets)
        self.assertFalse(PetRegistrationEffect.objects.exists())

    def created_pet(self):
        return PetRegistrationEffect.objects.get(operation_id=self.op.operation_key).pet

    def human_registration(self, **values):
        from apps.users.models import User
        from apps.patients.views import PetViewSet
        from rest_framework.test import APIRequestFactory, force_authenticate
        human, _ = User.objects.get_or_create(organization=self.org, username='b8e-human',
            defaults={'role': 'ADMIN', 'is_staff': True})
        request = APIRequestFactory().post('/api/pets/', {'name': 'Nala',
            'owner_public_id': str(self.owner.public_id), **values}, format='json')
        force_authenticate(request, user=human)
        response = PetViewSet.as_view({'post': 'create'}, basename='patient')(request)
        self.assertEqual(response.status_code, 201, response.data)
        pet = Pet.objects.get(public_id=response.data['public_id'])
        self.human_pet_ids = {*getattr(self, 'human_pet_ids', set()), pet.pk}
        self.non_agent_pet_ids.add(pet.pk)
        return pet
