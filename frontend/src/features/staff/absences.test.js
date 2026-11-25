/**
 * Ausencias (ADR p67): las fechas locales se comparan y formatean sin pasar por
 * la zona del navegador, y la agenda marca al veterinario ausente ese día.
 */
import { describe, expect, it } from "vitest";
import {
    absenceKindLabel, absencesByMember, formatAbsenceRange, formatLocalDate, isAbsentOn,
    orgTodayIso, vetOptionLabel,
} from "./absences";

const absence = (member, start, end) => ({ member, start_date: start, end_date: end });

describe("ausencias", () => {
    it("cubre ambos extremos del rango", () => {
        const list = [absence(1, "2026-12-01", "2026-12-03")];
        expect(isAbsentOn(list, "2026-11-30")).toBe(false);
        expect(isAbsentOn(list, "2026-12-01")).toBe(true);
        expect(isAbsentOn(list, "2026-12-03")).toBe(true);
        expect(isAbsentOn(list, "2026-12-04")).toBe(false);
        expect(isAbsentOn(undefined, "2026-12-01")).toBe(false);
        expect(isAbsentOn(list, "")).toBe(false);
    });

    it("formatea la fecha local sin correrla de día", () => {
        expect(formatLocalDate("2026-12-01")).toMatch(/1 de dic/);
        expect(formatAbsenceRange("2026-12-01", "2026-12-01")).toBe(formatLocalDate("2026-12-01"));
        expect(formatAbsenceRange("2026-12-01", "2026-12-03")).toContain("–");
    });

    it("agrupa por integrante y marca al veterinario ausente", () => {
        const map = absencesByMember([absence(7, "2026-12-01", "2026-12-01"), absence(8, "2026-12-05", "2026-12-06")]);
        const vet = { first_name: "Ana", last_name: "López", absences: map.get(7) };
        expect(vetOptionLabel(vet, "2026-12-01")).toBe("Ana López · ausente");
        expect(vetOptionLabel(vet, "2026-12-02")).toBe("Ana López");
        expect(vetOptionLabel({ first_name: "Luis", last_name: "Pérez" }, "2026-12-01")).toBe("Luis Pérez");
    });

    it("traduce el tipo y nunca muestra un código", () => {
        expect(absenceKindLabel("leave")).toBe("Permiso");
        expect(absenceKindLabel("raro")).toBe("Ausencia");
    });

    it("hoy es el día de la clínica, no el del navegador", () => {
        const instant = new Date("2026-11-24T03:30:00Z");
        expect(orgTodayIso("America/Mexico_City", instant)).toBe("2026-11-23");
        expect(orgTodayIso("UTC", instant)).toBe("2026-11-24");
    });
});
