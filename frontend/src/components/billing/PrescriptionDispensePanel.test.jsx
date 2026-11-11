import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("sonner", () => ({ toast: { promise: vi.fn((p) => p), error: vi.fn(), success: vi.fn() } }));
vi.mock("../../api/billing", () => ({
    dispensePrescription: vi.fn(),
    decidePrescriptionItem: vi.fn(),
}));

import PrescriptionDispensePanel from "./PrescriptionDispensePanel";
import { dispensePrescription, decidePrescriptionItem } from "../../api/billing";

const lot = { id: 9, lot_number: "L1", expiry_date: "2027-01-01", available_quantity_base: "10" };
const lotPresentations = [{
    id: 5, name: "Caja 10", sale_price: "100", max_selectable_quantity: 2,
    available_stock_quantity_presentations: 4, lots: [lot], blocking_reasons: [],
}];
const makeInvoice = (over = {}, suggestion = {}) => ({
    public_id: "chk-1", prescription_public_id: "rx-1", lifecycle: "open", version: 3,
    prescription_suggestions: [{
        prescription_item_id: 11, product_name: "Amoxicilina", dose: "1 tableta", base_unit: "tableta",
        prescribed_quantity_base: "10", fulfilled_quantity_base: "0", selected_quantity_base: "0", legal_remaining_quantity_base: "10",
        decision: "pending", tracks_lots: false,
        presentations: [{ id: 5, name: "Caja 10", sale_price: "100", max_selectable_quantity: 2, available_stock_quantity_presentations: 4, lots: [], blocking_reasons: [] }],
        ...suggestion,
    }],
    ...over,
});
const addBtn = () => screen.getByRole("button", { name: "Agregar al cobro" });

describe("PrescriptionDispensePanel", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        dispensePrescription.mockResolvedValue({ updated: true });
        decidePrescriptionItem.mockResolvedValue({ updated: true });
    });

    it("no renderiza si el cobro no está abierto, sin sugerencias o sin receta", () => {
        const cases = [
            makeInvoice({ lifecycle: "completed" }),
            makeInvoice({ prescription_suggestions: [] }),
            makeInvoice({ prescription_public_id: null }),
        ];
        for (const invoice of cases) {
            const { container, unmount } = render(<PrescriptionDispensePanel invoice={invoice} onDispensed={vi.fn()} />);
            expect(container).toBeEmptyDOMElement();
            unmount();
        }
    });

    it("nada viene preseleccionado", () => {
        render(<PrescriptionDispensePanel invoice={makeInvoice()} onDispensed={vi.fn()} />);
        expect(screen.getByRole("checkbox")).not.toBeChecked();
        expect(addBtn()).toBeDisabled();
    });

    it("al marcar y agregar dispensa la línea y avisa", async () => {
        const onDispensed = vi.fn();
        render(<PrescriptionDispensePanel invoice={makeInvoice()} onDispensed={onDispensed} />);
        await userEvent.click(screen.getByRole("checkbox"));
        await userEvent.click(addBtn());
        await waitFor(() => expect(onDispensed).toHaveBeenCalledTimes(1));
        expect(dispensePrescription).toHaveBeenCalledWith("rx-1", {
            lines: [{ presentation: 5, quantity: 1, prescription_item: 11 }],
            expectedVersion: 3,
            idempotencyKey: expect.any(String),
        });
    });

    it("una cantidad sobre el máximo deshabilita el botón", async () => {
        render(<PrescriptionDispensePanel invoice={makeInvoice()} onDispensed={vi.fn()} />);
        await userEvent.click(screen.getByRole("checkbox"));
        expect(addBtn()).toBeEnabled();
        fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "3" } });
        expect(addBtn()).toBeDisabled();
    });

    it("con lotes, sin elegir lote la línea no lo incluye", async () => {
        const invoice = makeInvoice({}, { tracks_lots: true, presentations: lotPresentations });
        const onDispensed = vi.fn();
        render(<PrescriptionDispensePanel invoice={invoice} onDispensed={onDispensed} />);
        await userEvent.click(screen.getByRole("checkbox"));
        await userEvent.click(addBtn());
        await waitFor(() => expect(onDispensed).toHaveBeenCalled());
        expect(dispensePrescription.mock.calls[0][1].lines).toEqual([
            { presentation: 5, quantity: 1, prescription_item: 11 },
        ]);
    });

    it("con lotes, al elegir un lote la línea lo incluye", async () => {
        const invoice = makeInvoice({}, { tracks_lots: true, presentations: lotPresentations });
        const onDispensed = vi.fn();
        render(<PrescriptionDispensePanel invoice={invoice} onDispensed={onDispensed} />);
        await userEvent.click(screen.getByRole("checkbox"));
        await userEvent.selectOptions(screen.getByDisplayValue("FEFO automático"), "9");
        await userEvent.click(addBtn());
        await waitFor(() => expect(onDispensed).toHaveBeenCalled());
        expect(dispensePrescription.mock.calls[0][1].lines).toEqual([
            { presentation: 5, quantity: 1, prescription_item: 11, lot: 9 },
        ]);
    });

    it("«No lo llevará» registra el rechazo y avisa", async () => {
        const onDispensed = vi.fn();
        render(<PrescriptionDispensePanel invoice={makeInvoice()} onDispensed={onDispensed} />);
        await userEvent.click(screen.getByRole("button", { name: "No lo llevará" }));
        await waitFor(() => expect(onDispensed).toHaveBeenCalled());
        expect(decidePrescriptionItem).toHaveBeenCalledWith("chk-1", 11, {
            decision: "declined", reasonCode: "not_now", expectedVersion: 3,
        });
    });
});
