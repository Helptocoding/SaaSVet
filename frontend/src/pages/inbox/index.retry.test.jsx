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
    can: (permission) => permissions.has(permission), user: { organization_timezone: "UTC" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";
import { toast } from "sonner";

const failed = () => ({ id: 42, conversation_public_id: "session-ana", client_message_id: "original-key",
    direction: "out", author_type: "human_staff", human_author_name: "María",
    human_author_public_id: "maria", payload_type: "text", body: "Respuesta original de María",
    status: "failed", failure_reason: "credentials_missing", created_at: "2026-10-21T12:00:00Z" });
const deferred = () => { let resolve, reject; const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
    return { promise, resolve, reject }; };
let messages;
const snapshot = (contact) => ({ owner_name: contact === "ana" ? "Ana" : "Beto",
    contact_phone: "5551234567", conversation: { public_id: `session-${contact}`, state: "human_active",
        session_window_open: true, session_window_expires_at: new Date(Date.now() + 86400000).toISOString() },
    messages: contact === "ana" ? messages : [], next_before: null });
beforeEach(() => {
    permissions.clear(); permissions.add("agentinbox.send");
    messages = [failed()];
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getThreads.mockResolvedValue({ results: ["ana", "beto"].map((contact) => ({
        contact_public_id: contact, channel_account_public_id: "main", owner_name: contact === "ana" ? "Ana" : "Beto",
        conversation_public_id: `session-${contact}`, state: "human_active", session_count: 1,
    })) });
    api.getThreadMessages.mockImplementation(async (contact) => snapshot(contact));
    api.getInboxMetrics.mockResolvedValue(null);
    api.retryInboxMessage.mockImplementation(async () => ({ ...failed(), status: "pending", failure_reason: "" }));
    toast.error.mockReset();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
async function mount() {
    const result = render(<Inbox />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Ana/ }));
    await act(async () => {});
    return result;
}

describe("WA-RETRY-01 — fallo conocido del servidor", () => {
    it("reintenta la fila original de otra autora sin duplicados ni pérdida del borrador", async () => {
        await mount();
        const draft = screen.getByRole("textbox"); fireEvent.change(draft, { target: { value: "Otro borrador" } });
        fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
        await act(async () => {});
        expect(api.retryInboxMessage.mock.calls[0].slice(0, 3)).toEqual(["session-ana", 42, "original-key"]);
        expect(api.sendInboxMessage).not.toHaveBeenCalled();
        expect(screen.getAllByText("Respuesta original de María")).toHaveLength(1);
        expect(screen.getByText("María")).toBeVisible();
        expect(screen.getByLabelText("Pendiente de envío")).toBeVisible();
        expect(draft).toHaveValue("Otro borrador");
        expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
    });
    it("bloquea doble clic hasta recibir respuesta", async () => {
        const pending = deferred(); api.retryInboxMessage.mockReturnValue(pending.promise);
        await mount();
        const button = screen.getByRole("button", { name: "Reintentar" });
        fireEvent.click(button); fireEvent.click(button);
        expect(screen.getByRole("button", { name: "Reintentando…" })).toBeDisabled();
        expect(api.retryInboxMessage).toHaveBeenCalledTimes(1);
        await act(async () => pending.resolve({ ...failed(), status: "pending" }));
    });
    it.each(["ventana de sesión de 24h cerrada", "session_window_closed", "meta_131047"])(
        "muestra llamada desde el fallo de ventana %s", async (failure_reason) => {
            messages = [{ ...failed(), failure_reason }]; await mount();
            expect(screen.getByText(/Ventana de WhatsApp cerrada/)).toBeVisible();
            const hint = screen.getByText(/Ventana de WhatsApp cerrada/);
            expect(within(hint).getByRole("link", { name: "5551234567" })).toHaveAttribute("href", "tel:5551234567");
        });
    it("el servidor puede detectar ventana cerrada y conservar mensaje y opción de llamada", async () => {
        api.retryInboxMessage.mockRejectedValue({ response: { status: 400, data: { code: "window_closed", suggestion: "call" } } });
        await mount(); fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
        await act(async () => {});
        expect(screen.getByText(/Ventana de WhatsApp cerrada/)).toBeVisible();
        expect(screen.getByRole("button", { name: "Reintentar" })).toBeEnabled();
        expect(screen.getByText("Respuesta original de María")).toBeVisible();
        expect(toast.error).not.toHaveBeenCalled();
    });
    it("fallo HTTP conserva el mensaje y permite otro intento explícito", async () => {
        api.retryInboxMessage.mockRejectedValueOnce(new Error("offline"));
        await mount(); fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
        await act(async () => {});
        expect(toast.error).toHaveBeenCalledTimes(1);
        fireEvent.click(screen.getByRole("button", { name: "Reintentar" })); await act(async () => {});
        expect(api.retryInboxMessage).toHaveBeenCalledTimes(2);
        expect(screen.getByLabelText("Pendiente de envío")).toBeVisible();
    });
    it.each(["pending", "sending", "sent", "delivered", "read", "uncertain", "discarded"])(
        "no ofrece reintentar para %s", async (status) => {
            messages = [{ ...failed(), status }]; await mount();
            expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
        });
    it("no ofrece reintento sin send ni para una sesión histórica", async () => {
        permissions.clear(); await mount();
        expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
    });
    it("una fila de otra sesión no usa el UUID vigente como sustituto", async () => {
        messages = [{ ...failed(), conversation_public_id: "archived-session" }]; await mount();
        expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
    });
    it.each(["acceptance_known", "provider_accepted_at", "delivered_at", "read_at", "uncertain_at"])(
        "no ofrece reintento de FAILED con evidencia %s", async (field) => {
            messages = [{ ...failed(), [field]: true }]; await mount();
            expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
        });
    it("cambio de hilo aborta e ignora respuesta tardía sin tocar el borrador nuevo", async () => {
        const pending = deferred(); api.retryInboxMessage.mockReturnValue(pending.promise);
        await mount(); fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
        const signal = api.retryInboxMessage.mock.calls[0][3].signal;
        fireEvent.click(screen.getByRole("button", { name: /Beto/ })); await act(async () => {});
        fireEvent.change(screen.getByRole("textbox"), { target: { value: "Para Beto" } });
        expect(signal.aborted).toBe(true);
        await act(async () => pending.resolve({ ...failed(), status: "pending" }));
        expect(screen.queryByText("Respuesta original de María")).not.toBeInTheDocument();
        expect(screen.getByRole("textbox")).toHaveValue("Para Beto");
    });
    it("desmontar aborta la solicitud", async () => {
        const pending = deferred(); api.retryInboxMessage.mockReturnValue(pending.promise);
        const view = await mount(); fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
        const signal = api.retryInboxMessage.mock.calls[0][3].signal;
        view.unmount(); expect(signal.aborted).toBe(true);
        await act(async () => pending.reject(new Error("late")));
        expect(toast.error).not.toHaveBeenCalled();
    });
    it("un acuse READ recibido por poll gana al PENDING tardío del POST", async () => {
        vi.useFakeTimers();
        const pending = deferred(); api.retryInboxMessage.mockReturnValue(pending.promise);
        await mount(); fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
        messages = [{ ...failed(), status: "read", acceptance_known: true }];
        await act(async () => vi.advanceTimersByTimeAsync(10000));
        expect(screen.getByLabelText("Leído")).toBeVisible();
        await act(async () => pending.resolve({ ...failed(), status: "pending" }));
        expect(screen.getByLabelText("Leído")).toBeVisible();
        expect(screen.queryByLabelText("Pendiente de envío")).not.toBeInTheDocument();
    });
    it("un GET anterior al acuse del retry no revive FAILED", async () => {
        vi.useFakeTimers();
        const pending = deferred(), oldPoll = deferred(); api.retryInboxMessage.mockReturnValue(pending.promise);
        await mount(); fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
        api.getThreadMessages.mockReturnValueOnce(oldPoll.promise);
        await act(async () => vi.advanceTimersByTimeAsync(10000));
        await act(async () => pending.resolve({ ...failed(), status: "pending" }));
        await act(async () => oldPoll.resolve(snapshot("ana")));
        expect(screen.getByLabelText("Pendiente de envío")).toBeVisible();
    });
});
