import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReceptionsModal from "./ReceptionsModal";
import {
    completeReception, discardReception, getReception, getReceptions, getUnattributedReceptionEntries,
} from "../api/inventory";

const confirmMock = vi.hoisted(() => vi.fn());
vi.mock("./useConfirm", () => ({ useConfirm: () => confirmMock }));
vi.mock("../auth/authContext", () => ({ useAuth: () => ({ user: { id: 1 } }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));
vi.mock("../api/inventory", () => ({
    completeReception: vi.fn(), discardReception: vi.fn(), getReception: vi.fn(),
    getReceptions: vi.fn(), getUnattributedReceptionEntries: vi.fn(),
}));

const LINE = { lot_number: "SYN", expiry_date: "2027-05-01", quantity: "2.00" };
const operation = (overrides = {}) => ({
    operation_id: "op-1", status: "pending", evidence_level: "intent", created_at: "2026-11-05T10:00:00Z",
    resolved_at: null, resolved_by_name: "", discard_reason: "", discard_note: "", actor_name: "Ana", is_own: true,
    product_name: "Vacuna", base_unit: "vial", presentation_name: "Vial", conversion_factor_snapshot: "1.0000",
    supplier_name: "Dist X", received_at: null, requested_lines: [LINE], applied_lines: [], lines_total: 1,
    legacy_lots: null, allowed_actions: ["complete", "discard"],
    ...overrides,
});
const withEvidence = (overrides = {}) => operation({
    current_balance: { product_stock_quantity: "9.0000", base_unit: "vial", lots: [{ lot_number: "SYN", quantity_on_hand: "9.0000" }] },
    ledger_since_intent: { entries: [], truncated: false },
    ...overrides,
});

const openList = async (props = {}) => {
    render(<ReceptionsModal onClose={vi.fn()} onChanged={props.onChanged ?? vi.fn()} onNewReception={props.onNewReception ?? vi.fn()} initialFilter={props.initialFilter ?? ""} />);
    await waitFor(() => expect(getReceptions).toHaveBeenCalled());
};

beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    confirmMock.mockResolvedValue(true);
});

