/**
 * Borrador de permisos de la ficha (ADR p69): misma aritmética que el backend
 * (rol ∪ concedidos − quitados; reservados dentro solo en ADMIN), casillas
 * bloqueadas y conservar o descartar ajustes al cambiar de rol.
 */
import { describe, expect, it } from "vitest";
import {
    changeRole, codeBadge, customCounts, draftFromMember, effectiveCodes, lockReason,
    overridesChanged, permissionsPayload, restoreRoleDefaults, toggleCode,
} from "./permissionDraft";

const CATALOG = {
    reserved: ["staff.create"],
    roles: {
        ADMIN: ["appointment.list", "billing.refund", "organization.update", "staff.create"],
        VET: ["appointment.list", "prescription.create"],
        ASSISTANT: ["appointment.list"],
    },
    areas: [
        { key: "clinical", groups: [{ permissions: [{ code: "prescription.create" }] }] },
        { key: "operation", groups: [{ permissions: [{ code: "appointment.list" }, { code: "billing.refund" }] }] },
        { key: "administration", groups: [{ permissions: [{ code: "organization.update" }, { code: "staff.create" }] }] },
    ],
};
const vet = draftFromMember({ role: "VET", permission_overrides: { granted: [], revoked: [] } });

describe("vista previa", () => {
    it("aplica concedidos y quitados sobre el rol", () => {
        const draft = toggleCode(CATALOG, toggleCode(CATALOG, vet, "billing.refund", true), "appointment.list", false);
        expect([...draft.granted]).toEqual(["billing.refund"]);
        expect([...draft.revoked]).toEqual(["appointment.list"]);
        expect(permissionsPayload(CATALOG, draft)).toEqual(["billing.refund", "prescription.create"]);
        expect(customCounts(CATALOG, draft)).toEqual({ extra: 1, removed: 1 });
        expect(codeBadge(CATALOG, draft, "billing.refund")).toBe("extra");
        expect(codeBadge(CATALOG, draft, "appointment.list")).toBe("removed");
        expect(overridesChanged(draft, vet)).toBe(true);
    });

    it("volver a marcar lo del rol no deja ajuste", () => {
        const draft = toggleCode(CATALOG, toggleCode(CATALOG, vet, "appointment.list", false), "appointment.list", true);
        expect(draft.revoked.size).toBe(0);
        expect(overridesChanged(draft, vet)).toBe(false);
    });

    it("los reservados entran solo en ADMIN", () => {
        expect(effectiveCodes(CATALOG, { ...vet, granted: new Set(["staff.create"]) }).has("staff.create")).toBe(false);
        expect(effectiveCodes(CATALOG, { role: "ADMIN", granted: new Set(), revoked: new Set(["staff.create"]) }).has("staff.create")).toBe(true);
    });
});

describe("casillas bloqueadas", () => {
    it("reservados y la regla de autoedición", () => {
        const admin = { role: "ADMIN", granted: new Set(), revoked: new Set() };
        expect(lockReason(CATALOG, vet, "staff.create")).toBe("Solo administradores");
        expect(lockReason(CATALOG, admin, "staff.create")).toBe("Siempre incluido en Administrador");
        const initial = effectiveCodes(CATALOG, admin);
        expect(lockReason(CATALOG, admin, "organization.update", { isSelf: true, initial })).toBe(
            "No puedes quitarte permisos de administración");
        expect(lockReason(CATALOG, admin, "billing.refund", { isSelf: true, initial })).toBeNull();
        expect(lockReason(CATALOG, admin, "organization.update", { isSelf: false, initial })).toBeNull();
    });
});

describe("cambio de rol", () => {
    const custom = toggleCode(CATALOG, vet, "billing.refund", true);

    it("conserva o descarta la diferencia", () => {
        expect(permissionsPayload(CATALOG, changeRole(custom, "ASSISTANT", true))).toEqual(["appointment.list", "billing.refund"]);
        expect(permissionsPayload(CATALOG, changeRole(custom, "ASSISTANT", false))).toEqual(["appointment.list"]);
        expect(permissionsPayload(CATALOG, restoreRoleDefaults(custom))).toEqual(["appointment.list", "prescription.create"]);
    });
});
