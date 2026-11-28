/**
 * Zona horaria en Configuración → Clínica (ADR p70 D1): se elige de un catálogo
 * cerrado de México, se confirma antes de cambiarla y, si hay citas por atender,
 * el 409 del servidor deja la zona guardada y ofrece ir a Citas.
 */
import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateOrg = vi.fn();
const confirmMock = vi.fn();
const refreshUser = vi.fn();
const navigate = vi.fn();

vi.mock("../../api/organizations", () => ({ updateOrg: (...a) => updateOrg(...a) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => confirmMock }));
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({ refreshUser }) }));
vi.mock("sonner", () => ({
    toast: { loading: vi.fn(() => "t1"), success: vi.fn(), error: vi.fn(), info: vi.fn(), dismiss: vi.fn() },
}));
vi.mock("react-router-dom", async (importOriginal) => ({
    ...(await importOriginal()),
    useNavigate: () => navigate,
}));

import { toast } from "sonner";
import TIMEZONES from "../../features/config/timezones.json";
import ClinicSection from "./ClinicSection";

const ORG = { name: "Clínica Luna", display_name: "", phone: "5512345678", timezone: "America/Mexico_City", tax_rate: "0.1600" };

/** Host con el estado del padre (`config/index.jsx`): borrador y lo guardado. */
function Host({ initial = ORG }) {
    const [org, setOrg] = useState(initial);
    const [savedOrg, setSavedOrg] = useState(initial);
    return (
        <MemoryRouter>
            <ClinicSection
                org={org}
                savedOrg={savedOrg}
                onOrgChange={setOrg}
                onSaved={(updated) => { setOrg(updated); setSavedOrg(updated); }}
            />
        </MemoryRouter>
    );
}

const zoneSelect = () => screen.getByRole("combobox", { name: "Zona horaria" });
const save = () => screen.getByRole("button", { name: "Guardar cambios" });

beforeEach(() => {
    vi.clearAllMocks();
});

