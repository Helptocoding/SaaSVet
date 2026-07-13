import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { DayPicker } from "react-day-picker";
import { es } from "react-day-picker/locale";
import "react-day-picker/style.css";
import "../styles/day-picker.css";
import { Icon } from "./icons";

/**
 * DateField — selector de fecha con calendario (estilo OriginUI: navegación por
 * selects de mes/año). Fuente única de captura de fechas en la app; reemplaza los
 * `<input type="date">` nativos para dar la misma UX en todos lados.
 *
 * - `value`/`onChange` en string ISO "YYYY-MM-DD" ("" cuando se limpia).
 * - `min`/`max` (string ISO | Date) limitan días seleccionables y el rango de años.
 * - Popover en **portal** con posición fija (no lo recorta el scroll del riel de
 *   consulta ni un modal). Se reubica al hacer scroll/resize y hace flip hacia
 *   arriba si no hay espacio abajo.
 */

const MONTHS = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

const POP_W = 300;
const POP_H = 352;

// "YYYY-MM-DD" → Date local (mediodía evita saltos por zona horaria).
const parseISO = (s) => (s ? new Date(`${s}T12:00:00`) : undefined);
const toISO = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const asDate = (v) => (v instanceof Date ? v : v ? parseISO(v) : undefined);

// Selects estilo referencia (OriginUI): sin relleno (transparente), solo borde
// fino + peso medio. Nada de la caja beige (--c-subtle) del tema.
const selectStyle = {
    background: "transparent", border: "1px solid var(--c-border)",
    borderRadius: "var(--r-md)", padding: "5px 8px",
    fontSize: "13px", fontFamily: "inherit", fontWeight: 500, color: "var(--c-text)",
    cursor: "pointer", outline: "none",
};

export default function DateField({
    value,
    onChange,
    min,
    max,
    disabled = false,
    placeholder = "Selecciona una fecha",
    clearable = false,
    id,
    className,
    inputClassName = "input",
}) {
    const [open, setOpen] = useState(false);
    const triggerRef = useRef(null);
    const popRef = useRef(null);

    const minDate = asDate(min);
    const maxDate = asDate(max);
    const selected = parseISO(value);
    const [month, setMonth] = useState(selected || maxDate || new Date());
    const [coords, setCoords] = useState({ top: 0, left: 0 });

    const reposition = useCallback(() => {
        const el = triggerRef.current;
        if (!el) return;
        const r = el.getBoundingClientRect();
        const spaceBelow = window.innerHeight - r.bottom;
        const placeAbove = spaceBelow < POP_H + 8 && r.top > POP_H + 8;
        const top = placeAbove ? r.top - POP_H - 4 : r.bottom + 4;
        const left = Math.max(8, Math.min(r.left, window.innerWidth - POP_W - 8));
        setCoords({ top, left });
    }, []);

    // Reubicar al abrir y mientras esté abierto (scroll interno vía capture).
    useLayoutEffect(() => {
        if (!open) return;
        reposition();
        const onScroll = () => reposition();
        window.addEventListener("scroll", onScroll, true);
        window.addEventListener("resize", onScroll);
        return () => {
            window.removeEventListener("scroll", onScroll, true);
            window.removeEventListener("resize", onScroll);
        };
    }, [open, reposition]);

    useEffect(() => {
        if (!open) return;
        const onDown = (e) => {
            if (triggerRef.current?.contains(e.target)) return;
            if (popRef.current?.contains(e.target)) return;
            setOpen(false);
        };
        document.addEventListener("mousedown", onDown);
        return () => document.removeEventListener("mousedown", onDown);
    }, [open]);

    const openPicker = () => {
        if (disabled) return;
        setMonth(selected || maxDate || new Date());
        setOpen((o) => !o);
    };

    const handleSelect = (date) => {
        if (!date) return;
        onChange(toISO(date));
        setOpen(false);
    };

    const displayValue = selected
        ? selected.toLocaleDateString("es-MX", { day: "numeric", month: "long", year: "numeric" })
        : "";

    const now = new Date();
    const endYear = maxDate ? maxDate.getFullYear() : now.getFullYear() + 5;
    const startYear = minDate
        ? minDate.getFullYear()
        : (maxDate ? maxDate.getFullYear() - 100 : now.getFullYear() - 1);
    const years = [];
    for (let y = endYear; y >= startYear; y--) years.push(y);

    // Array de matchers (NO un solo `{before, after}`: eso es DateInterval y
    // deshabilitaría el rango ENTRE ambas). Queremos: antes de min O después de max.
    const disabledMatchers = [];
    if (minDate) disabledMatchers.push({ before: minDate });
    if (maxDate) disabledMatchers.push({ after: maxDate });

    return (
        <div ref={triggerRef} className={className} style={{ position: "relative" }}>
            <input
                id={id}
                className={inputClassName}
                readOnly
                value={displayValue}
                placeholder={placeholder}
                disabled={disabled}
                onClick={openPicker}
                style={{ cursor: disabled ? "default" : "pointer", paddingRight: clearable && value ? 30 : undefined }}
            />
            {clearable && value && !disabled && (
                <button
                    type="button"
                    aria-label="Limpiar fecha"
                    onClick={() => onChange("")}
                    style={{
                        position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
                        background: "none", border: "none", cursor: "pointer", color: "var(--c-text-3)",
                        padding: 2, display: "flex", alignItems: "center",
                    }}
                >
                    <Icon.X s={13} />
                </button>
            )}
            {open && !disabled && createPortal(
                <div
                    ref={popRef}
                    style={{ position: "fixed", top: coords.top, left: coords.left, zIndex: 1100 }}
                >
                    <div style={{
                        background: "var(--c-surface)", borderRadius: "var(--r-lg)",
                        border: "1px solid var(--c-border)", boxShadow: "var(--shadow-md)",
                        padding: 12, width: POP_W,
                    }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                            <select
                                aria-label="Mes"
                                value={month.getMonth()}
                                onChange={(e) => setMonth(new Date(month.getFullYear(), Number(e.target.value), 1))}
                                style={{ ...selectStyle, flex: 1 }}
                            >
                                {MONTHS.map((m, i) => <option key={i} value={i}>{m}</option>)}
                            </select>
                            <select
                                aria-label="Año"
                                value={month.getFullYear()}
                                onChange={(e) => setMonth(new Date(Number(e.target.value), month.getMonth(), 1))}
                                style={{ ...selectStyle, width: 92 }}
                            >
                                {years.map((y) => <option key={y} value={y}>{y}</option>)}
                            </select>
                        </div>
                        <DayPicker
                            mode="single"
                            selected={selected}
                            onSelect={handleSelect}
                            disabled={disabledMatchers.length ? disabledMatchers : undefined}
                            month={month}
                            onMonthChange={setMonth}
                            locale={es}
                            hideNavigation
                            components={{ MonthCaption: () => null }}
                        />
                    </div>
                </div>,
                document.body,
            )}
        </div>
    );
}
