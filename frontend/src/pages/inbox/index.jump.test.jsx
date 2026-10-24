import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => Object.fromEntries([
    "assignConversation", "authorizeIdentityLink", "claimConversation", "closeConversation", "getAgentSettings",
    "getThreadMessages", "getThreads", "getInboxMetrics", "getWhatsappToken", "releaseConversation",
    "resetContactIdentity", "sendInboxMessage", "setWhatsappToken", "unlinkFamily", "updateAgentSettings",
    "verifyContactIdentity", "markThreadRead", "retryInboxMessage", "getThreadContext", "getAssignableUsers",
].map((key) => [key, vi.fn()])));
const permission = vi.hoisted(() => ({ send: true }));
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({
    can: (key) => permission.send && key === "agentinbox.send", user: { organization_timezone: "UTC" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";
import styles from "./inbox.module.css";

const quote = (id = 1) => ({ id, author_type: "client", excerpt: "La pregunta original", payload_type: "text", status: "processed" });
const message = (id, extra = {}) => ({ id, body: `Mensaje ${id}`, direction: "in", author_type: "client",
    payload_type: "text", status: "processed", created_at: "2026-10-22T12:00:00Z", ...extra });
const row = (name) => ({ contact_public_id: name, channel_account_public_id: "main", owner_name: name,
    conversation_public_id: `session-${name}`, state: "human_active" });
const packet = (name = "Ana", extra = {}) => ({ owner_name: name, contact_public_id: name, channel_account_public_id: "main",
    mode: "full", sync_cursor: `cursor-${name}`, sync_floor: "floor-51", conversation: { public_id: `session-${name}`,
        state: "human_active", session_window_open: true, session_window_expires_at: new Date(Date.now() + 86400000).toISOString() },
    messages: [message(51), message(60, { direction: "out", author_type: "human_staff", human_author_name: "Lucía", reply_to: quote() })],
    next_before: 51, ...extra });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const flush = async () => { await act(async () => {}); };
const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
const bubble = (id) => document.querySelector(`[data-server-message-id="${id}"]`);
const draft = () => screen.getByRole("textbox", { name: "Respuesta al cliente" });
const jump = async () => { fireEvent.click(screen.getByRole("button", { name: "Ir al mensaje original de Ana" })); await flush(); };
async function start() {
    const view = render(<Inbox />); await flush(); fireEvent.click(screen.getByRole("button", { name: /^Ana/ })); await flush(); return view;
}
beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] }); permission.send = true;
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getThreads.mockResolvedValue({ results: [row("Ana"), row("Beto")], has_more: false });
    api.getInboxMetrics.mockResolvedValue(null); api.getThreadMessages.mockImplementation(async (name) => packet(name));
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => {
    vi.useRealTimers(); vi.restoreAllMocks();
    if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
    else delete HTMLElement.prototype.scrollTo;
});

