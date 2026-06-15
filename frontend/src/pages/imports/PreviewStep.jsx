import { useMemo, useState } from "react";
import Pagination from "../../components/Pagination";
import s from "./imports.module.css";

const PAGE_SIZE = 25;

const num = (v) => Number(v || 0);

/* Lista paginada de incidencias (errores o advertencias) reportadas por el
   dry-run. Cada fila trae el número de fila del archivo, el campo (con su label
   amistoso del catálogo) y el mensaje. Reusa el paginador compartido. */
const IssuesTable = ({ title, items, labelByKey, tone }) => {
    const [page, setPage] = useState(1);
    if (!items || items.length === 0) return null;

    const start = (page - 1) * PAGE_SIZE;
    const slice = items.slice(start, start + PAGE_SIZE);

    return (
        <div style={{ marginTop: 8 }}>
            <p className={s.issuesTitle}>
                {title} ({items.length})
            </p>
            <div className="table-wrap">
                <table className="table">
                    <thead>
                        <tr>
                            <th style={{ width: 80 }}>Fila</th>
                            <th style={{ width: 220 }}>Campo</th>
                            <th>{tone === "error" ? "Error" : "Advertencia"}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {slice.map((it, i) => (
                            <tr key={`${it.row}-${it.field}-${start + i}`}>
                                <td className={s.rowNum}>{it.row != null ? `#${it.row}` : "—"}</td>
                                <td className={s.fieldLabel}>
                                    {it.field ? (labelByKey[it.field] || it.field) : "—"}
                                </td>
                                <td>{it.message}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <Pagination page={page} count={items.length} pageSize={PAGE_SIZE} onPage={setPage} />
        </div>
    );
};

/* Paso 3 — Vista previa (dry-run).
   Renderiza el `result` del validate: resumen de cuántos registros se crearán,
   cuántos duplicados se omitirán y cuántas filas tienen error, más el detalle
   de errores y advertencias. No escribe nada — solo informa. */
const PreviewStep = ({ result, fieldCatalog = [], onBack, onConfirm, committing, canCommit }) => {
    const labelByKey = useMemo(() => {
        // Fallbacks humanos para campos genéricos que no están en el catálogo
        // (errores a nivel fila/mapeo) — nunca mostrar el token técnico crudo.
        const m = { mapping: "Mapeo de columnas", owner: "Cliente", pet: "Mascota", row: "Fila" };
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);

    const r = result || {};
    const createdOwners = num(r.created_owners);
    const reusedOwners = num(r.reused_owners);
    const createdPets = num(r.created_pets);
    const skipped = num(r.skipped_duplicates);
    const errorRows = num(r.error_rows);
    const errors = r.errors || [];
    const warnings = r.warnings || [];

    return (
        <div>
            <div className="card" style={{ marginBottom: 18 }}>
                <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 3 }}>Revisa antes de importar</p>
                <p style={{ fontSize: 12.5, color: "var(--c-text-2)", marginBottom: 14 }}>
                    Esta es una simulación: todavía no se ha guardado nada. Revisa el
                    resumen y los avisos por fila antes de confirmar.
                </p>

                <p className={s.summaryLine}>
                    Se crearán <strong>{createdOwners} cliente{createdOwners === 1 ? "" : "s"}</strong> y{" "}
                    <strong>{createdPets} mascota{createdPets === 1 ? "" : "s"}</strong>
                    {reusedOwners > 0 && <> · {reusedOwners} cliente{reusedOwners === 1 ? "" : "s"} ya existente{reusedOwners === 1 ? "" : "s"} se reutilizará{reusedOwners === 1 ? "" : "n"}</>}
                    {" · "}{skipped} duplicado{skipped === 1 ? "" : "s"} se omitirá{skipped === 1 ? "" : "n"}
                    {" · "}{errorRows} fila{errorRows === 1 ? "" : "s"} con error
                </p>

                <div className={s.summaryGrid}>
                    <div className={s.sumCard}>
                        <div className={`${s.sumValue} ${s.sumValueSuccess}`}>{createdOwners}</div>
                        <div className={s.sumLabel}>Clientes nuevos</div>
                    </div>
                    <div className={s.sumCard}>
                        <div className={`${s.sumValue} ${s.sumValueSuccess}`}>{createdPets}</div>
                        <div className={s.sumLabel}>Mascotas nuevas</div>
                    </div>
                    <div className={s.sumCard}>
                        <div className={s.sumValue}>{reusedOwners}</div>
                        <div className={s.sumLabel}>Clientes reutilizados</div>
                    </div>
                    <div className={s.sumCard}>
                        <div className={`${s.sumValue} ${s.sumValueWarning}`}>{skipped}</div>
                        <div className={s.sumLabel}>Duplicados omitidos</div>
                    </div>
                    <div className={s.sumCard}>
                        <div className={`${s.sumValue} ${errorRows > 0 ? s.sumValueDanger : ""}`}>{errorRows}</div>
                        <div className={s.sumLabel}>Filas con error</div>
                    </div>
                </div>
            </div>

            <IssuesTable title="Errores" items={errors} labelByKey={labelByKey} tone="error" />
            <IssuesTable title="Advertencias" items={warnings} labelByKey={labelByKey} tone="warning" />

            {errors.length === 0 && warnings.length === 0 && (
                <div className="empty-state" style={{ padding: "32px 20px" }}>
                    <p className="empty-state-title">Sin errores ni advertencias.</p>
                    <p className="empty-state-sub">Tu archivo está listo para importar.</p>
                </div>
            )}

            <div className={s.actions}>
                <button className="btn btn-secondary btn-md" onClick={onBack} disabled={committing}>
                    Atrás
                </button>
                <div className={s.actionsRight}>
                    {canCommit ? (
                        <button
                            className="btn btn-primary btn-md"
                            onClick={onConfirm}
                            disabled={committing}
                        >
                            {committing ? "Importando..." : "Confirmar importación"}
                        </button>
                    ) : (
                        <span style={{ fontSize: 12.5, color: "var(--c-text-3)" }}>
                            No tienes permiso para confirmar la importación.
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
};

export default PreviewStep;
