import { useMemo, useState } from "react";
import s from "./imports.module.css";

// Valor de <option> que significa "esta columna no se importa".
const NONE = "";

/* Agrupa el field_catalog por su `group` preservando el orden de aparición.
   El backend ya entrega labels amistosos (incluido el de legacy_id, que NUNCA
   se muestra como "legacy_id" sino como "Nº de expediente anterior"). */
function groupCatalog(fieldCatalog) {
    const groups = [];
    const byName = new Map();
    for (const field of fieldCatalog) {
        const name = field.group || "Otros";
        if (!byName.has(name)) {
            const bucket = { name, fields: [] };
            byName.set(name, bucket);
            groups.push(bucket);
        }
        byName.get(name).fields.push(field);
    }
    return groups;
}

/* Paso 2 — Mapeo columna → campo.
   Una fila por cada columna del archivo; cada fila muestra el nombre de la
   columna + sus primeros valores de muestra + un <select> con los campos del
   catálogo agrupados. El padre (index.jsx) recibe el mapping final en onContinue
   y se encarga del PATCH mapping + POST validate. */
const MappingStep = ({
    sourceColumns = [],
    sampleRows = [],
    fieldCatalog = [],
    initialMapping = {},
    onContinue,
    onBack,
    busy = false,
}) => {
    // mapping: { <sourceColumn>: <targetFieldKey> }. Pre-cargado con la sugerencia.
    const [mapping, setMapping] = useState(() => {
        const seed = {};
        for (const col of sourceColumns) {
            seed[col] = initialMapping[col] || NONE;
        }
        return seed;
    });

    const groups = useMemo(() => groupCatalog(fieldCatalog), [fieldCatalog]);

    // Labels por key, para mostrar el nombre amistoso del campo faltante.
    const labelByKey = useMemo(() => {
        const m = {};
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);

    const requiredKeys = useMemo(
        () => fieldCatalog.filter(f => f.required).map(f => f.key),
        [fieldCatalog]
    );

    // Conjunto de keys efectivamente asignadas a alguna columna.
    const assignedKeys = useMemo(
        () => new Set(Object.values(mapping).filter(Boolean)),
        [mapping]
    );

    const missingRequired = requiredKeys.filter(k => !assignedKeys.has(k));
    const canContinue = missingRequired.length === 0 && !busy;

    // Muestra los primeros valores no vacíos de la columna (hasta 3).
    const samplePreview = (colIndex) => {
        const vals = [];
        for (const row of sampleRows) {
            const cell = row?.[colIndex];
            if (cell !== undefined && cell !== null && String(cell).trim() !== "") {
                vals.push(String(cell));
            }
            if (vals.length >= 3) break;
        }
        return vals.length ? vals.join(" · ") : "—";
    };

    const updateColumn = (col, value) => {
        setMapping(prev => ({ ...prev, [col]: value }));
    };

    const handleContinue = () => {
        // Solo enviamos columnas con destino real (omitimos las "(no importar)").
        const clean = {};
        for (const [col, key] of Object.entries(mapping)) {
            if (key) clean[col] = key;
        }
        onContinue(clean);
    };

    return (
        <div>
            <div className="card" style={{ marginBottom: 18, padding: "16px 20px" }}>
                <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 3 }}>Relaciona tus columnas con los campos del sistema</p>
                <p style={{ fontSize: 12.5, color: "var(--c-text-2)" }}>
                    Detectamos {sourceColumns.length} columna{sourceColumns.length === 1 ? "" : "s"} en tu archivo.
                    Indica a qué dato corresponde cada una. Las columnas que no necesites
                    déjalas en <em>(no importar)</em>.
                </p>
            </div>

            <div className={s.mapWrap}>
                <table className={s.mapTable}>
                    <thead>
                        <tr>
                            <th>Columna del archivo</th>
                            <th>Ejemplos</th>
                            <th>Campo del sistema</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sourceColumns.map((col, colIndex) => (
                            <tr key={col}>
                                <td className={s.srcCol}>{col}</td>
                                <td>
                                    <span className={s.sampleVals} title={samplePreview(colIndex)}>
                                        {samplePreview(colIndex)}
                                    </span>
                                </td>
                                <td>
                                    <select
                                        className={`select-input ${s.mapSelect}`}
                                        value={mapping[col] ?? NONE}
                                        onChange={(e) => updateColumn(col, e.target.value)}
                                        disabled={busy}
                                        aria-label={`Campo del sistema para la columna ${col}`}
                                    >
                                        <option value={NONE}>(no importar)</option>
                                        {groups.map(g => (
                                            <optgroup key={g.name} label={g.name}>
                                                {g.fields.map(f => (
                                                    <option key={f.key} value={f.key}>
                                                        {f.label}{f.required ? " *" : ""}
                                                    </option>
                                                ))}
                                            </optgroup>
                                        ))}
                                    </select>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {missingRequired.length > 0 && (
                <div className={s.missingBox}>
                    Falta asignar {missingRequired.length === 1 ? "un campo obligatorio" : "campos obligatorios"}:
                    <ul>
                        {missingRequired.map(k => (
                            <li key={k}>{labelByKey[k] || k}</li>
                        ))}
                    </ul>
                </div>
            )}

            <div className={s.actions}>
                <button className="btn btn-secondary btn-md" onClick={onBack} disabled={busy}>
                    Atrás
                </button>
                <div className={s.actionsRight}>
                    <button
                        className="btn btn-primary btn-md"
                        onClick={handleContinue}
                        disabled={!canContinue}
                    >
                        {busy ? "Validando..." : "Continuar"}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default MappingStep;
