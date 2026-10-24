import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => Object.fromEntries([
    "authorizeIdentityLink", "claimConversation", "closeConversation", "getAgentSettings",
    "getThreadMessages", "getThreads", "getInboxMetrics", "getWhatsappToken", "releaseConversation",
    "resetContactIdentity", "sendInboxMessage", "setWhatsappToken", "unlinkFamily", "updateAgentSettings",
    "verifyContactIdentity", "markThreadRead", "retryInboxMessage", "getThreadContext",
].map((key) => [key, vi.fn()])));
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({
    can: (permission) => permission === "agentinbox.send", user: { organization_timezone: "America/Tijuana" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";

const pending = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const message = (id, body = `Mensaje ${id}`) => ({ id, body, direction: "in", author_type: "client",
    status: "processed", created_at: "2026-10-21T12:00:00Z" });
const row = (contact) => ({ contact_public_id: contact, channel_account_public_id: "main",
    owner_name: contact === "ana" ? "Ana" : contact === "beto" ? "Beto" : "Cora",
    conversation_public_id: `session-${contact}`, state: "human_active", session_count: 1 });
const full = (contact = "ana") => ({ mode: "full", sync_cursor: `m-${contact}`, owner_name: row(contact).owner_name,
    contact_public_id: contact, channel_account_public_id: "main", contact_verification: "staff_verified",
    conversation: { public_id: `session-${contact}`, state: "human_active", session_window_open: true,
        session_window_expires_at: new Date(Date.now()+86400000).toISOString() },
    messages: [message(contact === "ana" ? 1 : 9)], next_before: null });
const list = (results = [row("ana"), row("beto")], extra = {}) => ({ mode: "full", sync_cursor: "l1",
    results, has_more: false, next_offset: null, unread_total: 0, ...extra });
const delta = (extra = {}) => ({ mode: "delta", sync_cursor: "m2", messages: [], removals: [], metadata: {}, ...extra });
const listDelta = (extra = {}) => ({ mode: "delta", sync_cursor: "l2", upserts: [], removals: [],
    has_more: false, next_offset: null, unread_total: 0, ...extra });
let hidden;
beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getThreads.mockResolvedValue(list());
    api.getThreadMessages.mockImplementation(async (contact) => full(contact));
    api.getInboxMetrics.mockResolvedValue(null);
    hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => hidden ? "hidden" : "visible");
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
async function flush() { await act(async () => {}); }
async function tick(ms = 10000) { await act(async () => vi.advanceTimersByTime(ms)); }
async function mount() {
    const view = render(<Inbox />); await flush();
    fireEvent.click(screen.getByRole("button", { name: /Ana/ })); await flush();
    return view;
}
const history = () => screen.getByRole("region", { name: "Mensajes de la conversación" });

describe("WA-PERF-03 — sincronización en Inbox", () => {
    it("tras cargar usa since en lista y transcript sin volver a descargar mensajes", async () => {
        await mount(); api.getThreads.mockResolvedValue(listDelta()); api.getThreadMessages.mockResolvedValue(delta());
        await tick(20000);
        expect(api.getThreads.mock.calls[1][0]).toEqual({ since: "l1" });
        expect(api.getThreadMessages.mock.calls[1][2]).toEqual({ since: "m-ana", floor: 1 });
        expect(history().querySelectorAll("[data-message-id]")).toHaveLength(1);
        expect(within(history()).getByText("Mensaje 1")).toBeVisible();
    });
    it("actualiza una fila y añade una nueva sin duplicar ni perder el borrador", async () => {
        await mount(); const draft = screen.getByRole("textbox");
        fireEvent.change(draft, { target: { value: "Conservar" } });
        api.getThreadMessages.mockResolvedValue(delta({ messages: [message(1, "Actualizado"), message(2)] }));
        await tick(); await tick();
        expect(history().querySelectorAll("[data-message-id]")).toHaveLength(2);
        expect(within(history()).getByText("Actualizado")).toBeVisible();
        expect(draft).toHaveValue("Conservar");
    });
    it("retira IDs explícitos sin borrar otros mensajes", async () => {
        await mount(); api.getThreadMessages.mockResolvedValue(delta({ messages: [message(2)], removals: [1] }));
        await tick();
        expect(within(history()).queryByText("Mensaje 1")).not.toBeInTheDocument();
        expect(within(history()).getByText("Mensaje 2")).toBeVisible();
    });
    it("cursor rechazado recupera el rango cargado una sola vez", async () => {
        await mount(); api.getThreadMessages.mockRejectedValueOnce({ response: { data: { code: "invalid_sync_cursor" } } })
            .mockResolvedValueOnce({ ...full(), sync_cursor: "fresh", messages: [message(2)], reset_range: true });
        await tick();
        expect(api.getThreadMessages.mock.calls.slice(1).map((call) => call[2])).toEqual([
            { since: "m-ana", floor: 1 }, { floor: 1 }]);
        expect(within(history()).queryByText("Mensaje 1")).not.toBeInTheDocument();
        expect(within(history()).getByText("Mensaje 2")).toBeVisible();
    });
    it("un delta de lista incompleto recupera full sin publicar el estado parcial", async () => {
        await mount(); api.getThreads.mockResolvedValueOnce(listDelta({ order: ["missing:main"] }))
            .mockResolvedValueOnce(list([row("cora")], { sync_cursor: "fresh" }));
        await tick(20000);
        expect(api.getThreads.mock.calls.slice(1).map((call) => call[0])).toEqual([{ since: "l1" }, {}]);
        expect(screen.getByRole("button", { name: /Cora/ })).toBeVisible();
    });
    it("publica juntas las páginas con movimientos y sin duplicar un hilo", async () => {
        api.getThreads.mockResolvedValueOnce(list([row("ana")], { has_more: true, next_offset: 100 }));
        await mount(); api.getThreads.mockResolvedValueOnce(list([row("beto")], { sync_cursor: "page2" }));
        fireEvent.click(screen.getByRole("button", { name: "Cargar más" })); await flush();
        api.getThreads.mockResolvedValueOnce(listDelta({ upserts: [row("cora")], removals: ["ana:main"],
            order: ["cora:main"], has_more: true, next_offset: 100 }))
            .mockResolvedValueOnce(listDelta({ upserts: [row("ana")], order: ["beto:main", "ana:main"] }));
        await tick(20000);
        expect(screen.getAllByRole("button", { name: /Ana/ })).toHaveLength(1);
        expect(screen.getByRole("button", { name: /Beto/ })).toBeVisible();
        expect(screen.getByRole("button", { name: /Cora/ })).toBeVisible();
        expect(api.getThreads.mock.calls.slice(2).map((call) => call[0])).toEqual([
            { since: "l1" }, { offset: 100, since: "page2" }]);
    });
    it("mantiene una sola petición de transcript en vuelo", async () => {
        const wait = pending(); api.getThreadMessages.mockReturnValueOnce(wait.promise);
        await mount(); await tick(40000);
        expect(api.getThreadMessages).toHaveBeenCalledTimes(1);
        await act(async () => wait.resolve(full()));
        api.getThreadMessages.mockResolvedValue(delta()); await tick();
        expect(api.getThreadMessages).toHaveBeenCalledTimes(2);
    });
    it("mantiene una sola petición de lista en vuelo", async () => {
        const wait = pending(); api.getThreads.mockReturnValueOnce(wait.promise);
        render(<Inbox />); await tick(60000);
        expect(api.getThreads).toHaveBeenCalledTimes(1);
        await act(async () => wait.resolve(list()));
        api.getThreads.mockResolvedValue(listDelta()); await tick(20000);
        expect(api.getThreads).toHaveBeenCalledTimes(2);
    });
    it("cambiar de hilo aborta un delta viejo y no conserva su cursor", async () => {
        await mount(); const wait = pending(); api.getThreadMessages.mockReturnValueOnce(wait.promise);
        await tick(); const signal = api.getThreadMessages.mock.calls[1][3].signal;
        fireEvent.click(screen.getByRole("button", { name: /Beto/ })); await flush();
        expect(signal.aborted).toBe(true);
        expect(api.getThreadMessages.mock.calls[2].slice(0, 3)).toEqual(["beto", "main", {}]);
        await act(async () => wait.resolve(delta({ messages: [message(8, "ANTIGUO")] })));
        expect(within(history()).queryByText("ANTIGUO")).not.toBeInTheDocument();
        expect(within(history()).getByText("Mensaje 9")).toBeVisible();
    });
    it("oculto no inicia polls y al volver conserva cursores delta", async () => {
        await mount(); api.getThreads.mockResolvedValue(listDelta()); api.getThreadMessages.mockResolvedValue(delta());
        hidden = true; fireEvent(document, new Event("visibilitychange")); await tick(60000);
        expect(api.getThreads).toHaveBeenCalledTimes(1); expect(api.getThreadMessages).toHaveBeenCalledTimes(1);
        hidden = false; fireEvent(document, new Event("visibilitychange")); await flush();
        expect(api.getThreads.mock.calls[1][0].since).toBe("l1");
        expect(api.getThreadMessages.mock.calls[1][2].since).toBe("m-ana");
    });
    it("un fallo HTTP conserva el cursor y reintenta delta en el siguiente poll", async () => {
        await mount(); api.getThreadMessages.mockRejectedValueOnce({ response: { status: 503 } })
            .mockResolvedValueOnce(delta({ messages: [message(2)] }));
        await tick(); expect(within(history()).getByText("Mensaje 1")).toBeVisible();
        await tick(); expect(within(history()).getByText("Mensaje 2")).toBeVisible();
        expect(api.getThreadMessages.mock.calls.slice(1).map((call) => call[2].since)).toEqual(["m-ana", "m-ana"]);
    });
    it("metadatos de archivo retiran composer y conservan historia", async () => {
        await mount(); api.getThreadMessages.mockResolvedValue(delta({ metadata: { conversation: null } }));
        await tick(); expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
        expect(within(history()).getByText("Mensaje 1")).toBeVisible();
    });
    it("ampliar el rango retira una fila histórica que desapareció mientras cargaba", async () => {
        await mount(); api.getThreadMessages.mockResolvedValueOnce(delta({ messages: [message(2)], range_ids: [2] }));
        await tick(); expect(within(history()).queryByText("Mensaje 1")).not.toBeInTheDocument();
        expect(within(history()).getByText("Mensaje 2")).toBeVisible();
    });
    it("cambiar filtro aborta lista y empieza con un cursor propio", async () => {
        await mount(); const wait = pending(); api.getThreads.mockReturnValueOnce(wait.promise);
        await tick(20000); const signal = api.getThreads.mock.calls[1][1].signal;
        fireEvent.click(screen.getByRole("button", { name: "Archivadas" })); await flush();
        expect(signal.aborted).toBe(true);
        expect(api.getThreads.mock.calls[2][0]).toEqual({ archived: 1 });
        await act(async () => wait.resolve(listDelta({ removals: ["ana:main", "beto:main"], order: [] })));
        expect(screen.getByRole("button", { name: /Ana/ })).toBeVisible();
    });
    it("desmontar cancela ambos recursos", async () => {
        const view = await mount(); const a = pending(); const b = pending();
        api.getThreads.mockReturnValueOnce(a.promise); api.getThreadMessages.mockReturnValueOnce(b.promise);
        await tick(20000);
        const listSignal = api.getThreads.mock.calls[1][1].signal;
        const threadSignal = api.getThreadMessages.mock.calls[1][3].signal;
        view.unmount(); expect(listSignal.aborted).toBe(true); expect(threadSignal.aborted).toBe(true);
        await act(async () => { a.resolve(listDelta()); b.resolve(delta()); });
    });
    it("conserva el floor opaco del servidor al ampliar historial y reconcilia su rango", async () => {
        api.getThreadMessages.mockResolvedValueOnce({ ...full(), messages: [message(51)],
            next_before: 51, sync_floor: "signed-floor-51" });
        await mount();
        api.getThreadMessages.mockResolvedValueOnce({ messages: [message(1), message(2)], next_before: null,
            sync_floor: "signed-floor-1" });
        fireEvent.click(screen.getByText("Cargar anteriores", { selector: "button" })); await flush();
        expect(within(history()).getByText("Mensaje 1")).toBeVisible();
        api.getThreadMessages.mockResolvedValueOnce(delta({ messages: [message(2)], range_ids: [2, 51] }));
        await tick();
        expect(api.getThreadMessages.mock.calls[2][2]).toEqual({ since: "m-ana", floor: "signed-floor-1" });
        expect(within(history()).queryByText("Mensaje 1")).not.toBeInTheDocument();
        expect(within(history()).getByText("Mensaje 2")).toBeVisible();
        expect(within(history()).getByText("Mensaje 51")).toBeVisible();
    });
});
