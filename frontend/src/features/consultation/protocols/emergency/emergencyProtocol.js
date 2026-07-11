import EmergencySection from "./EmergencySection";

/** "YYYY-MM-DDTHH:mm" local (para inputs datetime-local). */
export const nowLocalDateTime = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};

/**
 * Protocolo clínico "Urgencia" (A3). Gira alrededor del tiempo y el outcome. La UI
 * muestra "Evaluación rápida" (semáforos) y guarda por detrás A/B/C. Sin persistencia:
 * el EmergencyRecord lo materializa el backend al finalizar (services._materialize_emergency).
 *
 * `value` = { arrived_at, triage_at, stabilized_at, discharged_at, triage_level,
 *             airway_status, breathing_status, circulation_status, chief_complaint,
 *             stabilization_actions, response, discharge_status, reassessment_date }
 */
export const emergencyProtocol = {
  label: "Urgencia",
  Section: EmergencySection,

  initDraft: (record) =>
    record?.consultation_draft?.emergency ?? {
      arrived_at: nowLocalDateTime(),
      triage_at: nowLocalDateTime(),
      stabilized_at: null,
      discharged_at: null,
      triage_level: "",
      airway_status: "normal",
      breathing_status: "normal",
      circulation_status: "normal",
      chief_complaint: "",
      stabilization_actions: "",
      response: "",
      discharge_status: "",
      reassessment_date: null,
    },

  validate: (d) => {
    const errors = {};
    const missing = [];
    if (!d?.arrived_at) missing.push("hora de llegada");
    if (!d?.triage_at) missing.push("hora de triage");
    if (!d?.triage_level) missing.push("nivel de triage");
    if (!(d?.chief_complaint || "").trim()) missing.push("problema principal");
    if (!(d?.stabilization_actions || "").trim()) missing.push("acciones de estabilización");
    if (!d?.discharge_status) missing.push("estado al egreso");
    if (missing.length) {
      errors.emergency = [`Completa la urgencia: ${missing.join(", ")}.`];
    }
    if (d?.arrived_at && d?.triage_at && d.triage_at < d.arrived_at) {
      errors.emergency = ["El triage no puede ser anterior a la hora de llegada."];
    }
    return errors;
  },
};
