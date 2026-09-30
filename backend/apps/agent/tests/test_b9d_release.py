"""B9D component gates only: synthetic evidence never approves PROFILE-BETA-1."""
import io
import json
from dataclasses import replace, FrozenInstanceError
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection, transaction, DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.agent import beta_release as beta, operation_execution as execution
from apps.agent.models import AgentSettings, ConversationOperation, ToolExecution
from apps.organizations.models import Organization
from apps.appointments.models import Appointment, AppointmentMutationEffect
from apps.patients.models import PetRegistrationEffect
from . import b8b_support as create, b8c_support as mutations, b8d_support as attendance, b8e_support as pets
from .b9d_support import release_for, approval, TEST_DATE, TEST_ENVIRONMENT, CAPABILITIES


class ReleaseEvidenceTests(SimpleTestCase):
    def setUp(self):
        self.release = release_for(1)
        self.environment = patch.object(beta, 'EVIDENCE_ENVIRONMENT', TEST_ENVIRONMENT)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def evaluate(self, grant=None, release=None):
        return beta.evaluate(1, release=release or replace(self.release,
            organizations=(grant or self.release.organizations[0],)))

    def test_complete_synthetic_evidence_is_explicitly_test_only(self):
        snapshot = self.evaluate()
        self.assertEqual(snapshot['status'], 'READY')
        self.assertEqual(snapshot['evidence_environment'], 'TEST_EVIDENCE')
        self.assertEqual(snapshot['capabilities'], CAPABILITIES)

    def test_test_evidence_never_certifies_real_operational_readiness(self):
        with patch.object(beta, 'EVIDENCE_ENVIRONMENT', 'REAL_OPERATIONAL_EVIDENCE'):
            snapshot = self.evaluate()
        self.assertNotEqual(snapshot['status'], 'READY')
        self.assertEqual(snapshot['capabilities'], ())

    def test_production_default_is_empty_and_closed(self):
        snapshot = beta.evaluate(1)
        self.assertEqual(beta.APPROVED_RELEASE.organizations, ())
        self.assertEqual(snapshot['status'], 'PENDING_ACTIVATION_REQUIREMENTS')
        self.assertIn('profile_beta_1', snapshot['missing'])

    def test_pilot_selection_alone_does_not_approve_autonomy(self):
        grant = replace(approval(1), evidence=(approval(1).evidence[0],))
        self.assertNotEqual(self.evaluate(grant)['status'], 'READY')

    def test_other_organization_cannot_borrow_approval(self):
        self.assertIn('organization_not_approved', beta.evaluate(2, release=self.release)['missing'])
        wrong = replace(approval(1), evidence=approval(2).evidence)
        self.assertEqual(self.evaluate(wrong)['capabilities'], ())

    def test_provenance_missing_future_failed_or_skipped_is_closed(self):
        original = approval(1)
        for values in ({'authority': ''}, {'reference': ''}, {'revision': ''},
                       {'recorded_at': timezone.now() + timedelta(days=1)},
                       {'recorded_at': TEST_DATE.replace(tzinfo=None)},
                       {'outcome': 'FAIL'}, {'outcome': 'SKIPPED'}, {'failures': 1},
                       {'skipped': 1}, {'failures': False}, {'organization_id': True}):
            with self.subTest(values=values):
                grant = replace(original, evidence=(replace(original.evidence[0], **values), *original.evidence[1:]))
                self.assertNotEqual(self.evaluate(grant)['status'], 'READY')

    def test_duplicate_requirement_and_unknown_requirement_are_closed(self):
        grant = approval(1)
        for extra in (grant.evidence[0], replace(grant.evidence[0], requirement='privacy_ready')):
            self.assertIn('invalid_evidence', self.evaluate(replace(grant, evidence=(*grant.evidence, extra)))['missing'])

    def test_explicit_lists_deny_wildcards_unknown_control_and_composite(self):
        for values in (('*',), ('invented',), ('request_human',), ('register_pet_and_schedule',),
                       ('get_clinic_info', 'get_clinic_info'), ['get_clinic_info']):
            with self.subTest(values=values):
                self.assertIn('invalid_release', self.evaluate(release=replace(self.release, capabilities=values))['missing'])

    def test_org_cannot_expand_release_or_omit_capability_scope(self):
        for grant in (replace(approval(1), capabilities=()), approval(1)):
            snapshot = self.evaluate(release=replace(self.release, capabilities=('get_clinic_info',), organizations=(grant,)))
            self.assertEqual(snapshot['capabilities'], ())

    def test_read_only_release_does_not_approve_write(self):
        release = release_for(1, capabilities=('get_clinic_info', 'list_my_pets'))
        with patch.object(beta, 'APPROVED_RELEASE', release):
            self.assertEqual(beta.write_gate(SimpleNamespace(organization_id=1,
                operation_kind='CREATE_APPOINTMENT', created_at=timezone.now())), 'beta_capability_not_approved')

    def test_duplicate_tenant_and_invalid_candidate_are_closed(self):
        self.assertIn('invalid_release', self.evaluate(release=replace(self.release,
            organizations=(approval(1), approval(1))))['missing'])
        for changes in ({'candidate_commit': ''}, {'minimum_compatible_version': ''}, {'candidate_commit': 'x' * 40}):
            self.assertIn('candidate_artifact', self.evaluate(release=replace(self.release, **changes))['missing'])

    def test_reapproval_rejects_old_operation_without_new_revision(self):
        operation = SimpleNamespace(organization_id=1, operation_kind='CREATE_APPOINTMENT', created_at=timezone.now())
        grant = approval(1, approved_at=operation.created_at + timedelta(microseconds=1))
        with patch.object(beta, 'APPROVED_RELEASE', replace(self.release, organizations=(grant,))):
            self.assertEqual(beta.write_gate(operation), 'beta_operation_predates_approval')

    def test_immutable_release_and_no_agent_self_certification_capability(self):
        from apps.agent.capabilities import EFFECTS
        with self.assertRaises(FrozenInstanceError):
            self.release.organizations = (approval(2),)
        self.assertFalse(any('readiness' in name or 'activate' in name or 'approve' in name for name in EFFECTS))
        self.assertFalse(hasattr(beta, 'activate'))

    def test_reapproval_date_requires_matching_human_approval_evidence(self):
        grant = replace(approval(1), approved_at=timezone.now())
        self.assertIn('human_approval', self.evaluate(grant)['missing'])


