import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const inboxApi = vi.hoisted(() => ({
    authorizeIdentityLink: vi.fn(),
    claimConversation: vi.fn(),
    closeConversation: vi.fn(),
    getAgentSettings: vi.fn(),
    getInboxMetrics: vi.fn(),
    getThreadMessages: vi.fn(),
    getThreadContext: vi.fn(),
    getThreads: vi.fn(),
    markThreadRead: vi.fn(),
    getWhatsappToken: vi.fn(),
    releaseConversation: vi.fn(),
    resetContactIdentity: vi.fn(),
    sendInboxMessage: vi.fn(),
    retryInboxMessage: vi.fn(),
    setWhatsappToken: vi.fn(),
    unlinkFamily: vi.fn(),
    updateAgentSettings: vi.fn(),
    verifyContactIdentity: vi.fn(),
}));

vi.mock("../../api/inbox", () => inboxApi);
const authPermissions = vi.hoisted(() => new Set(['agentinbox.send']));
vi.mock("../../auth/authContext", () => ({
    useAuth: () => ({
        can: (permission) => authPermissions.has(permission),
        user: { organization_timezone: "America/Tijuana" },
    }),
}));
vi.mock("../../components/useConfirm", () => ({
    useConfirm: () => vi.fn(() => Promise.resolve(true)),
}));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({
    toast: { error: vi.fn(), success: vi.fn() },
}));

import Inbox, { HandoffReasonBanner } from "./index";
import { toast } from "sonner";

describe('B5 handoff evidence', () => {
    it('does not call discarded guidance pending delivery', () => {
        render(<HandoffReasonBanner handoff={{ reason: 'safety_urgent', guidance_status: 'discarded' }} />);
        expect(screen.getByText(/descartada sin envío/)).toBeInTheDocument();
        expect(screen.queryByText(/pendiente de entrega/)).not.toBeInTheDocument();
    });
    it('allows the current human owner to explicitly acknowledge a new queued case', async () => {
        authPermissions.add('agentinbox.claim');
        inboxApi.getThreadMessages.mockImplementation((contactId) => Promise.resolve({
            ...threadFor(contactId), conversation: { public_id: 'session-ana', state: 'human_active' },
            handoff: { reason: 'safety_urgent', priority: 'urgent', state: 'QUEUED' },
            identity_case: { kind: 'owner_ambiguous' },
        }));
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, 'Ana');
        expect(screen.getByText(/Safety · Revisión urgente/)).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Acusar recibo' }));
        await waitFor(() => expect(inboxApi.claimConversation).toHaveBeenCalledWith('session-ana'));
    });
    it('shows a durable queue without inventing notification or acknowledgement', () => {
        render(<HandoffReasonBanner handoff={{ reason: 'safety_urgent', priority: 'urgent',
            state: 'QUEUED', notification_status: 'NOT_CONFIGURED', opened_at: '2026-09-16T10:00:00Z' }} />);
        expect(screen.getByText(/Safety · Revisión urgente/)).toBeInTheDocument();
        expect(screen.getByText(/Pendiente de acuse/)).toBeInTheDocument();
        expect(screen.getByText(/Sin canal secundario de aviso/)).toBeInTheDocument();
        expect(screen.queryByText(/Acuse explícito registrado/)).not.toBeInTheDocument();
    });
    it('labels explicit acknowledgement without claiming clinical attention', () => {
        render(<HandoffReasonBanner handoff={{ reason: 'safety_urgent', state: 'ACKNOWLEDGED' }} />);
        expect(screen.getByText(/Acuse explícito registrado/)).toBeInTheDocument();
        expect(screen.queryByText(/veterinario.*atendiendo/i)).not.toBeInTheDocument();
    });
    it('keeps uncertain guidance visible and preserves multiple open legacy cases', () => {
        render(<HandoffReasonBanner handoff={{ reason: 'safety_urgent', guidance_status: 'uncertain',
            open_cases: [{ id: 1, reason: 'explicit_request', priority: 'normal', opened_at: '2026-09-15', state: 'QUEUED' },
                { id: 2, reason: 'safety_urgent', priority: 'urgent', opened_at: '2026-09-16', state: 'QUEUED' }] }} />);
        expect(screen.getByText(/Guía al cliente: envío incierto/)).toBeInTheDocument();
        expect(screen.getAllByRole('listitem')).toHaveLength(2);
    });
});

const ACCOUNT_ID = "account-main";
const rows = [
    {
        contact_public_id: "contact-ana",
        channel_account_public_id: ACCOUNT_ID,
        owner_name: "Ana",
        state: "active",
        session_count: 1,
        last_message_preview: "Hola de Ana",
        last_activity_at: "2026-08-22T10:00:00Z",
    },
    {
        contact_public_id: "contact-beto",
        channel_account_public_id: ACCOUNT_ID,
        owner_name: "Beto",
        state: "active",
        session_count: 1,
        last_message_preview: "Hola de Beto",
        last_activity_at: "2026-08-22T10:01:00Z",
    },
];

const threadFor = (contactId) => {
    const isAna = contactId === "contact-ana";
    return {
        owner_name: isAna ? "Ana" : "Beto",
        conversation: {
            session_window_open: true,
            session_window_expires_at: new Date(Date.now() + 86400000).toISOString(),
            public_id: isAna ? "session-ana" : "session-beto",
            state: "active",
        },
        messages: [],
    };
};

const sentMessage = (body, clientMessageId, id = `message-${clientMessageId}`) => ({
    id,
    client_message_id: clientMessageId,
    body,
    direction: "out",
    author_type: "human_staff",
    human_author_name: "Recepción",
    payload_type: "text",
    status: "pending",
    failure_reason: "",
    created_at: "2026-08-23T18:45:00Z",
});

beforeEach(() => {
    authPermissions.clear();
    authPermissions.add('agentinbox.send');
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
        configurable: true,
        value: vi.fn(),
    });

    for (const mock of Object.values(inboxApi)) mock.mockReset();
    toast.error.mockReset();
    toast.success.mockReset();
    inboxApi.getThreads.mockResolvedValue(rows);
    inboxApi.getThreadMessages.mockImplementation((contactId) =>
        Promise.resolve(threadFor(contactId))
    );
    inboxApi.getInboxMetrics.mockResolvedValue(null);
    inboxApi.sendInboxMessage.mockImplementation((_sessionId, body, clientMessageId) =>
        Promise.resolve(sentMessage(body, clientMessageId))
    );
});

afterEach(() => {
    vi.useRealTimers();
});

const selectConversation = async (user, name) => {
    await user.click(await screen.findByRole("button", { name: new RegExp(name) }));
    await screen.findByText(name, { selector: "strong" });
    return screen.getByPlaceholderText("Escribe una respuesta…");
};

describe("WA-GTF-01 — navegación al final", () => {
    function readAbove() {
        const region = screen.getByRole("region", { name: "Mensajes de la conversación" });
        Object.defineProperties(region, {
            scrollHeight: { configurable: true, value: 1200 },
            clientHeight: { configurable: true, value: 400 },
            scrollTop: { configurable: true, value: 100 },
        });
        fireEvent.scroll(region);
        return region;
    }

    it("cambiar de hilo no conserva el botón del historial anterior", async () => {
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        readAbove();
        expect(screen.getByRole("button", { name: "Ir al final" })).toBeVisible();
        await selectConversation(user, "Beto");
        expect(screen.queryByRole("button", { name: "Ir al final" })).not.toBeInTheDocument();
        expect(screen.getByRole("region", { name: "Mensajes de la conversación" })).toBeVisible();
    });

    it("permite recorrer un hilo archivado sin habilitar el envío", async () => {
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"), conversation: null });
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: /Ana/ }));
        await screen.findByText("Ana", { selector: "strong" });
        const region = readAbove();
        region.scrollTo = vi.fn();
        await user.click(screen.getByRole("button", { name: "Ir al final" }));
        expect(region.scrollTo).toHaveBeenCalledWith({ top: 1200, behavior: "auto" });
        expect(screen.queryByPlaceholderText("Escribe una respuesta…")).not.toBeInTheDocument();
    });
});

describe("WA-AGT-01 — turno del asistente", () => {
    beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }));

    it.each([
        ["active", "Tomar y acusar recibo", "claimConversation"],
        ["human_active", "Liberar", "releaseConversation"],
    ])("%s: explica el turno y habilita %s al terminar", async (state, action, api) => {
        authPermissions.add("agentinbox.claim");
        const active = { ...threadFor("contact-ana"),
            conversation: { public_id: "session-ana", state, agent_processing: true } };
        inboxApi.getThreadMessages.mockResolvedValue(active);
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        expect(screen.getByText("El asistente está respondiendo…")).toHaveAttribute("role", "status");
        const button = screen.getByRole("button", { name: action });
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute("title", "Espera a que el asistente termine de responder.");
        await user.click(button);
        expect(inboxApi[api]).not.toHaveBeenCalled();
        inboxApi.getThreadMessages.mockResolvedValue({ ...active,
            conversation: { ...active.conversation, agent_processing: false } });
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(screen.queryByText("El asistente está respondiendo…")).not.toBeInTheDocument();
        expect(button).toBeEnabled();
        expect(button).not.toHaveAttribute("title");
        await user.click(button);
        expect(inboxApi[api]).toHaveBeenCalledWith("session-ana");
    });

    it("muestra el indicador sin conceder permiso para tomar o liberar", async () => {
        const data = threadFor("contact-ana");
        data.conversation.agent_processing = true;
        inboxApi.getThreadMessages.mockResolvedValue(data);
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        expect(screen.getByText("El asistente está respondiendo…")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /Tomar|Liberar/ })).not.toBeInTheDocument();
    });

    it("no hereda el indicador de otro hilo ni de la fila antigua", async () => {
        authPermissions.add("agentinbox.claim");
        inboxApi.getThreads.mockResolvedValue(rows.map((row) => ({ ...row, agent_processing: true })));
        inboxApi.getThreadMessages.mockImplementation((contactId) => {
            const data = threadFor(contactId);
            if (contactId === "contact-ana") data.conversation.agent_processing = true;
            return Promise.resolve(data);
        });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        expect(screen.getByText("El asistente está respondiendo…")).toBeInTheDocument();
        await selectConversation(user, "Beto");
        expect(screen.queryByText("El asistente está respondiendo…")).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Tomar y acusar recibo" })).toBeEnabled();
    });

    it("un hilo archivado no muestra turno ni acciones aunque la lista esté desactualizada", async () => {
        authPermissions.add("agentinbox.claim");
        inboxApi.getThreads.mockResolvedValue(rows.map((row) => ({ ...row, agent_processing: true })));
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"), conversation: null });
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: /Ana/ }));
        await screen.findByText("Ana", { selector: "strong" });
        expect(screen.queryByText("El asistente está respondiendo…")).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /Tomar|Liberar/ })).not.toBeInTheDocument();
    });
});

