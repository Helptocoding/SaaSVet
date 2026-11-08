import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Inventory from "./inventory";
import { createProduct, receiveStock } from "../api/inventory";

vi.mock("../auth/authContext", () => ({ useAuth: () => ({ token: "synthetic", user: { id: 1, organization_public_id: "org", role: "ADMIN" }, initializing: false, can: () => true }) }));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("../features/inventory/tutorial/useProductTour", () => ({ useProductTour: () => ({}) }));
vi.mock("../api/inventory", () => ({
    getProducts: vi.fn().mockResolvedValue([
        { id: 1, public_id: "a", name: "Producto A", category: "other", stock_quantity: 12, presentation: { stock: 12, conversion_factor: 12, sale_price: 120, base_unit: "piece" } },
        { id: 2, public_id: "b", name: "Producto B", category: "other", stock_quantity: 6, presentation: { stock: 6, conversion_factor: 1, sale_price: 50, base_unit: "piece" } },
    ]),
    getUnitChoices: vi.fn().mockResolvedValue([]),
    getLotAlerts: vi.fn().mockResolvedValue({ expiring_soon: [], expired_with_stock: [] }),
    getReceptions: vi.fn().mockResolvedValue({ results: [] }),
    createProduct: vi.fn(), updateProduct: vi.fn(), deleteProduct: vi.fn(), adjustStock: vi.fn(),
    createPresentation: vi.fn(), updatePresentation: vi.fn(), receiveStock: vi.fn(),
}));

describe("orden de la tabla de inventario", () => {
    it("ordena por el valor y stock mostrados en ambas direcciones", async () => {
        render(<Inventory />);
        await screen.findByText("Producto A");
        const table = screen.getByRole("table");
        const rows = () => within(table).getAllByRole("row").slice(1).map(row => row.textContent);
        fireEvent.click(within(table).getByText("Valor en stock"));
        expect(rows()[0]).toContain("Producto A");
        expect(rows()[0]).toContain("$120");
        expect(rows()[1]).toContain("Producto B");
        expect(rows()[1]).toContain("$300");
        fireEvent.click(within(table).getByText("Valor en stock"));
        expect(rows()[0]).toContain("Producto B");
        fireEvent.click(within(table).getByText("Stock"));
        expect(rows()[0]).toContain("Producto B");
        fireEvent.click(within(table).getByText("Stock"));
        expect(rows()[0]).toContain("Producto A");
    });
});

describe("recepción pendiente del wizard", () => {
    it("recupera el intento tras recarga sin recrear el producto y conserva la identidad", async () => {
        const key = "inventory-pending-reception:org:1";
        const pending = { productId: "product", presentationId: "presentation", operationId: "operation", payload: { lots: [{ lot_number: "SYN", quantity: 2 }] } };
        localStorage.setItem(key, JSON.stringify(pending));
        vi.mocked(receiveStock).mockResolvedValueOnce({});
        vi.mocked(createProduct).mockClear();
        render(<Inventory />);
        fireEvent.click(await screen.findByRole("button", { name: "Confirmar recepción pendiente" }));
        await waitFor(() => expect(receiveStock).toHaveBeenCalledWith("presentation", pending.payload, "operation"));
        await waitFor(() => expect(localStorage.getItem(key)).toBeNull());
        expect(createProduct).not.toHaveBeenCalled();
    });

    it("conserva la identidad tras un fallo y la reutiliza en el siguiente intento", async () => {
        const key = "inventory-pending-reception:org:1";
        const pending = { productId: "product", presentationId: "presentation", operationId: "same-operation", payload: { lots: [{ lot_number: "SYN", quantity: 2 }] } };
        localStorage.setItem(key, JSON.stringify(pending));
        vi.mocked(receiveStock).mockReset().mockRejectedValueOnce(new Error("connection lost")).mockResolvedValueOnce({});
        vi.mocked(createProduct).mockClear();
        render(<Inventory />);
        const button = await screen.findByRole("button", { name: "Confirmar recepción pendiente" });
        fireEvent.click(button);
        await waitFor(() => expect(receiveStock).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(button).toBeEnabled());
        expect(JSON.parse(localStorage.getItem(key))).toEqual(pending);
        fireEvent.click(button);
        await waitFor(() => expect(receiveStock).toHaveBeenCalledTimes(2));
        expect(receiveStock).toHaveBeenNthCalledWith(1, "presentation", pending.payload, "same-operation");
        expect(receiveStock).toHaveBeenNthCalledWith(2, "presentation", pending.payload, "same-operation");
        expect(createProduct).not.toHaveBeenCalled();
        await waitFor(() => expect(localStorage.getItem(key)).toBeNull());
    });
});
