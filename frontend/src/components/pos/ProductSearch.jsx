import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { getPresentations, getPresentationByBarcode } from "../../api/inventory";
import { getServices } from "../../api/billing";
import PriceLabel from "../PriceLabel";
import s from "./pos.module.css";

const INITIAL_PRODUCTS = 6;
const INITIAL_SERVICES = 4;

const toList = (d) => (Array.isArray(d) ? d : d?.results || []);
const byProductName = (a, b) => `${a.product_name} ${a.name}`.localeCompare(`${b.product_name} ${b.name}`, "es", { sensitivity: "base" });
const byServiceName = (a, b) => a.name.localeCompare(b.name, "es", { sensitivity: "base" });

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
    const [productLimit, setProductLimit] = useState(INITIAL_PRODUCTS);
    const [serviceLimit, setServiceLimit] = useState(INITIAL_SERVICES);

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

    const visibleProducts = useMemo(() => products.slice(0, productLimit), [products, productLimit]);
    const visibleServices = useMemo(() => services.slice(0, serviceLimit), [services, serviceLimit]);
    const flat = useMemo(() => [
        ...visibleProducts.map(p => ({ kind: "product", item: p })),
        ...visibleServices.map(sv => ({ kind: "service", item: sv })),
    ], [visibleProducts, visibleServices]);
    const totalResults = products.length + services.length;
    const hasMoreResults = visibleProducts.length < products.length || visibleServices.length < services.length;

    const runSearch = (q) => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        const lower = q.trim().toLowerCase();
        if (!lower) {
            const cached = cacheRef.current;
            setProducts([...cached.products].sort(byProductName));
            setServices([...cached.services].sort(byServiceName));
            setProductLimit(INITIAL_PRODUCTS);
            setServiceLimit(INITIAL_SERVICES);
            setLoading(false);
            // Sin texto la lista es un catálogo para hojear. Si todavía no hay
            // catálogo (o está vacío) no se abre: un «Sin resultados» antes de
            // escribir nada responde una pregunta que nadie hizo (plan UX F1.6).
            setOpen(cached.products.length + cached.services.length > 0);
            setHighlight(-1);
            return;
        }
        setLoading(true);
        setOpen(true);
        setProductLimit(INITIAL_PRODUCTS);
        setServiceLimit(INITIAL_SERVICES);
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
                setProducts([...merged].sort(byProductName));
                setServices(svcs.filter(sv => sv.name?.toLowerCase().includes(lower)).sort(byServiceName));
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
        setProductLimit(INITIAL_PRODUCTS);
        setServiceLimit(INITIAL_SERVICES);
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
            <div className="searchBar" style={{ minHeight: 44, fontSize: 14 }}>
                <Search className="search-icon" size={17} strokeWidth={2.25} aria-hidden="true" />
                <input
                    ref={inputRef}
                    type="search"
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
            </div>
            {open && !disabled && (
                <div className={s.dropdown} role="listbox">
                    {loading && <div className={s.dropdownEmpty}>Buscando...</div>}
                    {!loading && flat.length === 0 && (
                        <div className={s.dropdownEmpty}>Sin resultados</div>
                    )}
                    {!loading && visibleProducts.length > 0 && <div className={s.groupLabel}>Productos</div>}
                    {!loading && visibleProducts.map((p, i) => (
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
                            <PriceLabel base={p.sale_price} withTax={p.sale_price_with_tax} className={s.resultPrice} />
                        </div>
                    ))}
                    {!loading && visibleServices.length > 0 && <div className={s.groupLabel}>Servicios</div>}
                    {!loading && visibleServices.map((sv, i) => {
                        const idx = visibleProducts.length + i;
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
                                <PriceLabel base={sv.base_price} withTax={sv.price_with_tax} className={s.resultPrice} />
                            </div>
                        );
                    })}
                    {!loading && hasMoreResults && (
                        <div className="search-results-footer">
                            <span className="search-result-count">Mostrando {flat.length} de {totalResults}</span>
                            <button
                                type="button"
                                className="search-load-more"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => {
                                    setProductLimit(limit => Math.min(limit + INITIAL_PRODUCTS, products.length));
                                    setServiceLimit(limit => Math.min(limit + INITIAL_SERVICES, services.length));
                                }}
                            >
                                Ver más
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
});

export default ProductSearch;
