// Reasignación en bloque de citas por atender (ADR p67). Decisión del PO: un
// veterinario destino para todas; cada cita se mueve si el destino está libre a
// esa hora. Las que no, se quedan como estaban y se listan con su motivo. Nunca
// cambia la fecha ni la hora. Cada cita viaja con el `expected_state` con el que
// llegó a esta lista (INV-A): no se relee antes de enviar.
import { useState } from "react";
import { toast } from "sonner";
import { reassignAppointments } from "../../api/appointments";
import { Icon } from "../../components/icons";
import { apiError } from "../../utils/apiError";
import { formatLocalDate } from "./absences";
import styles from "./ReassignModal.module.css";

const fullName = (member) =>
    `${member?.first_name || ""} ${member?.last_name || ""}`.trim() || member?.username || "";

const describeAppointment = (appt) =>
    `${formatLocalDate(appt.date)} · ${appt.start_time} · ${appt.pet_name} (${appt.owner_name})`;

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

export default function ReassignModal({ source, appointments, candidates, onClose, onDone }) {
    const [targetId, setTargetId] = useState("");
    const [saving, setSaving] = useState(false);
    const [result, setResult] = useState(null);

    const options = (candidates || []).filter(
        (member) => member.attends_patients && member.public_id !== source.public_id,
    );
    const byId = new Map(appointments.map((appt) => [appt.public_id, appt]));

    const submit = async () => {
        if (!targetId) {
            toast.error("Elige quién atenderá las citas");
            return;
        }
        setSaving(true);
        try {
            const data = await reassignAppointments({
                sourcePublicId: source.public_id,
                targetPublicId: targetId,
                appointments,
            });
            setResult(data);
            if (data.moved.length > 0) {
                toast.success(plural(data.moved.length, "cita reasignada", "citas reasignadas"));
            }
            onDone?.(data);
        } catch (err) {
            toast.error(apiError(err, "No se pudieron reasignar las citas."));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="modal-overlay">
            <div className="modal modal-md" role="dialog" aria-label={`Reasignar citas de ${fullName(source)}`}>
                <div className="modal-header">
                    <h3>Reasignar citas de {fullName(source)}</h3>
                    <button className="modal-close" onClick={onClose} disabled={saving} aria-label="Cerrar">
                        <Icon.X s={16} />
                    </button>
                </div>
                <div className="modal-body">
                    {result ? (
                        <>
                            <p className={styles.summary}>
                                Se reasignaron {result.moved.length} de {appointments.length}.
                            </p>
                            {result.skipped.length > 0 && (
                                <>
                                    <p className={styles.hint}>
                                        Estas se quedaron como estaban; resuélvelas en la agenda:
                                    </p>
                                    <ul className={styles.list} aria-label="Citas sin reasignar">
                                        {result.skipped.map((item) => {
                                            const appt = byId.get(item.public_id);
                                            return (
                                                <li key={item.public_id} className={styles.item}>
                                                    <span>{appt ? describeAppointment(appt) : "Cita"}</span>
                                                    <span className={styles.reason}>{item.message}</span>
                                                </li>
                                            );
                                        })}
                                    </ul>
                                </>
                            )}
                        </>
                    ) : (
                        <>
                            <ul className={styles.list} aria-label="Citas a reasignar">
                                {appointments.map((appt) => (
                                    <li key={appt.public_id} className={styles.item}>
                                        <span>{describeAppointment(appt)}</span>
                                        <span className={styles.meta}>{appt.reason}</span>
                                    </li>
                                ))}
                            </ul>
                            {options.length === 0 ? (
                                <p className={styles.hint}>
                                    No hay otro integrante activo que atienda pacientes. Márcalo en Equipo o da de alta a un veterinario.
                                </p>
                            ) : (
                                <div className="form-group">
                                    <label htmlFor="reassign-target">Las atenderá</label>
                                    <select
                                        id="reassign-target"
                                        className="select-input"
                                        value={targetId}
                                        onChange={(event) => setTargetId(event.target.value)}
                                        disabled={saving}
                                    >
                                        <option value="">Selecciona un veterinario</option>
                                        {options.map((member) => (
                                            <option key={member.public_id} value={member.public_id}>
                                                {fullName(member)}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            )}
                            <p className={styles.hint}>
                                Solo cambia el veterinario: la fecha y la hora se conservan. Las que choquen con su agenda o caigan en una ausencia suya se quedan como están.
                            </p>
                        </>
                    )}
                </div>
                <div className="modal-footer">
                    {result ? (
                        <button className={`btn btn-primary btn-md ${styles.footerButton}`} onClick={onClose}>
                            Cerrar
                        </button>
                    ) : (
                        <>
                            <button
                                className={`btn btn-primary btn-md ${styles.footerButton}`}
                                onClick={submit}
                                disabled={saving || options.length === 0}
                            >
                                {saving ? "Reasignando..." : `Reasignar ${plural(appointments.length, "cita", "citas")}`}
                            </button>
                            <button className={`btn btn-secondary btn-md ${styles.footerButton}`} onClick={onClose} disabled={saving}>
                                Cancelar
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
