"""
Smoke tests del paquete apps.core.pdf (Fase 1 rediseño documentos).

Sin DB (SimpleTestCase): el paquete no debe ejecutar queries — los tests de
N+1 de los endpoints PDF dependen de eso.
"""
from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase

from reportlab.lib.units import cm
from reportlab.platypus import Paragraph

from apps.core.pdf import (
    CONTENT_WIDTH,
    DEFAULT_THEME,
    build_styles,
    data_table,
    info_card,
    numbered_item,
    render_branded_pdf,
    section,
    signature_block,
    tint,
    title_block,
    totals_table,
)


def _extract_pdf_text_pages(content):
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(content))
    return [page.extract_text() or "" for page in reader.pages]


def _org(name="Clínica Demo", tz="UTC"):
    return SimpleNamespace(name=name, timezone=tz)


def _render(story, *, org=None, kicker="Documento de prueba", watermark=None):
    buf = BytesIO()
    render_branded_pdf(
        buf, story,
        organization=org or _org(),
        doc_kicker=kicker,
        pdf_title="Test",
        watermark=watermark,
    )
    return buf.getvalue()


class PdfThemeSmokeTests(SimpleTestCase):

    def setUp(self):
        self.theme = DEFAULT_THEME
        self.st = build_styles(self.theme)

    def _sample_story(self, table_rows=5):
        st, theme = self.st, self.theme
        flow = []
        flow += title_block(st, "Documento #1", ["Estado: <b>Abierto</b>", "Fecha: 01/01/2026"])
        flow += section(st, theme, "Datos")
        flow += info_card(st, theme, [
            ("Nombre", "Firulais"), ("Especie", "Perro"), ("Raza", ""),
            ("Dueño", "Juan Pérez"), ("Teléfono", "5551234567"),
        ], columns=3)
        flow += section(st, theme, "Tabla")
        rows = [
            [Paragraph(f"Concepto fila {i}", st['cell']), f"{i}", "$10.00"]
            for i in range(table_rows)
        ]
        flow += data_table(
            st, theme, ["Concepto", "Cant.", "Precio"], rows,
            col_widths=[CONTENT_WIDTH - 5 * cm, 2.5 * cm, 2.5 * cm],
            align_right=(1, 2),
        )
        flow += totals_table(st, theme, [["Subtotal", "$50.00"], ["Total", "$58.00"]])
        flow += numbered_item(st, 1, "Amoxicilina — 1 caja", ["Dosis: 1 al día", "Duración: 7 días"])
        flow += signature_block(st, theme, "MVZ Ana Pérez", ["Cirugía"])
        return flow

    def test_render_produces_pdf_with_chrome(self):
        content = _render(self._sample_story())
        self.assertTrue(content.startswith(b'%PDF'))
        pages = _extract_pdf_text_pages(content)
        text = "\n".join(pages)
        self.assertIn("Clínica Demo", text)            # header: nombre org
        self.assertIn("DOCUMENTO DE PRUEBA", text)     # header: kicker uppercased
        self.assertIn("Página 1 de", text)             # footer: numeración
        self.assertIn("Generado el", text)             # footer: fecha generación
        self.assertIn("Firulais", text)
        self.assertIn("MVZ Ana Pérez", text)

    def test_multipage_repeats_chrome_and_numbers_pages(self):
        content = _render(self._sample_story(table_rows=60))
        pages = _extract_pdf_text_pages(content)
        self.assertGreaterEqual(len(pages), 2)
        # Header y numeración presentes también en la segunda página.
        self.assertIn("DOCUMENTO DE PRUEBA", pages[1])
        self.assertIn(f"Página 2 de {len(pages)}", pages[1])

    def test_watermark_text_present(self):
        content = _render(self._sample_story(), watermark="BORRADOR")
        text = "\n".join(_extract_pdf_text_pages(content))
        self.assertIn("BORRADOR", text)

    def test_no_watermark_by_default(self):
        content = _render(self._sample_story())
        text = "\n".join(_extract_pdf_text_pages(content))
        self.assertNotIn("BORRADOR", text)

    def test_long_org_name_does_not_crash(self):
        org = _org(name="Clínica Veterinaria de Especialidades " * 10)
        content = _render(self._sample_story(), org=org)
        self.assertTrue(content.startswith(b'%PDF'))

    def test_data_table_without_rows_renders(self):
        flow = title_block(self.st, "Doc") + data_table(
            self.st, self.theme, ["A", "B"], [],
            col_widths=[CONTENT_WIDTH - 4 * cm, 4 * cm],
        )
        content = _render(flow)
        self.assertTrue(content.startswith(b'%PDF'))

    def test_info_card_empty_returns_no_flowables(self):
        self.assertEqual(info_card(self.st, self.theme, []), [])

    def test_info_card_blank_value_shows_dash(self):
        flow = title_block(self.st, "Doc") + info_card(
            self.st, self.theme, [("Raza", "")], columns=2,
        )
        text = "\n".join(_extract_pdf_text_pages(_render(flow)))
        self.assertIn("—", text)

    def test_tint_bounds(self):
        brand = DEFAULT_THEME.brand
        white = tint(brand, 0)
        self.assertAlmostEqual(white.red, 1.0)
        self.assertAlmostEqual(white.green, 1.0)
        self.assertAlmostEqual(white.blue, 1.0)
        full = tint(brand, 1)
        self.assertAlmostEqual(full.red, brand.red)
        self.assertAlmostEqual(full.green, brand.green)
        self.assertAlmostEqual(full.blue, brand.blue)

    def test_org_timezone_used_for_generated_label(self):
        # No debe explotar con timezone real de México; el label es texto libre.
        org = _org(tz="America/Mexico_City")
        content = _render(self._sample_story(), org=org)
        self.assertTrue(content.startswith(b'%PDF'))
