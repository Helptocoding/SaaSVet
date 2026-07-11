import VaccineSection from "./VaccineSection";
import { todayISO } from "./vaccinePresets";

/**
 * Protocolo clínico "Vacuna" — primer protocolo de referencia.
 *
 * Contrato mínimo (crece por evidencia, no por anticipación):
 *   - label     nombre clínico de la sección
 *   - Section   componente presentacional de captura
 *   - initDraft (record) → estado inicial del slice; rehidrata desde
 *               consultation_draft.vaccine al reabrir/recargar
 *   - validate  (draft) → { field: [msg] } (vacío = ok), corrido antes de finalizar
 *
 * NO tiene método de persistencia: la materialización del VaccineRecord vive en
 * el backend (apply_consultation_draft_on_close), dentro del atomic del cierre.
 */
export const vaccineProtocol = {
  label: "Vacuna aplicada",
  Section: VaccineSection,

  initDraft: (record) =>
    record?.consultation_draft?.vaccine ?? {
      presetId: null,
      vaccine_name: "",
      application_date: todayISO(),
      scheduleBooster: false,
      next_due_date: null,
      notes: "",
      _boosterMonths: null,
      _boosterEdited: false,
      // A2 — vínculo opcional a inventario + lote.
      product_id: null,
      product_public_id: null,
      product_name: "",
      product_tracks_lots: false,
      lot_id: null,
      lot_label: null,
    },

  validate: (d) => {
    const errors = {};
    // A2: si se ligó un producto lote-trackeado, el lote es obligatorio.
    if (d?.product_id && d?.product_tracks_lots && !d?.lot_id) {
      errors.vaccine = ["Selecciona el lote de la vacuna a aplicar."];
      return errors;
    }
    if (d?.scheduleBooster) {
      if (!d.next_due_date) {
        errors.vaccine = [
          "Indica la fecha del próximo refuerzo o desactiva “Programar próximo refuerzo”.",
        ];
      } else if (d.application_date && d.next_due_date <= d.application_date) {
        errors.vaccine = ["El refuerzo debe ser posterior a la fecha de aplicación."];
      }
    }
    return errors;
  },
};
