/**
 * Cierres excepcionales (ADR p70 D6, plan F2.1): lista, alta con validación
 * previa, aviso de citas en esos días, cancelación confirmada y errores.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getClosures = vi.fn();
const createClosure = vi.fn();
const cancelClosure = vi.fn();
const confirmMock = vi.fn();
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("sonner", () => ({ toast: toastMock }));
vi.mock("../../api/organizations", () => ({
    getClosures: (...a) => getClosures(...a),
    createClosure: (...a) => createClosure(...a),
    cancelClosure: (...a) => cancelClosure(...a),
}));
vi.mock("../../auth/authContext", () => ({
    useAuth: () => ({ user: { organization_timezone: "America/Mexico_City" } }),
}));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => confirmMock }));
vi.mock("../../components/DateField", () => ({
    default: ({ id, value, onChange, disabled }) => (
        <input id={id} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
    ),
}));

import { closureErrorsFor } from "../../features/config/closures";
import ClosuresSection from "./ClosuresSection";

const closure = (overrides = {}) => ({
    public_id: "c1",
    start_date: "2026-12-24",
    end_date: "2026-12-25",
    reason: "Navidad",
    is_active: true,
    ...overrides,
});

const renderSection = () => render(<MemoryRouter><ClosuresSection /></MemoryRouter>);

const fillForm = async (user, { start = "2026-12-31", end = "2026-12-31", reason = "Año nuevo" } = {}) => {
    await user.click(await screen.findByRole("button", { name: /Nuevo cierre/ }));
    fireEvent.change(screen.getByLabelText("Primer día"), { target: { value: start } });
    fireEvent.change(screen.getByLabelText("Último día"), { target: { value: end } });
    if (reason) await user.type(screen.getByLabelText("Motivo"), reason);
};

beforeEach(() => {
    vi.clearAllMocks();
});

describe("closureErrorsFor", () => {
    it("pide fechas y motivo, y que el final no sea anterior", () => {
        expect(closureErrorsFor({ start_date: "", end_date: "", reason: " " })).toEqual({
            start_date: "Elige el primer día.",
            end_date: "Elige el último día.",
            reason: "Escribe el motivo del cierre (por ejemplo, «Día festivo»).",
        });
        expect(closureErrorsFor({ start_date: "2026-12-26", end_date: "2026-12-25", reason: "x" }))
            .toEqual({ end_date: "La fecha final no puede ser anterior a la inicial." });
        expect(closureErrorsFor({ start_date: "2026-12-25", end_date: "2026-12-25", reason: "x" })).toEqual({});
    });
});

describe("ClosuresSection", () => {
    it("lista los cierres próximos con su motivo", async () => {
        getClosures.mockResolvedValue([closure()]);
        renderSection();
        const list = await screen.findByRole("list", { name: "Cierres próximos" });
        expect(within(list).getByText("Navidad")).toBeInTheDocument();
        expect(within(list).getByRole("button", { name: /Cancelar cierre del/ })).toBeInTheDocument();
    });

    it("sin cierres lo dice", async () => {
        getClosures.mockResolvedValue([]);
        renderSection();
        expect(await screen.findByText("No hay cierres próximos.")).toBeInTheDocument();
    });

    it("si falla la carga, permite reintentar", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures
            .mockRejectedValueOnce({ response: { status: 500, data: {} } })
            .mockResolvedValueOnce([closure()]);
        renderSection();
        await user.click(await screen.findByRole("button", { name: "Reintentar" }));
        expect(await screen.findByText("Navidad")).toBeInTheDocument();
        expect(getClosures).toHaveBeenCalledTimes(2);
    });

    it("no envía nada si falta el motivo", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures.mockResolvedValue([]);
        renderSection();
        await fillForm(user, { reason: "" });
        await user.click(screen.getByRole("button", { name: "Registrar cierre" }));
        expect(await screen.findByText(/Escribe el motivo del cierre/)).toBeInTheDocument();
        expect(createClosure).not.toHaveBeenCalled();
    });

    it("registra, recarga y avisa de las citas de esos días", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures.mockResolvedValueOnce([]).mockResolvedValueOnce([closure({ reason: "Año nuevo" })]);
        createClosure.mockResolvedValue({ ...closure(), affected_appointments: 3 });
        renderSection();
        await fillForm(user);
        await user.click(screen.getByRole("button", { name: "Registrar cierre" }));
        await waitFor(() => expect(createClosure).toHaveBeenCalledWith({
            start_date: "2026-12-31", end_date: "2026-12-31", reason: "Año nuevo",
        }));
        expect(await screen.findByText(/Hay 3 citas por atender en esos días/)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Ver citas" })).toBeInTheDocument();
        expect(await screen.findByText("Año nuevo")).toBeInTheDocument();
        expect(getClosures).toHaveBeenCalledTimes(2);
    });

    it("sin citas esos días no muestra aviso", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures.mockResolvedValue([]);
        createClosure.mockResolvedValue({ ...closure(), affected_appointments: 0 });
        renderSection();
        await fillForm(user);
        await user.click(screen.getByRole("button", { name: "Registrar cierre" }));
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith("Cierre registrado"));
        expect(screen.queryByText(/citas por atender/)).not.toBeInTheDocument();
    });

    it("un error de campo del servidor queda en su campo", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures.mockResolvedValue([]);
        createClosure.mockRejectedValue({
            response: { status: 400, data: { code: "validation_error", errors: { end_date: ["Ese cierre ya pasó; registra fechas de hoy en adelante."] } } },
        });
        renderSection();
        await fillForm(user);
        await user.click(screen.getByRole("button", { name: "Registrar cierre" }));
        expect(await screen.findByText("Ese cierre ya pasó; registra fechas de hoy en adelante.")).toBeInTheDocument();
    });

    it("un cruce con otro cierre (409) va a un aviso, sin cerrar el formulario", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures.mockResolvedValue([]);
        createClosure.mockRejectedValue({
            response: { status: 409, data: { code: "closure_overlap", message: "Ya hay un cierre registrado que se cruza con esas fechas." } },
        });
        renderSection();
        await fillForm(user);
        await user.click(screen.getByRole("button", { name: "Registrar cierre" }));
        await waitFor(() => expect(toastMock.error)
            .toHaveBeenCalledWith("Ya hay un cierre registrado que se cruza con esas fechas."));
        expect(screen.getByLabelText("Motivo")).toHaveValue("Año nuevo");
    });

    it("cancelar pide confirmación y recarga", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures.mockResolvedValueOnce([closure()]).mockResolvedValueOnce([]);
        confirmMock.mockResolvedValue(true);
        cancelClosure.mockResolvedValue({ ...closure(), is_active: false });
        renderSection();
        await user.click(await screen.findByRole("button", { name: /Cancelar cierre del/ }));
        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ dangerMode: true }));
        await waitFor(() => expect(cancelClosure).toHaveBeenCalledWith("c1"));
        expect(await screen.findByText("No hay cierres próximos.")).toBeInTheDocument();
    });

    it("si no se confirma, no cancela", async () => {
        const user = userEvent.setup({ delay: null });
        getClosures.mockResolvedValue([closure()]);
        confirmMock.mockResolvedValue(false);
        renderSection();
        await user.click(await screen.findByRole("button", { name: /Cancelar cierre del/ }));
        expect(cancelClosure).not.toHaveBeenCalled();
    });
});
