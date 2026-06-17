import { useMemo, useState } from "react";
import Pagination from "../../components/Pagination";
import { groupImportIssues } from "./groupImportIssues";
import s from "./imports.module.css";

const PAGE_SIZE = 25;

const num = (v) => Number(v || 0);

const CSV_ACTIONS = {
    "pet.name": "Agrega el nombre de la mascota en la columna correspondiente de tu archivo.",
    "owner.name": "Agrega el nombre del cliente en la columna correspondiente de tu archivo.",
    "owner.phone": "Corrige el teléfono: deben ser exactamente 10 dígitos, o deja la celda vacía.",
    "pet.species": "La especie no se reconoció. Puedes completarla después desde la ficha.",
    "pet.birth_date": "La fecha no tiene un formato válido. Puedes corregirla o completarla después.",
};

function buildCsv(items, labelByKey) {
    const BOM = "\uFEFF";
    const header = "Fila,Campo,Error,Qué hacer\n";
    const rows = items.map((it) => {
        const label = labelByKey[it.field] || it.field || "";
        const action = CSV_ACTIONS[it.field] || "";
        const msg = (it.message || "").replace(/"/g, '""');
        return `${it.row},"${label}","${msg}","${action}"`;
    });
    return BOM + header + rows.join("\n");
}

function downloadCsv(items, labelByKey, filename) {
    const csv = buildCsv(items, labelByKey);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

/* ── Card de conflicto individual (reusada por ambos grupos) ── */
const ConflictCard = ({ conflict }) => (
    <div className={s.conflictCard}>
        <div className={s.conflictRow}>
            <span className={s.conflictNum}>Fila #{conflict.row}</span>
        </div>
        <div className={s.conflictCompare}>
            <div className={s.conflictSide}>
                <div className={s.conflictSideLabel}>En tu archivo</div>
                <div className={s.conflictSideValue}>
                    {conflict.incoming?.pet_name || "—"}
                </div>
                <div className={s.conflictSideMeta}>
                    {conflict.incoming?.owner_name || "—"}
                </div>
            </div>
            <div className={s.conflictSide}>
                <div className={s.conflictSideLabel}>Ya registrado</div>
                <div className={s.conflictSideValue}>
                    {conflict.existing?.pet_name || "—"}
                </div>
                <div className={s.conflictSideMeta}>
                    {conflict.existing?.owner_name || "—"}
                </div>
            </div>
        </div>
        <p className={s.conflictHint}>
            {conflict.match_confidence === "high"
                ? "Parece el mismo paciente."
                : "El número de expediente ya pertenece a otro paciente."}
        </p>
        {conflict.existing?.public_id && (
            <a
                href={`/pets/${conflict.existing.public_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className={s.conflictLink}
            >
                Ver paciente
            </a>
        )}
    </div>
);

/* ── Grupo colapsable genérico (conflictos) ── */
const CollapseGroup = ({ icon, title, count, intro, items, open, onToggle, variant }) => {
    const [page, setPage] = useState(1);
    const start = (page - 1) * PAGE_SIZE;
    const slice = items.slice(start, start + PAGE_SIZE);

    const variantClass = variant ? s[`collapseBlock${variant}`] : "";

    return (
        <div className={`${s.collapseBlock} ${variantClass}`}>
            <button
                className={s.collapseToggle}
                onClick={onToggle}
                aria-expanded={open}
            >
                <span className={s.collapseIcon}>{icon}</span>
                <span className={s.collapseLabel}>
                    {title} ({count})
                </span>
                <span className={s.collapseChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.collapseBody}>
                    {intro && <p className={s.conflictIntro}>{intro}</p>}
                    {slice.map((c, i) => (
                        <ConflictCard key={`${c.row}-${i}`} conflict={c} />
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

/* ── Checklist de errores bloqueantes (tipo GitHub checks) ── */
const BlockingChecklist = ({ items, labelByKey, open, onToggle }) => {
    const actionsByField = {
        "pet.name": `Agrega el nombre en la columna asignada como ${labelByKey["pet.name"] || "Nombre de la mascota"}.`,
        "owner.name": `Agrega el nombre en la columna asignada como ${labelByKey["owner.name"] || "Nombre del cliente"}.`,
        "owner.phone": "Corrige el teléfono: deben ser 10 dígitos, o deja la celda vacía.",
    };

    const groups = useMemo(
        () => groupImportIssues(items, labelByKey, actionsByField),
        [items, labelByKey],
    );

    if (groups.length === 0) return null;

    return (
        <div className={s.section}>
            <button
                className={s.sectionToggle}
                onClick={onToggle}
                aria-expanded={open}
            >
                <span className={s.sectionIcon + " " + s.iconDanger}>!</span>
                <span className={s.sectionLabel}>
                    Necesitan corrección ({items.length})
                </span>
                <span className={s.sectionChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.checklistBody}>
                    <div className={s.checklistHint}>
                        Corrige estos datos en tu archivo y vuelve a subirlo.
                    </div>
                    {groups.map((g) => (
                        <ChecklistItem key={g.field} group={g} />
                    ))}
                </div>
            )}
        </div>
    );
};

/* ── Item de checklist (un tipo de problema) ── */
const ChecklistItem = ({ group }) => {
    const [open, setOpen] = useState(false);
    const hasMore = group.count > group.samples.length;

    return (
        <div className={s.checklistItem}>
            <button
                className={s.checklistToggle}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
            >
                <span className={s.checklistBullet} />
                <span className={s.checklistName}>{group.label}</span>
                <span className={s.checklistCount}>{group.count} fila{group.count === 1 ? "" : "s"}</span>
                <span className={s.checklistArrow}>{open ? "▾" : "▸"}</span>
            </button>
            <div className={s.checklistAction}>
                {group.action}
            </div>
            {open && (
                <div className={s.checklistSamples}>
                    {group.samples.map((it) => (
                        <div key={it.row} className={s.checklistSampleRow}>
                            <span className={s.checklistSampleNum}>#{it.row}</span>
                            <span className={s.checklistSampleMsg}>{it.message}</span>
                        </div>
                    ))}
                    {hasMore && (
                        <div className={s.checklistMore}>
                            …y {group.count - group.samples.length} más
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

/* ── Advertencias ultra-ligeras ── */
const WarningsLight = ({ items, labelByKey }) => {
    const [open, setOpen] = useState(false);

    const groups = useMemo(
        () => groupImportIssues(items, labelByKey),
        [items, labelByKey],
    );

    if (groups.length === 0) return null;

    return (
        <div className={s.section + " " + s.sectionMuted}>
            <button
                className={s.sectionToggle}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
            >
                <span className={s.sectionIcon + " " + s.iconInfo}>ℹ</span>
                <span className={s.sectionLabel}>
                    Se importarán con datos incompletos ({items.length})
                </span>
                <span className={s.sectionChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.warningsList}>
                    {groups.map((g) => (
                        <div key={g.field} className={s.warningItem}>
                            <span className={s.warningBullet}>○</span>
                            <span className={s.warningText}>
                                {g.label} ({g.count})
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

/* Paso 3 — Vista previa (dry-run) */
const PreviewStep = ({ result, fieldCatalog = [], onBack, onConfirm, committing, canCommit }) => {
    const labelByKey = useMemo(() => {
        const m = { mapping: "Mapeo de columnas", owner: "Cliente", pet: "Mascota", row: "Fila" };
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);

    const [openSections, setOpenSections] = useState({
        duplicates: true,
        expedientConflicts: true,
        blocking: true,
    });

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

    const highConfidence = conflicts.filter((c) => c.match_confidence === "high");
    const uncertainConfidence = conflicts.filter((c) => c.match_confidence !== "high");

    const hasBlocking = blocking.length > 0;
    const hasImportable = createdPets > 0;
    const hasAnyIssue = conflicts.length > 0 || hasBlocking || warnings.length > 0;

    const toggle = (section) =>
        setOpenSections((prev) => ({ ...prev, [section]: !prev[section] }));

    const totalOwners = createdOwners + reusedOwners;

    return (
        <div>
            {/* ── Barra de estado horizontal ── */}
            <div className={s.statusBar}>
                <div className={s.statusBarTitle}>
                    Revisa antes de importar
                </div>
                <div className={s.statusBarSub}>
                    Esta es una simulación — todavía no se ha guardado nada.
                </div>
                <div className={s.statusPills}>
                    {createdPets > 0 && (
                        <div className={`${s.statusPill} ${s.pillSuccess}`}>
                            <span className={s.pillIcon}>✓</span>
                            {createdPets} paciente{createdPets === 1 ? "" : "s"} listo{createdPets === 1 ? "" : "s"}
                            {totalOwners > 0 && (
                                <span className={s.pillExtra}>
                                    {" · "}{totalOwners} cliente{totalOwners === 1 ? "" : "s"}
                                </span>
                            )}
                        </div>
                    )}
                    {skippedDups > 0 && (
                        <div className={`${s.statusPill} ${s.pillMuted}`}>
                            <span className={s.pillIcon}>⊘</span>
                            {skippedDups} omitido{skippedDups === 1 ? "" : "s"}
                        </div>
                    )}
                    {skippedConflicts > 0 && (
                        <div className={`${s.statusPill} ${s.pillWarn}`}>
                            <span className={s.pillIcon}>⚠</span>
                            {skippedConflicts} en revisión
                        </div>
                    )}
                    {hasBlocking && (
                        <div className={`${s.statusPill} ${s.pillDanger}`}>
                            <span className={s.pillIcon}>!</span>
                            {blockingRows} necesitan corrección
                        </div>
                    )}
                    {warnings.length > 0 && (
                        <div className={`${s.statusPill} ${s.pillInfo}`}>
                            <span className={s.pillIcon}>ℹ</span>
                            {warnings.length} con datos incompletos
                        </div>
                    )}
                    {!hasAnyIssue && createdPets === 0 && (
                        <div className={`${s.statusPill} ${s.pillMuted}`}>
                            No se encontraron registros para importar.
                        </div>
                    )}
                </div>
            </div>

            {/* ── Posibles duplicados ── */}
            {highConfidence.length > 0 && (
                <CollapseGroup
                    icon="⚠"
                    title="Posibles duplicados"
                    count={highConfidence.length}
                    intro="Puede que estos pacientes ya estén registrados. Suele pasar si este archivo ya se importó antes."
                    items={highConfidence}
                    open={openSections.duplicates}
                    onToggle={() => toggle("duplicates")}
                />
            )}

            {/* ── Conflictos de expediente ── */}
            {uncertainConfidence.length > 0 && (
                <CollapseGroup
                    icon="⚡"
                    title="Conflictos de expediente"
                    count={uncertainConfidence.length}
                    intro={
                        "El número de expediente ya pertenece a otro paciente.\n\n"
                        + "Puede pasar si:\n"
                        + "· estás importando información de otra clínica.\n"
                        + "· el sistema anterior reinició numeraciones.\n"
                        + "· la columna seleccionada no corresponde al expediente."
                    }
                    items={uncertainConfidence}
                    open={openSections.expedientConflicts}
                    onToggle={() => toggle("expedientConflicts")}
                    variant="Warn"
                />
            )}

            {/* ── Errores bloqueantes (checklist) ── */}
            {blocking.length > 0 && (
                <BlockingChecklist
                    items={blocking}
                    labelByKey={labelByKey}
                    open={openSections.blocking}
                    onToggle={() => toggle("blocking")}
                />
            )}

            {/* ── Advertencias ── */}
            <WarningsLight items={warnings} labelByKey={labelByKey} />

            {/* ── Descarga CSV ── */}
            {(blocking.length > 0 || warnings.length > 0) && (
                <div style={{ marginBottom: 14 }}>
                    <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                            const all = [...blocking, ...warnings].sort((a, b) => a.row - b.row);
                            downloadCsv(all, labelByKey, "filas-con-problemas.csv");
                        }}
                    >
                        ⬇ Descargar filas con problemas (CSV)
                    </button>
                </div>
            )}

            {!hasAnyIssue && (
                <div className="empty-state" style={{ padding: "32px 20px" }}>
                    <p className="empty-state-title">Sin errores ni advertencias.</p>
                    <p className="empty-state-sub">Tu archivo está listo para importar.</p>
                </div>
            )}

            {/* ── CTA ── */}
            <div className={s.actions}>
                <button className="btn btn-secondary btn-md" onClick={onBack} disabled={committing}>
                    Atrás
                </button>
                <div className={s.actionsRight}>
                    {hasBlocking ? (
                        <span className={s.ctaBlocked}>
                            Corrige los {blocking.length} error{blocking.length === 1 ? "" : "es"} para poder importar.
                        </span>
                    ) : hasImportable && canCommit ? (
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
                            No hay registros nuevos para importar.
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
};

export default PreviewStep;
