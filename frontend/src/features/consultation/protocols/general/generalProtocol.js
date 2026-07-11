import GeneralSection from "./GeneralSection";

/**
 * Protocolo clínico "General" — familia diagnóstica (SOAP).
 *
 * Captura la S (motivo + historia) y la O (exploración por sistemas) estructuradas.
 * El diagnóstico (A) y el plan (P) viven en el núcleo (MedicalRecord.diagnosis /
 * treatment), no aquí — por eso `validate` no bloquea: el cierre valida dx/tx en
 * el núcleo (close_medical_record).
 *
 * Se materializa como `ConsultationAssessment` en el backend al finalizar
 * (services._materialize_general), dentro del atomic del cierre. Un protocolo
 * NUNCA muta MedicalRecord (principio binding, ADR p50).
 *
 * Contrato mínimo `{ label, Section, initDraft, validate }`. `initDraft` rehidrata
 * desde consultation_draft.general al recargar (sobrevive recarga vía el autosave).
 */
export const generalProtocol = {
  label: "Valoración clínica",
  Section: GeneralSection,

  initDraft: (record) =>
    record?.consultation_draft?.general ?? {
      chief_complaint: "",
      history: "",
      exam: {},
      differentials: "",
      recheck_date: null,
    },

  // Nada bloquea el cierre desde el protocolo: la valoración es recomendada, no
  // obligatoria. El cierre exige diagnóstico + tratamiento en el núcleo.
  validate: () => ({}),
};
