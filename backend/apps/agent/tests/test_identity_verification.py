"""F4 — FLUJO-C: verificación humana de identidad (ADR p57 §5.5).

Es la **única** ruta por la que un contacto no verificado puede terminar
operando sobre un `Owner` existente, y toda ella pasa por una persona.

Lo que se ancla:

  · **Verificar no autoriza.** Registrar el juicio no toca `ContactIdentity`,
    no toca el `Owner` y no resuelve el caso.
  · **Autorizar exige evidencia del MISMO caso y candidato.** Una aprobación
    de otro candidato, de otro hand-off o seguida de un rechazo no habilita
    nada (frescura acotada por el caso, no por reloj).
  · **Liberar no autoriza.** El release restaura la intención vencida; el
    contacto sigue sin vincular.
  · **Todo tenant-scoped**: cross-tenant es 404, sin auditoría ni vínculo.
  · **Append-only**: el registro no admite PATCH ni DELETE.
  · RBAC propio: `agentinbox.identity_verify`, no `agentinbox.config`.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import identity, services
from apps.agent.models import (
    ContactIdentity, ContactIdentityVerification, Conversation, HumanHandoff,
)
from apps.channels.models import ChannelAccount
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User

APPROVED = ContactIdentityVerification.DECISION_APPROVED
REJECTED = ContactIdentityVerification.DECISION_REJECTED
IN_PERSON = ContactIdentityVerification.EVIDENCE_IN_PERSON


def _role_with(org, name, codes):
    role, _ = Role.objects.get_or_create(
        name=name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        w, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([w])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes])
    return role


class IdentityCaseBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="F4 Org", timezone="UTC")
        self.admin = User.objects.create_user(
            username="f4_admin", password="p", organization=self.org, role="ADMIN")
        UserRole.objects.get_or_create(
            user=self.admin, role=_role_with(self.org, "ADMIN", ["*.*"]))
        # ASSISTANT: atiende la bandeja pero NO verifica identidad.
        self.assistant = User.objects.create_user(
            username="f4_asst", password="p", organization=self.org, role="ASSISTANT")
        UserRole.objects.get_or_create(
            user=self.assistant,
            role=_role_with(self.org, "ASSISTANT", PERMISSIONS["ASSISTANT"]))

        self.owner = Owner.objects.create(
            organization=self.org, name="Ana Soto", phone="5512345678")
        self.other_owner = Owner.objects.create(
            organization=self.org, name="Beto Ruiz", phone="5599998888")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770400770")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215512345678",
            verification_level=ContactIdentity.VERIFICATION_UNKNOWN)
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state=Conversation.STATE_HANDOFF_PENDING)
        self.case = self._open_case()

        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.verify_url = (
            f'/api/inbox/conversations/{self.conv.public_id}/verify-identity/')
        self.authorize_url = (
            f'/api/inbox/conversations/{self.conv.public_id}/authorize-identity/')

    def _open_case(self, detail='owner_exists'):
        return HumanHandoff.objects.create(
            organization=self.org, conversation=self.conv,
            reason_code=HumanHandoff.REASON_IDENTITY,
            reason_detail=detail, priority='normal')

    def _verify(self, *, owner=None, decision=APPROVED, client=None):
        return (client or self.client).post(self.verify_url, {
            'owner_public_id': str((owner or self.owner).public_id),
            'decision': decision,
            'evidence_kind': IN_PERSON,
            'evidence_note': 'vino a mostrador con identificación',
        }, format='json')

    def _authorize(self, *, owner=None, client=None):
        return (client or self.client).post(self.authorize_url, {
            'owner_public_id': str((owner or self.owner).public_id),
        }, format='json')


class VerifyDoesNotAuthorizeTests(IdentityCaseBase):
    """Paso 3: registrar el juicio NO ejecuta la consecuencia."""

    def test_recording_a_verification_writes_nothing_else(self):
        resp = self._verify()
        self.assertEqual(resp.status_code, 201, resp.data)

        record = ContactIdentityVerification.objects.get()
        self.assertEqual(record.decision, APPROVED)
        self.assertEqual(record.actor_id, self.admin.pk)      # server-side
        self.assertEqual(record.handoff_id, self.case.pk)     # atado al caso
        self.assertEqual(record.organization_id, self.org.pk)

        # NADA más se movió: ni el vínculo, ni el nivel, ni el caso.
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_UNKNOWN)
        self.case.refresh_from_db()
        self.assertIsNone(self.case.resolved_at)

    def test_a_rejection_is_recordable(self):
        """`ContactIdentity` no puede representar un rechazo; este modelo sí."""
        resp = self._verify(decision=REJECTED)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(ContactIdentityVerification.objects.get().decision,
                         REJECTED)

    def test_evidence_kinds_are_exactly_the_four_approved(self):
        """El enum es el de §5.5.3, ni uno más.

        Lo que ninguna opción puede ser es una comprobación sobre el **número
        que escribe** —el wa_id—: ese ya se sabe que coincide, es lo que creó el
        caso, y usarlo como prueba sería circular. `callback` no es esa: es
        llamar al teléfono **del expediente** y que conteste el titular.

        El test es una lista blanca a propósito. Una opción nueva tipo
        «coincide el número» o «código por SMS» tiene que romper esto y pasar
        por una decisión, no colarse como un `choices` más.
        """
        self.assertEqual(
            {k for k, _label in ContactIdentityVerification.EVIDENCE_CHOICES},
            {'in_person_id', 'known_record', 'callback', 'other'},
        )

    def test_an_invalid_decision_is_rejected(self):
        resp = self.client.post(self.verify_url, {
            'owner_public_id': str(self.owner.public_id),
            'decision': 'maybe', 'evidence_kind': IN_PERSON,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(ContactIdentityVerification.objects.exists())

    def test_verification_without_an_open_case_is_refused(self):
        self.case.resolved_at = timezone.now()
        self.case.save(update_fields=['resolved_at'])
        resp = self._verify()
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'no_identity_case')
        self.assertFalse(ContactIdentityVerification.objects.exists())


class AuthorizeTests(IdentityCaseBase):
    """Paso 4: vincular exige evidencia del mismo caso y candidato."""

    def test_authorize_after_approval_links_as_staff_verified(self):
        self._verify()
        resp = self._authorize()
        self.assertEqual(resp.status_code, 200, resp.data)

        self.contact.refresh_from_db()
        self.assertEqual(self.contact.owner_id, self.owner.pk)
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_STAFF)
        self.assertEqual(self.contact.linked_via, ContactIdentity.LINKED_STAFF)
        self.assertIsNotNone(self.contact.verified_at)
        # Autorizar cierra el trabajo: el caso queda resuelto.
        self.case.refresh_from_db()
        self.assertIsNotNone(self.case.resolved_at)
        self.assertEqual(self.case.resolution, HumanHandoff.RESOLUTION_HANDLED)

    def test_authorize_without_any_verification_is_refused(self):
        resp = self._authorize()
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'verification_required')
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)

    def test_an_approval_for_another_candidate_does_not_authorize(self):
        """Aprobar a A no autoriza a B (§5.5.2)."""
        self._verify(owner=self.other_owner)
        resp = self._authorize(owner=self.owner)
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'verification_required')
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)

    def test_a_later_rejection_invalidates_an_earlier_approval(self):
        """La autorización lee EL ÚLTIMO registro, no cualquiera aprobado."""
        self._verify(decision=APPROVED)
        self._verify(decision=REJECTED)
        resp = self._authorize()
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'verification_required')

    def test_an_approval_from_a_closed_case_does_not_carry_over(self):
        """Frescura acotada por el CASO, no por reloj (§5.5.3)."""
        self._verify()
        # Aquel caso se cerró y se abrió otro: hay que verificar de nuevo.
        self.case.resolved_at = timezone.now()
        self.case.save(update_fields=['resolved_at'])
        self._open_case()

        resp = self._authorize()
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'verification_required')

    def test_an_already_linked_contact_is_refused(self):
        self._verify()
        identity.link_staff_verified(self.contact, self.owner)
        resp = self._authorize()
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'already_linked')

    def test_an_unknown_candidate_is_refused(self):
        self._verify()
        resp = self.client.post(
            self.authorize_url,
            {'owner_public_id': '00000000-0000-4000-8000-000000000000'},
            format='json')
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'owner_changed')
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)

    def test_a_malformed_candidate_id_is_refused_without_leaking_why(self):
        self._verify()
        resp = self.client.post(self.authorize_url,
                                {'owner_public_id': 'no-soy-un-uuid'},
                                format='json')
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'owner_changed')

    def test_a_verified_candidate_cannot_be_deleted(self):
        """PROTECT: la auditoría no se borra por borrar el expediente."""
        from django.db.models import ProtectedError

        self._verify()
        with self.assertRaises(ProtectedError):
            self.owner.delete()

    def test_authorizing_clears_the_reset_block(self):
        """La vía auditada es la ÚNICA que deshace un reset (Item 1)."""
        self.contact.auto_rematch_blocked = True
        self.contact.save(update_fields=['auto_rematch_blocked'])
        self._verify()
        self._authorize()
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.auto_rematch_blocked)
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_STAFF)


class TenantAndRbacTests(IdentityCaseBase):
    """Todo se deriva del servidor; cross-tenant es 404 sin rastro."""

    def test_assistant_cannot_verify_or_authorize(self):
        client = APIClient()
        client.force_authenticate(self.assistant)
        self.assertEqual(self._verify(client=client).status_code, 403)
        self.assertEqual(self._authorize(client=client).status_code, 403)
        self.assertFalse(ContactIdentityVerification.objects.exists())

    def test_a_foreign_candidate_is_not_resolvable(self):
        other_org = Organization.objects.create(name="Ajena", timezone="UTC")
        foreign = Owner.objects.create(
            organization=other_org, name="Ajeno", phone="5500000001")
        resp = self.client.post(self.verify_url, {
            'owner_public_id': str(foreign.public_id),
            'decision': APPROVED, 'evidence_kind': IN_PERSON,
        }, format='json')
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'owner_changed')
        self.assertFalse(ContactIdentityVerification.objects.exists())

    def test_a_foreign_conversation_is_404_without_audit(self):
        other_org = Organization.objects.create(name="Ajena2", timezone="UTC")
        other_channel = ChannelAccount.objects.create(
            organization=other_org, external_account_id="770401770")
        other_contact = ContactIdentity.objects.create(
            organization=other_org, external_id="5215500000002")
        foreign_conv = Conversation.objects.create(
            organization=other_org, channel_account=other_channel,
            contact=other_contact)

        resp = self.client.post(
            f'/api/inbox/conversations/{foreign_conv.public_id}/verify-identity/',
            {'owner_public_id': str(self.owner.public_id),
             'decision': APPROVED, 'evidence_kind': IN_PERSON},
            format='json')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(ContactIdentityVerification.objects.exists())

    def test_the_actor_cannot_be_spoofed_from_the_body(self):
        resp = self.client.post(self.verify_url, {
            'owner_public_id': str(self.owner.public_id),
            'decision': APPROVED, 'evidence_kind': IN_PERSON,
            'actor': self.assistant.pk,          # se ignora
            'organization': 999,                 # se ignora
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        record = ContactIdentityVerification.objects.get()
        self.assertEqual(record.actor_id, self.admin.pk)
        self.assertEqual(record.organization_id, self.org.pk)

    def test_the_model_rejects_cross_tenant_fks(self):
        """El invariante se valida en el MODELO, no solo en la vista."""
        from django.core.exceptions import ValidationError

        other_org = Organization.objects.create(name="Ajena3", timezone="UTC")
        foreign = Owner.objects.create(
            organization=other_org, name="Ajeno", phone="5500000003")
        record = ContactIdentityVerification(
            organization=self.org, contact=self.contact,
            owner_candidate=foreign, conversation=self.conv,
            handoff=self.case, decision=APPROVED,
            evidence_kind=IN_PERSON, actor=self.admin)
        with self.assertRaises(ValidationError):
            record.save()


class AppendOnlyTests(IdentityCaseBase):
    """Como el resto de la auditoría: se corrige registrando, no borrando."""

    def test_no_patch_or_delete_route_exists(self):
        self._verify()
        record = ContactIdentityVerification.objects.get()
        # No hay endpoint de mutación: la corrección es otro registro.
        self._verify(decision=REJECTED)
        self.assertEqual(ContactIdentityVerification.objects.count(), 2)
        record.refresh_from_db()
        self.assertEqual(record.decision, APPROVED)   # el original, intacto


class ReleaseDoesNotAuthorizeTests(IdentityCaseBase):
    """§5.5.5: liberar sin verificar no vincula nada."""

    def test_releasing_restores_the_intent_but_leaves_the_contact_unlinked(self):
        self.conv.flow['suspended'] = {
            'kind': 'pending_action',
            'state': {'tool': 'register_new_client_and_pet',
                      'args': {'owner_name': 'Ana', 'owner_phone': '5512345678'},
                      'paraphrase': '¿Te registro?'},
            'suspension_id': 'susp-f4',
            'suspended_at': timezone.now().isoformat(),
            'handoff_reason': 'identity',
        }
        self.conv.save(update_fields=['flow'])

        result = services.release_conversation(self.conv, self.admin)
        self.assertEqual(result['verdict'], services.RELEASE_RESTORE)

        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_UNKNOWN)


class InboxCasePayloadTests(IdentityCaseBase):
    """La bandeja ve el caso y qué pidió el cliente, sin leer el transcript."""

    def test_the_case_is_exposed_with_what_the_client_asked_for(self):
        self.conv.flow['suspended'] = {
            'kind': 'pending_action',
            'state': {'tool': 'register_new_client_and_pet',
                      'args': {'owner_name': 'Ana Soto', 'pet_name': 'Luna',
                               'pet_species': 'canino', 'date': '2026-09-01',
                               'start_time': '10:00'},
                      'paraphrase': '¿Te registro?'},
            'suspension_id': 'susp-f4',
            'suspended_at': timezone.now().isoformat(),
            'handoff_reason': 'identity',
        }
        self.conv.save(update_fields=['flow'])

        resp = self.client.get(
            f'/api/inbox/conversations/{self.conv.public_id}/messages/')
        self.assertEqual(resp.status_code, 200, resp.data)
        case = resp.data['identity_case']
        self.assertEqual(case['kind'], 'owner_exists')
        self.assertEqual(case['requested']['pet_name'], 'Luna')
        self.assertIsNone(case['last_verification'])

    def test_the_last_verification_says_whether_it_applies_here(self):
        self._verify()
        resp = self.client.get(
            f'/api/inbox/conversations/{self.conv.public_id}/messages/')
        last = resp.data['identity_case']['last_verification']
        self.assertEqual(last['decision'], APPROVED)
        self.assertTrue(last['applies_to_this_case'])
        # La nota es PII operativa: no viaja en la proyección del caso.
        self.assertNotIn('evidence_note', last)

    def test_conversations_without_a_case_expose_none(self):
        self.case.resolved_at = timezone.now()
        self.case.save(update_fields=['resolved_at'])
        resp = self.client.get(
            f'/api/inbox/conversations/{self.conv.public_id}/messages/')
        self.assertIsNone(resp.data['identity_case'])
