import { useState } from "react";
import { toast } from "sonner";
import { updateOrg } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import styles from "./config.module.css";

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
    <div>
      <p className={styles.sectionTitle}>Información</p>
      <div className={styles.fieldGrid}>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Nombre comercial</label>
          <input className="input" value={org.display_name || org.name} onChange={set("display_name")} placeholder={org.name} />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Teléfono</label>
          <input className="input" value={org.phone || ""} onChange={set("phone")} placeholder="5512345678" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>WhatsApp</label>
          <input className="input" value={org.whatsapp || ""} onChange={set("whatsapp")} placeholder="5512345678" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Email</label>
          <input className="input" type="email" value={org.email || ""} onChange={set("email")} placeholder="hola@clinica.mx" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Sitio web</label>
          <input className="input" value={org.website || ""} onChange={set("website")} placeholder="https://clinica.mx" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Zona horaria</label>
          <input className="input" value={org.timezone} onChange={set("timezone")} placeholder="America/Mexico_City" />
        </div>
      </div>

      <p className={styles.sectionTitle} style={{ marginTop: 28 }}>Ubicación</p>
      <div className={styles.fieldGrid}>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Calle y número</label>
          <input className="input" value={org.address_line1 || ""} onChange={set("address_line1")} placeholder="Av. Principal 123" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Colonia</label>
          <input className="input" value={org.district || ""} onChange={set("district")} placeholder="Centro" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Ciudad</label>
          <input className="input" value={org.city || ""} onChange={set("city")} placeholder="Puebla" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Estado</label>
          <input className="input" value={org.state || ""} onChange={set("state")} placeholder="Puebla" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Código postal</label>
          <input className="input" value={org.postal_code || ""} onChange={set("postal_code")} placeholder="72000" />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>País</label>
          <input className="input" value={org.country || "Mexico"} onChange={set("country")} />
        </div>
      </div>
      <div className={styles.fieldGrid} style={{ marginTop: 16 }}>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Google Maps URL</label>
          <input className="input" value={org.google_maps_url || ""} onChange={set("google_maps_url")} placeholder="https://maps.google.com/..." />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel}>Indicaciones para llegar</label>
          <textarea className="textarea-input" style={{ minHeight: 60 }} value={org.arrival_instructions || ""} onChange={set("arrival_instructions")} placeholder="Estacionamiento por la calle lateral..." />
        </div>
      </div>

      <div className={styles.actions}>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Guardando..." : "Guardar"}
        </button>
      </div>
    </div>
  );
};

export default ClinicSection;
