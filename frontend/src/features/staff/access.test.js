/**
 * Presentación del estado de acceso (Fase 1 Equipo). El estado lo decide el
 * backend; aquí se comprueba el texto, la zona horaria y que solo la temporal
 * vencida pide atención.
 */
import { describe, expect, it } from "vitest";
import { ACCESS_LABELS, describeAccess, lastAccessLabel, PENDING_ACCESS } from "./access";

const NOW = new Date("2026-11-23T18:00:00Z");
const access = (status, extra = {}) => ({
    status, last_login: null, temp_password_expires_at: null, ...extra,
});

describe("describeAccess", () => {
    it("tiene texto para cada estado del backend", () => {
        // Lista cerrada de apps/users/access.py (ACCESS_STATUSES).
        expect(Object.keys(ACCESS_LABELS).sort()).toEqual([
            "active", "inactive", "password_change_pending", "pending_first_login",
            "temp_password_active", "temp_password_expired",
        ]);
    });

    it("solo la temporal vencida pide atención", () => {
        for (const status of Object.keys(ACCESS_LABELS)) {
            const extra = status.startsWith("temp_") ? { temp_password_expires_at: "2026-11-23T16:00:00Z" } : {};
            expect(describeAccess(access(status, extra), "UTC", NOW).attention).toBe(status === "temp_password_expired");
        }
    });

    it("muestra el vencimiento de la temporal, no el último acceso", () => {
        const view = describeAccess(
            access("temp_password_active", { temp_password_expires_at: "2026-11-24T02:00:00Z", last_login: "2026-11-20T10:00:00Z" }),
            "UTC", NOW,
        );
        expect(view).toMatchObject({ label: "Contraseña temporal", detail: "Vence en 8 h" });
        expect(view.title).toMatch(/2026/);
    });

    it("no inventa un último acceso", () => {
        expect(describeAccess(access("active"), "UTC", NOW)).toMatchObject({
            label: "Activo", detail: "Sin accesos registrados", title: "",
        });
    });

    it("un estado desconocido no rompe la fila", () => {
        expect(describeAccess(undefined, "UTC", NOW).label).toBe("—");
    });
});

describe("lastAccessLabel", () => {
    it("relativo el mismo día; ayer y fecha corta después, en la zona de la clínica", () => {
        expect(lastAccessLabel("2026-11-23T17:20:00Z", "UTC", NOW)).toBe("Último acceso: hace 40 min");
        expect(lastAccessLabel("2026-11-22T12:00:00Z", "UTC", NOW)).toBe("Último acceso: ayer");
        expect(lastAccessLabel("2026-11-02T12:00:00Z", "UTC", NOW)).toBe("Último acceso: 2 nov");
        // 02:00 UTC del 22 es el 21 en Ciudad de México.
        expect(lastAccessLabel("2026-11-22T02:00:00Z", "America/Mexico_City", NOW)).toBe("Último acceso: 21 nov");
    });
});

describe("PENDING_ACCESS", () => {
    it("cuenta solo a quien no ha completado su acceso", () => {
        expect([...PENDING_ACCESS].sort()).toEqual([
            "password_change_pending", "pending_first_login", "temp_password_active", "temp_password_expired",
        ]);
    });
});
