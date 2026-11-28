import { useState } from "react";
import { toast } from "sonner";
import { updateOrgSettings } from "../../api/organizations";
import { useConfirm } from "../../components/useConfirm";
import { changedFields } from "../../features/config/drafts";
import { DURATION_RANGE, durationError } from "../../features/config/rules";
import handleFormError from "../../utils/handleFormError";
import SettingsPanel from "./SettingsPanel";
import { ToggleRow } from "./parts";
import styles from "./config.module.css";

/**
 * Un apartado de reglas (Cobros o Atención). `settings` es el borrador y
 * `savedSettings` lo último guardado (plan F1.3): el PATCH lleva solo las
 * reglas de este apartado que cambiaron. Las que cambian cómo se cobra piden
 * confirmación al tocarlas (F1.5).
 */
const RulesSection = ({
  title, description, rules, settings, savedSettings, onSettingsChange, onSaved, showCreditTerm = false,
  showDuration = false,
}) => {
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const confirm = useConfirm();

  const fields = [
    ...rules.map(({ key }) => key),
    ...(showCreditTerm ? ["credit_default_days"] : []),
    ...(showDuration ? ["default_appointment_duration_minutes"] : []),
  ];

  const handleSave = async () => {
    const changes = changedFields(savedSettings, settings, fields);
    if (Object.keys(changes).length === 0) {
      toast.info("No hay cambios que guardar.");
      return;
    }
    if ("default_appointment_duration_minutes" in changes) {
      const message = durationError(changes.default_appointment_duration_minutes);
      if (message) {
        setErrors({ default_appointment_duration_minutes: message });
        return;
      }
    }
    setSaving(true);
    setErrors({});
    const toastId = toast.loading("Guardando...");
    try {
      const updated = await updateOrgSettings(changes);
      toast.success("Reglas guardadas", { id: toastId });
      if (updated && typeof updated === "object") onSaved(updated, fields);
    } catch (err) {
      toast.dismiss(toastId);
      handleFormError(err, setErrors);
    } finally {
      setSaving(false);
    }
  };

  const toggle = (rule) => async () => {
    const next = !settings?.[rule.key];
    if (rule.confirm) {
      const ok = await confirm(next ? rule.confirm.on : rule.confirm.off);
      if (!ok) return;
    }
    onSettingsChange({ ...settings, [rule.key]: next });
  };

  return (
    <SettingsPanel
      title={title}
      description={description}
      padded={false}
      footer={
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Guardando..." : "Guardar reglas"}
        </button>
      }
    >
      {rules.map((rule) => (
        <ToggleRow
          key={rule.key}
          label={rule.label}
          desc={rule.description}
          on={!!settings?.[rule.key]}
          onToggle={toggle(rule)}
        />
      ))}
      {showDuration && (
        <div className={styles.numberSetting}>
          <label htmlFor="default-appointment-duration" className={styles.numberSettingLabel}>
            Duración habitual de una cita
          </label>
          <p className={styles.numberSettingDesc}>
            La agenda la usa para la hora de fin de una cita nueva; se puede cambiar en cada cita.
            El asistente de WhatsApp y la atención sin cita siguen en 30 minutos.
          </p>
          <div className={styles.numberSettingRow}>
            <input
              id="default-appointment-duration"
              className={`input ${styles.numberSettingInput}${errors.default_appointment_duration_minutes ? " input-error" : ""}`}
              type="number"
              min={DURATION_RANGE.min}
              max={DURATION_RANGE.max}
              step="5"
              value={settings?.default_appointment_duration_minutes ?? 30}
              aria-describedby={errors.default_appointment_duration_minutes ? "default-appointment-duration-error" : undefined}
              onChange={(event) => onSettingsChange({
                ...settings,
                default_appointment_duration_minutes: event.target.value === "" ? "" : Number(event.target.value),
              })}
            />
            <span className={styles.numberSettingUnit}>minutos</span>
          </div>
          {errors.default_appointment_duration_minutes && (
            <p id="default-appointment-duration-error" className={styles.fieldError} role="alert">
              {errors.default_appointment_duration_minutes}
            </p>
          )}
        </div>
      )}
      {showCreditTerm && !!settings?.allow_post_unpaid && (
        <div className={styles.numberSetting}>
          <label htmlFor="credit-default-days" className={styles.numberSettingLabel}>
            Plazo de crédito predeterminado
          </label>
          <div className={styles.numberSettingRow}>
            <input
              id="credit-default-days"
              className={`input ${styles.numberSettingInput}${errors.credit_default_days ? " input-error" : ""}`}
              type="number"
              min="1"
              max="365"
              value={settings?.credit_default_days ?? 30}
              aria-describedby={errors.credit_default_days ? "credit-default-days-error" : undefined}
              onChange={(event) => onSettingsChange({
                ...settings,
                credit_default_days: Math.min(365, Math.max(1, Number(event.target.value) || 1)),
              })}
            />
            <span className={styles.numberSettingUnit}>días</span>
          </div>
          {errors.credit_default_days && (
            <p id="credit-default-days-error" className={styles.fieldError} role="alert">
              {errors.credit_default_days}
            </p>
          )}
        </div>
      )}
    </SettingsPanel>
  );
};

export default RulesSection;
