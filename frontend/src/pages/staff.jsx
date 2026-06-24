import { useState, useEffect } from "react";
import { getStaff, createStaff, deactivateStaff, resetStaffPassword } from "../api/staff";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import { useConfirm } from "../components/useConfirm";
import { toast } from "sonner";

const EMPTY_FORM = {
    username: "",
    first_name: "",
    last_name: "",
    email: "",
    password: "",
    role: "VET",
    specialty: ""
};

const ROLE_BADGE = {
    ADMIN_SAAS: "badge-danger",
    ADMIN: "badge-warning",
    VET: "badge-primary",
    ASSISTANT: "badge-default",
};

const ROLE_LABELS = {
    ADMIN_SAAS: "Admin SaaS",
    ADMIN: "Administrador",
    VET: "Veterinario",
    ASSISTANT: "Asistente",
};

const Staff = () => {
    const { user, initializing } = useAuth();
    const confirm = useConfirm();
    const isAdmin = user?.role === "ADMIN";

    const [staff, setStaff] = useState([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    // Temp password modal state — surfaced once after successful reset.
    const [resetResult, setResetResult] = useState(null);
    const [resetCopied, setResetCopied] = useState(false);

    useEffect(() => {
        if (!initializing && user) {
            fetchStaff();
        }
    }, [initializing, user]);

    const fetchStaff = async () => {
        try {
            setLoading(true);
            const data = await getStaff();
            setStaff(data);
        } catch (err) {
            console.log(err);
        } finally {
            setLoading(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        const usernameRe = /^[A-Za-z0-9_.-]+$/;
        const nameRe = /^[A-Za-zÁÉÍÓÚáéíóúñÑ ]+$/;

        if (!form.username.trim()) { toast.error("El nombre de usuario es obligatorio"); return; }
        if (!usernameRe.test(form.username.trim())) { toast.error("El usuario solo puede contener letras, números, puntos, guiones y guiones bajos"); return; }
        if (!form.first_name.trim()) { toast.error("El nombre es obligatorio"); return; }
        if (!nameRe.test(form.first_name.trim())) { toast.error("El nombre solo puede contener letras y espacios"); return; }
        if (!form.email.trim()) { toast.error("El correo electrónico es obligatorio"); return; }
        if (!form.password || form.password.length < 8) { toast.error("La contraseña debe tener al menos 8 caracteres"); return; }
        if (!/[A-Z]/.test(form.password)) { toast.error("La contraseña debe contener al menos una mayúscula"); return; }
        if (!/[0-9]/.test(form.password)) { toast.error("La contraseña debe contener al menos un número"); return; }

        setSaving(true);
        try {
            await toast.promise(createStaff(form), {
                loading: 'Creando usuario...',
                success: 'Usuario creado exitosamente',
                error: (err) => {
                    const d = err.response?.data;
                    if (d) {
                        const first = Object.values(d).flat()[0];
                        if (first) return String(first);
                    }
                    return "Error al crear usuario";
                },
            });
            setForm(EMPTY_FORM);
            setShowModal(false);
            fetchStaff();
        } catch {
            // Modal stays open — toast already shows the error
        } finally {
            setSaving(false);
        }
    };

    const handleDeactivate = async (id) => {
        const ok = await confirm({
            title: "Desactivar miembro",
            message: "El miembro perderá acceso al sistema. Esta acción se puede revertir desde la base de datos.",
            confirmText: "Desactivar",
            dangerMode: true,
        });
        if (!ok) return;
        try {
            await toast.promise(deactivateStaff(id), {
                loading: 'Desactivando...',
                success: 'Usuario desactivado',
                error: 'Error al desactivar usuario'
            });
            fetchStaff();
        } catch {
            // el error ya lo muestra toast.promise
        }
    };

    const closeModal = () => {
        setForm(EMPTY_FORM);
        setShowModal(false);
    };

    const handleResetPassword = async (member) => {
        const ok = await confirm({
            title: "Resetear contraseña",
            message: `Se generará una contraseña temporal para ${member.first_name} ${member.last_name}. Sus sesiones activas serán cerradas y deberá cambiarla en su próximo login. La contraseña se mostrará una sola vez.`,
            confirmText: "Resetear contraseña",
            dangerMode: true,
        });
        if (!ok) return;
        try {
            const data = await resetStaffPassword(member.public_id);
            setResetResult({ ...data, target: member });
            setResetCopied(false);
        } catch (err) {
            const code = err?.response?.status;
            if (code === 429) {
                toast.error("Límite de 5 resets por hora alcanzado.");
            } else if (code === 403) {
                toast.error("No tienes permiso para resetear esta cuenta.");
            } else {
                toast.error("Error al resetear la contraseña.");
            }
        }
    };

    const copyResetCredentials = async () => {
        if (!resetResult) return;
        const lines = [
            `Usuario: ${resetResult.target.username}`,
            `Contraseña temporal: ${resetResult.temp_password}`,
            `Válida por: 24 horas`,
            `Importante: debe cambiar la contraseña al iniciar sesión.`,
        ];
        try {
            await navigator.clipboard.writeText(lines.join("\n"));
            setResetCopied(true);
            toast.success("Credenciales copiadas.");
            setTimeout(() => setResetCopied(false), 2500);
        } catch {
            toast.error("No se pudo copiar. Selecciona y copia manualmente.");
        }
    };

    if (loading) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
                <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</p>
            </div>
        );
    }

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Equipo</h1>
                    <p className="page-subtitle">{staff.length} miembro{staff.length !== 1 ? "s" : ""}</p>
                </div>
                {isAdmin && (
                    <button
                        className="btn btn-primary btn-md"
                        onClick={() => setShowModal(true)}
                    >
                        + Agregar miembro
                    </button>
                )}
            </div>

            {staff.length === 0 ? (
                <div className="empty-state">
                    <p className="empty-state-title">Aún no hay miembros registrados</p>
                    <p className="empty-state-sub">
                        {isAdmin ? "Usa el botón de arriba para agregar miembros" : "Contacta al administrador"}
                    </p>
                </div>
            ) : (
                <div className="table-wrap">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Nombre</th>
                                <th>Usuario</th>
                                <th>Correo</th>
                                <th>Rol</th>
                                <th>Especialidad</th>
                                {isAdmin && <th></th>}
                            </tr>
                        </thead>
                        <tbody>
                            {staff.map((member) => (
                                <tr key={member.id}>
                                    <td style={{ fontWeight: "600" }}>
                                        {member.first_name} {member.last_name}
                                    </td>
                                    <td style={{ color: "var(--c-text-2)" }}>@{member.username}</td>
                                    <td style={{ color: "var(--c-text-2)" }}>{member.email}</td>
                                    <td>
                                        <span className={`badge ${ROLE_BADGE[member.role] || "badge-default"}`}>
                                            {ROLE_LABELS[member.role] || member.role}
                                        </span>
                                    </td>
                                    <td style={{ color: "var(--c-text-3)" }}>{member.specialty || "—"}</td>
                                    {isAdmin && (
                                        <td>
                                            <div style={{ display: "flex", gap: "6px" }}>
                                                {member.role !== "ADMIN_SAAS" && (
                                                    <button
                                                        className="btn btn-secondary btn-sm"
                                                        onClick={() => handleResetPassword(member)}
                                                        title="Resetear contraseña"
                                                    >
                                                        <Icon.Refresh s={14} />
                                                    </button>
                                                )}
                                                <button
                                                    className="btn btn-danger btn-sm"
                                                    onClick={() => handleDeactivate(member.public_id)}
                                                    title="Desactivar"
                                                >
                                                    <Icon.Trash s={14} />
                                                </button>
                                            </div>
                                        </td>
                                    )}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Modal Temp Password — display once, never persisted */}
            {resetResult && (
                <div className="modal-overlay">
                    <div className="modal modal-sm">
                        <div className="modal-header">
                            <h3>Contraseña temporal generada</h3>
                        </div>
                        <div className="modal-body">
                            <div style={{
                                background: "rgba(251,191,36,0.10)",
                                border: "1px solid rgba(251,191,36,0.30)",
                                borderRadius: "6px",
                                padding: "10px 12px",
                                marginBottom: "14px",
                                fontSize: "12.5px",
                                color: "#fbbf24",
                            }}>
                                <strong>⚠ Anota o copia ahora.</strong> Esta contraseña no se vuelve a mostrar. Si la pierdes, deberás resetear de nuevo.
                            </div>

                            <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "8px 14px", margin: 0 }}>
                                <dt style={{ fontSize: "11.5px", color: "var(--c-text-3)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: "500" }}>
                                    Usuario
                                </dt>
                                <dd style={{ margin: 0, fontSize: "13px", fontFamily: "var(--font-mono)" }}>
                                    {resetResult.target.username}
                                </dd>

                                <dt style={{ fontSize: "11.5px", color: "var(--c-text-3)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: "500" }}>
                                    Contraseña
                                </dt>
                                <dd style={{ margin: 0, fontSize: "13px", color: "#fbbf24", fontFamily: "var(--font-mono)", fontWeight: "600", wordBreak: "break-all" }}>
                                    {resetResult.temp_password}
                                </dd>

                                <dt style={{ fontSize: "11.5px", color: "var(--c-text-3)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: "500" }}>
                                    Válida
                                </dt>
                                <dd style={{ margin: 0, fontSize: "12.5px", color: "var(--c-text-2)" }}>
                                    24 horas para iniciar sesión
                                </dd>
                            </dl>

                            <p style={{ fontSize: "11.5px", color: "var(--c-text-3)", marginTop: "14px" }}>
                                El usuario deberá cambiar esta contraseña al iniciar sesión.
                                Envíasela por canal seguro (NO Slack / WhatsApp / SMS).
                            </p>

                            <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-md"
                                    onClick={copyResetCredentials}
                                >
                                    {resetCopied ? "Copiado ✓" : "Copiar credenciales"}
                                </button>
                                <button
                                    type="button"
                                    className="btn btn-primary btn-md"
                                    onClick={() => setResetResult(null)}
                                >
                                    Listo
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Modal Nuevo Miembro */}
            {showModal && (
                <div className="modal-overlay">
                    <div className="modal modal-lg">
                        <div className="modal-header">
                            <h3>Nuevo Miembro</h3>
                            <button className="modal-close" onClick={closeModal}><Icon.X s={16} /></button>
                        </div>
                        <div className="modal-body">
                            <form onSubmit={handleSubmit}>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 14px" }}>
                                    <div className="form-group">
                                        <label className="form-label">NOMBRE DE USUARIO *</label>
                                        <input
                                            className="input"
                                            placeholder="usuario123"
                                            value={form.username}
                                            onChange={e => setForm({ ...form, username: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">CORREO ELECTRÓNICO *</label>
                                        <input
                                            type="email"
                                            className="input"
                                            placeholder="correo@ejemplo.com"
                                            value={form.email}
                                            onChange={e => setForm({ ...form, email: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">NOMBRE *</label>
                                        <input
                                            className="input"
                                            placeholder="Juan"
                                            value={form.first_name}
                                            onChange={e => setForm({ ...form, first_name: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">APELLIDO</label>
                                        <input
                                            className="input"
                                            placeholder="Pérez"
                                            value={form.last_name}
                                            onChange={e => setForm({ ...form, last_name: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">CONTRASEÑA *</label>
                                        <input
                                            type="password"
                                            className="input"
                                            placeholder="Mínimo 6 caracteres"
                                            value={form.password}
                                            onChange={e => setForm({ ...form, password: e.target.value })}
                                        />
                                        <div style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>
                                            Contraseña temporal: el empleado deberá cambiarla en su primer acceso.
                                        </div>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label">ROL *</label>
                                        <select
                                            className="select-input"
                                            value={form.role}
                                            onChange={e => setForm({ ...form, role: e.target.value })}
                                        >
                                            <option value="VET">Veterinario</option>
                                            <option value="ASSISTANT">Asistente</option>
                                            <option value="ADMIN">Administrador</option>
                                        </select>
                                    </div>
                                    <div className="form-group" style={{ gridColumn: "1 / -1" }}>
                                        <label className="form-label">ESPECIALIDAD</label>
                                        <input
                                            className="input"
                                            placeholder="Cirugía, Dermatología..."
                                            value={form.specialty}
                                            onChange={e => setForm({ ...form, specialty: e.target.value })}
                                        />
                                    </div>
                                </div>
                            </form>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleSubmit} disabled={saving}>
                                {saving ? "Guardando..." : "Guardar"}
                            </button>
                            <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={closeModal} disabled={saving}>
                                Cancelar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Staff;
