import { forwardRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "../../components/icons";
import SearchSelect from "../../components/SearchSelect";
import styles from "./consultationForm.module.css";

const TreatmentSection = forwardRef(function TreatmentSection(
  {
    recipeRef,
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
      className={styles.card}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.05 }}
    >
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Tratamiento</h2>
        <p className={styles.cardDesc}>Indicaciones y medicamentos recetados</p>
      </div>

      <div data-consult-step="treat">
            <label className={`${styles.fieldLabel} ${styles.fieldLabelMinimal}`}>
              Tratamiento {treatmentRequired && <span className={styles.req}>*</span>}
            </label>
            <textarea
              className={`${styles.control} ${styles.textareaLg} ${styles.editorTextarea} ${
                treatmentRequired ? styles.inputRequired : ""
              } ${
                formErrors.treatment ? styles.fieldError : ""
              }`}
              placeholder="Comienza a escribir..."
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

          <div ref={recipeRef} className={styles.prescriptionPanel} data-consult-step="recipe">
            <div className={styles.subSectionHeader}>
              <div>
                <h3 className={styles.subSectionTitle}>Receta</h3>
                <p className={styles.note}>
                  Estos medicamentos no generan cargos automaticamente. Recepcion decide cuales dispensar.
                </p>
              </div>
            </div>

            {!disabled && (
              <div className={styles.adderLite}>
                <div className={styles.recipeSearchRow}>
                  <SearchSelect
                    placeholder="Buscar medicamento"
                    value={recipeLine.product}
                    onChange={(item) => onRecipeLineChange({ product: item })}
                    onSearch={onProductSearch}
                  />
                  <button
                    className="btn btn-primary btn-md"
                    onClick={onAddRecipe}
                    disabled={!recipeLine.product}
                  >
                    <Icon.Plus s={16} /> Agregar
                  </button>
                </div>

                <div className={styles.recipeMetaGrid}>
                  <div>
                    <span className={styles.adderLabel}>Dosis</span>
                    <input
                      className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                      placeholder="50 mg c/12h"
                      value={recipeLine.dose}
                      onChange={(e) => onRecipeLineChange({ dose: e.target.value })}
                    />
                  </div>
                  <div>
                    <span className={styles.adderLabel}>Duracion</span>
                    <input
                      className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                      placeholder="7 dias"
                      value={recipeLine.duration}
                      onChange={(e) => onRecipeLineChange({ duration: e.target.value })}
                    />
                  </div>
                  <div>
                    <span className={styles.adderLabel}>Cantidad</span>
                    <input
                      type="number"
                      min="1"
                      className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                      value={recipeLine.quantity}
                      onChange={(e) => onRecipeLineChange({ quantity: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            )}

            <div className={styles.recipeList}>
              {prescriptionItems.length === 0 ? (
                <p className={styles.recipeEmpty}>Aun no hay medicamentos recetados.</p>
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
                      <div>
                        <div className={styles.recipeName}>
                          {item.product_name ||
                            productMap[item.product_id || item.product]?.name}
                        </div>
                        <div className={`${styles.recipeDetails} ${styles.mono}`}>
                          {[item.dose, item.duration, `${item.quantity} u`]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
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

            <div className={styles.field}>
              <label className={`${styles.fieldLabel} ${styles.fieldLabelMinimal}`}>Notas</label>
              <textarea
                className={`${styles.control} ${styles.recipeNotes}`}
                rows={3}
                placeholder="Observaciones para la receta..."
                value={prescriptionNotes}
                disabled={disabled}
                onChange={(e) => onPrescriptionNotesChange(e.target.value)}
              />
            </div>
          </div>
    </motion.section>
  );
});

export default TreatmentSection;
