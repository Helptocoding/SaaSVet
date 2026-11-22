import { useState, useEffect } from "react";
import {
    getStaff, createStaff, updateStaff, deactivateStaff, resetStaffPassword, reactivateStaff,
} from "../api/staff";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import { useConfirm } from "../components/useConfirm";
import SegmentedControl from "../components/SegmentedControl";
import EmptyState from "../components/EmptyState";
import { apiError } from "../utils/apiError";
import handleFormError from "../utils/handleFormError";
import { toast } from "sonner";
import Skeleton from "react-loading-skeleton";
import TableSkeleton from "../components/TableSkeleton";
import styles from "./staff.module.css";

const STAFF_SKELETON_COLUMNS = [
    { label: "Nombre", width: 140 },
    { label: "Usuario", width: 90 },
    { label: "Correo", width: 160 },
    { label: "Rol", cell: () => <Skeleton width={84} height={20} borderRadius="var(--r-full)" /> },
    { label: "Especialidad", width: 90 },
    { label: "Cédula", width: 70 },
];

const EMPTY_FORM = {
    username: "",
    first_name: "",
    last_name: "",
    email: "",
    password: "",
    role: "VET",
    specialty: "",
    license_number: ""
};

// M01 (orden 7): cédula profesional, solo dígitos (5 a 10). Obligatoria para VET.
const LICENSE_RE = /^\d{5,10}$/;
const LICENSE_REQUIRED = "La cédula profesional es obligatoria para veterinarios";
const LICENSE_FORMAT = "La cédula profesional debe tener solo dígitos, entre 5 y 10";

function licenseError(role, value) {
    const license = value.trim();
    if (!license) return role === "VET" ? LICENSE_REQUIRED : null;
    return LICENSE_RE.test(license) ? null : LICENSE_FORMAT;
}

