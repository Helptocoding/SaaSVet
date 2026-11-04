"""
Paquete de generación de PDFs con tema compartido (Fase 1 rediseño documentos).

API pública para los views de dominio:

- ``get_theme_for_organization`` / ``build_styles`` — tema + estilos.
- ``render_branded_pdf`` / ``CONTENT_WIDTH`` — documento con membrete.
- componentes: ``title_block``, ``section``, ``info_card``, ``data_table``,
  ``totals_table``, ``numbered_item``, ``signature_block``.

Re-exporta los helpers de saneo de ``apps.core.pdf_utils`` para que los views
importen todo desde un solo lugar.
"""
from apps.core.pdf_utils import (  # noqa: F401
    pdf_filename,
    pdf_markup,
    safe_filename_segment,
    safe_pdf_text,
)

from .components import (  # noqa: F401
    data_table,
    info_card,
    numbered_item,
    section,
    signature_block,
    title_block,
    totals_table,
)
from .document import CONTENT_WIDTH, render_branded_pdf  # noqa: F401
from .theme import (  # noqa: F401
    DEFAULT_THEME,
    DocumentTheme,
    build_styles,
    get_theme_for_organization,
    tint,
)
