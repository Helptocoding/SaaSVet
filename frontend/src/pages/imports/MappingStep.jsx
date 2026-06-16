import { useMemo, useState } from "react";
import s from "./imports.module.css";
import { Icon } from "../../components/icons";
import DestinationPicker from "./DestinationPicker";

const PENDING = "__pending__";   // sin decidir → bloquea continuar
const NO_IMPORT = "";
const EXTRA_OWNER = "owner.extra";
const EXTRA_PET = "pet.extra";

const targetOf = (spec) =>
    spec === undefined ? PENDING : (typeof spec === "object" ? spec.target : spec);

/* Paso 2 — "VetCare entendió tu Excel, solo revisa unas cosas" (Fase D, rediseño UX).

   UNA sola decisión por columna: "¿Qué representa esta columna?" → se abre el
   DestinationPicker (modal) con campos del sistema + datos históricos + no importar.
   No se exponen conceptos internos ni listas abiertas dentro de cada card.

   - Columnas auto-reconocidas (el backend ya sugirió un campo del sistema) → sección
     compacta colapsable ("✓ N reconocidas automáticamente").
   - Las demás → cards compactas: pendiente "Seleccionar destino" / resuelta
     "✓ … Cambiar". La decisión nunca es irreversible.

   NO toca backend: el payload sigue siendo { col: string | {target, label} }. */
