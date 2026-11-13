"""H-4: el texto de usuario nunca se interpreta como marcado de ReportLab.

`Paragraph` entiende `<img src>`, que abre archivos locales y URLs. La exploración
física (`assessment.exam`) no pasa por `sanitize_text`, así que era alcanzable por la
API. Estas pruebas recorren esa ruta real contra un servidor en 127.0.0.1: nada sale
de la máquina.
"""
import ast
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
import tempfile
import threading

from django.test import SimpleTestCase
from pypdf import PdfReader
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph
from rest_framework.test import APITestCase

from apps.core.pdf_utils import pdf_markup, safe_pdf_text
from apps.core.sanitize import sanitize_text
from apps.medical_records.models import ConsultationAssessment, MedicalRecord
from apps.medical_records.tests.test_pdf import _make_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

BACKEND_APPS = Path(__file__).resolve().parents[2]
PDF_VIEWS = [
    BACKEND_APPS / 'billing/views.py',
    BACKEND_APPS / 'medical_records/views.py',
    BACKEND_APPS / 'prescriptions/views.py',
]
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
STYLE = getSampleStyleSheet()['Normal']


def plain(markup):
    return Paragraph(markup, STYLE).getPlainText()


class ImageServer:
    """Sirve un PNG en 127.0.0.1 y anota quién lo pide."""

    def __init__(self, test):
        self.hits = hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.end_headers()
                self.wfile.write(PNG)

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        test.addCleanup(thread.join)
        test.addCleanup(server.server_close)
        test.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_address[1]}/probe.png'


