import { useState } from "react";
import { toast } from "sonner";
import { replaceSchedule } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import styles from "./config.module.css";

const WEEKDAY_LABELS = {
  1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
  5: "Viernes", 6: "Sábado", 7: "Domingo",
};

// "HH:MM:SS" | "HH:MM" | null → "HH:MM"
const toHM = (t) => (t ? t.slice(0, 5) : "");
// "HH:MM" → "HH:MM:00" (formato que espera el backend TimeField)
const toHMS = (v) => (v ? `${v}:00` : null);

const ScheduleSection = ({ schedule, onScheduleChange }) => {
  const [saving, setSaving] = useState(false);

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
    setSaving(true);
    try {
      const updated = await toast.promise(
        replaceSchedule(schedule),
        { loading: "Guardando...", success: "Horario guardado", error: (e) => apiError(e) }
      );
      onScheduleChange(updated);
    } catch {
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <table className={styles.scheduleTable}>
        <thead>
          <tr>
            <th className={styles.scheduleTh}>Día</th>
            <th className={styles.scheduleTh}>Abre</th>
            <th className={styles.scheduleTh}>Entrada</th>
            <th className={styles.scheduleTh}>Salida</th>
            <th className={styles.scheduleTh}>Descanso</th>
            <th className={styles.scheduleTh}>Desde</th>
            <th className={styles.scheduleTh}>Hasta</th>
          </tr>
        </thead>
        <tbody>
          {schedule.map((day) => (
            <tr key={day.weekday} className={day.is_closed ? styles.scheduleRowClosed : ""}>
              <td className={styles.scheduleTd}>
                <span className={styles.scheduleDayName}>{WEEKDAY_LABELS[day.weekday]}</span>
              </td>
              <td className={styles.scheduleTd}>
                <input
                  type="checkbox"
                  className={styles.scheduleCheckbox}
                  checked={!day.is_closed}
                  onChange={(e) => setOpen(day.weekday, e.target.checked)}
                />
              </td>
              <td className={styles.scheduleTd}>
                <input
                  type="time"
                  className={styles.scheduleTimeInput}
                  value={day.is_closed ? "" : (toHM(day.opens_at) || "09:00")}
                  disabled={day.is_closed}
                  onChange={(e) => updateDay(day.weekday, { opens_at: toHMS(e.target.value) })}
                />
              </td>
              <td className={styles.scheduleTd}>
                <input
                  type="time"
                  className={styles.scheduleTimeInput}
                  value={day.is_closed ? "" : (toHM(day.closes_at) || "18:00")}
                  disabled={day.is_closed}
                  onChange={(e) => updateDay(day.weekday, { closes_at: toHMS(e.target.value) })}
                />
              </td>
              <td className={styles.scheduleTd}>
                <input
                  type="checkbox"
                  className={styles.scheduleCheckbox}
                  checked={!!day.has_break}
                  disabled={day.is_closed}
                  onChange={(e) => setBreak(day.weekday, e.target.checked)}
                />
              </td>
              <td className={styles.scheduleTd}>
                <input
                  type="time"
                  className={styles.scheduleTimeInput}
                  value={(!day.is_closed && day.has_break) ? (toHM(day.break_start) || "13:00") : ""}
                  disabled={day.is_closed || !day.has_break}
                  onChange={(e) => updateDay(day.weekday, { break_start: toHMS(e.target.value) })}
                />
              </td>
              <td className={styles.scheduleTd}>
                <input
                  type="time"
                  className={styles.scheduleTimeInput}
                  value={(!day.is_closed && day.has_break) ? (toHM(day.break_end) || "14:00") : ""}
                  disabled={day.is_closed || !day.has_break}
                  onChange={(e) => updateDay(day.weekday, { break_end: toHMS(e.target.value) })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className={styles.scheduleHint}>
        El descanso parte el día en dos: se atiende antes y después (comida, por ejemplo).
      </p>

      <div className={styles.actions}>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Guardando..." : "Guardar horario"}
        </button>
      </div>
    </div>
  );
};

export default ScheduleSection;
