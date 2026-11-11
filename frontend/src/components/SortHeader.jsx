import { Icon } from "./icons";

/**
 * Encabezado ordenable para la tabla global (`.table-wrap` + `.table`).
 * Patrón compartido (design-system.md §5 Tabla) — extraído del SortHeader
 * local de Inventario para no duplicar un tercer sorting por módulo.
 *
 * Props:
 *  - col / label: identificador y texto de la columna.
 *  - sortCol / sortDir: estado actual ("asc" | "desc").
 *  - onSort(col): el padre alterna columna/dirección.
 *  - align: "left" (default) | "right".
 */
export default function SortHeader({ col, label, sortCol, sortDir, onSort, align = "left" }) {
    const active = sortCol === col;
    const ArrowIcon = active ? (sortDir === "asc" ? Icon.ArrowUp : Icon.ArrowDown) : Icon.ArrowUpDown;
    return (
        <th
            className="th-sortable"
            style={{ textAlign: align }}
            onClick={() => onSort(col)}
            onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSort(col);
                }
            }}
            tabIndex={0}
            aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
        >
            <span className="th-inner">
                {label}
                <span className={`sort-arrow ${active ? "active" : ""}`}>
                    <ArrowIcon s={11} />
                </span>
            </span>
        </th>
    );
}
