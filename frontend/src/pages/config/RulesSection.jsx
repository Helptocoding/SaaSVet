import { useState } from "react";
import { toast } from "sonner";
import { updateOrgSettings } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import styles from "./config.module.css";

const RULES = [
  { key: "auto_create_invoice_on_done", label: "Factura automática", description: "Al completar una cita, genera una factura en borrador." },
  { key: "require_confirmation_before_start", label: "Confirmación obligatoria", description: "No se puede iniciar consulta sin confirmar la cita." },
  { key: "auto_create_medical_record", label: "Historial clínico automático", description: "Al completar una cita, abre un historial clínico." },
  { key: "allow_anonymous_walkin", label: "Atención sin cita", description: "Permite registrar consulta sin mascota registrada." },
  { key: "allow_emergency_walkin", label: "Urgencias sin cita", description: "Acepta pacientes de urgencia sin cita previa." },
  { key: "show_status_change_history", label: "Historial de cambios", description: "Muestra cambios de estado en el detalle de la cita." },
  { key: "require_open_cash_session", label: "Caja abierta obligatoria", description: "Requiere turno de caja abierto para cobrar." },
];

const RulesSection = ({ settings, onSettingsChange, canManage }) => {
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await toast.promise(
        updateOrgSettings(settings),
        { loading: "Guardando...", success: "Reglas guardadas", error: (e) => apiError(e) }
      );
      onSettingsChange(updated);
    } catch {
    } finally {
      setSaving(false);
    }
  };

  const toggle = (key) => {
    onSettingsChange({ ...settings, [key]: !settings[key] });
  };

  return (
    <div>
      {RULES.map(({ key, label, description }) => (
        <div key={key} className={styles.ruleRow}>
          <div className={styles.ruleContent}>
            <p className={styles.ruleLabel}>{label}</p>
            <p className={styles.ruleDesc}>{description}</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={!!settings?.[key]}
            disabled={!canManage}
            onClick={() => toggle(key)}
            className={`${styles.toggle} ${settings?.[key] ? styles.toggleOn : styles.toggleOff} ${!canManage ? styles.toggleDisabled : ""}`}
          >
            <span className={`${styles.toggleKnob} ${settings?.[key] ? styles.toggleKnobOn : styles.toggleKnobOff}`} />
          </button>
        </div>
      ))}

      <div className={styles.actions} style={{ marginTop: 24 }}>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving || !canManage}>
          {saving ? "Guardando..." : "Guardar reglas"}
        </button>
      </div>
    </div>
  );
};

export default RulesSection;
