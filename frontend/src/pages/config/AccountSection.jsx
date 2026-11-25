import { useState, useEffect } from "react";
import ChangePasswordForm from "../../components/ChangePasswordForm";
import { Icon } from "../../components/icons";
import SettingsPanel from "./SettingsPanel";
import MfaSettings from "./MfaSettings";
import styles from "./config.module.css";

const AccountSection = () => {
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    const handler = () => setShowModal(true);
    window.addEventListener("open-change-password", handler);
    return () => window.removeEventListener("open-change-password", handler);
  }, []);

  return (
    <SettingsPanel
      title="Cuenta"
      description="Tu acceso personal al sistema."
    >
      <div className={styles.accountRow}>
        <div className={styles.accountIcon}>
          <Icon.Lock s={18} c="var(--c-primary)" />
        </div>
        <div className={styles.accountInfo}>
          <p className={styles.accountLabel}>Contraseña</p>
          <p className={styles.accountDesc}>Actualiza tu contraseña de acceso al sistema.</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={() => setShowModal(true)}>
          Cambiar contraseña
        </button>
      </div>

      {/* ADR p68: solo aparece si la cuenta puede usarla (ADMIN, fuera de la demo). */}
      <MfaSettings />

      {showModal && (
        <div className="modal-overlay">
          <div className="modal modal-sm">
            <div className="modal-header">
              <h3>Cambiar contraseña</h3>
              <button className="modal-close" onClick={() => setShowModal(false)}>
                <Icon.X s={16} />
              </button>
            </div>
            <div className="modal-body">
              <ChangePasswordForm />
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary btn-md" style={{ flex: 1 }}
                onClick={() => setShowModal(false)}>Cerrar</button>
            </div>
          </div>
        </div>
      )}
    </SettingsPanel>
  );
};

export default AccountSection;
