import { useEffect, useMemo, useState } from "react";
import s from "./imports.module.css";
import { Icon } from "../../components/icons";

/* Selector de destino de UNA columna del Excel (Fase D, rediseño UX).
   Acordeón de categorías: cada una se despliega hacia abajo al seleccionarla y
   solo una está abierta a la vez (abrir otra cierra la anterior). Sin buscador
   (con pocas categorías confundía). Modal pequeño (clases globales .modal-*),
   sin librerías nuevas. NO toca backend: devuelve el mismo value que consume
   `choose()` en MappingStep (key del sistema | "*.extra" | "").

   Los destinos "extra" se derivan del fieldCatalog (is_extra) — sin hardcodear
   entidades; los textos legados de owner_pet se preservan vía EXTRA_OPTION_LABELS.

   Props:
   - column         nombre original de la columna del Excel (solo display).
   - examples       string de ejemplos ("Rojo · Azul · Verde").
   - fieldCatalog   catálogo de campos (los is_extra van como categoría histórica).
   - value          selección actual (para resaltar / abrir su categoría).
   - assignedSystem Set de keys del sistema ya usadas por OTRAS columnas (deshabilita).
   - onPick(value)  callback al elegir.
   - onClose()      cerrar sin cambiar.
*/
const NO_IMPORT = "";
const EXTRA_OPTION_LABELS = {
    "owner.extra": "Conservar como información anterior del cliente",
    "pet.extra": "Conservar como información anterior de la mascota",
};

const DestinationPicker = ({
    column,
    examples,
    fieldCatalog = [],
    value,
    assignedSystem,
    onPick,
    onClose,
}) => {
    // Categorías del acordeón: campos del sistema agrupados + histórico + no usar.
    const sections = useMemo(() => {
        const byGroup = {};
        for (const f of fieldCatalog) {
            if (f.is_extra) continue;
            const g = f.group || "Otros";
            (byGroup[g] ||= []).push(f);
        }
        const out = [];
        const sysSection = (name, icon, fields) => ({
            id: name,
            name,
            icon,
            options: fields.map((f) => ({ value: f.key, label: f.label, system: true })),
        });
        if (byGroup.Cliente) out.push(sysSection("Cliente", "User", byGroup.Cliente));
        if (byGroup.Mascota) out.push(sysSection("Mascota", "Paw", byGroup.Mascota));
        if (byGroup.Producto) out.push(sysSection("Producto", "Box", byGroup.Producto));
        if (byGroup["Presentación"]) out.push(sysSection("Presentación", "FileText", byGroup["Presentación"]));
        for (const g of Object.keys(byGroup)) {
            if (!["Cliente", "Mascota", "Producto", "Presentación"].includes(g)) {
                out.push(sysSection(g, "FileText", byGroup[g]));
            }
        }
        const extraOptions = fieldCatalog
            .filter((f) => f.is_extra)
            .map((f) => ({
                value: f.key,
                label: EXTRA_OPTION_LABELS[f.key] ?? `Conservar como ${f.label.toLowerCase()}`,
            }));
        if (extraOptions.length > 0) {
            out.push({
                id: "extra",
                name: "Datos del sistema anterior",
                icon: "Box",
                options: extraOptions,
            });
        }
        out.push({
            id: "no",
            name: "No usar",
            icon: "X",
            options: [{ value: NO_IMPORT, label: "No importar esta columna", ghost: true }],
        });
        return out;
    }, [fieldCatalog]);

    // Abrir de inicio la categoría que ya contiene la selección actual (si hay).
    const initialOpen = useMemo(() => {
        if (value === undefined) return null;
        for (const sec of sections) {
            if (sec.options.some((o) => o.value === value)) return sec.id;
        }
        return null;
    }, [sections, value]);
    const [open, setOpen] = useState(initialOpen);

    useEffect(() => {
        const onKey = (e) => { if (e.key === "Escape") onClose(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);

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
                    <div className={s.accordion}>
                        {sections.map((sec) => {
                            const isOpen = open === sec.id;
                            const SecIcon = Icon[sec.icon];
                            return (
                                <div key={sec.id} className={s.accSection}>
                                    <button
                                        type="button"
                                        className={s.accHeader}
                                        aria-expanded={isOpen}
                                        onClick={() => setOpen(isOpen ? null : sec.id)}
                                    >
                                        <span className={s.accIcon} aria-hidden="true">
                                            <SecIcon s={16} />
                                        </span>
                                        <span className={s.accName}>{sec.name}</span>
                                        <span className={s.accChevron} aria-hidden="true">
                                            {isOpen ? <Icon.ChevronDown s={16} /> : <Icon.ChevronRight s={16} />}
                                        </span>
                                    </button>
                                    {isOpen && (
                                        <div className={s.accBody}>
                                            {sec.options.map((o) => {
                                                const taken =
                                                    o.system && assignedSystem.has(o.value) && value !== o.value;
                                                return (
                                                    <button
                                                        key={o.value || "no-import"}
                                                        type="button"
                                                        className={`${s.pickerOption} ${o.ghost ? s.pickerOptionGhost : ""} ${value === o.value ? s.pickerOptionActive : ""}`}
                                                        disabled={taken}
                                                        title={taken ? "Ya asignado a otra columna" : undefined}
                                                        onClick={() => onPick(o.value)}
                                                    >
                                                        {o.label}
                                                        {taken && <span className={s.pickerTaken}> · ya asignado</span>}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
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
