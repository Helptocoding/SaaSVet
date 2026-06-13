"""
Paginación DRF — P1-2 (escalabilidad de endpoints).

Decisiones (ver reporte P1-2):
- NO se activa `DEFAULT_PAGINATION_CLASS` global. La paginación es opt-in por
  view (`pagination_class = ...`). Así los catálogos pequeños y los endpoints
  `?search` (que alimentan SearchSelect con array plano) quedan sin envolver.
- `StandardResultsPagination` (PageNumber, 25) para tablas administrativas
  acotadas por filtro (invoices, prescriptions, owners).
- `StockMovementCursorPagination` (Cursor, 50) SOLO para StockMovement: ledger
  append-only de alto volumen (50k+), donde el offset profundo degrada y los
  inserts concurrentes desplazarían filas en PageNumber. Orden estable
  `(-created_at, -id)`.

El contrato de respuesta paginada es el estándar DRF:
`{ "count", "next", "previous", "results": [...] }` (PageNumber) y
`{ "next", "previous", "results": [...] }` (Cursor, sin count por diseño).
El frontend normaliza con `utils/toList.js`.
"""
from rest_framework.pagination import CursorPagination, PageNumberPagination


class StandardResultsPagination(PageNumberPagination):
    """PageNumber 25, tope 100. Tablas administrativas (Cobros, Recetas, Owners)."""
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class StockMovementCursorPagination(CursorPagination):
    """
    Cursor para el ledger de movimientos de inventario.

    Orden `(-created_at, -id)` → total order estable: `created_at` puede colisionar
    (varios movimientos en la misma transacción atómica), el `-id` desempata para
    que el cursor no salte ni duplique filas entre páginas.
    """
    page_size = 50
    max_page_size = 100
    page_size_query_param = 'page_size'
    ordering = ('-created_at', '-id')
