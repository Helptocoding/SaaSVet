"""
Plantilla base de documento con membrete: header/footer en cada página,
numeración "Página N de M" y marca de agua opcional.

También define la geometría compartida del paquete — los views consumen
``CONTENT_WIDTH`` para calcular anchos de columnas de tablas.
"""
from functools import partial

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as _canvas
from reportlab.platypus import SimpleDocTemplate

from apps.core.datetime_utils import org_now_local
from apps.core.pdf_utils import safe_pdf_text

from .theme import get_theme_for_organization

PAGE_SIZE = letter
PAGE_W, PAGE_H = PAGE_SIZE
MARGIN_X = 2 * cm
TOP_MARGIN = 3.2 * cm
BOTTOM_MARGIN = 2.3 * cm
#: Ancho útil para flowables (para colWidths de tablas en los views).
CONTENT_WIDTH = PAGE_W - 2 * MARGIN_X

_HEADER_BASELINE_Y = PAGE_H - 1.55 * cm
_HEADER_RULE_Y = PAGE_H - 1.95 * cm
_FOOTER_RULE_Y = 1.55 * cm
_FOOTER_TEXT_Y = 1.18 * cm


def _fit_text(cnv, text, font, max_size, min_size, max_width):
    """Reduce el tamaño de fuente hasta ``min_size``; si aún no cabe, trunca con '…'."""
    size = max_size
    while size > min_size and cnv.stringWidth(text, font, size) > max_width:
        size -= 0.5
    if cnv.stringWidth(text, font, size) <= max_width:
        return text, size
    while len(text) > 1 and cnv.stringWidth(text + '…', font, size) > max_width:
        text = text[:-1]
    return text + '…', size


def _draw_chrome(cnv, doc, *, org_name, kicker, generated_text, theme, watermark):
    """Membrete + pie de página. Corre en cada página (callback onPage)."""
    cnv.saveState()

    # Marca de agua diagonal (alpha bajo para no estorbar la lectura).
    if watermark:
        cnv.saveState()
        cnv.translate(PAGE_W / 2, PAGE_H / 2)
        cnv.rotate(45)
        cnv.setFont(theme.font_bold, 64)
        cnv.setFillColor(theme.muted)
        try:
            cnv.setFillAlpha(0.08)
        except AttributeError:
            pass
        cnv.drawCentredString(0, 0, watermark)
        cnv.restoreState()

    # Header: nombre de la clínica (izquierda) + tipo de documento (derecha).
    kicker_w = cnv.stringWidth(kicker, theme.font_bold, 7.5)
    name_max_w = CONTENT_WIDTH - kicker_w - 0.6 * cm
    name, name_size = _fit_text(cnv, org_name, theme.font_bold, 13, 9, name_max_w)
    cnv.setFont(theme.font_bold, name_size)
    cnv.setFillColor(theme.brand)
    cnv.drawString(MARGIN_X, _HEADER_BASELINE_Y, name)

    cnv.setFont(theme.font_bold, 7.5)
    cnv.setFillColor(theme.muted)
    cnv.drawRightString(PAGE_W - MARGIN_X, _HEADER_BASELINE_Y, kicker)

    cnv.setStrokeColor(theme.brand)
    cnv.setLineWidth(1.1)
    cnv.line(MARGIN_X, _HEADER_RULE_Y, PAGE_W - MARGIN_X, _HEADER_RULE_Y)

    # Footer: hairline + fecha de generación (izquierda). La numeración la
    # dibuja _NumberedCanvas en la segunda pasada (necesita el total).
    cnv.setStrokeColor(theme.line)
    cnv.setLineWidth(0.5)
    cnv.line(MARGIN_X, _FOOTER_RULE_Y, PAGE_W - MARGIN_X, _FOOTER_RULE_Y)
    cnv.setFont(theme.font, 7)
    cnv.setFillColor(theme.muted)
    cnv.drawString(MARGIN_X, _FOOTER_TEXT_Y, generated_text)

    cnv.restoreState()


def _numbered_canvas_factory(theme):
    """Canvas de dos pasadas — recipe estándar para "Página N de M"."""
    class _NumberedCanvas(_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.setFont(theme.font, 7)
                self.setFillColor(theme.muted)
                self.drawRightString(
                    PAGE_W - MARGIN_X, _FOOTER_TEXT_Y,
                    f"Página {self._pageNumber} de {total}",
                )
                super().showPage()
            super().save()

    return _NumberedCanvas


def render_branded_pdf(buffer, story, *, organization, doc_kicker, pdf_title,
                       watermark=None, theme=None):
    """
    Construye el PDF con membrete sobre ``buffer``.

    El caller arma ``story`` (flowables con el contenido del dominio); aquí
    solo se agrega el chrome visual: header, footer, numeración y watermark.
    No ejecuta queries.
    """
    theme = theme or get_theme_for_organization(organization)
    org_name = safe_pdf_text(getattr(organization, 'name', '') or '')
    generated_local = org_now_local(organization).strftime('%d/%m/%Y %H:%M')

    doc = SimpleDocTemplate(
        buffer, pagesize=PAGE_SIZE,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN,
        title=pdf_title,
    )
    chrome = partial(
        _draw_chrome,
        org_name=org_name,
        kicker=safe_pdf_text(doc_kicker or '').upper(),
        generated_text=f"Generado el {generated_local}",
        theme=theme,
        watermark=safe_pdf_text(watermark) if watermark else None,
    )
    doc.build(
        story,
        onFirstPage=chrome, onLaterPages=chrome,
        canvasmaker=_numbered_canvas_factory(theme),
    )
    return doc
