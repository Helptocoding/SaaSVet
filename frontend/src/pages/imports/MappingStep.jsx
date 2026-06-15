import { useMemo, useState } from "react";
import s from "./imports.module.css";

// Estados de una columna:
const PENDING = "__pending__";   // desconocida, sin decidir → bloquea continuar
const NO_IMPORT = "";            // "no importar esta columna"
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

/* Paso 2 — Revisar excepciones (Fase D, enfoque "el sistema ya hizo el trabajo").
   - Las columnas reconocidas NO son protagonistas: van en una sección compacta
     colapsable ("✓ N columnas listas"); solo se tocan con "Modificar".
   - Las columnas DESCONOCIDAS son las protagonistas: una card por cada una que
     necesita revisión, con pregunta humana y 3 opciones. Bloquean continuar hasta
     decidir. El backend (mapping) no cambia. */
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
            seed[col] = v === undefined ? PENDING : v;
        }
        return seed;
    });
    const [readyOpen, setReadyOpen] = useState(false);   // sección de reconocidas
    const [editing, setEditing] = useState(() => new Set());      // reconocidas en "Modificar"
    const [sysOpen, setSysOpen] = useState(() => new Set());      // pendientes mostrando picker del sistema
    const [search, setSearch] = useState({});

    const isSystem = (v) => systemKeys.has(v);
    const assignedSystem = useMemo(
        () => new Set(Object.values(mapping).filter(isSystem)),
        [mapping]  // eslint-disable-line react-hooks/exhaustive-deps
    );

    const decide = (col, value) => {
        setMapping(prev => ({ ...prev, [col]: value }));
        setEditing(prev => { const n = new Set(prev); n.delete(col); return n; });
        setSysOpen(prev => { const n = new Set(prev); n.delete(col); return n; });
    };
    const openEdit = (col) => setEditing(prev => new Set(prev).add(col));
    const toggleSys = (col) => setSysOpen(prev => {
        const n = new Set(prev); n.has(col) ? n.delete(col) : n.add(col); return n;
    });

    const pendingCols = sourceColumns.filter(c => mapping[c] === PENDING);
    const readyCols = sourceColumns.filter(c => mapping[c] !== PENDING);
    const missingRequired = requiredKeys.filter(k => !assignedSystem.has(k));
    const canContinue = pendingCols.length === 0 && missingRequired.length === 0 && !busy;

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
        if (v === EXTRA_OWNER) return "Dato del cliente";
        if (v === EXTRA_PET) return "Dato de la mascota";
        return "No se importa";
    };

    const handleContinue = () => {
        const clean = {};
        for (const [col, v] of Object.entries(mapping)) {
            if (v === PENDING) continue;
            clean[col] = v;
        }
        onContinue(clean);
    };

    // Picker de campos del sistema (búsqueda + botones agrupados). Reusado por
    // "Modificar" y por la opción secundaria de las cards pendientes.
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
                                            onClick={() => decide(col, f.key)}
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

    // Card de columna PENDIENTE — protagonista.
    const exceptionCard = (col) => {
        const idx = sourceColumns.indexOf(col);
        return (
            <div key={col} className={s.exceptionCard}>
                <p className={s.exceptionName}>No reconocimos «{col}»</p>
                <p className={s.colSample}>Ejemplos: {samplePreview(idx)}</p>
                <p className={s.colQuestion}>¿Qué contiene esta columna?</p>
                <div className={s.optList}>
                    <button type="button" className={s.optBtn} onClick={() => decide(col, EXTRA_OWNER)} disabled={busy}>
                        Guardarlo como dato del cliente
                    </button>
                    <button type="button" className={s.optBtn} onClick={() => decide(col, EXTRA_PET)} disabled={busy}>
                        Guardarlo como dato de la mascota
                    </button>
                    <button type="button" className={s.optBtn} onClick={() => decide(col, NO_IMPORT)} disabled={busy}>
                        No importar esta columna
                    </button>
                </div>
                <button type="button" className={s.sysLink} onClick={() => toggleSys(col)} disabled={busy}>
                    {sysOpen.has(col) ? "Ocultar campos del sistema" : "¿Es un campo del sistema? (nombre, teléfono…)"}
                </button>
                {sysOpen.has(col) && systemPicker(col, mapping[col])}
            </div>
        );
    };

    // Fila de columna RECONOCIDA dentro de la sección colapsable.
    const readyRow = (col) => {
        if (editing.has(col)) {
            return (
                <div key={col} className={s.readyEditing}>
                    <p className={s.colQuestion}>Modificar «{col}»</p>
                    {systemPicker(col, mapping[col])}
                    <div className={s.pickerExtra}>
                        <span className={s.pickerOr}>o guárdala como información del sistema anterior:</span>
                        <div className={s.pickerBtns}>
                            <button type="button" className={`${s.pickerBtn} ${mapping[col] === EXTRA_OWNER ? s.pickerBtnActive : ""}`} onClick={() => decide(col, EXTRA_OWNER)} disabled={busy}>Dato del cliente</button>
                            <button type="button" className={`${s.pickerBtn} ${mapping[col] === EXTRA_PET ? s.pickerBtnActive : ""}`} onClick={() => decide(col, EXTRA_PET)} disabled={busy}>Dato de la mascota</button>
                            <button type="button" className={s.pickerBtnGhost} onClick={() => decide(col, NO_IMPORT)} disabled={busy}>No importar</button>
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
                    onClick={() => openEdit(col)}
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
                    <span className={s.summaryReady}>✓ {readyCols.length} listas</span>
                    {pendingCols.length > 0 && (
                        <span className={s.summaryWarn}> · ⚠ {pendingCols.length} necesitan revisión</span>
                    )}
                </p>
            </div>

            {/* Excepciones primero — lo único que requiere acción. */}
            {pendingCols.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                    <p className={s.sectionLabel}>Necesitan tu revisión</p>
                    {pendingCols.map(exceptionCard)}
                </div>
            )}

            {/* Reconocidas — compactas, colapsadas por defecto. */}
            {readyCols.length > 0 && (
                <div className={s.readyBlock}>
                    <button
                        type="button"
                        className={s.readyToggle}
                        onClick={() => setReadyOpen(o => !o)}
                        aria-expanded={readyOpen}
                    >
                        <span>✓ {readyCols.length} columnas listas</span>
                        <span className={s.readyChevron}>{readyOpen ? "▲" : "▼"}</span>
                    </button>
                    {readyOpen && <div className={s.readyList}>{readyCols.map(readyRow)}</div>}
                </div>
            )}

            {pendingCols.length === 0 && missingRequired.length > 0 && (
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
