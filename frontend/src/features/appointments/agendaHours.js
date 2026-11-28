// La agenda del personal con el horario de la clínica (ADR p70 D7, plan F2.2 y
// F2.3). Datos de `GET /api/appointments/agenda-config/`: horario semanal
// (`weekday` 1 = lunes … 7 = domingo), cierres vigentes y la duración habitual.
// Fechas locales de la clínica en ISO (`YYYY-MM-DD`) y horas `HH:MM[:SS]`: se
// comparan como texto, sin pasar por la zona del navegador.

export const DEFAULT_DURATION_MINUTES = 30;
const DEFAULT_RANGE = { slotMinTime: "07:00:00", slotMaxTime: "20:00:00" };

const WEEKDAY_PLURAL = ["", "lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos"];

const hm = (time) => (time ? String(time).slice(0, 5) : "");
const minutesOf = (time) => {
    const [h, m] = hm(time).split(":").map(Number);
    return h * 60 + m;
};
const pad = (n) => String(n).padStart(2, "0");
const clock = (minutes) => `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
const shortClock = (time) => hm(time).replace(/^0/, "");

/** Día de la semana (1 = lunes … 7 = domingo) de una fecha local ISO. */
export const isoWeekday = (isoDate) => {
    const day = new Date(`${isoDate}T00:00:00Z`).getUTCDay();
    return day === 0 ? 7 : day;
};

const nextIsoDate = (isoDate) => {
    const date = new Date(`${isoDate}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + 1);
    return date.toISOString().slice(0, 10);
};

/** Franjas de un día: una, o dos si tiene descanso. Día cerrado → ninguna. */
export function dayWindows(day) {
    if (!day || day.is_closed || !day.opens_at || !day.closes_at) return [];
    if (day.has_break && day.break_start && day.break_end) {
        return [[hm(day.opens_at), hm(day.break_start)], [hm(day.break_end), hm(day.closes_at)]];
    }
    return [[hm(day.opens_at), hm(day.closes_at)]];
}

/** `businessHours` de FullCalendar (0 = domingo). Sin horario cargado, sin sombreado. */
export function businessHoursFrom(schedule) {
    if (!Array.isArray(schedule)) return false;
    return schedule.flatMap((day) => dayWindows(day).map(([startTime, endTime]) => ({
        daysOfWeek: [day.weekday % 7], startTime, endTime,
    })));
}

/**
 * Horas visibles: de una hora antes de la primera apertura a una hora después
 * del último cierre, ampliadas para que ninguna cita cargada quede fuera de la
 * vista (el personal puede agendar fuera de horario). Sin horario, 07:00–20:00.
 */
export function visibleTimeRange(schedule, appointments = []) {
    const starts = [];
    const ends = [];
    for (const day of Array.isArray(schedule) ? schedule : []) {
        for (const [open, close] of dayWindows(day)) {
            starts.push(minutesOf(open));
            ends.push(minutesOf(close));
        }
    }
    if (!starts.length) return DEFAULT_RANGE;
    let min = Math.max(0, (Math.floor(Math.min(...starts) / 60) - 1) * 60);
    let max = Math.min(24 * 60, (Math.ceil(Math.max(...ends) / 60) + 1) * 60);
    for (const appointment of appointments) {
        if (appointment?.start_time) min = Math.min(min, Math.floor(minutesOf(appointment.start_time) / 60) * 60);
        if (appointment?.end_time) max = Math.max(max, Math.ceil(minutesOf(appointment.end_time) / 60) * 60);
    }
    return { slotMinTime: `${clock(min)}:00`, slotMaxTime: `${clock(Math.min(max, 24 * 60))}:00` };
}

/** Cierres como eventos de fondo, de las 00:00 del primer día a las 00:00 del siguiente al último. */
export function closureBackgroundEvents(closures) {
    return (closures || []).map((closure) => ({
        id: `closure-${closure.public_id}`,
        title: `Cerrado: ${closure.reason}`,
        start: `${closure.start_date}T00:00:00`,
        end: `${nextIsoDate(closure.end_date)}T00:00:00`,
        display: "background",
        editable: false,
        classNames: ["agenda-closure"],
        extendedProps: { closure },
    }));
}

/** El cierre vigente que cubre esa fecha, si hay. */
export const closureOn = (closures, isoDate) =>
    (closures || []).find((closure) => closure.start_date <= isoDate && isoDate <= closure.end_date) || null;

