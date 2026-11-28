import { describe, expect, it } from "vitest";
import { describeConfigEvent, scheduleDayLabel } from "./history";

const nbsp = (text) => text.replace(/[\u00a0\u202f]/g, " ");

describe("describeConfigEvent (ADR p70 D9)", () => {
    it("datos de la clínica: campo, antes y después", () => {
        const { title, details } = describeConfigEvent({
            kind: "clinic_updated",
            changes: { phone: ["", "5512345678"], arrival_instructions: ["a", "b"] },
        });
        expect(title).toBe("Editó los datos de la clínica");
        expect(details).toEqual([
            "Teléfono: sin capturar → 5512345678",
            "Indicaciones para llegar: cambió",
        ]);
    });

    it("zona horaria con nombres para personas", () => {
        const { details } = describeConfigEvent({
            kind: "timezone_changed",
            changes: { timezone: ["America/Mexico_City", "America/Cancun"] },
        });
        expect(details[0]).toMatch(/Ciudad de México → Sureste — Cancún/);
    });

    it("reglas: interruptores y plazos", () => {
        const { title, details } = describeConfigEvent({
            kind: "rules_updated",
            changes: { require_open_cash_session: [false, true], credit_default_days: [30, 45] },
        });
        expect(title).toBe("Cambió las reglas de operación");
        expect(details).toEqual([
            "Caja abierta obligatoria: desactivada → activada",
            "Plazo de crédito: 30 días → 45 días",
        ]);
    });

    it("horario: solo los días que cambiaron, en orden", () => {
        const open = { is_closed: false, opens_at: "09:00", closes_at: "18:00", has_break: false };
        const { details } = describeConfigEvent({
            kind: "schedule_replaced",
            changes: {
                weekday_7: [{ is_closed: true }, open],
                weekday_3: [open, { ...open, has_break: true, break_start: "14:00", break_end: "15:00" }],
            },
        });
        expect(details).toEqual([
            "Miércoles: 09:00–18:00 → 09:00–18:00, descanso 14:00–15:00",
            "Domingo: Cerrado → 09:00–18:00",
        ]);
    });

    it("servicios: nombre del servicio y precio con formato", () => {
        const subject = { type: "service", name: "Consulta general" };
        const created = describeConfigEvent({
            kind: "service_created", subject, changes: { base_price: [null, "350.00"] },
        });
        expect(created.title).toBe("Creó el servicio «Consulta general»");
        expect(nbsp(created.details[0])).toBe("Precio sin IVA: $350.00");

        const updated = describeConfigEvent({
            kind: "service_updated", subject, changes: { base_price: ["350.00", "400.00"] },
        });
        expect(nbsp(updated.details[0])).toBe("Precio sin IVA: $350.00 → $400.00");

        expect(describeConfigEvent({ kind: "service_deactivated", subject, changes: { is_active: [true, false] } }))
            .toEqual({ title: "Desactivó el servicio «Consulta general»", details: [] });
        expect(describeConfigEvent({ kind: "service_deleted", subject }).title)
            .toBe("Eliminó el servicio «Consulta general»");
    });

    it("un tipo nuevo usa la etiqueta del backend", () => {
        expect(describeConfigEvent({ kind: "something_new", kind_label: "Algo nuevo" }))
            .toEqual({ title: "Algo nuevo", details: [] });
    });

    it("día sin datos no inventa un horario", () => {
        expect(scheduleDayLabel(null)).toBe("sin capturar");
    });

    it("cierres excepcionales: rango y motivo (ADR p70 D6)", () => {
        const subject = { type: "closure", start_date: "2026-12-24", end_date: "2026-12-26" };
        const added = describeConfigEvent({
            kind: "closure_added",
            subject,
            changes: { start_date: [null, "2026-12-24"], end_date: [null, "2026-12-26"], reason: [null, "Navidad"] },
        });
        expect(nbsp(added.title)).toMatch(/^Registró un cierre: .*24 de dic.*26 de dic/);
        expect(added.details).toEqual(["Motivo: Navidad"]);
        const cancelled = describeConfigEvent({
            kind: "closure_cancelled",
            subject: { ...subject, reason: "Navidad" },
            changes: { cancelled: [false, true] },
        });
        expect(nbsp(cancelled.title)).toMatch(/^Canceló el cierre: /);
        expect(cancelled.details).toEqual(["Motivo: Navidad"]);
    });
});
