import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { useConfirm } from "../components/useConfirm";
import { getServices, createService, updateService, deleteService } from "../api/billing";
import { getOrgSettings, updateOrgSettings } from "../api/organizations";
import { apiError } from "../utils/apiError";
import { toList } from "../utils/toList";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import ChangePasswordForm from "../components/ChangePasswordForm";
import EmptyState from "../components/EmptyState";
import { toast } from "sonner";

const EMPTY_SERVICE = { name: "", description: "", base_price: "", is_active: true };

const FLOW_TOGGLES = [
    {
        key: "auto_create_invoice_on_done",
        label: "Crear factura automática al completar cita",
        description: "Al marcar una cita como completada, se genera una factura en borrador automáticamente.",
    },
    {
        key: "require_confirmation_before_start",
        label: "Requerir confirmación antes de iniciar consulta",
        description: "No se puede pasar a 'En consulta' sin pasar primero por 'Confirmada'.",
    },
    {
        key: "auto_create_medical_record",
        label: "Crear historial clínico automático al completar cita",
        description: "Al completar una cita, se abre un historial clínico vacío listo para que el veterinario lo llene.",
    },
    {
        key: "allow_anonymous_walkin",
        label: "Permitir atención sin cita (sin mascota registrada)",
        description: "Permite registrar una consulta sin seleccionar mascota, usando la mascota anónima genérica.",
    },
    {
        key: "show_status_change_history",
        label: "Mostrar historial de cambios de estado en citas",
        description: "Muestra un registro de cada cambio de estado en el detalle de la cita.",
    },
    {
        key: "require_open_cash_session",
        label: "Requerir caja abierta para cobrar",
        description: "Obliga a tener un turno de caja abierto para registrar cobros y pagos. Los cobros se vinculan al turno para el corte Z.",
    },
];

const ToggleSwitch = ({ checked, disabled, onChange }) => (
    <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={onChange}
        style={{
            position: "relative", flexShrink: 0,
            width: 40, height: 22,
            borderRadius: 11,
            background: checked ? "var(--c-primary)" : "var(--c-border)",
            border: "none", cursor: disabled ? "not-allowed" : "pointer",
            transition: "background 0.25s ease",
            opacity: disabled ? 0.5 : 1,
        }}
    >
        <span
            style={{
                position: "absolute", top: 2, left: checked ? 20 : 2,
                width: 18, height: 18, borderRadius: "50%",
                background: "#fff",
                boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                transition: "left 0.25s cubic-bezier(0.34, 1.56, 0.64, 1)",
            }}
        />
    </button>
);

const sectionVariants = {
    hidden: { opacity: 0, y: 12 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: "easeOut" } },
};

const rowVariants = {
    hidden: { opacity: 0, x: -8 },
    visible: (i) => ({
        opacity: 1, x: 0,
        transition: { delay: i * 0.04, duration: 0.25, ease: "easeOut" },
    }),
};