describe("WA-LDE-01 — carga y reconexión", () => {
    beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }));

    it("distingue carga inicial de lista y mensajes de un panel sin selección", async () => {
        let resolveList, resolveThread;
        inboxApi.getThreads.mockReturnValueOnce(new Promise((resolve) => { resolveList = resolve; }));
        inboxApi.getThreadMessages.mockReturnValueOnce(new Promise((resolve) => { resolveThread = resolve; }));
        const user = userEvent.setup();
        render(<Inbox />);
        expect(screen.getByRole("status", { name: "Cargando conversaciones" })).toBeInTheDocument();
        await act(async () => resolveList(rows));
        await user.click(screen.getByRole("button", { name: /Ana/ }));
        expect(screen.getByRole("status", { name: "Cargando mensajes" })).toBeInTheDocument();
        expect(screen.queryByText("Selecciona una conversación para ver los mensajes.")).not.toBeInTheDocument();
        await act(async () => resolveThread(threadFor("contact-ana")));
        expect(screen.queryByRole("status", { name: /Cargando/ })).not.toBeInTheDocument();
        expect(screen.getByPlaceholderText("Escribe una respuesta…")).toBeInTheDocument();
    });

    it("distingue el fallo inicial de lista vacía y permite reintentar", async () => {
        inboxApi.getThreads.mockRejectedValueOnce(new Error("offline"));
        const user = userEvent.setup();
        render(<Inbox />);
        const error = await screen.findByRole("alert", { name: "No se pudieron cargar las conversaciones" });
        expect(screen.queryByText("Sin conversaciones")).not.toBeInTheDocument();
        await user.click(within(error).getByRole("button", { name: "Reintentar ahora" }));
        expect(await screen.findByRole("button", { name: /Ana/ })).toBeInTheDocument();
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        expect(inboxApi.getThreads).toHaveBeenCalledTimes(2);
    });

    it("explica el fallo inicial de transcript y reintenta la misma conversación", async () => {
        inboxApi.getThreadMessages.mockRejectedValueOnce(new Error("offline"));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: /Ana/ }));
        const error = await screen.findByRole("alert", { name: "No se pudo cargar la conversación" });
        expect(screen.queryByText("Selecciona una conversación para ver los mensajes.")).not.toBeInTheDocument();
        await user.click(within(error).getByRole("button", { name: "Reintentar ahora" }));
        expect(await screen.findByPlaceholderText("Escribe una respuesta…")).toBeInTheDocument();
        expect(inboxApi.getThreadMessages).toHaveBeenLastCalledWith("contact-ana", ACCOUNT_ID, {}, { signal: expect.any(AbortSignal) });
        expect(toast.error).not.toHaveBeenCalled();
    });

    it.each([
        ["Conversaciones", "getThreads", 20_000], ["Mensajes", "getThreadMessages", 10_000],
    ])("%s: dos fallos muestran banner, conserva datos/borrador y reintenta sin duplicar", async (panel, api, interval) => {
        const transcript = { ...threadFor("contact-ana"), messages: [sentMessage("Historial conservado", "old", 1)] };
        inboxApi.getThreadMessages.mockResolvedValue(transcript);
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Borrador conservado");
        inboxApi[api].mockRejectedValue(new Error("offline"));
        await act(async () => vi.advanceTimersByTime(interval));
        expect(screen.queryByRole("status", { name: `${panel}: sin conexión` })).not.toBeInTheDocument();
        await act(async () => vi.advanceTimersByTime(interval));
        const banner = screen.getByRole("status", { name: `${panel}: sin conexión` });
        expect(within(banner).getByText(/Sin conexión — reintentando/)).toBeInTheDocument();
        expect(screen.getByText("Historial conservado")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Ana/ })).toBeInTheDocument();
        expect(composer).toHaveValue("Borrador conservado");
        expect(toast.error).not.toHaveBeenCalled();
        let resolveRetry;
        inboxApi[api].mockReturnValueOnce(new Promise((resolve) => { resolveRetry = resolve; }));
        const calls = inboxApi[api].mock.calls.length;
        await user.click(within(banner).getByRole("button", { name: "Reintentar ahora" }));
        const retrying = within(banner).getByRole("button", { name: "Reintentando…" });
        expect(retrying).toBeDisabled();
        await user.click(retrying);
        expect(inboxApi[api]).toHaveBeenCalledTimes(calls + 1);
        await act(async () => resolveRetry(api === "getThreads" ? rows : transcript));
        expect(screen.queryByRole("status", { name: `${panel}: sin conexión` })).not.toBeInTheDocument();
        expect(composer).toHaveValue("Borrador conservado");
        // Un fallo tras el éxito reinicia la racha, no hereda los dos anteriores.
        await act(async () => vi.advanceTimersByTime(interval));
        expect(screen.queryByRole("status", { name: `${panel}: sin conexión` })).not.toBeInTheDocument();
    });

    it("recupera ambos paneles automáticamente cuando vuelve la API", async () => {
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        inboxApi.getThreads.mockRejectedValue(new Error("offline"));
        inboxApi.getThreadMessages.mockRejectedValue(new Error("offline"));
        await act(async () => vi.advanceTimersByTime(20_000));
        await act(async () => vi.advanceTimersByTime(20_000));
        expect(screen.getByRole("status", { name: "Conversaciones: sin conexión" })).toBeInTheDocument();
        expect(screen.getByRole("status", { name: "Mensajes: sin conexión" })).toBeInTheDocument();
        inboxApi.getThreads.mockResolvedValue(rows);
        inboxApi.getThreadMessages.mockResolvedValue(threadFor("contact-ana"));
        await act(async () => vi.advanceTimersByTime(20_000));
        expect(screen.queryByRole("status", { name: /sin conexión/ })).not.toBeInTheDocument();
    });

    it("un fallo tardío del hilo anterior no contamina la racha del nuevo", async () => {
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        let rejectOld;
        inboxApi.getThreadMessages.mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
        await act(async () => vi.advanceTimersByTime(10_000));
        await selectConversation(user, "Beto");
        await act(async () => rejectOld(new Error("old request")));
        inboxApi.getThreadMessages.mockRejectedValueOnce(new Error("new first failure"));
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(screen.queryByRole("status", { name: "Mensajes: sin conexión" })).not.toBeInTheDocument();
        expect(screen.getByText("Beto", { selector: "strong" })).toBeInTheDocument();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it.each(["success", "failure"])("ignora %s tardío de lista tras cambiar de filtro", async (outcome) => {
        let resolveOld, rejectOld;
        inboxApi.getThreads
            .mockReturnValueOnce(new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject; }))
            .mockResolvedValueOnce([rows[1]]);
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(screen.getByRole("button", { name: "Archivadas" }));
        expect(await screen.findByRole("button", { name: /Beto/ })).toBeInTheDocument();
        await act(async () => outcome === "success" ? resolveOld([rows[0]]) : rejectOld(new Error("old request")));
        expect(screen.queryByRole("button", { name: /Ana/ })).not.toBeInTheDocument();
        inboxApi.getThreads.mockRejectedValueOnce(new Error("new first failure"));
        await act(async () => vi.advanceTimersByTime(20_000));
        expect(screen.queryByRole("status", { name: "Conversaciones: sin conexión" })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Beto/ })).toBeInTheDocument();
    });
});

describe("WA-VER-01 — verificación en lista y cabecera", () => {
    it.each([
        ["staff_verified", "Verificado"], ["confirmed_in_chat", "Verificado"],
        ["phone_match", "Teléfono coincide"], ["unknown", null],
    ])("representa %s en ambos paneles sin habilitar acciones de identidad", async (level, label) => {
        inboxApi.getThreads.mockResolvedValue([{ ...rows[0], contact_verification: level }]);
        const data = threadFor("contact-ana");
        inboxApi.getThreadMessages.mockResolvedValue({ ...data, contact_verification: level,
            conversation: { ...data.conversation, contact_verification: "staff_verified" } });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        const row = screen.getByRole("button", { name: /Ana/ });
        if (label) {
            expect(within(row).getByText(label)).toBeInTheDocument();
            expect(screen.getAllByText(label)).toHaveLength(2);
        } else {
            // Unknown explícito del hilo prevalece sobre una sesión legacy.
            expect(screen.queryByText("Verificado")).not.toBeInTheDocument();
            expect(screen.queryByText("Teléfono coincide")).not.toBeInTheDocument();
        }
        expect(inboxApi.verifyContactIdentity).not.toHaveBeenCalled();
        expect(inboxApi.authorizeIdentityLink).not.toHaveBeenCalled();
        expect(screen.queryByRole("button", { name: "Resetear identidad" })).not.toBeInTheDocument();
    });

    it("muestra la verificación del contacto incluso en un hilo archivado", async () => {
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"),
            contact_verification: "staff_verified", conversation: null });
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: /Ana/ }));
        expect(await screen.findByText("Verificado")).toBeInTheDocument();
        expect(screen.queryByPlaceholderText("Escribe una respuesta…")).not.toBeInTheDocument();
    });

    it("retira el distintivo cuando el siguiente poll informa unknown", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        inboxApi.getThreads.mockResolvedValue([{ ...rows[0], contact_verification: "staff_verified" }]);
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"), contact_verification: "staff_verified" });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        expect(screen.getAllByText("Verificado")).toHaveLength(2);
        inboxApi.getThreads.mockResolvedValue([{ ...rows[0], contact_verification: "unknown" }]);
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"), contact_verification: "unknown" });
        await act(async () => vi.advanceTimersByTime(20_000));
        expect(screen.queryByText("Verificado")).not.toBeInTheDocument();
    });
});

