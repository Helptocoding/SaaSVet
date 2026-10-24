import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useThreadHistory from "./useThreadHistory";

const getThreadMessages = vi.hoisted(() => vi.fn());
vi.mock("../../api/inbox", () => ({ getThreadMessages }));
const target = { contact: "contact-a", account: "account-a" };
const message = (id, extra = {}) => ({ id, body: `Mensaje ${id}`,
    created_at: "2026-10-21T12:00:00Z", ...extra });
const messages = (start, end) => Array.from({ length: end - start + 1 }, (_, i) => message(start + i));
const page = (rows, cursor = null) => ({ messages: rows, next_before: cursor });
beforeEach(() => { getThreadMessages.mockReset(); });
afterEach(() => { vi.restoreAllMocks(); });

function setup({ sessionId = null, geometry = false } = {}) {
    const area = { scrollTop: 100, clientHeight: 400 };
    const viewport = { current: area };
    let renderedRows = [];
    const hook = renderHook(({ local }) => {
        const history = useThreadHistory(viewport, { sessionId, optimisticMessages: local });
        renderedRows = history.transcriptMessages;
        return history;
    }, { initialProps: { local: [] } });
    Object.defineProperty(area, "scrollHeight", { get: () => 100 + renderedRows.length * 20 });
    if (geometry) {
        area.getBoundingClientRect = () => ({ top: 0, bottom: 400 });
        area.querySelectorAll = () => renderedRows.map((row, index) => ({
            getAttribute: () => String(row.id),
            getBoundingClientRect: () => ({
                top: 100 + index * 20 - area.scrollTop,
                bottom: 120 + index * 20 - area.scrollTop, height: 20,
            }),
        }));
    }
    return { ...hook, area };
}

