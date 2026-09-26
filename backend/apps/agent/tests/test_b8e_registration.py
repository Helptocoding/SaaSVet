"""PET functional, B8A guards and evidence tests against real PostgreSQL."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import connection, transaction, DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.agent import operation_execution as execution, durable, operations
from apps.agent.models import ConversationGoal, ContactIdentity, HumanHandoff
from apps.channels.models import Message
from apps.patients.models import Pet, Owner, PetRegistrationEffect
from .b8e_support import RegistrationFixtures, enabled_registration


def guard_case(scenario):
    def test(self):
        if scenario == 'pending':
            self.op = self.prepare()
            self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        elif scenario == 'rejected':
            self.proposal()
            self.response('No', reply_to=self.msg.external_message_id)
            self.assertEqual(self.evaluate().decision, 'REJECT')
            self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        else:
            self.authorized()
        if scenario == 'missing_evidence': self.tamper(authorization_message_id=self.op.source_message_id)
        if scenario == 'digest': self.tamper(parameters_digest='0'*64)
        if scenario == 'proposal_not_emitted': Message.objects.filter(pk=self.msg.pk).update(status='uncertain', uncertain_at=timezone.now())
        if scenario == 'not_causal': self.tamper(authorized_at=self.op.created_at, consent_decided_at=self.op.created_at)
        if scenario == 'binding': ConversationGoal.objects.filter(pk=self.goal.pk).update(binding_revision=self.goal.binding_revision+1)
        if scenario == 'identity':
            contact = self.conv.contact
            contact.verified_at = timezone.now()
            contact.save()
        if scenario == 'ownership': self.tamper(ownership_epoch=self.op.ownership_epoch+1)
        if scenario == 'correction': self.inbound('Perdón, es macho')
        if scenario == 'takeover': self.takeover()
        if scenario == 'handoff': HumanHandoff.objects.create(organization=self.org, conversation=self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        if scenario == 'revocation':
            contact = self.conv.contact
            contact.owner = None
            contact.verification_level = 'unknown'
            contact.verified_at = None
            contact.save()
        if scenario == 'owner_inactive': Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False)
        if scenario == 'contact_owner':
            other = Owner.objects.create(organization=self.org, name='Other')
            ContactIdentity.objects.filter(pk=self.conv.contact_id).update(owner=other)
        if scenario == 'owner_tenant':
            from apps.organizations.models import Organization
            other = Organization.objects.create(name='Other')
            Owner.all_objects.filter(pk=self.owner.pk).update(organization=other)
            self.initial_pets = Pet.all_objects.count()  # Organization seeds its generic Pet.
            self.non_agent_pet_ids = set(Pet.all_objects.values_list('pk', flat=True))
        if scenario == 'owner_snapshot': Owner.objects.filter(pk=self.owner.pk).update(name='Changed')
        if scenario == 'tenant': self.context = replace(self.context, contact_id=self.conv.contact_id+100000)
        if scenario == 'replaced':
            old = self.op
            durable.finalize_turn(self.witness)
            self.response('Otro registro')
            self.witness = self.claim()
            self.ctx = durable.context_for_work(self.witness)
            newer = self.prepare()
            self.assertEqual(newer.replaces_id, old.pk)
            self.context = replace(self.context, witness=self.witness)
        from contextlib import ExitStack
        with enabled_registration(), ExitStack() as stack:
            if scenario == 'expired': stack.enter_context(patch.object(durable, 'db_now', return_value=self.op.expires_at+timedelta(seconds=1)))
            if scenario == 'permission':
                from apps.agent.operation_permission import ActorPermission
                stack.enter_context(patch.object(execution.operation_permission, 'actor_permission',
                    return_value=ActorPermission('FORBIDDEN', 'revoked', {})))
            if scenario == 'safety': stack.enter_context(patch('apps.agent.safety_handoff.pending_signal', return_value=True))
            if scenario == 'contextual': stack.enter_context(patch.object(execution, 'authorization_mode_enabled', return_value=False))
            if scenario == 'b0': stack.enter_context(patch('apps.agent.intake.write_is_contained', return_value=True))
            if scenario == 'flag': stack.enter_context(override_settings(AGENT_OPERATION_EXECUTION_ENABLED={}))
            if scenario == 'consent_gate': stack.enter_context(override_settings(AGENT_B7B_CONSENT_ENABLED=False))
            if scenario in ('adapter_missing', 'kind_disabled'):
                registry = dict(execution.REGISTRY)
                registry['REGISTER_PET'] = execution.Registration(self.capability,
                    scenario != 'kind_disabled', None if scenario == 'adapter_missing' else registry['REGISTER_PET'].adapter)
                stack.enter_context(patch.object(execution, 'REGISTRY', registry))
            result = self.execute()
        self.assert_no_effect(result)
        return result
    return test


GUARDS = ('pending', 'rejected', 'missing_evidence', 'digest', 'proposal_not_emitted',
    'not_causal', 'binding', 'identity', 'ownership', 'correction', 'takeover', 'handoff',
    'revocation', 'owner_inactive', 'contact_owner', 'owner_tenant', 'owner_snapshot',
    'tenant', 'replaced', 'expired', 'permission', 'safety', 'contextual', 'b0', 'flag',
    'consent_gate', 'adapter_missing', 'kind_disabled')


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8ERegistrationTests(RegistrationFixtures, TestCase):
    def test_pet_01_authorized_exact_owner_tenant_and_definition(self):
        self.pet_data(species='felino', birth_date='2020-01-02')
        self.authorized()
        result = self.run_registration()
        self.assertEqual(result.status, 'SUCCEEDED', result)
        pet = self.created_pet()
        self.assertEqual((pet.owner_id, pet.organization_id, pet.name, pet.species,
            pet.birth_date.isoformat()), (self.owner.pk, self.org.pk, 'Nala', 'felino', '2020-01-02'))
        self.assertEqual(result.evidence.domain_object_id, str(pet.public_id))
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def test_pet_29_30_defaults_and_unknowns(self):
        self.authorized()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        pet = self.created_pet()
        self.assertEqual((pet.species, pet.birth_date, pet.sex, pet.breed, pet.color,
            pet.legacy_id, pet.extra_data, pet.is_generic), ('', None, 'unknown', '', '', '', [], False))

    def test_pet_26_27_28_no_implicit_entities(self):
        from apps.appointments.models import Appointment
        from apps.medical_records.models import MedicalRecord, VaccineRecord
        from apps.billing.models import Invoice
        models = (Owner, Appointment, MedicalRecord, VaccineRecord, Invoice)
        before = [list(m.all_objects.values()) for m in models]
        self.authorized()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        self.assertEqual(before, [list(m.all_objects.values()) for m in models])

    def test_visible_proposal(self):
        self.authorized()
        for text in (self.owner.name, 'Nala', 'pendiente', 'desconocido', 'raza y color'):
            self.assertIn(text, self.msg.body)

    def test_pet_07_required_name_missing(self):
        self.pet_data(name='')
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(PetRegistrationEffect.objects.exists())

    def test_pet_08_inferred_source_not_authorized(self):
        for source in ('DERIVED', 'SYSTEM_DEFAULT', 'TOOL_RESULT'):
            self.pet_data(source_type=source, species='felino')
            with self.assertRaisesMessage(operations.PreparationDenied, 'explicit_pet_data_required'):
                self.prepare()

    def test_noncanonical_human_name_rejected(self):
        self.pet_data(name='<script>')
        with self.assertRaisesMessage(operations.PreparationDenied, 'invalid_pet_data'): self.prepare()

    def test_future_birth_date_rejected(self):
        self.pet_data(birth_date='2099-01-01')
        with self.assertRaisesMessage(operations.PreparationDenied, 'invalid_pet_data'): self.prepare()

    def test_ambiguous_clinical_values_are_not_canonical(self):
        for values in ({'species': 'parece felino'}, {'birth_date': 'unos dos años'}):
            self.pet_data(species='felino', birth_date=None)
            self.pet_data(**values)
            with self.assertRaises(ValueError): self.prepare()

    def test_legacy_schema_cannot_publish_or_execute(self):
        from apps.agent.operation_proposals import has_proposal_snapshot
        from apps.agent.operation_schema import digest
        from apps.agent.pet_execution import RegisterPetAdapter
        self.op = self.prepare()
        self.op.preconditions = {'schema': 1, 'clinic_timezone': self.org.timezone, 'labels': {}}
        self.tamper(preconditions=self.op.preconditions, parameters_digest=digest(
            'REGISTER_PET', self.op.parameters, bindings=operations.digest_bindings(self.op)))
        self.assertFalse(has_proposal_snapshot(self.op))
        self.assertFalse(RegisterPetAdapter().validate_preconditions(self.op, None).allowed)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets)

    def test_contextual_mode_is_not_supported_for_registration(self):
        from apps.agent.operation_proposals import authorization_mode_enabled
        self.authorized()
        self.tamper(authorization_mode='CONTEXTUAL_DECLARATION')
        self.assertFalse(authorization_mode_enabled(self.op))
        self.assert_no_effect(self.run_registration())

    def test_explicit_optional_corrections_retire_prior_consent(self):
        self.pet_data(species='felino', birth_date='2020-01-02')
        self.proposal()
        old = self.op
        self.response('Perdón, es canino y nació el 3 de enero de 2021')
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.pet_data(source_type='USER_CORRECTION', species='canino', birth_date='2021-01-03')
        new = self.prepare()
        old.refresh_from_db()
        self.assertEqual(old.consent_state, 'INVALIDATED')
        self.assertEqual(old.parameters['species'], 'felino')
        self.assertEqual(new.parameters['birth_date'], '2021-01-03')
        self.assertEqual(new.parameters['species'], 'canino')
        self.assertEqual(new.consent_state, 'PENDING')

    def test_owner_change_invalidates_explicit_pet_fields(self):
        from apps.agent.matter_binding import values
        self.pet_data(species='felino')
        self.change({'owner': None})
        self.assertNotIn('pet_name', values(self.goal))
        self.assertNotIn('pet_species', values(self.goal))

    def test_no_owner_creation_when_missing(self):
        self.change({'owner': None})
        count = Owner.all_objects.count()
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(Owner.all_objects.count(), count)

    def test_pet_08_extra_fields_fail_closed(self):
        from apps.agent.operation_schema import canonicalize, InvalidParameters
        for field in ('sex', 'breed', 'color', 'weight', 'microchip', 'vaccines', 'legacy_id'):
            with self.assertRaises(InvalidParameters):
                canonicalize('REGISTER_PET', {'owner_id': self.owner.pk, 'name': 'Nala', field: 'inferred'})

    def test_pet_12_retry_after_human_changes(self):
        self.authorized()
        first = self.run_registration()
        self.assertEqual(first.status, 'SUCCEEDED', first)
        pet = self.created_pet()
        pet.name, pet.sex, pet.species = 'Sol', 'male', 'canino'
        pet.save()
        second = self.run_registration()
        self.assertEqual(second.evidence, first.evidence)
        self.assertTrue(second.duplicate)
        pet.refresh_from_db()
        self.assertEqual((pet.name, pet.sex, pet.species), ('Sol', 'male', 'canino'))
        self.assertEqual(PetRegistrationEffect.objects.count(), 1)

    def test_pet_14_human_equivalent_never_claimed(self):
        self.authorized()
        human = self.human_registration()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        self.assertNotEqual(self.created_pet().pk, human.pk)
        self.assertFalse(PetRegistrationEffect.objects.filter(pet=human).exists())
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+2)

    def test_pet_16_17_other_owner_and_tenant_never_reused(self):
        from apps.organizations.models import Organization
        for org in (self.org, Organization.objects.create(name='Other')):
            owner = Owner.objects.create(organization=org, name='Other')
            Pet.objects.create(organization=org, owner=owner, name='Nala')
        before = Pet.all_objects.count()
        self.non_agent_pet_ids = set(Pet.all_objects.values_list('pk', flat=True))
        self.authorized()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        self.assertEqual(self.created_pet().owner_id, self.owner.pk)
        self.assertEqual(Pet.all_objects.count(), before+1)

    def test_pet_18_contradictory_provenance(self):
        self.authorized()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('ALTER TABLE patients_petregistrationeffect DISABLE TRIGGER pet_registration_evidence_guard')
            try: cursor.execute("UPDATE patients_petregistrationeffect SET parameters_digest=%s", ['0'*64])
            finally: cursor.execute('ALTER TABLE patients_petregistrationeffect ENABLE TRIGGER pet_registration_evidence_guard')
        self.assertEqual(self.run_registration().status, 'UNCERTAIN')
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def test_sql_evidence_failure_rolls_back_insert_without_blind_retry(self):
        self.authorized()
        def fail(*args, **kwargs):
            with connection.cursor() as cursor: cursor.execute('SELECT 1 / 0')
        with patch.object(PetRegistrationEffect, 'save', fail):
            self.assert_no_effect(self.run_registration())
        self.assertEqual(self.run_registration().status, 'UNCERTAIN')
        self.assertEqual(Pet.all_objects.count(), self.initial_pets)

    def test_evidence_immutable_and_unique_at_database(self):
        self.authorized()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        with self.assertRaises(DatabaseError), transaction.atomic():
            PetRegistrationEffect.objects.update(parameters_digest='0'*64)
        with self.assertRaises(DatabaseError), transaction.atomic():
            PetRegistrationEffect.objects.all().delete()
        effect = PetRegistrationEffect.objects.get()
        effect.pk = None
        with self.assertRaises(DatabaseError), transaction.atomic(): effect.save(force_insert=True)

    def test_evidence_insert_rejects_wrong_tenant_owner_digest_definition(self):
        from apps.agent.pet_execution import definition_for
        from apps.organizations.models import Organization
        from uuid import uuid4
        self.authorized()
        other_org = Organization.objects.create(name='Other provenance tenant')
        other_owner = Owner.objects.create(organization=self.org, name='Other provenance owner')
        baseline = Pet.all_objects.count()
        original = definition_for(self.op)
        for changes in ({'parameters_digest': '0'*64}, {'organization_id': other_org.pk},
                {'owner_id': other_owner.pk}, {'definition': {**original, 'sex': 'female'}},
                {'operation_id': uuid4()}):
            with self.subTest(changes=tuple(changes)), self.assertRaises(DatabaseError), transaction.atomic():
                pet = Pet.objects.create(organization=self.org, owner=self.owner, name='Nala')
                values = {'operation_id': self.op.operation_key, 'organization_id': self.org.pk,
                    'owner_id': self.owner.pk, 'pet': pet, 'parameters_digest': self.op.parameters_digest,
                    'definition': original, 'committed_at': durable.db_now(), **changes}
                PetRegistrationEffect.objects.create(**values)
        self.assertEqual(Pet.all_objects.count(), baseline)
        self.assertFalse(PetRegistrationEffect.objects.exists())

    def test_correction_requires_new_definition_and_consent(self):
        self.proposal()
        old = self.op
        self.response('Perdón, se llama Sol')
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.pet_data(source_type='USER_CORRECTION', name='Sol')
        new = self.prepare()
        old.refresh_from_db()
        self.assertEqual(old.parameters['name'], 'Nala')
        self.assertEqual(old.consent_state, 'INVALIDATED')
        self.assertEqual(new.replaces_id, old.pk)
        self.assertEqual(new.parameters['name'], 'Sol')
        self.assertEqual(new.consent_state, 'PENDING')

    def test_inspector_history_and_current(self):
        from apps.agent.admin import ConversationOperationAdmin
        from apps.agent.models import ConversationOperation
        from django.contrib.admin.sites import AdminSite
        self.authorized()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        Pet.objects.filter(pk=self.created_pet().pk).update(name='Sol')
        inspector = ConversationOperationAdmin(ConversationOperation, AdminSite())
        data = inspector.pet_effect(self.op)
        self.assertEqual(data['historical_creation']['definition']['name'], 'Nala')
        self.assertEqual(data['current_pet']['name'], 'Sol')
        self.assertTrue(data['digest_match'])
        self.assertFalse(inspector.has_change_permission(None, self.op))

    def test_reconciliation_recomputes_definition_digest(self):
        from apps.agent.pet_execution import RegisterPetAdapter
        from apps.agent.admin import ConversationOperationAdmin
        from apps.agent.models import ConversationOperation
        from django.contrib.admin.sites import AdminSite
        self.authorized()
        self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        changed_zone = 'UTC' if self.op.preconditions['clinic_timezone'] != 'UTC' else 'America/Mexico_City'
        self.tamper(preconditions={**self.op.preconditions, 'clinic_timezone': changed_zone})
        self.assertEqual(RegisterPetAdapter().reconcile(self.op, None).status, 'UNCERTAIN')
        inspector = ConversationOperationAdmin(ConversationOperation, AdminSite())
        self.assertFalse(inspector.pet_effect(self.op)['digest_match'])
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def test_agent_human_endpoint_denied(self):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.patients.views import PetViewSet
        from apps.users.models import User
        user = User.objects.create(organization=self.org, username='b8e-agent', role='AGENT')
        request = APIRequestFactory().post('/api/pets/', {'name': 'Nala',
            'owner_public_id': str(self.owner.public_id)}, format='json')
        force_authenticate(request, user=user)
        response = PetViewSet.as_view({'post': 'create'}, basename='patient')(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets)

    def test_events_closed_and_without_pii_labels(self):
        from apps.agent.pet_execution import observe
        with self.assertRaises(ValueError): observe('Nala')
        self.authorized()
        with self.assertLogs('agent.events', level='INFO') as logs, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.run_registration().status, 'SUCCEEDED')
        rows = [r for r in logs.records if r.msg.startswith('AGENT_B8E_')]
        self.assertTrue(rows)
        for row in rows:
            for key in ('phone', 'owner_id', 'pet_id', 'operation_key', 'name', 'breed'):
                if key != 'name': self.assertNotIn(key, row.__dict__)


for scenario in GUARDS:
    setattr(B8ERegistrationTests, 'test_guard_' + scenario, guard_case(scenario))
