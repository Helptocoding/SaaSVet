import { useEffect, useMemo, useState } from "react";
import s from "./imports.module.css";

/* Selector de destino de UNA columna del Excel (Fase D, rediseño UX).
   Reemplaza los botones directos + el picker inline. Es la ÚNICA decisión:
   "¿Qué representa esta columna?" → un campo del sistema, un dato histórico
   (sistema anterior) o no importar. Modal pequeño (clases globales .modal-*),
   sin librerías nuevas. NO toca backend: devuelve el mismo value que consume
   `choose()` en MappingStep (key del sistema | "owner.extra" | "pet.extra" | "").

   Props:
   - column        nombre original de la columna del Excel (solo display).
   - examples       string de ejemplos ("Rojo · Azul · Verde").
   - fieldCatalog   catálogo de campos (se filtran is_extra: van como opción fija).
   - value          selección actual (para resaltar).
   - assignedSystem Set de keys del sistema ya usadas por OTRAS columnas (deshabilita).
   - onPick(value)  callback al elegir.
   - onClose()      cerrar sin cambiar.
*/
const EXTRA_OWNER = "owner.extra";
const EXTRA_PET = "pet.extra";
const NO_IMPORT = "";

const normalize = (str) =>
    (str || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

const GROUP_ICON = { Cliente: "👤", Mascota: "🐾" };

const DestinationPicker = ({
    column,
    examples,
    fieldCatalog = [],
    value,
    assignedSystem,
    onPick,
    onClose,
}) => {
    const [q, setQ] = useState("");

    useEffect(() => {
        const onKey = (e) => { if (e.key === "Escape") onClose(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);

    // Campos del sistema agrupados (Cliente / Mascota), sin los is_extra.
    const systemGroups = useMemo(() => {
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
    }, [fieldCatalog]);

    const match = (label) => normalize(label).includes(normalize(q));

    const extraOptions = [
        { value: EXTRA_OWNER, label: "Conservar como información anterior del cliente" },
        { value: EXTRA_PET, label: "Conservar como información anterior de la mascota" },
    ].filter((o) => match(o.label));
    const showNoImport = match("No importar esta columna");

    return (
        <div className={s.pickerOverlay} onClick={onClose}>
            <div
                className={`modal modal-sm ${s.pickerModal}`}
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
                aria-label={`¿Qué representa ${column}?`}
            >
                <div className="modal-header">
                    <h3>¿Qué representa «{column}»?</h3>
                </div>
                <div className={`modal-body ${s.pickerBody}`}>
                    {examples && examples !== "—" && (
                        <p className={s.pickerExamples}>Ejemplos: {examples}</p>
                    )}
                    <input
                        className="select-input"
                        placeholder="Buscar…"
                        value={q}
                        autoFocus
                        onChange={(e) => setQ(e.target.value)}
                        aria-label="Buscar destino"
                    />

                    {systemGroups.map((g) => {
                        const fields = g.fields.filter((f) => match(f.label));
                        if (!fields.length) return null;
                        return (
                            <div key={g.name} className={s.pickerSection}>
                                <p className={s.pickerSectionName}>
                                    <span aria-hidden="true">{GROUP_ICON[g.name] || "•"}</span> {g.name}
                                </p>
                                {fields.map((f) => {
                                    const taken = assignedSystem.has(f.key) && value !== f.key;
                                    return (
                                        <button
                                            key={f.key}
                                            type="button"
                                            className={`${s.pickerOption} ${value === f.key ? s.pickerOptionActive : ""}`}
                                            disabled={taken}
                                            title={taken ? "Ya asignado a otra columna" : undefined}
                                            onClick={() => onPick(f.key)}
                                        >
                                            {f.label}
                                            {taken && <span className={s.pickerTaken}> · ya asignado</span>}
                                        </button>
                                    );
                                })}
                            </div>
                        );
                    })}

                    {extraOptions.length > 0 && (
                        <div className={s.pickerSection}>
                            <p className={s.pickerSectionName}>
                                <span aria-hidden="true">📦</span> Datos del sistema anterior
                            </p>
                            {extraOptions.map((o) => (
                                <button
                                    key={o.value}
                                    type="button"
                                    className={`${s.pickerOption} ${value === o.value ? s.pickerOptionActive : ""}`}
                                    onClick={() => onPick(o.value)}
                                >
                                    {o.label}
                                </button>
                            ))}
                        </div>
                    )}

                    {showNoImport && (
                        <div className={s.pickerSection}>
                            <p className={s.pickerSectionName}>
                                <span aria-hidden="true">🚫</span> No usar
                            </p>
                            <button
                                type="button"
                                className={`${s.pickerOption} ${s.pickerOptionGhost} ${value === NO_IMPORT ? s.pickerOptionActive : ""}`}
                                onClick={() => onPick(NO_IMPORT)}
                            >
                                No importar esta columna
                            </button>
                        </div>
                    )}
                </div>
                <div className="modal-footer">
                    <button className="btn btn-secondary btn-md" style={{ width: "100%" }} onClick={onClose}>
                        Cancelar
                    </button>
                </div>
            </div>
        </div>
    );
};

export default DestinationPicker;
