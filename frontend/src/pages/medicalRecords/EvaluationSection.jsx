import { forwardRef } from "react";
import { motion } from "framer-motion";
import styles from "./consultationForm.module.css";

const EvaluationSection = forwardRef(function EvaluationSection(
  { draft, consultationTypes, formErrors, onChange, onClearError, disabled },
  ref
) {
  return (
    <motion.section
      ref={ref}
      className={styles.card}
      data-consult-step="eval"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Evaluación</h2>
        <p className={styles.cardDesc}>Tipo de consulta, notas y diagnóstico clínico</p>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Tipo de consulta</label>
        <div className={styles.typeGrid}>
          {consultationTypes.map((t, idx) => (
            <motion.button
              key={t.value}
              type="button"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: idx * 0.05 }}
              whileHover={disabled ? undefined : { scale: 1.02 }}
              whileTap={disabled ? undefined : { scale: 0.98 }}
              className={`${styles.typeCard} ${
                draft.consultation_type === t.value ? styles.typeCardActive : ""
              }`}
              disabled={disabled}
              onClick={() => onChange({ consultation_type: t.value })}
            >
              <span className={styles.typeIcon}>{t.icon}</span>
              <span>
                <span className={styles.typeName}>{t.label}</span>
                <span className={styles.typeDesc}>{t.desc}</span>
              </span>
            </motion.button>
          ))}
        </div>
      </div>

      <div className={styles.editorColumn}>
        <div className={styles.field}>
          <label className={`${styles.fieldLabel} ${styles.fieldLabelMinimal}`}>Notas</label>
          <textarea
            className={`${styles.control} ${styles.editorTextarea} ${formErrors.notes ? styles.fieldError : ""}`}
            placeholder="Notas generales de la consulta..."
            value={draft.notes}
            disabled={disabled}
            onChange={(e) => {
              onChange({ notes: e.target.value });
              if (formErrors.notes) onClearError("notes");
            }}
          />
          {formErrors.notes && (
            <div className={styles.fieldErrorMessage}>{formErrors.notes[0]}</div>
          )}
        </div>

        <div className={styles.field}>
          <label className={`${styles.fieldLabel} ${styles.fieldLabelMinimal}`}>
            Diagnóstico <span className={styles.req}>*</span>
          </label>
          <textarea
            className={`${styles.control} ${styles.editorTextarea} ${styles.inputRequired} ${formErrors.diagnosis ? styles.fieldError : ""}`}
            placeholder="Comienza a escribir..."
            value={draft.diagnosis}
            disabled={disabled}
            onChange={(e) => {
              onChange({ diagnosis: e.target.value });
              if (formErrors.diagnosis) onClearError("diagnosis");
            }}
          />
          {formErrors.diagnosis && (
            <div className={styles.fieldErrorMessage}>{formErrors.diagnosis[0]}</div>
          )}
        </div>
      </div>
    </motion.section>
  );
});

export default EvaluationSection;
