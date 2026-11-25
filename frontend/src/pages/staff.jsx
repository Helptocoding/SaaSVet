// Equipo (rediseño 2026-11-25, ADR p69): quién está en la clínica, qué puede
// hacer y qué hay que resolver. La ficha de cada persona se abre en un panel
// lateral (`?member=<uuid>`); `/staff/:publicId` redirige ahí.
//
// Jerarquía (design-system §2, D6): el color marca solo lo que pide una acción
// (falta de cédula, invitación vencida); lo normal va neutro. Lo pendiente se
// señala en su celda y en el contador del filtro «Requieren atención», no en un
// bloque aparte que compita con la tabla.
import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import Skeleton from "react-loading-skeleton";
import {
    createStaff, deactivateStaff, getPermissionCatalog, getStaff, getStaffImpact, reactivateStaff,
    resetStaffPassword,
} from "../api/staff";
import { useAuth } from "../auth/authContext";
import ActionMenu from "../components/ActionMenu";
import EmptyState from "../components/EmptyState";
import { Icon } from "../components/icons";
import SegmentedControl from "../components/SegmentedControl";
import TableSkeleton from "../components/TableSkeleton";
import { useConfirm } from "../components/useConfirm";
import AreaAccess from "../features/staff/AreaAccess";
import MemberDrawer from "../features/staff/MemberDrawer";
import { STAFF_MANAGEMENT_PERMS } from "../features/staff/permissions";
import { STAFF_ROLE_ORDER, roleLabel } from "../features/staff/roles";
import SpecialtyPicker from "../features/staff/SpecialtyPicker";
import { specialtiesLabel } from "../features/staff/specialties";
import {
    AttendsField, CredentialsModal, FieldError, MemberAvatar, RolePicker,
} from "../features/staff/StaffParts";
import {
    DEMO_EMAIL_HINT, attendsFor, createErrors, fullName, impactSentence, inputClass, normalizeName, plural,
} from "../features/staff/staffForm";
import {
    ACCOUNT_STATE_LABELS, TABS, accountState, filterMembers, lastAccessShort, memberAlerts, signingState,
    tabCounts,
} from "../features/staff/teamView";
import { apiError } from "../utils/apiError";
import { formatDateTime, orgTz } from "../utils/datetime";
import handleFormError from "../utils/handleFormError";
import styles from "./staff.module.css";

const twoLines = (first, second) => () => (
    <div>
        <Skeleton width={first} height={13} />
        <Skeleton width={second} height={11} />
    </div>
);

const STAFF_SKELETON_COLUMNS = [
    { label: "Integrante", cell: twoLines(140, 170) },
    { label: "Rol", cell: twoLines(90, 120) },
    { label: "Acceso por área", cell: twoLines(140, 80) },
    { label: "Firma de recetas", cell: twoLines(80, 0) },
    { label: "Estado", cell: twoLines(70, 0) },
    { label: "Último acceso", cell: twoLines(60, 0) },
    { label: "", width: 72 },
];

const EMPTY_FORM = {
    username: "",
    first_name: "",
    last_name: "",
    email: "",
    role: "VET",
    attends_patients: false,
    specialties: [],
    license_number: "",
};

// D6: «Activo» es lo normal y va como texto neutro; solo la invitación vencida
// pide una acción y lleva color.
const STATE_BADGE = {
    pending: "badge-default",
    expired: "badge-warning",
    inactive: "badge-default",
};

/** `/staff/:publicId` (ADR p67) ahora es la ficha lateral sobre Equipo. */
export function StaffMemberRedirect() {
    const { publicId } = useParams();
    return <Navigate to={`/staff?member=${encodeURIComponent(publicId)}`} replace />;
}

// Los conteos por estado ya están en el filtro: aquí solo el tamaño del equipo.
const teamSummary = (team) => plural(team.length, "integrante", "integrantes");

// El que pide atención lleva su contador en aviso; los demás, neutros.
const segmentTone = (tab) => (tab === "attention" ? "attention" : undefined);

