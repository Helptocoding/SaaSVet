import { useState, useEffect } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import {
    getStaff, createStaff, updateStaff, deactivateStaff, resetStaffPassword, reactivateStaff,
    changeStaffRole, getStaffImpact,
} from "../api/staff";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import { useConfirm } from "../components/useConfirm";
import SegmentedControl from "../components/SegmentedControl";
import EmptyState from "../components/EmptyState";
import ActionMenu from "../components/ActionMenu";
import { apiError } from "../utils/apiError";
import handleFormError from "../utils/handleFormError";
import { orgTz } from "../utils/datetime";
import { STAFF_MANAGEMENT_PERMS } from "../features/staff/permissions";
import { STAFF_ROLE_ORDER, roleLabel, roleShort, roleSummary } from "../features/staff/roles";
import { describeAccess, PENDING_ACCESS } from "../features/staff/access";
import { toast } from "sonner";
import Skeleton from "react-loading-skeleton";
import TableSkeleton from "../components/TableSkeleton";
import styles from "./staff.module.css";

const twoLines = (first, second) => () => (
    <div>
        <Skeleton width={first} height={13} />
        <Skeleton width={second} height={11} />
    </div>
);

const STAFF_SKELETON_COLUMNS = [
    { label: "Integrante", cell: twoLines(140, 170) },
    { label: "Rol", cell: twoLines(90, 150) },
    { label: "Datos profesionales", cell: twoLines(90, 110) },
    { label: "Acceso", cell: twoLines(80, 130) },
];

const EMPTY_FORM = {
    username: "",
    first_name: "",
    last_name: "",
    email: "",
    role: "VET",
    attends_patients: false,
    specialty: "",
    license_number: ""
};

// M01 (orden 7): cédula profesional, solo dígitos (5 a 10). Obligatoria para VET.
const LICENSE_RE = /^\d{5,10}$/;
const LICENSE_REQUIRED = "La cédula profesional es obligatoria para veterinarios";
const LICENSE_REQUIRED_CLINICIAN = "La cédula profesional es obligatoria para quien atiende pacientes";
const LICENSE_FORMAT = "La cédula profesional debe tener solo dígitos, entre 5 y 10";

// ADR p66: atiende quien es VET, o ADMIN marcado. Misma regla que
// apps/users/professional.py (la autoridad); aquí solo se avisa antes de enviar.
const attendsFor = (role, attendsPatients) => role === "VET" || (role === "ADMIN" && Boolean(attendsPatients));

function licenseError(role, value, attendsPatients = false) {
    const license = value.trim();
    if (!license) {
        if (role === "VET") return LICENSE_REQUIRED;
        return attendsFor(role, attendsPatients) ? LICENSE_REQUIRED_CLINICIAN : null;
    }
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

const fullName = (member) => `${member.first_name} ${member.last_name}`.trim() || member.username;

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

// Resumen del equipo bajo el título (Fase 1 Equipo): cuenta lo que ya se cargó.
function teamSummary(active, inactive, showInactive) {
    const parts = [plural(active.length, "activo", "activos")];
    if (showInactive) parts.push(plural(inactive.length, "inactivo", "inactivos"));
    const pending = active.filter((member) => PENDING_ACCESS.has(member.access?.status)).length;
    if (pending > 0) parts.push(`${pending} con acceso pendiente`);
    return parts.join(" · ");
}

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
    const license = licenseError(form.role, form.license_number, form.attends_patients);
    if (license) errors.license_number = license;
    return errors;
}

function editErrorsFor(editing) {
    const errors = {};
    const first = nameError(editing.first_name, { label: "El nombre", required: true });
    if (first) errors.first_name = first;
    const last = nameError(editing.last_name, { label: "El apellido", required: false });
    if (last) errors.last_name = last;
    if (!editing.email.trim()) errors.email = "El correo electrónico es obligatorio.";
    const license = licenseError(editing.member.role, editing.license_number, editing.attends_patients);
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
    if (member.role === "ADMIN" && editing.attends_patients !== Boolean(member.attends_patients)) {
        changes.attends_patients = editing.attends_patients;
    }
    return changes;
}

function FieldError({ message }) {
    return message ? <p className={styles.fieldError}>{message}</p> : null;
}

