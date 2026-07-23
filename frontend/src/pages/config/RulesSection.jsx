import { useState } from "react";
import { toast } from "sonner";
import { updateOrgSettings } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import SettingsPanel from "./SettingsPanel";
import { ToggleRow } from "./parts";

const RULES = [
  { key: "auto_create_invoice_on_done", label: "Factura automática", description: "Al completar una cita, genera un cobro en borrador." },
  { key: "require_confirmation_before_start", label: "Confirmación obligatoria", description: "No se puede iniciar la consulta sin confirmar la cita primero." },
  { key: "auto_create_medical_record", label: "Historial clínico automático", description: "Al completar una cita, abre un historial clínico." },
  { key: "allow_anonymous_walkin", label: "Atención sin cita", description: "Permite registrar una consulta sin mascota registrada." },
  { key: "allow_emergency_walkin", label: "Urgencias sin cita", description: "Acepta pacientes de urgencia sin cita previa." },
  { key: "show_status_change_history", label: "Historial de cambios", description: "Muestra los cambios de estado en el detalle de la cita." },
  { key: "require_open_cash_session", label: "Caja abierta obligatoria", description: "Requiere un turno de caja abierto para poder cobrar." },
];

const RulesSection = ({ settings, onSettingsChange, canManage }) => {
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const req = updateOrgSettings(settings);
      toast.promise(req, { loading: "Guardando...", success: "Reglas guardadas", error: (e) => apiError(e) });
      const updated = await req;   // sonner: await la promesa REAL, no toast.promise
      if (updated && typeof updated === "object") onSettingsChange(updated);
    } catch {
    } finally {
      setSaving(false);
    }
  };

  const toggle = (key) => () => onSettingsChange({ ...settings, [key]: !settings[key] });

  return (
    <SettingsPanel
      title="Reglas operativas"
      description="Cómo opera tu clínica día a día. Controlan el flujo de citas, cobros y caja."
      padded={false}
      footerNote={canManage ? undefined : "Solo un administrador puede cambiar estas reglas."}
      footer={
        <button className="btn btn-primary" onClick={handleSave} disabled={saving || !canManage}>
          {saving ? "Guardando..." : "Guardar reglas"}
        </button>
      }
    >
      {RULES.map(({ key, label, description }) => (
        <ToggleRow
          key={key}
          label={label}
          desc={description}
          on={!!settings?.[key]}
          disabled={!canManage}
          onToggle={toggle(key)}
        />
      ))}
    </SettingsPanel>
  );
};

export default RulesSection;
