/**
 * Historial de accesos (ADR p66): cada evento del backend se lee como una frase
 * y nunca inventa valores que el evento no trae.
 */
import { describe, expect, it } from "vitest";
import { describeEvent } from "./history";

describe("describeEvent", () => {
    it("describe cada tipo de evento", () => {
        expect(describeEvent({ kind: "created", changes: { role: "ASSISTANT" } })).toBe("Alta como asistente");
        expect(describeEvent({ kind: "profile_updated", changes: { fields: ["email", "license_number", "attends_patients"] } }))
            .toBe("Editó correo, cédula y si atiende pacientes");
        expect(describeEvent({ kind: "role_changed", changes: { role: { from: "ADMIN", to: "VET" } } }))
            .toBe("Cambió el rol de administrador a veterinario");
        expect(describeEvent({
            kind: "role_changed",
            changes: { role: { from: "VET", to: "ASSISTANT" }, attends_patients: { from: true, to: false } },
        })).toBe("Cambió el rol de veterinario a asistente; ya no atiende pacientes");
        expect(describeEvent({ kind: "deactivated" })).toBe("Desactivó su acceso");
        expect(describeEvent({ kind: "reactivated" })).toBe("Reactivó su acceso");
        expect(describeEvent({ kind: "password_reset", changes: {} })).toBe("Restableció su contraseña");
        expect(describeEvent({ kind: "password_reset", changes: { source: "platform" } }))
            .toBe("Soporte de la plataforma restableció su contraseña");
    });

    it("describe ausencias y reasignaciones (ADR p67)", () => {
        expect(describeEvent({ kind: "absence_added", changes: { kind: "vacation", start_date: "2026-12-01", end_date: "2026-12-01" } }))
            .toMatch(/^Registró vacaciones: .*1 de dic/);
        expect(describeEvent({ kind: "absence_cancelled", changes: { kind: "leave", start_date: "2026-12-01", end_date: "2026-12-03" } }))
            .toMatch(/^Canceló la ausencia del .*–/);
        expect(describeEvent({ kind: "appointments_reassigned", changes: { moved: 1, skipped: 0 } }))
            .toBe("Reasignó 1 cita a otro veterinario");
        expect(describeEvent({ kind: "appointments_reassigned", changes: { moved: 3, skipped: 2 } }))
            .toBe("Reasignó 3 citas a otro veterinario; 2 quedaron sin mover");
    });

    it("un tipo desconocido usa la etiqueta del backend", () => {
        expect(describeEvent({ kind: "otro", kind_label: "Algo nuevo" })).toBe("Algo nuevo");
    });
});
