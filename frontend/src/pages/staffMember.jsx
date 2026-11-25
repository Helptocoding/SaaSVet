// Ficha del integrante (ADR p67): datos, pendientes, citas por atender,
// ausencias e historial en un solo lugar. Es una pantalla de gestión: quien no
// gestiona personal no la abre ni por URL (el backend tampoco le entrega nada).
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import Skeleton from "react-loading-skeleton";
import {
    cancelAbsence, createAbsence, getAbsences, getStaff, getStaffAppointments, getStaffHistory,
    getStaffImpact, getStaffProfile,
} from "../api/staff";
import { useAuth } from "../auth/authContext";
import DateField from "../components/DateField";
import EmptyState from "../components/EmptyState";
import { useConfirm } from "../components/useConfirm";
import { describeAccess } from "../features/staff/access";
import {
    ABSENCE_KINDS, absenceKindLabel, formatAbsenceRange, formatLocalDate, orgTodayIso,
} from "../features/staff/absences";
import { describeEvent } from "../features/staff/history";
import { STAFF_MANAGEMENT_PERMS } from "../features/staff/permissions";
import { roleLabel } from "../features/staff/roles";
import ReassignModal from "../features/staff/ReassignModal";
import { apiError } from "../utils/apiError";
import handleFormError from "../utils/handleFormError";
import { formatDateTime, orgTz } from "../utils/datetime";
import styles from "./staffMember.module.css";

const fullName = (member) =>
    `${member?.first_name || ""} ${member?.last_name || ""}`.trim() || member?.username || "";

const EMPTY_ABSENCE = { start_date: "", end_date: "", kind: "vacation" };

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

function Field({ label, children }) {
    return (
        <div className={styles.field}>
            <dt className={styles.fieldLabel}>{label}</dt>
            <dd className={styles.fieldValue}>{children || "—"}</dd>
        </div>
    );
}

function Section({ id, title, action, children }) {
    return (
        <section className={styles.card} aria-labelledby={id}>
            <div className={styles.cardHeader}>
                <h2 id={id} className={styles.cardTitle}>{title}</h2>
                {action}
            </div>
            {children}
        </section>
    );
}

