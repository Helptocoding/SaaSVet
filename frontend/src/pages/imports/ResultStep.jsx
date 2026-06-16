import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../../components/icons";
import s from "./imports.module.css";

const num = (v) => Number(v || 0);

// Datos OPCIONALES que faltaron en el archivo (warnings del backend). NO son
// errores: el registro se importó igual. Se resumen una vez aquí (estrategia C)
// para no convertirlos en una alerta global permanente.
const INCOMPLETE_LABELS = {
    "pet.species": "mascotas sin especie",
    "pet.birth_date": "mascotas sin fecha de nacimiento",
    "owner.phone": "clientes sin teléfono",
};
const INCOMPLETE_ORDER = ["pet.species", "pet.birth_date", "owner.phone"];

/* Paso 4 — Resultado de la importación (commit).
   Muestra los conteos reales de lo que se escribió + los errores que quedaron,
   con CTA para ir a ver los registros importados y reiniciar el wizard. */
const ResultStep = ({ result, job, fieldCatalog = [], onReset }) => {
    const navigate = useNavigate();

    const labelByKey = useMemo(() => {
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

    // Resumen de datos opcionales incompletos (estrategia C: una sola vez, aquí).
    const incompleteRows = useMemo(() => {
        const counts = {};
        for (const w of (r.warnings || [])) {
            if (w.field) counts[w.field] = (counts[w.field] || 0) + 1;
        }
        const keys = [...new Set([...INCOMPLETE_ORDER.filter(k => counts[k]), ...Object.keys(counts)])];
        return keys.map(field => ({
            field,
            count: counts[field],
            label: INCOMPLETE_LABELS[field] || `registros con "${field}" pendiente`,
        }));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [result]);

    return (
        <div>
            <div className="card" style={{ marginBottom: 18 }}>
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
                    <div className={s.sumCard}>
                        <div className={`${s.sumValue} ${s.sumValueSuccess}`}>{createdOwners}</div>
                        <div className={s.sumLabel}>Clientes creados</div>
                    </div>
                    <div className={s.sumCard}>
                        <div className={`${s.sumValue} ${s.sumValueSuccess}`}>{createdPets}</div>
                        <div className={s.sumLabel}>Mascotas creadas</div>
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

            {incompleteRows.length > 0 && (
                <div className="card" style={{ marginBottom: 18 }}>
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

            <div className={s.actions}>
                <button className="btn btn-secondary btn-md" onClick={onReset}>
                    Importar otro archivo
                </button>
                <div className={s.actionsRight}>
                    <button className="btn btn-primary btn-md" onClick={() => navigate("/pets")}>
                        Ver clientes y mascotas
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ResultStep;
