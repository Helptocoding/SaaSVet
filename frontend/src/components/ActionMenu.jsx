import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icons";
import styles from "./ActionMenu.module.css";

/**
 * Menú contextual de acciones secundarias de una fila (Fase 1 Equipo).
 *
 * Botón de icono (⋯) que abre una lista `role="menu"`. Se pinta en un portal con
 * posición fija: `.table-wrap` recorta su contenido (`overflow: hidden`) y un
 * menú dentro de la celda quedaría cortado. Se reubica con el scroll y el
 * cambio de tamaño, y se abre hacia arriba si abajo no cabe.
 *
 * Teclado: Enter/Espacio/↓ abre y enfoca la primera opción; ↑/↓, Inicio y Fin
 * recorren; Escape cierra y devuelve el foco al botón; Tab cierra. Un clic fuera
 * también cierra.
 *
 * Props:
 * - `label`: nombre accesible del botón («Más acciones para Ana Galeno»).
 * - `items`: [{ id, label, onSelect, danger? }]. Sin opciones no se pinta nada.
 * - `disabled`: bloquea el botón (p. ej., otra acción en curso).
 * - `busy`: la acción de esta fila está en curso; muestra el indicador de carga.
 */
export default function ActionMenu({ label, items, disabled = false, busy = false }) {
    const [requestedOpen, setOpen] = useState(false);
    // Deshabilitado (otra acción empezó) nunca está abierto: se deriva en vez de
    // cerrarlo desde un efecto.
    const open = requestedOpen && !disabled;
    const [coords, setCoords] = useState(null);
    const triggerRef = useRef(null);
    const menuRef = useRef(null);
    const menuId = useId();

    const itemNodes = () => Array.from(menuRef.current?.querySelectorAll('[role="menuitem"]') || []);

    const close = useCallback((restoreFocus) => {
        setOpen(false);
        setCoords(null);
        if (restoreFocus) triggerRef.current?.focus();
    }, []);

    const reposition = useCallback(() => {
        const trigger = triggerRef.current;
        const menu = menuRef.current;
        if (!trigger || !menu) return;
        const r = trigger.getBoundingClientRect();
        const height = menu.offsetHeight;
        const width = menu.offsetWidth;
        const placeAbove = window.innerHeight - r.bottom < height + 8 && r.top > height + 8;
        setCoords({
            top: placeAbove ? r.top - height - 4 : r.bottom + 4,
            left: Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8)),
        });
    }, []);

    useLayoutEffect(() => {
        if (!open) return undefined;
        reposition();
        itemNodes()[0]?.focus();
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
            if (menuRef.current?.contains(event.target)) return;
            close(false);
        };
        document.addEventListener("mousedown", onDown);
        return () => document.removeEventListener("mousedown", onDown);
    }, [open, close]);

    if (!items || items.length === 0) return null;

    const onTriggerKeyDown = (event) => {
        if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
        }
    };

    const onMenuKeyDown = (event) => {
        const nodes = itemNodes();
        const index = nodes.indexOf(document.activeElement);
        const focusAt = (next) => nodes[(next + nodes.length) % nodes.length]?.focus();
        if (event.key === "Escape") { event.preventDefault(); close(true); }
        else if (event.key === "Tab") close(false);
        else if (event.key === "ArrowDown") { event.preventDefault(); focusAt(index + 1); }
        else if (event.key === "ArrowUp") { event.preventDefault(); focusAt(index - 1); }
        else if (event.key === "Home") { event.preventDefault(); focusAt(0); }
        else if (event.key === "End") { event.preventDefault(); focusAt(nodes.length - 1); }
    };

    const select = (item) => {
        close(true);
        item.onSelect();
    };

    return (
        <>
            <button
                ref={triggerRef}
                type="button"
                className="btn btn-ghost btn-sm btn-icon"
                aria-label={label}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-controls={open ? menuId : undefined}
                aria-busy={busy || undefined}
                disabled={disabled}
                onClick={() => (open ? close(false) : setOpen(true))}
                onKeyDown={onTriggerKeyDown}
            >
                {busy ? <Icon.Loader s={16} /> : <Icon.More s={16} />}
            </button>
            {open && createPortal(
                <div
                    ref={menuRef}
                    id={menuId}
                    role="menu"
                    aria-label={label}
                    className={styles.menu}
                    // Antes de medir se pinta fuera de la pantalla (no oculto: así la
                    // primera opción ya puede recibir el foco).
                    style={coords ? { top: coords.top, left: coords.left } : { top: -9999, left: -9999 }}
                    onKeyDown={onMenuKeyDown}
                >
                    {items.map((item) => (
                        <button
                            key={item.id}
                            type="button"
                            role="menuitem"
                            tabIndex={-1}
                            className={`${styles.item}${item.danger ? ` ${styles.danger}` : ""}`}
                            onClick={() => select(item)}
                        >
                            {item.label}
                        </button>
                    ))}
                </div>,
                document.body,
            )}
        </>
    );
}
