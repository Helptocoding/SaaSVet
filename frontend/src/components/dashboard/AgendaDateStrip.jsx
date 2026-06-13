import { useState } from "react";
import { Icon } from "../icons";

// Tira de navegación semanal. Las flechas avanzan/retroceden SEMANAS (no meses);
// el mes/año es solo etiqueta de contexto. El estado de selección vive en el
// padre (TodayAgendaList); este componente solo gestiona la ventana visible.
//
// El padre monta con key={selectedDate ISO}: al cambiar la selección desde
// fuera (chip o botón "Hoy") el componente remonta y la ventana se reencuadra
// a la semana de la selección. Navegar con flechas NO cambia selectedDate →
// sin remonte, la ventana persiste independiente de la selección.

const WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MONTHS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

function startOfWeek(d) {
  // Lunes como primer día.
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (x.getDay() + 6) % 7; // 0 = lunes
  x.setDate(x.getDate() - dow);
  return x;
}
function addDays(d, n) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() + n);
  return x;
}
function sameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export default function AgendaDateStrip({ selectedDate, onSelect, today }) {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(selectedDate));

  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const mid = days[3]; // punto medio de la semana → mes/año estable
  const monthLabel = `${MONTHS[mid.getMonth()]} ${mid.getFullYear()}`;

  return (
    <div className="agenda-strip">
      <div className="agenda-strip-month">{monthLabel}</div>

      <div className="agenda-strip-nav">
        <button
          type="button"
          className="agenda-strip-arrow"
          onClick={() => setWeekStart(addDays(weekStart, -7))}
          aria-label="Semana anterior"
        >
          <Icon.ChevronLeft s={16} />
        </button>

        <div className="agenda-strip-days">
          {days.map((d, i) => {
            const isSel = sameDay(d, selectedDate);
            const isToday = sameDay(d, today);
            return (
              <button
                key={i}
                type="button"
                className={`agenda-day${isSel ? " agenda-day-sel" : ""}${
                  isToday ? " agenda-day-today" : ""
                }`}
                onClick={() => onSelect(d)}
              >
                <span className="agenda-day-dow">{WEEKDAYS[i]}</span>
                <span className="agenda-day-num">{d.getDate()}</span>
              </button>
            );
          })}
        </div>

        <button
          type="button"
          className="agenda-strip-arrow"
          onClick={() => setWeekStart(addDays(weekStart, 7))}
          aria-label="Semana siguiente"
        >
          <Icon.ChevronRight s={16} />
        </button>
      </div>
    </div>
  );
}
