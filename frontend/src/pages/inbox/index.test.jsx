import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const inboxApi = vi.hoisted(() => ({
    authorizeIdentityLink: vi.fn(),
    claimConversation: vi.fn(),
    closeConversation: vi.fn(),
    getAgentSettings: vi.fn(),
    getInboxMetrics: vi.fn(),
    getThreadMessages: vi.fn(),
    getThreads: vi.fn(),
    getWhatsappToken: vi.fn(),
    releaseConversation: vi.fn(),
    resetContactIdentity: vi.fn(),
    sendInboxMessage: vi.fn(),
    setWhatsappToken: vi.fn(),
    unlinkFamily: vi.fn(),
    updateAgentSettings: vi.fn(),
    verifyContactIdentity: vi.fn(),
}));

vi.mock("../../api/inbox", () => inboxApi);
vi.mock("../../auth/authContext", () => ({
    useAuth: () => ({
        can: (permission) => permission === "agentinbox.send",
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

import Inbox from "./index";
import { toast } from "sonner";

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
    return screen.findByPlaceholderText("Escribe una respuesta…");
};

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
            expect(inboxApi.getThreadMessages).toHaveBeenCalledWith("contact-ana", ACCOUNT_ID)
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
        await user.type(firstComposer, "Texto idéntico, intención nueva");
        await user.click(screen.getByRole("button", { name: "Enviar" }));
        await waitFor(() => expect(inboxApi.sendInboxMessage).toHaveBeenCalledTimes(1));
        const oldKey = inboxApi.sendInboxMessage.mock.calls[0][2];

        await selectConversation(user, "Beto");
        const returnedComposer = await selectConversation(user, "Ana");
        await user.type(returnedComposer, "Texto idéntico, intención nueva");
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

        await waitFor(() => expect(screen.getByLabelText("Enviado")).toBeInTheDocument());
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

        await waitFor(() => expect(screen.getByLabelText("Enviado")).toBeInTheDocument());
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
        for (let index = 0; index < 11; index += 1) {
            fireEvent.change(composer, { target: { value: `Intento Ana ${index}` } });
            fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
            await waitFor(() => expect(inboxApi.sendInboxMessage)
                .toHaveBeenCalledTimes(index + 1));
        }

        composer = await selectConversation(user, "Beto");
        for (let index = 0; index < 10; index += 1) {
            fireEvent.change(composer, { target: { value: `Intento Beto ${index}` } });
            fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
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