describe("WA-HIST-01 — estado acumulativo del historial", () => {
    it.each([10, 51, 500])("recorre %i mensajes con páginas de 50 y cursores correctos", async (count) => {
        const history = messages(1, count);
        getThreadMessages.mockImplementation((_contact, _account, { before }) => {
            const older = history.filter((row) => row.id < before).slice(-50);
            return Promise.resolve(page(older, older.length === 50 ? older[0].id : null));
        });
        const { result } = setup();
        const initial = history.slice(-50);
        act(() => result.current.receiveLatest(initial, initial.length === 50 ? initial[0].id : null));
        while (result.current.nextBefore !== null && result.current.messages.length < count) {
            await act(async () => { await result.current.loadOlder(target); });
        }
        expect(result.current.messages.map((row) => row.id)).toEqual(history.map((row) => row.id));
        for (const [contact, account, params, options] of getThreadMessages.mock.calls) {
            expect([contact, account]).toEqual(["contact-a", "account-a"]);
            expect(params.before).toBeGreaterThan(0);
            expect(options.signal).toBeInstanceOf(AbortSignal);
        }
        const calls = getThreadMessages.mock.calls.length;
        await act(async () => { await result.current.loadOlder(target); });
        expect(getThreadMessages).toHaveBeenCalledTimes(calls);
        if (count === 500) {
            await act(async () => { await result.current.loadOlder(target, { manual: true }); });
            expect(result.current.nextBefore).toBeNull();
        }
    });

    it("ordena empates por ID numérico y no deduplica mensajes por texto", () => {
        const { result } = setup();
        act(() => result.current.receiveLatest([message(10, { body: "Igual" }), message(2, { body: "Igual" })], 2));
        act(() => result.current.receiveLatest([message(10, { status: "read" })], 10));
        expect(result.current.messages.map((row) => row.id)).toEqual([2, 10]);
        expect(result.current.messages[1].status).toBe("read");
        expect(result.current.nextBefore).toBe(2);
    });

    it("fusiona páginas solapadas sin sustituir estados más recientes del poll", async () => {
        const { result } = setup();
        act(() => result.current.receiveLatest([message(3, { status: "read" }), message(4)], 3));
        getThreadMessages.mockResolvedValue(page([message(2), message(3, { status: "sent" })], 2));
        await act(async () => { await result.current.loadOlder(target); });
        act(() => result.current.receiveLatest([message(4, { status: "delivered" }), message(5)], 4));
        expect(result.current.messages.map((row) => row.id)).toEqual([2, 3, 4, 5]);
        expect(result.current.messages.find((row) => row.id === 3).status).toBe("read");
        expect(result.current.nextBefore).toBe(2);
    });

    it("ancla la posición que la persona tiene al terminar la petición", async () => {
        let finish;
        getThreadMessages.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
        const { result, area } = setup();
        act(() => result.current.receiveLatest(messages(51, 100), 51));
        let pending;
        act(() => { pending = result.current.loadOlder(target); });
        area.scrollTop = 230;
        await act(async () => { finish(page(messages(1, 50))); await pending; });
        expect(area.scrollTop).toBe(230 + 50 * 20);
    });

    it("ignora dos disparos mientras existe una carga y permite seguir con el siguiente cursor", async () => {
        let finish;
        getThreadMessages.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
            .mockResolvedValueOnce(page([message(1)]));
        const { result } = setup();
        act(() => result.current.receiveLatest([message(3)], 3));
        let pending;
        act(() => { pending = result.current.loadOlder(target); });
        await act(async () => { await result.current.loadOlder(target); });
        expect(getThreadMessages).toHaveBeenCalledTimes(1);
        await act(async () => { finish(page([message(2)], 2)); await pending; });
        await act(async () => { await result.current.loadOlder(target); });
        expect(getThreadMessages.mock.calls[1][2]).toEqual({ before: 2 });
    });

    it("un cursor rechazado conserva mensajes, posición y cursor y exige reintento explícito", async () => {
        getThreadMessages.mockRejectedValueOnce({ response: { status: 400, data: { error: "Cursor inválido." } } })
            .mockResolvedValueOnce(page([message(1)]));
        const { result, area } = setup();
        act(() => result.current.receiveLatest([message(2)], 2));
        area.scrollTop = 100;
        await act(async () => { await result.current.loadOlder(target); });
        expect(result.current.messages.map((row) => row.id)).toEqual([2]);
        expect(result.current.nextBefore).toBe(2);
        expect(area.scrollTop).toBe(100);
        expect(result.current.olderLoad.error).toBe("Cursor inválido.");
        await act(async () => { await result.current.loadOlder(target); });
        expect(getThreadMessages).toHaveBeenCalledTimes(1);
        await act(async () => { await result.current.loadOlder(target, { manual: true }); });
        expect(getThreadMessages.mock.calls[1][2]).toEqual({ before: 2 });
        expect(result.current.olderLoad.error).toBe("");
    });

    it.each([{ incoming: [] }, { incoming: [message(2)] }])("detiene un cursor sin progreso con página $incoming", async ({ incoming }) => {
        getThreadMessages.mockResolvedValue(page(incoming, 2));
        const { result } = setup();
        act(() => result.current.receiveLatest([message(2)], 2));
        await act(async () => { await result.current.loadOlder(target); });
        expect(result.current.nextBefore).toBeNull();
        await act(async () => { await result.current.loadOlder(target); });
        expect(getThreadMessages).toHaveBeenCalledTimes(1);
    });

    it("a 500 mensajes cambia a carga manual sin descartar mensajes", async () => {
        const { result } = setup();
        act(() => result.current.receiveLatest(messages(51, 550), 51));
        getThreadMessages.mockResolvedValue(page(messages(1, 50), 1));
        await act(async () => { await result.current.loadOlder(target); });
        expect(getThreadMessages).not.toHaveBeenCalled();
        await act(async () => { await result.current.loadOlder(target, { manual: true }); });
        expect(result.current.messages).toHaveLength(550);
        expect(result.current.nextBefore).toBe(1);
    });

    it.each(["success", "failure"])("reset aborta y descarta %s antiguo, incluso A→B→A", async (outcome) => {
        let finish, fail;
        getThreadMessages.mockImplementation(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }));
        const { result } = setup();
        act(() => result.current.receiveLatest([message(5)], 5));
        let pending;
        act(() => { pending = result.current.loadOlder(target); });
        const signal = getThreadMessages.mock.calls[0][3].signal;
        act(() => {
            result.current.resetHistory();
            result.current.receiveLatest([message(20)], 20);
            result.current.resetHistory();
            result.current.receiveLatest([message(6)], 6);
        });
        expect(signal.aborted).toBe(true);
        await act(async () => {
            if (outcome === "success") finish(page([message(1)], 1));
            else fail(new Error("Respuesta antigua"));
            await pending;
        });
        expect(result.current.messages.map((row) => row.id)).toEqual([6]);
        expect(result.current.nextBefore).toBe(6);
        expect(result.current.olderLoad).toEqual({ loading: false, error: "" });
    });

    it("desmontar aborta la petición y no aplica su resultado", async () => {
        let finish;
        getThreadMessages.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
        const { result, unmount, area } = setup();
        act(() => result.current.receiveLatest([message(2)], 2));
        area.scrollTop = 100;
        let pending;
        act(() => { pending = result.current.loadOlder(target); });
        const signal = getThreadMessages.mock.calls[0][3].signal;
        unmount();
        expect(signal.aborted).toBe(true);
        await act(async () => { finish(page([message(1)])); await pending; });
        expect(area.scrollTop).toBe(100);
    });

    it("no inicia carga automática con la pestaña oculta", async () => {
        const descriptor = Object.getOwnPropertyDescriptor(document, "hidden");
        const { result } = setup();
        act(() => result.current.receiveLatest([message(2)], 2));
        try {
            Object.defineProperty(document, "hidden", { configurable: true, value: true });
            await act(async () => { await result.current.loadOlder(target); });
            expect(getThreadMessages).not.toHaveBeenCalled();
        } finally {
            if (descriptor) Object.defineProperty(document, "hidden", descriptor);
            else delete document.hidden;
        }
    });
});