/**
 * Aviso si la cita cae en un día cerrado o fuera del horario (D7: se advierte,
 * no se bloquea). `null` si está dentro, o si no se sabe (horario sin cargar).
 */
export function scheduleWarning({ schedule, closures, date, start, end }) {
    if (!date) return null;
    const closure = closureOn(closures, date);
    if (closure) return `La clínica está cerrada ese día (${closure.reason}).`;
    if (!Array.isArray(schedule)) return null;
    const weekday = isoWeekday(date);
    const day = schedule.find((item) => item.weekday === weekday);
    if (!day) return null;
    const windows = dayWindows(day);
    if (!windows.length) return `La clínica no abre los ${WEEKDAY_PLURAL[weekday]}.`;
    const from = hm(start);
    const to = hm(end) || from;
    if (windows.some(([open, close]) => open <= from && to <= close)) return null;
    const hours = windows.map(([open, close]) => `${shortClock(open)}–${shortClock(close)}`).join(" y ");
    return `Ese horario queda fuera del horario de la clínica (${hours}).`;
}

/** Botones de hora sin horario cargado: 7:00 a 19:00, como antes. */
export const DEFAULT_HOURS = Array.from({ length: 13 }, (_, i) => i + 7);
const FALLBACK_START_HOUR = 9;

/** Horas en punto (0–23) en que alguna franja está abierta. */
function hoursInWindows(windows) {
    const hours = new Set();
    for (const [open, close] of windows) {
        for (let hour = 0; hour < 24; hour += 1) {
            const time = `${pad(hour)}:00`;
            if (open <= time && time < close) hours.add(hour);
        }
    }
    return [...hours].sort((a, b) => a - b);
}

/**
 * Horas que ofrece el formulario de una cita nueva para esa fecha: las del
 * horario de ese día (sin el descanso). Si ese día no se atiende (día cerrado o
 * cierre) o no hay fecha, las de toda la semana: el personal puede agendar una
 * urgencia, con el aviso de `scheduleWarning`. Sin horario, 7:00–19:00. La hora
 * ya elegida siempre aparece, aunque quede fuera.
 */
export function hourOptions({ schedule, closures, date, selectedHour }) {
    let hours = DEFAULT_HOURS;
    if (Array.isArray(schedule)) {
        const day = date && !closureOn(closures, date)
            ? schedule.find((item) => item.weekday === isoWeekday(date)) : null;
        hours = hoursInWindows(dayWindows(day));
        if (!hours.length) hours = hoursInWindows(schedule.flatMap(dayWindows));
        if (!hours.length) hours = DEFAULT_HOURS;
    }
    if (Number.isInteger(selectedHour) && !hours.includes(selectedHour)) {
        hours = [...hours, selectedHour].sort((a, b) => a - b);
    }
    return hours;
}

/**
 * Botones de inicio del formulario: las horas en punto de `hourOptions` y, si
 * la elegida no es en punto (un clic en la casilla de las 10:30), también esa,
 * en su lugar. `[{hour, minute, label}]` en orden.
 */
export function startChoices({ schedule, closures, date, hour, minute = 0 }) {
    const onTheHour = !minute;
    const hours = hourOptions({ schedule, closures, date, selectedHour: onTheHour ? hour : undefined });
    const choices = hours.map((h) => ({ hour: h, minute: 0 }));
    if (!onTheHour && Number.isInteger(hour)) choices.push({ hour, minute });
    return choices
        .sort((a, b) => a.hour * 60 + a.minute - (b.hour * 60 + b.minute))
        .map((choice) => ({ ...choice, label: `${pad(choice.hour)}:${pad(choice.minute)}` }));
}

/** Hora inicial de una cita nueva ese día: la primera que ofrece el formulario; 9 sin horario. */
export function defaultHour({ schedule, closures, date }) {
    if (!Array.isArray(schedule)) return FALLBACK_START_HOUR;
    return hourOptions({ schedule, closures, date })[0] ?? FALLBACK_START_HOUR;
}

/** Hora de fin a partir del inicio y la duración; no pasa de las 23:59. */
export function endTimeFor(start, minutes = DEFAULT_DURATION_MINUTES) {
    const duration = Number(minutes) > 0 ? Number(minutes) : DEFAULT_DURATION_MINUTES;
    return clock(Math.min(minutesOf(start) + duration, 24 * 60 - 1));
}
