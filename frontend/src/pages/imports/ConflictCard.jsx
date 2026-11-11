import s from "./imports.module.css";

// Tarjeta de un conflicto: lo que trae el archivo frente a lo ya registrado.
// La usan la muestra de la vista previa y el detalle paginado (ConflictPages).
export default function ConflictCard({ conflict, cfg }) {
    const c = cfg.conflict;
    const link = c.link ? c.link(conflict) : null;
    // Sin texto fijo para «por revisar» (inventario: puede ser por código o por nombre),
    // se muestra el motivo concreto que envía el servidor.
    const hint = conflict.match_confidence === "high"
        ? c.highText
        : (c.cardUncertainText || conflict.message || "");
    return (
        <div className={s.conflictCard}>
            <div className={s.conflictRow}>
                <span className={s.conflictNum}>Fila #{conflict.row}</span>
            </div>
            <div className={s.conflictCompare}>
                <div className={s.conflictSide}>
                    <div className={s.conflictSideLabel}>En tu archivo</div>
                    <div className={s.conflictSideValue}>
                        {conflict.incoming?.[c.incomingPrimaryKey] || "—"}
                    </div>
                    <div className={s.conflictSideMeta}>
                        {conflict.incoming?.[c.incomingSecondaryKey] || "—"}
                    </div>
                </div>
                <div className={s.conflictSide}>
                    <div className={s.conflictSideLabel}>Ya registrado</div>
                    <div className={s.conflictSideValue}>
                        {conflict.existing ? (c.existingPrimary(conflict.existing) || "—") : "—"}
                    </div>
                    <div className={s.conflictSideMeta}>
                        {conflict.existing ? (c.existingSecondary(conflict.existing) || "") : ""}
                    </div>
                </div>
            </div>
            <p className={s.conflictHint}>{hint}</p>
            {link && (
                <a href={link} target="_blank" rel="noopener noreferrer" className={s.conflictLink}>
                    {c.linkText}
                </a>
            )}
        </div>
    );
}
