// Ausencias por días completos (ADR p67). Las fechas son locales de la clínica
// en formato ISO (`YYYY-MM-DD`), la misma unidad que la fecha de una cita: se
// comparan como texto y se formatean sin pasar por la zona del navegador.

export const ABSENCE_KINDS = [
    ["vacation", "Vacaciones"],
    ["training", "Capacitación"],
    ["leave", "Permiso"],
    ["other", "Otro"],
];

export const absenceKindLabel = (kind) =>
    (ABSENCE_KINDS.find(([value]) => value === kind) || [null, "Ausencia"])[1];

/** ¿Alguna de estas ausencias cubre ese día? */
export const isAbsentOn = (absences, isoDate) =>
    Boolean(isoDate) && (absences || []).some(
        (absence) => absence.start_date <= isoDate && isoDate <= absence.end_date,
    );

const DATE_FORMAT = new Intl.DateTimeFormat("es-MX", {
    weekday: "short", day: "numeric", month: "short", timeZone: "UTC",
});

/** «lun 24 nov» para una fecha local ISO, sin desplazarla por la zona del navegador. */
export const formatLocalDate = (isoDate) =>
    isoDate ? DATE_FORMAT.format(new Date(`${isoDate}T00:00:00Z`)) : "";

/** «lun 24 nov» o «lun 24 nov – mié 26 nov». */
export const formatAbsenceRange = (startDate, endDate) =>
    startDate === endDate
        ? formatLocalDate(startDate)
        : `${formatLocalDate(startDate)} – ${formatLocalDate(endDate)}`;

/** Ausencias agrupadas por PK del integrante (el `veterinarian` de una cita). */
export const absencesByMember = (absences) => {
    const map = new Map();
    for (const absence of absences || []) {
        if (!map.has(absence.member)) map.set(absence.member, []);
        map.get(absence.member).push(absence);
    }
    return map;
};

/** Etiqueta de un veterinario en un selector de la agenda para ese día. */
export const vetOptionLabel = (member, isoDate) => {
    const name = `${member.first_name} ${member.last_name}`.trim();
    return isAbsentOn(member.absences, isoDate) ? `${name} · ausente` : name;
};

/** Hoy en la zona de la clínica, como fecha local ISO (`YYYY-MM-DD`). */
export const orgTodayIso = (tz, now = new Date()) =>
    new Intl.DateTimeFormat("en-CA", {
        timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    }).format(now);
