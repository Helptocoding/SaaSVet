import { useMemo, useState } from "react";
import Pagination from "../../components/Pagination";
import s from "./imports.module.css";

const PAGE_SIZE = 25;

const num = (v) => Number(v || 0);

/* ── Sección colapsable para conflictos (posibles duplicados por expediente) ── */
const ConflictGroup = ({ conflicts, onToggle, open }) => {
    const [page, setPage] = useState(1);
    const start = (page - 1) * PAGE_SIZE;
    const slice = conflicts.slice(start, start + PAGE_SIZE);

    return (
        <div className={s.collapseBlock}>
            <button
                className={s.collapseToggle}
                onClick={onToggle}
                aria-expanded={open}
            >
                <span className={s.collapseIcon}>⚠</span>
                <span className={s.collapseLabel}>
                    Posibles duplicados ({conflicts.length})
                </span>
                <span className={s.collapseChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.collapseBody}>
                    <p className={s.conflictIntro}>
                        Puede que estos pacientes ya estén registrados. Suele pasar si este
                        archivo ya se importó antes.
                    </p>
                    {slice.map((c, i) => (
                        <div key={`${c.row}-${i}`} className={s.conflictCard}>
                            <div className={s.conflictRow}>
                                <span className={s.conflictNum}>Fila #{c.row}</span>
                            </div>
                            <div className={s.conflictCompare}>
                                <div className={s.conflictSide}>
                                    <div className={s.conflictSideLabel}>En tu archivo</div>
                                    <div className={s.conflictSideValue}>
                                        {c.incoming?.pet_name || "—"}
                                    </div>
                                    <div className={s.conflictSideMeta}>
                                        {c.incoming?.owner_name || "—"}
                                    </div>
                                </div>
                                <div className={s.conflictSide}>
                                    <div className={s.conflictSideLabel}>Ya registrado</div>
                                    <div className={s.conflictSideValue}>
                                        {c.existing?.pet_name || "—"}
                                    </div>
                                    <div className={s.conflictSideMeta}>
                                        {c.existing?.owner_name || "—"}
                                    </div>
                                </div>
                            </div>
                            <p className={s.conflictHint}>
                                {c.match_confidence === "high"
                                    ? "Parece el mismo paciente."
                                    : "Mismo expediente, datos distintos — revísalo."}
                            </p>
                            {c.existing?.public_id && (
                                <a
                                    href={`/pets/${c.existing.public_id}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className={s.conflictLink}
                                >
                                    Ver paciente
                                </a>
                            )}
                        </div>
                    ))}
                    <Pagination
                        page={page}
                        count={conflicts.length}
                        pageSize={PAGE_SIZE}
                        onPage={setPage}
                    />
                </div>
            )}
        </div>
    );
};

/* ── Sección colapsable para bloqueantes (faltan datos) ── */
const BlockingGroup = ({ items, labelByKey, onToggle, open }) => {
    const [page, setPage] = useState(1);
    const start = (page - 1) * PAGE_SIZE;
    const slice = items.slice(start, start + PAGE_SIZE);

    return (
        <div className={s.collapseBlock}>
            <button
                className={s.collapseToggle}
                onClick={onToggle}
                aria-expanded={open}
            >
                <span className={s.collapseIcon}>✗</span>
                <span className={s.collapseLabel}>
                    Requieren corrección ({items.length})
                </span>
                <span className={s.collapseChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.collapseBody}>
                    {slice.map((it, i) => (
                        <div key={`${it.row}-${it.field}-${i}`} className={s.blockingRow}>
                            <span className={s.blockingNum}>#{it.row}</span>
                            <span className={s.blockingField}>
                                {it.field ? (labelByKey[it.field] || it.field) : "—"}
                            </span>
                            <span className={s.blockingMsg}>{it.message}</span>
                        </div>
                    ))}
                    <Pagination
                        page={page}
                        count={items.length}
                        pageSize={PAGE_SIZE}
                        onPage={setPage}
                    />
                </div>
            )}
        </div>
    );
};

/* ── Tabla de advertencias (datos opcionales faltantes) ── */
const WarningsTable = ({ items, labelByKey }) => {
    const [page, setPage] = useState(1);
    if (!items || items.length === 0) return null;
    const start = (page - 1) * PAGE_SIZE;
    const slice = items.slice(start, start + PAGE_SIZE);

    return (
        <div className={s.collapseBlock}>
            <div className={s.warningsHeader}>
                <span className={s.collapseIcon}>ℹ</span>
                <span className={s.collapseLabel}>
                    Avisos ({items.length})
                </span>
            </div>
            <div className={s.collapseBody}>
                {slice.map((it, i) => (
                    <div key={`${it.row}-${it.field}-${start + i}`} className={s.blockingRow}>
                        <span className={s.blockingNum}>#{it.row}</span>
                        <span className={s.blockingField}>
                            {it.field ? (labelByKey[it.field] || it.field) : "—"}
                        </span>
                        <span className={s.blockingMsg}>{it.message}</span>
                    </div>
                ))}
                <Pagination
                    page={page}
                    count={items.length}
                    pageSize={PAGE_SIZE}
                    onPage={setPage}
                />
            </div>
        </div>
    );
};

/* Paso 3 — Vista previa (dry-run).
   Renderiza el `result` del validate con agrupación humana: posibles duplicados,
   filas que requieren corrección y avisos. Explica la consecuencia antes de
   confirmar. Bloquea el CTA si no hay nada importable. */
const PreviewStep = ({ result, fieldCatalog = [], onBack, onConfirm, committing, canCommit }) => {
    const labelByKey = useMemo(() => {
        const m = { mapping: "Mapeo de columnas", owner: "Cliente", pet: "Mascota", row: "Fila" };
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);

    const [openSections, setOpenSections] = useState({ conflicts: true, blocking: true });

    const r = result || {};
    const createdPets = num(r.created_pets);
    const createdOwners = num(r.created_owners);
    const reusedOwners = num(r.reused_owners);
    const skippedDups = num(r.skipped_duplicates);
    const skippedConflicts = num(r.skipped_conflicts);
    const blockingRows = num(r.blocking_rows);
    const conflicts = r.conflicts || [];
    const blocking = r.blocking || r.errors || [];
    const warnings = r.warnings || [];

    const hasImportable = createdPets > 0;
    const hasAnyIssue = conflicts.length > 0 || blocking.length > 0 || warnings.length > 0;

    const toggle = (section) =>
        setOpenSections((prev) => ({ ...prev, [section]: !prev[section] }));

    return (
        <div>
            {/* ── Resumen humano ── */}
            <div className="card" style={{ marginBottom: 18 }}>
                <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 3 }}>
                    Revisa antes de importar
                </p>
                <p style={{ fontSize: 12.5, color: "var(--c-text-2)", marginBottom: 14 }}>
                    Esta es una simulación: todavía no se ha guardado nada.
                </p>

                <div className={s.humanSummary}>
                    {createdPets > 0 && (
                        <div className={`${s.humanRow} ${s.humanRowSuccess}`}>
                            <span className={s.humanBullet}>✓</span>
                            {createdPets} paciente{createdPets === 1 ? "" : "s"} listo{createdPets === 1 ? "" : "s"} para importar
                            {createdOwners > 0 && (
                                <span className={s.humanExtra}>
                                    {" · "}{createdOwners} cliente{createdOwners === 1 ? "" : "s"} nuevo{createdOwners === 1 ? "" : "s"}
                                </span>
                            )}
                            {reusedOwners > 0 && (
                                <span className={s.humanExtra}>
                                    {" · "}{reusedOwners} reutilizado{reusedOwners === 1 ? "" : "s"}
                                </span>
                            )}
                        </div>
                    )}
                    {skippedDups > 0 && (
                        <div className={`${s.humanRow} ${s.humanRowMuted}`}>
                            <span className={s.humanBullet}>⊘</span>
                            {skippedDups} duplicado{skippedDups === 1 ? "" : "s"} se omitirá{skippedDups === 1 ? "" : "n"}
                        </div>
                    )}
                    {skippedConflicts > 0 && (
                        <div className={`${s.humanRow} ${s.humanRowWarn}`}>
                            <span className={s.humanBullet}>⚠</span>
                            {skippedConflicts} necesitan revisión (posibles duplicados)
                        </div>
                    )}
                    {blockingRows > 0 && (
                        <div className={`${s.humanRow} ${s.humanRowDanger}`}>
                            <span className={s.humanBullet}>✗</span>
                            {blockingRows} no se pueden importar (faltan datos)
                        </div>
                    )}
                    {!hasAnyIssue && createdPets === 0 && (
                        <div className={`${s.humanRow} ${s.humanRowMuted}`}>
                            No se encontraron registros para importar.
                        </div>
                    )}
                </div>
            </div>

            {/* ── Grupos colapsables ── */}
            {conflicts.length > 0 && (
                <ConflictGroup
                    conflicts={conflicts}
                    open={openSections.conflicts}
                    onToggle={() => toggle("conflicts")}
                />
            )}

            {blocking.length > 0 && (
                <BlockingGroup
                    items={blocking}
                    labelByKey={labelByKey}
                    open={openSections.blocking}
                    onToggle={() => toggle("blocking")}
                />
            )}

            <WarningsTable items={warnings} labelByKey={labelByKey} />

            {!hasAnyIssue && (
                <div className="empty-state" style={{ padding: "32px 20px" }}>
                    <p className="empty-state-title">Sin errores ni advertencias.</p>
                    <p className="empty-state-sub">Tu archivo está listo para importar.</p>
                </div>
            )}

            {/* ── Consecuencia + CTA ── */}
            <div className={s.actions}>
                <button className="btn btn-secondary btn-md" onClick={onBack} disabled={committing}>
                    Atrás
                </button>
                <div className={s.actionsRight}>
                    {hasImportable && canCommit ? (
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
                            <p className={s.consequence}>
                                Al continuar: ✓ se importarán {createdPets} registro{createdPets === 1 ? "" : "s"}
                                {skippedConflicts > 0 && <>{" · "}⚠ {skippedConflicts} posibles duplicados se omitirán</>}
                                {skippedDups > 0 && <>{" · "}⊘ {skippedDups} duplicados se omitirán</>}
                            </p>
                            <button
                                className="btn btn-primary btn-md"
                                onClick={onConfirm}
                                disabled={committing}
                            >
                                {committing ? "Importando..." : "Confirmar importación"}
                            </button>
                        </div>
                    ) : hasImportable && !canCommit ? (
                        <span style={{ fontSize: 12.5, color: "var(--c-text-3)" }}>
                            No tienes permiso para confirmar la importación.
                        </span>
                    ) : (
                        <span style={{ fontSize: 12.5, color: "var(--c-text-3)" }}>
                            Corrige los errores para poder importar.
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
};

export default PreviewStep;
