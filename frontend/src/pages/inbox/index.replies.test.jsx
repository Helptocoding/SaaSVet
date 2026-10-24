import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => Object.fromEntries([
    "assignConversation", "authorizeIdentityLink", "claimConversation", "closeConversation", "getAgentSettings",
    "getThreadMessages", "getThreads", "getInboxMetrics", "getWhatsappToken", "releaseConversation",
    "resetContactIdentity", "sendInboxMessage", "setWhatsappToken", "unlinkFamily", "updateAgentSettings",
    "verifyContactIdentity", "markThreadRead", "retryInboxMessage", "getThreadContext", "getAssignableUsers", "getInboxMedia",
].map((key) => [key, vi.fn()])));
const permissions = vi.hoisted(() => ({ send: true }));
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => ({
    can: (permission) => permissions.send && permission === "agentinbox.send",
    user: { organization_timezone: "UTC" },
}) }));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import Inbox from "./index";

const message = (id, extra = {}) => ({ id, body: `Pregunta ${id}`, direction: "in", author_type: "client",
    payload_type: "text", status: "processed", created_at: "2026-10-21T12:00:00Z", ...extra });
const row = (name, account = "main") => ({ contact_public_id: name, channel_account_public_id: account,
    owner_name: `${name}-${account}`, conversation_public_id: `session-${name}-${account}`, state: "human_active" });
const packet = (name, account = "main", extra = {}) => ({ owner_name: `${name}-${account}`,
    contact_public_id: name, channel_account_public_id: account,
    conversation: { public_id: `session-${name}-${account}`, state: "human_active", session_window_open: true,
        session_window_expires_at: new Date(Date.now() + 86400000).toISOString() },
    messages: [message(name === "Ana" ? 1 : 11), message(name === "Ana" ? 2 : 12)], next_before: null, ...extra });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const flush = async () => { await act(async () => {}); };
const composer = () => screen.getByRole("textbox", { name: "Respuesta al cliente" });
const chip = () => screen.getByRole("status", { name: "Mensaje citado" });
const bubble = (id) => document.querySelector(`[data-message-id="${id}"]`);
async function click(name) { fireEvent.click(screen.getByRole("button", { name, exact: true })); await flush(); }
async function select(name = "Ana-main") { await click(new RegExp(`^${name}`)); }
async function reply(id = 1) {
    fireEvent.click(within(bubble(id)).getByRole("button", { name: "Responder al mensaje" })); await flush();
}
async function start() { const view = render(<Inbox />); await flush(); await select(); return view; }

beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    Object.values(api).forEach((mock) => mock.mockReset()); permissions.send = true;
    api.getThreads.mockResolvedValue({ results: [row("Ana"), row("Beto"), row("Ana", "second")], has_more: false });
    api.getInboxMetrics.mockResolvedValue(null);
    api.getThreadMessages.mockImplementation((name, account) => Promise.resolve(packet(name, account)));
    api.sendInboxMessage.mockImplementation((sessionId, body, key) => Promise.resolve(message(200, {
        body, client_message_id: key, direction: "out", author_type: "human_staff", status: "pending",
    })));
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("WA-RPL-05 — composer de respuesta", () => {
    it("MED-05 conserva caption y cita junto al adjunto pendiente", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { messages: [message(1, {
            body: "Foto de Luna", payload_type: "image", media: { public_id: "pending-image", status: "pending" },
            reply_to: { id: 19, author_type: "client", excerpt: "Consulta previa", payload_type: "text", status: "processed" },
        })] }));
        await start();
        expect(within(bubble(1)).getByText("Foto de Luna")).toBeVisible();
        expect(within(bubble(1)).getByText("Consulta previa")).toBeVisible();
        expect(within(bubble(1)).getByText("Recibiendo archivo…")).toBeVisible();
        expect(screen.getAllByText("Foto de Luna")).toHaveLength(1);
        expect(api.getInboxMedia).not.toHaveBeenCalled();
        await reply(); expect(chip()).toHaveTextContent("Foto de Luna");
    });
    it.each([["image", "Foto"], ["audio", "Nota de voz"], ["video", "Video"], ["sticker", "Sticker"], ["document", "study.pdf"]])(
        "MED-05 la lista muestra preview legible de %s sin caption", async (kind, label) => {
            api.getThreads.mockResolvedValue({ results: [{ ...row("Ana"), last_message_preview: "",
                last_message_type: kind, last_message_filename: "study.pdf" }], has_more: false });
            render(<Inbox />); await flush();
            expect(screen.getByRole("button", { name: new RegExp(`Ana-main.*${label}`) })).toBeVisible();
        },
    );
    it("selecciona una cita con autor y extracto, enfoca el campo y conserva el borrador", async () => {
        await start(); fireEvent.change(composer(), { target: { value: "Borrador intacto" } }); await reply();
        expect(within(chip()).getByText("Respondiendo a Ana-main")).toBeVisible();
        expect(within(chip()).getByText("Pregunta 1")).toBeVisible();
        expect(composer()).toHaveValue("Borrador intacto"); expect(composer()).toHaveFocus();
        expect(composer()).toHaveAttribute("aria-describedby", "inbox-reply-preview");
    });
    it("seleccionar otro mensaje sustituye la única cita activa", async () => {
        await start(); await reply(); await reply(2);
        expect(screen.getAllByRole("status", { name: "Mensaje citado" })).toHaveLength(1);
        expect(within(chip()).getByText("Pregunta 2")).toBeVisible();
        expect(within(chip()).queryByText("Pregunta 1")).not.toBeInTheDocument();
    });
    it.each(["Escape", "botón"])("cancelar mediante %s conserva texto y foco", async (method) => {
        await start(); await reply(); fireEvent.change(composer(), { target: { value: "No borrar" } });
        if (method === "Escape") fireEvent.keyDown(composer(), { key: "Escape" });
        else await click("Cancelar respuesta citada");
        expect(screen.queryByRole("status", { name: "Mensaje citado" })).not.toBeInTheDocument();
        expect(composer()).toHaveValue("No borrar"); expect(composer()).toHaveFocus();
        expect(api.sendInboxMessage).not.toHaveBeenCalled();
    });
    it.each(["Enter", "botón"])("envía con %s la cita capturada y limpia antes del acuse", async (method) => {
        const wait = deferred(); api.sendInboxMessage.mockReturnValueOnce(wait.promise);
        await start(); await reply(); fireEvent.change(composer(), { target: { value: " Respuesta " } });
        if (method === "Enter") fireEvent.keyDown(composer(), { key: "Enter" });
        else fireEvent.click(screen.getByRole("button", { name: "Enviar", exact: true }));
        expect(api.sendInboxMessage).toHaveBeenCalledWith("session-Ana-main", "Respuesta", expect.any(String),
            { signal: expect.any(AbortSignal), replyToId: 1 });
        expect(composer()).toHaveValue("");
        expect(screen.queryByRole("status", { name: "Mensaje citado" })).not.toBeInTheDocument();
        const key = api.sendInboxMessage.mock.calls[0][2];
        expect(within(bubble(key)).getByRole("button", { name: "Responder al mensaje" })).toBeDisabled();
        await act(async () => wait.resolve(message(200, { body: "Respuesta", client_message_id: key, direction: "out" })));
        expect(within(bubble(key)).getByRole("button", { name: "Responder al mensaje" })).toBeEnabled();
    });
    it("cancelar y enviar después omite replyToId", async () => {
        await start(); await reply(); await click("Cancelar respuesta citada");
        fireEvent.change(composer(), { target: { value: "Normal" } }); await click("Enviar");
        expect(api.sendInboxMessage.mock.calls[0][3]).toEqual({ signal: expect.any(AbortSignal) });
    });
    it.each(["Beto-main", "Ana-second"])("cambiar a %s cancela la cita aunque sea la misma persona", async (name) => {
        await start(); await reply(); await select(name);
        expect(screen.queryByRole("status", { name: "Mensaje citado" })).not.toBeInTheDocument();
        expect(composer()).toHaveValue("");
        fireEvent.change(composer(), { target: { value: "Nuevo hilo" } }); await click("Enviar");
        expect(api.sendInboxMessage.mock.calls[0][3]).not.toHaveProperty("replyToId");
    });
    it("volver a pulsar el hilo seleccionado conserva la cita", async () => {
        await start(); await reply(); await select(); expect(chip()).toBeVisible();
    });
    it("un poll del mismo episodio conserva cita y borrador", async () => {
        await start(); await reply(); fireEvent.change(composer(), { target: { value: "Conservar" } });
        await act(async () => vi.advanceTimersByTime(10000));
        expect(chip()).toBeVisible(); expect(composer()).toHaveValue("Conservar");
    });
    it("otro episodio retira la cita antes de permitir un envío nuevo", async () => {
        await start(); await reply();
        api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { conversation: {
            ...packet("Ana").conversation, public_id: "new-session" } }));
        await act(async () => vi.advanceTimersByTime(10000));
        expect(screen.queryByRole("status", { name: "Mensaje citado" })).not.toBeInTheDocument();
    });
    it("sin permiso send no ofrece selección de cita ni composer", async () => {
        permissions.send = false; await start();
        expect(screen.queryByRole("button", { name: "Responder al mensaje" })).not.toBeInTheDocument();
        expect(screen.queryByRole("textbox", { name: "Respuesta al cliente" })).not.toBeInTheDocument();
    });
    it("el hilo archivado conserva lectura sin acciones de respuesta", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { conversation: null })); await start();
        expect(screen.getByText("Pregunta 1")).toBeVisible();
        expect(screen.queryByRole("button", { name: "Responder al mensaje" })).not.toBeInTheDocument();
    });
    it("una ventana cerrada deshabilita seleccionar y enviar", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { conversation: {
            ...packet("Ana").conversation, session_window_open: false } })); await start();
        expect(within(bubble(1)).getByRole("button", { name: "Responder al mensaje" })).toBeDisabled();
        fireEvent.keyDown(composer(), { key: "Enter" }); expect(api.sendInboxMessage).not.toHaveBeenCalled();
    });
    it("si vence la ventana después de seleccionar no envía la cita", async () => {
        vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
        api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { conversation: {
            ...packet("Ana").conversation, session_window_expires_at: new Date(Date.now() + 500).toISOString() } }));
        await start(); await reply(); fireEvent.change(composer(), { target: { value: "Conservar al vencer" } });
        await act(async () => vi.advanceTimersByTime(501)); fireEvent.keyDown(composer(), { key: "Enter" });
        expect(api.sendInboxMessage).not.toHaveBeenCalled(); expect(chip()).toBeVisible();
        await click("Cancelar respuesta citada"); expect(composer()).toHaveValue("Conservar al vencer");
    });
    it("media sin cuerpo mantiene una cita seleccionable con su tipo", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { messages: [message(1, { body: "", payload_type: "image" })] }));
        await start(); await reply(); expect(within(chip()).getByText("[image]")).toBeVisible();
    });
    it.each([["human_staff", "Lucía", "Lucía"], ["agent", null, "Asistente"]])(
        "cita al autor saliente %s con su etiqueta existente", async (author_type, human_author_name, label) => {
            api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { messages: [message(1,
                { direction: "out", author_type, human_author_name, status: "failed" })] }));
            await start(); await reply(); expect(within(chip()).getByText(`Respondiendo a ${label}`)).toBeVisible();
        },
    );
    it("acota el extracto a 80 puntos Unicode sin cortar un emoji", async () => {
        api.getThreadMessages.mockResolvedValue(packet("Ana", "main", { messages: [message(1, { body: "🐾".repeat(81) })] }));
        await start(); await reply(); expect(within(chip()).getByText("🐾".repeat(80))).toBeVisible();
    });
    it("un reintento conserva key y cita originales sin consumir la selección siguiente", async () => {
        api.sendInboxMessage.mockRejectedValueOnce(new Error("Red interrumpida"));
        await start(); await reply(); fireEvent.change(composer(), { target: { value: "Reintentar original" } }); await click("Enviar");
        const first = api.sendInboxMessage.mock.calls[0]; await reply(2); await click("Reintentar");
        const retry = api.sendInboxMessage.mock.calls[1];
        expect(retry.slice(0, 3)).toEqual(first.slice(0, 3)); expect(retry[3].replyToId).toBe(1);
        expect(within(chip()).getByText("Pregunta 2")).toBeVisible();
    });
    it("un POST antiguo no retira la cita seleccionada en el hilo nuevo", async () => {
        const wait = deferred(); api.sendInboxMessage.mockReturnValueOnce(wait.promise);
        await start(); await reply(); fireEvent.change(composer(), { target: { value: "Ana" } }); await click("Enviar");
        const key = api.sendInboxMessage.mock.calls[0][2]; await select("Beto-main"); await reply(11);
        await act(async () => wait.resolve(message(200, { body: "Ana", client_message_id: key, direction: "out" })));
        expect(within(chip()).getByText("Pregunta 11")).toBeVisible(); expect(composer()).toHaveValue("");
    });
    it("Enter de composición IME y Shift+Enter no consumen la cita", async () => {
        await start(); await reply(); fireEvent.change(composer(), { target: { value: "Entrada" } });
        fireEvent.keyDown(composer(), { key: "Enter", isComposing: true });
        fireEvent.keyDown(composer(), { key: "Enter", shiftKey: true });
        expect(api.sendInboxMessage).not.toHaveBeenCalled(); expect(chip()).toBeVisible();
    });
    it("un texto vacío no consume la cita seleccionada", async () => {
        await start(); await reply(); fireEvent.keyDown(composer(), { key: "Enter" });
        expect(api.sendInboxMessage).not.toHaveBeenCalled(); expect(chip()).toBeVisible();
    });
});