describe("WA-VIS-01 — polling del Inbox", () => {
    let hidden;
    const setHidden = async (value) => {
        hidden.mockReturnValue(value);
        await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    };
    beforeEach(() => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    });
    afterEach(() => hidden.mockRestore());

    it("pausa ambos polls y refresca lista/hilo al volver, conservando sus cadencias", async () => {
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        inboxApi.getThreads.mockClear();
        inboxApi.getThreadMessages.mockClear();
        await setHidden(true);
        await act(async () => vi.advanceTimersByTime(120_000));
        expect(inboxApi.getThreads).not.toHaveBeenCalled();
        expect(inboxApi.getThreadMessages).not.toHaveBeenCalled();
        await setHidden(false);
        expect(inboxApi.getThreads).toHaveBeenCalledTimes(1);
        expect(inboxApi.getThreadMessages).toHaveBeenCalledExactlyOnceWith("contact-ana", ACCOUNT_ID, {}, { signal: expect.any(AbortSignal) });
        // Let the resolved request settle between ticks; PERF-03 forbids
        // overlapping polls even when a fake clock batches multiple intervals.
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(inboxApi.getThreadMessages).toHaveBeenCalledTimes(2);
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(inboxApi.getThreads).toHaveBeenCalledTimes(2);
        expect(inboxApi.getThreadMessages).toHaveBeenCalledTimes(3);
    });

    it("cambia de hilo oculto sin consultar el anterior ni aplicar su respuesta tardía", async () => {
        let resolveOldPoll;
        inboxApi.getThreadMessages
            .mockResolvedValueOnce(threadFor("contact-ana"))
            .mockImplementationOnce(() => new Promise((resolve) => { resolveOldPoll = resolve; }));
        const user = userEvent.setup();
        const { unmount } = render(<Inbox />);
        await selectConversation(user, "Ana");
        await act(async () => vi.advanceTimersByTime(10_000));
        await setHidden(true);
        await user.click(screen.getByRole("button", { name: /Beto/ }));
        await act(async () => resolveOldPoll({ ...threadFor("contact-ana"),
            messages: [sentMessage("Respuesta antigua", "old", 1)] }));
        expect(screen.queryByText("Respuesta antigua")).not.toBeInTheDocument();
        expect(inboxApi.getThreadMessages).toHaveBeenCalledTimes(2);
        await setHidden(false);
        expect(inboxApi.getThreadMessages).toHaveBeenCalledTimes(3);
        expect(inboxApi.getThreadMessages).toHaveBeenLastCalledWith("contact-beto", ACCOUNT_ID, {}, { signal: expect.any(AbortSignal) });
        expect(await screen.findByText("Beto", { selector: "strong" })).toBeInTheDocument();
        const listCalls = inboxApi.getThreads.mock.calls.length;
        unmount();
        await setHidden(true);
        await setHidden(false);
        await act(async () => vi.advanceTimersByTime(60_000));
        expect(inboxApi.getThreads).toHaveBeenCalledTimes(listCalls);
        expect(inboxApi.getThreadMessages).toHaveBeenCalledTimes(3);
    });

    it("si inicia oculto no consulta la lista y usa el filtro vigente al volver", async () => {
        hidden.mockReturnValue(true);
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(screen.getByRole("button", { name: "Archivadas" }));
        await act(async () => vi.advanceTimersByTime(60_000));
        expect(inboxApi.getThreads).not.toHaveBeenCalled();
        expect(inboxApi.getThreadMessages).not.toHaveBeenCalled();
        await setHidden(false);
        expect(inboxApi.getThreads).toHaveBeenCalledExactlyOnceWith({ archived: 1 }, { signal: expect.any(AbortSignal) });
        expect(await screen.findByRole("button", { name: /Ana/ })).toBeInTheDocument();
    });
});

describe("WA-TAB-01 — lista real del Inbox", () => {
    it("refleja el último poll sin solicitar datos adicionales y restaura al salir", async () => {
        document.title = "SaaslyVet";
        const focus = vi.spyOn(document, "hasFocus").mockReturnValue(false);
        inboxApi.getThreads.mockResolvedValue(rows.map((row) => ({ ...row, has_unanswered: true })));
        const { unmount } = render(<Inbox />);
        try {
            await waitFor(() => expect(document.title).toBe("(2) SaaslyVet"));
            focus.mockReturnValue(true);
            act(() => window.dispatchEvent(new Event("focus")));
            expect(document.title).toBe("SaaslyVet");
            expect(inboxApi.getThreads).toHaveBeenCalledTimes(1);
            expect(inboxApi.getThreadMessages).not.toHaveBeenCalled();
        } finally {
            unmount();
            focus.mockRestore();
        }
        expect(document.title).toBe("SaaslyVet");
    });
});

describe("WA-CPY-01 — copiar y abrir enlaces", () => {
    afterEach(() => vi.restoreAllMocks());

    it("copia el cuerpo original completo, sin horas ni autor, y confirma el éxito", async () => {
        const body = "  Hola\nConsulta https://example.org/?a=1&b=2  ";
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"),
            messages: [sentMessage(body, "copy-1", 1)] });
        const user = userEvent.setup();
        const write = vi.spyOn(navigator.clipboard, "writeText");
        render(<Inbox />);
        await selectConversation(user, "Ana");
        await user.click(screen.getByRole("button", { name: "Copiar mensaje" }));
        expect(write).toHaveBeenCalledExactlyOnceWith(body);
        expect(toast.success).toHaveBeenCalledWith("Mensaje copiado");
        expect(inboxApi.sendInboxMessage).not.toHaveBeenCalled();
    });

    it("muestra un error recuperable cuando el navegador rechaza la copia", async () => {
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"),
            messages: [sentMessage("Mensaje a copiar", "copy-1", 1)] });
        const user = userEvent.setup();
        vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("NotAllowedError"));
        render(<Inbox />);
        await selectConversation(user, "Ana");
        await user.click(screen.getByRole("button", { name: "Copiar mensaje" }));
        expect(toast.error).toHaveBeenCalledWith("No se pudo copiar. Selecciona y copia el texto manualmente.");
        expect(toast.success).not.toHaveBeenCalled();
        expect(screen.getByText("Mensaje a copiar")).toBeInTheDocument();
    });

    it("maneja clipboard no disponible sin anunciar una copia falsa", async () => {
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"),
            messages: [sentMessage("Mensaje a copiar", "copy-1", 1)] });
        const user = userEvent.setup();
        const descriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
        Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
        try {
            render(<Inbox />);
            await selectConversation(user, "Ana");
            await user.click(screen.getByRole("button", { name: "Copiar mensaje" }));
            expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("No se pudo copiar"));
            expect(toast.success).not.toHaveBeenCalled();
        } finally {
            Object.defineProperty(navigator, "clipboard", descriptor);
        }
    });

    it.each([false, true])("copia teléfono y ofrece tel: también con hilo archivado=%s", async (archived) => {
        const phone = "+52 (55) 1234-5678";
        inboxApi.getThreads.mockResolvedValue(rows.map((row) => ({ ...row, contact_phone: phone })));
        const data = threadFor("contact-ana");
        inboxApi.getThreadMessages.mockResolvedValue({ ...data,
            conversation: archived ? null : { ...data.conversation, contact_phone: phone, claimed_by_name: "Sofía" } });
        // La lectura y la copia no requieren permiso de envío.
        authPermissions.clear();
        const user = userEvent.setup();
        const write = vi.spyOn(navigator.clipboard, "writeText");
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: /Ana/ }));
        expect(await screen.findByRole("link", { name: phone })).toHaveAttribute("href", "tel:+525512345678");
        await user.click(screen.getByRole("button", { name: "Copiar teléfono" }));
        expect(write).toHaveBeenCalledExactlyOnceWith(phone);
        expect(toast.success).toHaveBeenCalledWith("Teléfono copiado");
        if (!archived) expect(screen.getByText("Atiende: Sofía")).toBeInTheDocument();
    });

    it("renderiza enlaces seguros, preserva HTML literal y no ofrece copiar placeholders", async () => {
        const body = '<img src=x onerror=alert(1)> javascript:alert(1) https://example.org/cita?x=1&y=2';
        inboxApi.getThreadMessages.mockResolvedValue({ ...threadFor("contact-ana"), messages: [
            sentMessage(body, "copy-1", 1),
            { id: 2, body: "", direction: "in", payload_type: "image", created_at: "2026-08-23T18:46:00Z" },
        ] });
        const user = userEvent.setup();
        const { container } = render(<Inbox />);
        await selectConversation(user, "Ana");
        const link = screen.getByRole("link", { name: "https://example.org/cita?x=1&y=2" });
        expect(link).toHaveAttribute("href", "https://example.org/cita?x=1&y=2");
        expect(link).toHaveAttribute("target", "_blank");
        expect(link).toHaveAttribute("rel", "noopener noreferrer");
        expect(container).toHaveTextContent('<img src=x onerror=alert(1)> javascript:alert(1)');
        expect(container.querySelector("img, script, [onerror]")).toBeNull();
        expect(screen.getAllByRole("link")).toHaveLength(1);
        expect(screen.getAllByRole("button", { name: "Copiar mensaje" })).toHaveLength(1);
        expect(screen.queryByRole("button", { name: "Copiar teléfono" })).not.toBeInTheDocument();
    });
});

