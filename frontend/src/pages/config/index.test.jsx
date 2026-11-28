/**
 * Configuración por capacidad y por ruta (ADR p70 D8, plan F1.2) y sus estados
 * de guardado (F1.3, F1.5): borrador frente a lo guardado, aviso y bloqueo al
 * salir, solo lo cambiado viaja, error de carga con reintento y confirmación de
 * las reglas que cambian cómo se cobra.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

let auth;
const getConfiguration = vi.fn();
const getServices = vi.fn();
const updateOrgSettings = vi.fn();
const replaceSchedule = vi.fn();
const confirmMock = vi.fn();

vi.mock("../../auth/authContext", () => ({ useAuth: () => auth }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => confirmMock }));
vi.mock("../../api/organizations", () => ({
    getConfiguration: (...a) => getConfiguration(...a),
    updateOrgSettings: (...a) => updateOrgSettings(...a),
    replaceSchedule: (...a) => replaceSchedule(...a),
}));
vi.mock("../../api/billing", () => ({ getServices: (...a) => getServices(...a) }));
vi.mock("sonner", () => ({
    toast: { loading: vi.fn(() => "t"), success: vi.fn(), error: vi.fn(), info: vi.fn(), dismiss: vi.fn() },
}));
vi.mock("./ClinicSection", () => ({ default: () => <p>Apartado Clínica</p> }));
vi.mock("./ServicesSection", () => ({ default: () => <p>Apartado Servicios</p> }));
vi.mock("./HistorySection", () => ({ default: () => <p>Apartado Historial</p> }));
vi.mock("./ClosuresSection", () => ({ default: () => <p>Apartado Cierres</p> }));

import { toast } from "sonner";
import Config from "../config";
// Precarga de los apartados reales que el layout trae con `lazy`: con la suite
// completa la primera carga diferida puede pasar del segundo de `findBy`.
import "./RulesSection";
import "./ScheduleSection";

const LAZY = { timeout: 5000 };

const SETTINGS = {
    require_confirmation_before_start: false, allow_anonymous_walkin: false,
    auto_create_medical_record: false, show_status_change_history: true,
    require_open_cash_session: false, allow_post_unpaid: false, credit_default_days: 30,
    default_appointment_duration_minutes: 30,
};

const open = (weekday) => ({
    weekday, is_closed: false, opens_at: "09:00:00", closes_at: "18:00:00",
    has_break: false, break_start: null, break_end: null,
});
const WEEK = [1, 2, 3, 4, 5, 6].map(open).concat([{
    weekday: 7, is_closed: true, opens_at: null, closes_at: null, has_break: false, break_start: null, break_end: null,
}]);

const withPerms = (role, perms) => {
    const set = new Set(perms);
    auth = {
        user: { role, organization: 1, organization_name: "Clínica" },
        token: "t",
        initializing: false,
        can: (code) => set.has(code),
        canAny: (codes) => codes.some((code) => set.has(code)),
    };
};

let router;
const renderAt = (path) => {
    router = createMemoryRouter([
        { path: "/", element: <p>Inicio</p> },
        { path: "/config", element: <Config /> },
        { path: "/config/:section", element: <Config /> },
    ], { initialEntries: [path] });
    return render(<RouterProvider router={router} />);
};

const menu = () => screen.getByRole("navigation", { name: "Apartados de configuración" });

beforeEach(() => {
    vi.clearAllMocks();
    getConfiguration.mockResolvedValue({
        organization: { timezone: "America/Mexico_City" }, settings: SETTINGS, schedule: WEEK,
    });
    getServices.mockResolvedValue([]);
    confirmMock.mockResolvedValue(true);
});

describe("Configuración · acceso", () => {
    it("sin ninguna capacidad de configuración vuelve al inicio", async () => {
        withPerms("VET", ["appointment.list"]);
        renderAt("/config/clinic");
        expect(await screen.findByText("Inicio")).toBeInTheDocument();
    });

    it("el rol ADMIN sin la capacidad tampoco entra", async () => {
        withPerms("ADMIN", []);
        renderAt("/config");
        expect(await screen.findByText("Inicio")).toBeInTheDocument();
    });

    it("/config abre el primer apartado visible", async () => {
        withPerms("ADMIN", ["organization.update", "service.create"]);
        renderAt("/config");
        expect(await screen.findByText("Apartado Clínica")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Clínica/ })).toHaveAttribute("aria-current", "page");
    });

    it("quien solo gestiona servicios ve solo Servicios y no se pide la clínica", async () => {
        withPerms("ASSISTANT", ["service.update"]);
        renderAt("/config");
        expect(await screen.findByText("Apartado Servicios")).toBeInTheDocument();
        const items = Array.from(menu().querySelectorAll("button")).map((b) => b.textContent);
        expect(items).toEqual(["Servicios"]);
        expect(getConfiguration).not.toHaveBeenCalled();
    });

    it("un apartado sin permiso lleva al primero visible", async () => {
        withPerms("ASSISTANT", ["service.update"]);
        renderAt("/config/clinic");
        expect(await screen.findByText("Apartado Servicios")).toBeInTheDocument();
    });
});

describe("Configuración · rutas profundas", () => {
    it.each([
        ["/config/services", "Apartado Servicios"],
        ["/config/history", "Apartado Historial"],
    ])("%s abre su apartado", async (path, text) => {
        withPerms("ADMIN", ["organization.update", "service.create"]);
        renderAt(path);
        expect(await screen.findByText(text)).toBeInTheDocument();
    });

    it("Cobros y Atención reparten las reglas", async () => {
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/billing");
        expect(await screen.findByText("Caja abierta obligatoria", {}, LAZY)).toBeInTheDocument();
        expect(screen.queryByText("Confirmar la cita antes de atenderla")).toBeNull();
    });
});

describe("Configuración · guardado", () => {
    it("un ASSISTANT con organization.update edita las reglas, y solo viaja lo que cambió", async () => {
        const user = userEvent.setup({ delay: null });
        updateOrgSettings.mockResolvedValue({ ...SETTINGS, require_confirmation_before_start: true });
        withPerms("ASSISTANT", ["organization.update"]);
        renderAt("/config/care");
        await user.click(await screen.findByRole("switch", { name: "Confirmar la cita antes de atenderla" }, LAZY));
        await user.click(screen.getByRole("button", { name: "Guardar reglas" }));
        await waitFor(() => expect(updateOrgSettings).toHaveBeenCalledWith({
            require_confirmation_before_start: true,
        }));
        // Ya guardado, el apartado deja de marcarse.
        await waitFor(() => expect(screen.queryByText("Cambios sin guardar")).toBeNull());
    });

    it("un cambio sin guardar se marca en el menú y se puede descartar", async () => {
        const user = userEvent.setup({ delay: null });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/care");
        const toggle = await screen.findByRole("switch", { name: "Atender sin registrar la mascota" }, LAZY);
        await user.click(toggle);
        expect(screen.getByText("Cambios sin guardar")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Atención.*cambios sin guardar/ })).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Descartar" }));
        expect(screen.queryByText("Cambios sin guardar")).toBeNull();
        expect(screen.getByRole("switch", { name: "Atender sin registrar la mascota" }))
            .toHaveAttribute("aria-checked", "false");
    });

    it("el borrador sobrevive al cambiar de apartado", async () => {
        const user = userEvent.setup({ delay: null });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/care");
        await user.click(await screen.findByRole("switch", { name: "Atender sin registrar la mascota" }, LAZY));
        await user.click(screen.getByRole("button", { name: /Cobros/ }));
        expect(confirmMock).not.toHaveBeenCalled();
        await user.click(screen.getByRole("button", { name: /Atención/ }));
        expect(screen.getByRole("switch", { name: "Atender sin registrar la mascota" }))
            .toHaveAttribute("aria-checked", "true");
    });

    it("salir con cambios sin guardar pide confirmación; si se cancela, se queda", async () => {
        const user = userEvent.setup({ delay: null });
        confirmMock.mockResolvedValue(false);
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/care");
        await user.click(await screen.findByRole("switch", { name: "Atender sin registrar la mascota" }, LAZY));
        await act(async () => { router.navigate("/"); });
        await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            title: "Cambios sin guardar",
            message: expect.stringContaining("Atención"),
        })));
        expect(screen.queryByText("Inicio")).toBeNull();
        expect(router.state.location.pathname).toBe("/config/care");
    });

    it("sin cambios sale sin preguntar", async () => {
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/care");
        await screen.findByRole("switch", { name: "Atender sin registrar la mascota" }, LAZY);
        await act(async () => { router.navigate("/"); });
        expect(await screen.findByText("Inicio")).toBeInTheDocument();
        expect(confirmMock).not.toHaveBeenCalled();
    });

    it("si la carga falla, se puede reintentar", async () => {
        const user = userEvent.setup({ delay: null });
        getConfiguration.mockRejectedValueOnce({ response: { status: 500, data: {} } });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/care");
        await user.click(await screen.findByRole("button", { name: "Reintentar" }));
        expect(await screen.findByRole("switch", { name: "Atender sin registrar la mascota" }, LAZY)).toBeInTheDocument();
        expect(getConfiguration).toHaveBeenCalledTimes(2);
    });
});

describe("Configuración · reglas de cobro (F1.5)", () => {
    it("activar la caja obligatoria pide confirmación; si se cancela, no cambia", async () => {
        const user = userEvent.setup({ delay: null });
        confirmMock.mockResolvedValue(false);
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/billing");
        const toggle = await screen.findByRole("switch", { name: "Caja abierta obligatoria" }, LAZY);
        await user.click(toggle);
        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ title: "Exigir caja abierta" }));
        expect(toggle).toHaveAttribute("aria-checked", "false");
        expect(screen.queryByText("Cambios sin guardar")).toBeNull();
    });

    it("permitir crédito, confirmado, muestra el plazo", async () => {
        const user = userEvent.setup({ delay: null });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/billing");
        await user.click(await screen.findByRole("switch", { name: "Permitir cobros a crédito" }, LAZY));
        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ title: "Permitir cobros a crédito" }));
        expect(screen.getByLabelText("Plazo de crédito predeterminado")).toHaveValue(30);
    });

    it("un error del plazo se muestra en su campo", async () => {
        const user = userEvent.setup({ delay: null });
        getConfiguration.mockResolvedValue({
            organization: {}, settings: { ...SETTINGS, allow_post_unpaid: true }, schedule: WEEK,
        });
        updateOrgSettings.mockRejectedValue({ response: { status: 400, data: {
            code: "validation_error",
            errors: { credit_default_days: ["El plazo de crédito debe estar entre 1 y 365 días."] },
        } } });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/billing");
        const input = await screen.findByLabelText("Plazo de crédito predeterminado", {}, LAZY);
        await user.clear(input);
        await user.type(input, "45");
        await user.click(screen.getByRole("button", { name: "Guardar reglas" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("entre 1 y 365 días");
    });
});

describe("Configuración · duración de una cita (F2.3)", () => {
    it("Atención la edita y solo viaja ese campo", async () => {
        const user = userEvent.setup({ delay: null });
        updateOrgSettings.mockResolvedValue({ ...SETTINGS, default_appointment_duration_minutes: 45 });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/care");
        const input = await screen.findByLabelText("Duración habitual de una cita", {}, LAZY);
        expect(input).toHaveValue(30);
        fireEvent.change(input, { target: { value: "45" } });
        expect(screen.getByRole("button", { name: /Atención.*cambios sin guardar/ })).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Guardar reglas" }));
        await waitFor(() => expect(updateOrgSettings).toHaveBeenCalledWith({
            default_appointment_duration_minutes: 45,
        }));
    });

    it("fuera de 5–240 minutos no se envía y se dice por qué", async () => {
        const user = userEvent.setup({ delay: null });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/care");
        const input = await screen.findByLabelText("Duración habitual de una cita", {}, LAZY);
        fireEvent.change(input, { target: { value: "300" } });
        await user.click(screen.getByRole("button", { name: "Guardar reglas" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("La duración debe estar entre 5 y 240 minutos.");
        fireEvent.change(input, { target: { value: "" } });
        await user.click(screen.getByRole("button", { name: "Guardar reglas" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("entre 5 y 240 minutos");
        expect(updateOrgSettings).not.toHaveBeenCalled();
    });

    it("Cobros no la muestra", async () => {
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/billing");
        await screen.findByText("Caja abierta obligatoria", {}, LAZY);
        expect(screen.queryByLabelText("Duración habitual de una cita")).toBeNull();
    });
});

describe("Configuración · horario (F1.3)", () => {
    it("el horario muestra también los cierres excepcionales (F2.1)", async () => {
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/schedule");
        expect(await screen.findByText("Apartado Cierres", {}, LAZY)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Guardar horario" })).toBeInTheDocument();
    });

    it("un día inválido se marca en su fila y no se envía", async () => {
        const user = userEvent.setup({ delay: null });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/schedule");
        const closes = await screen.findByLabelText("Salida del miércoles", {}, LAZY);
        fireEvent.change(closes, { target: { value: "08:00" } });
        await user.click(screen.getByRole("button", { name: "Guardar horario" }));
        expect(await screen.findByText("La hora de apertura debe ser anterior a la de cierre.")).toBeInTheDocument();
        expect(replaceSchedule).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalled();
    });

    it("el error del servidor para un día se pinta en esa fila", async () => {
        const user = userEvent.setup({ delay: null });
        replaceSchedule.mockRejectedValue({ response: { status: 400, data: {
            code: "validation_error",
            errors: { day_2: { non_field_errors: ["El descanso debe quedar dentro del horario de apertura."] } },
        } } });
        withPerms("ADMIN", ["organization.update"]);
        renderAt("/config/schedule");
        await user.click(await screen.findByLabelText("Martes con descanso", {}, LAZY));
        await user.click(screen.getByRole("button", { name: "Guardar horario" }));
        const alert = await screen.findByRole("alert");
        expect(alert).toHaveTextContent("El descanso debe quedar dentro del horario de apertura.");
        expect(alert.closest("tr")).toHaveTextContent("Martes");
    });
});
