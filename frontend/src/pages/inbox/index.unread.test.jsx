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
    can: (permission) => permission === "agentinbox.view", user: { organization_timezone: "UTC" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";
import { toast } from "sonner";

let focus, visibility, hidden, snapshots;
const message = (id) => ({ id, direction: "in", status: "processed", author_type: "client",
    body: `Mensaje ${id}`, created_at: "2026-10-21T12:00:00Z" });
const rows = () => Object.entries(snapshots).map(([contact, data]) => ({
    contact_public_id: contact, channel_account_public_id: "main", owner_name: data.owner_name,
    conversation_public_id: data.conversation.public_id, state: "active", session_count: 1,
    unread_count: data.unread_count, last_message_preview: "Mensaje de prueba",
}));
const total = () => 20 + Object.values(snapshots).reduce((sum, row) => sum + row.unread_count, 0);
const list = () => ({ results: rows(), unread_total: total(), has_more: true, next_offset: 100 });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const tick = async (ms) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
beforeEach(() => {
    vi.useFakeTimers();
    focus = vi.spyOn(document, "hasFocus").mockReturnValue(true);
    visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    snapshots = {
        ana: { owner_name: "Ana", conversation: { public_id: "session-ana", state: "active" },
            last_read_message_id: 1, unread_count: 2, first_unread_message_id: 2,
            latest_visible_inbound_id: 3, messages: [1, 2, 3].map(message) },
        beto: { owner_name: "Beto", conversation: { public_id: "session-beto", state: "active" },
            last_read_message_id: 6, unread_count: 4, first_unread_message_id: 7,
            latest_visible_inbound_id: 10, messages: [7, 8, 9, 10].map(message) },
    };
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getThreads.mockImplementation(async () => list());
    api.getThreadMessages.mockImplementation(async (contact) => ({ ...snapshots[contact] }));
    api.getInboxMetrics.mockResolvedValue(null);
    api.markThreadRead.mockImplementation(async (contact, _account, id) => {
        snapshots[contact] = { ...snapshots[contact], last_read_message_id: id,
            unread_count: 0, first_unread_message_id: null };
        return { last_read_message_id: id, unread_count: 0, unread_total: total() };
    });
    toast.error.mockReset();
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
async function mount(open = true) {
    render(<Inbox />);
    await act(async () => {});
    if (open) {
        fireEvent.click(screen.getByRole("button", { name: /Ana/ }));
        await act(async () => {});
    }
}

describe("WA-UNR-02 — contador y divisor en Inbox", () => {
    it("muestra total de todas las páginas y contadores por hilo", async () => {
        await mount(false);
        expect(screen.getByLabelText("26 mensajes sin leer en conversaciones activas")).toHaveTextContent("26");
        expect(within(screen.getByRole("button", { name: /Ana/ })).getByLabelText("2 mensajes sin leer")).toBeVisible();
        expect(screen.getByRole("button", { name: "Cargar más" })).toBeVisible();
    });
    it("sitúa el divisor antes del primer nuevo y lo quita al confirmar, con view solamente", async () => {
        await mount();
        const divider = screen.getByRole("separator", { name: "Mensajes nuevos" });
        expect(divider.nextElementSibling).toHaveAttribute("data-message-id", "2");
        expect(screen.queryByRole("button", { name: "Enviar" })).not.toBeInTheDocument();
        await tick(1499); expect(api.markThreadRead).not.toHaveBeenCalled();
        await tick(1);
        expect(api.markThreadRead.mock.calls[0].slice(0, 3)).toEqual(["ana", "main", 3]);
        expect(screen.queryByRole("separator", { name: "Mensajes nuevos" })).not.toBeInTheDocument();
        expect(within(screen.getByRole("button", { name: /Ana/ })).queryByLabelText(/sin leer/)).not.toBeInTheDocument();
        expect(screen.getByLabelText("24 mensajes sin leer en conversaciones activas")).toBeVisible();
        expect(screen.getByText("Mensaje 2")).toBeVisible();
    });
    it("la pérdida de visibilidad durante debounce conserva contador y divisor", async () => {
        await mount(); await tick(1000);
        visibility.mockReturnValue("hidden"); hidden.mockReturnValue(true);
        fireEvent(document, new Event("visibilitychange"));
        await tick(21000);
        expect(api.markThreadRead).not.toHaveBeenCalled();
        expect(screen.getByRole("separator", { name: "Mensajes nuevos" })).toBeInTheDocument();
        expect(screen.getByLabelText("2 mensajes sin leer")).toBeInTheDocument();
    });
    it("no marca al abrir sin foco aunque se pueda ver el historial", async () => {
        focus.mockReturnValue(false);
        await mount(); await tick(2000);
        expect(api.markThreadRead).not.toHaveBeenCalled();
        expect(screen.getByRole("separator", { name: "Mensajes nuevos" })).toBeVisible();
    });
    it("el error se reintenta en el próximo poll sin toast ni desaparición anticipada", async () => {
        api.markThreadRead.mockRejectedValueOnce(new Error("offline"));
        await mount(); await tick(1500);
        expect(screen.getByRole("separator", { name: "Mensajes nuevos" })).toBeVisible();
        await tick(8499); expect(api.markThreadRead).toHaveBeenCalledTimes(1);
        await tick(1501); expect(api.markThreadRead).toHaveBeenCalledTimes(2);
        expect(screen.queryByRole("separator", { name: "Mensajes nuevos" })).not.toBeInTheDocument();
        expect(toast.error).not.toHaveBeenCalled();
    });
    it("cambiar de hilo durante debounce solo marca el nuevo destino", async () => {
        await mount(); await tick(1000);
        fireEvent.click(screen.getByRole("button", { name: /Beto/ }));
        await act(async () => {}); await tick(1500);
        expect(api.markThreadRead).toHaveBeenCalledTimes(1);
        expect(api.markThreadRead.mock.calls[0].slice(0, 3)).toEqual(["beto", "main", 10]);
    });
    it("un GET de lista iniciado antes del POST no revive el contador", async () => {
        const pendingRead = deferred(), pendingList = deferred();
        api.markThreadRead.mockReturnValueOnce(pendingRead.promise);
        await mount(); await tick(1500);
        const stale = list();
        api.getThreads.mockReturnValueOnce(pendingList.promise);
        await tick(18500);
        snapshots.ana = { ...snapshots.ana, unread_count: 0, last_read_message_id: 3, first_unread_message_id: null };
        await act(async () => pendingRead.resolve({ last_read_message_id: 3, unread_count: 0, unread_total: 24 }));
        await act(async () => pendingList.resolve(stale));
        expect(screen.queryByLabelText("2 mensajes sin leer")).not.toBeInTheDocument();
        expect(screen.getByLabelText("24 mensajes sin leer en conversaciones activas")).toBeVisible();
    });
    it("llegada → contador sube → apertura → divisor → lectura → contador baja", async () => {
        await mount(false);
        snapshots.ana = { ...snapshots.ana, unread_count: 3, latest_visible_inbound_id: 4,
            messages: [...snapshots.ana.messages, message(4)] };
        await tick(20000);
        expect(screen.getByLabelText("3 mensajes sin leer")).toBeVisible();
        fireEvent.click(screen.getByRole("button", { name: /Ana/ }));
        await act(async () => {});
        expect(screen.getByRole("separator", { name: "Mensajes nuevos" })).toBeVisible();
        await tick(1500);
        expect(api.markThreadRead.mock.calls[0][2]).toBe(4);
        expect(screen.queryByLabelText("3 mensajes sin leer")).not.toBeInTheDocument();
        expect(screen.queryByRole("separator", { name: "Mensajes nuevos" })).not.toBeInTheDocument();
    });
});
