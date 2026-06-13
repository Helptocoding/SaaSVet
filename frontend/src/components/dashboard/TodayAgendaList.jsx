import { useMemo, useState } from "react";
import AppointmentQuickModal from "./AppointmentQuickModal";
import AgendaDateStrip from "./AgendaDateStrip";
import StatusBadge from "../StatusBadge";
import { Icon } from "../icons";
import { useDayAppointments } from "../../hooks/useDayAppointments";

/**
 * Agenda del dashboard — mini agenda operativa con navegación por día.
 *
 * Dueño de selectedDate, date strip, fetch por día, conteo y empty state.
 * Solo presentación + composición; las acciones viven en AppointmentQuickModal
 * y los estados en StatusBadge. Fuente: GET appointments/?date= vía
 * useDayAppointments (sin backend nuevo).
 */

const WEEKDAYS_SHORT = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const MONTHS_SHORT = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

function sameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}
function fmtISO(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function minutesFromHHMM(t) {
  const [h, m] = (t || "").split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

export default function TodayAgendaList() {
  const today = useMemo(() => {
    const n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }, []);

  const [selectedDate, setSelectedDate] = useState(today);
  const [clickedApptId, setClickedApptId] = useState(null);

  const isoDate = fmtISO(selectedDate);
  const { appts, loading } = useDayAppointments(isoDate);

  const isToday = sameDay(selectedDate, today);
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();

  const count = appts.length;
  const countLabel = `${WEEKDAYS_SHORT[selectedDate.getDay()]} ${selectedDate.getDate()} ${
    MONTHS_SHORT[selectedDate.getMonth()]
  } · ${count} ${count === 1 ? "cita" : "citas"}`;

  return (
    <div className="tagenda">
      <div className="tagenda-head">
        <h3 className="tagenda-title">Agenda</h3>
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={() => setSelectedDate(today)}
          disabled={isToday}
        >
          Hoy
        </button>
      </div>

      <AgendaDateStrip
        key={isoDate}
        selectedDate={selectedDate}
        onSelect={setSelectedDate}
        today={today}
      />

      <div className="tagenda-count">{countLabel}</div>

      {loading && !appts.length ? (
        <p className="dsp-empty">Cargando…</p>
      ) : !appts.length ? (
        <div className="empty-state">
          <p className="empty-state-title">No hay citas para este día</p>
          <p className="empty-state-sub">Selecciona otro día en el calendario.</p>
        </div>
      ) : (
        <div className="tagenda-list">
          {appts.map((a) => {
            const time = (a.start_time || "").slice(0, 5);
            const isNow = isToday && a.status === "in_progress";
            const startMin = minutesFromHHMM(time);
            const pending = a.status === "scheduled" || a.status === "confirmed";
            const lateMin =
              isToday && pending && startMin != null && nowMin > startMin
                ? nowMin - startMin
                : 0;
            const initial = (a.pet_name || "?").charAt(0).toUpperCase();

            return (
              <div key={a.public_id} className="appointment-row">
                <div className="appointment-time">
                  <span className="appointment-time-val">{time}</span>
                  {isNow && <span className="appointment-now-tag">Ahora</span>}
                </div>

                <div
                  className={`appointment-card${isNow ? " appointment-card-now" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => setClickedApptId(a.public_id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setClickedApptId(a.public_id);
                    }
                  }}
                >
                  <div className="appointment-avatar" aria-hidden="true">
                    {initial}
                  </div>

                  <div className="appointment-info">
                    <div className="appointment-title">
                      {a.walk_in && (
                        <span className="appointment-walkin" title="Walk-in">
                          ●{" "}
                        </span>
                      )}
                      <span className="appointment-pet">
                        {a.pet_name || "Paciente"}
                      </span>
                      {a.owner_name && (
                        <span className="appointment-owner"> · {a.owner_name}</span>
                      )}
                    </div>
                    {a.reason && (
                      <div className="appointment-reason">{a.reason}</div>
                    )}
                    {lateMin > 0 && (
                      <div className="appointment-late">
                        <Icon.Clock s={11} /> Pendiente desde hace {lateMin} min
                      </div>
                    )}
                  </div>

                  <div className="appointment-status">
                    <StatusBadge status={a.status} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {clickedApptId && (
        <AppointmentQuickModal
          publicId={clickedApptId}
          onClose={() => setClickedApptId(null)}
        />
      )}
    </div>
  );
}
