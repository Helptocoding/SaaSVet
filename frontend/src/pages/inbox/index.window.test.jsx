import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => Object.fromEntries([
    "authorizeIdentityLink", "claimConversation", "closeConversation", "getAgentSettings",
    "getThreadMessages", "getThreads", "getInboxMetrics", "getWhatsappToken", "releaseConversation",
    "resetContactIdentity", "sendInboxMessage", "setWhatsappToken", "unlinkFamily", "updateAgentSettings",
    "verifyContactIdentity", "markThreadRead", "retryInboxMessage", "getThreadContext",
].map((key) => [key, vi.fn()])));
const permissions = vi.hoisted(() => new Set());
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({
    can: (permission) => permissions.has(permission), user: { organization_timezone: "America/Tijuana" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";

let snapshots, hidden, visibility;
const open = (minutes = 1440) => ({ session_window_open: true,
    session_window_expires_at: new Date(Date.now() + minutes * 60000).toISOString() });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const tick = (ms) => act(async () => vi.advanceTimersByTimeAsync(ms));
const draft = () => screen.getByRole("textbox", { name: "Respuesta al cliente" });
beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-21T12:00:00Z"));
    permissions.clear(); permissions.add("agentinbox.send");
    Object.values(api).forEach((mock) => mock.mockReset());
    snapshots = Object.fromEntries(["ana", "beto"].map((contact) => [contact, {
        owner_name: contact === "ana" ? "Ana" : "Beto",
        conversation: { public_id: `session-${contact}`, state: "human_active",
            contact_phone: "5551234567", ...open() }, messages: [], next_before: null,
    }]));
    api.getThreads.mockResolvedValue({ results: ["ana", "beto"].map((contact) => ({
        contact_public_id: contact, channel_account_public_id: "main", owner_name: contact === "ana" ? "Ana" : "Beto",
        conversation_public_id: `session-${contact}`, state: "human_active", session_count: 1,
    })) });
    api.getThreadMessages.mockImplementation(async (contact) => ({ ...snapshots[contact] }));
    api.getInboxMetrics.mockResolvedValue(null);
    api.sendInboxMessage.mockImplementation(async (sessionId, body, key) => ({
        id: 88, client_message_id: key, body, direction: "out", author_type: "human_staff",
        status: "pending", created_at: new Date().toISOString(), conversation_public_id: sessionId,
    }));
    hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
async function mount() {
    const view = render(<Inbox />); await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Ana/ })); await act(async () => {});
    return view;
}
function setWindow(fields) { snapshots.ana.conversation = { ...snapshots.ana.conversation, ...fields }; }
function enter(text = "Borrador conservado") { fireEvent.change(draft(), { target: { value: text } }); }