class ExamMarkupThroughTheRealApi(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica', timezone='UTC')
        cls.vet = _make_user('vet_markup', cls.org, 'VET')
        cls.vet.license_number = '1234567'  # M01 (orden 7): firma la consulta
        cls.vet.save(update_fields=['license_number'])
        owner = Owner.objects.create(name='Carlos', phone='5559876543', organization=cls.org)
        cls.pet = Pet.objects.create(name='Luna', species='cat', owner=owner, organization=cls.org,
                                     birth_date='2020-01-01')

    def setUp(self):
        self.client.force_authenticate(self.vet)

    def _pdf_of_closed_record_with_finding(self, finding):
        record = MedicalRecord.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            diagnosis='Dx', treatment='Tx',
            consultation_type=MedicalRecord.ConsultationType.GENERAL)
        url = f'/api/medical-records/{record.public_id}/'
        draft = {'general': {'exam': {'piel': {'status': 'altered', 'finding': finding}}}}
        response = self.client.patch(url, {'consultation_draft': draft}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.post(f'{url}close/', format='json')
        self.assertEqual(response.status_code, 200, response.content)
        stored = ConsultationAssessment.objects.get(medical_record=record).exam
        self.assertEqual(stored['piel']['finding'], finding, 'El payload debe llegar crudo')
        return self.client.get(f'{url}pdf/')

    def _text(self, response):
        return ''.join(p.extract_text() or '' for p in PdfReader(BytesIO(response.content)).pages)

    def test_img_url_does_not_trigger_a_server_side_request(self):
        server = ImageServer(self)
        response = self._pdf_of_closed_record_with_finding(f'<img src="{server.url}" width="9" height="9"/>')
        self.assertEqual(server.hits, [])
        self.assertEqual(response.status_code, 200)
        self.assertIn('<img', self._text(response))

    def test_img_local_file_is_not_embedded(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'secret.png'
            image.write_bytes(PNG)
            response = self._pdf_of_closed_record_with_finding(
                f'<img src="{image.as_posix()}" width="9" height="9"/>')
        self.assertEqual(response.status_code, 200)
        images = [i for p in PdfReader(BytesIO(response.content)).pages for i in p.images]
        self.assertEqual(images, [])

    def test_missing_file_does_not_become_an_existence_oracle(self):
        response = self._pdf_of_closed_record_with_finding('<img src="/no/existe.png"/>')
        self.assertEqual(response.status_code, 200)

    def test_unbalanced_markup_does_not_break_the_document(self):
        response = self._pdf_of_closed_record_with_finding('T < 39 & <b>sin cerrar')
        self.assertEqual(response.status_code, 200)
        self.assertIn('T < 39 & <b>sin cerrar', self._text(response))


class PdfMarkupContract(SimpleTestCase):
    def test_hostile_text_is_only_ever_text(self):
        for hostile in ('<script>alert(1)</script>', '<img src="/etc/passwd"/>',
                        '<img src="http://169.254.169.254/x"/>', '/etc/passwd',
                        'http://interno/x', '<para><b>x</b></para>', '<a href="x">y</a>'):
            with self.subTest(hostile=hostile):
                self.assertEqual(plain(pdf_markup(hostile)), hostile)

    def test_encoded_payload_cannot_become_markup(self):
        self.assertEqual(plain(pdf_markup('&lt;img src="/etc/passwd"/&gt;')), '<img src="/etc/passwd"/>')

    def test_text_stored_by_sanitize_text_is_not_escaped_twice(self):
        stored = sanitize_text('T < 39 & FC > 20')
        self.assertEqual(stored, 'T &lt; 39 &amp; FC &gt; 20')
        self.assertEqual(plain(pdf_markup(stored)), 'T < 39 & FC > 20')

    def test_special_characters_render_literally(self):
        self.assertEqual(plain(pdf_markup('A & B < C > D')), 'A & B < C > D')

    def test_empty_values_use_the_default(self):
        self.assertEqual(pdf_markup(None), '')
        self.assertEqual(pdf_markup(''), '')
        self.assertEqual(pdf_markup(None, default='—'), '—')

    def test_control_characters_are_still_removed(self):
        self.assertEqual(pdf_markup('a\x00b\x07c'), 'abc')

    def test_truncation_never_splits_an_entity(self):
        self.assertEqual(pdf_markup('abc&def', max_length=4), 'abc&amp;')
        self.assertEqual(plain(pdf_markup('abc&lt;def', max_length=4)), 'abc<')

    def test_line_breaks_are_the_only_markup_it_produces(self):
        self.assertEqual(pdf_markup('a\n<b>c</b>', linebreaks=True), 'a<br/>&lt;b&gt;c&lt;/b&gt;')

    def test_plain_helper_is_unchanged_for_the_canvas(self):
        self.assertEqual(safe_pdf_text('A & B'), 'A & B')


class EveryParagraphHonoursTheContract(SimpleTestCase):
    """Un `Paragraph` nuevo con un dato sin escapar pone esto en rojo."""

    SAFE_CALLS = {'pdf_markup', 'fmt_dt', 'strftime', '_fmt_money'}
    SAFE_NAMES = {'spec', 'prod_name', 'pres_name'}

    def _unsafe_leaves(self, node):
        if isinstance(node, ast.Constant):
            return []
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
            return [] if name in self.SAFE_CALLS else [ast.unparse(node)]
        if isinstance(node, ast.JoinedStr):
            return [leaf for v in node.values for leaf in self._unsafe_leaves(v)]
        if isinstance(node, ast.FormattedValue):
            return self._unsafe_leaves(node.value)
        if isinstance(node, ast.BinOp):
            return self._unsafe_leaves(node.left) + self._unsafe_leaves(node.right)
        if isinstance(node, ast.Name) and node.id in self.SAFE_NAMES:
            return []
        return [ast.unparse(node)]

    def test_views_only_build_paragraphs_from_escaped_values(self):
        offenders = []
        for path in PDF_VIEWS:
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'Paragraph':
                    for leaf in self._unsafe_leaves(node.args[0]):
                        offenders.append(f'{path.name}:{node.lineno}: {leaf}')
        self.assertEqual(offenders, [])

    def test_views_do_not_use_the_plain_helper(self):
        for path in PDF_VIEWS:
            with self.subTest(file=path.name):
                self.assertNotIn('safe_pdf_text', path.read_text(encoding='utf-8'))
