import { forwardRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "../../components/icons";
import SearchSelect from "../../components/SearchSelect";
import styles from "./consultationForm.module.css";

/**
 * Sección "Tratamiento" (presentacional): indicaciones de tratamiento
 * (obligatorio salvo en consultas de tipo vacuna) + medicamentos recetados.
 *
 * Los medicamentos recetados NO se cobran ni descuentan stock (badge "No se
 * cobra"): son solo indicación médica. Dosis, duración y cantidad usan
 * tipografía monoespaciada.
 */
const TreatmentSection = forwardRef(function TreatmentSection(
  {
    draft,
    formErrors,
    onChange,
    onClearError,
    disabled,
    prescriptionItems,
    prescriptionNotes,
    recipeLine,
    onRecipeLineChange,
    onAddRecipe,
    onRemoveRecipe,
    onPrescriptionNotesChange,
    onProductSearch,
    productMap,
  },
  ref
) {
  const treatmentRequired = draft.consultation_type !== "vaccine";

  return (
    <motion.section
      ref={ref}
      className={styles.section}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.05 }}
    >
      <div className={styles.secHead}>
        <div className={styles.secIcon}>
          <Icon.Pill s={17} />
        </div>
        <div>
          <h2 className={styles.secTitle}>Tratamiento</h2>
        </div>
      </div>

      <div className={styles.grid2}>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>
            Tratamiento e indicaciones
            {treatmentRequired && <span className={styles.req}>*</span>}
          </label>
          <textarea
            className={`${styles.control} ${styles.textareaLg} ${
              formErrors.treatment ? styles.fieldError : ""
            }`}
            placeholder="Instrucciones detalladas del tratamiento…"
            value={draft.treatment}
            disabled={disabled}
            onChange={(e) => {
              onChange({ treatment: e.target.value });
              if (formErrors.treatment) onClearError("treatment");
            }}
          />
          {formErrors.treatment && (
            <div className={styles.fieldErrorMessage}>{formErrors.treatment[0]}</div>
          )}
        </div>

        <div className={styles.field}>
          <label className={styles.fieldLabel}>
            Medicamentos recetados
            <span className="badge badge-info" style={{ flexShrink: 0 }}>
              No se cobra
            </span>
          </label>
          <p className={styles.note}>
            No se cobran ni descuentan stock. Solo indicación médica; recepción
            decide qué compra el cliente.
          </p>

          {!disabled && (
            <div className={styles.adder}>
              <div className={styles.addGrid}>
                <div className="grow">
                  <span className={styles.adderLabel}>Medicamento</span>
                  <SearchSelect
                    placeholder="Buscar…"
                    value={recipeLine.product}
                    onChange={(item) => onRecipeLineChange({ product: item })}
                    onSearch={onProductSearch}
                  />
                </div>
                <div className="cell">
                  <span className={styles.adderLabel}>Dosis</span>
                  <input
                    className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                    placeholder="50mg c/12h"
                    value={recipeLine.dose}
                    onChange={(e) => onRecipeLineChange({ dose: e.target.value })}
                  />
                </div>
                <div className="cell">
                  <span className={styles.adderLabel}>Duración</span>
                  <input
                    className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                    placeholder="7 días"
                    value={recipeLine.duration}
                    onChange={(e) => onRecipeLineChange({ duration: e.target.value })}
                  />
                </div>
                <div className="cell" style={{ flex: "0 1 70px" }}>
                  <span className={styles.adderLabel}>Cant.</span>
                  <input
                    type="number"
                    min="1"
                    className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                    value={recipeLine.quantity}
                    onChange={(e) => onRecipeLineChange({ quantity: e.target.value })}
                  />
                </div>
                <button
                  className="btn btn-primary btn-md"
                  style={{ height: "38px" }}
                  onClick={onAddRecipe}
                  disabled={!recipeLine.product}
                >
                  <Icon.Plus s={16} />
                </button>
              </div>
            </div>
          )}

          <div className={styles.recipeList}>
            {prescriptionItems.length === 0 ? (
              <p className={styles.recipeEmpty}>No hay medicamentos en la receta</p>
            ) : (
              <AnimatePresence initial={false}>
                {prescriptionItems.map((item, idx) => (
                  <motion.div
                    key={item._localKey ?? idx}
                    className={styles.recipeItem}
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, height: 0, marginTop: 0, paddingTop: 0, paddingBottom: 0 }}
                    transition={{ duration: 0.18 }}
                  >
                    <span className={styles.recipeIcon}>
                      <Icon.Pill s={16} />
                    </span>
                    <div className={styles.recipeName}>
                      {item.product_name ||
                        productMap[item.product_id || item.product]?.name}
                    </div>
                    <div className={`${styles.recipeDetails} ${styles.mono}`}>
                      {[item.dose, item.duration, `${item.quantity} u`]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {!disabled && (
                      <button
                        className={`btn btn-ghost btn-xs ${styles.iconBtnDanger}`}
                        onClick={() => onRemoveRecipe(idx)}
                      >
                        <Icon.Trash s={14} />
                      </button>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>
            )}
          </div>

          <div className={styles.field} style={{ marginTop: 14 }}>
            <label className={styles.fieldLabel}>Notas para la receta</label>
            <textarea
              className={styles.control}
              rows={2}
              placeholder="Observaciones de la receta…"
              value={prescriptionNotes}
              disabled={disabled}
              onChange={(e) => onPrescriptionNotesChange(e.target.value)}
            />
          </div>
        </div>
      </div>
    </motion.section>
  );
});

export default TreatmentSection;
