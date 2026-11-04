import { useMemo, useState, useEffect } from "react";
import Pagination from "../../components/Pagination";
import { groupImportIssues } from "./groupImportIssues";
import { getEntityConfig } from "./entityConfig";
import s from "./imports.module.css";
import ConflictPages from "./ConflictPages";

const PAGE_SIZE = 25;

// Coerción robusta a número: nunca enmascara un 0 legítimo ni propaga NaN.
const num = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
};

function buildCsv(items, labelByKey, csvActions) {
    const BOM = "\uFEFF";
    const header = "Fila,Campo,Error,Qué hacer\n";
    const rows = items.map((it) => {
        const label = labelByKey[it.field] || it.field || "";
        const action = csvActions[it.field] || "";
        const msg = (it.message || "").replace(/"/g, '""');
        return `${it.row},"${label}","${msg}","${action}"`;
    });
    return BOM + header + rows.join("\n");
}

function downloadCsv(items, labelByKey, filename, csvActions) {
    const csv = buildCsv(items, labelByKey, csvActions);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

/* ── Card de conflicto individual ── */
const ConflictCard = ({ conflict, cfg }) => {
    const c = cfg.conflict;
    const link = c.link ? c.link(conflict) : null;
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
                        {conflict.existing ? c.existingPrimary(conflict.existing) : "—"}
                    </div>
                    <div className={s.conflictSideMeta}>
                        {conflict.existing ? (c.existingSecondary(conflict.existing) || "") : ""}
                    </div>
                </div>
            </div>
            <p className={s.conflictHint}>
                {conflict.match_confidence === "high" ? c.highText : c.cardUncertainText}
            </p>
            {link && (
                <a href={link} target="_blank" rel="noopener noreferrer" className={s.conflictLink}>
                    {c.linkText}
                </a>
            )}
        </div>
    );
};

/* ── Grupo colapsable genérico (conflictos) ── */
const CollapseGroup = ({ icon, title, count, intro, items, open, onToggle, variant }) => {
    const [page, setPage] = useState(1);
    const start = (page - 1) * PAGE_SIZE;
    const slice = items.slice(start, start + PAGE_SIZE);
    const variantClass = variant ? s[`collapseBlock${variant}`] : "";

    return (
        <div className={`${s.collapseBlock} ${variantClass}`}>
            <button className={s.collapseToggle} onClick={onToggle} aria-expanded={open}>
                <span className={s.collapseIcon}>{icon}</span>
                <span className={s.collapseLabel}>{title} ({count})</span>
                <span className={s.collapseChevron}>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <div className={s.collapseBody}>
                    {intro && <p className={s.conflictIntro}>{intro}</p>}
                    {slice.map((c, i) => <ConflictCard key={`${c.row}-${i}`} conflict={c} />)}
                    <Pagination page={page} count={items.length} pageSize={PAGE_SIZE} onPage={setPage} />
                </div>
            )}
        </div>
    );
};

