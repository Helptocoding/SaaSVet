import { useMemo, useState } from "react";
import s from "./imports.module.css";

const PENDING = "__pending__";   // sin decidir → bloquea continuar
const NO_IMPORT = "";
const EXTRA_OWNER = "owner.extra";
const EXTRA_PET = "pet.extra";

const normalize = (str) =>
    (str || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

function groupSystemFields(fieldCatalog) {
    const groups = [];
    const byName = new Map();
    for (const f of fieldCatalog) {
        if (f.is_extra) continue;
        const name = f.group || "Otros";
        if (!byName.has(name)) {
            const bucket = { name, fields: [] };
            byName.set(name, bucket);
            groups.push(bucket);
        }
        byName.get(name).fields.push(f);
    }
    return groups;
}

/* Paso 2 — Revisar como una tabla rápida (Fase D, iteración compacta).
   - Columnas que NO son campo del sistema → grid responsive de tarjetas. Cada una
     con selector Cliente/Mascota/No importar SIEMPRE visible y cambiable, y label
     renombrable (solo el nombre visible; la columna original sigue siendo la
     referencia para leer el Excel → backend recibe {target, label}).
   - Columnas reconocidas → resumen compacto colapsable (sin cards). */
const MappingStep = ({
    sourceColumns = [],
    sampleRows = [],
    fieldCatalog = [],
    initialMapping = {},
    onContinue,
    onBack,
    busy = false,
}) => {
    const systemGroups = useMemo(() => groupSystemFields(fieldCatalog), [fieldCatalog]);
    const systemKeys = useMemo(
        () => new Set(fieldCatalog.filter(f => !f.is_extra).map(f => f.key)),
        [fieldCatalog]
    );
    const labelByKey = useMemo(() => {
        const m = {};
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);
    const requiredKeys = useMemo(
        () => fieldCatalog.filter(f => f.importance === "required").map(f => f.key),
        [fieldCatalog]
    );

    const [mapping, setMapping] = useState(() => {
        const seed = {};
        for (const col of sourceColumns) {
            const v = initialMapping[col];
            // initialMapping puede traer {target,label} (extra renombrado) o string.
            seed[col] = v === undefined ? PENDING : (typeof v === "object" ? v.target : v);
        }
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
    const [readyOpen, setReadyOpen] = useState(false);
    const [editing, setEditing] = useState(() => new Set());   // reconocidas en "Modificar"
    const [sysOpen, setSysOpen] = useState(() => new Set());   // excepción mostrando picker del sistema
    const [search, setSearch] = useState({});

    const isSystem = (v) => systemKeys.has(v);
    const assignedSystem = useMemo(
        () => new Set(Object.values(mapping).filter(isSystem)),
        [mapping]  // eslint-disable-line react-hooks/exhaustive-deps
    );

    const labelOf = (col) => (customLabel[col] ?? col);

    const choose = (col, value) => {
        setMapping(prev => ({ ...prev, [col]: value }));
        setSysOpen(prev => { const n = new Set(prev); n.delete(col); return n; });
        setEditing(prev => { const n = new Set(prev); n.delete(col); return n; });
    };
    const toggleSys = (col) => setSysOpen(prev => {
        const n = new Set(prev); n.has(col) ? n.delete(col) : n.add(col); return n;
    });
    const startLabelEdit = (col) => setEditingLabel(prev => new Set(prev).add(col));
    const commitLabel = (col) => setEditingLabel(prev => { const n = new Set(prev); n.delete(col); return n; });

    const recognizedCols = sourceColumns.filter(c => isSystem(mapping[c]));
    const exceptionCols = sourceColumns.filter(c => !isSystem(mapping[c]));
    const pendingCount = exceptionCols.filter(c => mapping[c] === PENDING).length;
    const missingRequired = requiredKeys.filter(k => !assignedSystem.has(k));
    const canContinue = pendingCount === 0 && missingRequired.length === 0 && !busy;

    const samplePreview = (colIndex) => {
        const vals = [];
        for (const row of sampleRows) {
            const cell = row?.[colIndex];
            if (cell !== undefined && cell !== null && String(cell).trim() !== "") vals.push(String(cell));
            if (vals.length >= 3) break;
        }
        return vals.length ? vals.join(" · ") : "—";
    };

    const destLabel = (v) => {
        if (isSystem(v)) return labelByKey[v];
        if (v === EXTRA_OWNER) return "Histórico del cliente";
        if (v === EXTRA_PET) return "Histórico de la mascota";
        return "No se importa";
    };

    const handleContinue = () => {
        const clean = {};
        for (const [col, v] of Object.entries(mapping)) {
            if (v === PENDING) continue;
            if (v === EXTRA_OWNER || v === EXTRA_PET) {
                const lbl = (labelOf(col) || "").trim() || col;
                clean[col] = { target: v, label: lbl };  // referencia original = la KEY (col)
            } else {
                clean[col] = v;  // campo del sistema o "" (no importar)
            }
        }
        onContinue(clean);
    };

    const systemPicker = (col, current) => {
        const q = search[col] || "";
        return (
            <div className={s.colPicker}>
                <input
                    className="select-input"
                    placeholder="Buscar un campo: nombre, teléfono, especie…"
                    value={q}
                    onChange={(e) => setSearch(p => ({ ...p, [col]: e.target.value }))}
                    disabled={busy}
                    aria-label={`Buscar campo del sistema para ${col}`}
                />
                {systemGroups.map(g => {
                    const fields = g.fields.filter(f => normalize(f.label).includes(normalize(q)));
                    if (!fields.length) return null;
                    return (
                        <div key={g.name} className={s.pickerGroup}>
                            <span className={s.pickerGroupName}>{g.name}</span>
                            <div className={s.pickerBtns}>
                                {fields.map(f => {
                                    const taken = assignedSystem.has(f.key) && current !== f.key;
                                    return (
                                        <button
                                            key={f.key}
                                            type="button"
                                            className={`${s.pickerBtn} ${current === f.key ? s.pickerBtnActive : ""}`}
                                            disabled={taken || busy}
                                            title={taken ? "Ya asignado a otra columna" : undefined}
                                            onClick={() => choose(col, f.key)}
                                        >
                                            {f.label}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    );
                })}
            </div>
        );
    };

    const exceptionCard = (col) => {
        const idx = sourceColumns.indexOf(col);
        const v = mapping[col];
        const undecided = v === PENDING;
        return (
            <div key={col} className={`${s.exCard} ${undecided ? s.exCardPending : ""}`}>
                <div className={s.exHead}>
                    {editingLabel.has(col) ? (
                        <input
                            className={s.exLabelInput}
                            value={labelOf(col)}
                            autoFocus
                            onChange={(e) => setCustomLabel(p => ({ ...p, [col]: e.target.value }))}
                            onKeyDown={(e) => { if (e.key === "Enter") commitLabel(col); }}
                            onBlur={() => commitLabel(col)}
                            disabled={busy}
                            aria-label={`Nombre del dato para ${col}`}
                        />
                    ) : (
                        <>
                            <span className={s.exLabel} title={labelOf(col) === col ? undefined : `Columna original: ${col}`}>
                                {labelOf(col)}
                            </span>
                            <button
                                type="button"
                                className={s.exEdit}
                                onClick={() => startLabelEdit(col)}
                                disabled={busy}
                                aria-label={`Renombrar ${col}`}
                                title="Renombrar el dato"
                            >
                                ✏️
                            </button>
                        </>
                    )}
                </div>
                <p className={s.exSample}>Ejemplos: {samplePreview(idx)}</p>
                <p className={s.exGuardar}>Conservar como:</p>
                <div className={s.segGroup}>
                    <button type="button" aria-pressed={v === EXTRA_OWNER} className={`${s.segBtn} ${v === EXTRA_OWNER ? s.segBtnActive : ""}`} onClick={() => choose(col, EXTRA_OWNER)} disabled={busy}>Histórico cliente</button>
                    <button type="button" aria-pressed={v === EXTRA_PET} className={`${s.segBtn} ${v === EXTRA_PET ? s.segBtnActive : ""}`} onClick={() => choose(col, EXTRA_PET)} disabled={busy}>Histórico mascota</button>
                    <button type="button" aria-pressed={v === NO_IMPORT} className={`${s.segBtn} ${v === NO_IMPORT ? s.segBtnActive : ""}`} onClick={() => choose(col, NO_IMPORT)} disabled={busy}>No importar</button>
                </div>
                <button type="button" className={s.sysLink} onClick={() => toggleSys(col)} disabled={busy}>
                    {sysOpen.has(col) ? "Ocultar campos del sistema" : "Relacionar con un campo existente"}
                </button>
                {sysOpen.has(col) && systemPicker(col, v)}
            </div>
        );
    };

    const readyRow = (col) => {
        if (editing.has(col)) {
            return (
                <div key={col} className={s.readyEditing}>
                    <p className={s.colQuestion}>Modificar «{col}»</p>
                    {systemPicker(col, mapping[col])}
                    <div className={s.pickerExtra}>
                        <span className={s.pickerOr}>o consérvala como dato del sistema anterior:</span>
                        <div className={s.pickerBtns}>
                            <button type="button" className={s.pickerBtn} onClick={() => choose(col, EXTRA_OWNER)} disabled={busy}>Histórico del cliente</button>
                            <button type="button" className={s.pickerBtn} onClick={() => choose(col, EXTRA_PET)} disabled={busy}>Histórico de la mascota</button>
                            <button type="button" className={s.pickerBtnGhost} onClick={() => choose(col, NO_IMPORT)} disabled={busy}>No importar</button>
                        </div>
                    </div>
                </div>
            );
        }
        return (
            <div key={col} className={s.readyRow}>
                <span className={s.readyCol}>{col}</span>
                <span className={s.readyArrow}>→</span>
                <span className={s.readyDest}>{destLabel(mapping[col])}</span>
                <button
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={() => setEditing(prev => new Set(prev).add(col))}
                    disabled={busy}
                    aria-label={`Modificar columna ${col}`}
                >
                    Modificar
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
                    <span className={s.summaryReady}>✓ {recognizedCols.length} reconocidas</span>
                    {pendingCount > 0 && (
                        <span className={s.summaryWarn}> · ⚠ {pendingCount} por revisar</span>
                    )}
                </p>
            </div>

            {exceptionCols.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                    <p className={s.sectionLabel}>Columnas sin un campo equivalente</p>
                    <p className={s.exIntro}>
                        No encontramos un campo del sistema para estas columnas. Puedes
                        conservar la información como referencia del sistema anterior, o
                        no importarla.
                    </p>
                    <div className={s.exGrid}>{exceptionCols.map(exceptionCard)}</div>
                </div>
            )}

            {recognizedCols.length > 0 && (
                <div className={s.readyBlock}>
                    <button
                        type="button"
                        className={s.readyToggle}
                        onClick={() => setReadyOpen(o => !o)}
                        aria-expanded={readyOpen}
                    >
                        <span>✓ Reconocidas automáticamente ({recognizedCols.length})</span>
                        <span className={s.readyChevron}>{readyOpen ? "▲" : "▼"}</span>
                    </button>
                    {readyOpen && <div className={s.readyList}>{recognizedCols.map(readyRow)}</div>}
                </div>
            )}

            {pendingCount === 0 && missingRequired.length > 0 && (
                <div className={s.missingBox}>
                    <strong>Para continuar</strong>, asigna {missingRequired.length === 1 ? "este campo obligatorio" : "estos campos obligatorios"}:
                    <ul>
                        {missingRequired.map(k => <li key={k}>{labelByKey[k] || k}</li>)}
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
        </div>
    );
};

export default MappingStep;