def missing_requirement_case(requirement):
    def test(self):
        grant = approval(1)
        grant = replace(grant, evidence=tuple(e for e in grant.evidence if e.requirement != requirement))
        result = self.evaluate(grant)
        self.assertEqual(result['missing'], (requirement,))
        self.assertEqual(result['capabilities'], ())
    return test


for _requirement in beta.OPERATIONAL_REQUIREMENTS + beta.TECHNICAL_REQUIREMENTS:
    setattr(ReleaseEvidenceTests, 'test_missing_' + _requirement, missing_requirement_case(_requirement))


class GateCases:
    kind = 'CREATE_APPOINTMENT'

    def setUp(self):
        super().setUp()
        if self.kind in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT', 'CONFIRM_ATTENDANCE'):
            self.mutation(self.kind)
        self.authorized()

    def run_gate(self, release=None):
        with override_settings(AGENT_B7B_CONSENT_ENABLED=True,
                AGENT_OPERATION_EXECUTION_ENABLED={self.kind: True}), patch(
                'apps.agent.intake.write_is_contained', return_value=False), patch.object(
                beta, 'EVIDENCE_ENVIRONMENT', TEST_ENVIRONMENT), patch.object(
                beta, 'APPROVED_RELEASE', release or beta.APPROVED_RELEASE):
            return self.execute()

    def effects(self):
        return (Appointment.all_objects.filter(source_operation_id=self.op.operation_key).count()
                + AppointmentMutationEffect.objects.filter(operation_id=self.op.operation_key).count()
                + PetRegistrationEffect.objects.filter(operation_id=self.op.operation_key).count())

    def test_unapproved_legacy_organization_blocked_even_with_other_gates_open(self):
        result = self.run_gate()
        self.assertEqual(result.reason, 'beta_requirements_pending')
        self.assertEqual(self.effects(), 0)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')

    def test_approved_exact_capability_reaches_real_adapter_once(self):
        release = release_for(self.org.pk, capabilities=(self.context.capability,))
        result = self.run_gate(release)
        self.assertEqual(result.status, 'SUCCEEDED', result)
        self.assertEqual(self.effects(), 1)
        self.assertEqual(self.run_gate(release).status, 'SUCCEEDED')
        self.assertEqual(self.effects(), 1)

    def test_other_tenant_and_read_approval_cannot_enable_write(self):
        other = Organization.objects.create(name='Other approval')
        self.assertEqual(self.run_gate(release_for(other.pk)).reason, 'beta_requirements_pending')
        self.assertEqual(self.run_gate(release_for(self.org.pk, capabilities=('get_clinic_info',))).reason,
                         'beta_capability_not_approved')
        self.assertEqual(self.effects(), 0)

    def test_withdrawal_keeps_committed_effect_reconcilable(self):
        self.assertEqual(self.run_gate(release_for(self.org.pk)).status, 'SUCCEEDED')
        self.assertEqual(self.run_gate().status, 'SUCCEEDED')
        self.assertEqual(self.effects(), 1)

    def test_requirement_loss_blocks_without_altering_budget_or_witness(self):
        from apps.agent.models import TurnWork
        before = list(TurnWork.objects.values())
        grant = approval(self.org.pk)
        missing = replace(grant, evidence=tuple(e for e in grant.evidence if e.requirement != 'validated_fallback'))
        release = replace(release_for(self.org.pk), organizations=(missing,))
        self.assertEqual(self.run_gate(release).reason, 'beta_requirements_pending')
        self.assertEqual(self.effects(), 0)
        self.assertEqual(list(TurnWork.objects.values()), before)

    def test_b0_still_precedes_beta_approval(self):
        with patch.object(beta, 'APPROVED_RELEASE', release_for(self.org.pk)):
            self.assertEqual(self.execute().reason, 'containment_closed')
        self.assertEqual(self.effects(), 0)

    def test_checked_ready_snapshot_cannot_authorize_after_withdrawal(self):
        with patch.object(beta, 'EVIDENCE_ENVIRONMENT', TEST_ENVIRONMENT):
            checked = beta.evaluate(self.org.pk, release=release_for(self.org.pk))
        self.assertEqual(checked['status'], 'READY')
        self.assertEqual(self.run_gate().reason, 'beta_requirements_pending')
        self.assertEqual(self.effects(), 0)

    def test_new_approval_does_not_revive_previously_authorized_operation(self):
        grant = approval(self.org.pk, approved_at=timezone.now())
        release = replace(release_for(self.org.pk), organizations=(grant,))
        self.assertEqual(self.run_gate(release).reason, 'beta_operation_predates_approval')
        self.assertEqual(self.effects(), 0)

    def test_sql_rollback_after_effect_preserves_existing_atomicity(self):
        before = list(ToolExecution.objects.values())
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                self.assertEqual(self.run_gate(release_for(self.org.pk)).status, 'SUCCEEDED')
                with connection.cursor() as cursor:
                    cursor.execute('SELECT b9d_deliberately_missing_sql_function()')
        self.assertEqual(self.effects(), 0)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertEqual(list(ToolExecution.objects.values()), before)


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class BetaCreateTests(GateCases, create.AppointmentExecutionFixtures, TestCase):
    pass


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class BetaRescheduleTests(GateCases, mutations.MutationFixtures, TestCase):
    kind = 'RESCHEDULE_APPOINTMENT'


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class BetaCancelTests(GateCases, mutations.MutationFixtures, TestCase):
    kind = 'CANCEL_APPOINTMENT'


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class BetaAttendanceTests(GateCases, attendance.AttendanceFixtures, TestCase):
    kind = 'CONFIRM_ATTENDANCE'


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class BetaRegistrationTests(GateCases, pets.RegistrationFixtures, TestCase):
    kind = 'REGISTER_PET'


