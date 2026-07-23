import { useState } from "react";
import { toast } from "sonner";
import { replaceSchedule } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import SettingsPanel from "./SettingsPanel";
import styles from "./config.module.css";

const WEEKDAY_LABELS = {
  1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
  5: "Viernes", 6: "Sábado", 7: "Domingo",
};

const toHM = (t) => (t ? t.slice(0, 5) : "");
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
      const req = replaceSchedule(schedule);
      toast.promise(req, { loading: "Guardando...", success: "Horario guardado", error: (e) => apiError(e) });
      const updated = await req;   // sonner: await la promesa REAL, no toast.promise
      if (Array.isArray(updated)) onScheduleChange(updated);
    } catch {
    } finally {
      setSaving(false);
    }
  };

  const timeCell = (day, field, fallback, enabled) => (
    <input
      type="time"
      className={styles.scheduleTimeInput}
      value={enabled ? (toHM(day[field]) || fallback) : ""}
      disabled={!enabled}
      onChange={(e) => updateDay(day.weekday, { [field]: toHMS(e.target.value) })}
    />
  );

  return (
    <SettingsPanel
      title="Horarios"
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
            return (
              <tr key={day.weekday} className={day.is_closed ? styles.scheduleRowClosed : ""}>
                <td className={styles.scheduleTd}>
                  <span className={styles.scheduleDayName}>{WEEKDAY_LABELS[day.weekday]}</span>
                </td>
                <td className={styles.scheduleTd}>
                  <input type="checkbox" className={styles.scheduleCheckbox}
                    checked={open} onChange={(e) => setOpen(day.weekday, e.target.checked)} />
                </td>
                <td className={styles.scheduleTd}>{timeCell(day, "opens_at", "09:00", open)}</td>
                <td className={styles.scheduleTd}>{timeCell(day, "closes_at", "18:00", open)}</td>
                <td className={styles.scheduleTd}>
                  <input type="checkbox" className={styles.scheduleCheckbox}
                    checked={!!day.has_break} disabled={!open}
                    onChange={(e) => setBreak(day.weekday, e.target.checked)} />
                </td>
                <td className={styles.scheduleTd}>{timeCell(day, "break_start", "13:00", brk)}</td>
                <td className={styles.scheduleTd}>{timeCell(day, "break_end", "14:00", brk)}</td>
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
