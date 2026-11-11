import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Inventory from "./inventory";
import { completeReception, createProduct, getProducts, getReception, getReceptions, receiveStock } from "../api/inventory";
import { toast } from "sonner";

vi.mock("../auth/authContext", () => ({ useAuth: () => ({ token: "synthetic", user: { id: 1, organization_public_id: "org", role: "ADMIN" }, initializing: false, can: () => true }) }));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("../features/inventory/tutorial/useProductTour", () => ({ useProductTour: () => ({}) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() }, Toaster: () => null }));
vi.mock("../api/inventory", () => ({
    getProducts: vi.fn().mockResolvedValue([{
        id: 1, public_id: "lot-product", name: "Vacuna", internal_code: "VAC", category: "other", tracks_lots: true, stock_quantity: 0,
        presentation: { stock: 0, conversion_factor: 1, sale_price: 10, base_unit: "vial" },
        presentations: [{ public_id: "pres", name: "Vial", conversion_factor: 1, base_unit: "vial" }],
    }]),
    getUnitChoices: vi.fn().mockResolvedValue([]),
    getLotAlerts: vi.fn().mockResolvedValue({ expiring_soon: [], expired_with_stock: [] }),
    getReceptions: vi.fn(), getReception: vi.fn(), getUnattributedReceptionEntries: vi.fn(),
    completeReception: vi.fn(), discardReception: vi.fn(),
    createProduct: vi.fn(), updateProduct: vi.fn(), deleteProduct: vi.fn(), adjustStock: vi.fn(),
    adjustPresentationStock: vi.fn(), createPresentation: vi.fn(), updatePresentation: vi.fn(), receiveStock: vi.fn(),
}));

const PENDING = {
    operation_id: "server-op", status: "pending", evidence_level: "intent", created_at: "2026-11-05T10:00:00Z",
    is_own: true, actor_name: "Ana", product_name: "Vacuna", presentation_name: "Vial",
    requested_lines: [{ lot_number: "SYN", expiry_date: null, quantity: "2.00" }], applied_lines: [], lines_total: 1, allowed_actions: ["complete", "discard"],
};

const enterLotReception = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Entrada de stock" }));
    const search = screen.getByPlaceholderText(/Escanea código de barras/);
    fireEvent.change(search, { target: { value: "VAC" } });
    fireEvent.keyDown(search, { key: "Enter" });
    const lotNumber = await screen.findByPlaceholderText("A123");
    fireEvent.change(lotNumber, { target: { value: "SYN" } });
    return lotNumber;
};

const confirmButton = () => screen.getByRole("button", { name: "Registrar recepción" });

beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    vi.mocked(getReceptions).mockResolvedValue({ results: [], next: null });
});

