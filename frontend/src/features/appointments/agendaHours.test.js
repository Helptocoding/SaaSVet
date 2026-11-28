import { describe, expect, it } from "vitest";
import {
    DEFAULT_HOURS, businessHoursFrom, closureBackgroundEvents, dayWindows, defaultHour, endTimeFor,
    hourOptions, isoWeekday, scheduleWarning, startChoices, visibleTimeRange,
} from "./agendaHours";

const day = (weekday, overrides = {}) => ({
    weekday, is_closed: false, opens_at: "09:00:00", closes_at: "18:00:00",
    has_break: false, break_start: null, break_end: null, ...overrides,
});
const closed = (weekday) => day(weekday, { is_closed: true, opens_at: null, closes_at: null });

// L–V 9–18 (miércoles con descanso 14–15), sábado 9–14, domingo cerrado.
const WEEK = [
    day(1), day(2), day(3, { has_break: true, break_start: "14:00:00", break_end: "15:00:00" }),
    day(4), day(5), day(6, { closes_at: "14:00:00" }), closed(7),
];
const CLOSURES = [{ public_id: "c1", start_date: "2026-12-24", end_date: "2026-12-25", reason: "Navidad" }];

describe("agendaHours (ADR p70 D7, plan F2.2)", () => {
    it("isoWeekday no depende de la zona del navegador", () => {
        expect(isoWeekday("2026-11-30")).toBe(1); // lunes
        expect(isoWeekday("2026-12-06")).toBe(7); // domingo
    });

    it("un día con descanso son dos franjas; uno cerrado, ninguna", () => {
        expect(dayWindows(WEEK[2])).toEqual([["09:00", "14:00"], ["15:00", "18:00"]]);
        expect(dayWindows(WEEK[6])).toEqual([]);
    });

    it("businessHours en el formato de FullCalendar (domingo = 0)", () => {
        const hours = businessHoursFrom(WEEK);
        expect(hours).toContainEqual({ daysOfWeek: [1], startTime: "09:00", endTime: "18:00" });
        expect(hours).toContainEqual({ daysOfWeek: [3], startTime: "15:00", endTime: "18:00" });
        expect(hours).toContainEqual({ daysOfWeek: [6], startTime: "09:00", endTime: "14:00" });
        expect(hours.some((h) => h.daysOfWeek[0] === 0)).toBe(false);
        expect(businessHoursFrom(null)).toBe(false);
    });

    it("horas visibles: una hora de margen, y ninguna cita queda fuera", () => {
        expect(visibleTimeRange(WEEK)).toEqual({ slotMinTime: "08:00:00", slotMaxTime: "19:00:00" });
        expect(visibleTimeRange([day(1, { opens_at: "09:30:00", closes_at: "18:30:00" })]))
            .toEqual({ slotMinTime: "08:00:00", slotMaxTime: "20:00:00" });
        expect(visibleTimeRange(WEEK, [{ start_time: "06:15:00", end_time: "21:10:00" }]))
            .toEqual({ slotMinTime: "06:00:00", slotMaxTime: "22:00:00" });
        expect(visibleTimeRange([day(1, { opens_at: "00:00:00", closes_at: "23:30:00" })]))
            .toEqual({ slotMinTime: "00:00:00", slotMaxTime: "24:00:00" });
    });

    it("sin horario (o todo cerrado) se queda en 07:00–20:00", () => {
        expect(visibleTimeRange(null)).toEqual({ slotMinTime: "07:00:00", slotMaxTime: "20:00:00" });
        expect(visibleTimeRange([closed(1)])).toEqual({ slotMinTime: "07:00:00", slotMaxTime: "20:00:00" });
    });

    it("cierres como fondo que cubre los días completos", () => {
        expect(closureBackgroundEvents(CLOSURES)).toEqual([expect.objectContaining({
            start: "2026-12-24T00:00:00", end: "2026-12-26T00:00:00",
            display: "background", editable: false, title: "Cerrado: Navidad",
        })]);
        expect(closureBackgroundEvents([{ ...CLOSURES[0], end_date: "2026-12-31" }])[0].end)
            .toBe("2027-01-01T00:00:00");
    });

    describe("scheduleWarning", () => {
        const warn = (date, start, end) => scheduleWarning({ schedule: WEEK, closures: CLOSURES, date, start, end });

        it("dentro del horario no avisa", () => {
            expect(warn("2026-11-30", "09:00", "09:30")).toBeNull();
            expect(warn("2026-11-30", "17:30", "18:00")).toBeNull();
            expect(warn("2026-12-02", "15:00", "15:45")).toBeNull();
        });

        it("fuera del horario o en el descanso avisa con las horas del día", () => {
            expect(warn("2026-11-30", "08:00", "08:30"))
                .toBe("Ese horario queda fuera del horario de la clínica (9:00–18:00).");
            expect(warn("2026-11-30", "17:45", "18:15")).not.toBeNull();
            expect(warn("2026-12-02", "13:45", "14:15"))
                .toBe("Ese horario queda fuera del horario de la clínica (9:00–14:00 y 15:00–18:00).");
        });

        it("día de la semana cerrado y cierre excepcional", () => {
            expect(warn("2026-12-06", "10:00", "10:30")).toBe("La clínica no abre los domingos.");
            expect(warn("2026-12-24", "10:00", "10:30")).toBe("La clínica está cerrada ese día (Navidad).");
        });

        it("sin horario cargado no inventa un aviso, pero los cierres sí cuentan", () => {
            expect(scheduleWarning({ schedule: null, closures: [], date: "2026-11-30", start: "03:00" })).toBeNull();
            expect(scheduleWarning({ schedule: null, closures: CLOSURES, date: "2026-12-25", start: "10:00" }))
                .toMatch(/cerrada ese día/);
        });
    });

    it("hora de fin con la duración habitual, sin pasar de las 23:59", () => {
        expect(endTimeFor("09:00", 45)).toBe("09:45");
        expect(endTimeFor("09:30", 90)).toBe("11:00");
        expect(endTimeFor("23:30", 60)).toBe("23:59");
        expect(endTimeFor("10:00", undefined)).toBe("10:30");
        expect(endTimeFor("10:00", 0)).toBe("10:30");
    });

    describe("hourOptions y defaultHour (botones de hora del formulario)", () => {
        const opts = (date, selectedHour) => hourOptions({ schedule: WEEK, closures: CLOSURES, date, selectedHour });

        it("las horas del día según su horario", () => {
            expect(opts("2026-11-30")).toEqual([9, 10, 11, 12, 13, 14, 15, 16, 17]); // lunes 9–18
            expect(opts("2026-12-05")).toEqual([9, 10, 11, 12, 13]); // sábado 9–14
        });

        it("el descanso no se ofrece", () => {
            expect(opts("2026-12-02")).toEqual([9, 10, 11, 12, 13, 15, 16, 17]); // miércoles, descanso 14–15
        });

        it("una apertura a media hora empieza en la siguiente hora en punto", () => {
            const schedule = [day(1, { opens_at: "09:30:00", closes_at: "12:00:00" })];
            expect(hourOptions({ schedule, closures: [], date: "2026-11-30" })).toEqual([10, 11]);
        });

        it("un día que no se atiende ofrece las horas de la semana", () => {
            const week = [9, 10, 11, 12, 13, 14, 15, 16, 17];
            expect(opts("2026-12-06")).toEqual(week); // domingo cerrado
            expect(opts("2026-12-24")).toEqual(week); // cierre (jueves)
            expect(opts(null)).toEqual(week); // sin fecha elegida
        });

        it("la hora elegida siempre aparece, aunque quede fuera", () => {
            expect(opts("2026-11-30", 20)).toEqual([9, 10, 11, 12, 13, 14, 15, 16, 17, 20]);
            expect(opts("2026-11-30", 7)[0]).toBe(7);
            expect(opts("2026-11-30", 10)).toHaveLength(9);
        });

        it("sin horario cargado, 7:00–19:00 como antes", () => {
            expect(hourOptions({ schedule: null, closures: [], date: "2026-11-30" })).toEqual(DEFAULT_HOURS);
            expect(DEFAULT_HOURS[0]).toBe(7);
            expect(DEFAULT_HOURS.at(-1)).toBe(19);
            expect(hourOptions({ schedule: [closed(1), closed(2)], closures: [], date: "2026-11-30" }))
                .toEqual(DEFAULT_HOURS);
        });

        it("la hora inicial es la primera apertura del día; 9 sin horario", () => {
            const late = WEEK.map((item) => (item.is_closed ? item : { ...item, opens_at: "11:00:00" }));
            expect(defaultHour({ schedule: late, closures: [], date: "2026-11-30" })).toBe(11);
            expect(defaultHour({ schedule: WEEK, closures: CLOSURES, date: "2026-12-06" })).toBe(9);
            expect(defaultHour({ schedule: null, closures: [], date: "2026-11-30" })).toBe(9);
        });
    });

    describe("startChoices (media hora)", () => {
        const labels = (args) => startChoices({ schedule: WEEK, closures: CLOSURES, date: "2026-12-05", ...args })
            .map((choice) => choice.label);

        it("en punto: solo las horas del día", () => {
            expect(labels({ hour: 10, minute: 0 })).toEqual(["09:00", "10:00", "11:00", "12:00", "13:00"]);
        });

        it("la media hora elegida aparece en su lugar, sin quitar la hora en punto", () => {
            expect(labels({ hour: 10, minute: 30 }))
                .toEqual(["09:00", "10:00", "10:30", "11:00", "12:00", "13:00"]);
        });

        it("una media hora fuera del horario también aparece", () => {
            expect(labels({ hour: 18, minute: 30 }).at(-1)).toBe("18:30");
            expect(labels({ hour: 18, minute: 30 })).not.toContain("18:00");
        });

        it("cada opción trae hora y minutos", () => {
            expect(startChoices({ schedule: null, closures: [], date: "2026-12-05", hour: 9, minute: 30 }))
                .toContainEqual({ hour: 9, minute: 30, label: "09:30" });
        });
    });
});