describe("WA-HIST-02 — lectura y llegadas nuevas", () => {
    function reading(options) {
        const hook = setup(options);
        act(() => hook.result.current.receiveLatest(messages(51, 100), 51));
        hook.area.scrollTop = 100;
        return hook;
    }

    it("conserva scrollTop al recibir cinco mensajes arriba y no vuelve a contarlos", () => {
        const { result, area } = reading();
        act(() => result.current.receiveLatest(messages(96, 105), 96));
        expect(area.scrollTop).toBe(100);
        expect(result.current.newBelow).toBe(5);
        act(() => result.current.receiveLatest(messages(96, 105), 96));
        expect(result.current.newBelow).toBe(5);
        act(() => result.current.receiveLatest([message(105, { status: "read" }), message(106)], 105));
        expect(result.current.newBelow).toBe(6);
        expect(area.scrollTop).toBe(100);
    });

    it.each([0, 80, 81])("a %i px del fondo respeta el límite inclusivo de 80", (distance) => {
        const { result, area } = reading();
        area.scrollTop = area.scrollHeight - area.clientHeight - distance;
        const before = area.scrollTop;
        act(() => result.current.receiveLatest([message(101)], 101));
        expect(area.scrollTop).toBe(distance <= 80 ? area.scrollHeight : before);
        expect(result.current.newBelow).toBe(distance <= 80 ? 0 : 1);
    });

    it("inicializa al fondo sin contar los mensajes ya cargados", () => {
        const { result, area } = setup();
        act(() => result.current.receiveLatest(messages(1, 50), 1));
        expect(area.scrollTop).toBe(area.scrollHeight);
        expect(result.current.newBelow).toBe(0);
    });

    it("actualizar recibos o recibir IDs anteriores no incrementa el contador", () => {
        const { result, area } = reading({ geometry: true });
        act(() => result.current.receiveLatest([message(95, { status: "read" }), message(45)], 45));
        expect(result.current.newBelow).toBe(0);
        expect(area.scrollTop).toBe(120); // Un mensaje anterior conserva el ancla visible.
    });

    it("el scrollback no suma nuevos ni borra el contador pendiente", async () => {
        const { result, area } = reading();
        act(() => result.current.receiveLatest(messages(101, 105), 101));
        getThreadMessages.mockResolvedValue(page(messages(1, 50), 1));
        await act(async () => { await result.current.loadOlder(target, { manual: true }); });
        expect(area.scrollTop).toBe(1100);
        expect(result.current.newBelow).toBe(5);
        expect(result.current.messages).toHaveLength(105);
    });

    it("poll y página anterior en el mismo render preservan el ancla sin sumar la altura de llegadas al fondo", async () => {
        let finish;
        const { result, area } = reading({ geometry: true });
        getThreadMessages.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
        let pending;
        act(() => { pending = result.current.loadOlder(target, { manual: true }); });
        await act(async () => {
            result.current.receiveLatest(messages(101, 105), 101);
            finish(page(messages(1, 50), 1));
            await pending;
        });
        expect(area.scrollTop).toBe(1100);
        expect(result.current.newBelow).toBe(5);
        expect(result.current.messages).toHaveLength(105);
    });

    it("click vuelve al fondo con scroll suave, conserva foco y limpia el contador", () => {
        const { result, area } = reading();
        area.scrollTo = vi.fn(({ top }) => { area.scrollTop = top; });
        area.focus = vi.fn();
        act(() => result.current.receiveLatest(messages(101, 105), 101));
        act(() => result.current.goToEnd());
        expect(area.scrollTo).toHaveBeenCalledWith({ top: area.scrollHeight, behavior: "smooth" });
        expect(area.focus).toHaveBeenCalledWith({ preventScroll: true });
        expect(result.current.newBelow).toBe(0);
        act(() => result.current.receiveLatest([message(106)], 106));
        expect(result.current.newBelow).toBe(0);
        expect(area.scrollTop).toBe(area.scrollHeight);
    });

    it("bajar manualmente al fondo limpia el contador", () => {
        const { result, area } = reading();
        act(() => result.current.receiveLatest(messages(101, 105), 101));
        area.scrollTop = area.scrollHeight - area.clientHeight;
        act(() => result.current.trackScroll(area));
        expect(result.current.newBelow).toBe(0);
    });

    it("un optimista y su confirmación cuentan una sola vez por client_message_id", () => {
        const { result, area, rerender } = reading({ sessionId: "session-a" });
        const local = message("tmp-1", { client_message_id: "client-1", sessionId: "session-a" });
        act(() => result.current.captureScroll());
        rerender({ local: [local] });
        expect(result.current.newBelow).toBe(1);
        act(() => result.current.receiveLatest([message(101, { client_message_id: "client-1" })], 101));
        expect(result.current.newBelow).toBe(1);
        act(() => result.current.captureScroll());
        rerender({ local: [] });
        expect(result.current.newBelow).toBe(1);
        expect(result.current.transcriptMessages.filter((m) => m.client_message_id === "client-1")).toHaveLength(1);
        expect(area.scrollTop).toBe(100);
    });

    it("retira del contador un optimista descartado sin contar mensajes de otra sesión", () => {
        const { result, rerender } = reading({ sessionId: "session-a" });
        act(() => result.current.captureScroll());
        rerender({ local: [message("tmp-1", { client_message_id: "key-1", sessionId: "session-a" })] });
        expect(result.current.newBelow).toBe(1);
        act(() => result.current.captureScroll());
        rerender({ local: [message("tmp-2", { client_message_id: "key-2", sessionId: "session-b" })] });
        expect(result.current.newBelow).toBe(0);
    });

    it("reset borra contador e identidades vistas y la selección nueva comienza sin avisos", () => {
        const { result, area } = reading();
        act(() => result.current.receiveLatest(messages(101, 105), 101));
        expect(result.current.newBelow).toBe(5);
        act(() => {
            result.current.resetHistory();
            result.current.receiveLatest([message(200)], 200);
        });
        expect(result.current.newBelow).toBe(0);
        expect(area.scrollTop).toBe(area.scrollHeight);
    });
});
