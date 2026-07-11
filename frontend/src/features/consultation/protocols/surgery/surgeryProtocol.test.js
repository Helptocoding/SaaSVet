import { describe, it, expect } from "vitest";
import { surgeryProtocol } from "./surgeryProtocol";

describe("surgeryProtocol", () => {
  it("label + initDraft por defecto", () => {
    expect(surgeryProtocol.label).toBe("Cirugía");
    const d = surgeryProtocol.initDraft(null);
    expect(d).toMatchObject({ surgery_type: "", complications: "Ninguna" });
  });

  it("initDraft rehidrata desde consultation_draft.surgery", () => {
    const record = { consultation_draft: { surgery: { surgery_type: "urgencia" } } };
    expect(surgeryProtocol.initDraft(record).surgery_type).toBe("urgencia");
  });

  it("validate exige el mínimo obligatorio", () => {
    const errs = surgeryProtocol.validate({});
    expect(errs.surgery).toBeTruthy();
  });

  it("validate ok con el parte completo", () => {
    const errs = surgeryProtocol.validate({
      surgery_type: "programada",
      asa_class: "II",
      anesthesia_type: "general",
      procedure: "Osteosíntesis con placa",
      postop_instructions: "Reposo 15 días",
    });
    expect(errs).toEqual({});
  });
});