describe("WA-RPL-06/04 — citas y navegación en Inbox", () => {
    it.each(["in", "out"])("renderiza la cita en una burbuja %s", async (direction) => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", { messages: [message(60, { direction, reply_to: quote() })] }));
        await start(); expect(within(bubble(60)).getByRole("button", { name: "Ir al mensaje original de Ana" })).toHaveTextContent("La pregunta original");
    });
    it("un original cargado con client_message_id se localiza por PK sin otra petición", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", { messages: [message(1, { client_message_id: "confirmed-key" }),
            message(60, { reply_to: quote() })] }));
        await start(); await jump(); expect(api.getThreadMessages).toHaveBeenCalledTimes(1);
        expect(bubble(1)).toHaveFocus(); expect(bubble(1)).toHaveClass(styles.messageHighlight);
        await act(async () => vi.advanceTimersByTime(2000)); expect(bubble(1)).not.toHaveClass(styles.messageHighlight);
    });
    it("carga around, conserva borrador/cita del composer y no usa metadatos antiguos de sesión", async () => {
        await start(); fireEvent.change(draft(), { target: { value: "Borrador conservado" } });
        fireEvent.click(within(bubble(60)).getByRole("button", { name: "Responder al mensaje" }));
        api.getThreadMessages.mockResolvedValueOnce(packet("Ana", { messages: [message(1), message(51)],
            sync_floor: "floor-1", conversation: null }));
        await jump(); expect(api.getThreadMessages.mock.calls[1]).toEqual(["Ana", "main", { around: 1 }, { signal: expect.any(AbortSignal) }]);
        expect(draft()).toHaveValue("Borrador conservado"); expect(screen.getByRole("status", { name: "Mensaje citado" })).toBeVisible();
        expect(bubble(1)).toHaveFocus(); expect(bubble(1)).toHaveClass(styles.messageHighlight);
        expect(document.querySelectorAll('[data-server-message-id="51"]')).toHaveLength(1);
    });
    it("mientras busca pausa el poll, impide duplicados y permite retomar con el floor ampliado", async () => {
        await start(); const wait = deferred(); api.getThreadMessages.mockReturnValueOnce(wait.promise);
        await jump(); expect(screen.getByText("Buscando mensaje original…")).toBeVisible();
        expect(screen.getByRole("button", { name: "Ir al mensaje original de Ana" })).toBeDisabled();
        await act(async () => vi.advanceTimersByTime(10000)); expect(api.getThreadMessages).toHaveBeenCalledTimes(2);
        await act(async () => wait.resolve(packet("Ana", { messages: [message(1)], sync_floor: "floor-1" })));
        api.getThreadMessages.mockResolvedValueOnce({ mode: "delta", sync_cursor: "next", messages: [], removals: [],
            metadata: {}, range_ids: [1, 51, 60] });
        await act(async () => vi.advanceTimersByTime(10000));
        expect(api.getThreadMessages.mock.calls[2][2]).toEqual({ since: "cursor-Ana", floor: "floor-1" });
        expect(bubble(1)).toBeInTheDocument(); expect(bubble(60)).toBeInTheDocument();
    });
    it("el salto cancela un full antiguo que podría borrar la página alrededor", async () => {
        await start(); const old = deferred(); api.getThreadMessages.mockReturnValueOnce(old.promise);
        await act(async () => vi.advanceTimersByTime(10000)); const oldSignal = api.getThreadMessages.mock.calls[1][3].signal;
        api.getThreadMessages.mockResolvedValueOnce(packet("Ana", { messages: [message(1)], sync_floor: "floor-1" }));
        await jump(); expect(oldSignal.aborted).toBe(true);
        await act(async () => old.resolve(packet("Ana", { reset_range: true, messages: [message(51)] })));
        expect(bubble(1)).toBeInTheDocument(); expect(bubble(60)).toBeInTheDocument();
    });
    it("cambiar de hilo aborta around y no traslada contenido, error ni foco", async () => {
        await start(); const wait = deferred(); api.getThreadMessages.mockReturnValueOnce(wait.promise); await jump();
        const signal = api.getThreadMessages.mock.calls[1][3].signal;
        fireEvent.click(screen.getByRole("button", { name: /^Beto/ })); await flush(); expect(signal.aborted).toBe(true);
        await act(async () => wait.resolve(packet("Ana", { messages: [message(1, { body: "ANTIGUO" })] })));
        expect(screen.queryByText("ANTIGUO")).not.toBeInTheDocument(); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        expect(bubble(60)).not.toHaveClass(styles.messageHighlight);
    });
    it("404 conserva el texto y ofrece reintento al volver a pulsar la cita", async () => {
        await start(); fireEvent.change(draft(), { target: { value: "No perder" } });
        api.getThreadMessages.mockRejectedValueOnce({ response: { status: 404 } }); await jump();
        expect(screen.getByRole("alert")).toHaveTextContent("El mensaje original ya no está disponible.");
        expect(draft()).toHaveValue("No perder"); expect(bubble(1)).toBeNull();
        api.getThreadMessages.mockResolvedValueOnce(packet("Ana", { messages: [message(1)] })); await jump();
        expect(screen.queryByRole("alert")).not.toBeInTheDocument(); expect(bubble(1)).toHaveFocus();
    });
    it("view sin send y un hilo archivado permiten navegar la cita", async () => {
        permission.send = false; api.getThreadMessages.mockResolvedValueOnce(packet("Ana", { conversation: null }));
        await start(); api.getThreadMessages.mockResolvedValueOnce(packet("Ana", { messages: [message(1)] }));
        await jump(); expect(bubble(1)).toHaveFocus(); expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });
    it("unmount cancela around", async () => {
        const view = await start(); const wait = deferred(); api.getThreadMessages.mockReturnValueOnce(wait.promise); await jump();
        const signal = api.getThreadMessages.mock.calls[1][3].signal; view.unmount(); expect(signal.aborted).toBe(true);
        await act(async () => wait.resolve(packet("Ana", { messages: [message(1)] })));
    });
});