describe("WA-GRP-01 — ráfagas en el transcript", () => {
    it("agrupa por autor sin ocultar mensajes, horas ni estados de entrega", async () => {
        inboxApi.getThreadMessages.mockResolvedValue({
            ...threadFor("contact-ana"),
            messages: [
                { ...sentMessage("Primera respuesta", "key-1", 1), human_author_public_id: "staff-a", status: "sent" },
                { ...sentMessage("Segunda respuesta", "key-2", 2), human_author_public_id: "staff-a", status: "read", created_at: "2026-08-23T18:46:00Z" },
                { ...sentMessage("Otro empleado homónimo", "key-3", 3), human_author_public_id: "staff-b", created_at: "2026-08-23T18:47:00Z" },
            ],
        });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        const burst = screen.getByRole("group", { name: "2 mensajes de Recepción" });
        expect(within(burst).getByText("Primera respuesta")).toBeInTheDocument();
        expect(within(burst).getByText("Segunda respuesta")).toBeInTheDocument();
        expect(within(burst).getByLabelText("Aceptado por WhatsApp")).toBeInTheDocument();
        expect(within(burst).getByLabelText("Leído")).toBeInTheDocument();
        expect(within(burst).getByText(/11:45/)).toBeInTheDocument();
        expect(within(burst).getByText(/11:46/)).toBeInTheDocument();
        const other = screen.getByRole("group", { name: "1 mensaje de Recepción" });
        expect(within(other).getByText("Otro empleado homónimo")).toBeInTheDocument();
    });

    it("corta la ráfaga en medianoche de la clínica aunque sólo pase un minuto", async () => {
        inboxApi.getThreadMessages.mockResolvedValue({
            ...threadFor("contact-ana"),
            messages: [
                { id: 1, direction: "in", body: "Antes de medianoche", created_at: "2026-08-23T06:59:00Z" },
                { id: 2, direction: "in", body: "Después de medianoche", created_at: "2026-08-23T07:00:00Z" },
                { id: 3, direction: "in", body: "Mismo día nuevo", created_at: "2026-08-23T07:01:00Z" },
            ],
        });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        expect(within(screen.getByRole("group", { name: "1 mensaje de Ana" }))
            .getByText("Antes de medianoche")).toBeInTheDocument();
        const after = screen.getByRole("group", { name: "2 mensajes de Ana" });
        expect(within(after).getByText("Después de medianoche")).toBeInTheDocument();
        expect(within(after).getByText("Mismo día nuevo")).toBeInTheDocument();
    });
});

describe("WA-CMP-01 — altura y contador del composer", () => {
    it("crece al pegar 2000 caracteres, limita la altura y encoge al borrar", async () => {
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        // jsdom no calcula layout; la altura natural representa el contenido
        // que mediría el navegador, cuya geometría se verifica por separado.
        Object.defineProperty(composer, "scrollHeight", {
            configurable: true,
            get: () => composer.value.length > 100 ? 300 : 38,
        });

        await user.click(composer);
        await user.paste("a".repeat(2000));
        expect(composer).toHaveValue("a".repeat(2000));
        expect(composer).toHaveStyle({ height: "120px" });
        expect(screen.queryByText("2000/4000")).not.toBeInTheDocument();

        await user.clear(composer);
        expect(composer).toHaveStyle({ height: "40px" });
    });

    it("muestra el contador después de 3600 y conserva el límite de 4000", async () => {
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        await user.click(composer);
        await user.paste("a".repeat(3600));
        expect(screen.queryByText("3600/4000")).not.toBeInTheDocument();

        await user.type(composer, "b");
        expect(screen.getByText("3601/4000")).toBeInTheDocument();
        expect(composer).toHaveAccessibleDescription("3601/4000");

        await user.paste("c".repeat(500));
        expect(composer.value).toHaveLength(4000);
        expect(screen.getByText("4000/4000")).toBeInTheDocument();
        await user.clear(composer);
        expect(screen.queryByText("4000/4000")).not.toBeInTheDocument();
        expect(composer).not.toHaveAttribute("aria-describedby");
    });

    it("reinicia altura y contador al enviar sin esperar el POST", async () => {
        let resolveSend;
        inboxApi.sendInboxMessage.mockReturnValueOnce(new Promise((resolve) => { resolveSend = resolve; }));
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        Object.defineProperty(composer, "scrollHeight", {
            configurable: true,
            get: () => composer.value ? 300 : 38,
        });
        await user.click(composer);
        await user.paste("a".repeat(3800));
        expect(screen.getByText("3800/4000")).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Enviar" }));

        expect(composer).toHaveValue("");
        expect(composer).toHaveStyle({ height: "40px" });
        expect(screen.queryByText("3800/4000")).not.toBeInTheDocument();
        const [session, body, key] = inboxApi.sendInboxMessage.mock.calls[0];
        expect(session).toBe("session-ana");
        expect(body).toHaveLength(3800);
        await act(async () => resolveSend(sentMessage(body, key)));
    });

    it("descarta texto y contador al cambiar de cliente", async () => {
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        await user.click(composer);
        await user.paste("a".repeat(3800));

        const nextComposer = await selectConversation(user, "Beto");
        expect(nextComposer).toHaveValue("");
        expect(screen.queryByText("3800/4000")).not.toBeInTheDocument();
        expect(inboxApi.sendInboxMessage).not.toHaveBeenCalled();
    });
});