describe("WA-WIN-01 — ventana preventiva en Inbox", () => {
    it("una ventana de más de 12 h permite enviar sin banda innecesaria", async () => {
        await mount(); expect(draft()).toBeEnabled();
        expect(screen.queryByText(/ventana de 24 h/)).not.toBeInTheDocument();
        enter("Respuesta en ventana"); fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
        await act(async () => {});
        expect(api.sendInboxMessage.mock.calls[0].slice(0, 2)).toEqual(["session-ana", "Respuesta en ventana"]);
    });
    it("muestra 7 h 12 min y actualiza a 7 h 11 min sin borrar el borrador", async () => {
        setWindow(open(432)); await mount(); enter();
        expect(screen.getByText(/cierra en 7 h 12 min/)).toBeVisible();
        await tick(60000);
        expect(screen.getByText(/cierra en 7 h 11 min/)).toBeVisible();
        expect(draft()).toHaveValue("Borrador conservado");
    });
    it("el aviso aparece al pasar de 12 h al intervalo de advertencia", async () => {
        setWindow(open(720)); await mount();
        expect(screen.queryByText(/cierra en/)).not.toBeInTheDocument();
        await tick(60000);
        expect(screen.getByText(/cierra en 11 h 59 min/)).toBeVisible();
    });
    it("bloquea en el límite entre ticks, conserva borrador y no envía por Enter", async () => {
        setWindow(open(0.5)); await mount(); enter();
        await tick(30000); expect(draft()).toBeEnabled(); // B4 includes the exact boundary.
        await tick(1); expect(draft()).toBeDisabled();
        expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
        expect(draft()).toHaveValue("Borrador conservado");
        expect(screen.getByText(/Ventana de WhatsApp cerrada/)).toBeVisible();
        fireEvent.keyDown(draft(), { key: "Enter" });
        expect(api.sendInboxMessage).not.toHaveBeenCalled();
        expect(draft()).toHaveAccessibleDescription(/Ventana de WhatsApp cerrada/);
    });
    it("el guard de Enter comprueba el reloj aunque aún no haya corrido el timer", async () => {
        setWindow(open(1)); await mount(); enter();
        vi.setSystemTime(new Date(Date.now() + 60001));
        fireEvent.keyDown(draft(), { key: "Enter" });
        expect(api.sendInboxMessage).not.toHaveBeenCalled();
        expect(draft()).toHaveValue("Borrador conservado");
    });
    it("el false del servidor bloquea aunque el reloj local vea un vencimiento futuro", async () => {
        setWindow({ ...open(), session_window_open: false }); await mount();
        expect(draft()).toBeDisabled();
        expect(within(screen.getByText(/Ventana de WhatsApp cerrada/)).getByRole("link", { name: "5551234567" }))
            .toHaveAttribute("href", "tel:5551234567");
    });
    it("sin último entrante la ventana cerrada tiene explicación", async () => {
        setWindow({ session_window_open: false, session_window_expires_at: null }); await mount();
        expect(draft()).toBeDisabled();
        expect(screen.getByText(/Espera un nuevo mensaje del cliente/)).toBeVisible();
    });
    it.each([{}, { session_window_open: true, session_window_expires_at: "invalid" },
        { session_window_open: true, session_window_expires_at: null }])(
        "metadatos incompletos o inválidos impiden enviar: %s", async (fields) => {
            snapshots.ana.conversation = { public_id: "session-ana", state: "active", ...fields };
            await mount(); expect(draft()).toBeDisabled();
            expect(screen.getByText(/No se pudo comprobar la ventana/)).toBeVisible();
        });
    it("un nuevo inbound proyectado por poll reabre y conserva el borrador anterior", async () => {
        setWindow(open(0.5)); await mount(); enter(); await tick(30001);
        expect(draft()).toBeDisabled();
        setWindow(open()); await tick(9999);
        expect(draft()).toBeEnabled(); expect(draft()).toHaveValue("Borrador conservado");
        expect(screen.queryByText(/Ventana de WhatsApp cerrada/)).not.toBeInTheDocument();
    });
    it("volver de pestaña oculta corrige el reloj de inmediato y refresca la sesión", async () => {
        setWindow(open(2)); await mount(); enter();
        hidden.mockReturnValue(true); visibility.mockReturnValue("hidden");
        fireEvent(document, new Event("visibilitychange"));
        const reads = api.getThreadMessages.mock.calls.length;
        vi.setSystemTime(new Date(Date.now() + 180000));
        expect(api.getThreadMessages).toHaveBeenCalledTimes(reads);
        hidden.mockReturnValue(false); visibility.mockReturnValue("visible");
        fireEvent(document, new Event("visibilitychange")); await act(async () => {});
        expect(draft()).toBeDisabled();
        expect(api.getThreadMessages).toHaveBeenCalledTimes(reads + 1);
        expect(draft()).toHaveValue("Borrador conservado");
    });
    it("un payload que llega ya expirado se cierra antes del siguiente minuto", async () => {
        const pending = deferred(); api.getThreadMessages.mockReturnValueOnce(pending.promise);
        render(<Inbox />); await act(async () => {});
        fireEvent.click(screen.getByRole("button", { name: /Ana/ })); await act(async () => {});
        setWindow(open(0.1));
        vi.setSystemTime(new Date(Date.now() + 7000));
        await act(async () => pending.resolve(snapshots.ana)); await tick(2);
        expect(draft()).toBeDisabled();
    });
    it("un hilo archivado no muestra composer ni ventana", async () => {
        snapshots.ana.conversation = null; await mount();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
        expect(screen.queryByText(/Ventana de WhatsApp cerrada|cierra en/)).not.toBeInTheDocument();
    });
    it("view sin send no muestra controles de envío ni aviso de composer", async () => {
        permissions.clear(); setWindow(open(30)); await mount();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
        expect(screen.queryByText(/cierra en/)).not.toBeInTheDocument();
    });
    it("el estado cerrado y el borrador no se trasladan al cambiar a otro hilo", async () => {
        setWindow({ ...open(), session_window_open: false }); await mount();
        fireEvent.click(screen.getByRole("button", { name: /Beto/ })); await act(async () => {});
        expect(draft()).toBeEnabled(); expect(draft()).toHaveValue("");
        expect(screen.queryByText(/Ventana de WhatsApp cerrada/)).not.toBeInTheDocument();
    });
    it("un GET tardío del hilo anterior no cierra el composer nuevo", async () => {
        await mount();
        const pending = deferred(); api.getThreadMessages.mockReturnValueOnce(pending.promise);
        await tick(10000);
        fireEvent.click(screen.getByRole("button", { name: /Beto/ })); await act(async () => {});
        setWindow({ ...open(), session_window_open: false });
        await act(async () => pending.resolve(snapshots.ana));
        expect(draft()).toBeEnabled();
        expect(screen.queryByText(/Ventana de WhatsApp cerrada/)).not.toBeInTheDocument();
    });
    it("desmontar cancela los timers de reloj, vencimiento y polling", async () => {
        setWindow(open(0.5)); const view = await mount();
        view.unmount(); expect(vi.getTimerCount()).toBe(0);
        const calls = api.getThreadMessages.mock.calls.length;
        await tick(60000); expect(api.getThreadMessages).toHaveBeenCalledTimes(calls);
    });
});
