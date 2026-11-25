// Equipo (rediseño 2026-11-25, ADR p69): quién está en la clínica, qué puede
// hacer y qué hay que resolver. La ficha de cada persona se abre en un panel
// lateral (`?member=<uuid>`); `/staff/:publicId` redirige ahí.
import { useEffect, useRef, useState } from "react";
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
import TableSkeleton from "../components/TableSkeleton";
import { useConfirm } from "../components/useConfirm";
import AreaAccess from "../features/staff/AreaAccess";
import MemberDrawer from "../features/staff/MemberDrawer";
import { STAFF_MANAGEMENT_PERMS } from "../features/staff/permissions";
import { STAFF_ROLE_ORDER, roleLabel, roleShort } from "../features/staff/roles";
import SpecialtyPicker from "../features/staff/SpecialtyPicker";
import { specialtiesLabel } from "../features/staff/specialties";
import {
    AttendsField, CredentialsModal, FieldError, MemberAvatar, RolePicker,
} from "../features/staff/StaffParts";
import {
    DEMO_EMAIL_HINT, attendsFor, createErrors, fullName, impactSentence, inputClass, normalizeName, plural,
} from "../features/staff/staffForm";
import {
    ACCOUNT_STATE_LABELS, SIGNING_LABELS, TABS, accountState, attentionItems, filterMembers,
    lastAccessShort, signingState, tabCounts,
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

const STATE_BADGE = {
    active: "badge-success",
    pending: "badge-warning",
    expired: "badge-danger",
    inactive: "badge-default",
};

/** `/staff/:publicId` (ADR p67) ahora es la ficha lateral sobre Equipo. */
export function StaffMemberRedirect() {
    const { publicId } = useParams();
    return <Navigate to={`/staff?member=${encodeURIComponent(publicId)}`} replace />;
}

function teamSummary(team, inactive, showInactive) {
    const parts = [plural(team.length, "integrante", "integrantes")];
    const active = team.filter((m) => accountState(m) === "active").length;
    const pending = team.length - active;
    parts.push(plural(active, "activo", "activos"));
    if (pending > 0) parts.push(plural(pending, "invitación pendiente", "invitaciones pendientes"));
    if (showInactive && inactive.length > 0) parts.push(plural(inactive.length, "desactivado", "desactivados"));
    return parts.join(" · ");
}

function TeamTabs({ tabs, value, counts, onChange, controls }) {
    const refs = useRef({});
    const onKeyDown = (event, index) => {
        const keys = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 };
        if (!(event.key in keys)) return;
        event.preventDefault();
        const next = tabs[(keys[event.key] + tabs.length) % tabs.length];
        onChange(next.id);
        refs.current[next.id]?.focus();
    };
    return (
        <div className={styles.tabs} role="tablist" aria-label="Integrantes">
            {tabs.map((tab, index) => (
                <button
                    key={tab.id}
                    ref={(node) => { refs.current[tab.id] = node; }}
                    type="button"
                    role="tab"
                    id={`staff-tab-${tab.id}`}
                    aria-selected={value === tab.id}
                    aria-controls={controls}
                    tabIndex={value === tab.id ? 0 : -1}
                    className={styles.tab}
                    onClick={() => onChange(tab.id)}
                    onKeyDown={(event) => onKeyDown(event, index)}
                >
                    {tab.label}{" "}
                    <span className={styles.tabCount}>{counts[tab.id] ?? 0}</span>
                </button>
            ))}
        </div>
    );
}

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
    const attention = attentionItems(staff, catalog);
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

    const rowMenuItems = (member) => {
        const self = isSelf(member);
        const state = accountState(member);
        if (state === "inactive") {
            return [{ id: "profile", label: "Ver ficha", onSelect: () => openMember(member) }];
        }
        const items = [{ id: "profile", label: "Ver ficha", onSelect: () => openMember(member) }];
        if (member.demo_protected) return items;
        if (canChangeRole && !self) {
            items.push({ id: "role", label: "Cambiar rol", onSelect: () => openMember(member, "role") });
        }
        if (canReset && !self) {
            const invite = state === "pending" || state === "expired";
            items.push({
                id: "reset",
                label: invite ? "Reenviar invitación" : "Restablecer contraseña",
                onSelect: () => handleResetPassword(member),
            });
        }
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

    const renderRole = (member) => (
        <>
            <div className={styles.primaryText}>{roleLabel(member.role)}</div>
            <div className={styles.secondaryText}>
                {member.specialties?.length > 0 ? specialtiesLabel(member.specialties) : roleShort(member.role)}
                {member.role === "ADMIN" && member.attends_patients && " · Atiende pacientes"}
            </div>
        </>
    );

    const renderSigning = (member) => {
        const signing = signingState(member, catalog);
        return (
            <>
                <div className={signing === "missing_license" ? styles.attentionText : signing === "enabled" ? styles.primaryText : styles.secondaryText}>
                    {SIGNING_LABELS[signing]}
                </div>
                {signing === "enabled" && (
                    <div className={styles.secondaryText}>
                        Cédula <span className={styles.mono}>{member.license_number}</span>
                    </div>
                )}
            </>
        );
    };

    const renderActions = (member) => {
        const name = fullName(member);
        const busyHere = pendingAction?.publicId === member.public_id;
        const inactiveRow = accountState(member) === "inactive";
        return (
            <>
                {inactiveRow ? (
                    canReactivate && (
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
                    )
                ) : (
                    canUpdate && !member.demo_protected && (
                        <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => openMember(member)}
                            disabled={rowBusy}
                            aria-label={`Editar a ${name}`}
                        >
                            <Icon.Edit s={14} /> Editar
                        </button>
                    )
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

    const attentionAction = (item) => {
        if (item.kind === "missing_license") {
            if (!canUpdate) return null;
            return item.members.length === 1 ? (
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => openMember(item.members[0], "license")}>
                    Completar cédula
                </button>
            ) : (
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setTab("attention")}>
                    Revisar
                </button>
            );
        }
        if (!canReset) return null;
        return (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => handleResetPassword(item.members[0])} disabled={rowBusy}>
                Reenviar invitación
            </button>
        );
    };

    const emptyTabBody = {
        all: "Agrega a tu equipo para que cada persona entre con su propia cuenta y su propio rol.",
        active: "Aquí aparece quien ya entró y completó su acceso.",
        pending: "Nadie tiene una invitación por usar.",
        attention: "Nada por resolver: todos pueden firmar lo que su rol permite y no hay invitaciones vencidas.",
        inactive: "Quien desactives aparecerá aquí y podrás reactivar su acceso.",
    };

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Equipo</h1>
                    <p className="page-subtitle">{teamSummary(staff, inactive, canReactivate)}</p>
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

            {attention.length > 0 && (
                <section className={styles.attention} aria-labelledby="staff-attention-title">
                    <h2 id="staff-attention-title" className={styles.attentionTitle}>
                        <Icon.AlertTriangle s={16} /> Requiere atención
                    </h2>
                    <ul className={styles.attentionList}>
                        {attention.map((item) => (
                            <li key={item.key} className={styles.attentionItem}>
                                <span>{item.text}</span>
                                {attentionAction(item)}
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            <TeamTabs tabs={tabs} value={tab} counts={counts} onChange={setTab} controls="staff-panel" />

            <div className={styles.toolbar}>
                <div className={styles.search}>
                    <Icon.Search s={16} />
                    <input
                        type="search"
                        className="input"
                        aria-label="Buscar por nombre o correo"
                        placeholder="Buscar por nombre o correo"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                    />
                </div>
                <select
                    className="select-input"
                    aria-label="Filtrar por rol"
                    value={roleFilter}
                    onChange={(event) => setRoleFilter(event.target.value)}
                >
                    <option value="">Todos los roles</option>
                    {STAFF_ROLE_ORDER.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}
                </select>
            </div>

            <div id="staff-panel" role="tabpanel" aria-labelledby={`staff-tab-${tab}`}>
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
                                {rows.map((member) => {
                                    const state = accountState(member);
                                    return (
                                        <tr key={member.public_id}>
                                            <td className={styles.memberCell}>
                                                <div className={styles.member}>
                                                    <MemberAvatar member={member} />
                                                    <div className={styles.memberText}>
                                                        <div className={styles.memberName}>
                                                            <button type="button" className={styles.memberLink} onClick={() => openMember(member)}>
                                                                {fullName(member)}
                                                            </button>
                                                            {isSelf(member) && <span className="badge badge-default">Tú</span>}
                                                        </div>
                                                        <div className={styles.secondaryText}>{member.email}</div>
                                                    </div>
                                                </div>
                                            </td>
                                            <td data-label="Rol">{renderRole(member)}</td>
                                            <td data-label="Acceso por área"><AreaAccess member={member} catalog={catalog} /></td>
                                            <td data-label="Firma de recetas">{renderSigning(member)}</td>
                                            <td data-label="Estado">
                                                <span className={`badge ${STATE_BADGE[state]}`}>{ACCOUNT_STATE_LABELS[state]}</span>
                                            </td>
                                            <td data-label="Último acceso">
                                                <span title={member.access?.last_login ? formatDateTime(member.access.last_login, tz, "es-MX") : undefined}>
                                                    {lastAccessShort(member, { isSelf: isSelf(member) })}
                                                </span>
                                            </td>
                                            <td className={styles.actionsCell}>
                                                <div className={styles.actions}>{renderActions(member)}</div>
                                            </td>
                                        </tr>
                                    );
                                })}
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
