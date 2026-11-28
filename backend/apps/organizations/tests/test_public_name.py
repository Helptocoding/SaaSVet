"""Nombre público de la clínica (ADR p70 D5, plan F1.6).

`Organization.public_name` es el nombre comercial o, si está vacío, el legal.
Lo usan el membrete de los PDFs, el agente (saludo y contexto) y el encabezado
del menú (`/me/` → `organization_public_name`).
"""
from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.agent.prompts import build_persona_preamble
from apps.agent.tier0 import render_first_reply
from apps.core.pdf import render_branded_pdf
from apps.organizations.models import Organization
from apps.users.models import User


class PublicNameTests(SimpleTestCase):
    def test_commercial_name_wins_and_falls_back_to_legal(self):
        self.assertEqual(Organization(name='Servicios Vet SA', display_name='Clínica Luna').public_name,
                         'Clínica Luna')
        self.assertEqual(Organization(name='Servicios Vet SA', display_name='   ').public_name,
                         'Servicios Vet SA')

    def test_the_pdf_letterhead_uses_it(self):
        from pypdf import PdfReader
        from reportlab.platypus import Paragraph
        from apps.core.pdf import DEFAULT_THEME, build_styles
        buf = BytesIO()
        org = SimpleNamespace(name='Servicios Vet SA', public_name='Clínica Luna', timezone='UTC')
        story = [Paragraph('Contenido', build_styles(DEFAULT_THEME)['body'])]
        render_branded_pdf(buf, story, organization=org, doc_kicker='Receta', pdf_title='Receta')
        text = '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(buf.getvalue())).pages)
        self.assertIn('Clínica Luna', text)
        self.assertNotIn('Servicios Vet SA', text)

    def test_the_agent_greets_and_reasons_with_it(self):
        org = Organization(name='Servicios Vet SA', display_name='Clínica Luna')
        self.assertEqual(build_persona_preamble(None, org), 'Clínica: Clínica Luna.')
        reply = render_first_reply(None, org)
        self.assertIn('Clínica Luna', reply)
        self.assertNotIn('Servicios Vet SA', reply)


class PublicNameInMeTests(TestCase):
    def test_me_publishes_it_for_the_menu(self):
        org = Organization.objects.create(name='Servicios Vet SA', display_name='Clínica Luna')
        user = User.objects.create_user(username='pn_user', password='p', organization=org, role='VET')
        client = APIClient()
        client.force_authenticate(user)
        data = client.get('/api/me/').data
        self.assertEqual(data['organization_public_name'], 'Clínica Luna')
        self.assertEqual(data['organization_name'], 'Servicios Vet SA')