describe("Inbox — aislamiento del borrador", () => {
    it("descarta el texto de Ana al cambiar al hilo de Beto", async () => {
        const user = userEvent.setup();
        render(<Inbox />);

        const anaComposer = await selectConversation(user, "Ana");
        await user.type(anaComposer, "Texto destinado solamente a Ana");

        const betoComposer = await selectConversation(user, "Beto");

        expect(betoComposer).toHaveValue("");
        expect(inboxApi.sendInboxMessage).not.toHaveBeenCalled();
    });

    it("conserva el borrador al volver a clicar el mismo hilo", async () => {
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Borrador de Ana");
        await user.click(await screen.findByRole("button", { name: /Ana/ }));

        expect(composer).toHaveValue("Borrador de Ana");
        expect(inboxApi.sendInboxMessage).not.toHaveBeenCalled();
    });

    it("envía al sessionId vigente con una key de idempotencia no vacía", async () => {
        let resolveAna;
        const delayedAna = new Promise((resolve) => { resolveAna = resolve; });
        inboxApi.getThreadMessages.mockImplementation((contactId) =>
            contactId === "contact-ana"
                ? delayedAna
                : Promise.resolve(threadFor(contactId))
        );
        const user = userEvent.setup();
        render(<Inbox />);

        await user.click(await screen.findByRole("button", { name: /Ana/ }));
        await waitFor(() =>
            expect(inboxApi.getThreadMessages).toHaveBeenCalledWith("contact-ana", ACCOUNT_ID, {}, { signal: expect.any(AbortSignal) })
        );
        const betoComposer = await selectConversation(user, "Beto");

        // La respuesta vieja llega después: no debe reinstalar session-ana.
        await act(async () => { resolveAna(threadFor("contact-ana")); });
        await user.type(betoComposer, "Respuesta para Beto");
        await user.click(screen.getByRole("button", { name: "Enviar" }));

        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(1));
        const [sessionId, body, idempotencyKey] = inboxApi.sendInboxMessage.mock.calls[0];
        expect(sessionId).toBe("session-beto");
        expect(body).toBe("Respuesta para Beto");
        expect(idempotencyKey).toEqual(expect.any(String));
        expect(idempotencyKey.length).toBeGreaterThan(0);
    });

    it("no reinstala ni borra el hilo nuevo si el POST anterior termina tarde", async () => {
        let resolveAnaSend;
        inboxApi.sendInboxMessage
            .mockReturnValueOnce(new Promise((resolve) => { resolveAnaSend = resolve; }))
            .mockImplementationOnce((_sessionId, text, key) =>
                Promise.resolve(sentMessage(text, key, "message-beto"))
            );
        const user = userEvent.setup();
        render(<Inbox />);

        const anaComposer = await selectConversation(user, "Ana");
        await user.type(anaComposer, "Respuesta lenta para Ana");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(1));

        const betoComposer = await selectConversation(user, "Beto");
        await user.type(betoComposer, "Borrador que pertenece a Beto");
        const anaLoadsBeforeSendSettles = inboxApi.getThreadMessages.mock.calls
            .filter(([contactId]) => contactId === "contact-ana").length;
        const [, anaBody, anaKey] = inboxApi.sendInboxMessage.mock.calls[0];
        await act(async () => {
            resolveAnaSend(sentMessage(anaBody, anaKey, "message-ana"));
        });

        await waitFor(() => expect(screen.getByRole("button", { name: "Enviar" })).toBeEnabled());
        expect(screen.getByText("Beto", { selector: "strong" })).toBeInTheDocument();
        expect(betoComposer).toHaveValue("Borrador que pertenece a Beto");
        expect(inboxApi.getThreadMessages.mock.calls
            .filter(([contactId]) => contactId === "contact-ana")).toHaveLength(
            anaLoadsBeforeSendSettles
        );
        await user.click(screen.getByRole("button", { name: "Enviar" }));

        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(2));
        expect(inboxApi.sendInboxMessage.mock.calls[1][0]).toBe("session-beto");
        expect(inboxApi.sendInboxMessage.mock.calls[1][1]).toBe("Borrador que pertenece a Beto");
        expect(inboxApi.sendInboxMessage.mock.calls[1][2])
            .not.toBe(inboxApi.sendInboxMessage.mock.calls[0][2]);
    });

    it("reutiliza la key si se reintenta el mismo texto tras un error de red", async () => {
        inboxApi.sendInboxMessage
            .mockRejectedValueOnce(new Error("network lost"))
            .mockImplementationOnce((_sessionId, text, key) =>
                Promise.resolve(sentMessage(text, key, "message-ana"))
            );
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Un solo intento lógico");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        expect(composer).toHaveValue("");
        await user.click(await screen.findByRole("button", { name: "Reintentar" }));

        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(2));
        expect(inboxApi.sendInboxMessage.mock.calls[1][2])
            .toBe(inboxApi.sendInboxMessage.mock.calls[0][2]);

        await waitFor(() => expect(screen.queryByRole("button", { name: "Reintentar" }))
            .not.toBeInTheDocument());
        await user.type(composer, "Un solo intento lógico");
        await user.click(screen.getByRole("button", { name: "Enviar" }));

        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(3));
        expect(inboxApi.sendInboxMessage.mock.calls[2][2])
            .not.toBe(inboxApi.sendInboxMessage.mock.calls[1][2]);
    });

    it("conserva la key incierta al navegar B y volver a A con el mismo texto", async () => {
        inboxApi.sendInboxMessage
            .mockRejectedValueOnce(new Error("response lost"))
            .mockImplementationOnce((_sessionId, text, key) =>
                Promise.resolve(sentMessage(text, key, "message-ana"))
            );
        const user = userEvent.setup();
        render(<Inbox />);

        const firstComposer = await selectConversation(user, "Ana");
        await user.type(firstComposer, "Respuesta que pudo haberse enviado");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        await screen.findByRole("button", { name: "Reintentar" });
        const firstKey = inboxApi.sendInboxMessage.mock.calls[0][2];

        await selectConversation(user, "Beto");
        await selectConversation(user, "Ana");
        await user.click(await screen.findByRole("button", { name: "Reintentar" }));

        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(2));
        expect(inboxApi.sendInboxMessage.mock.calls[1][0]).toBe("session-ana");
        expect(inboxApi.sendInboxMessage.mock.calls[1][2]).toBe(firstKey);
    });

    it("un éxito antiguo A→B→A no borra un draft nuevo aunque tenga el mismo texto", async () => {
        let resolveFirstSend;
        inboxApi.sendInboxMessage
            .mockReturnValueOnce(new Promise((resolve) => { resolveFirstSend = resolve; }))
            .mockImplementationOnce((_sessionId, text, key) =>
                Promise.resolve(sentMessage(text, key, "message-ana-new"))
            );
        const user = userEvent.setup();
        render(<Inbox />);

        const firstComposer = await selectConversation(user, "Ana");
        fireEvent.change(firstComposer, { target: { value: "Texto idéntico, intención nueva" } });
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(1));
        const oldKey = inboxApi.sendInboxMessage.mock.calls[0][2];

        await selectConversation(user, "Beto");
        const returnedComposer = await selectConversation(user, "Ana");
        fireEvent.change(returnedComposer, { target: { value: "Texto idéntico, intención nueva" } });
        const [, oldBody, oldKeyFromCall] = inboxApi.sendInboxMessage.mock.calls[0];
        await act(async () => {
            resolveFirstSend(sentMessage(oldBody, oldKeyFromCall, "message-ana-old"));
        });

        await waitFor(() => expect(screen.getByRole("button", { name: "Enviar" })).toBeEnabled());
        expect(returnedComposer).toHaveValue("Texto idéntico, intención nueva");
        expect(screen.getByText("Ana", { selector: "strong" })).toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: "Enviar" }));
        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(2));
        expect(inboxApi.sendInboxMessage.mock.calls[1][0]).toBe("session-ana");
        expect(inboxApi.sendInboxMessage.mock.calls[1][1]).toBe("Texto idéntico, intención nueva");
        expect(inboxApi.sendInboxMessage.mock.calls[1][2]).not.toBe(oldKey);
    });

    it("A→B→A conserva visible el 201 aunque el GET de regreso esté vacío", async () => {
        let resolveSend;
        inboxApi.sendInboxMessage.mockReturnValueOnce(
            new Promise((resolve) => { resolveSend = resolve; })
        );
        const user = userEvent.setup();
        render(<Inbox />);

        const firstComposer = await selectConversation(user, "Ana");
        await user.type(firstComposer, "Confirmado durante navegación");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        const [, text, key] = inboxApi.sendInboxMessage.mock.calls[0];

        await selectConversation(user, "Beto");
        const returnedComposer = await selectConversation(user, "Ana");
        await user.type(returnedComposer, "Draft posterior intacto");
        expect(screen.getAllByText("Confirmado durante navegación")).toHaveLength(1);

        await act(async () => {
            resolveSend({ ...sentMessage(text, key, "message-after-navigation"), status: "sent" });
        });

        await waitFor(() => expect(screen.getByLabelText("Aceptado por WhatsApp")).toBeInTheDocument());
        expect(screen.getAllByText("Confirmado durante navegación")).toHaveLength(1);
        expect(returnedComposer).toHaveValue("Draft posterior intacto");
    });

    it("regenera la key cuando cambia el texto después de un error", async () => {
        inboxApi.sendInboxMessage
            .mockRejectedValueOnce(new Error("network lost"))
            .mockImplementationOnce((_sessionId, text, key) =>
                Promise.resolve(sentMessage(text, key, "message-ana"))
            );
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Texto original");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        await screen.findByRole("button", { name: "Reintentar" });

        await user.type(composer, "Texto original corregido");
        await user.click(screen.getByRole("button", { name: "Enviar" }));

        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(2));
        expect(inboxApi.sendInboxMessage.mock.calls[1][1]).toBe("Texto original corregido");
        expect(inboxApi.sendInboxMessage.mock.calls[1][2])
            .not.toBe(inboxApi.sendInboxMessage.mock.calls[0][2]);
    });

    it("pinta el envío antes del POST y reconcilia el 201 sin duplicar", async () => {
        let resolveSend;
        inboxApi.sendInboxMessage.mockReturnValueOnce(
            new Promise((resolve) => { resolveSend = resolve; })
        );
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Visible inmediatamente");
        await user.click(screen.getByRole("button", { name: "Enviar" }));

        expect(composer).toHaveValue("");
        expect(screen.getByText("Visible inmediatamente")).toBeInTheDocument();
        expect(screen.getByLabelText("Pendiente de envío")).toBeInTheDocument();
        const [, text, key] = inboxApi.sendInboxMessage.mock.calls[0];

        await act(async () => {
            resolveSend({ ...sentMessage(text, key, "message-confirmed"), status: "sent" });
        });

        await waitFor(() => expect(screen.getByLabelText("Aceptado por WhatsApp")).toBeInTheDocument());
        expect(screen.getAllByText("Visible inmediatamente")).toHaveLength(1);
        expect(screen.queryByText("Tú")).not.toBeInTheDocument();
    });

    it("elimina el optimista ante 400 y muestra el error del servidor", async () => {
        let rejectSend;
        inboxApi.sendInboxMessage.mockReturnValueOnce(
            new Promise((_resolve, reject) => { rejectSend = reject; })
        );
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Mensaje inválido");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        expect(screen.getByText("Mensaje inválido")).toBeInTheDocument();

        await act(async () => {
            rejectSend({ response: { status: 400, data: { error: "Sesión cerrada" } } });
        });

        await waitFor(() => expect(screen.queryByText("Mensaje inválido"))
            .not.toBeInTheDocument());
        expect(screen.queryByRole("button", { name: "Reintentar" }))
            .not.toBeInTheDocument();
        expect(toast.error).toHaveBeenCalledWith("Sesión cerrada");
    });

    it("conserva el optimista reintentable ante un 5xx", async () => {
        inboxApi.sendInboxMessage.mockRejectedValueOnce({
            response: { status: 503, data: { detail: "Proveedor no disponible" } },
        });
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Queda para reintento");
        await user.click(screen.getByRole("button", { name: "Enviar" }));

        expect(await screen.findByRole("button", { name: "Reintentar" }))
            .toBeInTheDocument();
        expect(screen.getByText("Queda para reintento")).toBeInTheDocument();
        expect(screen.getByLabelText(/No se pudo enviar: Proveedor no disponible/))
            .toBeInTheDocument();
    });

    it("deduplica un polling concurrente exclusivamente por client_message_id", async () => {
        vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
        vi.setSystemTime(new Date("2026-08-23T20:00:00Z"));
        let threadLoads = 0;
        let resolveSend;
        inboxApi.sendInboxMessage.mockReturnValueOnce(
            new Promise((resolve) => { resolveSend = resolve; })
        );
        inboxApi.getThreadMessages.mockImplementation((contactId) => {
            threadLoads += 1;
            if (threadLoads === 1) return Promise.resolve(threadFor(contactId));
            const [, text, key] = inboxApi.sendInboxMessage.mock.calls[0];
            return Promise.resolve({
                ...threadFor(contactId),
                messages: [{ ...sentMessage(text, key, "message-from-poll"), status: "delivered" }],
            });
        });
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Solo una burbuja");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        expect(screen.getAllByText("Solo una burbuja")).toHaveLength(1);

        await act(async () => {
            vi.advanceTimersByTime(10_000);
        });

        await waitFor(() => expect(screen.getByLabelText("Entregado")).toBeInTheDocument());
        expect(screen.getAllByText("Solo una burbuja")).toHaveLength(1);
        const [, text, key] = inboxApi.sendInboxMessage.mock.calls[0];
        await act(async () => {
            resolveSend({ ...sentMessage(text, key, "message-from-poll"), status: "delivered" });
        });
        expect(screen.getAllByText("Solo una burbuja")).toHaveLength(1);
    });

    it("dos envíos consecutivos por Enter reciben keys distintas", async () => {
        inboxApi.sendInboxMessage.mockImplementation(() => new Promise(() => {}));
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Mensaje repetido");
        await user.keyboard("{Enter}");
        await waitFor(() => expect(composer).toHaveValue(""));
        await user.type(composer, "Mensaje repetido");
        await user.keyboard("{Enter}");

        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(2));
        expect(inboxApi.sendInboxMessage.mock.calls[0][2])
            .not.toBe(inboxApi.sendInboxMessage.mock.calls[1][2]);
        expect(screen.getAllByText("Mensaje repetido")).toHaveLength(2);
    });

    it("no ejecuta continuaciones del POST después de desmontar el Inbox", async () => {
        let resolveSend;
        inboxApi.sendInboxMessage.mockReturnValueOnce(
            new Promise((resolve) => { resolveSend = resolve; })
        );
        const user = userEvent.setup();
        const view = render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Respuesta antes de desmontar");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        const [, text, key, options] = inboxApi.sendInboxMessage.mock.calls[0];
        const listCalls = inboxApi.getThreads.mock.calls.length;
        const threadCalls = inboxApi.getThreadMessages.mock.calls.length;

        view.unmount();
        expect(options.signal.aborted).toBe(true);
        await act(async () => {
            resolveSend(sentMessage(text, key, "message-after-unmount"));
        });

        expect(inboxApi.getThreads).toHaveBeenCalledTimes(listCalls);
        expect(inboxApi.getThreadMessages).toHaveBeenCalledTimes(threadCalls);
        expect(toast.error).not.toHaveBeenCalled();
        expect(toast.success).not.toHaveBeenCalled();
    });

    it("aplica el cap global de 20 intentos entre sesiones", async () => {
        inboxApi.sendInboxMessage.mockRejectedValue(new Error("offline"));
        const user = userEvent.setup();
        render(<Inbox />);

        let composer = await selectConversation(user, "Ana");
        let sendButton = screen.getByRole("button", { name: "Enviar" });
        for (let index = 0; index < 11; index += 1) {
            fireEvent.change(composer, { target: { value: `Intento Ana ${index}` } });
            fireEvent.click(sendButton);
            await waitFor(() => expect(inboxApi.sendInboxMessage)
                .toHaveBeenCalledTimes(index + 1));
        }

        composer = await selectConversation(user, "Beto");
        sendButton = screen.getByRole("button", { name: "Enviar" });
        for (let index = 0; index < 10; index += 1) {
            fireEvent.change(composer, { target: { value: `Intento Beto ${index}` } });
            fireEvent.click(sendButton);
            await waitFor(() => expect(inboxApi.sendInboxMessage)
                .toHaveBeenCalledTimes(12 + index));
        }

        await selectConversation(user, "Ana");
        expect(screen.queryByText("Intento Ana 0")).not.toBeInTheDocument();
        expect(screen.getByText("Intento Ana 1")).toBeInTheDocument();
        expect(screen.getAllByRole("button", { name: "Reintentar" })).toHaveLength(10);

        await selectConversation(user, "Beto");
        expect(screen.getByText("Intento Beto 0")).toBeInTheDocument();
        expect(screen.getAllByRole("button", { name: "Reintentar" })).toHaveLength(10);
    });

    it("oculta failed-local cuando el hilo regresa con otra sesión activa", async () => {
        let anaLoads = 0;
        inboxApi.getThreadMessages.mockImplementation((contactId) => {
            const data = threadFor(contactId);
            if (contactId === "contact-ana") {
                anaLoads += 1;
                if (anaLoads > 1) {
                    data.conversation = { ...data.conversation, public_id: "session-ana-new" };
                }
            }
            return Promise.resolve(data);
        });
        inboxApi.sendInboxMessage.mockRejectedValueOnce(new Error("offline"));
        const user = userEvent.setup();
        render(<Inbox />);

        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Pertenece a la sesión anterior");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        await screen.findByRole("button", { name: "Reintentar" });

        await selectConversation(user, "Beto");
        await selectConversation(user, "Ana");

        expect(screen.queryByText("Pertenece a la sesión anterior"))
            .not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Reintentar" }))
            .not.toBeInTheDocument();
    });

    it("renderiza un divisor por día local de la organización", async () => {
        vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
        vi.setSystemTime(new Date("2026-01-05T20:00:00Z"));
        inboxApi.getThreadMessages.mockResolvedValue({
            ...threadFor("contact-ana"),
            messages: [
                {
                    id: "message-2025",
                    body: "Antes de medianoche",
                    direction: "in",
                    created_at: "2026-01-01T07:30:00Z", // 31 dic, 23:30 en Tijuana
                },
                {
                    id: "message-2026",
                    body: "Después de medianoche",
                    direction: "in",
                    created_at: "2026-01-01T08:30:00Z", // 1 ene, 00:30 en Tijuana
                },
            ],
        });
        const user = userEvent.setup();
        render(<Inbox />);

        await selectConversation(user, "Ana");

        expect(await screen.findByRole("separator", { name: "31 dic 2025" }))
            .toBeInTheDocument();
        expect(screen.getByRole("separator", { name: "1 ene" }))
            .toBeInTheDocument();
        expect(screen.getAllByRole("separator")).toHaveLength(2);
    });

    it("mantiene la hora del mensaje histórico bajo el divisor Ayer", async () => {
        vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
        vi.setSystemTime(new Date("2026-08-23T20:00:00Z"));
        inboxApi.getThreadMessages.mockResolvedValue({
            ...threadFor("contact-ana"),
            messages: [
                {
                    id: "message-yesterday",
                    body: "Mensaje de ayer",
                    direction: "in",
                    created_at: "2026-08-22T18:45:00Z", // 22 ago, 11:45 en Tijuana
                },
            ],
        });
        const user = userEvent.setup();
        render(<Inbox />);

        await selectConversation(user, "Ana");

        expect(await screen.findByRole("separator", { name: "Ayer" }))
            .toBeInTheDocument();
        expect(screen.getByText(/11:45/)).toBeInTheDocument();
    });

    it("integra recibos de entrega solo en mensajes salientes del transcript", async () => {
        vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
        vi.setSystemTime(new Date("2026-08-23T20:00:00Z"));
        inboxApi.getThreadMessages.mockResolvedValue({
            ...threadFor("contact-ana"),
            messages: [
                {
                    id: "message-inbound",
                    body: "Mensaje recibido",
                    direction: "in",
                    status: "pending",
                    created_at: "2026-08-23T18:30:00Z",
                },
                {
                    id: "message-outbound",
                    body: "Respuesta entregada",
                    direction: "out",
                    author_type: "human_staff",
                    human_author_name: "Recepción",
                    status: "delivered",
                    created_at: "2026-08-23T18:31:00Z",
                },
            ],
        });
        const user = userEvent.setup();
        render(<Inbox />);

        await selectConversation(user, "Ana");

        expect(await screen.findByLabelText("Entregado")).toHaveTextContent("✓✓");
        expect(screen.queryByLabelText("Pendiente de envío")).not.toBeInTheDocument();
    });

    it("actualiza todos los divisores con una sola referencia al cruzar medianoche", async () => {
        vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
        vi.setSystemTime(new Date("2026-08-23T06:59:30Z")); // 22 ago, 23:59:30 en Tijuana
        inboxApi.getThreadMessages.mockResolvedValue({
            ...threadFor("contact-ana"),
            messages: [
                {
                    id: "message-before-midnight",
                    body: "Último mensaje del día",
                    direction: "in",
                    created_at: "2026-08-23T06:45:00Z", // 22 ago, 23:45 en Tijuana
                },
            ],
        });
        const user = userEvent.setup();
        render(<Inbox />);

        await selectConversation(user, "Ana");
        expect(await screen.findByRole("separator", { name: "Hoy" }))
            .toBeInTheDocument();

        await act(async () => {
            vi.advanceTimersByTime(60_000);
        });

        expect(await screen.findByRole("separator", { name: "Ayer" }))
            .toBeInTheDocument();
        expect(screen.queryByRole("separator", { name: "Hoy" }))
            .not.toBeInTheDocument();
    });
});