const Staff = () => {
    const { user, initializing, can, canAny } = useAuth();
    const confirm = useConfirm();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();

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
    const [catalog, setCatalog] = useState(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);
    const [tab, setTab] = useState("all");
    const [query, setQuery] = useState("");
    const [roleFilter, setRoleFilter] = useState("");
    const [saving, setSaving] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [formErrors, setFormErrors] = useState({});
    // Credenciales (alta, restablecer o reactivar): se muestran una sola vez.
    const [credentials, setCredentials] = useState(null);
    // Acción de fila en curso: { publicId, kind } | null. Mientras dure, ninguna
    // otra acción de fila se puede lanzar.
    const [pendingAction, setPendingAction] = useState(null);

    const memberParam = searchParams.get("member");
    const sectionParam = searchParams.get("section");

    // Con `staff.reactivate`, activos e inactivos se cargan en paralelo. El
    // catálogo de permisos se pide una vez; sin él la tabla sigue (sin áreas).
    async function fetchStaff() {
        try {
            const [active, archived, permissionCatalog] = await Promise.all([
                getStaff(),
                canReactivate ? getStaff({ archived: "true" }) : Promise.resolve([]),
                catalog ? Promise.resolve(catalog) : getPermissionCatalog().catch((err) => {
                    console.error(apiError(err));
                    return null;
                }),
            ]);
            setStaff(active);
            setInactive(archived);
            setCatalog(permissionCatalog);
            setLoadError(null);
        } catch (err) {
            setLoadError(apiError(err, "No se pudo cargar el equipo."));
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
    const rowBusy = Boolean(pendingAction);
    const tabs = TABS.filter((item) => item.id !== "inactive" || canReactivate);
    const everyone = [...staff, ...inactive];
    const counts = tabCounts(everyone, catalog);
    const rows = filterMembers(everyone, { tab, query, role: roleFilter }, catalog);
    const filtering = Boolean(query.trim() || roleFilter);

    const openMember = (member, section = null) => {
        const next = new URLSearchParams(searchParams);
        next.set("member", member.public_id);
        if (section) next.set("section", section);
        else next.delete("section");
        setSearchParams(next);
    };

    const closeMember = () => {
        const next = new URLSearchParams(searchParams);
        next.delete("member");
        next.delete("section");
        setSearchParams(next);
    };

    const runRowAction = async (member, kind, task) => {
        if (pendingAction) return false;
        setPendingAction({ publicId: member.public_id, kind });
        try {
            return await task();
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
                // ADR p68: solo quien atiende tiene especialidades.
                specialties: attendsFor(form.role, form.attends_patients) ? form.specialties : [],
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

    // ── Restablecer (o reenviar invitación), desactivar, reactivar ────────
    // Devuelven true si la acción se completó (la ficha recarga entonces).
    const handleResetPassword = async (member) => {
        if (pendingAction) return false;
        const invite = ["pending", "expired"].includes(accountState(member));
        const ok = await confirm({
            title: invite ? "Reenviar invitación" : "Restablecer contraseña",
            message: invite
                ? `Se generará una contraseña temporal nueva para ${fullName(member)}, válida 24 h. La anterior deja de servir y la nueva se mostrará una sola vez.`
                : `Se generará una contraseña temporal para ${fullName(member)}. Sus sesiones activas se cerrarán y deberá cambiarla en su próximo acceso. La contraseña se mostrará una sola vez.`,
            confirmText: invite ? "Reenviar invitación" : "Restablecer contraseña",
            dangerMode: !invite,
        });
        if (!ok) return false;
        return runRowAction(member, "reset", async () => {
            try {
                const data = await resetStaffPassword(member.public_id);
                setCredentials({ ...data, kind: "reset", target: member });
                fetchStaff();
                return true;
            } catch (err) {
                toast.error(apiError(err, "No se pudo restablecer la contraseña."));
                return false;
            }
        });
    };

    // ADR p66: antes de confirmar se consulta qué tiene pendiente. Una caja
    // abierta bloquea (también en el backend); citas y consultas solo se avisan.
    const handleDeactivate = async (member) => {
        if (pendingAction) return false;
        const name = fullName(member);
        return runRowAction(member, "deactivate", async () => {
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
                return false;
            }
            const base = "Dejará de poder entrar y se cerrarán sus sesiones. Sus citas, consultas y registros se conservan. Podrás reactivarlo desde Desactivados.";
            const ok = await confirm({
                title: `Desactivar acceso de ${name}`,
                message: [impactSentence(impact), base].filter(Boolean).join(" "),
                confirmText: "Desactivar acceso",
                dangerMode: true,
            });
            if (!ok) return false;
            try {
                await deactivateStaff(member.public_id);
                // ADR p67: con citas por atender, el siguiente paso es reasignarlas.
                const pendingAppointments = impact?.upcoming_appointments > 0 && can("appointment.update");
                toast.success("Acceso desactivado", pendingAppointments ? {
                    action: { label: "Reasignar citas", onClick: () => openMember(member) },
                } : undefined);
                await fetchStaff();
                return true;
            } catch (err) {
                toast.error(apiError(err, "No se pudo desactivar el acceso."));
                return false;
            }
        });
    };

    const handleReactivate = async (member) => {
        if (pendingAction) return false;
        let message = `Conservará su rol (${roleLabel(member.role)}), sus permisos y su historial. Se generará una contraseña temporal válida por 24 h que deberá cambiar al entrar.`;
        if (member.attends_patients && !member.license_number) {
            message += " No tiene cédula profesional registrada: no podrá firmar consultas ni recetas hasta que la captures.";
        }
        const ok = await confirm({
            title: `Reactivar acceso de ${fullName(member)}`,
            message,
            confirmText: "Reactivar acceso",
        });
        if (!ok) return false;
        return runRowAction(member, "reactivate", async () => {
            try {
                const data = await reactivateStaff(member.public_id);
                setCredentials({ ...data, kind: "reactivated", target: data.member || member });
                return true;
            } catch (err) {
                // 409 already_active (p. ej. tras una respuesta perdida): el mensaje
                // del backend indica usar Restablecer contraseña.
                toast.error(apiError(err, "No se pudo reactivar el acceso."));
                return false;
            } finally {
                await fetchStaff();
            }
        });
    };

    // Lo que resuelve un pendiente va primero; después, lo de siempre.
    const rowMenuItems = (member) => {
        const self = isSelf(member);
        const state = accountState(member);
        const profile = { id: "profile", label: "Ver ficha", onSelect: () => openMember(member) };
        if (state === "inactive" || member.demo_protected) return [profile];
        const missingLicense = memberAlerts(member, catalog).some((alert) => alert.kind === "missing_license");
        const items = [];
        if (missingLicense && canUpdate) {
            items.push({ id: "license", label: "Completar cédula", onSelect: () => openMember(member, "license") });
        }
        const invite = state === "pending" || state === "expired";
        const reset = canReset && !self ? {
            id: "reset",
            label: invite ? "Reenviar invitación" : "Restablecer contraseña",
            onSelect: () => handleResetPassword(member),
        } : null;
        if (reset && state === "expired") items.push(reset);
        items.push(profile);
        if (canChangeRole && !self) {
            items.push({ id: "role", label: "Cambiar rol", onSelect: () => openMember(member, "role") });
        }
        if (reset && state !== "expired") items.push(reset);
        if (canDestroy && !self) {
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
                        <Skeleton width={220} height={12} />
                    </div>
                </div>
                <div role="status" aria-label="Cargando equipo">
                    <TableSkeleton rows={5} columns={STAFF_SKELETON_COLUMNS} />
                </div>
            </div>
        );
    }

    // Una línea por dato; la segunda solo si dice algo que la primera no.
    const renderRole = (member) => {
        const detail = [
            member.specialties?.length > 0 ? specialtiesLabel(member.specialties) : null,
            member.role === "ADMIN" && member.attends_patients ? "Atiende pacientes" : null,
        ].filter(Boolean).join(" · ");
        return (
            <>
                <div className={styles.primaryText}>{roleLabel(member.role)}</div>
                {detail && <div className={styles.secondaryText}>{detail}</div>}
            </>
        );
    };

    const renderSigning = (member) => {
        const signing = signingState(member, catalog);
        if (signing === "enabled") {
            return <span className={styles.neutralText}><Icon.Check s={14} /> Habilitada</span>;
        }
        if (signing === "not_applicable") {
            return (
                <span className={styles.mutedText} title="No aplica">
                    <span aria-hidden="true">—</span><span className="sr-only">No aplica</span>
                </span>
            );
        }
        // Falta cédula: lo único de la columna que pide una acción, y la lleva a ella.
        if (!canUpdate || member.demo_protected || accountState(member) === "inactive") {
            return <span className={styles.attentionText}><Icon.AlertTriangle s={14} /> Falta cédula</span>;
        }
        return (
            <button
                type="button"
                className={styles.attentionLink}
                onClick={(event) => { event.stopPropagation(); openMember(member, "license"); }}
                aria-label={`Falta cédula: completar la de ${fullName(member)}`}
            >
                <Icon.AlertTriangle s={14} /> Falta cédula
            </button>
        );
    };

    const renderState = (member) => {
        const state = accountState(member);
        if (state === "active") return <span className={styles.mutedText}>{ACCOUNT_STATE_LABELS.active}</span>;
        return <span className={`badge ${STATE_BADGE[state]}`}>{ACCOUNT_STATE_LABELS[state]}</span>;
    };

    const renderActions = (member) => {
        const name = fullName(member);
        const busyHere = pendingAction?.publicId === member.public_id;
        const inactiveRow = accountState(member) === "inactive";
        return (
            <>
                {inactiveRow && canReactivate && (
                    <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleReactivate(member)}
                        disabled={rowBusy}
                        aria-busy={busyHere || undefined}
                        aria-label={`Reactivar acceso de ${name}`}
                    >
                        {busyHere ? <><Icon.Loader s={14} /> Reactivando…</> : <><Icon.UserCheck s={14} /> Reactivar</>}
                    </button>
                )}
                <ActionMenu
                    label={`Más acciones para ${name}`}
                    items={rowMenuItems(member)}
                    disabled={rowBusy}
                    busy={busyHere && !inactiveRow}
                />
            </>
        );
    };

    const emptyTabBody = {
        all: "Agrega a tu equipo: cada persona entra con su propia cuenta.",
        active: "Aparece aquí quien ya entró por primera vez.",
        pending: "Nadie tiene una invitación por usar.",
        attention: "Nada por resolver.",
        inactive: "Aquí aparece quien desactives.",
    };

    // Clic en la fila abre la ficha (design-system §5, tabla); lo interactivo de
    // dentro detiene la propagación para no abrirla dos veces.
    const stop = (event) => event.stopPropagation();

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Equipo</h1>
                    <p className="page-subtitle">{teamSummary(staff)}</p>
                </div>
                {canCreate && (
                    <button type="button" className="btn btn-primary btn-md" onClick={openCreate}>
                        <Icon.Plus s={14} /> Agregar miembro
                    </button>
                )}
            </div>

            {loadError && (
                <EmptyState
                    icon={Icon.AlertTriangle}
                    title="No se pudo cargar el equipo"
                    body={loadError}
                    actions={[{ label: "Reintentar", onClick: fetchStaff, variant: "secondary" }]}
                />
            )}

            {/* Una sola línea: qué grupo ver (filtro excluyente) y, a la derecha, cómo acotarlo. */}
            <div className={styles.toolbar}>
                <SegmentedControl
                    ariaLabel="Mostrar integrantes"
                    value={tab}
                    onChange={setTab}
                    options={tabs.map((item) => ({
                        id: item.id,
                        label: item.label,
                        count: counts[item.id] ?? 0,
                        tone: segmentTone(item.id),
                    }))}
                />
                <div className={styles.filters}>
                    <div className={`searchBar ${styles.search}`}>
                        <span className="search-icon" aria-hidden="true"><Icon.Search s={15} /></span>
                        <input
                            type="search"
                            aria-label="Buscar por nombre o correo"
                            placeholder="Buscar…"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                        />
                        {query && (
                            <button type="button" className="search-clear" aria-label="Limpiar búsqueda" onClick={() => setQuery("")}>
                                <Icon.X s={14} />
                            </button>
                        )}
                    </div>
                    <select
                        className={`select-input ${styles.roleSelect}`}
                        aria-label="Filtrar por rol"
                        value={roleFilter}
                        onChange={(event) => setRoleFilter(event.target.value)}
                    >
                        <option value="">Todos los roles</option>
                        {STAFF_ROLE_ORDER.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}
                    </select>
                </div>
            </div>

            <div>
                {rows.length === 0 ? (
                    filtering ? (
                        <EmptyState
                            icon={Icon.Search}
                            title="Sin coincidencias"
                            body="Prueba con otro nombre o correo, o quita el filtro de rol."
                            actions={[{ label: "Limpiar filtros", onClick: () => { setQuery(""); setRoleFilter(""); }, variant: "secondary" }]}
                        />
                    ) : (
                        <EmptyState
                            icon={Icon.Users}
                            title={tab === "all" ? "Aún no hay integrantes" : `Sin integrantes en «${TABS.find((t) => t.id === tab)?.label}»`}
                            body={emptyTabBody[tab]}
                            actions={[tab === "all" && canCreate ? { label: "Agregar miembro", onClick: openCreate, variant: "primary" } : null]}
                        />
                    )
                ) : (
                    <div className="table-wrap">
                        <table className={`table ${styles.teamTable}`}>
                            <thead>
                                <tr>
                                    <th>Integrante</th>
                                    <th>Rol</th>
                                    <th>Acceso por área</th>
                                    <th>Firma de recetas</th>
                                    <th>Estado</th>
                                    <th>Último acceso</th>
                                    <th aria-label="Acciones"></th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows.map((member) => (
                                    <tr
                                        key={member.public_id}
                                        className="table-row-clickable"
                                        onClick={() => openMember(member)}
                                    >
                                        <td className={styles.memberCell}>
                                            <div className={styles.member}>
                                                <MemberAvatar member={member} />
                                                <div className={styles.memberText}>
                                                    <div className={styles.memberName}>
                                                        {/* Vía de teclado a la ficha; con el ratón basta la fila. */}
                                                        <button
                                                            type="button"
                                                            className={styles.memberLink}
                                                            onClick={(event) => { stop(event); openMember(member); }}
                                                        >
                                                            {fullName(member)}
                                                        </button>
                                                        {isSelf(member) && <span className="badge badge-default">Tú</span>}
                                                    </div>
                                                    <div className={styles.secondaryText}>{member.email}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td data-label="Rol">{renderRole(member)}</td>
                                        <td data-label="Acceso por área" onClick={stop}>
                                            <AreaAccess member={member} catalog={catalog} />
                                        </td>
                                        <td data-label="Firma de recetas">{renderSigning(member)}</td>
                                        <td data-label="Estado">{renderState(member)}</td>
                                        <td data-label="Último acceso">
                                            <span
                                                className={styles.mutedText}
                                                title={member.access?.last_login ? formatDateTime(member.access.last_login, tz, "es-MX") : undefined}
                                            >
                                                {lastAccessShort(member, { isSelf: isSelf(member) })}
                                            </span>
                                        </td>
                                        <td className={styles.actionsCell} onClick={stop}>
                                            <div className={styles.actions}>{renderActions(member)}</div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {memberParam && (
                <MemberDrawer
                    key={memberParam}
                    publicId={memberParam}
                    catalog={catalog}
                    team={staff}
                    focusSection={sectionParam}
                    busy={rowBusy}
                    onClose={closeMember}
                    onSaved={fetchStaff}
                    onResetPassword={handleResetPassword}
                    onDeactivate={handleDeactivate}
                    onReactivate={handleReactivate}
                />
            )}

            {credentials && (
                <CredentialsModal result={credentials} onClose={() => setCredentials(null)} />
            )}

            {/* Alta: la contraseña inicial la genera el sistema */}
            {showModal && (
                <div className="modal-overlay">
                    <div className="modal modal-lg" role="dialog" aria-modal="true" aria-label="Nuevo miembro">
                        <div className="modal-header">
                            <h3>Nuevo miembro</h3>
                            <button type="button" className="modal-close" onClick={closeModal} disabled={saving} aria-label="Cerrar"><Icon.X s={16} /></button>
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
                                    {attendsFor(form.role, form.attends_patients) && (
                                        <div className="form-group">
                                            <SpecialtyPicker
                                                idPrefix="create-specialty"
                                                value={form.specialties}
                                                onChange={(next) => setForm({ ...form, specialties: next })}
                                                error={formErrors.specialties}
                                            />
                                        </div>
                                    )}
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
                                    No necesitas inventar una contraseña: el sistema generará una al guardar y te la mostrará una sola vez. Deberá cambiarla en su primer ingreso. Sus permisos serán los de su rol; puedes ajustarlos después en su ficha.
                                </p>
                            </form>
                        </div>
                        <div className="modal-footer">
                            <button type="button" className={`btn btn-primary btn-md ${styles.footerButton}`} onClick={handleSubmit} disabled={saving}>
                                {saving ? "Guardando..." : "Guardar"}
                            </button>
                            <button type="button" className={`btn btn-secondary btn-md ${styles.footerButton}`} onClick={closeModal} disabled={saving}>
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
