import { useState } from "react";
import { toast } from "sonner";
import { createService, updateService, deleteService } from "../../api/billing";
import { apiError } from "../../utils/apiError";
import handleFormError from "../../utils/handleFormError";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import { Icon } from "../../components/icons";
import EmptyState from "../../components/EmptyState";
import PriceLabel from "../../components/PriceLabel";
import { formatTaxRate } from "../../utils/money";
import SettingsPanel from "./SettingsPanel";
import { ToggleRow } from "./parts";
import { SPECIALTIES, specialtyLabel } from "../../features/staff/specialties";
import styles from "./config.module.css";

const EMPTY_SERVICE = { name: "", description: "", base_price: "", specialty: "", is_active: true };

// Plan F1.7: qué deja de pasar con un servicio inactivo, dicho una sola vez.
const INACTIVE_EFFECT = "Un servicio inactivo no aparece al cobrar ni en la consulta, y el asistente no lo ofrece. Conserva su historial.";

const isDependencyConflict = (err) => err?.response?.status === 409;

/**
 * Catálogo de servicios (ADR p70, plan F1.7). Cada acción según su permiso
 * (`service.create`, `service.update`, `service.destroy`). `services` llega con
 * los inactivos incluidos; aquí se filtran salvo que se pida verlos.
 */
