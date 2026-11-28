import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Skeleton from "react-loading-skeleton";
import { toast } from "sonner";
import { cancelClosure, createClosure, getClosures } from "../../api/organizations";
import { useAuth } from "../../auth/authContext";
import DateField from "../../components/DateField";
import EmptyState from "../../components/EmptyState";
import { Icon } from "../../components/icons";
import { useConfirm } from "../../components/useConfirm";
import { CLOSURE_REASON_MAX, closureErrorsFor } from "../../features/config/closures";
import { formatAbsenceRange, orgTodayIso } from "../../features/staff/absences";
import { apiError } from "../../utils/apiError";
import { orgTz } from "../../utils/datetime";
import handleFormError from "../../utils/handleFormError";
import SettingsPanel from "./SettingsPanel";
import styles from "./config.module.css";

const EMPTY_FORM = { start_date: "", end_date: "", reason: "" };

const appointmentsNotice = (count) => (count === 1
    ? "Hay 1 cita por atender en esos días. No se movió: revísala en Citas."
    : `Hay ${count} citas por atender en esos días. No se movieron: revísalas en Citas.`);

/**
 * Cierres excepcionales (ADR p70 D6, plan F2.1): días festivos o cualquier día
 * completo en que la clínica no atiende. Se guardan al momento (no forman parte
 * del borrador del horario). Las citas de esos días no se mueven: se avisa
 * cuántas hay; el asistente de WhatsApp deja de ofrecer y agendar esos días.
 */