const inputClass = (error) => `input${error ? " input-error" : ""}`;

// Credenciales que se muestran una sola vez: la inicial del alta (no vence) y la
// temporal de restablecer o reactivar (24 h).
function CredentialsModal({ result, onClose }) {
    const [copied, setCopied] = useState(false);
    const created = result.kind === "created";
    const title = created ? "Integrante creado" : "Contraseña temporal generada";
    const seconds = result.expires_in_seconds;
    const hours = seconds ? Math.round(seconds / 3600) : null;
    const validity = hours != null
        ? `${hours} ${hours === 1 ? "hora" : "horas"} para iniciar sesión`
        : "Hasta su primer ingreso";

    const copy = async () => {
        const lines = [
            `Usuario: ${result.target.username}`,
            ...(result.target.email ? [`Correo: ${result.target.email}`] : []),
            `Contraseña temporal: ${result.temp_password}`,
            `Válida: ${validity}`,
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
            <div className="modal modal-sm" role="dialog" aria-label={title}>
                <div className="modal-header">
                    <h3>{title}</h3>
                </div>
                <div className="modal-body">
                    {created && (
                        <p className={styles.credentialsIntro}>
                            Entrégale estos datos a {fullName(result.target)} para su primer ingreso.
                        </p>
                    )}
                    <div className={styles.tempWarning}>
                        <strong>⚠ Anota o copia ahora.</strong> Esta contraseña no se vuelve a mostrar. Si la pierdes, deberás restablecerla de nuevo.
                    </div>
                    <dl className={styles.credentials}>
                        <dt>Usuario</dt>
                        <dd className={styles.credentialMono}>{result.target.username}</dd>
                        {result.target.email && (
                            <>
                                <dt>Correo</dt>
                                <dd className={styles.credentialMono}>{result.target.email}</dd>
                            </>
                        )}
                        <dt>Contraseña</dt>
                        <dd className={styles.tempPassword}>{result.temp_password}</dd>
                        <dt>Válida</dt>
                        <dd>{validity}</dd>
                    </dl>
                    <p className={styles.tempNote}>
                        Entra con su correo o su usuario. Deberá cambiar esta contraseña al iniciar sesión. Entrégala en persona o por un canal privado.
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

// Elección del rol (alta y cambio de rol), con lo que permite cada uno.
function RolePicker({ value, onChange, name = "create-role" }) {
    return (
        <fieldset className={styles.roleOptions}>
            <legend className="form-label">ROL *</legend>
            {STAFF_ROLE_ORDER.map((role) => (
                <label key={role} className={`${styles.roleOption}${value === role ? ` ${styles.roleOptionSelected}` : ""}`}>
                    <input
                        type="radio"
                        name={name}
                        value={role}
                        checked={value === role}
                        onChange={() => onChange(role)}
                    />
                    <span>
                        <span className={styles.roleName}>{roleLabel(role)}</span>
                        <span className={styles.roleDescription}>{roleSummary(role)}</span>
                    </span>
                </label>
            ))}
        </fieldset>
    );
}

// ADR p66: solo en ADMIN se elige si atiende pacientes (VET siempre, ASSISTANT nunca).
function AttendsField({ id, checked, onChange, disabled = false }) {
    return (
        <label className={styles.attendsField} htmlFor={id}>
            <input
                id={id}
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(e) => onChange(e.target.checked)}
            />
            <span>
                <span className={styles.roleName}>Atiende pacientes</span>
                <span className={styles.roleDescription}>
                    Aparece como veterinario en la agenda y puede recibir citas. Requiere cédula profesional.
                </span>
            </span>
        </label>
    );
}

function impactSentence(impact) {
    if (!impact) return "";
    const parts = [];
    if (impact.upcoming_appointments > 0) {
        parts.push(`${impact.upcoming_appointments} ${impact.upcoming_appointments === 1 ? "cita próxima" : "citas próximas"}`);
    }
    if (impact.open_medical_records > 0) {
        parts.push(`${impact.open_medical_records} ${impact.open_medical_records === 1 ? "consulta abierta" : "consultas abiertas"}`);
    }
    if (parts.length === 0) return "";
    return `Tiene ${parts.join(" y ")} a su nombre: seguirán asignadas; las citas se reasignan desde su ficha.`;
}

// Cambio de rol (ADR p66). Las reglas las aplica el backend (último ADMIN,
// cédula, a sí mismo); aquí se avisa y se bloquea lo que ya se sabe inválido.
function RoleChangeModal({ state, saving, onChange, onSave, onClose }) {
    const { member, role, attends, impact } = state;
    const nextAttends = attendsFor(role, attends);
    const missingLicense = nextAttends && !member.license_number;
    const unchanged = role === member.role && nextAttends === Boolean(member.attends_patients);
    const losesClinic = Boolean(member.attends_patients) && !nextAttends;
    return (
        <div className="modal-overlay">
            <div className="modal modal-md" role="dialog" aria-label={`Cambiar rol de ${fullName(member)}`}>
                <div className="modal-header">
                    <h3>Cambiar rol de {fullName(member)}</h3>
                    <button className="modal-close" onClick={onClose} disabled={saving} aria-label="Cerrar"><Icon.X s={16} /></button>
                </div>
                <div className="modal-body">
                    <RolePicker name="change-role" value={role} onChange={(next) => onChange({ role: next })} />
                    {role === "ADMIN" && (
                        <AttendsField id="change-attends" checked={attends} onChange={(next) => onChange({ attends: next })} />
                    )}
                    {missingLicense && (
                        <p className={styles.notice}>
                            No tiene cédula profesional registrada. Captúrala en Editar antes de darle un rol que atiende pacientes.
                        </p>
                    )}
                    {losesClinic && impactSentence(impact) && (
                        <p className={styles.notice}>{impactSentence(impact)}</p>
                    )}
                    <p className={styles.passwordHint}>
                        El cambio aplica en su siguiente acción; no se cierran sus sesiones.
                    </p>
                </div>
                <div className="modal-footer">
                    <button className={`btn btn-primary btn-md ${styles.footerButton}`} onClick={onSave} disabled={saving || unchanged || missingLicense}>
                        {saving ? "Guardando..." : "Cambiar rol"}
                    </button>
                    <button className={`btn btn-secondary btn-md ${styles.footerButton}`} onClick={onClose} disabled={saving}>
                        Cancelar
                    </button>
                </div>
            </div>
        </div>
    );
}

const Staff = () => {
    const { user, initializing, can, canAny, refreshUser } = useAuth();
    const confirm = useConfirm();
    const navigate = useNavigate();

    // Permisos por capacidad (nunca por rol).
    const canManage = canAny(STAFF_MANAGEMENT_PERMS);
    const canCreate = can("staff.create");
    const canUpdate = can("staff.update");
    const canReset = can("staff.reset_password");
    const canDestroy = can("staff.destroy");
    const canReactivate = can("staff.reactivate");
    const canChangeRole = can("staff.change_role");
    const tz = orgTz(user);

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
    // Credenciales (alta, restablecer o reactivar): se muestran una sola vez.
    const [credentials, setCredentials] = useState(null);
    // Acción de fila en curso: { publicId, kind } | null. Mientras dure, ninguna
    // otra acción de fila se puede lanzar.
    const [pendingAction, setPendingAction] = useState(null);
    // Cambio de rol: { member, role, attends, impact } | null (ADR p66).
    const [roleChange, setRoleChange] = useState(null);

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

    useEffect(() => {
        if (!initializing && user && canManage) {
            // eslint-disable-next-line react-hooks/set-state-in-effect -- carga inicial del equipo desde la API al montar
            fetchStaff();
        }
    }, [initializing, user]);

    // Equipo es una pantalla de gestión: quien no gestiona personal no la abre ni
    // por URL. El backend tampoco le entrega correo, cédula ni datos de acceso.
    if (!initializing && !canManage) {
        return <Navigate to="/" replace />;
    }

    const isSelf = (member) => user?.id != null && member.id === user.id;
    const showingInactive = canReactivate && view === "inactive";
    const rows = showingInactive ? inactive : staff;
    // La ficha la abre cualquiera que gestione personal: toda fila tiene acciones.
    const hasActions = canManage;
    const rowBusy = Boolean(pendingAction);

    const runRowAction = async (member, kind, task) => {
        if (pendingAction) return;
        setPendingAction({ publicId: member.public_id, kind });
        try {
            await task();
        } finally {
            setPendingAction(null);
        }
    };

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
        if (saving) return;
        const errors = createErrors(form);
        setFormErrors(errors);
        if (Object.keys(errors).length > 0) return;

        setSaving(true);
        try {
            const data = await createStaff({
                ...form,
                attends_patients: form.role === "ADMIN" ? form.attends_patients : false,
                username: form.username.trim(),
                first_name: normalizeName(form.first_name),
                last_name: normalizeName(form.last_name),
                email: form.email.trim(),
                license_number: form.license_number.trim(),
            });
            closeModal();
            setCredentials({ ...data, kind: "created", target: data.member });
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
            attends_patients: Boolean(member.attends_patients),
        });
    };

    const editPending = editing ? editChanges(editing) : {};
    const editHasChanges = Object.keys(editPending).length > 0;

    const handleEditSave = async () => {
        if (!editing || !editHasChanges || saving) return;
        const errors = editErrorsFor(editing);
        setEditErrors(errors);
        if (Object.keys(errors).length > 0) return;

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
        if (pendingAction) return;
        const ok = await confirm({
            title: "Restablecer contraseña",
            message: `Se generará una contraseña temporal para ${fullName(member)}. Sus sesiones activas se cerrarán y deberá cambiarla en su próximo acceso. La contraseña se mostrará una sola vez.`,
            confirmText: "Restablecer contraseña",
            dangerMode: true,
        });
        if (!ok) return;
        await runRowAction(member, "reset", async () => {
            try {
                const data = await resetStaffPassword(member.public_id);
                setCredentials({ ...data, kind: "reset", target: member });
                fetchStaff();
            } catch (err) {
                toast.error(apiError(err, "No se pudo restablecer la contraseña."));
            }
        });
    };

    // ADR p66: antes de confirmar se consulta qué tiene pendiente. Una caja
    // abierta bloquea (también en el backend); citas y consultas solo se avisan.
    const handleDeactivate = async (member) => {
        if (pendingAction) return;
        const name = fullName(member);
        await runRowAction(member, "deactivate", async () => {
            let impact = null;
            try {
                impact = await getStaffImpact(member.public_id);
            } catch (err) {
                console.error(apiError(err));
            }
            if (impact?.open_cash_session) {
                const goToCash = await confirm({
                    title: `${name} tiene una caja abierta`,
                    message: "Ciérrala desde Caja (cierre administrativo) antes de desactivar su acceso.",
                    confirmText: "Ir a Caja",
                });
                if (goToCash) navigate("/cash");
                return;
            }
            const base = "Dejará de poder entrar y se cerrarán sus sesiones. Sus citas, consultas y registros se conservan. Podrás reactivarlo desde Inactivos.";
            const ok = await confirm({
                title: `Desactivar acceso de ${name}`,
                message: [impactSentence(impact), base].filter(Boolean).join(" "),
                confirmText: "Desactivar acceso",
                dangerMode: true,
            });
            if (!ok) return;
            try {
                await deactivateStaff(member.public_id);
                // ADR p67: con citas por atender, el siguiente paso es reasignarlas.
                const pendingAppointments = impact?.upcoming_appointments > 0 && can("appointment.update");
                toast.success("Acceso desactivado", pendingAppointments ? {
                    action: { label: "Reasignar citas", onClick: () => navigate(`/staff/${member.public_id}`) },
                } : undefined);
                await fetchStaff();
            } catch (err) {
                toast.error(apiError(err, "No se pudo desactivar el acceso."));
            }
        });
    };

    // ── Cambio de rol e historial (ADR p66) ───────────────────────────────
    const openRoleChange = (member) => {
        setRoleChange({ member, role: member.role, attends: Boolean(member.attends_patients), impact: null });
        if (member.attends_patients) {
            getStaffImpact(member.public_id)
                .then((impact) => setRoleChange((current) => (
                    current?.member.public_id === member.public_id ? { ...current, impact } : current
                )))
                .catch((err) => console.error(apiError(err)));
        }
    };

    const handleRoleSave = async () => {
        if (!roleChange || saving) return;
        const { member, role, attends } = roleChange;
        setSaving(true);
        try {
            await changeStaffRole(member.public_id, {
                role,
                attendsPatients: role === "ADMIN" ? attends : undefined,
            });
            toast.success("Rol actualizado");
            setRoleChange(null);
            fetchStaff();
        } catch (err) {
            toast.error(apiError(err, "No se pudo cambiar el rol."));
        } finally {
            setSaving(false);
        }
    };

    const handleReactivate = async (member) => {
        if (pendingAction) return;
        const role = roleLabel(member.role);
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
        await runRowAction(member, "reactivate", async () => {
            try {
                const data = await reactivateStaff(member.public_id);
                setCredentials({ ...data, kind: "reactivated", target: data.member || member });
            } catch (err) {
                // 409 already_active (p. ej. tras una respuesta perdida): el mensaje
                // del backend indica usar Restablecer contraseña.
                toast.error(apiError(err, "No se pudo reactivar el acceso."));
            } finally {
                await fetchStaff();
            }
        });
    };

    const rowMenuItems = (member) => {
        const self = isSelf(member);
        const items = [];
        if (canChangeRole && !self && !showingInactive) {
            items.push({ id: "role", label: "Cambiar rol", onSelect: () => openRoleChange(member) });
        }
        items.push({ id: "profile", label: "Ver ficha", onSelect: () => navigate(`/staff/${member.public_id}`) });
        if (canReset && !self && !showingInactive) {
            items.push({ id: "reset", label: "Restablecer contraseña", onSelect: () => handleResetPassword(member) });
        }
        if (canDestroy && !self && !showingInactive) {
            items.push({ id: "deactivate", label: "Desactivar acceso", danger: true, onSelect: () => handleDeactivate(member) });
        }
        return items;
    };

    if (loading) {
        return (
            <div>
                <div className="page-header">
                    <div>
                        <h1 className="page-title">Equipo</h1>
                        <Skeleton width={180} height={12} />
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

    const renderProfessional = (member) => {
        const missingLicense = Boolean(member.attends_patients) && !member.license_number;
        return (
            <>
                <div className={member.specialty ? styles.primaryText : styles.secondaryText}>
                    {member.specialty || "—"}
                </div>
                {member.license_number ? (
                    <div className={styles.secondaryText}>
                        Cédula <span className={styles.mono}>{member.license_number}</span>
                    </div>
                ) : missingLicense ? (
                    <div className={styles.attentionText}>Sin cédula: no puede firmar</div>
                ) : null}
            </>
        );
    };

    const renderAccess = (member) => {
        const access = describeAccess(member.access, tz);
        return (
            <>
                <div className={access.attention ? styles.attentionText : styles.primaryText}>{access.label}</div>
                {access.detail && (
                    <div className={styles.secondaryText} title={access.title || undefined}>{access.detail}</div>
                )}
            </>
        );
    };

    const renderActions = (member) => {
        const name = fullName(member);
        const busyHere = pendingAction?.publicId === member.public_id;
        if (showingInactive) {
            return (
                <>
                    {canReactivate && (
                        <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleReactivate(member)}
                            disabled={rowBusy}
                            aria-busy={busyHere || undefined}
                            aria-label={`Reactivar acceso de ${name}`}
                        >
                            {busyHere ? <><Icon.Loader s={14} /> Reactivando…</> : <><Icon.UserCheck s={14} /> Reactivar</>}
                        </button>
                    )}
                    <ActionMenu label={`Más acciones para ${name}`} items={rowMenuItems(member)} disabled={rowBusy} />
                </>
            );
        }
        if (member.demo_protected) return null;
        return (
            <>
                {canUpdate && (
                    <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => openEdit(member)}
                        disabled={rowBusy}
                        aria-label={`Editar a ${name}`}
                    >
                        <Icon.Edit s={14} /> Editar
                    </button>
                )}
                <ActionMenu
                    label={`Más acciones para ${name}`}
                    items={rowMenuItems(member)}
                    disabled={rowBusy}
                    busy={busyHere}
                />
            </>
        );
    };

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Equipo</h1>
                    <p className="page-subtitle">{teamSummary(staff, inactive, canReactivate)}</p>
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
                    <EmptyState
                        icon={Icon.Users}
                        title="Aún no hay integrantes"
                        body="Agrega a tu equipo para que cada persona entre con su propia cuenta y su propio rol."
                        actions={[canCreate ? { label: "Agregar miembro", onClick: openCreate, variant: "primary" } : null]}
                    />
                )
            ) : (
                <div className="table-wrap">
                    <table className={`table ${styles.teamTable}`}>
                        <thead>
                            <tr>
                                <th>Integrante</th>
                                <th>Rol</th>
                                <th>Datos profesionales</th>
                                <th>Acceso</th>
                                {hasActions && <th aria-label="Acciones"></th>}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((member) => (
                                <tr key={member.public_id}>
                                    <td className={styles.memberCell}>
                                        <div className={styles.memberName}>
                                            <Link to={`/staff/${member.public_id}`} className={styles.memberLink}>
                                                {fullName(member)}
                                            </Link>
                                            {isSelf(member) && <span className={`badge badge-default ${styles.selfTag}`}>Tú</span>}
                                        </div>
                                        <div className={styles.secondaryText}>{member.email}</div>
                                    </td>
                                    <td data-label="Rol">
                                        <div className={styles.primaryText}>{roleLabel(member.role)}</div>
                                        <div className={styles.secondaryText}>
                                            {roleShort(member.role)}
                                            {member.role === "ADMIN" && member.attends_patients && " · Atiende pacientes"}
                                        </div>
                                    </td>
                                    <td data-label="Datos profesionales">{renderProfessional(member)}</td>
                                    <td data-label="Acceso">{renderAccess(member)}</td>
                                    {hasActions && (
                                        <td className={styles.actionsCell}>
                                            <div className={styles.actions}>{renderActions(member)}</div>
                                        </td>
                                    )}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {credentials && (
                <CredentialsModal result={credentials} onClose={() => setCredentials(null)} />
            )}

            {roleChange && (
                <RoleChangeModal
                    state={roleChange}
                    saving={saving}
                    onChange={(patch) => setRoleChange((current) => ({ ...current, ...patch }))}
                    onSave={handleRoleSave}
                    onClose={() => setRoleChange(null)}
                />
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
                            <p className={styles.editHeading}>{fullName(editing.member)}</p>
                            <div className={styles.roleReadonly}>
                                <span className={styles.roleName}>{roleLabel(editing.member.role)}</span>
                                <span className={styles.roleDescription}>{roleSummary(editing.member.role)}</span>
                            </div>
                            {editing.member.role === "ADMIN" && (
                                <AttendsField
                                    id="edit-attends"
                                    checked={editing.attends_patients}
                                    onChange={(attends) => setEditing({ ...editing, attends_patients: attends })}
                                />
                            )}
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
                                    CÉDULA PROFESIONAL{attendsFor(editing.member.role, editing.attends_patients) ? " *" : ""}
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

            {/* Modal Nuevo Miembro: la contraseña inicial la genera el sistema */}
            {showModal && (
                <div className="modal-overlay">
                    <div className="modal modal-lg">
                        <div className="modal-header">
                            <h3>Nuevo Miembro</h3>
                            <button className="modal-close" onClick={closeModal} disabled={saving} aria-label="Cerrar"><Icon.X s={16} /></button>
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
                                    <div className={styles.fullRow}>
                                        <RolePicker value={form.role} onChange={(role) => setForm({ ...form, role })} />
                                        <FieldError message={formErrors.role} />
                                        {form.role === "ADMIN" && (
                                            <AttendsField
                                                id="create-attends"
                                                checked={form.attends_patients}
                                                onChange={(attends) => setForm({ ...form, attends_patients: attends })}
                                            />
                                        )}
                                        <FieldError message={formErrors.attends_patients} />
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
                                            CÉDULA PROFESIONAL{attendsFor(form.role, form.attends_patients) ? " *" : ""}
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
                                <p className={styles.passwordHint}>
                                    No necesitas inventar una contraseña: el sistema generará una al guardar y te la mostrará una sola vez. Deberá cambiarla en su primer ingreso.
                                </p>
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
