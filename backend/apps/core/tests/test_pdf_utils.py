from datetime import date

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.pdf_utils import pdf_filename, safe_pdf_text, safe_filename_segment


class SafePdfTextTests(SimpleTestCase):
    def test_strips_nul_bytes(self):
        self.assertEqual(safe_pdf_text("hola\x00mundo"), "holamundo")

    def test_strips_other_control_chars(self):
        # \x07 = BEL, \x1f = US
        self.assertEqual(safe_pdf_text("a\x07b\x1fc"), "abc")

    def test_preserves_tab_newline_carriage_return(self):
        self.assertEqual(safe_pdf_text("a\tb\nc\rd"), "a\tb\nc\rd")

    def test_preserves_unicode(self):
        self.assertEqual(safe_pdf_text("Ñoño con tildes áéíóú"), "Ñoño con tildes áéíóú")

    def test_none_returns_default(self):
        self.assertEqual(safe_pdf_text(None), "")
        self.assertEqual(safe_pdf_text(None, default="-"), "-")

    def test_non_string_coerces(self):
        self.assertEqual(safe_pdf_text(42), "42")


class SafeFilenameSegmentTests(SimpleTestCase):
    def test_strips_punctuation(self):
        self.assertEqual(safe_filename_segment("Hola/mundo?.txt"), "Holamundotxt")

    def test_keeps_spaces_and_dashes(self):
        self.assertEqual(safe_filename_segment("Firulais-Garcia 2026"), "Firulais-Garcia 2026")

    def test_truncates(self):
        self.assertEqual(safe_filename_segment("a" * 100, max_length=10), "a" * 10)

    def test_empty(self):
        self.assertEqual(safe_filename_segment(""), "")
        self.assertEqual(safe_filename_segment(None), "")


class PdfFilenameTests(SimpleTestCase):
    def test_basic_with_date(self):
        self.assertEqual(
            pdf_filename('receta', 142, 'Rocky', date(2026, 6, 10)),
            'receta_142_Rocky_2026-06-10.pdf',
        )

    def test_without_date(self):
        self.assertEqual(pdf_filename('consulta', 7, 'Firulais'), 'consulta_7_Firulais.pdf')

    def test_sanitizes_segment(self):
        self.assertEqual(
            pdf_filename('factura', 3, 'Max/«?»', date(2026, 1, 2)),
            'factura_3_Max_2026-01-02.pdf',
        )

    def test_empty_segment_falls_back(self):
        self.assertEqual(
            pdf_filename('consulta', 9, '', date(2026, 1, 2)),
            'consulta_9_documento_2026-01-02.pdf',
        )


class PdfDownloadCorsContractTests(SimpleTestCase):
    def test_content_disposition_is_exposed_to_browser(self):
        """
        Sin content-disposition en CORS_EXPOSE_HEADERS, axios no puede leer el
        header cross-origin y toda descarga cae al fallback genérico del
        frontend ("consulta.pdf", "consulta (1).pdf"...).
        """
        exposed = [h.lower() for h in getattr(settings, 'CORS_EXPOSE_HEADERS', [])]
        self.assertIn('content-disposition', exposed)
