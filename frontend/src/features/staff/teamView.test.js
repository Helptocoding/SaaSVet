/**
 * Reglas de presentación de Equipo (rediseño 2026-11-25): estado de la cuenta,
 * firma de recetas, áreas con acceso, alertas, último acceso y filtros.
 */
import { describe, expect, it } from "vitest";
import {
    accountState, attentionItems, filterMembers, groupsSummary, hasAllAreas, isCustomized,
    lastAccessShort, memberAlerts, memberAreas, signingState, tabCounts,
} from "./teamView";

const NOW = new Date("2026-11-25T12:00:00Z");
const CATALOG = {
    signing_permission: "prescription.create",
    areas: [
        { key: "clinical", label: "Clínica", groups: [
            { key: "medical_records", label: "Consultas", permissions: [{ code: "medicalrecord.list", label: "Ver consultas" }] },
            { key: "prescriptions", label: "Recetas", permissions: [{ code: "prescription.create", label: "Emitir y firmar recetas" }] },
        ] },
        { key: "operation", label: "Operación", groups: [
            { key: "appointments", label: "Citas", permissions: [{ code: "appointment.list", label: "Ver la agenda" }] },
        ] },
        { key: "administration", label: "Administración", groups: [
            { key: "team", label: "Equipo", permissions: [{ code: "staff.create", label: "Dar de alta integrantes" }] },
        ] },
    ],
};
const member = (overrides = {}) => ({
    public_id: overrides.public_id || "id", first_name: "Ana", last_name: "Galeno", email: "ana@vet.mx",
    role: "VET", is_active: true, license_number: "1234567",
    permissions: ["medicalrecord.list", "prescription.create", "appointment.list"],
    permission_overrides: { granted: [], revoked: [] },
    access: { status: "active", last_login: "2026-11-23T12:00:00Z", temp_password_expires_at: null },
    ...overrides,
});

describe("estado y firma", () => {
    it("mapea el estado de acceso a cuatro estados de cuenta", () => {
        expect(accountState(member())).toBe("active");
        for (const status of ["pending_first_login", "temp_password_active", "password_change_pending"]) {
            expect(accountState(member({ access: { status } }))).toBe("pending");
        }
        expect(accountState(member({ access: { status: "temp_password_expired" } }))).toBe("expired");
        expect(accountState(member({ is_active: false, access: { status: "inactive" } }))).toBe("inactive");
    });

    it("firma solo con permiso de recetas y cédula", () => {
        expect(signingState(member(), CATALOG)).toBe("enabled");
        expect(signingState(member({ license_number: "" }), CATALOG)).toBe("missing_license");
        expect(signingState(member({ permissions: ["appointment.list"] }), CATALOG)).toBe("not_applicable");
    });
});

describe("áreas", () => {
    it("solo muestra áreas y acciones que sí tiene", () => {
        const areas = memberAreas(member({ permissions: ["prescription.create", "appointment.list"] }), CATALOG);
        expect(areas.map((a) => a.label)).toEqual(["Clínica", "Operación"]);
        expect(areas[0].groups).toEqual([{ key: "prescriptions", label: "Recetas", actions: ["Emitir y firmar recetas"] }]);
    });

    it("todas las áreas, personalizado y resumen en texto", () => {
        expect(hasAllAreas(member(), CATALOG)).toBe(false);
        expect(hasAllAreas(member({ permissions: ["medicalrecord.list", "prescription.create", "appointment.list", "staff.create"] }), CATALOG)).toBe(true);
        expect(isCustomized(member())).toBe(false);
        expect(isCustomized(member({ permission_overrides: { granted: ["billing.refund"], revoked: [] } }))).toBe(true);
        expect(groupsSummary([{ label: "Consultas" }, { label: "Recetas" }, { label: "Vacunas" }])).toBe("Consultas, recetas, vacunas");
    });
});

describe("alertas", () => {
    it("agrupa a quienes no pueden firmar y separa cada invitación vencida", () => {
        const rows = [
            member({ public_id: "a", first_name: "Ana", license_number: "" }),
            member({ public_id: "b", first_name: "Beto", last_name: "Ruiz", license_number: "" }),
            member({ public_id: "c", first_name: "Caro", access: { status: "temp_password_expired", temp_password_expires_at: "2026-11-22T10:00:00Z" } }),
            member({ public_id: "d", is_active: false, license_number: "", access: { status: "inactive" } }),
        ];
        const items = attentionItems(rows, CATALOG, NOW);
        expect(items.map((i) => i.text)).toEqual([
            "2 veterinarios sin cédula no pueden firmar recetas: Ana Galeno, Beto Ruiz",
            "La invitación de Caro Galeno venció hace 3 días",
        ]);
        expect(memberAlerts(rows[3], CATALOG, NOW)).toEqual([]);
    });
});

describe("último acceso", () => {
    it("ahora, nunca y fecha relativa corta", () => {
        expect(lastAccessShort(member(), { isSelf: true, now: NOW })).toBe("Ahora");
        expect(lastAccessShort(member({ access: { last_login: null } }), { now: NOW })).toBe("Nunca");
        expect(lastAccessShort(member(), { now: NOW })).toBe("hace 2 d");
        expect(lastAccessShort(member({ access: { last_login: "2026-11-25T09:00:00Z" } }), { now: NOW })).toBe("hace 3 h");
    });
});

describe("filtros", () => {
    const rows = [
        member({ public_id: "a", first_name: "Ana" }),
        member({ public_id: "b", first_name: "Bruno", role: "ASSISTANT", email: "bruno@vet.mx", access: { status: "pending_first_login" } }),
        member({ public_id: "c", first_name: "Ñandú", license_number: "", is_active: true }),
        member({ public_id: "d", first_name: "Dora", is_active: false, access: { status: "inactive" } }),
    ];

    it("cuenta por pestaña; «Todos» no incluye a los desactivados", () => {
        expect(tabCounts(rows, CATALOG, NOW)).toEqual({ all: 3, active: 2, pending: 1, attention: 1, inactive: 1 });
    });

    it("combina pestaña, búsqueda sin acentos y rol", () => {
        expect(filterMembers(rows, { tab: "all", query: "nandu" }, CATALOG, NOW).map((m) => m.public_id)).toEqual(["c"]);
        expect(filterMembers(rows, { tab: "all", query: "bruno@" }, CATALOG, NOW).map((m) => m.public_id)).toEqual(["b"]);
        expect(filterMembers(rows, { tab: "all", role: "ASSISTANT" }, CATALOG, NOW).map((m) => m.public_id)).toEqual(["b"]);
        expect(filterMembers(rows, { tab: "attention" }, CATALOG, NOW).map((m) => m.public_id)).toEqual(["c"]);
    });
});
