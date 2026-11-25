// Ficha del integrante en un panel lateral sobre Equipo (rediseño 2026-11-25,
// ADR p67/p69). Sustituye a la página `/staff/:publicId`.
//
// Un solo «Guardar cambios» envía datos, rol y permisos en un PATCH; el backend
// lo aplica en una transacción (`update_staff_member`). Restablecer, desactivar y
// reactivar son acciones inmediatas con su propia confirmación: las ejecuta la
// página, que muestra las credenciales de un solo uso.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";
import Skeleton from "react-loading-skeleton";
import {
    getAbsences, getStaffAppointments, getStaffHistory, getStaffImpact, getStaffProfile, updateStaff,
} from "../../api/staff";
import { useAuth } from "../../auth/authContext";
import { Icon } from "../../components/icons";
import { useConfirm } from "../../components/useConfirm";
import { apiError } from "../../utils/apiError";
import { formatDateTime, orgTz } from "../../utils/datetime";
import handleFormError from "../../utils/handleFormError";
import { describeAccess } from "./access";
import { formatLocalDate, orgTodayIso } from "./absences";
import { describeEvent } from "./history";
import MemberAbsences from "./MemberAbsences";
import PermissionEditor from "./PermissionEditor";
import {
    draftFromMember, hasOverrides, overridesChanged, permissionsPayload, restoreRoleDefaults, toggleCode,
} from "./permissionDraft";
import ReassignModal from "./ReassignModal";
import { roleLabel } from "./roles";
import SpecialtyPicker from "./SpecialtyPicker";
import { specialtiesLabel } from "./specialties";
import { AttendsField, FieldError, MemberAvatar, RolePicker } from "./StaffParts";
import {
    DEMO_EMAIL_HINT, EMAIL_CHANGE_NOTICE, attendsFor, fullName, impactSentence, inputClass,
    plural, profileChanges, profileErrors,
} from "./staffForm";
import { ACCOUNT_STATE_LABELS, accountState, lastAccessShort, memberAlerts } from "./teamView";
import styles from "./MemberDrawer.module.css";

const EMPTY_OVERRIDES = { granted: new Set(), revoked: new Set() };

const profileDraftFrom = (member) => ({
    first_name: member.first_name || "",
    last_name: member.last_name || "",
    email: member.email || "",
    license_number: member.license_number || "",
    specialties: member.specialties || [],
    role: member.role,
    attends_patients: Boolean(member.attends_patients),
});

function Section({ id, title, description, action, children }) {
    return (
        <section className={styles.section} aria-labelledby={id}>
            <div className={styles.sectionHeader}>
                <div>
                    <h3 id={id} className={styles.sectionTitle}>{title}</h3>
                    {description && <p className={styles.sectionDescription}>{description}</p>}
                </div>
                {action}
            </div>
            {children}
        </section>
    );
}

