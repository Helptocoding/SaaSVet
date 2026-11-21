import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Inventory from "./inventory";

vi.mock("../auth/authContext", () => ({ useAuth: () => ({ token: "synthetic", user: { id: 1, organization_public_id: "org", role: "ADMIN" }, initializing: false, can: () => true }) }));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("../features/inventory/tutorial/useProductTour", () => ({ useProductTour: () => ({}) }));

const { product } = vi.hoisted(() => ({
    product: (id, name, category, stock, min, extra = {}) => ({
        id, public_id: `p-${id}`, name, category, is_active: true,
        stock_quantity: stock, min_stock: min,
        presentation: { stock, min_stock: min, conversion_factor: 1, sale_price: 10, base_unit: "piece" },
        ...extra,
    }),
}));

vi.mock("../api/inventory", () => ({
    getProducts: vi.fn().mockResolvedValue([
        product(1, "Agotado Uno", "medication", 0, 5),
        product(2, "Bajo Dos", "medication", 2, 5),
        // En el mínimo exacto: el flag del backend lo marcaba bajo, el badge dice Normal.
        product(3, "Justo Tres", "medication", 10, 10),
        product(4, "Inactivo Cuatro", "medication", 0, 5, { is_active: false }),
        product(5, "Croqueta Cinco", "food", 50, 5),
    ]),
    getUnitChoices: vi.fn().mockResolvedValue([]),
    getLotAlerts: vi.fn().mockResolvedValue({ expiring_soon: [], expired_with_stock: [] }),
    getReceptions: vi.fn().mockResolvedValue({ results: [] }),
    createProduct: vi.fn(), updateProduct: vi.fn(), deleteProduct: vi.fn(), adjustStock: vi.fn(),
    createPresentation: vi.fn(), updatePresentation: vi.fn(), receiveStock: vi.fn(),
}));

const rowNames = () => within(screen.getByRole("table"))
    .getAllByRole("row").slice(1)
    .map(row => row.textContent);

const shows = (names) => {
    const rows = rowNames();
    expect(rows).toHaveLength(names.length);
    names.forEach(name => expect(rows.some(r => r.includes(name))).toBe(true));
};

describe("productos que requieren atención en Inventario", () => {
    it("no muestra el aviso persistente y los indicadores cuentan lo mismo que filtran", async () => {
        render(<Inventory />);
        await screen.findByText("Agotado Uno");
        expect(screen.queryByText(/requieren atención:/)).toBeNull();

        const low = screen.getByRole("button", { name: "Bajo stock: 1" });
        const out = screen.getByRole("button", { name: "Sin stock: 1" });
        expect(low).toHaveAttribute("aria-pressed", "false");

        fireEvent.click(out);
        expect(out).toHaveAttribute("aria-pressed", "true");
        shows(["Agotado Uno"]);

        fireEvent.click(low);
        shows(["Bajo Dos"]);

        fireEvent.click(low);
        expect(low).toHaveAttribute("aria-pressed", "false");
        expect(rowNames()).toHaveLength(5);
    });

    it("los indicadores muestran en el pie datos reales del inventario, sin deltas inventados", async () => {
        render(<Inventory />);
        await screen.findByText("Agotado Uno");
        const summary = screen.getByRole("region", { name: "Resumen de inventario" });
        // 4 activos (el inactivo no cuenta) y 1 desactivado.
        expect(within(summary).getByText("Productos activos").closest("div")).toHaveTextContent("Desactivados: 1");
        // 3 de los 4 activos son medicamentos → 75 %; ninguno exige receta.
        expect(within(summary).getByText("75%")).toBeInTheDocument();
        expect(within(summary).getByText(/Con receta:/)).toHaveTextContent("Con receta: 0");
        expect(within(summary).queryByText(/vs mes anterior/i)).toBeNull();
    });

    it("el indicador ignora categoría y búsqueda para mostrar exactamente su número", async () => {
        render(<Inventory />);
        await screen.findByText("Agotado Uno");
        fireEvent.click(screen.getByRole("button", { name: "Alimentos" }));
        fireEvent.change(screen.getByPlaceholderText("Buscar producto..."), { target: { value: "croq" } });

        fireEvent.click(screen.getByRole("button", { name: "Sin stock: 1" }));
        expect(screen.getByPlaceholderText("Buscar producto...")).toHaveValue("");
        shows(["Agotado Uno"]);
    });

    it("el chip filtra bajo + agotado del contexto y se puede quitar", async () => {
        render(<Inventory />);
        await screen.findByText("Agotado Uno");
        const chip = screen.getByRole("button", { name: /Requieren atención \(2\)/ });

        fireEvent.click(chip);
        expect(chip).toHaveAttribute("aria-pressed", "true");
        shows(["Agotado Uno", "Bajo Dos"]);

        fireEvent.click(chip);
        expect(rowNames()).toHaveLength(5);
    });

    it("con filtros sin coincidencias ofrece quitarlos en vez de decir que no hay productos", async () => {
        render(<Inventory />);
        await screen.findByText("Agotado Uno");
        fireEvent.click(screen.getByRole("button", { name: /Requieren atención/ }));
        fireEvent.click(screen.getByRole("button", { name: "Alimentos" }));

        expect(screen.getByText("Ningún producto coincide con los filtros")).toBeInTheDocument();
        expect(screen.queryByText("Aún no tienes productos")).toBeNull();
        expect(screen.getByRole("button", { name: /Requieren atención \(0\)/ })).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Quitar filtros" }));
        expect(rowNames()).toHaveLength(5);
    });
});