const Config = () => {
    const { token, user, initializing, can } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const confirm = useConfirm();
    const [services, setServices] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [editingService, setEditingService] = useState(null);
    const [form, setForm] = useState(EMPTY_SERVICE);

    const [orgSettings, setOrgSettings] = useState(null);
    const [savingToggle, setSavingToggle] = useState(null);
    const [saving, setSaving] = useState(false);
    const [showPasswordModal, setShowPasswordModal] = useState(false);

    useEffect(() => {
        const handler = () => setShowPasswordModal(true);
        window.addEventListener("open-change-password", handler);
        return () => window.removeEventListener("open-change-password", handler);
    }, []);

    // ADMIN_SAAS no pertenece a una clínica — los endpoints tenant-scoped
    // (services, orgSettings) responden 404 / 400 si user.organization es null.
    // Skip fetches y mostrar solo "Mi cuenta" para él.
    const isPlatformOperator = user?.role === "ADMIN_SAAS";
    const hasOrg = !!user?.organization;
    const showTenantSections = !isPlatformOperator && hasOrg;

    useEffect(() => {
        if (!token) return;
        if (!showTenantSections) {
            setLoading(false);
            return;
        }
        loadServices();
        getOrgSettings()
            .then(setOrgSettings)
            .catch(err => console.error('[Config] OrgSettings error:', apiError(err)));
    }, [token, showTenantSections]);

    const loadServices = async () => {
        setLoading(true);
        try {
            const data = await getServices();
            setServices(toList(data));
        } catch (err) {
            console.error(apiError(err));
        } finally {
            setLoading(false);
        }
    };

    const handleToggle = async (key, value) => {
        setSavingToggle(key);
        try {
            const updated = await updateOrgSettings({ [key]: value });
            setOrgSettings(updated);
            toast.success("Configuración guardada");
        } catch {
            toast.error("Error al guardar configuración");
        } finally {
            setSavingToggle(null);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!form.name.trim()) { toast.error("El nombre es obligatorio"); return; }
        if (!form.base_price || Number(form.base_price) <= 0) { toast.error("El precio debe ser mayor a 0"); return; }
        setSaving(true);
        try {
            if (editingService) {
                await updateService(editingService.public_id, form);
            } else {
                await createService(form);
            }
            toast.success(editingService ? 'Servicio actualizado' : 'Servicio creado');
            closeModal();
            // Onboarding: volver al dashboard automáticamente tras crear el 1er servicio.
            if (!editingService && location.state?.fromOnboarding) {
                navigate("/", { state: { onboardingStep: "has_services" } });
                return;
            }
            await loadServices();
        } catch (err) {
            toast.error(apiError(err, "Error al guardar el servicio"));
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (id) => {
        const ok = await confirm({ message: "¿Eliminar este servicio?", confirmText: "Eliminar", dangerMode: true });
        if (!ok) return;
        try {
            await toast.promise(deleteService(id), {
                loading: 'Eliminando...',
                success: 'Servicio eliminado',
                error: 'No se puede eliminar: puede estar en uso en facturas'
            });
            loadServices();
        } catch {
            // el error ya lo muestra toast.promise
        }
    };

    const openEdit = (svc) => {
        setEditingService(svc);
        setForm({ name: svc.name, description: svc.description || "", base_price: svc.base_price, is_active: svc.is_active });
        setShowModal(true);
    };

    const closeModal = () => {
        setShowModal(false);
        setEditingService(null);
        setForm(EMPTY_SERVICE);
    };

    const formatCurrency = (amount) => Number(amount || 0).toFixed(2);

    if (initializing || loading) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
                <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</p>
            </div>
        );
    }

    const canManage = user?.role !== "ASSISTANT";

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Configuración</h1>
                    <p className="page-subtitle">Ajustes y catálogos de tu organización</p>
                </div>
            </div>

            {/* Secciones tenant-scoped — ocultas para ADMIN_SAAS sin clínica. */}
            {!showTenantSections && (
                <div className="card" style={{ marginBottom: "20px" }}>
                    <p style={{ fontSize: "12.5px", color: "var(--c-text-3)" }}>
                        Las configuraciones de flujo clínico y catálogo de servicios
                        están disponibles solo para administradores de una clínica.
                    </p>
                </div>
            )}

            {/* Catálogo de Servicios — tenant-scoped */}
            {showTenantSections && (
                <motion.div
                    variants={sectionVariants} initial="hidden" animate="visible"
                    style={{
                        background: "var(--c-surface)", borderRadius: "var(--r-lg)",
                        border: "1px solid var(--c-border)",
                        boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)",
                        marginBottom: "24px", overflow: "hidden",
                        transition: "box-shadow 0.25s ease, transform 0.25s ease",
                    }}
                    onMouseEnter={e => { e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                    onMouseLeave={e => { e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)"; e.currentTarget.style.transform = "translateY(0)"; }}
                >
                    <div style={{
                        padding: "18px 22px",
                        borderBottom: "1px solid var(--c-border)",
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                    }}>
                        <div>
                            <p style={{ fontWeight: "600", fontSize: "14px", marginBottom: "3px" }}>Catálogo de Servicios</p>
                            <p style={{ fontSize: "12.5px", color: "var(--c-text-3)" }}>
                                Servicios que puedes agregar al facturar una consulta o venta
                            </p>
                        </div>
                        {canManage && (
                            <button
                                className="btn btn-primary btn-sm"
                                onClick={() => { setEditingService(null); setForm(EMPTY_SERVICE); setShowModal(true); }}
                            >
                                + Nuevo Servicio
                            </button>
                        )}
                    </div>

                    <div style={{ padding: services.length === 0 ? "0" : "10px 14px 14px" }}>
                    {services.length === 0 ? (
                        <EmptyState
                            compact
                            title="Define los servicios que cobras"
                            body="Consulta, vacunación, cirugía… los usarás al facturar una consulta o venta."
                            actions={[
                                can("service.create")
                                    ? { label: "Nuevo servicio", onClick: () => { setEditingService(null); setForm(EMPTY_SERVICE); setShowModal(true); }, variant: "primary" }
                                    : null,
                            ]}
                        />
                    ) : (
                        <div style={{ display: "grid", gap: "4px" }}>
                            {services.map((svc, i) => (
                                <motion.div
                                    key={svc.id}
                                    custom={i}
                                    variants={rowVariants}
                                    initial="hidden"
                                    animate="visible"
                                    style={{
                                        display: "flex", justifyContent: "space-between", alignItems: "center",
                                        padding: "10px 12px", borderRadius: "var(--r-md)",
                                        cursor: "default",
                                    }}
                                    whileHover={{ backgroundColor: "var(--c-subtle)", x: 2 }}
                                    transition={{ type: "spring", stiffness: 400, damping: 25 }}
                                >
                                    <div>
                                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <span style={{ fontWeight: "500", fontSize: "13.5px", color: svc.is_active ? "var(--c-text)" : "var(--c-text-3)" }}>
                                                {svc.name}
                                            </span>
                                            {!svc.is_active && <span className="badge badge-default">Inactivo</span>}
                                        </div>
                                        {svc.description && (
                                            <p style={{ fontSize: "12px", color: "var(--c-text-3)", marginTop: "1px" }}>{svc.description}</p>
                                        )}
                                    </div>
                                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                        <span style={{ fontWeight: "600", color: "var(--c-text-2)", fontSize: "13px" }}>
                                            ${formatCurrency(svc.base_price)}
                                        </span>
                                        {canManage && (
                                            <div style={{ display: "flex", gap: "4px" }}>
                                                <motion.button
                                                    className="btn btn-secondary btn-sm"
                                                    style={{ padding: "4px 8px" }}
                                                    onClick={() => openEdit(svc)} title="Editar"
                                                    whileHover={{ scale: 1.05 }}
                                                    whileTap={{ scale: 0.95 }}
                                                >
                                                    <Icon.Edit s={13} />
                                                </motion.button>
                                                <motion.button
                                                    className="btn btn-danger btn-sm"
                                                    style={{ padding: "4px 8px" }}
                                                    onClick={() => handleDelete(svc.public_id)} title="Eliminar"
                                                    whileHover={{ scale: 1.05 }}
                                                    whileTap={{ scale: 0.95 }}
                                                >
                                                    <Icon.Trash s={13} />
                                                </motion.button>
                                            </div>
                                        )}
                                    </div>
                                </motion.div>
                            ))}
                        </div>
                    )}
                    </div>
                </motion.div>
            )}

            {/* Flujo Clínico */}
            {showTenantSections && orgSettings !== null && (
                <motion.div
                    variants={sectionVariants} initial="hidden" animate="visible"
                    style={{
                        background: "var(--c-surface)", borderRadius: "var(--r-lg)",
                        border: "1px solid var(--c-border)",
                        boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)",
                        overflow: "hidden",
                        transition: "box-shadow 0.25s ease, transform 0.25s ease",
                    }}
                    onMouseEnter={e => { e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                    onMouseLeave={e => { e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)"; e.currentTarget.style.transform = "translateY(0)"; }}
                >
                    <div style={{
                        padding: "18px 22px",
                        borderBottom: "1px solid var(--c-border)",
                    }}>
                        <p style={{ fontWeight: "600", fontSize: "14px", marginBottom: "3px" }}>Flujo Clínico</p>
                        <p style={{ fontSize: "12.5px", color: "var(--c-text-3)" }}>
                            Comportamiento automático de citas y consultas en tu organización
                        </p>
                    </div>
                    <div style={{ padding: "6px 22px 10px" }}>
                        {FLOW_TOGGLES.map(({ key, label, description }, i) => (
                            <motion.div
                                key={key}
                                custom={i}
                                variants={rowVariants}
                                initial="hidden"
                                animate="visible"
                                style={{
                                    display: "flex", justifyContent: "space-between", alignItems: "flex-start",
                                    padding: "14px 0",
                                    borderBottom: i < FLOW_TOGGLES.length - 1 ? "1px solid var(--c-border)" : "none",
                                    opacity: savingToggle === key ? 0.5 : 1,
                                    transition: "opacity 0.15s",
                                }}
                                whileHover={{ x: 3 }}
                                transition={{ type: "spring", stiffness: 400, damping: 25 }}
                            >
                                <div style={{ flex: 1, marginRight: "16px" }}>
                                    <p style={{ fontWeight: "500", fontSize: "13.5px", marginBottom: "2px" }}>{label}</p>
                                    <p style={{ fontSize: "12px", color: "var(--c-text-3)", lineHeight: 1.4 }}>{description}</p>
                                </div>
                                <ToggleSwitch
                                    checked={!!orgSettings[key]}
                                    disabled={savingToggle === key || !canManage}
                                    onChange={() => handleToggle(key, !orgSettings[key])}
                                />
                            </motion.div>
                        ))}
                    </div>
                </motion.div>
            )}

            {/* Modal */}
            {showModal && (
                <div className="modal-overlay">
                    <div className="modal modal-sm">
                        <div className="modal-header">
                            <h3>{editingService ? "Editar Servicio" : "Nuevo Servicio"}</h3>
                            <button className="modal-close" onClick={closeModal}><Icon.X s={16} /></button>
                        </div>
                        <div className="modal-body">
                            <form onSubmit={handleSubmit}>
                                <div className="form-group">
                                    <label className="form-label" htmlFor="service-name">NOMBRE *</label>
                                    <input
                                        id="service-name"
                                        name="service-name"
                                        className="input"
                                        value={form.name}
                                        onChange={e => setForm({ ...form, name: e.target.value })}
                                        placeholder="Ej: Consulta general"
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label" htmlFor="service-price">PRECIO BASE *</label>
                                    <input
                                        id="service-price"
                                        name="service-price"
                                        type="number"
                                        step="0.01"
                                        min="0"
                                        className="input"
                                        value={form.base_price}
                                        onChange={e => setForm({ ...form, base_price: e.target.value })}
                                        placeholder="0.00"
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label" htmlFor="service-description">DESCRIPCIÓN</label>
                                    <textarea
                                        id="service-description"
                                        name="service-description"
                                        className="textarea-input"
                                        style={{ minHeight: "60px" }}
                                        value={form.description}
                                        onChange={e => setForm({ ...form, description: e.target.value })}
                                        placeholder="Descripción opcional..."
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="checkbox-label">
                                        <input
                                            id="service-active"
                                            name="service-active"
                                            type="checkbox"
                                            checked={form.is_active}
                                            onChange={e => setForm({ ...form, is_active: e.target.checked })}
                                        />
                                        Activo (visible en facturación)
                                    </label>
                                </div>
                            </form>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleSubmit} disabled={saving}>
                                {saving ? "Guardando..." : editingService ? "Guardar" : "Crear"}
                            </button>
                            <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={closeModal} disabled={saving}>
                                Cancelar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Modal cambiar contraseña */}
            {showPasswordModal && (
                <div className="modal-overlay">
                    <div className="modal modal-sm">
                        <div className="modal-header">
                            <h3>Cambiar contraseña</h3>
                            <button className="modal-close" onClick={() => setShowPasswordModal(false)}>
                                <Icon.X s={16} />
                            </button>
                        </div>
                        <div className="modal-body">
                            <ChangePasswordForm />
                        </div>
                        <div className="modal-footer">
                            <button
                                className="btn btn-secondary btn-md"
                                style={{ flex: 1 }}
                                onClick={() => setShowPasswordModal(false)}
                            >
                                Cerrar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Config;