export default function MemberDrawer({
    publicId, catalog, team, focusSection = null, busy = false,
    onClose, onSaved, onResetPassword, onDeactivate, onReactivate,
}) {
    const { user, can, refreshUser } = useAuth();
    const confirm = useConfirm();
    const titleId = useId();
    const headingRef = useRef(null);
    const licenseRef = useRef(null);
    const roleRef = useRef(null);
    const returnFocusRef = useRef(typeof document !== "undefined" ? document.activeElement : null);
    const tz = orgTz(user);

    const canUpdate = can("staff.update");
    const canChangeRole = can("staff.change_role");
    const canManagePermissions = can("staff.manage_permissions");
    const canAbsences = can("staff.manage_absences");
    const canReassign = can("appointment.update");

    const [data, setData] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [draft, setDraft] = useState(null);
    const [overrides, setOverrides] = useState(EMPTY_OVERRIDES);
    const [permsTouched, setPermsTouched] = useState(false);
    const [keepCustom, setKeepCustom] = useState(null);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [reassign, setReassign] = useState(null);

    const resetDraft = (member) => {
        setDraft(profileDraftFrom(member));
        setOverrides(draftFromMember(member));
        setPermsTouched(false);
        setKeepCustom(null);
        setErrors({});
    };

    const load = useCallback(async ({ reset = false } = {}) => {
        try {
            const [member, impact, appointments, absences, history] = await Promise.all([
                getStaffProfile(publicId),
                getStaffImpact(publicId),
                getStaffAppointments(publicId),
                getAbsences({ member: publicId }),
                getStaffHistory(publicId),
            ]);
            setData({ member, impact, appointments, absences, history });
            setLoadError(null);
            if (reset) resetDraft(member);
            return member;
        } catch (err) {
            setLoadError(err?.response?.status === 404
                ? "No encontramos a este integrante en tu clínica."
                : apiError(err, "No se pudo cargar la ficha."));
            return null;
        }
    }, [publicId]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- carga de la ficha desde la API al abrirla o cambiar de integrante
        load({ reset: true });
    }, [load]);

    // Foco: al título al abrir (o a la sección pedida) y de vuelta a quien la abrió al cerrar.
    useEffect(() => {
        if (!data) return;
        const target = focusSection === "role" ? roleRef.current
            : focusSection === "license" ? licenseRef.current : headingRef.current;
        (target || headingRef.current)?.focus();
        // Solo la primera vez que hay datos.
        // eslint-disable-next-line react-hooks/exhaustive-deps -- enfocar una sola vez al cargar, no en cada recarga
    }, [Boolean(data)]);

    useEffect(() => () => returnFocusRef.current?.focus?.(), []);

    const member = data?.member;
    const original = member ? draftFromMember(member) : EMPTY_OVERRIDES;
    const roleChanged = Boolean(member && draft && draft.role !== member.role);
    const decisionShown = roleChanged && hasOverrides(original) && !permsTouched;
    const viewDraft = draft ? {
        role: draft.role,
        ...(decisionShown && keepCustom === false ? EMPTY_OVERRIDES : overrides),
    } : null;

    const changes = member && draft ? profileChanges(draft, member) : {};
    const attendsChanged = Boolean(member && draft && !roleChanged && member.role === "ADMIN"
        && draft.attends_patients !== Boolean(member.attends_patients));
    const permissionsChanged = Boolean(catalog && viewDraft && permsTouched
        && (overridesChanged(viewDraft, original) || roleChanged));
    const dirty = Object.keys(changes).length > 0 || roleChanged || attendsChanged || permissionsChanged;

    const requestClose = useCallback(async () => {
        if (saving) return;
        if (dirty) {
            const ok = await confirm({
                title: "¿Descartar los cambios?",
                message: "Hay cambios sin guardar en la ficha.",
                confirmText: "Descartar cambios",
                dangerMode: true,
            });
            if (!ok) return;
        }
        onClose();
    }, [saving, dirty, confirm, onClose]);

    useEffect(() => {
        const onKey = (event) => {
            if (event.key !== "Escape" || event.defaultPrevented) return;
            // Un diálogo encima (confirmación, reasignar) se cierra primero.
            if (reassign || document.querySelector("[data-confirm-dialog], .modal-overlay .modal")) return;
            event.preventDefault();
            requestClose();
        };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [requestClose, reassign]);

    if (loadError) {
        return (
            <DrawerShell titleId={titleId} onClose={onClose} title="Ficha no disponible">
                <div className={styles.body}>
                    <p className={styles.muted}>{loadError}</p>
                    <button type="button" className="btn btn-secondary btn-md" onClick={() => load({ reset: true })}>
                        Reintentar
                    </button>
                </div>
            </DrawerShell>
        );
    }

    if (!data || !draft) {
        return (
            <DrawerShell titleId={titleId} onClose={onClose} title="Cargando ficha">
                <div className={styles.body} role="status" aria-label="Cargando ficha">
                    <Skeleton width={220} height={20} />
                    <Skeleton width={160} height={12} />
                    <Skeleton count={6} height={14} />
                </div>
            </DrawerShell>
        );
    }

    const { impact, appointments, absences, history } = data;
    const isSelf = user?.id != null && member.id === user.id;
    const active = member.is_active;
    const state = accountState(member);
    const editable = active && !member.demo_protected;
    const access = describeAccess(member.access, tz);
    const alerts = memberAlerts(member, catalog);
    const nextAttends = attendsFor(draft.role, draft.attends_patients);
    const activeAdmins = (team || []).filter((m) => m.role === "ADMIN" && m.is_active !== false).length;
    const lastAdmin = member.role === "ADMIN" && activeAdmins <= 1;
    const roleLock = !canChangeRole ? "Tu rol no permite cambiar roles."
        : isSelf ? "No puedes cambiar tu propio rol."
        : lastAdmin ? "Es el único administrador activo: asigna otro antes de cambiarle el rol."
        : null;
    const losesClinic = Boolean(member.attends_patients) && !nextAttends;
    const pending = state === "pending" || state === "expired";

    const setField = (field, value) => setDraft((current) => ({ ...current, [field]: value }));

    const onRoleChange = (role) => setDraft((current) => ({
        ...current,
        role,
        attends_patients: role === "ADMIN" ? (member.role === "ADMIN" && Boolean(member.attends_patients)) : false,
    }));

    const onToggle = (code, checked) => {
        setOverrides(toggleCode(catalog, viewDraft, code, checked));
        setPermsTouched(true);
    };

    const onRestore = () => {
        setOverrides(restoreRoleDefaults(viewDraft));
        setPermsTouched(true);
    };

    const save = async () => {
        if (!dirty || saving) return;
        const found = profileErrors(draft);
        if (!canUpdate) {
            delete found.first_name;
            delete found.last_name;
            delete found.email;
        }
        setErrors(found);
        if (Object.keys(found).length > 0) return;
        if (decisionShown && keepCustom === null) {
            toast.error("Elige qué pasa con sus permisos personalizados.");
            return;
        }
        const body = canUpdate ? { ...changes } : {};
        if (roleChanged) {
            body.role = draft.role;
            if (draft.role === "ADMIN") body.attends_patients = draft.attends_patients;
        } else if (attendsChanged) {
            body.attends_patients = draft.attends_patients;
        }
        if (permissionsChanged && canManagePermissions) {
            body.permissions = permissionsPayload(catalog, viewDraft);
            // ADR p69 §12: los que se veían al abrir la ficha, tal como llegaron
            // (nunca releídos antes de guardar: eso compararía contra sí mismo).
            body.expected_permissions = [...(member.permissions || [])].sort();
        } else if (decisionShown) {
            body.keep_custom_permissions = keepCustom;
        }
        setSaving(true);
        try {
            await updateStaff(member.public_id, body);
            toast.success("Cambios guardados");
            await load({ reset: true });
            if (isSelf) refreshUser?.();
            onSaved?.();
        } catch (err) {
            handleFormError(err, setErrors);
            // 409 permissions_changed: otro administrador cambió sus permisos.
            // Se recargan y se vuelve a decidir sobre ellos; nunca se reintenta.
            // Los datos que se estaban editando se conservan.
            if (err?.response?.status === 409 && err?.response?.data?.code === "permissions_changed") {
                const fresh = await load();
                if (fresh) {
                    setOverrides(draftFromMember(fresh));
                    setPermsTouched(false);
                    setKeepCustom(null);
                }
            }
        } finally {
            setSaving(false);
        }
    };

    const afterAction = async (action) => {
        const done = await action(member);
        if (done !== false) {
            await load({ reset: !dirty });
            onSaved?.();
        }
    };

    return (
        <DrawerShell
            titleId={titleId}
            onClose={requestClose}
            closeDisabled={saving}
            title={fullName(member)}
            header={(
                <div className={styles.identity}>
                    <MemberAvatar member={member} size="lg" />
                    <div className={styles.identityText}>
                        <h2 id={titleId} ref={headingRef} tabIndex={-1} className={styles.name}>
                            {fullName(member)}
                            {isSelf && <span className="badge badge-default">Tú</span>}
                        </h2>
                        {/* Una línea: rol, especialidades y estado. El correo vive en Datos. */}
                        <p className={styles.meta}>
                            <span>
                                {roleLabel(member.role)}
                                {member.specialties?.length > 0 && ` · ${specialtiesLabel(member.specialties)}`}
                            </span>
                            {/* D6: «Activo» es lo normal y no lleva color. */}
                            <span className={`badge ${state === "expired" ? "badge-warning" : "badge-default"}`}>
                                {ACCOUNT_STATE_LABELS[state]}
                            </span>
                        </p>
                    </div>
                </div>
            )}
            footer={(
                <>
                    {active && can("staff.destroy") && !isSelf && !member.demo_protected && (
                        <button
                            type="button"
                            className={`btn btn-ghost btn-md ${styles.dangerButton}`}
                            onClick={() => afterAction(onDeactivate)}
                            disabled={saving || busy}
                        >
                            <Icon.UserX s={14} /> Desactivar acceso
                        </button>
                    )}
                    {!active && can("staff.reactivate") && (
                        <button
                            type="button"
                            className="btn btn-secondary btn-md"
                            onClick={() => afterAction(onReactivate)}
                            disabled={saving || busy}
                        >
                            <Icon.UserCheck s={14} /> Reactivar acceso
                        </button>
                    )}
                    <span className={styles.footerSpacer} />
                    <button type="button" className="btn btn-secondary btn-md" onClick={requestClose} disabled={saving}>
                        {dirty ? "Cancelar" : "Cerrar"}
                    </button>
                    {editable && (
                        <button
                            type="button"
                            className="btn btn-primary btn-md"
                            onClick={save}
                            disabled={!dirty || saving}
                        >
                            {saving ? "Guardando..." : "Guardar cambios"}
                        </button>
                    )}
                </>
            )}
        >
            <div className={styles.body}>
                {alerts.length > 0 && (
                    <div className={styles.alerts} role="status">
                        {alerts.map((alert) => (
                            <div key={alert.kind} className={styles.alert}>
                                <Icon.AlertTriangle s={16} />
                                {alert.kind === "missing_license" ? (
                                    <>
                                        <span>No puede firmar recetas: falta su cédula profesional.</span>
                                        {canUpdate && editable && (
                                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => licenseRef.current?.focus()}>
                                                Completar cédula
                                            </button>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        <span>Su invitación venció sin que entrara.</span>
                                        {can("staff.reset_password") && (
                                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => afterAction(onResetPassword)} disabled={busy}>
                                                Reenviar invitación
                                            </button>
                                        )}
                                    </>
                                )}
                            </div>
                        ))}
                    </div>
                )}
                {member.demo_protected && (
                    <p className={styles.notice}>Cuenta de la demo: se puede consultar, no editar.</p>
                )}

                <Section id={`${titleId}-role`} title="Rol">
                    <div ref={roleRef} tabIndex={-1} className={styles.focusTarget}>
                        <RolePicker
                            compact
                            name="member-role"
                            value={draft.role}
                            onChange={onRoleChange}
                            disabled={!editable || Boolean(roleLock)}
                        />
                    </div>
                    {roleLock && editable && <p className={styles.muted}>{roleLock}</p>}
                    {draft.role === "ADMIN" && (
                        <AttendsField
                            compact
                            id="member-attends"
                            checked={draft.attends_patients}
                            onChange={(value) => setField("attends_patients", value)}
                            disabled={!editable || (!roleChanged && !canUpdate)}
                        />
                    )}
                    <FieldError message={errors.attends_patients || errors.role} />
                    {losesClinic && impactSentence(impact) && (
                        <p className={styles.notice}>{impactSentence(impact)}</p>
                    )}
                    {decisionShown && (
                        <fieldset className={styles.decision}>
                            <legend className={styles.decisionTitle}>
                                Tiene permisos ajustados. ¿Los conserva con el rol nuevo?
                            </legend>
                            <label className={styles.decisionOption}>
                                <input type="radio" name="keep-custom" checked={keepCustom === true} onChange={() => setKeepCustom(true)} />
                                Conservar ajustes
                            </label>
                            <label className={styles.decisionOption}>
                                <input type="radio" name="keep-custom" checked={keepCustom === false} onChange={() => setKeepCustom(false)} />
                                Usar los de {roleLabel(draft.role)}
                            </label>
                            <FieldError message={errors.keep_custom_permissions} />
                        </fieldset>
                    )}
                </Section>

                <Section id={`${titleId}-permissions`} title="Permisos">
                    {catalog ? (
                        <PermissionEditor
                            catalog={catalog}
                            draft={viewDraft}
                            onToggle={onToggle}
                            onRestore={onRestore}
                            readOnly={!canManagePermissions || !editable}
                            isSelf={isSelf}
                            initial={new Set(member.permissions || [])}
                        />
                    ) : (
                        <p className={styles.muted}>No se pudo cargar el catálogo de permisos.</p>
                    )}
                    <FieldError message={errors.permissions} />
                </Section>

                <Section id={`${titleId}-data`} title="Datos">
                    <div className={styles.formGrid}>
                        <div className="form-group">
                            <label className="form-label" htmlFor="member-first-name">NOMBRE *</label>
                            <input
                                id="member-first-name"
                                className={inputClass(errors.first_name)}
                                value={draft.first_name}
                                disabled={!editable || !canUpdate}
                                onChange={(e) => setField("first_name", e.target.value)}
                            />
                            <FieldError message={errors.first_name} />
                        </div>
                        <div className="form-group">
                            <label className="form-label" htmlFor="member-last-name">APELLIDO</label>
                            <input
                                id="member-last-name"
                                className={inputClass(errors.last_name)}
                                value={draft.last_name}
                                disabled={!editable || !canUpdate}
                                onChange={(e) => setField("last_name", e.target.value)}
                            />
                            <FieldError message={errors.last_name} />
                        </div>
                        <div className={`form-group ${styles.fullRow}`}>
                            <label className="form-label" htmlFor="member-email">CORREO ELECTRÓNICO *</label>
                            <input
                                id="member-email"
                                type="email"
                                className={inputClass(errors.email)}
                                value={draft.email}
                                disabled={!editable || !canUpdate}
                                onChange={(e) => setField("email", e.target.value)}
                            />
                            <FieldError message={errors.email} />
                            {"email" in changes && <p className={styles.notice}>{EMAIL_CHANGE_NOTICE}</p>}
                            {user?.is_demo && <p className="form-hint">{DEMO_EMAIL_HINT}</p>}
                        </div>
                        <div className={`form-group ${styles.fullRow}`}>
                            <label className="form-label" htmlFor="member-license">
                                CÉDULA PROFESIONAL{nextAttends ? " *" : ""}
                            </label>
                            <input
                                id="member-license"
                                ref={licenseRef}
                                className={inputClass(errors.license_number)}
                                inputMode="numeric"
                                placeholder="Solo dígitos"
                                value={draft.license_number}
                                disabled={!editable || !canUpdate}
                                onChange={(e) => setField("license_number", e.target.value)}
                            />
                            <FieldError message={errors.license_number} />
                        </div>
                        {nextAttends && (
                            <div className={`form-group ${styles.fullRow}`}>
                                <SpecialtyPicker
                                    idPrefix="member-specialty"
                                    value={draft.specialties}
                                    onChange={(next) => setField("specialties", next)}
                                    disabled={!editable || !canUpdate}
                                    error={errors.specialties}
                                />
                            </div>
                        )}
                    </div>
                </Section>

                <Section
                    id={`${titleId}-security`}
                    title="Seguridad y acceso"
                    action={active && can("staff.reset_password") && !isSelf && (
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => afterAction(onResetPassword)} disabled={busy || saving}>
                            {pending ? "Reenviar invitación" : "Restablecer contraseña"}
                        </button>
                    )}
                >
                    <dl className={styles.fields}>
                        <div className={styles.field}>
                            <dt>Estado</dt>
                            <dd>{access.label}{access.detail && state !== "active" ? ` · ${access.detail}` : ""}</dd>
                        </div>
                        <div className={styles.field}>
                            <dt>Último acceso</dt>
                            <dd title={access.title || undefined}>{lastAccessShort(member, { isSelf })}</dd>
                        </div>
                        <div className={styles.field}>
                            <dt>Usuario</dt>
                            <dd className={styles.mono}>{member.username}</dd>
                        </div>
                        {member.role === "ADMIN" && (
                            <div className={styles.field}>
                                <dt>Verificación en dos pasos</dt>
                                <dd>{member.mfa_enabled ? "Activada" : "No activada"}</dd>
                            </div>
                        )}
                    </dl>
                </Section>

                <Section
                    id={`${titleId}-appointments`}
                    title="Citas por atender"
                    action={canReassign && appointments.length > 0 && (
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setReassign({ appointments })}>
                            Reasignar citas
                        </button>
                    )}
                >
                    {appointments.length === 0 ? (
                        <p className={styles.muted}>No tiene citas programadas ni confirmadas por atender.</p>
                    ) : (
                        <ul className={styles.list} aria-label="Citas por atender">
                            {appointments.map((appt) => (
                                <li key={appt.public_id} className={styles.item}>
                                    <span className={styles.itemTitle}>
                                        {formatLocalDate(appt.date)} · {appt.start_time} · {appt.pet_name}
                                    </span>
                                    <span className={styles.muted}>{appt.owner_name} · {appt.reason}</span>
                                </li>
                            ))}
                        </ul>
                    )}
                    {impact.open_medical_records > 0 && (
                        <p className={styles.muted}>
                            Además tiene {plural(impact.open_medical_records, "consulta abierta", "consultas abiertas")}.
                        </p>
                    )}
                </Section>

                <Section id={`${titleId}-absences`} title="Ausencias">
                    <MemberAbsences
                        member={member}
                        absences={absences}
                        today={orgTodayIso(tz)}
                        canManage={canAbsences}
                        onChanged={() => load()}
                        onAffected={(affected) => {
                            if (affected.length === 0) return;
                            if (canReassign) setReassign({ appointments: affected });
                            else toast.info(`Tiene ${plural(affected.length, "cita", "citas")} en esos días; pide que las reasignen.`);
                        }}
                    />
                </Section>

                <Section id={`${titleId}-history`} title="Historial">
                    {history.length === 0 ? (
                        <p className={styles.muted}>Sin cambios registrados. El historial empezó a guardarse con esta versión.</p>
                    ) : (
                        <ol className={styles.list} aria-label="Historial">
                            {history.map((event, index) => (
                                <li key={`${event.created_at}-${index}`} className={styles.item}>
                                    <span className={styles.itemTitle}>{describeEvent(event, catalog)}</span>
                                    <span className={styles.muted}>
                                        {formatDateTime(event.created_at, tz, "es-MX")} · {event.actor_name}
                                    </span>
                                </li>
                            ))}
                        </ol>
                    )}
                </Section>
            </div>

            {reassign && (
                <ReassignModal
                    source={member}
                    appointments={reassign.appointments}
                    candidates={team}
                    onClose={() => setReassign(null)}
                    onDone={() => load()}
                />
            )}
        </DrawerShell>
    );
}

function DrawerShell({ titleId, title, header, footer, onClose, closeDisabled = false, children }) {
    return (
        <div className={styles.overlay} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
            <div className={styles.drawer} role="dialog" aria-modal="true" aria-labelledby={header ? titleId : undefined} aria-label={header ? undefined : title}>
                <div className={styles.header}>
                    {header || <h2 className={styles.name}>{title}</h2>}
                    <button type="button" className="modal-close" onClick={onClose} disabled={closeDisabled} aria-label="Cerrar ficha">
                        <Icon.X s={16} />
                    </button>
                </div>
                {children}
                {footer && <div className={styles.footer}>{footer}</div>}
            </div>
        </div>
    );
}