class BetaInspectorTests(TestCase):
    def test_readonly_legacy_defaults_and_no_migration_activation(self):
        org = Organization.objects.create(name='Legacy configuration')
        AgentSettings.objects.create(organization=org, enabled=True, faq_facts={'privacy_ready': 'true'})
        before = list(AgentSettings.objects.values())
        output = io.StringIO()
        call_command('agent_inspect_beta', organization_id=org.pk, stdout=output)
        data = json.loads(output.getvalue())
        self.assertEqual(data['status'], 'PENDING_ACTIVATION_REQUIREMENTS')
        self.assertEqual(data['approved_capabilities'], [])
        self.assertTrue(data['agent_enabled'])
        self.assertEqual(before, list(AgentSettings.objects.values()))
        self.assertFalse(ConversationOperation.objects.exists())

    def test_no_settings_created_and_unknown_org_rejected(self):
        org = Organization.objects.create(name='Not configured')
        output = io.StringIO()
        call_command('agent_inspect_beta', organization_id=org.pk, stdout=output)
        self.assertFalse(AgentSettings.objects.filter(organization=org).exists())
        with self.assertRaises(CommandError):
            call_command('agent_inspect_beta', organization_id=org.pk + 999)

    def test_test_evidence_visible_and_no_pii_or_documents_in_snapshot(self):
        org = Organization.objects.create(name='Private clinic name')
        with patch.object(beta, 'EVIDENCE_ENVIRONMENT', TEST_ENVIRONMENT), patch.object(
                beta, 'APPROVED_RELEASE', release_for(org.pk)):
            output = json.dumps(beta.inspect_organization(org.pk))
        self.assertIn('TEST_EVIDENCE', output)
        self.assertNotIn(org.name, output)
        self.assertNotIn('test-fixture:', output)
        self.assertNotIn('test-authority', output)

    def test_agent_tool_arguments_cannot_self_certify(self):
        from apps.agent import tools
        org = Organization.objects.create(name='Agent cannot approve')
        for name in ('approve_beta', 'activate_organization', 'mark_readiness', 'privacy_ready'):
            result = tools.run_tool(name, {'organization_id': org.pk, 'ready': True},
                                    conversation=None, executor=None)
            self.assertEqual(result.client_error, 'unknown_tool')
        self.assertEqual(beta.evaluate(org.pk)['status'], 'PENDING_ACTIVATION_REQUIREMENTS')
        self.assertFalse(AgentSettings.objects.filter(organization=org).exists())
