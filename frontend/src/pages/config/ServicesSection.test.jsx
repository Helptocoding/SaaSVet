/**
 * Servicios con ciclo de vida y permisos (ADR p70, plan F1.7).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

let perms;
const createService = vi.fn();
const updateService = vi.fn();
const deleteService = vi.fn();
const confirmMock = vi.fn();

vi.mock("../../api/billing", () => ({
    createService: (...a) => createService(...a),
    updateService: (...a) => updateService(...a),
    deleteService: (...a) => deleteService(...a),
}));
vi.mock("../../auth/authContext", () => ({
    useAuth: () => ({ can: (code) => perms.has(code), user: { organization_tax_rate: "0.1600" } }),
}));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => confirmMock }));
vi.mock("sonner", () => ({
    toast: { loading: vi.fn(() => "t"), success: vi.fn(), error: vi.fn(), info: vi.fn(), dismiss: vi.fn() },
}));

import { toast } from "sonner";
import ServicesSection from "./ServicesSection";

const SERVICES = [
    { public_id: "a", name: "Consulta general", base_price: "350.00", price_with_tax: "406.00", is_active: true, specialty: "" },
    { public_id: "b", name: "Baño medicado", base_price: "200.00", price_with_tax: "232.00", is_active: false, specialty: "" },
];

const renderSection = (props = {}) => {
    const onServicesChange = vi.fn();
    render(<ServicesSection services={SERVICES} onServicesChange={onServicesChange} {...props} />);
    return { onServicesChange };
};

beforeEach(() => {
    vi.clearAllMocks();
    perms = new Set(["service.create", "service.update", "service.destroy"]);
    confirmMock.mockResolvedValue(true);
});

describe("ServicesSection", () => {
    it("cada acción según su permiso", () => {
        perms = new Set(["service.update"]);
        renderSection();
        expect(screen.queryByRole("button", { name: /Nuevo servicio/ })).toBeNull();
        expect(screen.getByRole("button", { name: "Editar Consulta general" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Eliminar Consulta general" })).toBeNull();
    });

    it("los inactivos se ocultan hasta pedirlos", async () => {
        const user = userEvent.setup({ delay: null });
        renderSection();
        expect(screen.queryByText("Baño medicado")).toBeNull();
        await user.click(screen.getByLabelText("Mostrar inactivos (1)"));
        expect(screen.getByText("Baño medicado")).toBeInTheDocument();
        expect(screen.getByText("Inactivo")).toBeInTheDocument();
    });

    it("desactivar explica qué deja de pasar y lo guarda", async () => {
        const user = userEvent.setup({ delay: null });
        updateService.mockResolvedValue({});
        const { onServicesChange } = renderSection();
        await user.click(screen.getByRole("button", { name: "Desactivar" }));
        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            title: "Desactivar «Consulta general»",
            message: expect.stringContaining("no aparece al cobrar"),
        }));
        await waitFor(() => expect(updateService).toHaveBeenCalledWith("a", { is_active: false }));
        expect(onServicesChange).toHaveBeenCalled();
    });

    it("activar un inactivo no pide confirmación", async () => {
        const user = userEvent.setup({ delay: null });
        updateService.mockResolvedValue({});
        renderSection();
        await user.click(screen.getByLabelText("Mostrar inactivos (1)"));
        await user.click(screen.getByRole("button", { name: "Activar" }));
        await waitFor(() => expect(updateService).toHaveBeenCalledWith("b", { is_active: true }));
        expect(confirmMock).not.toHaveBeenCalled();
    });

    it("si eliminar choca con su historial (409), muestra el motivo y ofrece desactivarlo", async () => {
        const user = userEvent.setup({ delay: null });
        deleteService.mockRejectedValue({ response: { status: 409, data: {
            code: "resource_has_dependencies", message: "Este servicio tiene 3 registros asociados.", protected_count: 3,
        } } });
        updateService.mockResolvedValue({});
        renderSection();
        await user.click(screen.getByRole("button", { name: "Eliminar Consulta general" }));
        await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(2));
        expect(confirmMock).toHaveBeenLastCalledWith(expect.objectContaining({
            title: "No se puede eliminar",
            message: expect.stringContaining("3 registros asociados"),
            confirmText: "Desactivar",
        }));
        await waitFor(() => expect(updateService).toHaveBeenCalledWith("a", { is_active: false }));
    });

    it("un error de un campo del formulario se muestra en ese campo", async () => {
        const user = userEvent.setup({ delay: null });
        createService.mockRejectedValue({ response: { status: 400, data: {
            code: "validation_error", errors: { name: ["El nombre contiene caracteres no permitidos."] },
        } } });
        renderSection();
        await user.click(screen.getByRole("button", { name: /Nuevo servicio/ }));
        await user.type(screen.getByLabelText("Nombre *"), "Consulta <b>");
        await user.type(screen.getByLabelText("Precio sin IVA *"), "100");
        await user.click(screen.getByRole("button", { name: /Crear/ }));
        expect(await screen.findByRole("alert")).toHaveTextContent("caracteres no permitidos");
        expect(toast.success).not.toHaveBeenCalled();
    });

    it("la edición tiene el interruptor Activo con su efecto", async () => {
        const user = userEvent.setup({ delay: null });
        updateService.mockResolvedValue({});
        renderSection();
        await user.click(screen.getByRole("button", { name: "Editar Consulta general" }));
        await user.click(screen.getByRole("switch", { name: "Activo" }));
        await user.click(screen.getByRole("button", { name: /Guardar/ }));
        await waitFor(() => expect(updateService).toHaveBeenCalledWith("a", expect.objectContaining({ is_active: false })));
    });
});
