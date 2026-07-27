import { useState } from "react";
import { toast } from "sonner";
import { updateOrg } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import SettingsPanel from "./SettingsPanel";
import { SettingRow, IdentityHeader } from "./parts";
import styles from "./config.module.css";

const ClinicSection = ({ org, onOrgChange, onOnboardingDone }) => {
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const req = updateOrg({
        display_name: org.display_name,
        phone: org.phone,
        whatsapp: org.whatsapp,
        email: org.email,
        website: org.website,
        timezone: org.timezone,
        address_line1: org.address_line1,
        district: org.district,
        city: org.city,
        state: org.state,
        postal_code: org.postal_code,
        country: org.country,
        google_maps_url: org.google_maps_url,
        arrival_instructions: org.arrival_instructions,
      });
      toast.promise(req, { loading: "Guardando...", success: "Clínica actualizada", error: (e) => apiError(e) });
      const updated = await req;   // sonner: await la promesa REAL, no toast.promise
      if (updated && typeof updated === "object") onOrgChange(updated);

      // Flujo de onboarding: el hito es `has_clinic_contact` = teléfono capturado.
      // Guardar sin teléfono NO lo cubre — volver al dashboard celebrando algo que
      // el endpoint de activación seguirá viendo incompleto confundiría al ADMIN.
      if (onOnboardingDone) {
        if (updated?.phone) {
          onOnboardingDone();
        } else {
          toast.info("Falta el teléfono de la clínica para terminar este paso.");
        }
      }
    } catch {
    } finally {
      setSaving(false);
    }
  };

  const set = (key) => (e) => onOrgChange({ ...org, [key]: e.target.value });

  const meta = [
    [org.city, org.state].filter(Boolean).join(", "),
    org.phone,
    org.email,
  ].filter(Boolean);

  return (
    <SettingsPanel
      title="Clínica"
      description="Identidad y contacto. El asistente de WhatsApp usa estos datos al responder dirección, teléfono e indicaciones."
      padded={false}
      footerNote="Se aplica a toda la clínica."
      footer={
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Guardando..." : "Guardar cambios"}
        </button>
      }
    >
      <IdentityHeader name={org.display_name || org.name} meta={meta} />

      <SettingRow label="Nombre comercial" desc="Como aparece ante tus clientes.">
        <input className="input" value={org.display_name || ""} onChange={set("display_name")} placeholder={org.name} />
      </SettingRow>
      <SettingRow label="Teléfono" desc="Línea principal de la clínica.">
        <input className="input" value={org.phone || ""} onChange={set("phone")} placeholder="5512345678" />
      </SettingRow>
      <SettingRow label="WhatsApp" desc="Número del asistente virtual.">
        <input className="input" value={org.whatsapp || ""} onChange={set("whatsapp")} placeholder="5512345678" />
      </SettingRow>
      <SettingRow label="Correo electrónico">
        <input className="input" type="email" value={org.email || ""} onChange={set("email")} placeholder="hola@clinica.mx" />
      </SettingRow>
      <SettingRow label="Sitio web">
        <input className="input" value={org.website || ""} onChange={set("website")} placeholder="https://clinica.mx" />
      </SettingRow>
      <SettingRow label="Zona horaria" desc="Afecta agenda, cobros y reportes.">
        <input className="input" value={org.timezone || ""} onChange={set("timezone")} placeholder="America/Mexico_City" />
      </SettingRow>

      <SettingRow label="Dirección" desc="Se muestra al agendar y en indicaciones.">
        <div className={styles.fieldGrid}>
          <div className={`${styles.fieldGroup} ${styles.fieldFull}`}>
            <input className="input" value={org.address_line1 || ""} onChange={set("address_line1")} placeholder="Calle y número" />
          </div>
          <div className={styles.fieldGroup}>
            <input className="input" value={org.district || ""} onChange={set("district")} placeholder="Colonia" />
          </div>
          <div className={styles.fieldGroup}>
            <input className="input" value={org.postal_code || ""} onChange={set("postal_code")} placeholder="C.P." />
          </div>
          <div className={styles.fieldGroup}>
            <input className="input" value={org.city || ""} onChange={set("city")} placeholder="Ciudad" />
          </div>
          <div className={styles.fieldGroup}>
            <input className="input" value={org.state || ""} onChange={set("state")} placeholder="Estado" />
          </div>
        </div>
      </SettingRow>
      <SettingRow label="Google Maps" desc="Enlace que el asistente comparte al agendar.">
        <input className="input" value={org.google_maps_url || ""} onChange={set("google_maps_url")} placeholder="https://maps.google.com/..." />
      </SettingRow>
      <SettingRow label="Indicaciones para llegar" desc="Referencias que el asistente comparte.">
        <textarea className="textarea-input" style={{ minHeight: 64 }} value={org.arrival_instructions || ""} onChange={set("arrival_instructions")} placeholder="Estacionamiento por la calle lateral, timbre azul..." />
      </SettingRow>
    </SettingsPanel>
  );
};

export default ClinicSection;