describe("WA-PERF-02 — paginación de conversaciones", () => {
    const page = (results, nextOffset = null) => ({
        results, has_more: nextOffset !== null, next_offset: nextOffset,
    });
    const third = { ...rows[1], contact_public_id: "contact-caro", owner_name: "Caro" };
    const advancePoll = async () => {
        await act(async () => { vi.advanceTimersByTime(20_000); });
    };

    it("permite alcanzar 250 conversaciones en tres páginas y anuncia las restantes", async () => {
        const all = Array.from({ length: 250 }, (_, i) => ({
            ...rows[0], contact_public_id: `contact-${i}`, owner_name: `Cliente ${i}`,
            handoff_priority: i < 5 ? "urgent" : null,
        }));
        inboxApi.getThreads.mockImplementation(({ offset = 0 }) =>
            Promise.resolve(page(all.slice(offset, offset + 100), offset < 200 ? offset + 100 : null)));
        const user = userEvent.setup();
        render(<Inbox />);
        const status = await screen.findByText("100 conversaciones cargadas. Hay más conversaciones.");
        const pagination = within(status.parentElement);
        await user.click(pagination.getByRole("button", { name: "Cargar más" }));
        await screen.findByText("200 conversaciones cargadas. Hay más conversaciones.");
        await user.click(pagination.getByRole("button", { name: "Cargar más" }));
        await screen.findByText("250 conversaciones cargadas.");
        expect(pagination.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
        const names = screen.getAllByText(/^Cliente \d+$/);
        expect(names.map((name) => name.textContent)).toEqual(all.map((r) => r.owner_name));
        expect(names.every((name) => name.closest("button"))).toBe(true);
        expect(inboxApi.getThreads.mock.calls.map(([params]) => params)).toEqual([{}, { offset: 100 }, { offset: 200 }]);
    });

    it("deduplica por contacto y cuenta sin ocultar otra cuenta del mismo contacto", async () => {
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100)).mockResolvedValueOnce(page([
            { ...rows[0], last_message_preview: "Actualizado" },
            { ...rows[0], channel_account_public_id: "other-account", owner_name: "Ana otra cuenta" },
        ]));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: "Cargar más" }));
        await screen.findByText("3 conversaciones cargadas.");
        expect(screen.getAllByRole("button", { name: /Ana/ })).toHaveLength(2);
        expect(screen.getByText("Actualizado")).toBeInTheDocument();
    });

    it("refresca todas las páginas cargadas y conserva selección y borrador", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100)).mockResolvedValueOnce(page([third]));
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Borrador intacto");
        await user.click(screen.getByRole("button", { name: "Cargar más" }));
        await screen.findByText("3 conversaciones cargadas.");
        inboxApi.getThreads.mockResolvedValueOnce(page([{ ...third, handoff_priority: "urgent" }, rows[0]], 100))
            .mockResolvedValueOnce(page([rows[1]]));
        await advancePoll();
        expect(inboxApi.getThreads.mock.calls.slice(-2).map(([params]) => params)).toEqual([{}, { offset: 100 }]);
        expect(screen.getAllByRole("button", { name: /Hola de/ }).map((b) =>
            b.querySelector('[class*="convName"]').textContent)).toEqual(["Caro", "Ana", "Beto"]);
        expect(composer).toHaveValue("Borrador intacto");
        expect(screen.getByText("Ana", { selector: "strong" })).toBeInTheDocument();
    });

    it("bloquea el doble clic y el poll mientras carga otra página", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        let finish;
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100))
            .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.dblClick(await screen.findByRole("button", { name: "Cargar más" }));
        expect(screen.getByRole("button", { name: "Cargando más…" })).toBeDisabled();
        await advancePoll();
        expect(inboxApi.getThreads).toHaveBeenCalledTimes(2);
        await act(async () => { finish(page([third])); });
        expect(screen.getByText("3 conversaciones cargadas.")).toBeInTheDocument();
    });

    it("una respuesta de poll anterior no borra una página recién añadida", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        let finishPoll;
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100))
            .mockImplementationOnce(() => new Promise((resolve) => { finishPoll = resolve; }))
            .mockResolvedValueOnce(page([third]));
        const user = userEvent.setup();
        render(<Inbox />);
        await screen.findByRole("button", { name: "Cargar más" });
        await advancePoll();
        await user.click(screen.getByRole("button", { name: "Cargar más" }));
        await screen.findByText("3 conversaciones cargadas.");
        await act(async () => { finishPoll(page([rows[0]])); });
        expect(screen.getByText("3 conversaciones cargadas.")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Caro/ })).toBeInTheDocument();
    });

    it("conserva las filas ante un error de carga y reintenta el mismo desplazamiento", async () => {
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100))
            .mockRejectedValueOnce({ response: { data: { error: "Sin conexión para cargar más" } } })
            .mockResolvedValueOnce(page([third]));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: "Cargar más" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("Sin conexión para cargar más");
        expect(screen.getByText("2 conversaciones cargadas. Hay más conversaciones.")).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Reintentar cargar más" }));
        await screen.findByText("3 conversaciones cargadas.");
        expect(inboxApi.getThreads.mock.calls.slice(-2).map(([params]) => params)).toEqual([{ offset: 100 }, { offset: 100 }]);
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("un refresco parcial fallido retiene todas las filas y muestra reconexión tras dos fallos", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100)).mockResolvedValueOnce(page([third]));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: "Cargar más" }));
        await screen.findByText("3 conversaciones cargadas.");
        inboxApi.getThreads.mockImplementation(({ offset }) => offset
            ? Promise.reject(new Error("offline")) : Promise.resolve(page([rows[0]], 100)));
        await advancePoll();
        expect(screen.getByRole("button", { name: /^Beto/ })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Caro/ })).toBeInTheDocument();
        await advancePoll();
        expect(screen.getByRole("button", { name: /Reintentar/ })).toBeInTheDocument();
        expect(screen.getByText("3 conversaciones cargadas.")).toBeInTheDocument();
        inboxApi.getThreads.mockImplementation(({ offset }) =>
            Promise.resolve(offset ? page([third]) : page(rows, 100)));
        await advancePoll();
        expect(screen.queryByRole("button", { name: /Reintentar/ })).not.toBeInTheDocument();
    });

    it.each(["éxito", "error"])("ignora una carga tardía con %s después de cambiar de filtro", async (outcome) => {
        let finish, fail;
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100))
            .mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }))
            .mockResolvedValueOnce(page([third], 100)).mockResolvedValueOnce(page([rows[1]]));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: "Cargar más" }));
        await user.click(screen.getByRole("button", { name: "Archivadas" }));
        await screen.findByRole("button", { name: /Caro/ });
        await act(async () => { if (outcome === "éxito") finish(page(rows)); else fail(new Error("old")); });
        expect(screen.queryByRole("button", { name: /Ana/ })).not.toBeInTheDocument();
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Cargar más" }));
        await screen.findByText("2 conversaciones cargadas.");
        expect(inboxApi.getThreads.mock.calls.slice(-2).map(([params]) => params))
            .toEqual([{ archived: 1 }, { archived: 1, offset: 100 }]);
    });

    it("no inicia otra página del poll al ocultarse y refresca todas al volver", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        const descriptor = Object.getOwnPropertyDescriptor(document, "hidden");
        let finish;
        try {
            Object.defineProperty(document, "hidden", { configurable: true, value: false });
            inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100)).mockResolvedValueOnce(page([third]))
                .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
            const user = userEvent.setup();
            render(<Inbox />);
            await user.click(await screen.findByRole("button", { name: "Cargar más" }));
            await screen.findByText("3 conversaciones cargadas.");
            await advancePoll();
            Object.defineProperty(document, "hidden", { configurable: true, value: true });
            fireEvent(document, new Event("visibilitychange"));
            await act(async () => { finish(page(rows, 100)); });
            expect(inboxApi.getThreads).toHaveBeenCalledTimes(3);
            expect(screen.getByText("3 conversaciones cargadas.")).toBeInTheDocument();
            inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100)).mockResolvedValueOnce(page([third]));
            Object.defineProperty(document, "hidden", { configurable: true, value: false });
            await act(async () => { fireEvent(document, new Event("visibilitychange")); });
            expect(inboxApi.getThreads).toHaveBeenCalledTimes(5);
        } finally {
            if (descriptor) Object.defineProperty(document, "hidden", descriptor);
            else delete document.hidden;
        }
    });

    it("no continúa un refresco de varias páginas después de desmontar", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        let finish;
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100)).mockResolvedValueOnce(page([third]))
            .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
        const user = userEvent.setup();
        const view = render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: "Cargar más" }));
        await screen.findByText("3 conversaciones cargadas.");
        await advancePoll();
        view.unmount();
        await act(async () => { finish(page(rows, 100)); });
        expect(inboxApi.getThreads).toHaveBeenCalledTimes(3);
    });

    it("reduce las páginas a refrescar cuando la lista se agota antes", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        inboxApi.getThreads.mockResolvedValueOnce(page(rows, 100)).mockResolvedValueOnce(page([third]));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: "Cargar más" }));
        await screen.findByText("3 conversaciones cargadas.");
        inboxApi.getThreads.mockResolvedValue(page([rows[0]]));
        await advancePoll();
        expect(screen.getByText("1 conversación cargada.")).toBeInTheDocument();
        await advancePoll();
        expect(inboxApi.getThreads.mock.calls.slice(-2).map(([params]) => params)).toEqual([{}, {}]);
    });

    it.each([0, -1, "100", null])("no ofrece un cursor inválido %s", async (offset) => {
        inboxApi.getThreads.mockResolvedValue({ results: rows, has_more: true, next_offset: offset });
        render(<Inbox />);
        await screen.findByText("2 conversaciones cargadas.");
        expect(screen.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
    });
});

