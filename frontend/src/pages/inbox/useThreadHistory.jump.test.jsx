import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useThreadHistory from "./useThreadHistory";

const getThreadMessages = vi.hoisted(() => vi.fn());
vi.mock("../../api/inbox", () => ({ getThreadMessages }));
const target = { contact: "ana", account: "main" };
const message = (id, extra = {}) => ({ id, body: `Mensaje ${id}`, created_at: "2026-10-22T12:00:00Z", ...extra });
const page = (rows, extra = {}) => ({ messages: rows, next_before: 1, ...extra });
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function setup() {
    let rows = [];
    const focus = vi.fn();
    const area = { scrollTop: 100, clientHeight: 300, getBoundingClientRect: () => ({ top: 0, bottom: 300 }) };
    area.scrollTo = vi.fn(({ top }) => { area.scrollTop = top; }); area.focus = vi.fn();
    Object.defineProperty(area, "scrollHeight", { get: () => rows.length * 100 + 300 });
    area.querySelectorAll = () => rows.map((row, index) => ({ focus,
        getAttribute: () => String(row.id), getBoundingClientRect: () => ({ top: 100 + index * 100 - area.scrollTop,
            bottom: 200 + index * 100 - area.scrollTop, height: 100 }) }));
    const viewport = { current: area };
    const hook = renderHook(() => { const history = useThreadHistory(viewport); rows = history.transcriptMessages; return history; });
    act(() => hook.result.current.receiveLatest([message(51), message(52)], 51, { syncFloor: "floor-51" }));
    area.scrollTop = 100;
    return { ...hook, area, focus };
}
beforeEach(() => {
    getThreadMessages.mockReset(); vi.useFakeTimers();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("WA-RPL-06 — salto e historial", () => {
    it("salta a un ID cargado sin GET, enfoca y resalta exactamente dos segundos", async () => {
        const { result, area, focus } = setup();
        await act(async () => result.current.jumpToMessage(target, 51));
        expect(getThreadMessages).not.toHaveBeenCalled(); expect(area.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
        expect(focus).toHaveBeenCalledWith({ preventScroll: true }); expect(result.current.highlightedId).toBe(51);
        act(() => vi.advanceTimersByTime(1999)); expect(result.current.highlightedId).toBe(51);
        act(() => vi.advanceTimersByTime(1)); expect(result.current.highlightedId).toBeNull();
    });
    it("respeta movimiento reducido", async () => {
        matchMedia.mockReturnValue({ matches: true }); const { result, area } = setup();
        await act(async () => result.current.jumpToMessage(target, 51)); expect(area.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "auto" });
    });
    it.each(["processed", "discarded", "failed"])("around incorpora el destino %s y deduplica sin retroceder estados", async (status) => {
        const { result } = setup();
        act(() => result.current.receiveLatest([message(52, { status: "read" })], 52));
        getThreadMessages.mockResolvedValue(page([message(1, { status, is_hidden: true }), message(51), message(52, { status: "sent" })], { sync_floor: "floor-1" }));
        await act(async () => result.current.jumpToMessage(target, 1));
        expect(getThreadMessages).toHaveBeenCalledExactlyOnceWith("ana", "main", { around: 1 }, { signal: expect.any(AbortSignal) });
        expect(result.current.messages.map((row) => row.id)).toEqual([1, 51, 52]);
        expect(result.current.messages[2].status).toBe("read"); expect(result.current.highlightedId).toBe(1);
        expect(result.current.nextBefore).toBe(51); expect(result.current.getSyncFloor()).toBe("floor-1");
        expect(result.current.newBelow).toBe(0);
    });
    it("llenar el intervalo con before mantiene el floor más antiguo", async () => {
        const { result } = setup();
        getThreadMessages.mockResolvedValueOnce(page([message(1)], { sync_floor: "floor-1" }))
            .mockResolvedValueOnce(page([message(25), message(50)], { next_before: 25, sync_floor: "floor-25" }));
        await act(async () => result.current.jumpToMessage(target, 1));
        await act(async () => result.current.loadOlder(target, { manual: true }));
        expect(getThreadMessages.mock.calls[1][2]).toEqual({ before: 51 });
        expect(result.current.getSyncFloor()).toBe("floor-1"); expect(result.current.nextBefore).toBe(25);
        expect(result.current.messages.map((row) => row.id)).toEqual([1, 25, 50, 51, 52]);
    });
    it("no cuenta la ventana histórica como nueva ni descarta avisos reales", async () => {
        const { result } = setup(); act(() => result.current.receiveLatest([message(53)], 53));
        expect(result.current.newBelow).toBe(1);
        getThreadMessages.mockResolvedValue(page([message(1)])); await act(async () => result.current.jumpToMessage(target, 1));
        expect(result.current.newBelow).toBe(1);
        act(() => result.current.trackScroll({ scrollTop: 1000, clientHeight: 300, scrollHeight: 1000 }));
        expect(result.current.newBelow).toBe(1);
    });
    it("el mismo salto pendiente no duplica GET y una cita distinta cancela el anterior", async () => {
        const first = deferred(), second = deferred(); const { result } = setup();
        getThreadMessages.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
        let a, b; act(() => { a = result.current.jumpToMessage(target, 1); });
        await act(async () => result.current.jumpToMessage(target, 1)); expect(getThreadMessages).toHaveBeenCalledTimes(1);
        const signal = getThreadMessages.mock.calls[0][3].signal;
        act(() => { b = result.current.jumpToMessage(target, 2); }); expect(signal.aborted).toBe(true);
        await act(async () => { second.resolve(page([message(2)])); await b; first.resolve(page([message(1)])); await a; });
        expect(result.current.highlightedId).toBe(2); expect(result.current.messages.some((row) => row.id === 1)).toBe(false);
    });
    it.each(["resolve", "reject"])("reset descarta %s tardío incluso al volver al mismo hilo", async (outcome) => {
        const wait = deferred(); const { result } = setup(); getThreadMessages.mockReturnValue(wait.promise);
        let pending; act(() => { pending = result.current.jumpToMessage(target, 1); });
        const signal = getThreadMessages.mock.calls[0][3].signal;
        act(() => { result.current.resetHistory(); result.current.receiveLatest([message(99)], null); });
        expect(signal.aborted).toBe(true);
        await act(async () => { wait[outcome](outcome === "resolve" ? page([message(1)]) : new Error("Antiguo")); await pending; });
        expect(result.current.messages.map((row) => row.id)).toEqual([99]); expect(result.current.jumpLoad.error).toBe("");
        expect(result.current.highlightedId).toBeNull();
    });
    it("404 y reintento explícito mantienen historial y cursor", async () => {
        const { result, area } = setup(); getThreadMessages.mockRejectedValueOnce({ response: { status: 404 } })
            .mockResolvedValueOnce(page([message(1)]));
        await act(async () => result.current.jumpToMessage(target, 1));
        expect(result.current.jumpLoad.error).toMatch(/ya no está disponible/); expect(area.scrollTop).toBe(100);
        expect(result.current.messages.map((row) => row.id)).toEqual([51, 52]); expect(result.current.nextBefore).toBe(51);
        await act(async () => result.current.jumpToMessage(target, 1)); expect(result.current.jumpLoad.error).toBe("");
    });
    it.each([page([]), page([message(1)], { contact_public_id: "ajeno" }), page([message(1)], { channel_account_public_id: "ajena" })])(
        "rechaza un paquete sin destino o de otro hilo %#", async (data) => {
            const { result } = setup(); getThreadMessages.mockResolvedValue(data);
            await act(async () => result.current.jumpToMessage(target, 1));
            expect(result.current.messages.map((row) => row.id)).toEqual([51, 52]); expect(result.current.jumpLoad.error).not.toBe("");
        },
    );
    it("una retirada explícita recibida durante around gana al paquete tardío", async () => {
        const wait = deferred(); const { result } = setup(); getThreadMessages.mockReturnValue(wait.promise);
        let pending; act(() => { pending = result.current.jumpToMessage(target, 1); });
        act(() => result.current.receiveLatest([], null, { removals: [1] }));
        await act(async () => { wait.resolve(page([message(1)])); await pending; });
        expect(result.current.messages.some((row) => row.id === 1)).toBe(false);
    });
    it("el rango operacional conserva durante el highlight al destino oculto revelado explícitamente", async () => {
        const { result } = setup();
        getThreadMessages.mockResolvedValue(page([message(1, { is_hidden: true, status: "discarded" })]));
        await act(async () => result.current.jumpToMessage(target, 1));
        act(() => result.current.receiveLatest([], null, { rangeIds: [51, 52] }));
        expect(result.current.messages[0].id).toBe(1); expect(result.current.highlightedId).toBe(1);
        act(() => result.current.receiveLatest([], null, { removals: [1], rangeIds: [51, 52] }));
        expect(result.current.messages.some((row) => row.id === 1)).toBe(false);
    });
    it("Ir al final cancela un around pendiente y conserva su propia intención", async () => {
        const wait = deferred(); const { result, area } = setup(); getThreadMessages.mockReturnValue(wait.promise);
        let pending; act(() => { pending = result.current.jumpToMessage(target, 1); });
        const signal = getThreadMessages.mock.calls[0][3].signal; act(() => result.current.goToEnd());
        expect(signal.aborted).toBe(true); expect(area.scrollTo).toHaveBeenLastCalledWith({ top: area.scrollHeight, behavior: "auto" });
        await act(async () => { wait.resolve(page([message(1)])); await pending; }); expect(result.current.highlightedId).toBeNull();
    });
    it("unmount aborta y limpia el temporizador de highlight", async () => {
        const { result, unmount } = setup(); await act(async () => result.current.jumpToMessage(target, 51));
        expect(vi.getTimerCount()).toBe(1); unmount(); expect(vi.getTimerCount()).toBe(0);
    });
    it.each([null, -1, "tmp:1", 0])("IDs inválidos %s no hacen GET", async (id) => {
        const { result } = setup(); await act(async () => result.current.jumpToMessage(target, id)); expect(getThreadMessages).not.toHaveBeenCalled();
    });
});
