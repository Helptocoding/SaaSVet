import { beforeEach, describe, expect, it, vi } from "vitest";
import api from "./client";
import { receiveStock } from "./inventory";

vi.mock("./client", () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

const DATA = { lots: [{ lot_number: "SYN", quantity: 2 }] };

// Cuerpo de bloque a propósito: si beforeEach devuelve una función, Vitest la ejecuta como
// limpieza, y mockReset() devuelve el propio mock (que en una prueba rechaza).
beforeEach(() => {
    vi.mocked(api.post).mockReset();
});

describe("receiveStock", () => {
    it("registra la intención antes de ejecutar y no reenvía la captura al ejecutar", async () => {
        vi.mocked(api.post).mockResolvedValue({ data: { status: "confirmed" } });

        const result = await receiveStock("pres", DATA, "op");

        expect(result).toEqual({ status: "confirmed" });
        expect(vi.mocked(api.post).mock.calls).toEqual([
            ["inventory/presentations/pres/receptions/", DATA, { headers: { "X-Idempotency-Key": "op" } }],
            ["inventory/receptions/op/complete/"],
        ]);
    });

    it("no ejecuta si no sabe que la intención quedó registrada", async () => {
        vi.mocked(api.post).mockRejectedValue(new Error("connection lost"));

        await expect(receiveStock("pres", DATA, "op")).rejects.toThrow("connection lost");

        expect(api.post).toHaveBeenCalledTimes(1);
        expect(vi.mocked(api.post).mock.calls[0][0]).toBe("inventory/presentations/pres/receptions/");
    });

    it("una llamada sin identidad conserva su contrato directo", async () => {
        vi.mocked(api.post).mockResolvedValue({ data: { lots: [] } });

        await receiveStock("pres", DATA);

        expect(vi.mocked(api.post).mock.calls).toEqual([["inventory/presentations/pres/receive/", DATA]]);
    });
});
