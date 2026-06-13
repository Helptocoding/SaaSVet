import { Icon } from "../../components/icons";
import styles from "./consultationForm.module.css";

/**
 * Modal de captura de signos vitales (presentacional). Reutiliza el patrón
 * modal global (.modal-overlay / .modal-sm). Los valores son numéricos →
 * tipografía monoespaciada. Si la consulta está cerrada, los inputs quedan
 * deshabilitados (solo lectura).
 */
export default function VitalsModal({
  vitalFields,
  draft,
  formErrors,
  closed,
  onChange,
  onClearError,
  onClose,
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Signos vitales</h3>
          <button className="modal-close" onClick={onClose}>
            <Icon.X s={16} />
          </button>
        </div>
        <div className="modal-body">
          <div className={styles.vitalsModalGrid}>
            {vitalFields.map((v) => (
              <div key={v.f} className={styles.vitalItem}>
                <div className={styles.vitalItemLabel}>
                  {v.icon} {v.l}
                </div>
                <div className={styles.vitalItemWrap}>
                  <input
                    type="number"
                    className={`${styles.vitalItemInput} ${styles.mono} ${
                      formErrors[v.f] ? styles.fieldError : ""
                    }`}
                    value={draft[v.f]}
                    disabled={closed}
                    onChange={(e) => {
                      onChange({ [v.f]: e.target.value });
                      if (formErrors[v.f]) onClearError(v.f);
                    }}
                    placeholder="—"
                  />
                  <span className={styles.vitalItemUnit}>{v.u}</span>
                </div>
                {formErrors[v.f] && (
                  <div
                    className={styles.fieldErrorMessage}
                    style={{ fontSize: "10px", marginTop: "2px" }}
                  >
                    {formErrors[v.f][0]}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-primary btn-md" onClick={onClose}>
            {closed ? "Cerrar" : "Continuar consulta"}
          </button>
        </div>
      </div>
    </div>
  );
}
