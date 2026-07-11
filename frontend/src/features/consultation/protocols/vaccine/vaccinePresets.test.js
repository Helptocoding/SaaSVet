import { describe, it, expect } from "vitest";
import {
  getVaccinePresets,
  getVaccinePreset,
  computeNextDue,
  todayISO,
} from "./vaccinePresets";

describe("getVaccinePresets — filtro por especie", () => {
  it("canino incluye Rabia y excluye Triple felina", () => {
    const ids = getVaccinePresets({ species: "canino" }).map((p) => p.id);
    expect(ids).toContain("rabia");
    expect(ids).not.toContain("triple_felina");
  });

  it("felino incluye Triple felina y excluye Parvovirus", () => {
    const ids = getVaccinePresets({ species: "felino" }).map((p) => p.id);
    expect(ids).toContain("triple_felina");
    expect(ids).not.toContain("parvovirus");
  });

  it("sin especie devuelve todos", () => {
    expect(getVaccinePresets().length).toBeGreaterThanOrEqual(6);
  });

  it("especie sin protocolo (fallback) devuelve el catálogo completo", () => {
    const all = getVaccinePresets();
    expect(getVaccinePresets({ species: "exótico" })).toHaveLength(all.length);
  });
});

describe("computeNextDue", () => {
  it("suma N meses a la fecha de aplicación", () => {
    expect(computeNextDue("2026-07-01", 12)).toBe("2027-07-01");
    expect(computeNextDue("2026-01-15", 3)).toBe("2026-04-15");
  });

  it("null si no hay meses de refuerzo o falta la fecha base", () => {
    expect(computeNextDue("2026-07-01", null)).toBeNull();
    expect(computeNextDue(null, 12)).toBeNull();
    expect(computeNextDue("", 12)).toBeNull();
  });
});

describe("helpers auxiliares", () => {
  it("getVaccinePreset resuelve por id", () => {
    expect(getVaccinePreset("rabia")?.name).toBe("Rabia");
    expect(getVaccinePreset("no-existe")).toBeNull();
  });

  it("todayISO devuelve formato YYYY-MM-DD", () => {
    expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