/* ── Panel de revisión tipo inbox ── */
const ReviewPanel = ({ blockingGroups, warningsGroups, labelByKey }) => {
    const allItems = [
        ...blockingGroups.map((g) => ({ ...g, kind: "blocking" })),
        ...warningsGroups.map((g) => ({ ...g, kind: "warning" })),
    ];

    const [selected, setSelected] = useState(null);

    useEffect(() => {
        if (!selected && allItems.length > 0) {
            setSelected(allItems[0]);
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const selectedGroup = allItems.find(
        (g) => g.field === selected?.field && g.kind === selected?.kind,
    );
    const isBlocking = selectedGroup?.kind === "blocking";
    const hasMore = selectedGroup && selectedGroup.count > selectedGroup.samples.length;

    return (
        <div className={s.reviewPanel}>
            <div className={s.reviewSidebar}>
                {blockingGroups.length > 0 && (
                    <div className={s.reviewSection}>
                        <div className={s.reviewSectionTitle}>
                            <span className={s.reviewBullet + " " + s.bulletDanger} />
                            Necesitan corrección
                        </div>
                        {blockingGroups.map((g) => (
                            <button
                                key={g.field}
                                className={`${s.reviewItem} ${selected?.field === g.field && selected?.kind === "blocking" ? s.reviewItemActive : ""}`}
                                onClick={() => setSelected({ field: g.field, kind: "blocking" })}
                            >
                                <span className={s.reviewItemName}>{g.label}</span>
                                <span className={s.reviewItemCount}>{g.count}</span>
                            </button>
                        ))}
                    </div>
                )}
                {warningsGroups.length > 0 && (
                    <div className={s.reviewSection}>
                        <div className={s.reviewSectionTitle}>
                            <span className={s.reviewBullet + " " + s.bulletMuted} />
                            Datos incompletos
                        </div>
                        {warningsGroups.map((g) => (
                            <button
                                key={g.field}
                                className={`${s.reviewItem} ${selected?.field === g.field && selected?.kind === "warning" ? s.reviewItemActive : ""}`}
                                onClick={() => setSelected({ field: g.field, kind: "warning" })}
                            >
                                <span className={s.reviewItemName}>{g.label}</span>
                                <span className={s.reviewItemCount}>{g.count}</span>
                            </button>
                        ))}
                    </div>
                )}
            </div>

            <div className={s.reviewDetail}>
                {selectedGroup ? (
                    <>
                        <div className={s.reviewDetailHeader}>
                            <span className={`${s.reviewDetailIcon} ${isBlocking ? s.iconDanger : s.iconInfo}`}>
                                {isBlocking ? "!" : "ℹ"}
                            </span>
                            <div>
                                <div className={s.reviewDetailTitle}>{selectedGroup.label}</div>
                                <div className={s.reviewDetailSub}>
                                    {selectedGroup.count} fila{selectedGroup.count === 1 ? "" : "s"} afectada{selectedGroup.count === 1 ? "" : "s"}
                                </div>
                            </div>
                        </div>
                        <div className={s.reviewDetailDivider} />
                        <div className={s.reviewDetailAction}>
                            {isBlocking ? "Qué hacer: " : ""}{selectedGroup.action}
                        </div>
                        <div className={s.reviewDetailDivider} />
                        <div className={s.reviewDetailExamples}>
                            <div className={s.reviewDetailExamplesLabel}>
                                Ejemplo{selectedGroup.samples.length === 1 ? "" : "s"}
                            </div>
                            {selectedGroup.samples.map((it) => (
                                <div key={it.row} className={s.reviewDetailExampleRow}>
                                    <span className={s.reviewDetailExampleNum}>#{it.row}</span>
                                    <span className={s.reviewDetailExampleMsg}>{it.message}</span>
                                </div>
                            ))}
                            {hasMore && (
                                <div className={s.reviewDetailMore}>
                                    …y {selectedGroup.count - selectedGroup.samples.length} más
                                </div>
                            )}
                        </div>
                    </>
                ) : (
                    <div className={s.reviewDetailEmpty}>
                        Selecciona un problema para ver detalles.
                    </div>
                )}
            </div>
        </div>
    );
};

/* Paso 3 — Vista previa (dry-run) */
const PreviewStep = ({
    result,
    fieldCatalog = [],
    onBack,
    onConfirm,
    committing,
    canCommit,
    entityType = "owner_pet",
    jobPublicId,
}) => {
    const cfg = getEntityConfig(entityType);
    const labelByKey = useMemo(() => {
        const m = { mapping: "Mapeo de columnas", owner: "Cliente", pet: "Mascota", row: "Fila" };
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);

    const [openSections, setOpenSections] = useState({
        warnings: false,
        omitted: true,
    });

    const r = result || {};
    const createdTotal = num(r[cfg.createdTotalKey]);
    const createdPets = createdTotal; // alias interno legado (pills/CTA genéricos)
    const skippedDups = num(r.skipped_duplicates);
    const skippedConflicts = num(r.skipped_conflicts);
    const blockingRows = num(r.blocking_rows);
    const conflicts = r.conflicts || [];
    const blocking = r.blocking || r.errors || [];
    const warnings = r.warnings || [];
    const preview = r.preview || [];
    const skipped = r.skipped || [];
    // Totales reales: el backend manda *_total cuando el array es muestra capada.
    // `!= null` honra un 0 legítimo; solo cae al array si el campo no vino (resp. vieja).
    const previewTotal = r.preview_total != null ? num(r.preview_total) : createdPets;
    const skippedTotal = r.skipped_total != null ? num(r.skipped_total) : skippedDups;

    // Cards de muestra (lo que llega en el array; puede ser < total si se capa).
    const highConfidence = conflicts.filter((c) => c.match_confidence === "high");
    const uncertainConfidence = conflicts.filter((c) => c.match_confidence !== "high");

    // Split AGREGADO de conflictos = fuente única de verdad para los conteos.
    // El backend envía conflicts_high/uncertain (suman skipped_conflicts). Fallback
    // a derivarlo del array solo para respuestas viejas sin el split.
    const conflictsHighTotal = r.conflicts_high != null ? num(r.conflicts_high) : highConfidence.length;
    const conflictsUncertainTotal = r.conflicts_uncertain != null ? num(r.conflicts_uncertain) : uncertainConfidence.length;

    // Totales derivados SOLO de agregados → los hijos SIEMPRE suman al padre:
    //   registeredTotal + conflictsUncertainTotal === omittedTotal
    const omittedTotal = skippedTotal + skippedConflicts;          // "No se importarán"
    const registeredTotal = skippedTotal + conflictsHighTotal;     // "Ya estaban registrados"

    const hasBlocking = blocking.length > 0;
    const hasImportable = createdPets > 0;
    const hasAnyIssue = skippedConflicts > 0 || hasBlocking || warnings.length > 0 || skippedDups > 0;

    const toggle = (s) => setOpenSections((prev) => ({ ...prev, [s]: !prev[s] }));

    const totalPersons = cfg.createdSecondaryKeys.reduce((acc, k) => acc + num(r[k]), 0);

    const blockingActions = Object.fromEntries(
        Object.entries(cfg.blockingActions).map(([field, fn]) => [field, fn(labelByKey)]),
    );

    const blockingGroups = useMemo(
        () => groupImportIssues(blocking, labelByKey, blockingActions),
        [blocking, labelByKey],
    );
    const warningsGroups = useMemo(
        () => groupImportIssues(warnings, labelByKey),
        [warnings, labelByKey],
    );

    return (
        <div>
            {/* ── Barra de estado ── */}
            <div className={s.statusBar}>
                <div className={s.statusBarTitle}>Revisa antes de importar</div>
                <div className={s.statusBarSub}>
                    Esta es una simulación — todavía no se han importado registros.
                </div>
                <div className={s.statusPills}>
                    {createdTotal > 0 && (
                        <div className={`${s.statusPill} ${s.pillSuccess}`}>
                            <span className={s.pillIcon}>✓</span>
                            Se crearán {createdTotal} {createdTotal !== 1 ? cfg.nouns.primaryPlural : cfg.nouns.primary}
                            {cfg.showPersonsPill && totalPersons > 0 && (
                                <span className={s.pillExtra}>
                                    {" · "}asociadas a {totalPersons} {totalPersons !== 1 ? cfg.nouns.personPlural : cfg.nouns.person}
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
                    {!hasAnyIssue && createdTotal === 0 && (
                        <div className={`${s.statusPill} ${s.pillMuted}`}>
                            No se encontraron registros para importar.
                        </div>
                    )}
                </div>
            </div>

            {/* ── Sección: SE CREARÁN ── */}
            {hasImportable && preview.length > 0 && (
                <div className={s.previewSection}>
                    <div className={s.previewSectionHeader}>
                        <span className={s.previewSectionIcon}>✓</span>
                        <span>SE CREARÁN</span>
                        <span className={s.previewTotal}>
                            ({previewTotal} {previewTotal === 1 ? cfg.nouns.primary : cfg.nouns.primaryPlural})
                        </span>
                    </div>
                    <div className={s.previewTableWrap}>
                        <table className={s.previewTable}>
                            <thead>
                                <tr>
                                    <th>#</th>
                                    {cfg.previewColumns.map((col) => (
                                        <th key={col.key}>{col.label}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {preview.map((p) => (
                                    <tr key={p.row}>
                                        <td className={s.rowNum}>{p.row}</td>
                                        {cfg.previewColumns.map((col) => (
                                            <td key={col.key} className={col.cellClass ? s[col.cellClass] : undefined}>
                                                {p[col.key] || "—"}
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {previewTotal > preview.length && (
                        <div className={s.previewShowing}>
                            Mostrando {preview.length} de {previewTotal}
                        </div>
                    )}
                    {warnings.length > 0 && (
                        <div className={s.warningNotice}>
                            <button className={s.warningNoticeToggle} onClick={() => toggle("warnings")} aria-expanded={openSections.warnings}>
                                <span className={s.warningNoticeIcon}>⚠</span>
                                <span>{warnings.length} registro{warnings.length === 1 ? "" : "s"} se importará{warnings.length === 1 ? "" : "n"} con algunos datos faltantes.</span>
                                <span className={s.warningNoticeAction}>
                                    Puedes completarlos después. {openSections.warnings ? "▲" : "▸ ver detalle"}
                                </span>
                            </button>
                            {openSections.warnings && (
                                <div className={s.warningNoticeBody}>
                                    {warningsGroups.map((g) => (
                                        <div key={g.field} className={s.warningGroup}>
                                            <div className={s.warningGroupLabel}>
                                                {g.label} — {g.count} registro{g.count === 1 ? "" : "s"}
                                            </div>
                                            <div className={s.warningGroupAction}>{g.action}</div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* ── Panel de revisión: errores que bloquean ── */}
            {hasBlocking && (
                <ReviewPanel
                    blockingGroups={blockingGroups}
                    warningsGroups={[]}
                    labelByKey={labelByKey}
                />
            )}

            {/* ── NO SE IMPORTARÁN ── */}
            {omittedTotal > 0 && (
                <div className={s.collapseBlock}>
                    <button className={s.collapseToggle} onClick={() => toggle("omitted")} aria-expanded={openSections.omitted}>
                        <span className={s.collapseIcon}>⊘</span>
                        <span className={s.collapseLabel}>No se importarán ({omittedTotal})</span>
                        <span className={s.collapseChevron}>{openSections.omitted ? "▲" : "▼"}</span>
                    </button>
                    {openSections.omitted && (
                        <div className={s.collapseBody}>
                            <p className={s.omittedIntro}>
                                Estos registros no se crearán. No es un error — ya existen en SaaslyVet
                                o tienen conflictos que requieren revisión.
                            </p>

                            {registeredTotal > 0 && (
                                <div className={s.omittedReasonBlock}>
                                    <div className={s.omittedReasonTitle}>
                                        {/* Total real desde AGREGADOS: dups (skippedTotal) + conflictos
                                            high (conflictsHighTotal). Las cards salen de las muestras
                                            skipped[]/highConfidence; los "Mostrando N de M" cubren el gap. */}
                                        Ya estaban registrados ({registeredTotal})
                                    </div>
                                    {skipped.map((item) => (
                                        <div key={`skip-${item.row}`} className={s.skippedCard}>
                                            <div className={s.skippedCardHeader}>
                                                <span className={s.conflictNum}>Fila #{item.row}</span>
                                            </div>
                                            <div className={s.skippedCardInfo}>
                                                {cfg.skippedCardFields.map((f) => (
                                                    <span key={f.key}>
                                                        <span className={s.skippedInfoLabel}>{f.label}: </span>
                                                        {item[f.key] || "—"}
                                                    </span>
                                                ))}
                                            </div>
                                            <p style={{ fontSize: 12, color: "var(--c-text-3)", margin: "6px 0 0" }}>
                                                {item.message}
                                            </p>
                                        </div>
                                    ))}
                                    {skippedTotal > skipped.length && (
                                        <div className={s.previewShowing}>
                                            Mostrando {skipped.length} de {skippedTotal}
                                        </div>
                                    )}
                                    {highConfidence.map((c) => (
                                        <ConflictCard key={`reg-conf-${c.row}`} conflict={c} cfg={cfg} />
                                    ))}
                                    {conflictsHighTotal > highConfidence.length && (
                                        <div className={s.previewShowing}>
                                            Mostrando {highConfidence.length} de {conflictsHighTotal}
                                        </div>
                                    )}
                                </div>
                            )}

                            {conflictsUncertainTotal > 0 && (
                                <div className={s.omittedReasonBlock}>
                                    <div className={s.omittedReasonTitle}>
                                        {cfg.conflict.uncertainTitle(conflictsUncertainTotal)}
                                    </div>
                                    <p className={s.omittedReasonDesc}>
                                        {cfg.conflict.uncertainDesc}
                                    </p>
                                    {uncertainConfidence.map((c) => (
                                        <ConflictCard key={`exp-conf-${c.row}`} conflict={c} cfg={cfg} />
                                    ))}
                                    {conflictsUncertainTotal > uncertainConfidence.length && (
                                        <div className={s.previewShowing}>
                                            Mostrando {uncertainConfidence.length} de {conflictsUncertainTotal}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            <ConflictPages key={r.conflict_report?.version} publicId={jobPublicId} report={r.conflict_report} highTotal={conflictsHighTotal} uncertainTotal={conflictsUncertainTotal} />

            {/* ── Descarga CSV ── */}
            {(blocking.length > 0 || warnings.length > 0) && (
                <div style={{ marginBottom: 14 }}>
                    <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                            const all = [...blocking, ...warnings].sort((a, b) => a.row - b.row);
                            downloadCsv(all, labelByKey, "filas-con-problemas.csv", cfg.csvActions);
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
                <button className="btn btn-secondary btn-md" onClick={onBack} disabled={committing}>Atrás</button>
                <div className={s.actionsRight}>
                    {hasBlocking ? (
                        <span className={s.ctaBlocked}>
                            Corrige los {blocking.length} error{blocking.length === 1 ? "" : "es"} para poder importar.
                        </span>
                    ) : hasImportable && canCommit ? (
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
                            <p className={s.consequence}>
                                Al continuar: ✓ se importarán {createdPets} registro{createdPets === 1 ? "" : "s"}
                                {omittedTotal > 0 && <>{" · "}⊘ {omittedTotal} no se importarán</>}
                            </p>
                            <button className="btn btn-primary btn-md" onClick={onConfirm} disabled={committing}>
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
