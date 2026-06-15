import { useMemo, useState } from "react";
import s from "./imports.module.css";

// Estados posibles de una columna:
const PENDING = "__pending__";   // desconocida, sin decidir → bloquea continuar
const NO_IMPORT = "";            // "no necesito esta columna"
const EXTRA_OWNER = "owner.extra";
const EXTRA_PET = "pet.extra";

const normalize = (str) =>
    (str || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

function groupSystemFields(fieldCatalog) {
    const groups = [];
    const byName = new Map();
    for (const f of fieldCatalog) {
        if (f.is_extra) continue;            // los *.extra no van en el picker del sistema
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

/* Paso 2 — Relacionar columnas (rediseño Fase D, lenguaje humano).
   - Columna RECONOCIDA (el sistema sugirió un campo) → confirmada + "Cambiar".
   - Columna DESCONOCIDA → "¿Qué hacemos con «X»?" con opciones claras; queda
     "pendiente de decidir" y BLOQUEA continuar hasta que el usuario elija (por
     consentimiento, para no meter "Facebook" en la mascota por inercia).
   - "Cambiar" / decidir abre un picker COMPACTO con búsqueda (no el select gigante)
     + guardar como dato del cliente / de la mascota / no importar. */
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

    // Semilla: columna con sugerencia/decisión previa → ese valor; sin nada → PENDING.
    const [mapping, setMapping] = useState(() => {
        const seed = {};
        for (const col of sourceColumns) {
            const v = initialMapping[col];
            seed[col] = v === undefined ? PENDING : v;
        }
        return seed;
    });
    const [editing, setEditing] = useState(() => new Set());  // columnas expandidas
    const [search, setSearch] = useState({});                 // texto de búsqueda por columna

    const isSystem = (v) => systemKeys.has(v);

    const assignedSystem = useMemo(
        () => new Set(Object.values(mapping).filter(isSystem)),
        [mapping]  // eslint-disable-line react-hooks/exhaustive-deps
    );

    const decide = (col, value) => {
        setMapping(prev => ({ ...prev, [col]: value }));
        setEditing(prev => { const n = new Set(prev); n.delete(col); return n; });
    };
    const openEdit = (col) => setEditing(prev => new Set(prev).add(col));

    const pendingCols = sourceColumns.filter(c => mapping[c] === PENDING);
    const recognizedCount = sourceColumns.filter(c => isSystem(mapping[c])).length;
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

    const handleContinue = () => {
        // Enviar toda columna decidida (incluye "" = no importar y los *.extra);
        // PENDING nunca llega (continuar está bloqueado).
        const clean = {};
        for (const [col, v] of Object.entries(mapping)) {
            if (v === PENDING) continue;
            clean[col] = v;
        }
        onContinue(clean);
    };

    const renderPicker = (col, current) => {
        const q = search[col] || "";
        return (
            <div className={s.colPicker}>
                {current === PENDING && (
                    <p className={s.colQuestion}>¿Qué hacemos con «{col}»?</p>
                )}
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
                <div className={s.pickerExtra}>
                    <span className={s.pickerOr}>o guárdala como información del sistema anterior:</span>
                    <div className={s.pickerBtns}>
                        <button
                            type="button"
                            className={`${s.pickerBtn} ${current === EXTRA_OWNER ? s.pickerBtnActive : ""}`}
                            onClick={() => decide(col, EXTRA_OWNER)}
                            disabled={busy}
                        >
                            Guardar como dato del cliente
                        </button>
                        <button
                            type="button"
                            className={`${s.pickerBtn} ${current === EXTRA_PET ? s.pickerBtnActive : ""}`}
                            onClick={() => decide(col, EXTRA_PET)}
                            disabled={busy}
                        >
                            Guardar como dato de la mascota
                        </button>
                        <button
                            type="button"
                            className={s.pickerBtnGhost}
                            onClick={() => decide(col, NO_IMPORT)}
                            disabled={busy}
                        >
                            No necesito esta columna
                        </button>
                    </div>
                </div>
            </div>
        );
    };

    const renderDecided = (col, v) => {
        let text;
        let muted = false;
        if (isSystem(v)) text = <>✓ Se importará como <strong>«{labelByKey[v]}»</strong></>;
        else if (v === EXTRA_OWNER) text = <>Se guardará como dato del cliente</>;
        else if (v === EXTRA_PET) text = <>Se guardará como dato de la mascota</>;
        else { text = "No se importará"; muted = true; }
        return (
            <div className={s.colDecided}>
                <span className={muted ? s.colMuted : s.colOk}>{text}</span>
                <button
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={() => openEdit(col)}
                    disabled={busy}
                    aria-label={`Cambiar columna ${col}`}
                >
                    Cambiar
                </button>
            </div>
        );
    };

    return (
        <div>
            <div className="card" style={{ marginBottom: 16, padding: "16px 20px" }}>
                <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 3 }}>
                    Revisa qué hacer con cada columna
                </p>
                <p style={{ fontSize: 12.5, color: "var(--c-text-2)" }}>
                    {sourceColumns.length} columnas · {recognizedCount} reconocidas
                    {pendingCols.length > 0 && <> · <strong>{pendingCols.length} por decidir</strong></>}
                </p>
            </div>

            <div className={s.colList}>
                {sourceColumns.map((col, idx) => {
                    const v = mapping[col];
                    const expanded = v === PENDING || editing.has(col);
                    return (
                        <div key={col} className={`${s.colCard} ${v === PENDING ? s.colCardPending : ""}`}>
                            <div className={s.colHead}>
                                <span className={s.colName}>{col}</span>
                                <span className={s.colSample} title={samplePreview(idx)}>
                                    ej: {samplePreview(idx)}
                                </span>
                            </div>
                            {expanded ? renderPicker(col, v) : renderDecided(col, v)}
                        </div>
                    );
                })}
            </div>

            {pendingCols.length > 0 && (
                <div className={s.missingBox}>
                    Hay {pendingCols.length === 1 ? "una columna" : `${pendingCols.length} columnas`} por
                    decidir. Elige qué hacer con cada una para continuar.
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
