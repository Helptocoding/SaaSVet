import Skeleton from "react-loading-skeleton";

/**
 * Tabla en carga: encabezados reales + filas de esqueleto, con la misma clase de
 * tabla que la página para que las columnas queden donde aparecerán los datos.
 *
 * Presentacional: no anuncia nada. El caller lo envuelve en su contenedor con
 * `role="status"` + `aria-label` (ver docs/modules/frontend.md § Esqueletos).
 *
 * columns: [{ label, align?, width?, cell?(rowIndex) }]
 *   - `width`: ancho del esqueleto de la celda (por defecto 80).
 *   - `cell`: render propio para celdas compuestas (avatar + nombre, pastillas…).
 */
const TableSkeleton = ({ columns, rows = 6, tableClassName = "table", tableStyle, wrap = true }) => {
    const table = (
        <table className={tableClassName} style={tableStyle} aria-hidden="true">
            <thead>
                <tr>
                    {columns.map((col, i) => (
                        <th key={i} style={col.align ? { textAlign: col.align } : undefined}>{col.label}</th>
                    ))}
                </tr>
            </thead>
            <tbody>
                {Array.from({ length: rows }, (_, row) => (
                    <tr key={row}>
                        {columns.map((col, i) => (
                            <td key={i} style={col.align ? { textAlign: col.align } : undefined}>
                                {col.cell ? col.cell(row) : <Skeleton width={col.width ?? 80} height={12} />}
                            </td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    );
    return wrap ? <div className="table-wrap">{table}</div> : table;
};

export default TableSkeleton;
