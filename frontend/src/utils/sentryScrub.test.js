import { describe, it, expect } from "vitest";
import { scrubEvent } from "./sentryScrub";

describe("scrubEvent", () => {
    it("dropea el body y cookies del request, filtra headers sensibles", () => {
        const event = {
            request: {
                data: { diagnosis: "x", phone: "5551234567" },
                cookies: { sid: "x" },
                headers: {
                    Authorization: "Bearer t",
                    "X-Idempotency-Key": "k",
                    "Content-Type": "application/json",
                },
            },
        };
        const out = scrubEvent(event);
        expect(out.request.data).toBeUndefined();
        expect(out.request.cookies).toBeUndefined();
        expect(out.request.headers.Authorization).toBe("[Filtered]");
        expect(out.request.headers["X-Idempotency-Key"]).toBe("[Filtered]");
        // Header benigno se conserva.
        expect(out.request.headers["Content-Type"]).toBe("application/json");
    });

    it("elimina PII del user pero conserva el id", () => {
        const event = {
            user: { id: "42", email: "a@b.com", username: "vet", ip_address: "1.2.3.4" },
        };
        const out = scrubEvent(event);
        expect(out.user.id).toBe("42");
        expect(out.user.email).toBeUndefined();
        expect(out.user.username).toBeUndefined();
        expect(out.user.ip_address).toBeUndefined();
    });

    it("maneja request/user ausentes sin lanzar", () => {
        expect(() => scrubEvent({})).not.toThrow();
        expect(scrubEvent(null)).toBeNull();
    });
});
