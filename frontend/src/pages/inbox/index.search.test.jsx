import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => Object.fromEntries([
    "authorizeIdentityLink", "claimConversation", "closeConversation", "getAgentSettings", "getThreadMessages",
    "getThreads", "getInboxMetrics", "getWhatsappToken", "releaseConversation", "resetContactIdentity",
    "sendInboxMessage", "setWhatsappToken", "unlinkFamily", "updateAgentSettings", "verifyContactIdentity",
    "markThreadRead", "retryInboxMessage", "getThreadContext",
].map((key) => [key, vi.fn()])));
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({
    can: (permission) => permission === "agentinbox.send", user: { organization_timezone: "America/Tijuana" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";

const row = (name) => ({ contact_public_id: name, channel_account_public_id: "main", owner_name: name,
    conversation_public_id: `session-${name}`, state: "human_active", session_count: 1 });
const list = (names = ["Ana"], extra = {}) => ({ mode: "full", sync_cursor: "list-cursor", results: names.map(row),
    unread_total: 7, has_more: false, next_offset: null, ...extra });
const pending = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
async function flush() { await act(async () => {}); }
async function tick(ms) { await act(async () => vi.advanceTimersByTime(ms)); }
async function click(label) { fireEvent.click(screen.getByRole("button", { name: label, exact: true })); await flush(); }
function type(value) { fireEvent.change(screen.getByRole("searchbox", { name: "Buscar conversaciones" }), { target: { value } }); }
const lastParams = () => api.getThreads.mock.calls.at(-1)[0];
let hidden;

beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getThreads.mockResolvedValue(list());
    api.getInboxMetrics.mockResolvedValue(null);
    api.getThreadMessages.mockResolvedValue({ owner_name: "Ana", contact_public_id: "Ana", channel_account_public_id: "main",
        conversation: { public_id: "session-Ana", state: "human_active", session_window_open: true,
            session_window_expires_at: new Date(Date.now()+86400000).toISOString() }, messages: [], next_before: null });
    hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("WA-SRCH-01 — búsqueda de contactos", () => {
    it("ignora texto vacío o de un carácter sin hacer GET extra", async () => {
        render(<Inbox />); await flush(); type(" a "); await tick(300);
        expect(api.getThreads).toHaveBeenCalledTimes(1);
        type(" "); await tick(300); expect(api.getThreads).toHaveBeenCalledTimes(1);
    });
    it("espera exactamente 250 ms y envía el texto recortado al servidor", async () => {
        render(<Inbox />); await flush(); type("  Ana  "); await tick(249);
        expect(api.getThreads).toHaveBeenCalledTimes(1);
        api.getThreads.mockResolvedValueOnce(list(["Resultado del servidor"])); await tick(1);
        expect(lastParams()).toEqual({ q: "Ana" });
        expect(screen.getByRole("button", { name: /Resultado del servidor/ })).toBeVisible();
    });
    it("una ráfaga de teclas solo consulta el último texto", async () => {
        render(<Inbox />); await flush(); type("An"); await tick(100); type("Anabel"); await tick(249);
        expect(api.getThreads).toHaveBeenCalledTimes(1); await tick(1);
        expect(api.getThreads).toHaveBeenCalledTimes(2); expect(lastParams()).toEqual({ q: "Anabel" });
    });
    it.each(["ctrlKey", "metaKey"])("%s+K enfoca y selecciona el buscador", async (modifier) => {
        render(<Inbox />); await flush(); const input = screen.getByRole("searchbox"); type("Ana");
        fireEvent.keyDown(document, { key: "k", [modifier]: true });
        expect(input).toHaveFocus(); expect(input.selectionStart).toBe(0); expect(input.selectionEnd).toBe(3);
    });
    it("Escape limpia inmediatamente y conserva los segmentos", async () => {
        render(<Inbox />); await flush(); await click("Míos"); type("Ana"); await tick(250);
        fireEvent.keyDown(screen.getByRole("searchbox"), { key: "Escape" }); await flush();
        expect(lastParams()).toEqual({ claimed: "me" });
        expect(screen.getByRole("searchbox")).toHaveValue(""); expect(screen.getByRole("searchbox")).toHaveFocus();
    });
    it("limpiar antes del debounce cancela la búsqueda pendiente", async () => {
        render(<Inbox />); await flush(); type("Ana"); await tick(100); await click("Limpiar búsqueda"); await tick(300);
        expect(api.getThreads).toHaveBeenCalledTimes(1); expect(screen.getByRole("searchbox")).toHaveValue("");
    });
    it("aborta la búsqueda anterior y descarta una respuesta tardía", async () => {
        const wait = pending(); render(<Inbox />); await flush();
        api.getThreads.mockReturnValueOnce(wait.promise); type("Ana"); await tick(250);
        const signal = api.getThreads.mock.calls[1][1].signal;
        api.getThreads.mockResolvedValueOnce(list(["Cora"])); type("Cora"); await tick(250);
        expect(signal.aborted).toBe(true); expect(lastParams()).toEqual({ q: "Cora" });
        await act(async () => wait.resolve(list(["ANTIGUO"])));
        expect(screen.queryByRole("button", { name: /ANTIGUO/ })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Cora/ })).toBeVisible();
    });
    it("reinicia páginas y cursor al buscar y los conserva en los siguientes polls", async () => {
        api.getThreads.mockResolvedValueOnce(list(["Ana"], { has_more: true, next_offset: 100 }))
            .mockResolvedValueOnce(list(["Beto"]));
        render(<Inbox />); await flush(); await click("Cargar más");
        api.getThreads.mockResolvedValueOnce(list(["Cora"], { sync_cursor: "search-cursor", has_more: true, next_offset: 100 }));
        type("Cora"); await tick(250); expect(lastParams()).toEqual({ q: "Cora" });
        await click("Cargar más"); expect(lastParams()).toEqual({ q: "Cora", offset: 100 });
        api.getThreads.mockClear(); await tick(20000);
        expect(api.getThreads.mock.calls[0][0]).toEqual({ q: "Cora", since: "search-cursor" });
    });
    it("combina búsqueda, filtros AND y archivados", async () => {
        render(<Inbox />); await flush(); type("555 123"); await tick(250);
        await click("Sin atender"); await click("Urgentes"); await click("Míos"); await click("Archivadas");
        expect(lastParams()).toEqual({ q: "555 123", unanswered: 1, urgent: 1, claimed: "me", archived: 1 });
    });
    it("el vacío sugiere otra búsqueda y mantiene chat y borrador", async () => {
        render(<Inbox />); await flush(); await click(/Ana/);
        const draft = screen.getByRole("textbox"); fireEvent.change(draft, { target: { value: "Conservar" } });
        api.getThreads.mockResolvedValueOnce(list([])); type("Sin resultado"); await tick(250);
        expect(screen.getByText("Sin coincidencias")).toBeVisible();
        expect(screen.getByText(/Prueba otro nombre o teléfono/)).toBeVisible(); expect(draft).toHaveValue("Conservar");
        expect(api.getThreadMessages).toHaveBeenCalledTimes(1);
    });
    it("reintenta un fallo con la consulta vigente", async () => {
        render(<Inbox />); await flush(); api.getThreads.mockRejectedValueOnce(new Error("fallo sintético"));
        type("Ana"); await tick(250); await click("Reintentar ahora");
        expect(lastParams()).toEqual({ q: "Ana" }); expect(screen.getByRole("button", { name: /Ana/ })).toBeVisible();
    });
    it("volver a un carácter recupera la lista base sin reutilizar cursor", async () => {
        render(<Inbox />); await flush(); type("Ana"); await tick(250); type("A"); await tick(250);
        expect(lastParams()).toEqual({});
    });
    it("oculto no consulta la búsqueda y al volver usa el último texto", async () => {
        render(<Inbox />); await flush(); hidden = true; fireEvent(document, new Event("visibilitychange"));
        type("Ana"); await tick(250); expect(api.getThreads).toHaveBeenCalledTimes(1);
        hidden = false; fireEvent(document, new Event("visibilitychange")); await flush();
        expect(lastParams()).toEqual({ q: "Ana" });
    });
    it("desmontar cancela el debounce y el atajo global", async () => {
        const view = render(<Inbox />); await flush(); type("Ana"); view.unmount(); await tick(300);
        const key = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, cancelable: true });
        document.dispatchEvent(key); expect(key.defaultPrevented).toBe(false); expect(api.getThreads).toHaveBeenCalledTimes(1);
    });
});
