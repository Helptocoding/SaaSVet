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

    it("un tipo desconocido usa la etiqueta del backend", () => {
        expect(describeEvent({ kind: "otro", kind_label: "Algo nuevo" })).toBe("Algo nuevo");
    });
});
