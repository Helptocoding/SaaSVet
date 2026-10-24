import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => Object.fromEntries([
    "authorizeIdentityLink", "claimConversation", "closeConversation", "getAgentSettings", "getThreadMessages",
    "getThreads", "getInboxMetrics", "getWhatsappToken", "releaseConversation", "resetContactIdentity",
    "sendInboxMessage", "setWhatsappToken", "unlinkFamily", "updateAgentSettings", "verifyContactIdentity",
    "markThreadRead", "retryInboxMessage", "getThreadContext", "getAssignableUsers", "assignConversation",
].map((key) => [key, vi.fn()])));
const permissions = vi.hoisted(() => ({ claim: true }));
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({
    can: (permission) => permission === "agentinbox.send" || (permissions.claim && permission === "agentinbox.claim"),
    user: { organization_timezone: "UTC" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import { toast } from "sonner";
import Inbox from "./index";

const row = (name) => ({ contact_public_id: name, channel_account_public_id: "main", owner_name: name,
    conversation_public_id: `session-${name}`, state: "human_active", session_count: 1 });
const packet = (name, extra = {}) => ({ owner_name: name, contact_public_id: name, channel_account_public_id: "main",
    conversation: { public_id: `session-${name}`, state: "human_active", session_window_open: true,
        session_window_expires_at: new Date(Date.now()+86400000).toISOString(), ...extra }, messages: [], next_before: null });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
async function flush() { await act(async () => {}); }
async function click(name) { fireEvent.click(screen.getByRole("button", { name, exact: true })); await flush(); }
async function selectConversation(name = "Ana") { await click(new RegExp(name)); }
async function prepareAssignment() {
    await click("Asignar a…");
    fireEvent.change(screen.getByRole("combobox", { name: "Persona asignada" }), { target: { value: "vet-id" } });
}

beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    Object.values(api).forEach((mock) => mock.mockReset()); permissions.claim = true;
    toast.success.mockClear(); toast.error.mockClear();
    api.getThreads.mockResolvedValue({ results: [row("Ana"), row("Beto")], unread_total: 0, has_more: false, next_offset: null });
    api.getInboxMetrics.mockResolvedValue(null);
    api.getThreadMessages.mockImplementation((contact) => Promise.resolve(packet(contact)));
    api.getAssignableUsers.mockResolvedValue([{ public_id: "vet-id", name: "María sintética" }]);
    api.assignConversation.mockResolvedValue({});
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("WA-ASN-01 — cabecera y transiciones", () => {
    it("asigna el episodio vigente, refresca e informa sin borrar el borrador", async () => {
        render(<Inbox />); await flush(); await selectConversation();
        fireEvent.change(screen.getByRole("textbox"), { target: { value: "Borrador conservado" } });
        await prepareAssignment(); api.getThreadMessages.mockResolvedValueOnce(packet("Ana", { claimed_by_name: "María sintética" }));
        await click("Asignar");
        expect(api.assignConversation).toHaveBeenCalledExactlyOnceWith("session-Ana", "vet-id");
        expect(screen.getByText("Atiende: María sintética")).toBeVisible();
        expect(screen.getByRole("textbox")).toHaveValue("Borrador conservado");
        expect(toast.success).toHaveBeenCalledWith("Conversación asignada");
    });
    it("oculta la acción sin permiso claim", async () => {
        permissions.claim = false; render(<Inbox />); await flush(); await selectConversation();
        expect(screen.queryByRole("button", { name: "Asignar a…" })).not.toBeInTheDocument();
        expect(api.getAssignableUsers).not.toHaveBeenCalled();
    });
    it("no permite asignar una conversación archivada", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", { state: "closed" }));
        render(<Inbox />); await flush(); await selectConversation();
        expect(screen.queryByRole("button", { name: "Asignar a…" })).not.toBeInTheDocument();
    });
    it("el turno activo deshabilita asignar como Tomar/Liberar", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", { agent_processing: true }));
        render(<Inbox />); await flush(); await selectConversation();
        expect(screen.getByRole("button", { name: "Asignar a…" })).toBeDisabled();
    });
    it("el fallo mantiene elección y borrador para corregir o reintentar", async () => {
        api.assignConversation.mockRejectedValueOnce({ response: { status: 400, data: { message: "Persona sin permiso" } } });
        render(<Inbox />); await flush(); await selectConversation();
        fireEvent.change(screen.getByRole("textbox"), { target: { value: "Conservar" } });
        await prepareAssignment(); await click("Asignar");
        expect(toast.error).toHaveBeenCalledWith("Persona sin permiso");
        expect(screen.getByRole("combobox")).toHaveValue("vet-id"); expect(screen.getByRole("textbox")).toHaveValue("Conservar");
        await click("Asignar"); expect(api.assignConversation).toHaveBeenCalledTimes(2);
    });
    it("doble submit bloquea acciones simultáneas", async () => {
        const wait = deferred(); api.assignConversation.mockReturnValueOnce(wait.promise);
        render(<Inbox />); await flush(); await selectConversation(); await prepareAssignment();
        const form = screen.getByRole("form"); fireEvent.submit(form); fireEvent.submit(form);
        expect(api.assignConversation).toHaveBeenCalledTimes(1);
        expect(screen.getByRole("button", { name: "Liberar" })).toBeDisabled();
        await act(async () => wait.resolve({}));
    });
    it("cambiar de hilo cancela el directorio sin trasladar la selección", async () => {
        const wait = deferred(); api.getAssignableUsers.mockReturnValueOnce(wait.promise);
        render(<Inbox />); await flush(); await selectConversation(); await click("Asignar a…");
        const signal = api.getAssignableUsers.mock.calls[0][0].signal; await selectConversation("Beto");
        expect(signal.aborted).toBe(true); await act(async () => wait.resolve([{ public_id: "old", name: "Antigua" }]));
        expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
        await click("Asignar a…"); expect(screen.queryByRole("option", { name: "Antigua" })).not.toBeInTheDocument();
    });
    it("un POST tardío no refresca ni anuncia el hilo anterior", async () => {
        const wait = deferred(); api.assignConversation.mockReturnValueOnce(wait.promise);
        render(<Inbox />); await flush(); await selectConversation(); await prepareAssignment();
        fireEvent.submit(screen.getByRole("form")); await selectConversation("Beto");
        fireEvent.change(screen.getByRole("textbox"), { target: { value: "Beto solamente" } });
        const calls = api.getThreadMessages.mock.calls.length;
        await act(async () => wait.resolve({}));
        expect(api.getThreadMessages).toHaveBeenCalledTimes(calls); expect(toast.success).not.toHaveBeenCalled();
        expect(screen.getByRole("textbox")).toHaveValue("Beto solamente");
    });
    it("una respuesta de otra sesión del mismo hilo también invalida el POST", async () => {
        const wait = deferred(); api.assignConversation.mockReturnValueOnce(wait.promise);
        render(<Inbox />); await flush(); await selectConversation(); await prepareAssignment();
        fireEvent.submit(screen.getByRole("form"));
        api.getThreadMessages.mockResolvedValue(packet("Ana", { public_id: "new-session" }));
        await act(async () => vi.advanceTimersByTime(10000)); await act(async () => wait.resolve({}));
        expect(toast.success).not.toHaveBeenCalled();
    });
    it("mantiene el contrato de Tomar y Liberar al compartir el guard", async () => {
        api.getThreadMessages.mockResolvedValueOnce(packet("Ana", { state: "active" }));
        render(<Inbox />); await flush(); await selectConversation();
        await click("Tomar y acusar recibo"); expect(api.claimConversation).toHaveBeenCalledExactlyOnceWith("session-Ana");
        await click("Liberar"); expect(api.releaseConversation).toHaveBeenCalledExactlyOnceWith("session-Ana");
    });
    it("salir del inbox descarta la respuesta tardía de asignación", async () => {
        const wait = deferred(); api.assignConversation.mockReturnValueOnce(wait.promise);
        const view = render(<Inbox />); await flush(); await selectConversation(); await prepareAssignment();
        fireEvent.submit(screen.getByRole("form")); view.unmount();
        const calls = api.getThreadMessages.mock.calls.length;
        await act(async () => wait.resolve({}));
        expect(api.getThreadMessages).toHaveBeenCalledTimes(calls); expect(toast.success).not.toHaveBeenCalled();
    });
});
