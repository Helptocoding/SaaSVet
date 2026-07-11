import { describe, it, expect } from "vitest";
import { emergencyProtocol } from "./emergencyProtocol";

const MINIMAL = {
  arrived_at: "2026-07-11T10:00",
  triage_at: "2026-07-11T10:05",
  triage_level: "orange",
  chief_complaint: "Disnea aguda",
  stabilization_actions: "O2",
  discharge_status: "alta",
};

describe("emergencyProtocol", () => {
  it("label + initDraft por defecto", () => {
    expect(emergencyProtocol.label).toBe("Urgencia");
    const d = emergencyProtocol.initDraft(null);
    expect(d.airway_status).toBe("normal");
    expect(d.arrived_at).toBeTruthy();
  });

  it("validate exige el mínimo obligatorio", () => {
    expect(emergencyProtocol.validate({ airway_status: "normal" }).emergency).toBeTruthy();
  });

  it("validate ok con el mínimo completo", () => {
    expect(emergencyProtocol.validate(MINIMAL)).toEqual({});
  });

  it("validate rechaza triage anterior a la llegada", () => {
    const errs = emergencyProtocol.validate({ ...MINIMAL, triage_at: "2026-07-11T09:55" });
    expect(errs.emergency).toBeTruthy();
  });
});
