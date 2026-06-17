import { useMemo, useState } from "react";
import Pagination from "../../components/Pagination";
import { groupImportIssues } from "./groupImportIssues";
import s from "./imports.module.css";

const PAGE_SIZE = 25;

const num = (v) => Number(v || 0);

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

/* ── Grupo colapsable genérico ── */
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

/* ── Bloqueantes agrupados por tipo de problema ── */
const BlockingSummary = ({ items, labelByKey, open, onToggle }) => {
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
        <div className={s.collapseBlock}>
            <button
                className={s.collapseToggle}
                onClick={onToggle}
                aria-expanded={open}
            >
                <span className={s.collapseIcon}>✗</span>
                <span className={s.collapseLabel}>
                    No se pueden importar ({items.length})
                </span>
                <span className={s.collapseChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.collapseBody}>
                    <p className={s.blockingIntro}>
                        Necesitan corregirse en el archivo original antes de volver a subirlo.
                    </p>
                    {groups.map((g) => (
                        <GroupCard key={g.field} group={g} />
                    ))}
                </div>
            )}
        </div>
    );
};

/* ── Card de un tipo de problema (agrupado) ── */
const GroupCard = ({ group }) => {
    const [open, setOpen] = useState(false);
    const hasMore = group.count > group.samples.length;

    return (
        <div className={s.groupCard}>
            <button
                className={s.groupCardToggle}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
            >
                <span className={s.groupCardLabel}>
                    {group.label}
                </span>
                <span className={s.groupCardCount}>
                    Afecta {group.count} fila{group.count === 1 ? "" : "s"}
                </span>
                <span className={s.groupCardChevron}>{open ? "▲" : "▼"}</span>
            </button>
            <div className={s.groupCardAction}>
                ▶ Qué hacer: {group.action}
            </div>
            {open && (
                <div className={s.groupCardSamples}>
                    <div className={s.groupCardSamplesLabel}>
                        Ejemplo{group.samples.length === 1 ? "" : "s"}:
                    </div>
                    {group.samples.map((it) => (
                        <div key={it.row} className={s.sampleRow}>
                            <span className={s.sampleNum}>Fila #{it.row}</span>
                            <span className={s.sampleSep}>·</span>
                            <span className={s.sampleVal}>
                                {it.message}
                            </span>
                        </div>
                    ))}
                    {hasMore && (
                        <div className={s.sampleMore}>
                            ...y {group.count - group.samples.length} más
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

/* ── Advertencias agrupadas por tipo ── */
const WarningsSummary = ({ items, labelByKey }) => {
    const [open, setOpen] = useState(false);

    const groups = useMemo(
        () => groupImportIssues(items, labelByKey),
        [items, labelByKey],
    );

    if (groups.length === 0) return null;

    return (
        <div className={s.collapseBlock}>
            <button
                className={s.collapseToggle}
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
            >
                <span className={s.collapseIcon}>ℹ</span>
                <span className={s.collapseLabel}>
                    Se importarán con datos incompletos ({items.length})
                </span>
                <span className={s.collapseChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.collapseBody}>
                    <p className={s.warningsIntro}>
                        No bloquean la importación. Puedes completar estos datos después desde cada ficha.
                    </p>
                    {groups.map((g) => (
                        <GroupCard key={g.field} group={g} />
                    ))}
                </div>
            )}
        </div>
    );
};

/* Paso 3 — Vista previa (dry-run).
   Renderiza el `result` del validate con agrupación humana: posibles duplicados
   (match_confidence=high), conflictos de expediente (match_confidence=uncertain),
   filas que requieren corrección y avisos. Explica la consecuencia antes de
   confirmar. Bloquea el CTA si no hay nada importable. */
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

    // Separar conflictos por match_confidence
    const highConfidence = conflicts.filter((c) => c.match_confidence === "high");
    const uncertainConfidence = conflicts.filter((c) => c.match_confidence !== "high");

    const hasBlocking = blocking.length > 0;
    const hasImportable = createdPets > 0;
    const hasAnyIssue = conflicts.length > 0 || hasBlocking || warnings.length > 0;

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

            {/* ── Posibles duplicados (match_confidence = high) ── */}
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

            {/* ── Conflictos de expediente (match_confidence = uncertain) ── */}
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

            {blocking.length > 0 && (
                <BlockingSummary
                    items={blocking}
                    labelByKey={labelByKey}
                    open={openSections.blocking}
                    onToggle={() => toggle("blocking")}
                />
            )}

            <WarningsSummary items={warnings} labelByKey={labelByKey} />

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
                    {hasBlocking ? (
                        <span className={s.ctaBlocked}>
                            Corrige los {blocking.length} error{blocking.length === 1 ? "" : "es"} bloqueante{blocking.length === 1 ? "" : "s"} para poder importar.
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
