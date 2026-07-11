import SurgerySection from "./SurgerySection";

/**
 * Protocolo clínico "Cirugía" (A3) — grupos PreOp · Procedimiento · Recuperación.
 * Contrato mínimo { label, Section, initDraft, validate }. Sin persistencia: el
 * SurgeryRecord lo materializa el backend al finalizar (services._materialize_surgery).
 *
 * `value` = { preop_diagnosis, surgery_type, asa_class, asa_emergency,
 *             anesthesia_type, procedure, wound_class, findings, complications,
 *             postop_instructions, suture_removal_date }
 */
export const surgeryProtocol = {
  label: "Cirugía",
  Section: SurgerySection,

  initDraft: (record) =>
    record?.consultation_draft?.surgery ?? {
      preop_diagnosis: "",
      surgery_type: "",
      asa_class: "",
      asa_emergency: false,
      anesthesia_type: "",
      procedure: "",
      wound_class: "",
      findings: "",
      complications: "Ninguna",
      postop_instructions: "",
      suture_removal_date: null,
    },

  validate: (d) => {
    const errors = {};
    const missing = [];
    if (!d?.surgery_type) missing.push("tipo de cirugía");
    if (!d?.asa_class) missing.push("clasificación ASA");
    if (!d?.anesthesia_type) missing.push("tipo de anestesia");
    if (!(d?.procedure || "").trim()) missing.push("procedimiento realizado");
    if (!(d?.postop_instructions || "").trim()) missing.push("indicaciones postoperatorias");
    if (missing.length) {
      errors.surgery = [`Completa el parte quirúrgico: ${missing.join(", ")}.`];
    }
    return errors;
  },
};
