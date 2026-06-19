import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";
import s from "./EntitySearch.module.css";

/**
 * EntitySearch — combobox relacional reusable (mascotas, clientes, …).
 *
 * Reemplaza el uso crudo de `SearchSelect` para entidades con muchos registros
 * (clínicas importadas con miles). Reusa el patrón probado de SearchSelect
 * (debounce 250ms, protección de carrera con `reqId`, estado loading) pero la
 * API soporta lo que faltaba:
 *
 *   - **Render rico** (`renderItem`): cada opción muestra contexto suficiente
 *     para diferenciar homónimos (dueño · teléfono · expediente), no solo un
 *     string. Con datos reales "Bella / Bella / Bella" deja de ser ambiguo.
 *   - **Paginación incremental** (`fetchPage` + "Ver más"): la primera página
 *     trae pocos (el fetcher define el tamaño, 8 en `api/lookups.js`) y se cargan
 *     más bajo demanda. NO hay tope invisible: si hay más coincidencias, el
 *     usuario las puede traer.
 *
 * Contrato de `fetchPage`:
 *   fetchPage({ query, page }) => Promise<{ items: object[], hasMore: boolean }>
 *   - `page` es 1-based. El consumidor mapea su API → `items` (cada item debe
 *     traer `id` para el cuerpo de la petición y, si aplica, `public_id`).
 *
 * `value` es el item seleccionado (o null). `getOptionLabel(item)` define el
 * texto del input tras seleccionar.
 */
