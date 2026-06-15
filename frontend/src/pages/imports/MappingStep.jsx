import { useMemo, useState } from "react";
import s from "./imports.module.css";

// Valor de <option> que significa "esta columna no se importa".
const NONE = "";

// Importancia del campo destino → etiqueta humana + clase de badge global.
const IMPORTANCE = {
    required: { label: "Obligatorio", cls: "badge-danger" },
    recommended: { label: "Recomendado", cls: "badge-warning" },
    optional: { label: "Opcional", cls: "badge-default" },
};

/* Agrupa el field_catalog por su `group` (Cliente / Mascota) preservando el
   orden de aparición. El backend entrega labels humanos ("Nombre del cliente",
   no "Cliente · Nombre"; legacy_id como "Nº de expediente anterior"). */
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

/* Paso 2 — Relaciona cada columna del archivo con un campo del sistema.
   Una fila por columna: nombre + ejemplos + selector de campo (agrupado
   Cliente/Mascota, con "No importar columna") + el tipo del campo elegido
   (Obligatorio/Recomendado/Opcional). Solo Nombre del cliente y Nombre de la
   mascota son obligatorios; el resto no bloquea la importación. */
const MappingStep = ({
    sourceColumns = [],
    sampleRows = [],
    fieldCatalog = [],
    initialMapping = {},
    onContinue,
    onBack,
    busy = false,
}) => {
    const [mapping, setMapping] = useState(() => {
        const seed = {};
        for (const col of sourceColumns) {
            seed[col] = initialMapping[col] || NONE;
        }
        return seed;
    });

    const groups = useMemo(() => groupCatalog(fieldCatalog), [fieldCatalog]);

    const metaByKey = useMemo(() => {
        const m = {};
        for (const f of fieldCatalog) m[f.key] = f;
        return m;
    }, [fieldCatalog]);

    const labelByKey = useMemo(() => {
        const m = {};
        for (const f of fieldCatalog) m[f.key] = f.label;
        return m;
    }, [fieldCatalog]);

    const requiredKeys = useMemo(
        () => fieldCatalog.filter(f => f.importance === "required").map(f => f.key),
        [fieldCatalog]
    );
    const recommendedKeys = useMemo(
        () => fieldCatalog.filter(f => f.importance === "recommended").map(f => f.key),
        [fieldCatalog]
    );

    const assignedKeys = useMemo(
        () => new Set(Object.values(mapping).filter(Boolean)),
        [mapping]
    );

    const missingRequired = requiredKeys.filter(k => !assignedKeys.has(k));
    const missingRecommended = recommendedKeys.filter(k => !assignedKeys.has(k));
    const canContinue = missingRequired.length === 0 && !busy;

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
        // Solo enviamos columnas con destino real (omitimos "No importar columna").
        const clean = {};
        for (const [col, key] of Object.entries(mapping)) {
            if (key) clean[col] = key;
        }
        onContinue(clean);
    };

    // Badge del tipo de campo elegido para una columna (o "No se importa").
    const typeBadge = (key) => {
        if (!key) return <span className={s.skipTag}>No se importa</span>;
        const imp = IMPORTANCE[metaByKey[key]?.importance] || IMPORTANCE.optional;
        return <span className={`badge ${imp.cls}`}>{imp.label}</span>;
    };

    return (
        <div>
            <div className="card" style={{ marginBottom: 18, padding: "16px 20px" }}>
                <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 3 }}>
                    Relaciona tus columnas con los campos del sistema
                </p>
                <p style={{ fontSize: 12.5, color: "var(--c-text-2)" }}>
                    Detectamos {sourceColumns.length} columna{sourceColumns.length === 1 ? "" : "s"} en
                    tu archivo. Elige a qué dato corresponde cada una. Las columnas que no
                    necesites déjalas en <em>No importar columna</em>.
                </p>
            </div>

            <div className={s.mapWrap}>
                <table className={s.mapTable}>
                    <thead>
                        <tr>
                            <th>Columna del archivo</th>
                            <th>Ejemplos</th>
                            <th>Se importa como</th>
                            <th>Importancia</th>
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
                                        <option value={NONE}>No importar columna</option>
                                        {groups.map(g => (
                                            <optgroup key={g.name} label={g.name}>
                                                {g.fields.map(f => (
                                                    <option key={f.key} value={f.key}>
                                                        {f.label}
                                                    </option>
                                                ))}
                                            </optgroup>
                                        ))}
                                    </select>
                                </td>
                                <td>{typeBadge(mapping[col])}</td>
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

            {missingRequired.length === 0 && missingRecommended.length > 0 && (
                <div className={s.recommendBox}>
                    Puedes continuar. Te recomendamos también asignar, si tu archivo los tiene:{" "}
                    {missingRecommended.map(k => labelByKey[k] || k).join(", ")}.
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
