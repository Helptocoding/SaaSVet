import { forwardRef } from "react";
import { motion } from "framer-motion";
import { Icon } from "../../components/icons";
import styles from "./consultationForm.module.css";

/**
 * Sección "Evaluación" (presentacional): tipo de consulta (selección única),
 * motivo y diagnóstico clínico (obligatorio). Sin chips de sugerencia (no hay
 * fuente de datos en backend todavía).
 *
 * Recibe `ref` para que el container pueda hacer scroll a esta sección cuando
 * una validación de cierre falla en uno de sus campos.
 */
const EvaluationSection = forwardRef(function EvaluationSection(
  { draft, consultationTypes, formErrors, onChange, onClearError, disabled },
  ref
) {
  return (
    <motion.section
      ref={ref}
      className={styles.section}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className={styles.secHead}>
        <div className={styles.secIcon}>
          <Icon.Stethoscope s={17} />
        </div>
        <div>
          <h2 className={styles.secTitle}>Evaluación</h2>
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Tipo de consulta</label>
        <div className={styles.typeGrid}>
          {consultationTypes.map((t) => (
            <motion.button
              key={t.value}
              type="button"
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
                <span className={styles.typeDesc} style={{ display: "block" }}>
                  {t.desc}
                </span>
              </span>
            </motion.button>
          ))}
        </div>
      </div>

      <div className={styles.grid2}>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Motivo de consulta</label>
          <textarea
            className={`${styles.control} ${formErrors.notes ? styles.fieldError : ""}`}
            placeholder="Tos seca persistente desde hace 4 días…"
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
          <label className={styles.fieldLabel}>
            Diagnóstico clínico <span className={styles.req}>*</span>
          </label>
          <textarea
            className={`${styles.control} ${formErrors.diagnosis ? styles.fieldError : ""}`}
            placeholder="Bronquitis aguda"
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