describe("recuperación desde el servidor en la página de inventario", () => {
    it("con el navegador vacío avisa de lo pendiente y no ejecuta nada por su cuenta", async () => {
        vi.mocked(getReceptions).mockResolvedValue({ results: [PENDING], next: null, can_supervise: false });

        render(<Inventory />);

        fireEvent.click(await screen.findByRole("button", { name: "Revisar recepciones" }));
        await screen.findByRole("dialog", { name: "Recepciones" });
        expect(screen.getByRole("button", { name: "Sin resolver" })).toHaveAttribute("aria-pressed", "true");
        expect(receiveStock).not.toHaveBeenCalled();
        expect(createProduct).not.toHaveBeenCalled();
        expect(screen.queryByRole("button", { name: "Confirmar recepción pendiente" })).not.toBeInTheDocument();
    });

    it("al completar conserva abierto el panel con la evidencia y refresca el inventario", async () => {
        vi.mocked(getReceptions).mockResolvedValue({ results: [PENDING], next: null });
        vi.mocked(getReception).mockResolvedValue({ ...PENDING, current_balance: { product_stock_quantity: "0", base_unit: "vial", lots: [] }, ledger_since_intent: { entries: [], truncated: false } });
        vi.mocked(completeReception).mockResolvedValue({ ...PENDING, status: "confirmed", evidence_level: "ledger", allowed_actions: [], resolved_at: "2026-11-05T10:00:01Z", applied_lines: [{ movement_id: 7, lot_number: "SYN", quantity_presentation: "2.0000", quantity_base: "2.0000", created_at: "2026-11-05T10:00:01Z" }], current_balance: { product_stock_quantity: "2", base_unit: "vial", lots: [] } });
        render(<Inventory />);
        fireEvent.click(await screen.findByRole("button", { name: "Revisar recepciones" }));
        fireEvent.click(await screen.findByRole("button", { name: /Lote SYN/ }));
        const productLoads = vi.mocked(getProducts).mock.calls.length;

        fireEvent.click(await screen.findByRole("button", { name: "Completar esta recepción" }));

        await screen.findByText(/ya sumó stock/);
        await waitFor(() => expect(vi.mocked(getProducts).mock.calls.length).toBe(productLoads + 1));
        expect(screen.getByRole("dialog", { name: "Recepciones" })).toBeInTheDocument();
        expect(screen.getByText(/ya sumó stock/)).toBeInTheDocument();
    });

    it("sin pendientes también permite consultar lo ya confirmado", async () => {
        render(<Inventory />);

        fireEvent.click(await screen.findByRole("button", { name: "Recepciones" }));

        await screen.findByRole("dialog", { name: "Recepciones" });
        expect(screen.getByRole("button", { name: "Todas" })).toHaveAttribute("aria-pressed", "true");
    });

    it("el reintento local oculto no compite si el servidor ya lista esa misma operación", async () => {
        localStorage.setItem("inventory-pending-reception:org:1", JSON.stringify({ productId: "p", presentationId: "pres", operationId: "server-op", payload: { lots: [] } }));
        vi.mocked(getReceptions).mockResolvedValue({ results: [PENDING], next: null });

        render(<Inventory />);

        await screen.findByRole("button", { name: "Revisar recepciones" });
        expect(screen.queryByRole("button", { name: "Confirmar recepción pendiente" })).not.toBeInTheDocument();
    });

    it("un almacenamiento ilegible no bloquea ni simula una recepción", async () => {
        localStorage.setItem("inventory-pending-reception:org:1", "{no-json");

        render(<Inventory />);

        await screen.findByRole("button", { name: "Recepciones" });
        expect(screen.queryByText(/sin confirmar/)).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Confirmar recepción pendiente" })).not.toBeInTheDocument();
    });
});

describe("entrada de stock por lotes", () => {
    it("reintenta la misma captura con la misma identidad y, sin respuesta, lleva a revisar", async () => {
        vi.mocked(receiveStock).mockRejectedValue(new Error("connection lost"));
        render(<Inventory />);
        await enterLotReception();

        fireEvent.click(confirmButton());

        await screen.findByRole("dialog", { name: "Recepciones" });
        expect(receiveStock).toHaveBeenCalledTimes(1);
        expect(receiveStock.mock.calls[0][0]).toBe("pres");
        expect(receiveStock.mock.calls[0][2]).toMatch(/^[0-9a-f-]{36}$/);
        expect(toast.error).toHaveBeenCalled();
    });

    it("un rechazo de validación se queda en el formulario y conserva la identidad", async () => {
        vi.mocked(receiveStock).mockRejectedValue({ response: { status: 400, data: { code: "validation_error", message: "Fecha inválida" } } });
        render(<Inventory />);
        await enterLotReception();

        fireEvent.click(confirmButton());
        await waitFor(() => expect(receiveStock).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(confirmButton()).toBeEnabled());
        expect(screen.queryByRole("dialog", { name: "Recepciones" })).not.toBeInTheDocument();
        fireEvent.click(confirmButton());

        await waitFor(() => expect(receiveStock).toHaveBeenCalledTimes(2));
        expect(receiveStock.mock.calls[1][2]).toBe(receiveStock.mock.calls[0][2]);
    });

    it("cambiar lo capturado es otra recepción: nueva identidad", async () => {
        vi.mocked(receiveStock).mockRejectedValue({ response: { status: 400, data: { code: "validation_error", message: "Fecha inválida" } } });
        render(<Inventory />);
        const lotNumber = await enterLotReception();

        fireEvent.click(confirmButton());
        await waitFor(() => expect(receiveStock).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(confirmButton()).toBeEnabled());
        fireEvent.change(lotNumber, { target: { value: "OTRO" } });
        fireEvent.click(confirmButton());

        await waitFor(() => expect(receiveStock).toHaveBeenCalledTimes(2));
        expect(receiveStock.mock.calls[1][2]).not.toBe(receiveStock.mock.calls[0][2]);
    });
});