const StaffMember = () => {
    const { publicId } = useParams();
    const { user, initializing, can, canAny } = useAuth();
    const confirm = useConfirm();
    const canManage = canAny(STAFF_MANAGEMENT_PERMS);
    const canAbsences = can("staff.manage_absences");
    const canReassign = can("appointment.update");
    const tz = orgTz(user);

    const [data, setData] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [team, setTeam] = useState([]);
    const [absenceForm, setAbsenceForm] = useState(EMPTY_ABSENCE);
    const [absenceErrors, setAbsenceErrors] = useState({});
    const [savingAbsence, setSavingAbsence] = useState(false);
    const [cancellingId, setCancellingId] = useState(null);
    // Reasignación abierta: { appointments } | null.
    const [reassign, setReassign] = useState(null);

    const load = useCallback(async () => {
        try {
            const [member, impact, appointments, absences, history, staff] = await Promise.all([
                getStaffProfile(publicId),
                getStaffImpact(publicId),
                getStaffAppointments(publicId),
                getAbsences({ member: publicId }),
                getStaffHistory(publicId),
                getStaff(),
            ]);
            setData({ member, impact, appointments, absences, history });
            setTeam(staff);
            setLoadError(null);
        } catch (err) {
            setLoadError(err?.response?.status === 404
                ? "No encontramos a este integrante en tu clínica."
                : apiError(err, "No se pudo cargar la ficha."));
        }
    }, [publicId]);

    useEffect(() => {
        if (!initializing && user && canManage) {
            // eslint-disable-next-line react-hooks/set-state-in-effect -- carga de la ficha desde la API al montar o cambiar de integrante
            load();
        }
    }, [initializing, user, canManage, load]);

    if (!initializing && !canManage) {
        return <Navigate to="/" replace />;
    }

    if (loadError) {
        return (
            <div>
                <Link to="/staff" className={styles.back}>← Equipo</Link>
                <EmptyState title="Ficha no disponible" body={loadError}
                    actions={[{ label: "Reintentar", onClick: load, variant: "secondary" }]} />
            </div>
        );
    }

    if (!data) {
        return (
            <div role="status" aria-label="Cargando ficha">
                <Link to="/staff" className={styles.back}>← Equipo</Link>
                <Skeleton width={220} height={24} />
                <Skeleton width={160} height={12} />
                <div className={styles.grid}>
                    {[0, 1, 2].map((key) => (
                        <div key={key} className={styles.card} aria-hidden="true">
                            <Skeleton count={4} height={14} />
                        </div>
                    ))}
                </div>
            </div>
        );
    }

    const { member, impact, appointments, absences, history } = data;
    const access = describeAccess(member.access, tz);
    const today = orgTodayIso(tz);
    const isSelf = user?.id != null && member.id === user.id;

    // ── Ausencias ─────────────────────────────────────────────────────────
    const absenceError = () => {
        const errors = {};
        if (!absenceForm.start_date) errors.start_date = "Elige el primer día";
        if (!absenceForm.end_date) errors.end_date = "Elige el último día";
        else if (absenceForm.start_date && absenceForm.end_date < absenceForm.start_date) {
            errors.end_date = "El último día no puede ser anterior al primero";
        }
        return errors;
    };

    const handleRegisterAbsence = async () => {
        if (savingAbsence) return;
        const errors = absenceError();
        setAbsenceErrors(errors);
        if (Object.keys(errors).length) return;
        setSavingAbsence(true);
        try {
            const result = await createAbsence(member.public_id, {
                startDate: absenceForm.start_date,
                endDate: absenceForm.end_date,
                kind: absenceForm.kind,
            });
            toast.success("Ausencia registrada");
            setAbsenceForm(EMPTY_ABSENCE);
            setAbsenceErrors({});
            await load();
            const affected = result.affected_appointments || [];
            if (affected.length > 0 && canReassign) {
                setReassign({ appointments: affected });
            } else if (affected.length > 0) {
                toast.info(`Tiene ${plural(affected.length, "cita", "citas")} en esos días; pide que las reasignen.`);
            }
        } catch (err) {
            handleFormError(err, setAbsenceErrors);
        } finally {
            setSavingAbsence(false);
        }
    };

    const handleCancelAbsence = async (absence) => {
        if (cancellingId) return;
        const ok = await confirm({
            title: "Cancelar ausencia",
            message: `${absenceKindLabel(absence.kind)} del ${formatAbsenceRange(absence.start_date, absence.end_date)}. Volverá a poder recibir citas esos días.`,
            confirmText: "Cancelar ausencia",
            dangerMode: true,
        });
        if (!ok) return;
        setCancellingId(absence.public_id);
        try {
            await cancelAbsence(absence.public_id);
            toast.success("Ausencia cancelada");
            await load();
        } catch (err) {
            toast.error(apiError(err, "No se pudo cancelar la ausencia."));
        } finally {
            setCancellingId(null);
        }
    };

    const pendingParts = [
        plural(impact.upcoming_appointments, "cita por atender", "citas por atender"),
        plural(impact.open_medical_records, "consulta abierta", "consultas abiertas"),
    ];
    if (impact.open_cash_session) pendingParts.push("caja abierta");

    return (
        <div>
            <Link to="/staff" className={styles.back}>← Equipo</Link>
            <div className="page-header">
                <div>
                    <h1 className="page-title">
                        {fullName(member)}
                        {isSelf && <span className={`badge badge-default ${styles.inlineBadge}`}>Tú</span>}
                        {!member.is_active && <span className={`badge badge-danger ${styles.inlineBadge}`}>Inactivo</span>}
                    </h1>
                    <p className={styles.subtitle}>
                        {roleLabel(member.role)}
                        {member.attends_patients ? " · Atiende pacientes" : ""}
                        {" · "}{pendingParts.join(" · ")}
                    </p>
                </div>
            </div>

            <div className={styles.grid}>
                <Section id="ficha-datos" title="Datos">
                    <dl className={styles.fields}>
                        <Field label="Correo">{member.email}</Field>
                        <Field label="Usuario">{member.username}</Field>
                        <Field label="Especialidad">{member.specialty}</Field>
                        <Field label="Cédula profesional">{member.license_number}</Field>
                        <Field label="Acceso">
                            <span title={access.title}>{access.label}{access.detail ? ` · ${access.detail}` : ""}</span>
                        </Field>
                    </dl>
                </Section>

                <Section
                    id="ficha-citas"
                    title="Citas por atender"
                    action={canReassign && appointments.length > 0 && (
                        <button className="btn btn-secondary btn-sm" onClick={() => setReassign({ appointments })}>
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
                </Section>

                <Section id="ficha-ausencias" title="Ausencias">
                    {absences.length === 0 ? (
                        <p className={styles.muted}>Sin ausencias registradas de hoy en adelante.</p>
                    ) : (
                        <ul className={styles.list} aria-label="Ausencias">
                            {absences.map((absence) => (
                                <li key={absence.public_id} className={`${styles.item} ${styles.itemRow}`}>
                                    <div>
                                        <span className={styles.itemTitle}>
                                            {absenceKindLabel(absence.kind)} · {formatAbsenceRange(absence.start_date, absence.end_date)}
                                        </span>
                                        <span className={styles.muted}>Registró {absence.created_by_name}</span>
                                    </div>
                                    {canAbsences && (
                                        <button
                                            className="btn btn-secondary btn-sm"
                                            onClick={() => handleCancelAbsence(absence)}
                                            disabled={Boolean(cancellingId)}
                                            aria-label={`Cancelar ausencia del ${formatAbsenceRange(absence.start_date, absence.end_date)}`}
                                        >
                                            {cancellingId === absence.public_id ? "Cancelando..." : "Cancelar"}
                                        </button>
                                    )}
                                </li>
                            ))}
                        </ul>
                    )}
                    {canAbsences && member.is_active && (
                        <div className={styles.absenceForm}>
                            <h3 className={styles.formTitle}>Registrar ausencia</h3>
                            <p className={styles.muted}>
                                Días completos. Mientras dure, nadie podrá agendarle citas esos días y el asistente de WhatsApp no ofrecerá sus horarios.
                            </p>
                            <div className={styles.formRow}>
                                <div className="form-group">
                                    <label htmlFor="absence-start">Primer día</label>
                                    <DateField
                                        id="absence-start"
                                        value={absenceForm.start_date}
                                        min={today}
                                        onChange={(value) => setAbsenceForm((form) => ({ ...form, start_date: value }))}
                                        disabled={savingAbsence}
                                    />
                                    {absenceErrors.start_date && <p className={styles.error}>{absenceErrors.start_date}</p>}
                                </div>
                                <div className="form-group">
                                    <label htmlFor="absence-end">Último día</label>
                                    <DateField
                                        id="absence-end"
                                        value={absenceForm.end_date}
                                        min={absenceForm.start_date || today}
                                        onChange={(value) => setAbsenceForm((form) => ({ ...form, end_date: value }))}
                                        disabled={savingAbsence}
                                    />
                                    {absenceErrors.end_date && <p className={styles.error}>{absenceErrors.end_date}</p>}
                                </div>
                                <div className="form-group">
                                    <label htmlFor="absence-kind">Tipo</label>
                                    <select
                                        id="absence-kind"
                                        className="select-input"
                                        value={absenceForm.kind}
                                        onChange={(event) => setAbsenceForm((form) => ({ ...form, kind: event.target.value }))}
                                        disabled={savingAbsence}
                                    >
                                        {ABSENCE_KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                    </select>
                                </div>
                            </div>
                            <button className="btn btn-primary btn-md" onClick={handleRegisterAbsence} disabled={savingAbsence}>
                                {savingAbsence ? "Registrando..." : "Registrar ausencia"}
                            </button>
                        </div>
                    )}
                </Section>

                <Section id="ficha-historial" title="Historial">
                    {history.length === 0 ? (
                        <p className={styles.muted}>Sin cambios registrados. El historial empezó a guardarse con esta versión.</p>
                    ) : (
                        <ol className={styles.list} aria-label="Historial">
                            {history.map((event, index) => (
                                <li key={`${event.created_at}-${index}`} className={styles.item}>
                                    <span className={styles.itemTitle}>{describeEvent(event)}</span>
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
        </div>
    );
};

export default StaffMember;
