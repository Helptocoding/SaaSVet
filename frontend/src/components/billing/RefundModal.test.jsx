import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("sonner", () => ({ toast: { promise: vi.fn((p) => p), error: vi.fn(), success: vi.fn() } }));
vi.mock("../../api/billing", () => ({ refundInvoice: vi.fn() }));

import RefundModal from "./RefundModal";
import { refundInvoice } from "../../api/billing";

const invoice = { public_id: "inv-1", id: 7, total: "300.00", items: [
    { id: 1, description: "Consulta", quantity: "1.00", subtotal: "100.00", presentation: null },
    { id: 2, description: "Shampoo", quantity: "2.00", subtotal: "200.00", presentation: 55 },
] };

const setup = () => {
    const onDone = vi.fn();
    const onClose = vi.fn();
    render(<RefundModal invoice={invoice} onClose={onClose} onDone={onDone} />);
    return { onDone, onClose };
};
const submitBtn = () => screen.getByRole("button", { name: "Emitir devolución" });

describe("RefundModal", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        refundInvoice.mockResolvedValue({});
    });

    it("por defecto emite la devolución completa", async () => {
        const { onDone } = setup();
        await userEvent.click(submitBtn());
        await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
        expect(refundInvoice).toHaveBeenCalledWith("inv-1", {
            creditLines: [
                { invoice_item: 1, quantity: "1.00", amount: "100.00", disposition: "restock" },
                { invoice_item: 2, quantity: "2.00", amount: "200.00", disposition: "restock" },
            ],
            refundLines: [{ method: "cash", amount: "300.00" }],
            reasonCode: "customer_return",
            reasonNotes: "",
            idempotencyKey: expect.any(String),
        });
    });

    it("al desmarcar una fila exige igualar el reembolso al nuevo total", async () => {
        const { onDone } = setup();
        await userEvent.click(screen.getAllByRole("checkbox")[0]);
        expect(submitBtn()).toBeDisabled();
        await userEvent.click(screen.getByRole("button", { name: "Igualar al total" }));
        expect(submitBtn()).toBeEnabled();
        await userEvent.click(submitBtn());
        await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
        const [, payload] = refundInvoice.mock.calls[0];
        expect(payload.creditLines).toHaveLength(1);
        expect(payload.creditLines[0].amount).toBe("200.00");
        expect(payload.refundLines).toEqual([{ method: "cash", amount: "200.00" }]);
    });

    it("una cantidad mayor que la máxima deshabilita el botón", () => {
        setup();
        const qtyShampoo = screen.getAllByRole("spinbutton")[2];
        fireEvent.change(qtyShampoo, { target: { value: "3" } });
        expect(submitBtn()).toBeDisabled();
    });

    it("si falla el modal sigue abierto y el reintento reutiliza la misma clave", async () => {
        refundInvoice.mockRejectedValueOnce(new Error("boom"));
        const { onDone } = setup();
        await userEvent.click(submitBtn());
        await waitFor(() => expect(refundInvoice).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(submitBtn()).toBeEnabled());
        expect(onDone).not.toHaveBeenCalled();

        await userEvent.click(submitBtn());
        await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
        const firstKey = refundInvoice.mock.calls[0][1].idempotencyKey;
        const secondKey = refundInvoice.mock.calls[1][1].idempotencyKey;
        expect(secondKey).toBe(firstKey);
    });

    it("una línea sin presentación envía siempre restock", async () => {
        setup();
        await userEvent.selectOptions(screen.getByDisplayValue("Reingresa a stock"), "discard");
        await userEvent.click(submitBtn());
        await waitFor(() => expect(refundInvoice).toHaveBeenCalledTimes(1));
        const { creditLines } = refundInvoice.mock.calls[0][1];
        expect(creditLines[0].disposition).toBe("restock");
        expect(creditLines[1].disposition).toBe("discard");
    });
});