describe("WA-HIST-01 — historial en Inbox", () => {
    const message = (id) => ({ id, body: `Histórico ${id}`, direction: "in",
        created_at: "2026-10-21T12:00:00Z" });
    const range = (start, end) => Array.from({ length: end - start + 1 }, (_, i) => message(start + i));
    const page = (messages, next_before = null, extra = {}) => ({
        ...threadFor("contact-ana"), messages, next_before, ...extra,
    });

    it("carga al subir, deduplica 51 mensajes y conserva la posición sin saltar al fondo", async () => {
        inboxApi.getThreadMessages.mockResolvedValueOnce(page(range(2, 51), 2))
            .mockResolvedValueOnce(page([message(1), message(2)]));
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        const region = screen.getByRole("region", { name: "Mensajes de la conversación" });
        Object.defineProperties(region, {
            scrollTop: { configurable: true, writable: true, value: 159 },
            clientHeight: { configurable: true, value: 400 },
            scrollHeight: { configurable: true, get: () => 100 + within(region).queryAllByText(/^Histórico \d+$/).length * 40 },
        });
        const scrollIntoView = HTMLElement.prototype.scrollIntoView;
        scrollIntoView.mockClear();
        fireEvent.scroll(region);
        await screen.findByText("Histórico 1", { exact: true });
        expect(inboxApi.getThreadMessages.mock.calls[1].slice(0, 3)).toEqual(["contact-ana", ACCOUNT_ID, { before: 2 }]);
        expect(within(region).getAllByText(/^Histórico \d+$/)).toHaveLength(51);
        expect(region.scrollTop).toBe(199);
        expect(scrollIntoView).not.toHaveBeenCalled();
        expect(screen.getByText("Inicio del historial disponible")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Cargar anteriores" })).not.toBeInTheDocument();
    });

    it("el poll conserva páginas anteriores y actualiza mensajes y metadatos sin adelantar el cursor", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        inboxApi.getThreadMessages.mockResolvedValueOnce(page(range(51, 100), 51))
            .mockResolvedValueOnce(page(range(1, 50), 1))
            .mockResolvedValueOnce(page(range(61, 110), 61, { contact_verification: "staff_verified" }))
            .mockResolvedValueOnce(page([]));
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        await user.click(screen.getByRole("button", { name: "Cargar anteriores" }));
        await screen.findByText("Histórico 1", { exact: true });
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(screen.getByText("Histórico 1", { exact: true })).toBeInTheDocument();
        expect(screen.getByText("Histórico 110", { exact: true })).toBeInTheDocument();
        expect(screen.getByText("Verificado")).toBeInTheDocument();
        expect(within(screen.getByRole("region", { name: "Mensajes de la conversación" })).getAllByText(/^Histórico \d+$/)).toHaveLength(110);
        await user.click(screen.getByRole("button", { name: "Cargar anteriores" }));
        expect(inboxApi.getThreadMessages.mock.calls[3][2]).toEqual({ before: 1 });
        await screen.findByText("Inicio del historial disponible");
    });

    it("un 400 muestra error persistente y reintenta el cursor manteniendo lista, historial y borrador", async () => {
        inboxApi.getThreadMessages.mockResolvedValueOnce(page([message(2)], 2))
            .mockRejectedValueOnce({ response: { status: 400, data: { error: "Cursor inválido." } } })
            .mockResolvedValueOnce(page([message(1)]));
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        await user.type(composer, "Borrador conservado");
        await user.click(screen.getByRole("button", { name: "Cargar anteriores" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("Cursor inválido.");
        expect(screen.getByText("Histórico 2")).toBeInTheDocument();
        expect(composer).toHaveValue("Borrador conservado");
        await user.click(screen.getByRole("button", { name: "Reintentar anteriores" }));
        await screen.findByText("Histórico 1");
        expect(inboxApi.getThreadMessages.mock.calls[2][2]).toEqual({ before: 2 });
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("la página anterior no sustituye la sesión vigente renovada por el poll", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        let finish;
        inboxApi.getThreadMessages.mockResolvedValueOnce(page([message(10)], 10))
            .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
            .mockResolvedValueOnce(page([message(11)], 11, {
                conversation: { ...threadFor("contact-ana").conversation, public_id: "session-ana-new", state: "active" },
            }));
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        await user.click(screen.getByRole("button", { name: "Cargar anteriores" }));
        expect(screen.getByRole("status", { name: "Cargando mensajes anteriores" })).toBeInTheDocument();
        await act(async () => vi.advanceTimersByTime(10_000));
        await act(async () => finish(page([message(9)], 9)));
        fireEvent.change(composer, { target: { value: "Usar sesión actual" } });
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        expect(inboxApi.sendInboxMessage.mock.calls[0][0]).toBe("session-ana-new");
        expect(screen.getByText("Histórico 9")).toBeInTheDocument();
        expect(screen.getByText("Histórico 11")).toBeInTheDocument();
    });

    it.each(["success", "failure"])("ignora %s antiguo al cambiar de hilo y aborta su petición", async (outcome) => {
        let finish, fail;
        inboxApi.getThreadMessages.mockResolvedValueOnce(page([message(10)], 10))
            .mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }))
            .mockResolvedValueOnce({ ...threadFor("contact-beto"), messages: [message(20)], next_before: null });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        await user.click(screen.getByRole("button", { name: "Cargar anteriores" }));
        const signal = inboxApi.getThreadMessages.mock.calls[1][3].signal;
        await selectConversation(user, "Beto");
        expect(signal.aborted).toBe(true);
        await act(async () => {
            if (outcome === "success") finish(page([message(1)]));
            else fail(new Error("Antiguo"));
        });
        expect(screen.getByText("Histórico 20")).toBeInTheDocument();
        expect(screen.queryByText("Histórico 1")).not.toBeInTheDocument();
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        expect(screen.getByText("Inicio del historial disponible")).toBeInTheDocument();
    });

    it("los hilos archivados permiten cargar anteriores sin ofrecer envío", async () => {
        inboxApi.getThreadMessages.mockResolvedValueOnce(page([message(2)], 2, { conversation: null }))
            .mockResolvedValueOnce(page([message(1)], null, { conversation: null }));
        const user = userEvent.setup();
        render(<Inbox />);
        await user.click(await screen.findByRole("button", { name: /Ana/ }));
        await screen.findByText("Ana", { selector: "strong" });
        await user.click(screen.getByRole("button", { name: "Cargar anteriores" }));
        await screen.findByText("Histórico 1");
        expect(screen.queryByRole("textbox", { name: "Respuesta al cliente" })).not.toBeInTheDocument();
    });
});

describe("WA-HIST-02 — llegadas en Inbox", () => {
    const message = (id) => ({ id, body: `Llegada ${id}`, direction: "in",
        created_at: "2026-10-21T12:00:00Z" });
    const range = (start, end) => Array.from({ length: end - start + 1 }, (_, i) => message(start + i));
    const page = (messages) => ({ ...threadFor("contact-ana"), messages, next_before: null });
    function setPosition(top) {
        const area = screen.getByRole("region", { name: "Mensajes de la conversación" });
        Object.defineProperties(area, {
            scrollHeight: { configurable: true, get: () => 100 + area.querySelectorAll("[data-message-id]").length * 40 },
            clientHeight: { configurable: true, value: 400 },
            scrollTop: { configurable: true, writable: true, value: top },
        });
        return area;
    }
    beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }));

    it("una ráfaga muestra cinco nuevos sin mover la lectura y click vuelve al fondo", async () => {
        inboxApi.getThreadMessages.mockResolvedValueOnce(page(range(1, 50))).mockResolvedValue(page(range(6, 55)));
        const user = userEvent.setup();
        render(<Inbox />);
        const composer = await selectConversation(user, "Ana");
        fireEvent.change(composer, { target: { value: "Borrador intacto" } });
        const area = setPosition(100);
        area.scrollTo = vi.fn(({ top }) => { area.scrollTop = top; });
        fireEvent.scroll(area);
        await act(async () => vi.advanceTimersByTime(10_000));
        const pill = screen.getByRole("button", { name: "5 mensajes nuevos" });
        expect(pill).toBeVisible();
        expect(area.scrollTop).toBe(100);
        expect(area.querySelectorAll("[data-message-id]")).toHaveLength(55);
        expect(composer).toHaveValue("Borrador intacto");
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(screen.getByRole("button", { name: "5 mensajes nuevos" })).toBeInTheDocument();
        await user.click(pill);
        expect(area.scrollTo).toHaveBeenCalledWith({ top: area.scrollHeight, behavior: "smooth" });
        expect(area).toHaveFocus();
        expect(screen.queryByRole("button", { name: /mensajes nuevos/ })).not.toBeInTheDocument();
    });

    it("un mensaje nuevo pegado al fondo sigue visible sin contador", async () => {
        inboxApi.getThreadMessages.mockResolvedValueOnce(page(range(1, 50))).mockResolvedValueOnce(page(range(2, 51)));
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        const area = setPosition(1700); // scrollHeight 2100 - clientHeight 400.
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(area.scrollTop).toBe(area.scrollHeight);
        expect(screen.queryByRole("button", { name: /mensaje.*nuevo/ })).not.toBeInTheDocument();
        expect(screen.getByText("Llegada 51")).toBeInTheDocument();
    });

    it("bajar manualmente hasta el fondo retira el contador", async () => {
        inboxApi.getThreadMessages.mockResolvedValueOnce(page(range(1, 50))).mockResolvedValueOnce(page(range(2, 51)));
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        const area = setPosition(100);
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(screen.getByRole("button", { name: "1 mensaje nuevo" })).toBeInTheDocument();
        area.scrollTop = area.scrollHeight - area.clientHeight;
        fireEvent.scroll(area);
        expect(screen.queryByRole("button", { name: "1 mensaje nuevo" })).not.toBeInTheDocument();
    });

    it("cambiar de hilo no conserva el contador del anterior", async () => {
        let anaLoads = 0;
        inboxApi.getThreadMessages.mockImplementation((contact) => {
            if (contact !== "contact-ana") return Promise.resolve({ ...threadFor(contact), messages: [message(200)] });
            anaLoads += 1;
            return Promise.resolve(page(anaLoads === 1 ? range(1, 50) : range(2, 51)));
        });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        setPosition(100);
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(screen.getByRole("button", { name: "1 mensaje nuevo" })).toBeInTheDocument();
        await selectConversation(user, "Beto");
        expect(screen.queryByRole("button", { name: /mensaje.*nuevo/ })).not.toBeInTheDocument();
        expect(screen.getByText("Llegada 200")).toBeInTheDocument();
    });

    it("al volver de pestaña oculta conserva la lectura y cuenta sólo llegadas posteriores", async () => {
        const descriptor = Object.getOwnPropertyDescriptor(document, "hidden");
        try {
            Object.defineProperty(document, "hidden", { configurable: true, value: false });
            inboxApi.getThreadMessages.mockResolvedValueOnce(page(range(1, 50))).mockResolvedValueOnce(page(range(6, 55)));
            const user = userEvent.setup();
            render(<Inbox />);
            await selectConversation(user, "Ana");
            const area = setPosition(100);
            Object.defineProperty(document, "hidden", { configurable: true, value: true });
            fireEvent(document, new Event("visibilitychange"));
            await act(async () => vi.advanceTimersByTime(20_000));
            expect(inboxApi.getThreadMessages).toHaveBeenCalledTimes(1);
            Object.defineProperty(document, "hidden", { configurable: true, value: false });
            await act(async () => fireEvent(document, new Event("visibilitychange")));
            expect(screen.getByRole("button", { name: "5 mensajes nuevos" })).toBeInTheDocument();
            expect(area.scrollTop).toBe(100);
        } finally {
            if (descriptor) Object.defineProperty(document, "hidden", descriptor);
            else delete document.hidden;
        }
    });
});

