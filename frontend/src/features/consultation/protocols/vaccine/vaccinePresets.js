/**
 * Catálogo de vacunas comunes (es-MX).
 *
 * ESTÁTICO hoy, pero la forma está pensada para volverse un catálogo
 * configurable por organización sin refactorizar a los consumidores: el
 * acceso pasa siempre por `getVaccinePresets()` (accessor único). Cuando
 * migre a backend, solo cambia el accessor (de const a fetch), no la UI.
 *
 * Campos por preset:
 *  - id            estable (futura PK / FK del catálogo)
 *  - name          nombre visible de la vacuna
 *  - species       códigos de SPECIES_CHOICES (patients/models.py) a los que aplica
 *  - boosterMonths intervalo de refuerzo recomendado en meses (null = sin refuerzo default)
 *
 * Extender = agregar un objeto aquí. No hardcodear vacunas en componentes.
 */
export const VACCINE_PRESETS = [
  { id: "rabia", name: "Rabia", species: ["canino", "felino"], boosterMonths: 12 },
  { id: "parvovirus", name: "Parvovirus", species: ["canino"], boosterMonths: 12 },
  { id: "moquillo", name: "Moquillo / Triple", species: ["canino"], boosterMonths: 12 },
  { id: "octuple", name: "Óctuple", species: ["canino"], boosterMonths: 12 },
  { id: "triple_felina", name: "Triple felina", species: ["felino"], boosterMonths: 12 },
  { id: "leucemia_felina", name: "Leucemia felina", species: ["felino"], boosterMonths: 12 },
  { id: "bordetella", name: "Bordetella (tos de las perreras)", species: ["canino"], boosterMonths: 12 },
  // futuro org-config: source:'system'|'org', organization_id, active, order
];

/**
 * Presets aplicables a una especie. Sin `species` → todos. Si ninguna coincide
 * (p.ej. especie exótica sin protocolo), devuelve el catálogo completo para no
 * dejar al usuario sin opciones (siempre queda además "Otra vacuna").
 */
export const getVaccinePresets = ({ species } = {}) => {
  if (!species) return VACCINE_PRESETS;
  const matches = VACCINE_PRESETS.filter((p) => p.species.includes(species));
  return matches.length ? matches : VACCINE_PRESETS;
};

export const getVaccinePreset = (id) =>
  VACCINE_PRESETS.find((p) => p.id === id) || null;

/**
 * Fecha de próximo refuerzo = fecha de aplicación + N meses.
 * Devuelve "YYYY-MM-DD" o null (si falta fecha base o el preset no tiene refuerzo).
 */
export const computeNextDue = (applicationDate, boosterMonths) => {
  if (!applicationDate || boosterMonths == null) return null;
  const base = new Date(`${applicationDate}T00:00:00`);
  if (Number.isNaN(base.getTime())) return null;
  base.setMonth(base.getMonth() + boosterMonths);
  const y = base.getFullYear();
  const m = String(base.getMonth() + 1).padStart(2, "0");
  const d = String(base.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
};

/** Fecha local de hoy en formato "YYYY-MM-DD" (para default de aplicación). */
export const todayISO = () => {
  const t = new Date();
  const y = t.getFullYear();
  const m = String(t.getMonth() + 1).padStart(2, "0");
  const d = String(t.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
};
