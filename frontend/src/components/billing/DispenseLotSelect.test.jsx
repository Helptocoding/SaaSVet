import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import DispenseLotSelect from "./DispenseLotSelect";

const lotsA = [
    { id: 9, lot_number: "L1", expiry_date: "2027-01-01", available_quantity_base: "10" },
    { id: 10, lot_number: "L2", expiry_date: null, available_quantity_base: "4" },
];
const row = {
    key: 11,
    presentationId: "5",
    lot: null,
    presentations: [
        { id: 5, lots: lotsA },
        { id: 6, lots: [{ id: 99, lot_number: "OTRO", available_quantity_base: "1" }] },
    ],
};

describe("DispenseLotSelect", () => {
    it("ofrece FEFO automático y los lotes de la presentación elegida", () => {
        render(<DispenseLotSelect row={row} setRow={vi.fn()} disabled={false} />);
        expect(screen.getByRole("option", { name: "FEFO automático" })).toBeInTheDocument();
        expect(screen.getByRole("option", { name: "L1 · 2027-01-01 · 10" })).toBeInTheDocument();
        expect(screen.getByRole("option", { name: "L2 · 4" })).toBeInTheDocument();
        expect(screen.queryByRole("option", { name: /OTRO/ })).not.toBeInTheDocument();
    });

    it("al cambiar la selección llama a setRow con el lote", async () => {
        const setRow = vi.fn();
        render(<DispenseLotSelect row={row} setRow={setRow} disabled={false} />);
        await userEvent.selectOptions(screen.getByRole("combobox"), "9");
        expect(setRow).toHaveBeenCalledWith(11, { lot: lotsA[0] });
    });
});