describe("ClinicSection · zona horaria", () => {
    it("ofrece solo el catálogo de México, con nombres para personas", () => {
        render(<Host />);
        const options = Array.from(zoneSelect().options).map((o) => [o.value, o.textContent]);
        expect(options).toEqual(TIMEZONES);
        expect(zoneSelect()).toHaveValue("America/Mexico_City");
    });

    it("una zona guardada fuera del catálogo se muestra, pero no se puede volver a elegir", () => {
        render(<Host initial={{ ...ORG, timezone: "UTC" }} />);
        const legacy = screen.getByRole("option", { name: /UTC \(sin soporte/ });
        expect(legacy).toBeDisabled();
        expect(zoneSelect()).toHaveValue("UTC");
    });

    it("guardar sin cambiar la zona no pide confirmación ni refresca la sesión", async () => {
        const user = userEvent.setup({ delay: null });
        updateOrg.mockResolvedValue({ ...ORG, display_name: "Luna Centro" });
        render(<Host />);
        await user.type(screen.getByLabelText("Nombre comercial"), "Luna Centro");
        await user.click(save());
        // Plan F1.3 (C16): solo viaja lo que cambió.
        await waitFor(() => expect(updateOrg).toHaveBeenCalledWith({ display_name: "Luna Centro" }));
        expect(confirmMock).not.toHaveBeenCalled();
        expect(refreshUser).not.toHaveBeenCalled();
    });

    it("sin cambios no se envía nada", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Host />);
        await user.click(save());
        expect(updateOrg).not.toHaveBeenCalled();
        expect(toast.info).toHaveBeenCalledWith("No hay cambios que guardar.");
    });

    it("un error de un campo se muestra en ese campo", async () => {
        const user = userEvent.setup({ delay: null });
        updateOrg.mockRejectedValue({ response: { status: 400, data: {
            code: "validation_error", errors: { email: ["Introduzca una dirección de correo electrónico válida."] },
        } } });
        render(<Host />);
        await user.type(screen.getByLabelText("Correo electrónico"), "mal@");
        await user.click(save());
        expect(await screen.findByRole("alert")).toHaveTextContent("correo electrónico válida");
        expect(screen.getByLabelText("Correo electrónico")).toHaveClass("input-error");
    });

    it("el nombre legal es de solo lectura y el complemento de dirección se guarda (ADR p70 D5)", async () => {
        const user = userEvent.setup({ delay: null });
        updateOrg.mockResolvedValue({ ...ORG, address_line2: "Local 3" });
        render(<Host />);
        const legalRow = screen.getByText("Nombre legal").parentElement.parentElement;
        expect(within(legalRow).getByText("Clínica Luna")).toBeInTheDocument();
        expect(screen.queryByRole("textbox", { name: "Nombre legal" })).toBeNull();
        await user.type(screen.getByLabelText("Interior, piso o referencia"), "Local 3");
        await user.click(save());
        await waitFor(() => expect(updateOrg).toHaveBeenCalledWith({ address_line2: "Local 3" }));
    });

    it("el encabezado muestra lo guardado, no lo que se escribe", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Host initial={{ ...ORG, display_name: "Clínica Luna Centro" }} />);
        const field = screen.getByLabelText("Nombre comercial");
        await user.clear(field);
        await user.type(field, "Otro nombre");
        expect(screen.getByText("Clínica Luna Centro")).toBeInTheDocument();
    });

    it("cambiarla pide confirmación; si se cancela, no se guarda", async () => {
        const user = userEvent.setup({ delay: null });
        confirmMock.mockResolvedValue(false);
        render(<Host />);
        await user.selectOptions(zoneSelect(), "America/Cancun");
        await user.click(save());
        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            message: expect.stringContaining("Sureste — Cancún (Quintana Roo)"),
        }));
        expect(updateOrg).not.toHaveBeenCalled();
    });

    it("confirmada, se guarda y la sesión toma la zona nueva", async () => {
        const user = userEvent.setup({ delay: null });
        confirmMock.mockResolvedValue(true);
        updateOrg.mockResolvedValue({ ...ORG, timezone: "America/Cancun" });
        render(<Host />);
        await user.selectOptions(zoneSelect(), "America/Cancun");
        await user.click(save());
        await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1));
        expect(updateOrg).toHaveBeenCalledWith({ timezone: "America/Cancun" });
        expect(toast.success).toHaveBeenCalledWith("Clínica actualizada", { id: "t1" });
        // Ya guardada, otro cambio no la toma como un cambio de zona.
        updateOrg.mockResolvedValue({ ...ORG, timezone: "America/Cancun", city: "Cancún" });
        await user.type(screen.getByLabelText("Ciudad"), "Cancún");
        await user.click(save());
        await waitFor(() => expect(updateOrg).toHaveBeenCalledTimes(2));
        expect(updateOrg).toHaveBeenLastCalledWith({ city: "Cancún" });
        expect(confirmMock).toHaveBeenCalledTimes(1);
    });

    it("con citas por atender, el 409 vuelve a la zona guardada y ofrece ir a Citas", async () => {
        const user = userEvent.setup({ delay: null });
        confirmMock.mockResolvedValue(true);
        const message = "No se puede cambiar la zona horaria: hay 2 citas por atender. Cambia la zona cuando no queden citas futuras.";
        updateOrg.mockRejectedValue({
            response: { status: 409, data: { code: "timezone_change_blocked", message, future_appointments: 2 } },
        });
        render(<Host />);
        await user.selectOptions(zoneSelect(), "America/Cancun");
        await user.click(save());

        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        const [shown, options] = toast.error.mock.calls[0];
        expect(shown).toBe(message);
        expect(options.id).toBe("t1");
        expect(options.action.label).toBe("Ver citas");
        options.action.onClick();
        expect(navigate).toHaveBeenCalledWith("/appointments");

        expect(zoneSelect()).toHaveValue("America/Mexico_City");
        expect(refreshUser).not.toHaveBeenCalled();
        expect(save()).not.toBeDisabled();
    });
});