const ClosuresSection = () => {
    const { user } = useAuth();
    const navigate = useNavigate();
    const confirm = useConfirm();
    const today = orgTodayIso(orgTz(user));

    // `attempt` cambia al reintentar o tras registrar/cancelar: el estado solo
    // cambia en los callbacks de la petición, nunca dentro del efecto.
    const [attempt, setAttempt] = useState(0);
    const [closures, setClosures] = useState(null);
    const [outcome, setOutcome] = useState({ key: null, error: null });
    const [adding, setAdding] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [cancellingId, setCancellingId] = useState(null);
    const [affected, setAffected] = useState(0);

    useEffect(() => {
        let current = true;
        getClosures()
            .then((data) => {
                if (!current) return;
                setClosures(Array.isArray(data) ? data : []);
                setOutcome({ key: attempt, error: null });
            })
            .catch((err) => {
                if (!current) return;
                setOutcome({ key: attempt, error: apiError(err, "No se pudieron cargar los cierres.") });
            });
        return () => { current = false; };
    }, [attempt]);

    const reload = () => setAttempt((n) => n + 1);
    const fetching = outcome.key !== attempt;
    const loadError = fetching ? null : outcome.error;

    const setField = (field, value) => setForm((currentForm) => ({ ...currentForm, [field]: value }));

    const closeForm = () => {
        setForm(EMPTY_FORM);
        setErrors({});
        setAdding(false);
    };

    const register = async () => {
        if (saving) return;
        const found = closureErrorsFor(form);
        setErrors(found);
        if (Object.keys(found).length) return;
        setSaving(true);
        try {
            const created = await createClosure({ ...form, reason: form.reason.trim() });
            toast.success("Cierre registrado");
            setAffected(created?.affected_appointments || 0);
            closeForm();
            reload();
        } catch (err) {
            handleFormError(err, setErrors);
        } finally {
            setSaving(false);
        }
    };

    const cancel = async (closure) => {
        if (cancellingId) return;
        const range = formatAbsenceRange(closure.start_date, closure.end_date);
        const ok = await confirm({
            title: "Cancelar cierre",
            message: `${closure.reason} · ${range}. Esos días se vuelve a atender según el horario, también por WhatsApp.`,
            confirmText: "Cancelar cierre",
            dangerMode: true,
        });
        if (!ok) return;
        setCancellingId(closure.public_id);
        try {
            await cancelClosure(closure.public_id);
            toast.success("Cierre cancelado");
            reload();
        } catch (err) {
            toast.error(apiError(err, "No se pudo cancelar el cierre."));
        } finally {
            setCancellingId(null);
        }
    };

    let list;
    if (loadError) {
        list = (
            <EmptyState
                compact
                icon={Icon.AlertCircle}
                title="No se pudieron cargar los cierres"
                body={loadError}
                actions={[{ label: "Reintentar", onClick: reload, variant: "secondary" }]}
            />
        );
    } else if (closures === null) {
        list = (
            <div role="status" aria-label="Cargando cierres" className={styles.historyList}>
                {[0, 1].map((i) => (
                    <div key={i} className={styles.historyItem} aria-hidden="true">
                        <Skeleton width="40%" height={14} />
                        <Skeleton width="25%" height={11} />
                    </div>
                ))}
            </div>
        );
    } else if (closures.length === 0) {
        list = <p className={styles.closureEmpty}>No hay cierres próximos.</p>;
    } else {
        list = (
            <ul className={styles.historyList} aria-label="Cierres próximos" aria-busy={fetching}>
                {closures.map((closure) => {
                    const range = formatAbsenceRange(closure.start_date, closure.end_date);
                    return (
                        <li key={closure.public_id} className={`${styles.historyItem} ${styles.closureItem}`}>
                            <div>
                                <p className={styles.historyTitle}>{closure.reason}</p>
                                <p className={styles.historyMeta}>{range}</p>
                            </div>
                            <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => cancel(closure)}
                                disabled={Boolean(cancellingId) || saving}
                                aria-label={`Cancelar cierre del ${range}`}
                            >
                                {cancellingId === closure.public_id ? "Cancelando..." : "Cancelar"}
                            </button>
                        </li>
                    );
                })}
            </ul>
        );
    }

    return (
        <SettingsPanel
            title="Cierres"
            description="Días completos en que la clínica no atiende, como un día festivo. El asistente de WhatsApp no ofrece citas esos días; las que ya existen no se mueven."
            padded={false}
            action={!adding && (
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAdding(true)}>
                    <Icon.Plus s={14} /> Nuevo cierre
                </button>
            )}
        >
            {affected > 0 && (
                <div className={styles.closureNotice} role="status">
                    <span>{appointmentsNotice(affected)}</span>
                    <div className={styles.closureNoticeActions}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigate("/appointments")}>
                            Ver citas
                        </button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAffected(0)}>
                            Entendido
                        </button>
                    </div>
                </div>
            )}
            {adding && (
                <div className={styles.closureForm}>
                    <div className={styles.closureFormRow}>
                        <div className="form-group">
                            <label htmlFor="closure-start">Primer día</label>
                            <DateField
                                id="closure-start"
                                value={form.start_date}
                                min={today}
                                onChange={(value) => setField("start_date", value)}
                                disabled={saving}
                            />
                            {errors.start_date && <p className={styles.fieldError} role="alert">{errors.start_date}</p>}
                        </div>
                        <div className="form-group">
                            <label htmlFor="closure-end">Último día</label>
                            <DateField
                                id="closure-end"
                                value={form.end_date}
                                min={form.start_date || today}
                                onChange={(value) => setField("end_date", value)}
                                disabled={saving}
                            />
                            {errors.end_date && <p className={styles.fieldError} role="alert">{errors.end_date}</p>}
                        </div>
                        <div className="form-group">
                            <label htmlFor="closure-reason">Motivo</label>
                            <input
                                id="closure-reason"
                                className={`input${errors.reason ? " input-error" : ""}`}
                                value={form.reason}
                                maxLength={CLOSURE_REASON_MAX}
                                placeholder="Día festivo"
                                onChange={(event) => setField("reason", event.target.value)}
                                disabled={saving}
                            />
                            {errors.reason && <p className={styles.fieldError} role="alert">{errors.reason}</p>}
                        </div>
                    </div>
                    <div className={styles.closureFormActions}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={closeForm} disabled={saving}>
                            Cancelar
                        </button>
                        <button type="button" className="btn btn-primary btn-sm" onClick={register} disabled={saving}>
                            {saving ? "Registrando..." : "Registrar cierre"}
                        </button>
                    </div>
                </div>
            )}
            {list}
        </SettingsPanel>
    );
};

export default ClosuresSection;
