import { Icon } from "./icons";
import { isCanino, isFelino } from "../utils/petFilters";
import s from "./EntitySearch.module.css";

/**
 * Renderers de opción ricos compartidos por todos los `EntitySearch` de
 * entidades clínicas. Fuente única: no rearmar el label por módulo (citas,
 * historial, POS, recetas). Muestran el contexto que diferencia homónimos
 * (dueño · teléfono · expediente), no solo el nombre.
 */

const speciesVisual = (species) => {
    const probe = { species };
    if (isCanino(probe)) return { bg: "#dbeafe", color: "#3b82f6", I: Icon.Dog };
    if (isFelino(probe)) return { bg: "#fce7f3", color: "#ec4899", I: Icon.Cat };
    return { bg: "var(--c-subtle)", color: "var(--c-text-2)", I: Icon.Paw };
};

// minúsculas a propósito: se invocan como función (renderItem(item)), no como
// componentes JSX → evita el ruido de react/jsx sobre "componentes sin usar".
export const renderPetOption = (pet) => {
    const v = speciesVisual(pet.species);
    const SpIcon = v.I;
    const sub = [
        pet.owner?.name,
        pet.owner?.phone,
        pet.legacy_id && `Exp #${pet.legacy_id}`,
        !pet.owner?.name && pet.breed,   // sin dueño → al menos la raza como pista
    ].filter(Boolean).join(" · ");
    return (
        <div className={s.optRow}>
            <div className={s.optIcon} style={{ background: v.bg }}>
                <SpIcon s={16} c={v.color} />
            </div>
            <div className={s.optBody}>
                <div className={s.optName}>{pet.name}{pet.species ? ` · ${pet.species}` : ""}</div>
                <div className={s.optSub}>{sub || "Sin datos del dueño"}</div>
            </div>
        </div>
    );
};

export const renderOwnerOption = (owner) => {
    const sub = [owner.phone, owner.legacy_id && `Exp #${owner.legacy_id}`].filter(Boolean).join(" · ");
    return (
        <div className={s.optRow}>
            <div className={s.optIcon} style={{ background: "var(--c-subtle)" }}>
                <Icon.User s={15} c="var(--c-text-2)" />
            </div>
            <div className={s.optBody}>
                <div className={s.optName}>{owner.name}</div>
                <div className={s.optSub}>{sub || "Sin teléfono"}</div>
            </div>
        </div>
    );
};

// Texto del input tras seleccionar (más contexto que el nombre solo).
export const petOptionLabel = (pet) =>
    pet?.owner?.name ? `${pet.name} — ${pet.owner.name}` : (pet?.name ?? "");

export const ownerOptionLabel = (owner) =>
    owner?.phone ? `${owner.name} — ${owner.phone}` : (owner?.name ?? "");
