import { describe, expect, it } from "vitest";
import { changedFields, dirtySections, discardSection, scheduleChanged } from "./drafts";
import { SCHEDULE_MESSAGES, validateDay, validateWeek } from "./schedule";

const day = (weekday, extra = {}) => ({
    weekday, is_closed: false, opens_at: "09:00:00", closes_at: "18:00:00",
    has_break: false, break_start: null, break_end: null, ...extra,
});

describe("changedFields (plan F1.3, C16)", () => {
    it("solo los campos que cambiaron, y vacío equivale a nulo", () => {
        const saved = { phone: "", email: null, city: "Mérida" };
        const draft = { phone: null, email: "", city: "Cancún" };
        expect(changedFields(saved, draft, ["phone", "email", "city"])).toEqual({ city: "Cancún" });
    });
});

describe("scheduleChanged", () => {
    it("ignora segundos y detecta un descanso nuevo", () => {
        expect(scheduleChanged([day(1)], [day(1, { opens_at: "09:00" })])).toBe(false);
        expect(scheduleChanged([day(1)], [day(1, { has_break: true, break_start: "13:00", break_end: "14:00" })]))
            .toBe(true);
    });
});

describe("dirtySections y discardSection", () => {
    const saved = {
        org: { phone: "5512345678" },
        settings: { require_open_cash_session: false, require_confirmation_before_start: false },
        schedule: [day(1)],
    };

    it("marca cada apartado por separado", () => {
        const draft = { ...saved, settings: { ...saved.settings, require_open_cash_session: true } };
        expect([...dirtySections(saved, draft)]).toEqual(["billing"]);
    });

    it("descartar un apartado no toca el borrador de otro", () => {
        const draft = {
            ...saved,
            settings: { require_open_cash_session: true, require_confirmation_before_start: true },
        };
        const after = discardSection(saved, draft, "billing");
        expect(after.settings).toEqual({ require_open_cash_session: false, require_confirmation_before_start: true });
        expect([...dirtySections(saved, after)]).toEqual(["care"]);
    });

    it("sin datos cargados no hay nada sin guardar", () => {
        expect(dirtySections(null, null).size).toBe(0);
    });
});

describe("validateDay (mismos mensajes que el servidor)", () => {
    it("acepta un día cerrado y uno bien formado", () => {
        expect(validateDay({ weekday: 7, is_closed: true })).toBeNull();
        expect(validateDay(day(1, { has_break: true, break_start: "13:00", break_end: "14:00" }))).toBeNull();
    });

    it.each([
        [{ opens_at: null }, SCHEDULE_MESSAGES.hoursRequired],
        [{ opens_at: "18:00", closes_at: "09:00" }, SCHEDULE_MESSAGES.hoursOrder],
        [{ has_break: true, break_start: null, break_end: "14:00" }, SCHEDULE_MESSAGES.breakRequired],
        [{ has_break: true, break_start: "08:00", break_end: "10:00" }, SCHEDULE_MESSAGES.breakInside],
    ])("%o → %s", (patch, message) => {
        expect(validateDay(day(3, patch))).toBe(message);
    });

    it("validateWeek devuelve solo los días con problema", () => {
        expect(validateWeek([day(1), day(2, { closes_at: "08:00" })]))
            .toEqual({ 2: SCHEDULE_MESSAGES.hoursOrder });
    });
});