describe("descubrimiento sin estado local", () => {
    it("consulta sin ningún identificador y sin leer el navegador", async () => {
        const fromStorage = vi.spyOn(Storage.prototype, "getItem");
        getReceptions.mockResolvedValue({ results: [operation()], next: null, can_supervise: false });

        await openList();

        await screen.findByText("Vacuna");
        expect(getReceptions).toHaveBeenCalledWith({ scope: "own" });
        expect(fromStorage).not.toHaveBeenCalled();
        fromStorage.mockRestore();
    });

    it("muestra cuando el servidor falla y permite reintentar, sin afirmar que no hay nada", async () => {
        getReceptions.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce({ results: [operation()], next: null });

        await openList();

        const alert = await screen.findByRole("alert");
        expect(screen.queryByText(/No hay operaciones en esta vista/)).not.toBeInTheDocument();
        fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
        await screen.findByText("Vacuna");
    });

    it("carga la siguiente página con el cursor del servidor", async () => {
        getReceptions
            .mockResolvedValueOnce({ results: [operation()], next: "http://api/inventory/receptions/?cursor=abc" })
            .mockResolvedValueOnce({ results: [operation({ operation_id: "op-2", product_name: "Otra" })], next: null });

        await openList();
        fireEvent.click(await screen.findByRole("button", { name: "Cargar más" }));

        await screen.findByText("Otra");
        expect(getReceptions).toHaveBeenLastCalledWith({ scope: "own", cursor: "abc" });
        expect(screen.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
    });

    it("una página que llega tarde no se mezcla con el filtro que se eligió después", async () => {
        let deliverLatePage;
        getReceptions
            .mockResolvedValueOnce({ results: [operation()], next: "http://api/inventory/receptions/?cursor=abc" })
            .mockImplementationOnce(() => new Promise(resolve => { deliverLatePage = resolve; }))
            .mockResolvedValueOnce({ results: [operation({ operation_id: "op-3", product_name: "Filtrada" })], next: null });

        await openList();
        fireEvent.click(await screen.findByRole("button", { name: "Cargar más" }));
        await waitFor(() => expect(getReceptions).toHaveBeenLastCalledWith({ scope: "own", cursor: "abc" }));
        fireEvent.click(screen.getByRole("button", { name: "Sin resolver" }));
        await screen.findByText("Filtrada");

        await act(async () => {
            deliverLatePage({ results: [operation({ operation_id: "op-2", product_name: "Tardía" })], next: "http://api/inventory/receptions/?cursor=vieja" });
        });

        expect(screen.queryByText("Tardía")).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
    });
});

describe("candidatas ambiguas", () => {
    const candidates = () => {
        getReceptions.mockResolvedValue({
            results: [operation({ operation_id: "op-1" }), operation({ operation_id: "op-2" })],
            next: null,
        });
    };

    it("no elige por el usuario aunque sean idénticas ni actúa al consultar", async () => {
        candidates();

        await openList({ initialFilter: "pending" });

        const rows = await screen.findAllByRole("button", { name: /Vacuna/ });
        expect(rows).toHaveLength(2);
        expect(rows.every(row => row.getAttribute("aria-pressed") === "false")).toBe(true);
        expect(getReception).not.toHaveBeenCalled();
        expect(screen.queryByRole("button", { name: "Completar esta recepción" })).not.toBeInTheDocument();
        expect(completeReception).not.toHaveBeenCalled();
        expect(discardReception).not.toHaveBeenCalled();
    });

    it("completa solo la seleccionada, con su identidad y sin reenviar la captura", async () => {
        candidates();
        getReception.mockResolvedValue(withEvidence({ operation_id: "op-2" }));
        completeReception.mockResolvedValue(withEvidence({ operation_id: "op-2", status: "confirmed", evidence_level: "ledger", allowed_actions: [], applied_lines: [{ movement_id: 7, lot_number: "SYN", quantity_presentation: "2.0000", quantity_base: "2.0000", created_at: "2026-11-05T10:00:01Z" }], ledger_since_intent: undefined }));
        const onChanged = vi.fn();

        await openList({ onChanged });
        const rows = await screen.findAllByRole("button", { name: /Vacuna/ });
        fireEvent.click(rows[1]);
        await waitFor(() => expect(getReception).toHaveBeenCalledWith("op-2"));
        fireEvent.click(await screen.findByRole("button", { name: "Completar esta recepción" }));

        await waitFor(() => expect(completeReception).toHaveBeenCalledTimes(1));
        expect(completeReception).toHaveBeenCalledWith("op-2");
        expect(onChanged).toHaveBeenCalledWith("op-2");
        await screen.findByText(/ya sumó stock/);
    });

    it("no ejecuta si la persona no confirma", async () => {
        candidates();
        confirmMock.mockResolvedValue(false);
        getReception.mockResolvedValue(withEvidence());

        await openList();
        fireEvent.click((await screen.findAllByRole("button", { name: /Vacuna/ }))[0]);
        fireEvent.click(await screen.findByRole("button", { name: "Completar esta recepción" }));

        await waitFor(() => expect(confirmMock).toHaveBeenCalled());
        expect(completeReception).not.toHaveBeenCalled();
    });
});

describe("revisión de una operación", () => {
    it("separa la cantidad histórica del saldo actual", async () => {
        getReceptions.mockResolvedValue({ results: [operation({ status: "confirmed" })], next: null });
        getReception.mockResolvedValue(withEvidence({
            status: "confirmed", evidence_level: "ledger", allowed_actions: [], ledger_since_intent: undefined,
            applied_lines: [{ movement_id: 7, lot_number: "SYN", quantity_presentation: "2.0000", quantity_base: "2.0000", created_at: "2026-11-05T10:00:01Z" }],
        }));

        await openList();
        fireEvent.click(await screen.findByRole("button", { name: /Vacuna/ }));

        const ledger = (await screen.findByText(/libro de movimientos registró/)).closest("div");
        expect(within(ledger).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["SYN", "2", "2"]);
        const balance = screen.getByText(/Saldo actual/).closest("div");
        expect(balance).toHaveTextContent("9 vial");
        expect(balance).toHaveTextContent("no es la cantidad de esta operación");
        expect(screen.queryByRole("button", { name: "Completar esta recepción" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Descartar esta operación" })).not.toBeInTheDocument();
    });

    it("exige motivo para descartar y conserva lo que se escribió", async () => {
        getReceptions.mockResolvedValue({ results: [operation()], next: null });
        getReception.mockResolvedValue(withEvidence());
        discardReception.mockResolvedValue(withEvidence({ status: "discarded", allowed_actions: [], resolved_at: "2026-11-05T11:00:00Z", resolved_by_name: "Ana", discard_reason: "already_registered", ledger_since_intent: undefined }));

        await openList();
        fireEvent.click(await screen.findByRole("button", { name: /Vacuna/ }));
        fireEvent.click(await screen.findByRole("button", { name: "Descartar esta operación" }));
        expect(discardReception).not.toHaveBeenCalled();

        fireEvent.change(screen.getByLabelText("Motivo para descartar"), { target: { value: "already_registered" } });
        fireEvent.change(screen.getByLabelText("Nota"), { target: { value: " remisión 12 " } });
        fireEvent.click(screen.getByRole("button", { name: "Descartar esta operación" }));

        await waitFor(() => expect(discardReception).toHaveBeenCalledWith("op-1", { reason: "already_registered", note: "remisión 12" }));
        await screen.findByText(/No sumó stock/);
    });

    it("tras un conflicto muestra lo que el servidor sabe ahora, sin reintentar", async () => {
        getReceptions.mockResolvedValue({ results: [operation()], next: null });
        getReception
            .mockResolvedValueOnce(withEvidence())
            .mockResolvedValueOnce(withEvidence({ status: "confirmed", evidence_level: "ledger", allowed_actions: [], ledger_since_intent: undefined, applied_lines: [{ movement_id: 7, lot_number: "SYN", quantity_presentation: "2.0000", quantity_base: "2.0000", created_at: "2026-11-05T10:00:01Z" }] }));
        discardReception.mockRejectedValue({ response: { status: 409, data: { code: "reception_already_confirmed", message: "Esta recepción ya sumó stock y no puede descartarse." } } });

        await openList();
        fireEvent.click(await screen.findByRole("button", { name: /Vacuna/ }));
        fireEvent.change(await screen.findByLabelText("Motivo para descartar"), { target: { value: "not_received" } });
        fireEvent.click(screen.getByRole("button", { name: "Descartar esta operación" }));

        await screen.findByText(/ya sumó stock el/);
        expect(discardReception).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole("button", { name: "Descartar esta operación" })).not.toBeInTheDocument();
    });

    it("una operación ajena no ofrece completarla", async () => {
        getReceptions.mockResolvedValue({ results: [operation({ is_own: false })], next: null, can_supervise: true });
        getReception.mockResolvedValue(withEvidence({ is_own: false, allowed_actions: ["discard"] }));

        await openList();
        fireEvent.click(await screen.findByRole("button", { name: /Vacuna/ }));

        await screen.findByRole("button", { name: "Descartar esta operación" });
        expect(screen.queryByRole("button", { name: "Completar esta recepción" })).not.toBeInTheDocument();
        expect(screen.getByText(/Solo Ana puede completarla/)).toBeInTheDocument();
        expect(screen.getByRole("group", { name: "Alcance" })).toBeInTheDocument();
    });

    it("un recibo antiguo declara su límite y no muestra cantidades inventadas", async () => {
        const legacy = { status: "confirmed", evidence_level: "legacy_receipt", requested_lines: null, legacy_lots: [{ lot_number: "OLD", expiry_date: null }], allowed_actions: [], lines_total: 0 };
        getReceptions.mockResolvedValue({ results: [operation(legacy)], next: null });
        getReception.mockResolvedValue(withEvidence({ ...legacy, ledger_since_intent: undefined }));

        await openList();
        fireEvent.click(await screen.findByRole("button", { name: /sin cantidades registradas/ }));

        await screen.findByText(/no conserva cantidades/);
        expect(screen.queryByText(/libro de movimientos registró/)).not.toBeInTheDocument();
        expect(screen.queryByText(/Lo capturado/)).not.toBeInTheDocument();
    });
});

describe("entradas sin identidad", () => {
    it("explica el procedimiento y deja la recepción nueva como acción explícita", async () => {
        getReceptions.mockResolvedValue({ results: [], next: null });
        getUnattributedReceptionEntries.mockResolvedValue({
            results: [{ id: 3, created_at: "2026-11-01T10:00:00Z", product_name: "Vacuna", presentation_name: "Vial", lot_number: "L9", quantity: "4.0000", quantity_unit: "base", actor_name: "Ana" }],
            next: null,
        });
        const onNewReception = vi.fn();

        await openList({ onNewReception });
        fireEvent.click(screen.getByRole("button", { name: "Entradas sin identidad" }));

        await screen.findByText("L9");
        expect(screen.getByText(/no puede decir a qué intento corresponden/)).toBeInTheDocument();
        expect(screen.getByText(/no hay nada que repetir ni que corregir/)).toBeInTheDocument();
        expect(onNewReception).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: "Registrar una recepción nueva" }));
        expect(onNewReception).toHaveBeenCalledTimes(1);
    });

    it("carga la siguiente página de entradas con su propio cursor", async () => {
        const entry = (id, lot) => ({ id, created_at: "2026-11-01T10:00:00Z", product_name: "Vacuna", presentation_name: "Vial", lot_number: lot, quantity: "4.0000", quantity_unit: "base", actor_name: "Ana" });
        getReceptions.mockResolvedValue({ results: [], next: null });
        getUnattributedReceptionEntries
            .mockResolvedValueOnce({ results: [entry(3, "L9")], next: "http://api/inventory/receptions/unattributed/?cursor=xyz" })
            .mockResolvedValueOnce({ results: [entry(4, "L10")], next: null });

        await openList();
        fireEvent.click(screen.getByRole("button", { name: "Entradas sin identidad" }));
        fireEvent.click(await screen.findByRole("button", { name: "Cargar más" }));

        await screen.findByText("L10");
        expect(screen.getByText("L9")).toBeInTheDocument();
        expect(getUnattributedReceptionEntries).toHaveBeenLastCalledWith({ scope: "own", cursor: "xyz" });
        expect(getReceptions).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
    });
});
