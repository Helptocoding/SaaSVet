import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";
import { Search, X } from "lucide-react";
import styles from "./SearchSelect.module.css";

const byLabel = (a, b) => String(a?.label ?? "").localeCompare(String(b?.label ?? ""), "es", { sensitivity: "base" });

export default function SearchSelect({
    id,
    name,
    value,
    onChange,
    onSearch,
    placeholder = "Buscar...",
    disabled = false,
    prefetchOnFocus = true,
    defaultQuery = "",
    maxSuggestions = 5,
}) {
    const autoId = useId();
    const inputId = id || `search-select-${autoId}`;
    const listboxId = `${inputId}-listbox`;
    const [inputVal, setInputVal]   = useState(value?.label ?? "");
    const [results,  setResults]    = useState([]);
    const [visibleCount, setVisibleCount] = useState(maxSuggestions);
    const [open,     setOpen]       = useState(false);
    const [loading,  setLoading]    = useState(false);

    const wrapperRef = useRef(null);
    const debounceRef = useRef(null);
    const reqId = useRef(0);
    const lastQueryRef = useRef(null);

    useEffect(() => {
        setInputVal(value?.label ?? "");
        if (!value) {
            setResults([]);
            setOpen(false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value?.id]);

    useEffect(() => {
        function handleMouseDown(e) {
            if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
                setOpen(false);
            }
        }
        document.addEventListener("mousedown", handleMouseDown);
        return () => document.removeEventListener("mousedown", handleMouseDown);
    }, []);

    function runSearch(q) {
        if (lastQueryRef.current === q && results.length > 0) {
            setVisibleCount(maxSuggestions);
            setOpen(true);
            return;
        }
        if (debounceRef.current) clearTimeout(debounceRef.current);

        setLoading(true);
        setOpen(true);
        setVisibleCount(maxSuggestions);

        debounceRef.current = setTimeout(() => {
            const id = ++reqId.current;
            onSearch(q)
                .then(data => {
                    if (reqId.current !== id) return;
                    setResults(Array.isArray(data) ? [...data].sort(byLabel) : []);
                    lastQueryRef.current = q;
                    setLoading(false);
                })
                .catch(() => {
                    if (reqId.current !== id) return;
                    toast.error("Error al buscar");
                    setResults([]);
                    lastQueryRef.current = null;
                    setLoading(false);
                });
        }, 250);
    }

    function handleInputChange(e) {
        const q = e.target.value;
        setInputVal(q);

        if (!q.trim()) {
            if (prefetchOnFocus) {
                runSearch(defaultQuery);
            } else {
                setResults([]);
                setOpen(false);
                setLoading(false);
            }
            return;
        }

        runSearch(q);
    }

    function handleSelect(item) {
        setInputVal(item.label);
        setResults([]);
        setVisibleCount(maxSuggestions);
        lastQueryRef.current = null;
        setOpen(false);
        onChange(item);
    }

    function handleClear(e) {
        e.stopPropagation();
        if (debounceRef.current) clearTimeout(debounceRef.current);
        reqId.current++;
        setInputVal("");
        setResults([]);
        setOpen(false);
        setLoading(false);
        onChange(null);
    }

    function handleKeyDown(e) {
        if (e.key === "Escape") setOpen(false);
    }

    function handleFocus() {
        if (disabled) return;
        if (prefetchOnFocus && results.length === 0 && !loading) {
            runSearch(defaultQuery);
            return;
        }
        if (results.length > 0) setOpen(true);
    }

    const showClear = !disabled && value !== null && value !== undefined;
    const visibleResults = results.slice(0, visibleCount);
    const hasMoreResults = results.length > visibleCount;

    return (
        <div ref={wrapperRef} className={styles.wrapper}>
            <div className="searchBar">
                <Search className="search-icon" size={15} strokeWidth={2.5} aria-hidden="true" />
                <input
                    type="search"
                    id={inputId}
                    name={name || inputId}
                    value={inputVal}
                    onChange={handleInputChange}
                    onKeyDown={handleKeyDown}
                    onFocus={handleFocus}
                    placeholder={placeholder}
                    disabled={disabled}
                    autoComplete="off"
                    role="combobox"
                    aria-expanded={open}
                    aria-controls={listboxId}
                />
                {showClear && (
                    <button
                        type="button"
                        onClick={handleClear}
                        className="search-clear"
                        aria-label="Limpiar selección"
                    >
                        <X size={15} strokeWidth={2} aria-hidden="true" />
                    </button>
                )}
            </div>

            {open && (
                <div
                    id={listboxId}
                    role="listbox"
                    className={`${styles.popover} result-popover`}
                >
                    {loading && (
                        <div className={styles.statusText}>
                            Buscando...
                        </div>
                    )}
                    {!loading && results.length === 0 && (
                        <div className={styles.statusText}>
                            Sin resultados
                        </div>
                    )}
                    {!loading && visibleResults.map((item, index) => (
                        <div
                            key={`${item.id ?? "no-id"}-${item.label ?? "no-label"}-${index}`}
                            onMouseDown={() => handleSelect(item)}
                            className={`${styles.item} result-popover-item`}
                        >
                            {item.label}
                        </div>
                    ))}
                    {!loading && hasMoreResults && (
                        <div className="search-results-footer">
                            <span className="search-result-count">Mostrando {visibleResults.length} de {results.length}</span>
                            <button
                                type="button"
                                className="search-load-more"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => setVisibleCount(count => Math.min(count + maxSuggestions, results.length))}
                            >
                                Ver más
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
