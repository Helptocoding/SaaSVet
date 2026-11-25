// Catálogo cerrado de especialidades (ADR p68). Copia del backend
// (apps/users/specialties.py): una prueba del backend exige que coincidan.
// Se guardan códigos; se muestran etiquetas, siempre en el orden del catálogo.
import CATALOG from "./specialties.json";

export const SPECIALTIES = CATALOG;
const LABELS = new Map(CATALOG);
const ORDER = CATALOG.map(([code]) => code);

export const specialtyLabel = (code) => LABELS.get(code) || "";

/** Códigos conocidos, sin repetir y en el orden del catálogo. */
export const orderSpecialties = (codes) => ORDER.filter((code) => (codes || []).includes(code));

export const specialtiesLabel = (codes) => orderSpecialties(codes).map(specialtyLabel).join(", ");

export const sameSpecialties = (a, b) => orderSpecialties(a).join("|") === orderSpecialties(b).join("|");
