export const DEFAULT_ORG_TIMEZONE = "America/Mexico_City";

const MS_PER_DAY = 86400000;
const timeZoneValidity = new Map();

const toUtcIso = (value) => {
    if (!value) return null;
    if (value instanceof Date) return value.toISOString();
    if (typeof value === "string" && (value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value))) {
        return value;
    }
    if (typeof value === "string") return `${value}Z`;
    return null;
};

const toDate = (value) => {
    const normalized = toUtcIso(value);
    if (!normalized) return null;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
};

const validTimeZone = (candidate) => {
    if (!candidate || typeof candidate !== "string") return false;
    if (timeZoneValidity.has(candidate)) return timeZoneValidity.get(candidate);
    let valid = true;
    try {
        new Intl.DateTimeFormat("es-MX", { timeZone: candidate }).format(0);
    } catch {
        valid = false;
    }
    timeZoneValidity.set(candidate, valid);
    return valid;
};

const safeTimeZone = (candidate) => (
    validTimeZone(candidate) ? candidate : DEFAULT_ORG_TIMEZONE
);

const localDayParts = (value, timeZone) => {
    const date = toDate(value);
    if (!date) return null;
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: safeTimeZone(timeZone),
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
    const year = Number(values.year);
    const month = Number(values.month);
    const day = Number(values.day);
    return {
        year,
        month,
        day,
        key: `${values.year}-${values.month}-${values.day}`,
        ordinal: Date.UTC(year, month - 1, day) / MS_PER_DAY,
    };
};

export const orgTz = (user) => safeTimeZone(user?.organization_timezone);

export const dayLabelOrg = (isoUtc, tz, now = new Date()) => {
    const target = localDayParts(isoUtc, tz);
    const today = localDayParts(now, tz);
    if (!target || !today) return "";
    const dayDiff = today.ordinal - target.ordinal;
    if (dayDiff === 0) return "Hoy";
    if (dayDiff === 1) return "Ayer";
    return new Intl.DateTimeFormat("es-MX", {
        timeZone: safeTimeZone(tz),
        day: "numeric",
        month: "short",
        ...(target.year !== today.year ? { year: "numeric" } : {}),
    }).format(toDate(isoUtc)).replace(/\./g, "");
};

export const clockTimeOrg = (isoUtc, tz) => {
    const date = toDate(isoUtc);
    if (!date) return "";
    return new Intl.DateTimeFormat("es-MX", {
        timeZone: safeTimeZone(tz),
        hour: "2-digit",
        minute: "2-digit",
    }).format(date);
};

export const fmtTimeOrg = (isoUtc, tz, now = new Date()) => {
    const date = toDate(isoUtc);
    if (!date) return "";
    const target = localDayParts(date, tz);
    const today = localDayParts(now, tz);
    if (target?.key === today?.key) return clockTimeOrg(date, tz);
    return new Intl.DateTimeFormat("es-MX", {
        timeZone: safeTimeZone(tz),
        day: "2-digit",
        month: "short",
    }).format(date).replace(/\./g, "");
};

export const relativeTimeOrg = (isoUtc, tz, now = new Date()) => {
    const date = toDate(isoUtc);
    const reference = toDate(now);
    if (!date || !reference) return "";
    const timeZone = safeTimeZone(tz);
    const seconds = Math.round((date.getTime() - reference.getTime()) / 1000);
    const future = seconds > 0;
    const absolute = Math.abs(seconds);
    if (absolute < 30) return "ahora";
    const format = (value, unit) => future ? `en ${value} ${unit}` : `hace ${value} ${unit}`;
    if (absolute < 60) return format(absolute, "s");
    if (absolute < 3600) return format(Math.round(absolute / 60), "min");
    if (absolute < 86400) return format(Math.round(absolute / 3600), "h");
    const targetDay = localDayParts(date, timeZone);
    const referenceDay = localDayParts(reference, timeZone);
    return format(Math.max(1, Math.abs(targetDay.ordinal - referenceDay.ordinal)), "d");
};

export const groupMessagesByDay = (messages, tz, now = new Date()) => {
    if (!Array.isArray(messages) || messages.length === 0) return [];
    const groups = [];
    for (const message of messages) {
        const day = localDayParts(message?.created_at, tz);
        if (!day) continue;
        const last = groups[groups.length - 1];
        if (last?.key === day.key) {
            last.messages.push(message);
        } else {
            groups.push({
                key: day.key,
                label: dayLabelOrg(message.created_at, tz, now),
                messages: [message],
            });
        }
    }
    return groups;
};

export const formatDateTime = (isoUtc, tz = "UTC", locale = "es-ES") => {
    const normalized = toUtcIso(isoUtc);
    if (!normalized) return "";
    const dt = new Date(normalized);
    if (Number.isNaN(dt.getTime())) return "";

    return new Intl.DateTimeFormat(locale, {
        timeZone: safeTimeZone(tz),
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    }).format(dt);
};

export const formatDate = (isoUtc, tz = "UTC", locale = "es-ES") => {
    const normalized = toUtcIso(isoUtc);
    if (!normalized) return "";
    const dt = new Date(normalized);
    if (Number.isNaN(dt.getTime())) return "";

    return new Intl.DateTimeFormat(locale, {
        timeZone: safeTimeZone(tz),
        year: "numeric",
        month: "long",
        day: "numeric",
    }).format(dt);
};
