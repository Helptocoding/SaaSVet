"""
Tema visual compartido para los PDFs generados por el SaaS.

Fase 1 del rediseño de documentos: tema único hardcodeado, derivado de la
paleta del design system (verde bosque / cream — ver frontend/design-system.md).
En Fase 2 (branding por organización), ``get_theme_for_organization()`` leerá
el branding del tenant (logo, color, datos de contacto) y este módulo será el
único punto de cambio — los views no se tocan.

Nada en este paquete ejecuta queries: los views siguen siendo dueños de QUÉ
datos lleva cada documento; aquí solo vive CÓMO se ve.
"""
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle


def tint(color, fraction):
    """Mezcla ``color`` con blanco. ``fraction=0`` → blanco, ``1`` → color puro."""
    return colors.Color(
        1 - (1 - color.red) * fraction,
        1 - (1 - color.green) * fraction,
        1 - (1 - color.blue) * fraction,
    )


@dataclass(frozen=True)
class DocumentTheme:
    """Paleta + tipografía de un documento. Inmutable por diseño."""
    brand: colors.Color
    brand_dark: colors.Color
    ink: colors.Color
    muted: colors.Color
    line: colors.Color
    card_bg: colors.Color
    font: str = 'Helvetica'
    font_bold: str = 'Helvetica-Bold'
    font_italic: str = 'Helvetica-Oblique'

    @property
    def table_header_bg(self):
        return tint(self.brand, 0.10)

    @property
    def zebra_bg(self):
        return tint(self.brand, 0.035)


#: Paleta por defecto = identidad VetCare (tokens.css / design-system.md).
DEFAULT_THEME = DocumentTheme(
    brand=colors.HexColor('#1a4434'),
    brand_dark=colors.HexColor('#0f2a1f'),
    ink=colors.HexColor('#1f1f1f'),
    muted=colors.HexColor('#6f6f64'),
    line=colors.HexColor('#d9d2be'),
    card_bg=colors.HexColor('#f5f1e8'),
)


def get_theme_for_organization(organization):
    """
    Resuelve el tema del documento para una organización.

    Fase 1: siempre el tema por defecto, sin tocar DB (los tests de N+1 de
    los endpoints PDF dependen de que esto NO agregue queries). Fase 2
    reemplaza el cuerpo por una lectura de OrganizationBranding con fallback
    a DEFAULT_THEME.
    """
    return DEFAULT_THEME


def build_styles(theme):
    """ParagraphStyles derivados del tema. Devuelve un dict por nombre."""
    return {
        'doc_title': ParagraphStyle(
            'doc_title', fontName=theme.font_bold, fontSize=17, leading=21,
            textColor=theme.ink, spaceAfter=3,
        ),
        'doc_meta': ParagraphStyle(
            'doc_meta', fontName=theme.font, fontSize=9, leading=13,
            textColor=theme.muted,
        ),
        'section': ParagraphStyle(
            'section', fontName=theme.font_bold, fontSize=9.5, leading=12,
            textColor=theme.brand, spaceAfter=3, keepWithNext=1,
        ),
        'body': ParagraphStyle(
            'body', fontName=theme.font, fontSize=10, leading=14.5,
            textColor=theme.ink,
        ),
        'body_sm': ParagraphStyle(
            'body_sm', fontName=theme.font, fontSize=9, leading=12.5,
            textColor=theme.ink,
        ),
        'label': ParagraphStyle(
            'label', fontName=theme.font, fontSize=6.8, leading=9,
            textColor=theme.muted,
        ),
        'value': ParagraphStyle(
            'value', fontName=theme.font, fontSize=10, leading=13,
            textColor=theme.ink, spaceBefore=1,
        ),
        'item_title': ParagraphStyle(
            'item_title', fontName=theme.font_bold, fontSize=10.5, leading=14,
            textColor=theme.ink, spaceBefore=7,
        ),
        'item_detail': ParagraphStyle(
            'item_detail', fontName=theme.font, fontSize=9, leading=12.5,
            textColor=theme.muted, leftIndent=14,
        ),
        'cell': ParagraphStyle(
            'cell', fontName=theme.font, fontSize=9, leading=12,
            textColor=theme.ink,
        ),
        'note_italic': ParagraphStyle(
            'note_italic', fontName=theme.font_italic, fontSize=9,
            leading=12.5, textColor=theme.muted, spaceBefore=6,
        ),
        'sig_name': ParagraphStyle(
            'sig_name', fontName=theme.font_bold, fontSize=10, leading=13,
            textColor=theme.ink, alignment=TA_CENTER,
        ),
        'sig_sub': ParagraphStyle(
            'sig_sub', fontName=theme.font, fontSize=8.5, leading=11,
            textColor=theme.muted, alignment=TA_CENTER,
        ),
    }