describe("WA-HIST-02 — historial de tres meses", () => {
    it("una llegada de hoy conserva la lectura de julio aunque cree un divisor de día", async () => {
        vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
        const old = Array.from({ length: 50 }, (_, i) => ({
            id: i + 1, body: `Julio ${i + 1}`, direction: "in", created_at: "2026-07-21T12:00:00Z",
        }));
        inboxApi.getThreadMessages.mockResolvedValueOnce({ ...threadFor("contact-ana"), messages: old, next_before: null })
            .mockResolvedValueOnce({ ...threadFor("contact-ana"), next_before: null,
                messages: [...old.slice(1), { id: 51, body: "Llegó en octubre", direction: "in", created_at: "2026-10-21T12:00:00Z" }] });
        const user = userEvent.setup();
        render(<Inbox />);
        await selectConversation(user, "Ana");
        const area = screen.getByRole("region", { name: "Mensajes de la conversación" });
        Object.defineProperties(area, {
            scrollHeight: { configurable: true, get: () => area.querySelectorAll("[data-message-id]").length * 40 + 100 },
            clientHeight: { configurable: true, value: 400 },
            scrollTop: { configurable: true, writable: true, value: 200 },
        });
        await act(async () => vi.advanceTimersByTime(10_000));
        expect(area.scrollTop).toBe(200);
        expect(screen.getByRole("button", { name: "1 mensaje nuevo" })).toBeVisible();
        expect(screen.getAllByRole("separator")).toHaveLength(2);
        expect(screen.getByText("Julio 1")).toBeInTheDocument();
        expect(screen.getByText("Llegó en octubre")).toBeInTheDocument();
    });
});
