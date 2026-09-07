"""Filtros DRF compartidos."""
from rest_framework.filters import OrderingFilter


class StableOrderingFilter(OrderingFilter):
    """
    OrderingFilter que garantiza un **orden total** agregando `-id` como
    desempate cuando el `?ordering` solicitado no lo incluye.

    Sin esto, ordenar por un campo con valores repetidos deja las filas
    empatadas en orden no determinista entre consultas → al paginar, una fila
    puede aparecer en dos páginas o saltarse (P1-2). El dominio garantiza
    empates: p.ej. `?ordering=total` sobre facturas emitidas con el mismo total.
    El orden por defecto de la vista
    (`ordering = ['-created_at', '-id']`) ya es estable; este filtro cubre el
    path opt-in del `?ordering`.
    """
    tiebreaker = '-id'

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering
        # ¿ya desempata por PK (asc o desc)? entonces no tocar.
        if any(field.lstrip('-') == 'id' for field in ordering):
            return ordering
        return [*ordering, self.tiebreaker]
