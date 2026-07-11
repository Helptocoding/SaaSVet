import { describe, it, expect } from "vitest";
import { vaccineProtocol } from "./vaccineProtocol";
import { todayISO } from "./vaccinePresets";

describe("vaccineProtocol.initDraft", () => {
  it("sin record: draft vacío con fecha de aplicación = hoy y refuerzo apagado", () => {
    const d = vaccineProtocol.initDraft(null);
    expect(d.vaccine_name).toBe("");
    expect(d.application_date).toBe(todayISO());
    expect(d.scheduleBooster).toBe(false);
    expect(d.next_due_date).toBeNull();
  });

  it("rehidrata desde record.consultation_draft.vaccine", () => {
    const slice = { vaccine_name: "Rabia", application_date: "2026-07-01", scheduleBooster: true };
    const d = vaccineProtocol.initDraft({ consultation_draft: { vaccine: slice } });
    expect(d).toEqual(slice);
  });
});

describe("vaccineProtocol.validate", () => {
  it("sin refuerzo programado: siempre válido", () => {
    expect(vaccineProtocol.validate({ scheduleBooster: false })).toEqual({});
  });

  it("refuerzo programado sin fecha: error", () => {
    const errs = vaccineProtocol.validate({ scheduleBooster: true, next_due_date: null });
    expect(errs.vaccine).toBeTruthy();
  });

  it("refuerzo no posterior a la aplicación: error", () => {
    const errs = vaccineProtocol.validate({
      scheduleBooster: true,
      application_date: "2026-07-01",
      next_due_date: "2026-07-01",
    });
    expect(errs.vaccine).toBeTruthy();
  });

  it("refuerzo posterior a la aplicación: válido", () => {
    const errs = vaccineProtocol.validate({
      scheduleBooster: true,
      application_date: "2026-07-01",
      next_due_date: "2027-07-01",
    });
    expect(errs).toEqual({});
  });
});
