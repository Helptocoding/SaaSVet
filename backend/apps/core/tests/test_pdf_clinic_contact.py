"""Datos de la clínica en el membrete de los PDFs (ADR p70, plan F2.4).

Bajo el nombre público van el teléfono y la dirección, solo si se capturaron.
Se dibujan en el canvas (`drawString`), que no interpreta marcado; se limpian
caracteres de control y saltos. Leen la fila de la organización ya cargada:
cero consultas.
"""
from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from reportlab.platypus import Paragraph

from apps.core.pdf import DEFAULT_THEME, build_styles, render_branded_pdf
from apps.core.pdf.document import clinic_contact_line
from apps.organizations.models import Organization


def _org(**fields):
    base = dict(name='Servicios Vet SA', public_name='Clínica Luna', timezone='UTC',
                phone='', address_line1='', address_line2='', district='', city='',
                state='', postal_code='')
    base.update(fields)
    return SimpleNamespace(**base)


def _pdf_text(organization):
    from pypdf import PdfReader
    buf = BytesIO()
    story = [Paragraph('Contenido', build_styles(DEFAULT_THEME)['body'])]
    render_branded_pdf(buf, story, organization=organization, doc_kicker='Receta', pdf_title='Receta')
    reader = PdfReader(BytesIO(buf.getvalue()))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


class ClinicContactLineTests(SimpleTestCase):
    def test_phone_and_full_address(self):
        org = _org(phone='5512345678', address_line1='Av. Juárez 10', address_line2='Local 3',
                   district='Centro', city='Toluca', state='Estado de México', postal_code='50000')
        self.assertEqual(
            clinic_contact_line(org),
            'Tel. 5512345678 · Av. Juárez 10, Local 3, Centro, Toluca, Estado de México, C.P. 50000',
        )

    def test_only_what_was_captured(self):
        self.assertEqual(clinic_contact_line(_org(phone='5512345678')), 'Tel. 5512345678')
        self.assertEqual(clinic_contact_line(_org(city='Toluca', postal_code='50000')), 'Toluca, C.P. 50000')
        self.assertEqual(clinic_contact_line(_org(postal_code='50000')), 'C.P. 50000')
        self.assertEqual(clinic_contact_line(_org()), '')

    def test_an_organization_without_the_fields_does_not_break(self):
        self.assertEqual(clinic_contact_line(SimpleNamespace(name='X', timezone='UTC')), '')

    def test_breaks_and_control_characters_are_removed(self):
        org = _org(address_line1='Calle 1\nCol.\x00 Centro', city='  Toluca \t ')
        self.assertEqual(clinic_contact_line(org), 'Calle 1 Col. Centro, Toluca')


class LetterheadContactTests(SimpleTestCase):
    def test_letterhead_shows_phone_and_address_under_the_name(self):
        text = _pdf_text(_org(phone='5512345678', address_line1='Av. Juárez 10', city='Toluca'))
        self.assertIn('Clínica Luna', text)
        self.assertIn('Tel. 5512345678', text)
        self.assertIn('Av. Juárez 10, Toluca', text)

    def test_without_contact_there_is_no_empty_line(self):
        text = _pdf_text(_org())
        self.assertIn('Clínica Luna', text)
        self.assertNotIn('Tel.', text)
        self.assertNotIn('C.P.', text)

    def test_markup_in_the_address_is_printed_as_text(self):
        hostile = '<img src="file:///etc/passwd"/> <b>sin cerrar'
        text = _pdf_text(_org(address_line1=hostile, phone='5512345678'))
        self.assertIn('<img src=', text)
        self.assertIn('<b>sin cerrar', text)

    def test_a_very_long_address_is_cut_without_breaking_the_document(self):
        text = _pdf_text(_org(address_line1='Calle muy larga ' * 40, phone='5512345678'))
        self.assertIn('Tel. 5512345678', text)
        self.assertIn('…', text)


class LetterheadQueriesTests(TestCase):
    def test_rendering_the_letterhead_makes_no_queries(self):
        org = Organization.objects.create(
            name='Servicios Vet SA', display_name='Clínica Luna', phone='5512345678',
            address_line1='Av. Juárez 10', city='Toluca', postal_code='50000',
        )
        org = Organization.objects.get(pk=org.pk)
        story = [Paragraph('Contenido', build_styles(DEFAULT_THEME)['body'])]
        with self.assertNumQueries(0):
            render_branded_pdf(BytesIO(), story, organization=org, doc_kicker='Receta', pdf_title='Receta')
