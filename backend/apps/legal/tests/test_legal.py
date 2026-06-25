"""
Tests del LegalAcceptanceGate + modelos + endpoints + flujos (ADR p46).

Propiedad clave: el gate es **no-op** sin documentos `is_current` → no rompe el
resto de la suite. Aquí sí se crean documentos para ejercer el gate.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.legal.models import LegalAcceptance, LegalDocument
from apps.legal.services import (
    legal_acceptance_required,
    pending_documents,
    record_acceptances,
)
from apps.organizations.models import Organization
from apps.platform.services.provision_organization import provision_organization

User = get_user_model()

GATED_URL = '/api/staff/'   # HybridPermission (staff.list); el ADMIN tiene wildcard


def make_doc(doc_type, version='2026-06-24', current=True):
    return LegalDocument.objects.create(
        doc_type=doc_type, version=version, effective_date=date(2026, 6, 24),
        landing_url=f'https://www.saaslyvet.com/{doc_type}', is_current=current,
    )


def mk_user(org, role, username):
    return User.objects.create_user(
        username=username, email=f'{username}@c.test', password='Pass1234!',
        role=role, organization=org,
    )


class LegalModelTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org M')
        self.user = mk_user(self.org, 'ADMIN', 'mu')

    def test_acceptance_inherits_organization_from_user(self):
        doc = make_doc('privacy')
        LegalAcceptance.objects.create(user=self.user, document=doc, accepted_at=timezone.now())
        a = LegalAcceptance.objects.get(user=self.user, document=doc)
        self.assertEqual(a.organization_id, self.org.id)

    def test_record_acceptances_idempotent(self):
        doc = make_doc('privacy')
        record_acceptances(user=self.user, documents=[doc])
        record_acceptances(user=self.user, documents=[doc])  # 2da vez = no duplica
        self.assertEqual(
            LegalAcceptance.objects.filter(user=self.user, document=doc).count(), 1
        )


class LegalServiceRoleTests(APITestCase):
    """Requisito por rol: ADMIN=terms+privacy, VET/ASSISTANT=privacy."""
    def setUp(self):
        self.org = Organization.objects.create(name='Org R')
        self.admin = mk_user(self.org, 'ADMIN', 'radmin')
        self.vet = mk_user(self.org, 'VET', 'rvet')
        self.terms = make_doc('terms')
        self.privacy = make_doc('privacy')

    def test_admin_requires_both(self):
        self.assertEqual({d.doc_type for d in pending_documents(self.admin)}, {'terms', 'privacy'})
        record_acceptances(user=self.admin, documents=[self.privacy])
        self.assertEqual({d.doc_type for d in pending_documents(self.admin)}, {'terms'})  # falta terms
        self.assertTrue(legal_acceptance_required(self.admin))
        record_acceptances(user=self.admin, documents=[self.terms])
        self.assertFalse(legal_acceptance_required(self.admin))

    def test_vet_requires_only_privacy(self):
        self.assertEqual({d.doc_type for d in pending_documents(self.vet)}, {'privacy'})
        record_acceptances(user=self.vet, documents=[self.privacy])
        self.assertFalse(legal_acceptance_required(self.vet))  # terms NO le aplica


class LegalGateTests(APITestCase):
    def setUp(self):
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Org G')
        self.admin = mk_user(self.org, 'ADMIN', 'gadmin')
        self.terms = make_doc('terms')
        self.privacy = make_doc('privacy')

    def test_no_current_docs_is_noop(self):
        LegalDocument.objects.update(is_current=False)  # demo / sin docs vigentes
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(GATED_URL).status_code, status.HTTP_200_OK)

    def test_gated_when_pending(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(GATED_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_allowed_after_accept(self):
        record_acceptances(user=self.admin, documents=[self.terms, self.privacy])
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(GATED_URL).status_code, status.HTTP_200_OK)

    def test_me_and_legal_endpoints_whitelisted(self):
        self.client.force_authenticate(user=self.admin)  # pendiente
        self.assertEqual(self.client.get('/api/me/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/api/legal/current/').status_code, status.HTTP_200_OK)

    def test_superuser_exempt(self):
        op = User.objects.create_superuser(
            username='opsaas', email='ops@p.test', password='OpsPass1234!',
            role='ADMIN_SAAS', organization=self.org,
        )
        self.client.force_authenticate(user=op)
        # ADMIN_SAAS exento del gate legal (aunque haya docs pendientes).
        self.assertNotEqual(self.client.get(GATED_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_version_bump_reconsent(self):
        record_acceptances(user=self.admin, documents=[self.terms, self.privacy])
        self.assertFalse(legal_acceptance_required(self.admin))
        # Cambio material: nueva versión de privacy → demote v1, v2 is_current.
        self.privacy.is_current = False
        self.privacy.save(update_fields=['is_current'])
        make_doc('privacy', version='2026-12-01')
        self.assertTrue(legal_acceptance_required(self.admin))  # re-consent
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(GATED_URL).status_code, status.HTTP_403_FORBIDDEN)


class LegalEndpointTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org E')
        self.admin = mk_user(self.org, 'ADMIN', 'eadmin')
        self.terms = make_doc('terms')
        self.privacy = make_doc('privacy')
        self.client.force_authenticate(user=self.admin)

    def test_current_lists_required_with_accepted_flag(self):
        r = self.client.get('/api/legal/current/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['acceptance_required'])
        self.assertEqual(len(r.data['documents']), 2)
        self.assertFalse(any(d['accepted'] for d in r.data['documents']))

    def test_accept_records_and_flips_me(self):
        r = self.client.post('/api/legal/accept/', {
            'document_public_ids': [str(self.terms.public_id), str(self.privacy.public_id)],
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['acceptance_required'])
        me = self.client.get('/api/me/')
        self.assertFalse(me.data['legal_acceptance_required'])
        self.assertEqual(me.data['pending_legal_documents'], [])
        # ip/user_agent server-side
        a = LegalAcceptance.objects.get(user=self.admin, document=self.terms)
        self.assertIsNotNone(a.accepted_at)

    def test_accept_rejects_empty(self):
        r = self.client.post('/api/legal/accept/', {'document_public_ids': []}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_accept_rejects_non_current_doc(self):
        old = make_doc('privacy', version='old', current=False)
        r = self.client.post('/api/legal/accept/', {
            'document_public_ids': [str(old.public_id)],
        }, format='json')
        self.assertEqual(r.status_code, 400)


class LegalFlowTests(APITestCase):
    """E2E del flujo OWNER: provisión → login → must-change → legal → dashboard."""
    def setUp(self):
        caches['throttle_login'].clear()
        self.op_org = Organization.objects.create(name='Internal')
        self.op = User.objects.create_superuser(
            username='platops', email='ops@vc.test', password='OpsPass1234!',
            role='ADMIN_SAAS', organization=self.op_org,
        )
        make_doc('terms')
        make_doc('privacy')

    def test_owner_new_must_change_then_legal_then_dashboard(self):
        res = provision_organization(actor=self.op, validated_data={
            'name': 'Clinica Flow', 'timezone': 'America/Mexico_City', 'tax_rate': '0.1600',
            'admin_username': 'flowadmin', 'admin_email': 'fa@c.test',
            'admin_password': 'FlowPass1234!', 'admin_first_name': 'Flo', 'admin_last_name': 'Adm',
        })
        # 1. Login → must_change_password=True
        pub = APIClient()
        login = pub.post('/api/token/', {'username': 'flowadmin', 'password': 'FlowPass1234!'}, format='json')
        self.assertTrue(login.data.get('must_change_password'))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        # 2. must-change bloquea el gated endpoint
        self.assertEqual(c.get(GATED_URL).status_code, status.HTTP_403_FORBIDDEN)
        # 3. Cambia contraseña
        changed = c.post('/api/users/change-password/', {
            'current_password': 'FlowPass1234!', 'new_password': 'NewFlowPass5678!',
            'confirm_password': 'NewFlowPass5678!',
        }, format='json')
        self.assertEqual(changed.status_code, 200)
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f"Bearer {changed.data['access']}")
        # 4. Ya sin must-change, AHORA bloquea el legal gate
        me = c2.get('/api/me/')
        self.assertFalse(me.data['must_change_password'])
        self.assertTrue(me.data['legal_acceptance_required'])
        self.assertEqual(c2.get(GATED_URL).status_code, status.HTTP_403_FORBIDDEN)
        # 5. Acepta los documentos vigentes
        docs = c2.get('/api/legal/current/').data['documents']
        c2.post('/api/legal/accept/', {
            'document_public_ids': [d['public_id'] for d in docs],
        }, format='json')
        # 6. Dashboard accesible
        self.assertEqual(c2.get(GATED_URL).status_code, status.HTTP_200_OK)

    def test_existing_user_gated_when_docs_published(self):
        # Usuario que existía ANTES de publicar documentos.
        admin = mk_user(self.op_org, 'ADMIN', 'preexisting')  # nota: en op_org, rol ADMIN
        # Ya hay docs is_current (setUp) → queda gateado hasta aceptar.
        self.assertTrue(legal_acceptance_required(admin))
