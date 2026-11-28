import { useState } from "react";
import { toast } from "sonner";
import { replaceSchedule } from "../../api/organizations";
import { validateWeek } from "../../features/config/schedule";
import handleFormError from "../../utils/handleFormError";
import SettingsPanel from "./SettingsPanel";
import styles from "./config.module.css";

const WEEKDAY_LABELS = {
  1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
  5: "Viernes", 6: "Sábado", 7: "Domingo",
};

const toHM = (t) => (t ? t.slice(0, 5) : "");
const toHMS = (v) => (v ? `${v}:00` : null);

/**
 * `schedule` es el borrador (plan F1.3). Antes de guardar se valida cada día con
 * los mismos mensajes que el servidor; los errores, propios o del servidor
 * (`day_N`), se pintan en la fila de su día.
 */
const ScheduleSection = ({ schedule, onScheduleChange, onSaved }) => {
  const [saving, setSaving] = useState(false);
  const [clientErrors, setClientErrors] = useState({});
  const [serverErrors, setServerErrors] = useState({});

  const dayError = (weekday) => clientErrors[weekday]
    || serverErrors[`day_${weekday}.non_field_errors`]
    || serverErrors[`day_${weekday}`];

  const updateDay = (weekday, patch) => {
    onScheduleChange(prev =>
      prev.map(d => d.weekday === weekday ? { ...d, ...patch } : d)
    );
  };

  const setOpen = (weekday, open) => {
    updateDay(weekday, open
      ? { is_closed: false, opens_at: "09:00:00", closes_at: "18:00:00" }
      : { is_closed: true, opens_at: null, closes_at: null,
          has_break: false, break_start: null, break_end: null });
  };

  const setBreak = (weekday, on) => {
    updateDay(weekday, on
      ? { has_break: true, break_start: "13:00:00", break_end: "14:00:00" }
      : { has_break: false, break_start: null, break_end: null });
  };

  const handleSave = async () => {
    const found = validateWeek(schedule);
    setClientErrors(found);
    setServerErrors({});
    if (Object.keys(found).length > 0) {
      toast.error("Revisa el horario de los días marcados.");
      return;
    }
    setSaving(true);
    const toastId = toast.loading("Guardando...");
    try {
      const updated = await replaceSchedule(schedule);
      toast.success("Horario guardado", { id: toastId });
      if (Array.isArray(updated)) onSaved(updated);
    } catch (err) {
      toast.dismiss(toastId);
      handleFormError(err, setServerErrors);
    } finally {
      setSaving(false);
    }
  };

  const timeCell = (day, field, fallback, enabled, label) => (
    <input
      type="time"
      aria-label={`${label} del ${WEEKDAY_LABELS[day.weekday].toLowerCase()}`}
      className={styles.scheduleTimeInput}
      value={enabled ? (toHM(day[field]) || fallback) : ""}
      disabled={!enabled}
      onChange={(e) => updateDay(day.weekday, { [field]: toHMS(e.target.value) })}
    />
  );

  return (
    <SettingsPanel
      title="Horario"
      description="Cuándo atiende la clínica. El asistente solo ofrece citas dentro de este horario; el descanso parte el día en dos."
      padded={false}
      footerNote="Días completos, una franja + descanso opcional."
      footer={
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Guardando..." : "Guardar horario"}
        </button>
      }
    >
      <table className={styles.scheduleTable}>
        <thead>
          <tr>
            <th className={styles.scheduleTh}>Día</th>
            <th className={styles.scheduleTh}>Abierto</th>
            <th className={styles.scheduleTh}>Entrada</th>
            <th className={styles.scheduleTh}>Salida</th>
            <th className={styles.scheduleTh}>Descanso</th>
            <th className={styles.scheduleTh}>Desde</th>
            <th className={styles.scheduleTh}>Hasta</th>
          </tr>
        </thead>
        <tbody>
          {schedule.map((day) => {
            const open = !day.is_closed;
            const brk = open && day.has_break;
            const name = WEEKDAY_LABELS[day.weekday];
            const error = dayError(day.weekday);
            const rowClass = [day.is_closed && styles.scheduleRowClosed, error && styles.scheduleRowError]
              .filter(Boolean).join(" ");
            return (
              <tr key={day.weekday} className={rowClass}>
                <td className={styles.scheduleTd} data-label="Día">
                  <span className={styles.scheduleDayName}>{name}</span>
                  {error && <p className={styles.scheduleDayError} role="alert">{error}</p>}
                </td>
                <td className={styles.scheduleTd} data-label="Abierto">
                  <input type="checkbox" className={styles.scheduleCheckbox} aria-label={`${name} abierto`}
                    checked={open} onChange={(e) => setOpen(day.weekday, e.target.checked)} />
                </td>
                <td className={styles.scheduleTd} data-label="Entrada">{timeCell(day, "opens_at", "09:00", open, "Entrada")}</td>
                <td className={styles.scheduleTd} data-label="Salida">{timeCell(day, "closes_at", "18:00", open, "Salida")}</td>
                <td className={styles.scheduleTd} data-label="Descanso">
                  <input type="checkbox" className={styles.scheduleCheckbox} aria-label={`${name} con descanso`}
                    checked={!!day.has_break} disabled={!open}
                    onChange={(e) => setBreak(day.weekday, e.target.checked)} />
                </td>
                <td className={styles.scheduleTd} data-label="Desde">{timeCell(day, "break_start", "13:00", brk, "Inicio del descanso")}</td>
                <td className={styles.scheduleTd} data-label="Hasta">{timeCell(day, "break_end", "14:00", brk, "Fin del descanso")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className={styles.scheduleHint}>
        Marca “Descanso” para cerrar a media jornada (comida, por ejemplo): se atiende antes y después.
      </p>
    </SettingsPanel>
  );
};

export default ScheduleSection;
