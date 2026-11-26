// Ausencias del integrante dentro de su ficha (ADR p67): lista vigente, cancelar
// y registrar. Al registrar una con citas en esos días, avisa al padre para
// ofrecer la reasignación. El formulario se abre con «Nueva ausencia».
import { useState } from "react";
import { toast } from "sonner";
import { cancelAbsence, createAbsence } from "../../api/staff";
import DateField from "../../components/DateField";
import { Icon } from "../../components/icons";
import { useConfirm } from "../../components/useConfirm";
import { apiError } from "../../utils/apiError";
import handleFormError from "../../utils/handleFormError";
import { ABSENCE_KINDS, absenceKindLabel, formatAbsenceRange } from "./absences";
import { DateTile, FieldError } from "./StaffParts";
import styles from "./MemberDrawer.module.css";

const EMPTY_ABSENCE = { start_date: "", end_date: "", kind: "vacation" };

function absenceErrorsFor(form) {
    const errors = {};
    if (!form.start_date) errors.start_date = "Elige el primer día";
    if (!form.end_date) errors.end_date = "Elige el último día";
    else if (form.start_date && form.end_date < form.start_date) {
        errors.end_date = "El último día no puede ser anterior al primero";
    }
    return errors;
}

export default function MemberAbsences({ member, absences, today, canManage, onChanged, onAffected }) {
    const confirm = useConfirm();
    const [form, setForm] = useState(EMPTY_ABSENCE);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [cancellingId, setCancellingId] = useState(null);
    const [adding, setAdding] = useState(false);

    const closeForm = () => {
        setForm(EMPTY_ABSENCE);
        setErrors({});
        setAdding(false);
    };

    const register = async () => {
        if (saving) return;
        const found = absenceErrorsFor(form);
        setErrors(found);
        if (Object.keys(found).length) return;
        setSaving(true);
        try {
            const result = await createAbsence(member.public_id, {
                startDate: form.start_date,
                endDate: form.end_date,
                kind: form.kind,
            });
            toast.success("Ausencia registrada");
            closeForm();
            await onChanged();
            onAffected(result.affected_appointments || []);
        } catch (err) {
            handleFormError(err, setErrors);
        } finally {
            setSaving(false);
        }
    };

    const cancel = async (absence) => {
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
            await onChanged();
        } catch (err) {
            toast.error(apiError(err, "No se pudo cancelar la ausencia."));
        } finally {
            setCancellingId(null);
        }
    };

    return (
        <>
            {absences.length === 0 ? (
                <p className={styles.muted}>Sin ausencias próximas.</p>
            ) : (
                <ul className={styles.list} aria-label="Ausencias">
                    {absences.map((absence) => (
                        <li key={absence.public_id} className={`${styles.item} ${styles.itemWithTile} ${styles.itemRow}`}>
                            <DateTile iso={absence.start_date} />
                            <div className={styles.itemText}>
                                <span className={styles.itemTitle}>
                                    {absenceKindLabel(absence.kind)} · {formatAbsenceRange(absence.start_date, absence.end_date)}
                                </span>
                                <span className={styles.itemMeta}>Registró {absence.created_by_name}</span>
                            </div>
                            {canManage && (
                                <button
                                    type="button"
                                    className="btn btn-ghost btn-sm"
                                    onClick={() => cancel(absence)}
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
            {canManage && member.is_active && !adding && (
                <button type="button" className={`btn btn-ghost btn-sm ${styles.addButton}`} onClick={() => setAdding(true)}>
                    <Icon.Plus s={14} /> Nueva ausencia
                </button>
            )}
            {canManage && member.is_active && adding && (
                <div className={styles.subForm}>
                    <p className={styles.formHint}>Días completos. Esos días no recibe citas, tampoco por WhatsApp.</p>
                    <div className={styles.formRow}>
                        <div className="form-group">
                            <label htmlFor="absence-start">Primer día</label>
                            <DateField
                                id="absence-start"
                                value={form.start_date}
                                min={today}
                                onChange={(value) => setForm((current) => ({ ...current, start_date: value }))}
                                disabled={saving}
                            />
                            <FieldError message={errors.start_date} />
                        </div>
                        <div className="form-group">
                            <label htmlFor="absence-end">Último día</label>
                            <DateField
                                id="absence-end"
                                value={form.end_date}
                                min={form.start_date || today}
                                onChange={(value) => setForm((current) => ({ ...current, end_date: value }))}
                                disabled={saving}
                            />
                            <FieldError message={errors.end_date} />
                        </div>
                        <div className="form-group">
                            <label htmlFor="absence-kind">Tipo</label>
                            <select
                                id="absence-kind"
                                className="select-input"
                                value={form.kind}
                                onChange={(event) => setForm((current) => ({ ...current, kind: event.target.value }))}
                                disabled={saving}
                            >
                                {ABSENCE_KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className={styles.subFormActions}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={closeForm} disabled={saving}>
                            Cancelar
                        </button>
                        <button type="button" className="btn btn-primary btn-sm" onClick={register} disabled={saving}>
                            {saving ? "Registrando..." : "Registrar ausencia"}
                        </button>
                    </div>
                </div>
            )}
        </>
    );
}
