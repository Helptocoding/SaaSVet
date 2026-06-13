/**
 * Paginador Anterior/Siguiente para tablas paginadas server-side (P1-2).
 *
 * Reusable (no crear paginadores por página). Trabaja sobre el contrato
 * PageNumber de DRF: el padre conoce `page` (1-based), `count` (total) y
 * `pageSize`; este componente solo navega.
 *
 * No se renderiza si `count <= pageSize` (una sola página → sin ruido visual).
 */
const Pagination = ({ page, count, pageSize = 25, onPage, fetching = false }) => {
    const totalPages = Math.max(1, Math.ceil((count || 0) / pageSize));
    if (totalPages <= 1) return null;

    const canPrev = page > 1 && !fetching;
    const canNext = page < totalPages && !fetching;

    return (
        <div
            style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "flex-end",
                gap: 12,
                padding: "10px 14px",
                borderTop: "1px solid var(--c-border, #e5e7eb)",
                fontSize: 13,
                color: "var(--c-text-2, #4b5563)",
            }}
        >
            <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={!canPrev}
                onClick={() => canPrev && onPage(page - 1)}
                aria-label="Página anterior"
            >
                ‹ Anterior
            </button>
            <span aria-live="polite">
                Página {page} de {totalPages}
            </span>
            <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={!canNext}
                onClick={() => canNext && onPage(page + 1)}
                aria-label="Página siguiente"
            >
                Siguiente ›
            </button>
        </div>
    );
};

export default Pagination;
