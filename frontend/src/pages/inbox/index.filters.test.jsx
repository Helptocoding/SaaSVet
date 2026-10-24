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
async function click(label) { fireEvent.click(screen.getByRole("button", { name: label, exact: true })); await flush(); }
const lastParams = () => api.getThreads.mock.calls.at(-1)[0];

beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getThreads.mockResolvedValue(list());
    api.getInboxMetrics.mockResolvedValue(null);
    api.getThreadMessages.mockResolvedValue({ owner_name: "Ana", contact_public_id: "Ana", channel_account_public_id: "main",
        conversation: { public_id: "session-Ana", state: "human_active", session_window_open: true,
            session_window_expires_at: new Date(Date.now()+86400000).toISOString() }, messages: [], next_before: null });
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("WA-FIL-01 — segmentos del Inbox", () => {
    it.each([["Sin atender", { unanswered: 1 }], ["Esperando cliente", { unanswered: 0 }],
        ["Urgentes", { urgent: 1 }], ["Míos", { claimed: "me" }]])("%s envía filtro al servidor y muestra su respuesta", async (label, params) => {
        render(<Inbox />); await flush();
        api.getThreads.mockResolvedValueOnce(list(["Beto"])); await click(label);
        expect(lastParams()).toEqual(params);
        expect(screen.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByRole("button", { name: /Beto/ })).toBeVisible();
        expect(screen.queryByRole("button", { name: /Ana/ })).not.toBeInTheDocument();
    });
    it("combina segmentos AND, conserva archivo y permite desactivar", async () => {
        render(<Inbox />); await flush();
        await click("Sin atender"); await click("Urgentes"); await click("Míos"); await click("Archivadas");
        expect(lastParams()).toEqual({ archived: 1, unanswered: 1, urgent: 1, claimed: "me" });
        await click("Urgentes");
        expect(lastParams()).toEqual({ archived: 1, unanswered: 1, claimed: "me" });
    });
    it("los estados de atención son excluyentes y un segundo clic los limpia", async () => {
        render(<Inbox />); await flush(); await click("Sin atender"); await click("Esperando cliente");
        expect(lastParams()).toEqual({ unanswered: 0 });
        expect(screen.getByRole("button", { name: "Sin atender", exact: true })).toHaveAttribute("aria-pressed", "false");
        await click("Esperando cliente"); expect(lastParams()).toEqual({});
    });
    it("descarta páginas y cursores previos, aborta peticiones y rechaza respuestas tardías", async () => {
        const wait = pending();
        api.getThreads.mockResolvedValueOnce(list(["Ana"], { has_more: true, next_offset: 100 }))
            .mockResolvedValueOnce(list(["Beto"], { has_more: true, next_offset: 200 })).mockReturnValueOnce(wait.promise);
        render(<Inbox />); await flush(); await click("Cargar más");
        await act(async () => vi.advanceTimersByTime(20000));
        const signal = api.getThreads.mock.calls[2][1].signal;
        api.getThreads.mockResolvedValueOnce(list(["Cora"])); await click("Míos");
        expect(signal.aborted).toBe(true);
        expect(lastParams()).toEqual({ claimed: "me" });
        await act(async () => wait.resolve(list(["ANTIGUO"])));
        expect(screen.queryByRole("button", { name: /ANTIGUO|Beto|Ana/ })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Cora/ })).toBeVisible();
        expect(screen.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
    });
    it("paginación y polls conservan el filtro y su cursor propio", async () => {
        render(<Inbox />); await flush();
        api.getThreads.mockResolvedValueOnce(list(["Beto"], { sync_cursor: "filtered", has_more: true, next_offset: 100 }));
        await click("Sin atender"); await click("Cargar más");
        expect(lastParams()).toEqual({ unanswered: 1, offset: 100 });
        api.getThreads.mockClear();
        await act(async () => vi.advanceTimersByTime(20000));
        expect(api.getThreads.mock.calls[0][0]).toEqual({ unanswered: 1, since: "filtered" });
    });
    it("conserva conversación abierta, borrador y total de no leídos al filtrar", async () => {
        render(<Inbox />); await flush(); await click(/Ana/);
        const draft = screen.getByRole("textbox"); fireEvent.change(draft, { target: { value: "Conservar borrador" } });
        api.getThreads.mockResolvedValueOnce(list([])); await click("Míos");
        expect(draft).toHaveValue("Conservar borrador");
        expect(screen.getByText("Sin coincidencias")).toBeVisible();
        expect(screen.getByLabelText("7 mensajes sin leer en conversaciones activas")).toHaveTextContent("7");
        expect(api.getThreadMessages).toHaveBeenCalledTimes(1);
    });
    it("un error del filtro permite reintentar con los mismos parámetros", async () => {
        render(<Inbox />); await flush(); api.getThreads.mockRejectedValueOnce(new Error("fallo sintético"));
        await click("Urgentes"); expect(screen.getByText("No se pudieron cargar las conversaciones")).toBeVisible();
        await click("Reintentar ahora"); expect(lastParams()).toEqual({ urgent: 1 });
        expect(screen.getByRole("button", { name: /Ana/ })).toBeVisible();
    });
});
