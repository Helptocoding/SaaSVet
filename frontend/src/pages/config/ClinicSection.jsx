import { useState } from "react";
import { toast } from "sonner";
import { updateOrg } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import SettingsPanel from "./SettingsPanel";
import styles from "./config.module.css";

const Field = ({ label, hint, full, children }) => (
  <div className={`${styles.fieldGroup} ${full ? styles.fieldFull : ""}`}>
    <label className={styles.fieldLabel}>{label}</label>
    {children}
    {hint && <span className={styles.fieldHint}>{hint}</span>}
  </div>
);

const ClinicSection = ({ org, onOrgChange }) => {
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await toast.promise(
        updateOrg({
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
        }),
        { loading: "Guardando...", success: "Clínica actualizada", error: (e) => apiError(e) }
      );
      onOrgChange(updated);
    } catch {
    } finally {
      setSaving(false);
    }
  };

  const set = (key) => (e) => onOrgChange({ ...org, [key]: e.target.value });

  return (
    <SettingsPanel
      title="Clínica"
      description="Identidad y contacto de tu clínica. El asistente de WhatsApp usa estos datos al responder dirección, teléfono e indicaciones."
      footerNote="Se aplica a toda la clínica."
      footer={
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Guardando..." : "Guardar cambios"}
        </button>
      }
    >
      <div className={styles.group}>
        <p className={styles.groupTitle}>Información</p>
        <div className={styles.fieldGrid}>
          <Field label="Nombre comercial">
            <input className="input" value={org.display_name || ""} onChange={set("display_name")} placeholder={org.name} />
          </Field>
          <Field label="Teléfono">
            <input className="input" value={org.phone || ""} onChange={set("phone")} placeholder="5512345678" />
          </Field>
          <Field label="WhatsApp">
            <input className="input" value={org.whatsapp || ""} onChange={set("whatsapp")} placeholder="5512345678" />
          </Field>
          <Field label="Correo electrónico">
            <input className="input" type="email" value={org.email || ""} onChange={set("email")} placeholder="hola@clinica.mx" />
          </Field>
          <Field label="Sitio web">
            <input className="input" value={org.website || ""} onChange={set("website")} placeholder="https://clinica.mx" />
          </Field>
          <Field label="Zona horaria" hint="Afecta agenda, cobros y reportes.">
            <input className="input" value={org.timezone || ""} onChange={set("timezone")} placeholder="America/Mexico_City" />
          </Field>
        </div>
      </div>

      <div className={styles.group}>
        <p className={styles.groupTitle}>Ubicación</p>
        <div className={styles.fieldGrid}>
          <Field label="Calle y número" full>
            <input className="input" value={org.address_line1 || ""} onChange={set("address_line1")} placeholder="Av. Principal 123" />
          </Field>
          <Field label="Colonia">
            <input className="input" value={org.district || ""} onChange={set("district")} placeholder="Centro" />
          </Field>
          <Field label="Ciudad">
            <input className="input" value={org.city || ""} onChange={set("city")} placeholder="Puebla" />
          </Field>
          <Field label="Estado">
            <input className="input" value={org.state || ""} onChange={set("state")} placeholder="Puebla" />
          </Field>
          <Field label="Código postal">
            <input className="input" value={org.postal_code || ""} onChange={set("postal_code")} placeholder="72000" />
          </Field>
          <Field label="País">
            <input className="input" value={org.country || "Mexico"} onChange={set("country")} />
          </Field>
          <Field label="Google Maps" full hint="Enlace que el asistente comparte al agendar.">
            <input className="input" value={org.google_maps_url || ""} onChange={set("google_maps_url")} placeholder="https://maps.google.com/..." />
          </Field>
          <Field label="Indicaciones para llegar" full>
            <textarea className="textarea-input" style={{ minHeight: 64 }} value={org.arrival_instructions || ""} onChange={set("arrival_instructions")} placeholder="Estacionamiento por la calle lateral, timbre azul..." />
          </Field>
        </div>
      </div>
    </SettingsPanel>
  );
};

export default ClinicSection;