const ServicesSection = ({ services, onServicesChange, onOnboardingDone }) => {
  const { can, user } = useAuth();
  const confirm = useConfirm();
  const canCreate = Boolean(can?.("service.create"));
  const canUpdate = Boolean(can?.("service.update"));
  const canDestroy = Boolean(can?.("service.destroy"));

  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_SERVICE);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [showInactive, setShowInactive] = useState(false);

  const inactiveCount = services.filter((svc) => !svc.is_active).length;
  const visible = showInactive ? services : services.filter((svc) => svc.is_active);

  const openNew = () => { setEditing(null); setForm(EMPTY_SERVICE); setErrors({}); setShowModal(true); };
  const openEdit = (svc) => {
    setEditing(svc);
    setForm({ name: svc.name, description: svc.description || "", base_price: svc.base_price, specialty: svc.specialty || "", is_active: svc.is_active });
    setErrors({});
    setShowModal(true);
  };
  const close = () => { setShowModal(false); setEditing(null); setForm(EMPTY_SERVICE); setErrors({}); };

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    const found = {};
    if (!form.name.trim()) found.name = "El nombre es obligatorio.";
    if (!form.base_price || Number(form.base_price) <= 0) found.base_price = "El precio debe ser mayor a 0.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setSaving(true);
    const toastId = toast.loading(editing ? "Actualizando..." : "Creando...");
    try {
      if (editing) await updateService(editing.public_id, form);
      else await createService(form);
      toast.success(editing ? "Servicio actualizado" : "Servicio creado", { id: toastId });
      const wasEditing = Boolean(editing);
      close();
      // Flujo de onboarding: solo la CREACIÓN cubre el hito (editar un servicio
      // existente no es un primer paso). El layout hace el navigate.
      if (!wasEditing && onOnboardingDone) {
        onOnboardingDone();
        return;
      }
      onServicesChange();
    } catch (err) {
      toast.dismiss(toastId);
      handleFormError(err, setErrors);
    } finally {
      setSaving(false);
    }
  };

  const applyActive = async (svc, active) => {
    setBusyId(svc.public_id);
    try {
      await updateService(svc.public_id, { is_active: active });
      toast.success(active ? "Servicio activado" : "Servicio desactivado");
      onServicesChange();
    } catch (err) {
      toast.error(apiError(err, "No se pudo cambiar el servicio."));
    } finally {
      setBusyId(null);
    }
  };

  const setActive = async (svc, active) => {
    if (!active) {
      const ok = await confirm({
        title: `Desactivar «${svc.name}»`,
        message: INACTIVE_EFFECT,
        confirmText: "Desactivar",
      });
      if (!ok) return;
    }
    await applyActive(svc, active);
  };

  const handleDelete = async (svc) => {
    const ok = await confirm({
      title: `Eliminar «${svc.name}»`,
      message: "Se borra del catálogo. Si ya se usó en una consulta o un cobro, no se puede eliminar.",
      confirmText: "Eliminar",
      dangerMode: true,
    });
    if (!ok) return;
    setBusyId(svc.public_id);
    let conflict = null;
    try {
      await deleteService(svc.public_id);
      toast.success("Servicio eliminado");
      onServicesChange();
    } catch (err) {
      if (isDependencyConflict(err) && canUpdate && svc.is_active) conflict = err;
      else toast.error(apiError(err, "No se pudo eliminar el servicio."));
    } finally {
      setBusyId(null);
    }
    if (!conflict) return;
    // El historial lo protege (409): se dice por qué y se ofrece desactivarlo.
    const deactivate = await confirm({
      title: "No se puede eliminar",
      message: `${apiError(conflict, "Este servicio ya se usó.")} Puedes desactivarlo en su lugar. ${INACTIVE_EFFECT}`,
      confirmText: "Desactivar",
    });
    if (deactivate) await applyActive(svc, false);
  };

  const taxLabel = formatTaxRate(user?.organization_tax_rate);

  return (
    <SettingsPanel
      title="Servicios"
      description="El catálogo que usas al cobrar y que el asistente consulta para dar precios."
      padded={false}
      action={canCreate && (
        <button className="btn btn-secondary btn-sm" onClick={openNew}><Icon.Plus s={14} /> Nuevo servicio</button>
      )}
    >
      {inactiveCount > 0 && (
        <label className={styles.serviceFilter}>
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
          />
          Mostrar inactivos ({inactiveCount})
        </label>
      )}
      {visible.length === 0 ? (
        <div className={styles.serviceEmpty}>
          <EmptyState
            compact
            title="Define los servicios que cobras"
            body="Consulta, vacunación, cirugía… los usarás al cobrar."
            actions={[canCreate ? { label: "Nuevo servicio", onClick: openNew, variant: "primary" } : null]}
          />
        </div>
      ) : (
        visible.map((svc) => {
          const busy = busyId === svc.public_id;
          return (
            <div key={svc.public_id} className={styles.serviceRow}>
              <div className={styles.serviceInfo}>
                <span className={`${styles.serviceName} ${!svc.is_active ? styles.serviceNameInactive : ""}`}>
                  {svc.name}
                </span>
                {svc.specialty && <span className="badge badge-info">{specialtyLabel(svc.specialty)}</span>}
                {!svc.is_active && <span className="badge badge-default">Inactivo</span>}
              </div>
              <div className={styles.serviceActions}>
                <PriceLabel base={svc.base_price} withTax={svc.price_with_tax} className={styles.servicePrice} />
                {canUpdate && (
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => setActive(svc, !svc.is_active)}
                    disabled={busy}
                  >
                    {svc.is_active ? "Desactivar" : "Activar"}
                  </button>
                )}
                {canUpdate && (
                  <button className="btn btn-ghost btn-icon" onClick={() => openEdit(svc)} aria-label={`Editar ${svc.name}`} title="Editar" disabled={busy}>
                    <Icon.Edit s={13} />
                  </button>
                )}
                {canDestroy && (
                  <button className="btn btn-danger btn-icon" onClick={() => handleDelete(svc)} aria-label={`Eliminar ${svc.name}`} title="Eliminar" disabled={busy}>
                    <Icon.Trash s={13} />
                  </button>
                )}
              </div>
            </div>
          );
        })
      )}

      {showModal && (
        <div className="modal-overlay">
          <div className="modal modal-sm" role="dialog" aria-modal="true" aria-labelledby="service-modal-title">
            <div className="modal-header">
              <h3 id="service-modal-title">{editing ? "Editar servicio" : "Nuevo servicio"}</h3>
              <button className="modal-close" onClick={close} aria-label="Cerrar"><Icon.X s={16} /></button>
            </div>
            <div className="modal-body">
              <form onSubmit={handleSubmit}>
                <div className="form-group">
                  <label className="form-label" htmlFor="service-name">Nombre *</label>
                  <input id="service-name" className={`input${errors.name ? " input-error" : ""}`} value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Ej: Consulta general" />
                  {errors.name && <p className={styles.fieldError} role="alert">{errors.name}</p>}
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="service-price">Precio sin IVA *</label>
                  <input id="service-price" className={`input${errors.base_price ? " input-error" : ""}`} type="number" step="0.01" min="0"
                    value={form.base_price}
                    onChange={(e) => setForm({ ...form, base_price: e.target.value })}
                    placeholder="0.00" />
                  {errors.base_price && <p className={styles.fieldError} role="alert">{errors.base_price}</p>}
                  <p className="form-hint">
                    {taxLabel
                      ? `Al cobrar se suma el IVA de la clínica (${taxLabel}).`
                      : "Al cobrar se suma el IVA de la clínica."}
                  </p>
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="service-specialty">Especialidad</label>
                  <select id="service-specialty" className="select-input" value={form.specialty}
                    onChange={(e) => setForm({ ...form, specialty: e.target.value })}>
                    <option value="">Sin especialidad</option>
                    {SPECIALTIES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                  </select>
                  <p className="form-hint">Liga el servicio con quienes tienen esa especialidad en Equipo.</p>
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="service-description">Descripción</label>
                  <textarea id="service-description" className={`textarea-input ${styles.serviceDescription}`}
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="Descripción opcional..." />
                </div>
                {editing && (
                  <ToggleRow
                    label="Activo"
                    desc={INACTIVE_EFFECT}
                    on={form.is_active}
                    onToggle={() => setForm({ ...form, is_active: !form.is_active })}
                  />
                )}
              </form>
            </div>
            <div className="modal-footer">
              <button className={`btn btn-primary btn-md ${styles.modalAction}`}
                onClick={handleSubmit} disabled={saving}>
                <Icon.Check s={15} /> {saving ? "Guardando..." : editing ? "Guardar" : "Crear"}
              </button>
              <button className={`btn btn-secondary btn-md ${styles.modalAction}`}
                onClick={close} disabled={saving}>Cancelar</button>
            </div>
          </div>
        </div>
      )}
    </SettingsPanel>
  );
};

export default ServicesSection;
