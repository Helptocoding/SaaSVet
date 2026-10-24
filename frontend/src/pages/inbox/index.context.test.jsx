import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => Object.fromEntries([
    "authorizeIdentityLink", "claimConversation", "closeConversation", "getAgentSettings",
    "getThreadMessages", "getThreads", "getInboxMetrics", "getWhatsappToken", "releaseConversation",
    "resetContactIdentity", "sendInboxMessage", "setWhatsappToken", "unlinkFamily", "updateAgentSettings",
    "verifyContactIdentity", "markThreadRead", "retryInboxMessage", "getThreadContext",
].map((key) => [key, vi.fn()])));
const permissions = vi.hoisted(() => new Set());
const navigate = vi.hoisted(() => vi.fn());
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({
    can: (permission) => permissions.has(permission), user: { organization_timezone: "America/Tijuana" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";

const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const context = (contact = "ana") => ({
    owner: { public_id: `owner-${contact}`, name: `Cliente ${contact}`, phone: "5551234567" },
    pets: [{ public_id: `pet-${contact}`, name: contact === "ana" ? "Luna" : "Bruno", species: "felino" }],
    last_appointment: { date: "2026-10-20", status: "canceled" },
});
let snapshots;
beforeEach(() => {
    permissions.clear(); permissions.add("agentinbox.send"); permissions.add("patient.retrieve");
    navigate.mockReset();
    Object.values(api).forEach((mock) => mock.mockReset());
    snapshots = Object.fromEntries(["ana", "beto"].map((contact) => [contact, {
        owner_name: contact === "ana" ? "Ana" : "Beto", contact_verification: "staff_verified",
        conversation: { public_id: `session-${contact}`, state: "human_active",
            session_window_open: true, session_window_expires_at: new Date(Date.now()+86400000).toISOString() },
        messages: [{ id: contact === "ana" ? 1 : 2, direction: "in", author_type: "client", status: "processed",
            body: `Mensaje de ${contact}`, created_at: "2026-10-21T12:00:00Z" }], next_before: null,
    }]));
    api.getThreads.mockResolvedValue({ results: ["ana", "beto"].map((contact) => ({
        contact_public_id: contact, channel_account_public_id: "main", owner_name: contact === "ana" ? "Ana" : "Beto",
        conversation_public_id: `session-${contact}`, state: "human_active", session_count: 1,
    })) });
    api.getThreadMessages.mockImplementation(async (contact) => ({ ...snapshots[contact] }));
    api.getThreadContext.mockImplementation(async (contact) => context(contact));
    api.getInboxMetrics.mockResolvedValue(null);
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
async function mount() {
    const view = render(<Inbox />); await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Ana/ })); await act(async () => {});
    return view;
}
async function open() {
    fireEvent.click(screen.getByRole("button", { name: "Ver contexto del cliente" }));
    await act(async () => {});
}
const panel = () => screen.getByRole("region", { name: "Contexto del cliente" });

describe("WA-CTX-01 — contexto del cliente en Inbox", () => {
    it("carga sólo al abrir y llega al expediente correcto en dos clics desde el chat", async () => {
        await mount(); expect(api.getThreadContext).not.toHaveBeenCalled();
        await open();
        expect(api.getThreadContext.mock.calls[0].slice(0, 2)).toEqual(["ana", "main"]);
        expect(within(panel()).getByText("Cliente ana")).toBeVisible();
        expect(within(panel()).getByText("felino")).toBeVisible();
        expect(within(panel()).getByRole("link", { name: "5551234567" })).toHaveAttribute("href", "tel:5551234567");
        expect(within(panel()).getByText(/20 de octubre de 2026/)).toBeVisible();
        expect(within(panel()).getByText(/Cancelada/)).toBeVisible();
        fireEvent.click(within(panel()).getByRole("button", { name: "Abrir expediente de Luna" }));
        expect(navigate).toHaveBeenCalledWith("/pets/pet-ana");
        expect(api.getThreadContext).toHaveBeenCalledTimes(1);
    });
    it("el panel conserva borrador e historial y se pliega con estado accesible", async () => {
        await mount();
        const draft = screen.getByRole("textbox"); fireEvent.change(draft, { target: { value: "Respuesta pendiente" } });
        await open();
        const toggle = screen.getByRole("button", { name: "Ocultar contexto del cliente" });
        expect(toggle).toHaveAttribute("aria-expanded", "true");
        expect(toggle).toHaveAttribute("aria-controls", "inbox-client-context");
        expect(draft).toHaveValue("Respuesta pendiente");
        expect(screen.getByText("Mensaje de ana")).toBeVisible();
        fireEvent.click(toggle);
        expect(screen.getByRole("button", { name: "Ver contexto del cliente" })).toHaveAttribute("aria-expanded", "false");
        expect(within(panel()).queryByText("Luna")).not.toBeInTheDocument();
        expect(draft).toHaveValue("Respuesta pendiente");
    });
    it("muestra carga propia y aborta si se cierra antes de recibir", async () => {
        const pending = deferred(); api.getThreadContext.mockReturnValueOnce(pending.promise);
        await mount(); await open();
        expect(within(panel()).getByRole("status")).toHaveTextContent("Cargando contexto del cliente");
        const signal = api.getThreadContext.mock.calls[0][2].signal;
        fireEvent.click(screen.getByRole("button", { name: "Ocultar contexto del cliente" }));
        expect(signal.aborted).toBe(true);
        await act(async () => pending.resolve(context()));
        expect(within(panel()).queryByText("Luna")).not.toBeInTheDocument();
    });
    it("un error reintenta sólo el contexto sin borrar transcript ni borrador", async () => {
        api.getThreadContext.mockRejectedValueOnce(new Error("offline"));
        await mount(); const draft = screen.getByRole("textbox");
        fireEvent.change(draft, { target: { value: "Conservar" } });
        await open();
        expect(within(panel()).getByRole("alert")).toBeVisible();
        fireEvent.click(screen.getByRole("button", { name: "Reintentar contexto" })); await act(async () => {});
        expect(within(panel()).getByText("Luna")).toBeVisible();
        expect(screen.getByText("Mensaje de ana")).toBeVisible();
        expect(draft).toHaveValue("Conservar");
        expect(api.getThreadMessages).toHaveBeenCalledTimes(1);
    });
    it("sin vínculo no inventa cliente, mascotas ni expediente", async () => {
        api.getThreadContext.mockResolvedValueOnce({ owner: null, pets: [], last_appointment: null });
        await mount(); await open();
        expect(within(panel()).getByText(/aún no tiene un cliente vinculado/)).toBeVisible();
        expect(within(panel()).queryByRole("button", { name: /Abrir expediente/ })).not.toBeInTheDocument();
    });
    it("con cliente sin mascotas ni citas muestra los estados vacíos", async () => {
        api.getThreadContext.mockResolvedValueOnce({ ...context(), pets: [], last_appointment: null });
        await mount(); await open();
        expect(within(panel()).getByText("No tiene mascotas registradas.")).toBeVisible();
        expect(within(panel()).getByText(/Sin citas anteriores/)).toBeVisible();
    });
    it("elige UUIDs de mascotas homónimas sin navegar por nombre ni por PK", async () => {
        api.getThreadContext.mockResolvedValueOnce({ ...context(), pets: [
            { public_id: "pet-one", name: "Luna", species: "" },
            { public_id: "pet-two", name: "Luna", species: "canino" },
        ] });
        await mount(); await open();
        expect(screen.getByText("Especie pendiente")).toBeVisible();
        fireEvent.click(within(panel()).getAllByRole("button", { name: "Abrir expediente de Luna" })[1]);
        expect(navigate).toHaveBeenCalledWith("/pets/pet-two");
    });
    it("VET con view y retrieve abre contexto aunque no pueda enviar", async () => {
        permissions.delete("agentinbox.send"); await mount(); await open();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Abrir expediente de Luna" }));
        expect(navigate).toHaveBeenCalledWith("/pets/pet-ana");
    });
    it("sin permiso de consulta de mascota no ofrece abrir expediente", async () => {
        permissions.delete("patient.retrieve"); await mount(); await open();
        expect(within(panel()).getByText("Luna")).toBeVisible();
        expect(within(panel()).queryByRole("button", { name: /Abrir expediente/ })).not.toBeInTheDocument();
    });
    it("un hilo archivado conserva el panel pero no el composer", async () => {
        snapshots.ana.conversation = null; await mount(); await open();
        expect(within(panel()).getByText("Luna")).toBeVisible();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });
    it("cambiar de hilo aborta e ignora un contexto antiguo", async () => {
        const pending = deferred(); api.getThreadContext.mockReturnValueOnce(pending.promise);
        await mount(); await open();
        const signal = api.getThreadContext.mock.calls[0][2].signal;
        fireEvent.click(screen.getByRole("button", { name: /Beto/ })); await act(async () => {});
        expect(signal.aborted).toBe(true);
        await open();
        await act(async () => pending.resolve(context("ana")));
        expect(within(panel()).getByText("Bruno")).toBeVisible();
        expect(within(panel()).queryByText("Luna")).not.toBeInTheDocument();
        expect(api.getThreadContext.mock.calls[1].slice(0, 2)).toEqual(["beto", "main"]);
    });
    it("cerrar y reabrir consulta el contexto vigente y no revive una respuesta abortada", async () => {
        const pending = deferred(); api.getThreadContext.mockReturnValueOnce(pending.promise);
        await mount(); await open();
        fireEvent.click(screen.getByRole("button", { name: "Ocultar contexto del cliente" }));
        api.getThreadContext.mockResolvedValueOnce({ owner: null, pets: [], last_appointment: null });
        await open(); await act(async () => pending.resolve(context()));
        expect(within(panel()).queryByText("Luna")).not.toBeInTheDocument();
        expect(within(panel()).getByText(/aún no tiene un cliente vinculado/)).toBeVisible();
    });
    it("el poll de mensajes no vuelve a cargar contexto y una revocación lo retira", async () => {
        vi.useFakeTimers(); await mount(); await open();
        await act(async () => vi.advanceTimersByTimeAsync(10000));
        expect(api.getThreadContext).toHaveBeenCalledTimes(1);
        snapshots.ana = { ...snapshots.ana, owner_name: null, contact_verification: "unknown" };
        await act(async () => vi.advanceTimersByTimeAsync(10000));
        expect(screen.getByRole("button", { name: "Ver contexto del cliente" })).toBeVisible();
        expect(within(panel()).queryByText("Luna")).not.toBeInTheDocument();
    });
    it("desmontar cancela la petición pendiente", async () => {
        const pending = deferred(); api.getThreadContext.mockReturnValueOnce(pending.promise);
        const view = await mount(); await open();
        const signal = api.getThreadContext.mock.calls[0][2].signal;
        view.unmount(); expect(signal.aborted).toBe(true);
        await act(async () => pending.resolve(context()));
        expect(navigate).not.toHaveBeenCalled();
    });
    it("los nombres HTML se presentan como texto sin insertar elementos ejecutables", async () => {
        api.getThreadContext.mockResolvedValueOnce({ ...context(), owner: { ...context().owner,
            name: '<img src=x onerror="alert(1)">' } });
        await mount(); await open();
        expect(within(panel()).getByText('<img src=x onerror="alert(1)">')).toBeVisible();
        expect(panel().querySelector("img")).toBeNull();
    });
});
