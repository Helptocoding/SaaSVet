import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { getPresentations, getPresentationByBarcode } from "../../api/inventory";
import { getServices } from "../../api/billing";
import s from "./pos.module.css";

const MAX_PRODUCTS = 6;
const MAX_SERVICES = 4;

const toList = (d) => (Array.isArray(d) ? d : d?.results || []);

/* ── ProductSearch — input único del POS: escáner + búsqueda ──
   Un lector USB funciona como teclado: escribe el código y envía Enter. Por
   eso Enter intenta primero el lookup exacto por código de barras
   (GET /inventory/presentations/barcode/) y solo después cae a la búsqueda
   por nombre (productos + servicios). Seleccionar agrega al carrito y limpia
   el input, listo para el siguiente escaneo. */
const ProductSearch = forwardRef(function ProductSearch({ onAddProduct, onAddService, disabled }, ref) {
    const [query, setQuery] = useState("");
    const [products, setProducts] = useState([]);
    const [services, setServices] = useState([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [highlight, setHighlight] = useState(-1);

    const inputRef = useRef(null);
    const wrapperRef = useRef(null);
    const debounceRef = useRef(null);
    const reqIdRef = useRef(0);
    const cacheRef = useRef({ products: [], services: [] });

    useImperativeHandle(ref, () => ({ focus: () => inputRef.current?.focus() }));

    // Prefetch de catálogos para mostrar sugerencias con el input vacío.
    useEffect(() => {
        Promise.all([
            getPresentations({ active: "true" }).then(toList).catch(() => []),
            getServices({ active: "true" }).then(toList).catch(() => []),
        ]).then(([pres, svcs]) => {
            cacheRef.current = { products: pres, services: svcs };
        });
    }, []);

    useEffect(() => {
        const handleMouseDown = (e) => {
            if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener("mousedown", handleMouseDown);
        return () => document.removeEventListener("mousedown", handleMouseDown);
    }, []);

    const flat = useMemo(() => [
        ...products.map(p => ({ kind: "product", item: p })),
        ...services.map(sv => ({ kind: "service", item: sv })),
    ], [products, services]);

    const runSearch = (q) => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        const lower = q.trim().toLowerCase();
        if (!lower) {
            setProducts(cacheRef.current.products.slice(0, MAX_PRODUCTS));
            setServices(cacheRef.current.services.slice(0, MAX_SERVICES));
            setLoading(false);
            setOpen(true);
            setHighlight(-1);
            return;
        }
        setLoading(true);
        setOpen(true);
        debounceRef.current = setTimeout(() => {
            const id = ++reqIdRef.current;
            const code = q.trim();
            Promise.all([
                getPresentations({ search: q }).then(toList).catch(() => []),
                getServices({ active: "true", search: q }).then(toList).catch(() => []),
                // El search del backend solo filtra por nombre de producto;
                // el código de barras tecleado (no solo escaneado con Enter)
                // también debe aparecer en el dropdown → lookup exacto extra.
                getPresentationByBarcode(code).catch(() => null),
            ]).then(([pres, svcs, byCode]) => {
                if (reqIdRef.current !== id) return;
                const merged = byCode
                    ? [byCode, ...pres.filter(p => p.id !== byCode.id)]
                    : pres;
                setProducts(merged.slice(0, MAX_PRODUCTS));
                setServices(svcs.filter(sv => sv.name?.toLowerCase().includes(lower)).slice(0, MAX_SERVICES));
                setLoading(false);
                setHighlight(-1);
            });
        }, 250);
    };

    const reset = () => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        reqIdRef.current++;
        setQuery("");
        setProducts([]);
        setServices([]);
        setOpen(false);
        setLoading(false);
        setHighlight(-1);
        inputRef.current?.focus();
    };

    const select = (entry) => {
        const added = entry.kind === "product"
            ? onAddProduct(entry.item)
            : onAddService(entry.item);
        if (added) reset();
    };

    const handleKeyDown = async (e) => {
        if (e.key === "Escape") { setOpen(false); return; }
        if (e.key === "ArrowDown") {
            e.preventDefault();
            if (!open) { runSearch(query); return; }
            setHighlight(h => Math.min(h + 1, flat.length - 1));
            return;
        }
        if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight(h => Math.max(h - 1, -1));
            return;
        }
        if (e.key !== "Enter") return;
        e.preventDefault();
        if (open && highlight >= 0 && flat[highlight]) { select(flat[highlight]); return; }
        const code = query.trim();
        if (!code) return;
        // Camino del escáner: lookup exacto por código de barras.
        try {
            const pres = await getPresentationByBarcode(code);
            if (onAddProduct(pres)) reset();
            return;
        } catch {
            // 404 → no es un código registrado; cae a la búsqueda por nombre.
        }
        if (flat.length > 0) { select(flat[0]); return; }
        toast.error(`Sin coincidencias para «${code}».`);
    };

    return (
        <div ref={wrapperRef} className={s.searchWrap}>
            <input
                ref={inputRef}
                className={`input ${s.searchInput}`}
                value={query}
                placeholder="Escanea un código o busca producto / servicio…"
                disabled={disabled}
                autoFocus
                autoComplete="off"
                role="combobox"
                aria-expanded={open}
                onChange={e => { setQuery(e.target.value); runSearch(e.target.value); }}
                onKeyDown={handleKeyDown}
                onFocus={() => { if (!disabled) runSearch(query); }}
            />
            {open && !disabled && (
                <div className={s.dropdown} role="listbox">
                    {loading && <div className={s.dropdownEmpty}>Buscando...</div>}
                    {!loading && flat.length === 0 && (
                        <div className={s.dropdownEmpty}>Sin resultados</div>
                    )}
                    {!loading && products.length > 0 && <div className={s.groupLabel}>Productos</div>}
                    {!loading && products.map((p, i) => (
                        <div
                            key={`p-${p.id}`}
                            role="option"
                            aria-selected={highlight === i}
                            className={`${s.resultRow} ${highlight === i ? s.resultRowActive : ""}`}
                            onMouseDown={() => select({ kind: "product", item: p })}
                            onMouseEnter={() => setHighlight(i)}
                        >
                            <span className={s.resultName}>
                                {p.product_name} — {p.name}
                                {p.requires_prescription ? " · Rx" : ""}
                            </span>
                            <span className={s.resultMeta}>Stock {p.stock}</span>
                            <span className={s.resultPrice}>${Number(p.sale_price).toFixed(2)}</span>
                        </div>
                    ))}
                    {!loading && services.length > 0 && <div className={s.groupLabel}>Servicios</div>}
                    {!loading && services.map((sv, i) => {
                        const idx = products.length + i;
                        return (
                            <div
                                key={`s-${sv.id}`}
                                role="option"
                                aria-selected={highlight === idx}
                                className={`${s.resultRow} ${highlight === idx ? s.resultRowActive : ""}`}
                                onMouseDown={() => select({ kind: "service", item: sv })}
                                onMouseEnter={() => setHighlight(idx)}
                            >
                                <span className={s.resultName}>{sv.name}</span>
                                <span className={s.resultPrice}>${Number(sv.base_price).toFixed(2)}</span>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
});

export default ProductSearch;
