import { useState } from "react";
import { toast } from "sonner";
import { createService, updateService, deleteService } from "../../api/billing";
import { apiError } from "../../utils/apiError";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import { Icon } from "../../components/icons";
import EmptyState from "../../components/EmptyState";
import SettingsPanel from "./SettingsPanel";
import styles from "./config.module.css";

const EMPTY_SERVICE = { name: "", description: "", base_price: "", is_active: true };

const ServicesSection = ({ services, onServicesChange }) => {
  const { can } = useAuth();
  const confirm = useConfirm();
  const canManage = can("service.create");

  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_SERVICE);
  const [saving, setSaving] = useState(false);

  const openNew = () => { setEditing(null); setForm(EMPTY_SERVICE); setShowModal(true); };
  const openEdit = (svc) => {
    setEditing(svc);
    setForm({ name: svc.name, description: svc.description || "", base_price: svc.base_price, is_active: svc.is_active });
    setShowModal(true);
  };
  const close = () => { setShowModal(false); setEditing(null); setForm(EMPTY_SERVICE); };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("El nombre es obligatorio"); return; }
    if (!form.base_price || Number(form.base_price) <= 0) { toast.error("El precio debe ser mayor a 0"); return; }
    setSaving(true);
    try {
      if (editing) {
        await toast.promise(updateService(editing.public_id, form), {
          loading: "Actualizando...", success: "Servicio actualizado", error: (e) => apiError(e)
        });
      } else {
        const req = createService(form);
        toast.promise(req, { loading: "Creando...", success: "Servicio creado", error: (e) => apiError(e) });
        await req;
      }
      close();
      onServicesChange();
    } catch {
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    const ok = await confirm({ message: "¿Eliminar este servicio?", confirmText: "Eliminar", dangerMode: true });
    if (!ok) return;
    try {
      await toast.promise(deleteService(id), {
        loading: "Eliminando...", success: "Eliminado", error: "No se puede eliminar: puede estar en uso"
      });
      onServicesChange();
    } catch { }
  };

  const fmt = (n) => Number(n || 0).toFixed(2);

  return (
    <SettingsPanel
      title="Servicios"
      description="El catálogo que usas al cobrar y que el asistente consulta para dar precios."
      padded={false}
      action={canManage && (
        <button className="btn btn-secondary btn-sm" onClick={openNew}>+ Nuevo servicio</button>
      )}
    >
      {services.length === 0 ? (
        <div className={styles.serviceEmpty}>
          <EmptyState
            compact
            title="Define los servicios que cobras"
            body="Consulta, vacunación, cirugía… los usarás al facturar."
            actions={[canManage ? { label: "Nuevo servicio", onClick: openNew, variant: "primary" } : null]}
          />
        </div>
      ) : (
        services.map((svc) => (
          <div key={svc.id} className={styles.serviceRow}>
            <div className={styles.serviceInfo}>
              <span className={`${styles.serviceName} ${!svc.is_active ? styles.serviceNameInactive : ""}`}>
                {svc.name}
              </span>
              {!svc.is_active && <span className="badge badge-default">Inactivo</span>}
            </div>
            <div className={styles.serviceActions}>
              <span className={styles.servicePrice}>${fmt(svc.base_price)}</span>
              <button className={styles.iconBtn} onClick={() => openEdit(svc)} title="Editar">
                <Icon.Edit s={13} />
              </button>
              <button className={`${styles.iconBtn} ${styles.iconBtnDanger}`} onClick={() => handleDelete(svc.public_id)} title="Eliminar">
                <Icon.Trash s={13} />
              </button>
            </div>
          </div>
        ))
      )}

      {showModal && (
        <div className="modal-overlay">
          <div className="modal modal-sm">
            <div className="modal-header">
              <h3>{editing ? "Editar servicio" : "Nuevo servicio"}</h3>
              <button className="modal-close" onClick={close}><Icon.X s={16} /></button>
            </div>
            <div className="modal-body">
              <form onSubmit={handleSubmit}>
                <div className="form-group">
                  <label className="form-label">NOMBRE *</label>
                  <input className="input" value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Ej: Consulta general" />
                </div>
                <div className="form-group">
                  <label className="form-label">PRECIO BASE *</label>
                  <input className="input" type="number" step="0.01" min="0"
                    value={form.base_price}
                    onChange={(e) => setForm({ ...form, base_price: e.target.value })}
                    placeholder="0.00" />
                </div>
                <div className="form-group">
                  <label className="form-label">DESCRIPCIÓN</label>
                  <textarea className="textarea-input" style={{ minHeight: 60 }}
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="Descripción opcional..." />
                </div>
              </form>
            </div>
            <div className="modal-footer">
              <button className="btn btn-primary btn-md" style={{ flex: 1 }}
                onClick={handleSubmit} disabled={saving}>
                {saving ? "Guardando..." : editing ? "Guardar" : "Crear"}
              </button>
              <button className="btn btn-secondary btn-md" style={{ flex: 1 }}
                onClick={close} disabled={saving}>Cancelar</button>
            </div>
          </div>
        </div>
      )}
    </SettingsPanel>
  );
};

export default ServicesSection;
