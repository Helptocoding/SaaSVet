import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { updateOrg } from "../../api/organizations";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import TIMEZONES from "../../features/config/timezones.json";
import { CLINIC_FIELDS, changedFields } from "../../features/config/drafts";
import { apiError, isTimezoneChangeBlocked } from "../../utils/apiError";
import handleFormError from "../../utils/handleFormError";
import { formatTaxRate } from "../../utils/money";
import SettingsPanel from "./SettingsPanel";
import { SettingRow, IdentityHeader } from "./parts";
import styles from "./config.module.css";

// ADR p70 D1: catálogo cerrado de zonas de México (copia del backend, con prueba
// de contraste). Etiqueta para personas; se guarda el identificador IANA.
const TIMEZONE_LABELS = Object.fromEntries(TIMEZONES);

const timezoneLabel = (code) => TIMEZONE_LABELS[code] ?? code;

const ADDRESS_FIELDS = ["address_line1", "address_line2", "district", "postal_code", "city", "state"];

/**
 * `org` es el borrador; `savedOrg`, lo último guardado (plan F1.3). El
 * encabezado muestra lo guardado y el PATCH lleva solo lo que cambió.
 */
const ClinicSection = ({ org, savedOrg, onOrgChange, onSaved, onOnboardingDone }) => {
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const confirm = useConfirm();
  const navigate = useNavigate();
  const { refreshUser } = useAuth();

  const savedTimezone = savedOrg?.timezone;
  const timezoneChanging = Boolean(savedTimezone) && org.timezone !== savedTimezone;
  const currentOutsideCatalog = Boolean(org.timezone) && !TIMEZONE_LABELS[org.timezone];

  const handleSave = async () => {
    const changes = changedFields(savedOrg, org, CLINIC_FIELDS);
    if (Object.keys(changes).length === 0) {
      toast.info("No hay cambios que guardar.");
      return;
    }
    // La confirmación va ANTES de activar el guardado (regla de formularios).
    if (timezoneChanging) {
      const ok = await confirm({
        title: "Cambiar la zona horaria",
        message: `La agenda, los cobros y los reportes se mostrarán con la hora de «${timezoneLabel(org.timezone)}». Solo se puede cambiar mientras no haya citas por atender.`,
        confirmText: "Cambiar zona horaria",
      });
      if (!ok) return;
    }

    setSaving(true);
    setErrors({});
    const toastId = toast.loading("Guardando...");
    try {
      const updated = await updateOrg(changes);
      toast.success("Clínica actualizada", { id: toastId });
      if (updated && typeof updated === "object") {
        onSaved(updated);
        // `/me/` publica la zona que usan las fechas de toda la app.
        if (timezoneChanging) await refreshUser();
      }

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
    } catch (err) {
      if (isTimezoneChangeBlocked(err)) {
        // No se escribió nada (tampoco el resto de los campos): se vuelve a la
        // zona guardada y se ofrece ir a las citas que lo impiden.
        onOrgChange({ ...org, timezone: savedTimezone });
        toast.error(apiError(err), {
          id: toastId,
          action: { label: "Ver citas", onClick: () => navigate("/appointments") },
        });
      } else {
        toast.dismiss(toastId);
        handleFormError(err, setErrors);
      }
    } finally {
      setSaving(false);
    }
  };

  const set = (key) => (e) => onOrgChange({ ...org, [key]: e.target.value });
  const errorOf = (key) => errors?.[key];
  const inputClass = (key, base = "input") => (errorOf(key) ? `${base} input-error` : base);

  // El encabezado dice lo guardado, no lo que se está escribiendo.
  const shown = savedOrg || org;
  const meta = [
    [shown.city, shown.state].filter(Boolean).join(", "),
    shown.phone,
    shown.email,
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
      <IdentityHeader name={shown.display_name || shown.name} meta={meta} />

      {/* ADR p70 D5: el legal lo fija plataforma; el comercial es el que ven los
          clientes (PDFs, asistente y menú) y, vacío, se usa el legal. */}
      <SettingRow label="Nombre legal" desc="El de tu razón social. Para cambiarlo, escribe a soporte.">
        <p className={styles.readonlyValue}>{org.name}</p>
      </SettingRow>
      <SettingRow
        label="Nombre comercial"
        desc="Como aparece ante tus clientes: en los PDFs, el asistente de WhatsApp y el menú. Si lo dejas vacío, se usa el legal."
        error={errorOf("display_name")}
      >
        <input className={inputClass("display_name")} aria-label="Nombre comercial" value={org.display_name || ""} onChange={set("display_name")} placeholder={org.name} />
      </SettingRow>
      <SettingRow label="Teléfono" desc="Línea principal de la clínica." error={errorOf("phone")}>
        <input className={inputClass("phone")} aria-label="Teléfono" value={org.phone || ""} onChange={set("phone")} placeholder="5512345678" />
      </SettingRow>
      <SettingRow
        label="WhatsApp de la clínica (informativo)"
        desc="El asistente lo comparte como dato de contacto; no cambia el número desde el que responde."
        error={errorOf("whatsapp")}
      >
        <input className={inputClass("whatsapp")} aria-label="WhatsApp de la clínica" value={org.whatsapp || ""} onChange={set("whatsapp")} placeholder="5512345678" />
      </SettingRow>
      <SettingRow label="Correo electrónico" error={errorOf("email")}>
        <input className={inputClass("email")} aria-label="Correo electrónico" type="email" value={org.email || ""} onChange={set("email")} placeholder="hola@clinica.mx" />
      </SettingRow>
      <SettingRow label="Sitio web" error={errorOf("website")}>
        <input className={inputClass("website")} aria-label="Sitio web" value={org.website || ""} onChange={set("website")} placeholder="https://clinica.mx" />
      </SettingRow>
      <SettingRow
        label="Zona horaria"
        desc="La hora de la agenda, los cobros y los reportes. Elígela al empezar: no se puede cambiar mientras haya citas por atender."
        error={errorOf("timezone")}
      >
        <select
          id="clinic-timezone"
          aria-label="Zona horaria"
          className="select-input"
          value={org.timezone || ""}
          onChange={set("timezone")}
        >
          {currentOutsideCatalog && (
            <option value={org.timezone} disabled>
              {org.timezone} (sin soporte: elige una de la lista)
            </option>
          )}
          {TIMEZONES.map(([code, label]) => (
            <option key={code} value={code}>{label}</option>
          ))}
        </select>
      </SettingRow>

      {/* ADR p70 D3: la tasa es visible, no editable por la clínica. */}
      <SettingRow
        label="IVA de tus cobros"
        desc="Se suma a cada cobro. Los precios de servicios y productos se capturan sin IVA. Para cambiarlo, escribe a soporte."
      >
        <p className={styles.readonlyValue}>{formatTaxRate(org.tax_rate) ?? "Sin configurar"}</p>
      </SettingRow>

      <SettingRow
        label="Dirección"
        desc="Se muestra al agendar y en indicaciones."
        error={ADDRESS_FIELDS.map(errorOf).find(Boolean)}
      >
        <div className={styles.fieldGrid}>
          <div className={`${styles.fieldGroup} ${styles.fieldFull}`}>
            <input className={inputClass("address_line1")} aria-label="Calle y número" value={org.address_line1 || ""} onChange={set("address_line1")} placeholder="Calle y número" />
          </div>
          <div className={`${styles.fieldGroup} ${styles.fieldFull}`}>
            <input className={inputClass("address_line2")} aria-label="Interior, piso o referencia" value={org.address_line2 || ""} onChange={set("address_line2")} placeholder="Interior, piso o referencia" />
          </div>
          <div className={styles.fieldGroup}>
            <input className={inputClass("district")} aria-label="Colonia" value={org.district || ""} onChange={set("district")} placeholder="Colonia" />
          </div>
          <div className={styles.fieldGroup}>
            <input className={inputClass("postal_code")} aria-label="Código postal" value={org.postal_code || ""} onChange={set("postal_code")} placeholder="C.P." />
          </div>
          <div className={styles.fieldGroup}>
            <input className={inputClass("city")} aria-label="Ciudad" value={org.city || ""} onChange={set("city")} placeholder="Ciudad" />
          </div>
          <div className={styles.fieldGroup}>
            <input className={inputClass("state")} aria-label="Estado" value={org.state || ""} onChange={set("state")} placeholder="Estado" />
          </div>
        </div>
      </SettingRow>
      <SettingRow label="Google Maps" desc="Enlace que el asistente comparte al agendar." error={errorOf("google_maps_url")}>
        <input className={inputClass("google_maps_url")} aria-label="Google Maps" value={org.google_maps_url || ""} onChange={set("google_maps_url")} placeholder="https://maps.google.com/..." />
      </SettingRow>
      <SettingRow label="Indicaciones para llegar" desc="Referencias que el asistente comparte." error={errorOf("arrival_instructions")}>
        <textarea className={inputClass("arrival_instructions", "textarea-input")} aria-label="Indicaciones para llegar" style={{ minHeight: 64 }} value={org.arrival_instructions || ""} onChange={set("arrival_instructions")} placeholder="Estacionamiento por la calle lateral, timbre azul..." />
      </SettingRow>
    </SettingsPanel>
  );
};

export default ClinicSection;