export default function EntitySearch({
    id,
    name,
    value,
    onChange,
    fetchPage,
    renderItem,
    getOptionLabel = (item) => item?.label ?? "",
    placeholder = "Buscar...",
    disabled = false,
    prefetchOnFocus = true,
    defaultQuery = "",
    emptyText = "Sin resultados",
}) {
    const autoId = useId();
    const inputId = id || `entity-search-${autoId}`;
    const listboxId = `${inputId}-listbox`;

    const [inputVal, setInputVal] = useState(value ? getOptionLabel(value) : "");
    const [items, setItems] = useState([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);       // primera página
    const [loadingMore, setLoadingMore] = useState(false); // "Ver más"
    const [hasMore, setHasMore] = useState(false);
    const [highlight, setHighlight] = useState(-1);

    const wrapperRef = useRef(null);
    const debounceRef = useRef(null);
    const reqId = useRef(0);
    const pageRef = useRef(1);
    const queryRef = useRef("");

    // Sincroniza el texto del input cuando el padre resetea/cambia el value.
    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- sync de prop externa (value)
        setInputVal(value ? getOptionLabel(value) : "");
        if (!value) {
            setItems([]);
            setOpen(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value?.id, value?.public_id]);

    // Cerrar al click fuera.
    useEffect(() => {
        function handleMouseDown(e) {
            if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false);
        }
        document.addEventListener("mousedown", handleMouseDown);
        return () => document.removeEventListener("mousedown", handleMouseDown);
    }, []);

    function fetchFirstPage(q) {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        setLoading(true);
        setOpen(true);
        setHighlight(-1);
        debounceRef.current = setTimeout(() => {
            const rid = ++reqId.current;
            queryRef.current = q;
            pageRef.current = 1;
            fetchPage({ query: q, page: 1 })
                .then(({ items: rows, hasMore: more }) => {
                    if (reqId.current !== rid) return;   // respuesta vieja, descartar
                    setItems(rows);
                    setHasMore(Boolean(more));
                    setLoading(false);
                })
                .catch(() => {
                    if (reqId.current !== rid) return;
                    toast.error("Error al buscar");
                    setItems([]);
                    setHasMore(false);
                    setLoading(false);
                });
        }, 250);
    }

    function loadMore() {
        if (loadingMore || loading || !hasMore) return;
        const rid = reqId.current;                // mismo query que la última búsqueda
        const nextPage = pageRef.current + 1;
        setLoadingMore(true);
        fetchPage({ query: queryRef.current, page: nextPage })
            .then(({ items: rows, hasMore: more }) => {
                if (reqId.current !== rid) return; // el query cambió mientras tanto
                pageRef.current = nextPage;
                setItems(prev => [...prev, ...rows]);
                setHasMore(Boolean(more));
                setLoadingMore(false);
            })
            .catch(() => {
                if (reqId.current !== rid) return;
                toast.error("Error al cargar más");
                setLoadingMore(false);
            });
    }

    function handleInputChange(e) {
        const q = e.target.value;
        setInputVal(q);
        if (!q.trim()) {
            if (prefetchOnFocus) {
                fetchFirstPage(defaultQuery);
            } else {
                setItems([]);
                setHasMore(false);
                setOpen(false);
                setLoading(false);
            }
            return;
        }
        fetchFirstPage(q);
    }

    function handleSelect(item) {
        setInputVal(getOptionLabel(item));
        setItems([]);
        setHasMore(false);
        setOpen(false);
        setHighlight(-1);
        onChange(item);
    }

    function handleClear(e) {
        e.stopPropagation();
        if (debounceRef.current) clearTimeout(debounceRef.current);
        reqId.current++;
        setInputVal("");
        setItems([]);
        setHasMore(false);
        setOpen(false);
        setLoading(false);
        setHighlight(-1);
        onChange(null);
    }

    function handleKeyDown(e) {
        if (e.key === "Escape") { setOpen(false); return; }
        if (e.key === "ArrowDown") {
            e.preventDefault();
            if (!open) { fetchFirstPage(inputVal.trim() || defaultQuery); return; }
            setHighlight(h => Math.min(h + 1, items.length - 1));
            return;
        }
        if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight(h => Math.max(h - 1, -1));
            return;
        }
        if (e.key === "Enter" && open && highlight >= 0 && items[highlight]) {
            e.preventDefault();
            handleSelect(items[highlight]);
        }
    }

    function handleFocus() {
        if (disabled) return;
        if (prefetchOnFocus && items.length === 0 && !loading) {
            fetchFirstPage(defaultQuery);
            return;
        }
        if (items.length > 0) setOpen(true);
    }

    const showClear = !disabled && value !== null && value !== undefined;

    return (
        <div ref={wrapperRef} className={s.wrap}>
            <div className={s.inputWrap}>
                <input
                    id={inputId}
                    name={name || inputId}
                    className="input"
                    value={inputVal}
                    onChange={handleInputChange}
                    onKeyDown={handleKeyDown}
                    onFocus={handleFocus}
                    placeholder={placeholder}
                    disabled={disabled}
                    style={{ paddingRight: showClear ? "28px" : undefined, width: "100%", boxSizing: "border-box" }}
                    autoComplete="off"
                    role="combobox"
                    aria-expanded={open}
                    aria-controls={listboxId}
                />
                {showClear && (
                    <button type="button" className={s.clearBtn} onClick={handleClear} tabIndex={-1} aria-label="Limpiar">
                        ×
                    </button>
                )}
            </div>

            {open && (
                <div id={listboxId} role="listbox" className={s.listbox}>
                    {loading && <div className={s.hint}>Buscando...</div>}
                    {!loading && items.length === 0 && <div className={s.hint}>{emptyText}</div>}
                    {!loading && items.map((item, index) => (
                        <div
                            key={item.public_id ?? item.id ?? index}
                            role="option"
                            aria-selected={highlight === index}
                            className={`${s.option} ${highlight === index ? s.optionActive : ""}`}
                            onMouseDown={() => handleSelect(item)}
                            onMouseEnter={() => setHighlight(index)}
                        >
                            {renderItem ? renderItem(item) : <span>{getOptionLabel(item)}</span>}
                        </div>
                    ))}
                    {!loading && hasMore && (
                        <button
                            type="button"
                            className={s.moreBtn}
                            // onMouseDown (no onClick) → corre antes del blur del input,
                            // así el dropdown no se cierra al pedir más.
                            onMouseDown={(e) => { e.preventDefault(); loadMore(); }}
                            disabled={loadingMore}
                        >
                            {loadingMore ? "Cargando..." : "Ver más resultados"}
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}
