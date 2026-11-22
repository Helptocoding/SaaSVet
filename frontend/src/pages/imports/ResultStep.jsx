import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../../components/icons";
import { getEntityConfig } from "./entityConfig";
import s from "./imports.module.css";
import ConflictPages from "./ConflictPages";

const num = (v) => Number(v || 0);

/* Paso 4 — Resultado de la importación (commit).
   Muestra los conteos reales de lo que se escribió + los errores que quedaron,
   con CTA para ir a ver los registros importados y reiniciar el wizard.
   Los textos/tarjetas vienen de entityConfig (default = owner_pet). */
const ResultStep = ({ result, job, fieldCatalog = [], onReset, entityType = "owner_pet" }) => {
    const navigate = useNavigate();
    const cfg = getEntityConfig(entityType);

    const labelByKey = useMemo(() => {
        const m = { mapping: "Mapeo de columnas", owner: "Cliente", pet: "Mascota", row: "Fila" };
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);

    const r = result || {};
    const errors = r.errors || [];

    // Resumen de datos opcionales incompletos (estrategia C: una sola vez, aquí).
    const incompleteRows = useMemo(() => {
        const counts = {};
        for (const w of (r.warnings || [])) {
            if (w.field) counts[w.field] = (counts[w.field] || 0) + 1;
        }
        const keys = [...new Set([...cfg.incompleteOrder.filter(k => counts[k]), ...Object.keys(counts)])];
        return keys.map(field => ({
            field,
            count: counts[field],
            label: cfg.incompleteLabels[field] || `registros con "${field}" pendiente`,
        }));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [result]);

    return (
        <div>
            <div className="card" style={{ marginBottom: 16 }}>
                <div className={s.resultHero}>
                    <span className={s.resultIcon}>
                        <Icon.CheckCircle s={26} c="var(--c-success-text)" />
                    </span>
                    <div>
                        <div className={s.resultTitle}>Importación completada</div>
                        <div className={s.resultSub}>
                            {job?.original_filename ? `Archivo: ${job.original_filename}` : "Tus registros ya están en el sistema."}
                        </div>
                    </div>
                </div>

                <div className={s.summaryGrid}>
                    {cfg.summaryCards.map((card) => {
                        const value = num(r[card.valueKey]);
                        const toneClass =
                            card.tone === "success" ? s.sumValueSuccess
                            : card.tone === "warning" ? s.sumValueWarning
                            : card.tone === "danger" && value > 0 ? s.sumValueDanger
                            : "";
                        return (
                            <div className={s.sumCard} key={card.valueKey}>
                                <div className={`${s.sumValue} ${toneClass}`}>{value}</div>
                                <div className={s.sumLabel}>{card.label}</div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {incompleteRows.length > 0 && (
                <div className="card" style={{ marginBottom: 16 }}>
                    <p className={s.issuesTitle}>Datos opcionales pendientes</p>
                    <p className={s.resultSub} style={{ marginBottom: 12 }}>
                        Estos registros se importaron sin problema. No necesitas hacer nada ahora:
                        puedes completar estos datos cuando abras cada ficha.
                    </p>
                    <ul className={s.incompleteList}>
                        {incompleteRows.map(({ field, count, label }) => (
                            <li key={field}><strong>{count}</strong> {label}</li>
                        ))}
                    </ul>
                </div>
            )}

            {errors.length > 0 && (
                <div>
                    <p className={s.issuesTitle}>Filas que no se pudieron importar ({errors.length})</p>
                    <div className="table-wrap">
                        <table className="table">
                            <thead>
                                <tr>
                                    <th style={{ width: 80 }}>Fila</th>
                                    <th style={{ width: 220 }}>Campo</th>
                                    <th>Error</th>
                                </tr>
                            </thead>
                            <tbody>
                                {errors.map((it, i) => (
                                    <tr key={`${it.row}-${it.field}-${i}`}>
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
                </div>
            )}

            <ConflictPages key={r.conflict_report?.version} publicId={job?.public_id} report={r.conflict_report} highTotal={num(r.conflicts_high)} uncertainTotal={num(r.conflicts_uncertain)} cfg={cfg} />

            <div className={s.actions}>
                <button className="btn btn-secondary btn-md" onClick={onReset}>
                    Importar otro archivo
                </button>
                <div className={s.actionsRight}>
                    <button className="btn btn-primary btn-md" onClick={() => navigate(cfg.doneCta.path)}>
                        {cfg.doneCta.label}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ResultStep;