// D4 (plan Equipo): misma regla que el backend (apps/users/serializers.py), que es
// la autoridad. Aquí solo se avisa antes de enviar. NFC + recorte de extremos;
// nada más (sin mayúsculas forzadas ni colapso de espacios).
const PERSON_NAME_RE = /^[A-Za-zÀ-ÖØ-öø-ÿĀ-ž '’-]+$/;

function normalizeName(value) {
    return (value || "").normalize("NFC").trim();
}

function nameError(value, { label, required }) {
    const name = normalizeName(value);
    if (!name) return required ? `${label} es obligatorio.` : null;
    return PERSON_NAME_RE.test(name)
        ? null
        : `${label} solo puede contener letras, espacios, guiones y apóstrofos.`;
}

const USERNAME_RE = /^[A-Za-z0-9_.-]+$/;
const DEMO_EMAIL_HINT = "En la demo usa un correo de ejemplo, como nombre@example.com.";
const EMAIL_CHANGE_NOTICE = "Es su acceso al sistema. Desde que guardes entrará con el correo nuevo; avísale.";

const ROLE_BADGE = {
    ADMIN: "badge-warning",
    VET: "badge-primary",
    ASSISTANT: "badge-default",
};

const ROLE_LABELS = {
    ADMIN: "Administrador",
    VET: "Veterinario",
    ASSISTANT: "Asistente",
};

const fullName = (member) => `${member.first_name} ${member.last_name}`.trim() || member.username;

function createErrors(form) {
    const errors = {};
    const username = form.username.trim();
    if (!username) errors.username = "El nombre de usuario es obligatorio.";
    else if (!USERNAME_RE.test(username)) {
        errors.username = "El nombre de usuario solo puede contener letras, números, puntos, guiones y guiones bajos.";
    }
    const first = nameError(form.first_name, { label: "El nombre", required: true });
    if (first) errors.first_name = first;
    const last = nameError(form.last_name, { label: "El apellido", required: false });
    if (last) errors.last_name = last;
    if (!form.email.trim()) errors.email = "El correo electrónico es obligatorio.";
    if (!form.password || form.password.length < 8) {
        errors.password = "La contraseña debe tener al menos 8 caracteres.";
    } else if (!/[A-Z]/.test(form.password)) {
        errors.password = "La contraseña debe contener al menos una letra mayúscula.";
    } else if (!/[0-9]/.test(form.password)) {
        errors.password = "La contraseña debe contener al menos un número.";
    }
    const license = licenseError(form.role, form.license_number);
    if (license) errors.license_number = license;
    return errors;
}

// Solo lo que cambió respecto del integrante: el backend rechaza claves de más
// y un valor igual no se guarda.
function editChanges(editing) {
    const { member } = editing;
    const changes = {};
    const first = normalizeName(editing.first_name);
    if (first !== member.first_name) changes.first_name = first;
    const last = normalizeName(editing.last_name);
    if (last !== (member.last_name || "")) changes.last_name = last;
    const email = editing.email.trim();
    if (email.toLowerCase() !== (member.email || "").toLowerCase()) changes.email = email;
    const specialty = editing.specialty.trim();
    if (specialty !== (member.specialty || "")) changes.specialty = specialty;
    const license = editing.license_number.trim();
    if (license !== (member.license_number || "")) changes.license_number = license;
    return changes;
}

function FieldError({ message }) {
    return message ? <p className={styles.fieldError}>{message}</p> : null;
}

const inputClass = (error) => `input${error ? " input-error" : ""}`;

// Contraseña temporal: se muestra una sola vez (restablecer y reactivar).
function TempPasswordModal({ result, onClose }) {
    const [copied, setCopied] = useState(false);
    const hours = Math.round((result.expires_in_seconds || 0) / 3600);
    const validity = `${hours} ${hours === 1 ? "hora" : "horas"}`;

    const copy = async () => {
        const lines = [
            `Usuario: ${result.target.username}`,
            `Contraseña temporal: ${result.temp_password}`,
            `Válida por: ${validity}`,
            "Importante: debe cambiar la contraseña al iniciar sesión.",
        ];
        try {
            await navigator.clipboard.writeText(lines.join("\n"));
            setCopied(true);
            toast.success("Credenciales copiadas.");
            setTimeout(() => setCopied(false), 2500);
        } catch {
            toast.error("No se pudo copiar. Selecciona y copia manualmente.");
        }
    };

    return (
        <div className="modal-overlay">
            <div className="modal modal-sm" role="dialog" aria-label="Contraseña temporal generada">
                <div className="modal-header">
                    <h3>Contraseña temporal generada</h3>
                </div>
                <div className="modal-body">
                    <div className={styles.tempWarning}>
                        <strong>⚠ Anota o copia ahora.</strong> Esta contraseña no se vuelve a mostrar. Si la pierdes, deberás restablecerla de nuevo.
                    </div>
                    <dl className={styles.credentials}>
                        <dt>Usuario</dt>
                        <dd className={styles.credentialMono}>{result.target.username}</dd>
                        <dt>Contraseña</dt>
                        <dd className={styles.tempPassword}>{result.temp_password}</dd>
                        <dt>Válida</dt>
                        <dd>{validity} para iniciar sesión</dd>
                    </dl>
                    <p className={styles.tempNote}>
                        Deberá cambiar esta contraseña al iniciar sesión. Entrégala en persona o por un canal privado.
                    </p>
                    <div className={styles.modalActions}>
                        <button type="button" className="btn btn-secondary btn-md" onClick={copy}>
                            {copied ? "Copiado ✓" : "Copiar credenciales"}
                        </button>
                        <button type="button" className="btn btn-primary btn-md" onClick={onClose}>
                            Listo
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

const Staff = () => {
    const { user, initializing, can, refreshUser } = useAuth();
    const confirm = useConfirm();

    // Permisos por capacidad (nunca por rol).
    const canCreate = can("staff.create");
    const canUpdate = can("staff.update");
    const canReset = can("staff.reset_password");
    const canDestroy = can("staff.destroy");
    const canReactivate = can("staff.reactivate");

    const [staff, setStaff] = useState([]);
    const [inactive, setInactive] = useState([]);
    const [view, setView] = useState("active");
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [formErrors, setFormErrors] = useState({});
    // Edición: { member, first_name, last_name, email, specialty, license_number } | null
    const [editing, setEditing] = useState(null);
    const [editErrors, setEditErrors] = useState({});
    // Contraseña temporal (restablecer o reactivar): se muestra una sola vez.
    const [tempResult, setTempResult] = useState(null);

    useEffect(() => {
        if (!initializing && user) {
            fetchStaff();
        }
    }, [initializing, user]);

    // Con `staff.reactivate`, activos e inactivos se cargan en paralelo.
    async function fetchStaff() {
        try {
            const [active, archived] = await Promise.all([
                getStaff(),
                canReactivate ? getStaff({ archived: "true" }) : Promise.resolve([]),
            ]);
            setStaff(active);
            setInactive(archived);
        } catch (err) {
            console.error(apiError(err));
        } finally {
            setLoading(false);
        }
    }

    const isSelf = (member) => user?.id != null && member.id === user.id;
    const showingInactive = canReactivate && view === "inactive";
    const rows = showingInactive ? inactive : staff;
    const hasActions = showingInactive ? canReactivate : (canUpdate || canReset || canDestroy);

    // ── Alta ──────────────────────────────────────────────────────────────
    const openCreate = () => {
        setForm(EMPTY_FORM);
        setFormErrors({});
        setShowModal(true);
    };

    const closeModal = () => {
        setForm(EMPTY_FORM);
        setFormErrors({});
        setShowModal(false);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const errors = createErrors(form);
        setFormErrors(errors);
        if (Object.keys(errors).length > 0) return;

        setSaving(true);
        try {
            await createStaff({
                ...form,
                username: form.username.trim(),
                first_name: normalizeName(form.first_name),
                last_name: normalizeName(form.last_name),
                email: form.email.trim(),
                license_number: form.license_number.trim(),
            });
            toast.success("Usuario creado exitosamente");
            closeModal();
            fetchStaff();
        } catch (err) {
            // El modal queda abierto con los errores en sus campos.
            handleFormError(err, setFormErrors);
        } finally {
            setSaving(false);
        }
    };

    // ── Edición ───────────────────────────────────────────────────────────
    const openEdit = (member) => {
        setEditErrors({});
        setEditing({
            member,
            first_name: member.first_name || "",
            last_name: member.last_name || "",
            email: member.email || "",
            specialty: member.specialty || "",
            license_number: member.license_number || "",
        });
    };

    const editPending = editing ? editChanges(editing) : {};
    const editHasChanges = Object.keys(editPending).length > 0;

    const handleEditSave = async () => {
        if (!editing || !editHasChanges) return;
        const first = nameError(editing.first_name, { label: "El nombre", required: true });
        if (first) { toast.error(first); return; }
        const last = nameError(editing.last_name, { label: "El apellido", required: false });
        if (last) { toast.error(last); return; }
        if (!editing.email.trim()) { toast.error("El correo electrónico es obligatorio."); return; }
        const licenseProblem = licenseError(editing.member.role, editing.license_number);
        if (licenseProblem) { toast.error(licenseProblem); return; }

        const self = isSelf(editing.member);
        setSaving(true);
        try {
            await updateStaff(editing.member.public_id, editPending);
            toast.success("Miembro actualizado");
            setEditing(null);
            if (self) refreshUser?.();
            fetchStaff();
        } catch (err) {
            handleFormError(err, setEditErrors);
        } finally {
            setSaving(false);
        }
    };

    // ── Restablecer, desactivar, reactivar ────────────────────────────────
    const handleResetPassword = async (member) => {
        const ok = await confirm({
            title: "Restablecer contraseña",
            message: `Se generará una contraseña temporal para ${fullName(member)}. Sus sesiones activas se cerrarán y deberá cambiarla en su próximo acceso. La contraseña se mostrará una sola vez.`,
            confirmText: "Restablecer contraseña",
            dangerMode: true,
        });
        if (!ok) return;
        try {
            const data = await resetStaffPassword(member.public_id);
            setTempResult({ ...data, target: member });
        } catch (err) {
            toast.error(apiError(err, "No se pudo restablecer la contraseña."));
        }
    };

    const handleDeactivate = async (member) => {
        const name = fullName(member);
        const ok = await confirm({
            title: `Desactivar acceso de ${name}`,
            message: "Dejará de poder entrar y se cerrarán sus sesiones. Sus citas, consultas y registros se conservan. Revisa en Citas si tiene citas próximas asignadas. Podrás reactivarlo desde Inactivos.",
            confirmText: "Desactivar acceso",
            dangerMode: true,
        });
        if (!ok) return;
        try {
            await deactivateStaff(member.public_id);
            toast.success("Acceso desactivado");
            fetchStaff();
        } catch (err) {
            toast.error(apiError(err, "No se pudo desactivar el acceso."));
        }
    };

    const handleReactivate = async (member) => {
        const role = ROLE_LABELS[member.role] || member.role;
        let message = `Conservará su rol (${role}) y su historial. Se generará una contraseña temporal válida por 24 h que deberá cambiar al entrar.`;
        if (member.role === "VET" && !member.license_number) {
            message += " No tiene cédula profesional registrada: no podrá firmar consultas ni recetas hasta que la captures.";
        }
        const ok = await confirm({
            title: `Reactivar acceso de ${fullName(member)}`,
            message,
            confirmText: "Reactivar acceso",
        });
        if (!ok) return;
        try {
            const data = await reactivateStaff(member.public_id);
            setTempResult({ ...data, target: data.member || member });
        } catch (err) {
            // 409 already_active (p. ej. tras una respuesta perdida): el mensaje
            // del backend indica usar Restablecer contraseña.
            toast.error(apiError(err, "No se pudo reactivar el acceso."));
        } finally {
            fetchStaff();
        }
    };

    if (loading) {
        return (
            <div>
                <div className="page-header">
                    <div>
                        <h1 className="page-title">Equipo</h1>
                        <Skeleton width={90} height={12} />
                    </div>
                </div>
                <div role="status" aria-label="Cargando equipo">
                    <TableSkeleton
                        rows={5}
                        columns={hasActions ? [...STAFF_SKELETON_COLUMNS, { label: "", width: 72 }] : STAFF_SKELETON_COLUMNS}
                    />
                </div>
            </div>
        );
    }

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Equipo</h1>
                    <p className="page-subtitle">
                        {rows.length} miembro{rows.length !== 1 ? "s" : ""}{showingInactive ? " inactivo" + (rows.length !== 1 ? "s" : "") : ""}
                    </p>
                </div>
                {canCreate && (
                    <button className="btn btn-primary btn-md" onClick={openCreate}>
                        <Icon.Plus s={14} /> Agregar miembro
                    </button>
                )}
            </div>

            {canReactivate && (
                <div className={styles.segment}>
                    <SegmentedControl
                        ariaLabel="Mostrar integrantes"
                        options={[
                            { id: "active", label: "Activos" },
                            { id: "inactive", label: "Inactivos" },
                        ]}
                        value={view}
                        onChange={setView}
                    />
                </div>
            )}

            {rows.length === 0 ? (
                showingInactive ? (
                    <EmptyState
                        icon={Icon.Users}
                        title="No hay integrantes inactivos"
                        body="Quien desactives aparecerá aquí y podrás reactivar su acceso."
                    />
                ) : (
                    <div className="empty-state">
                        <p className="empty-state-title">Aún no hay miembros registrados</p>
                        <p className="empty-state-sub">
                            {canCreate ? "Usa el botón de arriba para agregar miembros" : "Contacta al administrador"}
                        </p>
                    </div>
                )
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
                                <th>Cédula</th>
                                {hasActions && <th aria-label="Acciones"></th>}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((member) => {
                                const self = isSelf(member);
                                const locked = Boolean(member.demo_protected);
                                return (
                                    <tr key={member.public_id}>
                                        <td className={styles.nameCell}>
                                            {member.first_name} {member.last_name}
                                            {self && <span className={`badge badge-default ${styles.selfTag}`}>Tú</span>}
                                        </td>
                                        <td className={styles.muted}>@{member.username}</td>
                                        <td className={styles.muted}>{member.email}</td>
                                        <td>
                                            <span className={`badge ${ROLE_BADGE[member.role] || "badge-default"}`}>
                                                {ROLE_LABELS[member.role] || member.role}
                                            </span>
                                        </td>
                                        <td className={styles.subtle}>{member.specialty || "—"}</td>
                                        <td className={styles.mono}>{member.license_number || "—"}</td>
                                        {hasActions && (
                                            <td>
                                                <div className={styles.actions}>
                                                    {showingInactive ? (
                                                        <button
                                                            className="btn btn-secondary btn-sm"
                                                            onClick={() => handleReactivate(member)}
                                                            aria-label={`Reactivar acceso de ${fullName(member)}`}
                                                        >
                                                            <Icon.UserCheck s={14} /> Reactivar
                                                        </button>
                                                    ) : (
                                                        <>
                                                            {canUpdate && !locked && (
                                                                <button
                                                                    className="btn btn-secondary btn-sm"
                                                                    onClick={() => openEdit(member)}
                                                                    aria-label={`Editar a ${fullName(member)}`}
                                                                >
                                                                    <Icon.Edit s={14} /> Editar
                                                                </button>
                                                            )}
                                                            {canReset && !self && !locked && (
                                                                <button
                                                                    className="btn btn-secondary btn-sm"
                                                                    onClick={() => handleResetPassword(member)}
                                                                    aria-label={`Restablecer la contraseña de ${fullName(member)}`}
                                                                >
                                                                    <Icon.Refresh s={14} /> Restablecer
                                                                </button>
                                                            )}
                                                            {canDestroy && !self && !locked && (
                                                                <button
                                                                    className="btn btn-danger btn-sm"
                                                                    onClick={() => handleDeactivate(member)}
                                                                    aria-label={`Desactivar acceso de ${fullName(member)}`}
                                                                >
                                                                    <Icon.UserX s={14} /> Desactivar
                                                                </button>
                                                            )}
                                                        </>
                                                    )}
                                                </div>
                                            </td>
                                        )}
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}

            {tempResult && (
                <TempPasswordModal result={tempResult} onClose={() => setTempResult(null)} />
            )}

            {/* Modal Editar Miembro — identidad (A1), especialidad y cédula (M01) */}
            {editing && (
                <div className="modal-overlay">
                    <div className="modal modal-sm">
                        <div className="modal-header">
                            <h3>Editar miembro</h3>
                            <button className="modal-close" onClick={() => setEditing(null)} disabled={saving} aria-label="Cerrar"><Icon.X s={16} /></button>
                        </div>
                        <div className="modal-body">
                            <p className={styles.editHeading}>
                                {fullName(editing.member)}
                                <span className={styles.editRole}> · {ROLE_LABELS[editing.member.role] || editing.member.role}</span>
                            </p>
                            <div className="form-group">
                                <label className="form-label" htmlFor="edit-first-name">NOMBRE *</label>
                                <input
                                    id="edit-first-name"
                                    className={inputClass(editErrors.first_name)}
                                    value={editing.first_name}
                                    onChange={e => setEditing({ ...editing, first_name: e.target.value })}
                                />
                                <FieldError message={editErrors.first_name} />
                            </div>
                            <div className="form-group">
                                <label className="form-label" htmlFor="edit-last-name">APELLIDO</label>
                                <input
                                    id="edit-last-name"
                                    className={inputClass(editErrors.last_name)}
                                    value={editing.last_name}
                                    onChange={e => setEditing({ ...editing, last_name: e.target.value })}
                                />
                                <FieldError message={editErrors.last_name} />
                            </div>
                            <div className="form-group">
                                <label className="form-label" htmlFor="edit-email">CORREO ELECTRÓNICO *</label>
                                <input
                                    id="edit-email"
                                    type="email"
                                    className={inputClass(editErrors.email)}
                                    value={editing.email}
                                    onChange={e => setEditing({ ...editing, email: e.target.value })}
                                />
                                <FieldError message={editErrors.email} />
                                {"email" in editPending && <p className={styles.notice}>{EMAIL_CHANGE_NOTICE}</p>}
                                {user?.is_demo && <p className="form-hint">{DEMO_EMAIL_HINT}</p>}
                            </div>
                            <div className="form-group">
                                <label className="form-label" htmlFor="edit-specialty">ESPECIALIDAD</label>
                                <input
                                    id="edit-specialty"
                                    className={inputClass(editErrors.specialty)}
                                    placeholder="Cirugía, Dermatología..."
                                    value={editing.specialty}
                                    onChange={e => setEditing({ ...editing, specialty: e.target.value })}
                                />
                                <FieldError message={editErrors.specialty} />
                            </div>
                            <div className="form-group">
                                <label className="form-label" htmlFor="edit-license">
                                    CÉDULA PROFESIONAL{editing.member.role === "VET" ? " *" : ""}
                                </label>
                                <input
                                    id="edit-license"
                                    className={inputClass(editErrors.license_number)}
                                    inputMode="numeric"
                                    placeholder="Solo dígitos"
                                    value={editing.license_number}
                                    onChange={e => setEditing({ ...editing, license_number: e.target.value })}
                                />
                                <FieldError message={editErrors.license_number} />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className={`btn btn-primary btn-md ${styles.footerButton}`} onClick={handleEditSave} disabled={saving || !editHasChanges}>
                                {saving ? "Guardando..." : "Guardar"}
                            </button>
                            <button className={`btn btn-secondary btn-md ${styles.footerButton}`} onClick={() => setEditing(null)} disabled={saving}>
                                Cancelar
                            </button>
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
                            <button className="modal-close" onClick={closeModal} aria-label="Cerrar"><Icon.X s={16} /></button>
                        </div>
                        <div className="modal-body">
                            <form onSubmit={handleSubmit} noValidate>
                                <div className={styles.formGrid}>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-username">NOMBRE DE USUARIO *</label>
                                        <input
                                            id="create-username"
                                            className={inputClass(formErrors.username)}
                                            placeholder="usuario123"
                                            value={form.username}
                                            onChange={e => setForm({ ...form, username: e.target.value })}
                                        />
                                        <FieldError message={formErrors.username} />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-email">CORREO ELECTRÓNICO *</label>
                                        <input
                                            id="create-email"
                                            type="email"
                                            className={inputClass(formErrors.email)}
                                            placeholder="correo@ejemplo.com"
                                            value={form.email}
                                            onChange={e => setForm({ ...form, email: e.target.value })}
                                        />
                                        <FieldError message={formErrors.email} />
                                        {user?.is_demo && <p className="form-hint">{DEMO_EMAIL_HINT}</p>}
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-first-name">NOMBRE *</label>
                                        <input
                                            id="create-first-name"
                                            className={inputClass(formErrors.first_name)}
                                            placeholder="Juan"
                                            value={form.first_name}
                                            onChange={e => setForm({ ...form, first_name: e.target.value })}
                                        />
                                        <FieldError message={formErrors.first_name} />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-last-name">APELLIDO</label>
                                        <input
                                            id="create-last-name"
                                            className={inputClass(formErrors.last_name)}
                                            placeholder="Pérez"
                                            value={form.last_name}
                                            onChange={e => setForm({ ...form, last_name: e.target.value })}
                                        />
                                        <FieldError message={formErrors.last_name} />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-password">CONTRASEÑA *</label>
                                        <input
                                            id="create-password"
                                            type="password"
                                            className={inputClass(formErrors.password)}
                                            placeholder="Mínimo 8 caracteres"
                                            value={form.password}
                                            onChange={e => setForm({ ...form, password: e.target.value })}
                                        />
                                        <FieldError message={formErrors.password} />
                                        <p className="form-hint">
                                            Al menos 8 caracteres, una mayúscula y un número. Deberá cambiarla en su primer acceso.
                                        </p>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-role">ROL *</label>
                                        <select
                                            id="create-role"
                                            className="select-input"
                                            value={form.role}
                                            onChange={e => setForm({ ...form, role: e.target.value })}
                                        >
                                            <option value="VET">Veterinario</option>
                                            <option value="ASSISTANT">Asistente</option>
                                            <option value="ADMIN">Administrador</option>
                                        </select>
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-specialty">ESPECIALIDAD</label>
                                        <input
                                            id="create-specialty"
                                            className={inputClass(formErrors.specialty)}
                                            placeholder="Cirugía, Dermatología..."
                                            value={form.specialty}
                                            onChange={e => setForm({ ...form, specialty: e.target.value })}
                                        />
                                        <FieldError message={formErrors.specialty} />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-license">
                                            CÉDULA PROFESIONAL{form.role === "VET" ? " *" : ""}
                                        </label>
                                        <input
                                            id="create-license"
                                            className={inputClass(formErrors.license_number)}
                                            inputMode="numeric"
                                            placeholder="Solo dígitos"
                                            value={form.license_number}
                                            onChange={e => setForm({ ...form, license_number: e.target.value })}
                                        />
                                        <FieldError message={formErrors.license_number} />
                                    </div>
                                </div>
                            </form>
                        </div>
                        <div className="modal-footer">
                            <button className={`btn btn-primary btn-md ${styles.footerButton}`} onClick={handleSubmit} disabled={saving}>
                                {saving ? "Guardando..." : "Guardar"}
                            </button>
                            <button className={`btn btn-secondary btn-md ${styles.footerButton}`} onClick={closeModal} disabled={saving}>
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