const MappingStep = ({
    sourceColumns = [],
    sampleRows = [],
    fieldCatalog = [],
    initialMapping = {},
    onContinue,
    onBack,
    busy = false,
}) => {
    const systemKeys = useMemo(
        () => new Set(fieldCatalog.filter((f) => !f.is_extra).map((f) => f.key)),
        [fieldCatalog]
    );
    const labelByKey = useMemo(() => {
        const m = {};
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);
    const requiredKeys = useMemo(
        () => fieldCatalog.filter((f) => f.importance === "required").map((f) => f.key),
        [fieldCatalog]
    );
    const isSystem = (v) => systemKeys.has(v);
    const isExtra = (v) => v === EXTRA_OWNER || v === EXTRA_PET;

    // Origen: columnas que el backend ya reconoció como campo del sistema. Estable
    // (no cambia aunque el usuario reasigne) → define qué va al bloque compacto.
    const autoCols = useMemo(
        () => sourceColumns.filter((c) => isSystem(targetOf(initialMapping[c]))),
        [sourceColumns, initialMapping, systemKeys]  // eslint-disable-line react-hooks/exhaustive-deps
    );
    const reviewCols = useMemo(
        () => sourceColumns.filter((c) => !autoCols.includes(c)),
        [sourceColumns, autoCols]
    );

    const [mapping, setMapping] = useState(() => {
        const seed = {};
        for (const col of sourceColumns) seed[col] = targetOf(initialMapping[col]);
        return seed;
    });
    const [customLabel, setCustomLabel] = useState(() => {
        const seed = {};
        for (const col of sourceColumns) {
            const v = initialMapping[col];
            if (v && typeof v === "object" && v.label) seed[col] = v.label;
        }
        return seed;
    });
    const [editingLabel, setEditingLabel] = useState(() => new Set());
    const [detailsOpen, setDetailsOpen] = useState(false);
    const [pickerCol, setPickerCol] = useState(null);   // columna con el modal abierto

    const assignedSystem = useMemo(
        () => new Set(Object.values(mapping).filter(isSystem)),
        [mapping]  // eslint-disable-line react-hooks/exhaustive-deps
    );
    const labelOf = (col) => (customLabel[col] ?? col);

    const choose = (col, value) => {
        setMapping((prev) => ({ ...prev, [col]: value }));
        setPickerCol(null);
    };
    const startLabelEdit = (col) => setEditingLabel((prev) => new Set(prev).add(col));
    const commitLabel = (col) =>
        setEditingLabel((prev) => { const n = new Set(prev); n.delete(col); return n; });

    const pendingCount = reviewCols.filter((c) => mapping[c] === PENDING).length;
    const readyCount = sourceColumns.length - pendingCount;
    const missingRequired = requiredKeys.filter((k) => !assignedSystem.has(k));
    const canContinue = pendingCount === 0 && missingRequired.length === 0 && !busy;

    const colIndex = (col) => sourceColumns.indexOf(col);
    const samplePreview = (col) => {
        const idx = colIndex(col);
        const vals = [];
        for (const row of sampleRows) {
            const cell = row?.[idx];
            if (cell !== undefined && cell !== null && String(cell).trim() !== "") vals.push(String(cell));
            if (vals.length >= 3) break;
        }
        return vals.length ? vals.join(" · ") : "—";
    };

    const destLine = (v) => {
        if (isSystem(v)) return `Se importará como ${labelByKey[v]}`;
        if (v === EXTRA_OWNER) return "Se conservará como Información anterior del cliente";
        if (v === EXTRA_PET) return "Se conservará como Información anterior de la mascota";
        return "No se importará";
    };

    const handleContinue = () => {
        const clean = {};
        for (const [col, v] of Object.entries(mapping)) {
            if (v === PENDING) continue;
            if (isExtra(v)) {
                const lbl = (labelOf(col) || "").trim() || col;
                clean[col] = { target: v, label: lbl };   // referencia original = la KEY (col)
            } else {
                clean[col] = v;   // campo del sistema o "" (no importar)
            }
        }
        onContinue(clean);
    };

    // ── Card de columna a revisar ───────────────────────────────────────────
    const reviewCard = (col) => {
        const v = mapping[col];
        if (v === PENDING) {
            return (
                <div key={col} className={`${s.colCard} ${s.colCardPending}`}>
                    <p className={s.colCardTitle}>
                        <span className={s.colCardWarn} aria-hidden="true"><Icon.AlertTriangle s={15} /></span>
                        <span className={s.colCardName}>{col}</span>
                    </p>
                    <p className={s.colCardExamples}>Ejemplos: {samplePreview(col)}</p>
                    <button
                        type="button"
                        className={`btn btn-primary btn-sm ${s.btnWithIcon}`}
                        onClick={() => setPickerCol(col)}
                        disabled={busy}
                    >
                        Seleccionar destino <Icon.ChevronDown s={14} />
                    </button>
                </div>
            );
        }
        return (
            <div key={col} className={s.colCard}>
                <p className={s.colCardTitle}>
                    <span className={s.colCardOk} aria-hidden="true"><Icon.Check s={15} /></span>
                    <span className={s.colCardName}>{col}</span>
                </p>
                <p className={s.colCardDest}>{destLine(v)}</p>
                {isExtra(v) && (
                    <div className={s.renameRow}>
                        {editingLabel.has(col) ? (
                            <input
                                className={s.renameInput}
                                value={labelOf(col)}
                                autoFocus
                                onChange={(e) => setCustomLabel((p) => ({ ...p, [col]: e.target.value }))}
                                onKeyDown={(e) => { if (e.key === "Enter") commitLabel(col); }}
                                onBlur={() => commitLabel(col)}
                                disabled={busy}
                                aria-label={`Nombre visible para ${col}`}
                            />
                        ) : (
                            <>
                                <span className={s.renameLabel}>Nombre visible: <strong>{labelOf(col)}</strong></span>
                                <button
                                    type="button"
                                    className={s.renameBtn}
                                    onClick={() => startLabelEdit(col)}
                                    disabled={busy}
                                    aria-label={`Renombrar ${col}`}
                                    title="Cambiar el nombre visible"
                                >
                                    <Icon.Edit s={14} />
                                </button>
                            </>
                        )}
                    </div>
                )}
                <button
                    type="button"
                    className={s.changeLink}
                    onClick={() => setPickerCol(col)}
                    disabled={busy}
                    aria-label={`Cambiar destino de ${col}`}
                >
                    Cambiar
                </button>
            </div>
        );
    };

    return (
        <div>
            <div className="card" style={{ marginBottom: 16, padding: "16px 20px" }}>
                <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
                    {sourceColumns.length} columnas detectadas
                </p>
                <p style={{ fontSize: 13, color: "var(--c-text-2)" }}>
                    <span className={s.summaryReady}>
                        <Icon.Check s={14} /> <span>{readyCount} listas</span>
                    </span>
                    {pendingCount > 0 && (
                        <span className={s.summaryWarn}>
                            <span aria-hidden="true"> · </span>
                            <Icon.AlertTriangle s={14} /> <span>{pendingCount} necesitan revisión</span>
                        </span>
                    )}
                </p>
            </div>

            {reviewCols.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                    {pendingCount > 0 && (
                        <p className={s.exIntro}>
                            Revisa estas columnas: dinos qué representa cada una para
                            importarla bien (o consérvala como información del sistema
                            anterior).
                        </p>
                    )}
                    <div className={s.colGrid}>{reviewCols.map(reviewCard)}</div>
                </div>
            )}

            {autoCols.length > 0 && (
                <div className={s.readyBlock}>
                    <button
                        type="button"
                        className={s.readyToggle}
                        onClick={() => setDetailsOpen((o) => !o)}
                        aria-expanded={detailsOpen}
                    >
                        <span className={s.readyToggleLabel}>
                            <Icon.Check s={15} /> {autoCols.length} columnas reconocidas automáticamente
                        </span>
                        <span className={s.readyChevron}>
                            {detailsOpen ? "Ocultar" : "Ver detalles"}
                            {detailsOpen ? <Icon.ChevronUp s={14} /> : <Icon.ChevronDown s={14} />}
                        </span>
                    </button>
                    {detailsOpen && (
                        <div className={s.readyList}>
                            {autoCols.map((col) => (
                                <div key={col} className={s.readyRow}>
                                    <span className={s.readyCol}>{col}</span>
                                    <span className={s.readyArrow}>→</span>
                                    <span className={s.readyDest}>
                                        {isSystem(mapping[col]) ? labelByKey[mapping[col]] : destLine(mapping[col])}
                                    </span>
                                    <button
                                        type="button"
                                        className={s.changeLink}
                                        onClick={() => setPickerCol(col)}
                                        disabled={busy}
                                        aria-label={`Cambiar columna ${col}`}
                                    >
                                        Cambiar
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {pendingCount === 0 && missingRequired.length > 0 && (
                <div className={s.missingBox}>
                    <strong>Para continuar</strong>, asigna {missingRequired.length === 1 ? "este campo obligatorio" : "estos campos obligatorios"}:
                    <ul>
                        {missingRequired.map((k) => <li key={k}>{labelByKey[k] || k}</li>)}
                    </ul>
                </div>
            )}

            <div className={s.actions}>
                <button className="btn btn-secondary btn-md" onClick={onBack} disabled={busy}>
                    Atrás
                </button>
                <div className={s.actionsRight}>
                    <button className="btn btn-primary btn-md" onClick={handleContinue} disabled={!canContinue}>
                        {busy ? "Validando..." : "Continuar"}
                    </button>
                </div>
            </div>

            {pickerCol !== null && (
                <DestinationPicker
                    column={pickerCol}
                    examples={samplePreview(pickerCol)}
                    fieldCatalog={fieldCatalog}
                    value={mapping[pickerCol] === PENDING ? undefined : mapping[pickerCol]}
                    assignedSystem={assignedSystem}
                    onPick={(value) => choose(pickerCol, value)}
                    onClose={() => setPickerCol(null)}
                />
            )}
        </div>
    );
};

export default MappingStep;
