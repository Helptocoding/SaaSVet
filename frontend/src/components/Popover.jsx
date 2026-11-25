import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import styles from "./Popover.module.css";

/**
 * Botón que abre un panel informativo junto a él (no un menú: para acciones,
 * ActionMenu). Se pinta en un portal con posición fija porque `.table-wrap`
 * recorta con `overflow: hidden`.
 *
 * Accesible: el botón lleva `aria-expanded` y `aria-controls`; el panel es un
 * `role="dialog"` con nombre. Se abre con clic, Enter o Espacio; Escape lo cierra
 * y devuelve el foco al botón; también se cierra con clic fuera, scroll o al
 * cambiar el tamaño de la ventana. Con el foco dentro, Tab recorre su contenido.
 *
 * Props:
 * - `label`: nombre accesible del panel (y del botón si no lleva `ariaLabel`).
 * - `trigger`: contenido visible del botón.
 * - `ariaLabel`: nombre accesible del botón cuando su texto no basta.
 * - `triggerClassName`: clases del botón.
 * - `children`: contenido del panel.
 */
export default function Popover({ label, trigger, ariaLabel, triggerClassName = "", children }) {
    const [open, setOpen] = useState(false);
    const [coords, setCoords] = useState(null);
    const triggerRef = useRef(null);
    const panelRef = useRef(null);
    const panelId = useId();

    const close = useCallback((restoreFocus) => {
        setOpen(false);
        setCoords(null);
        if (restoreFocus) triggerRef.current?.focus();
    }, []);

    const reposition = useCallback(() => {
        const trigger = triggerRef.current;
        const panel = panelRef.current;
        if (!trigger || !panel) return;
        const r = trigger.getBoundingClientRect();
        const height = panel.offsetHeight;
        const width = panel.offsetWidth;
        const placeAbove = window.innerHeight - r.bottom < height + 8 && r.top > height + 8;
        setCoords({
            top: placeAbove ? r.top - height - 6 : r.bottom + 6,
            left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)),
        });
    }, []);

    useLayoutEffect(() => {
        if (!open) return undefined;
        reposition();
        const onMove = () => close(false);
        window.addEventListener("scroll", onMove, true);
        window.addEventListener("resize", onMove);
        return () => {
            window.removeEventListener("scroll", onMove, true);
            window.removeEventListener("resize", onMove);
        };
    }, [open, reposition, close]);

    useEffect(() => {
        if (!open) return undefined;
        const onDown = (event) => {
            if (triggerRef.current?.contains(event.target)) return;
            if (panelRef.current?.contains(event.target)) return;
            close(false);
        };
        const onKey = (event) => {
            if (event.key === "Escape") {
                event.preventDefault();
                close(true);
            }
        };
        document.addEventListener("mousedown", onDown);
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("mousedown", onDown);
            document.removeEventListener("keydown", onKey);
        };
    }, [open, close]);

    return (
        <>
            <button
                ref={triggerRef}
                type="button"
                className={triggerClassName}
                aria-label={ariaLabel}
                aria-expanded={open}
                aria-controls={open ? panelId : undefined}
                onClick={() => (open ? close(false) : setOpen(true))}
            >
                {trigger}
            </button>
            {open && createPortal(
                <div
                    ref={panelRef}
                    id={panelId}
                    role="dialog"
                    aria-label={label}
                    className={styles.panel}
                    style={coords
                        ? { top: coords.top, left: coords.left }
                        : { top: 0, left: 0, visibility: "hidden" }}
                >
                    {children}
                </div>,
                document.body,
            )}
        </>
    );
}
