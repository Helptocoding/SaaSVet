import { act, fireEvent, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useThreadRead from "./useThreadRead";

const markThreadRead = vi.hoisted(() => vi.fn());
vi.mock("../../api/inbox", () => ({ markThreadRead }));
const a = { contact: "a", account: "main" };
const b = { contact: "a", account: "second" };
const data = (extra = {}) => ({ conversation: { public_id: "current" },
    last_read_message_id: 1, unread_count: 2, first_unread_message_id: 2,
    latest_visible_inbound_id: 3, ...extra });
const ack = (id = 3, count = 0) => ({ last_read_message_id: id, unread_count: count, unread_total: count });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
let focus, visibility;
beforeEach(() => {
    vi.useFakeTimers();
    focus = vi.spyOn(document, "hasFocus").mockReturnValue(true);
    visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    markThreadRead.mockReset().mockResolvedValue(ack());
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
const tick = async (ms) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
function setup(initial = data()) {
    const onDivider = vi.fn(), onMarked = vi.fn();
    const hook = renderHook(() => useThreadRead({ onDivider, onMarked }));
    act(() => { hook.result.current.resetRead(a); hook.result.current.receiveReadState(a, initial); });
    return { ...hook, onDivider, onMarked };
}

describe("WA-UNR-02 — lectura con atención real", () => {
    it("espera 1,5 s y confirma el último inbound mostrado", async () => {
        const hook = setup();
        expect(hook.onDivider).toHaveBeenLastCalledWith(2);
        await tick(1499);
        expect(markThreadRead).not.toHaveBeenCalled();
        await tick(1);
        expect(markThreadRead).toHaveBeenCalledWith("a", "main", 3, { signal: expect.any(AbortSignal) });
        expect(hook.onDivider).toHaveBeenLastCalledWith(null);
        expect(hook.onMarked).toHaveBeenCalledWith(a, ack());
    });
    it.each(["hidden", "prerender"])("no marca con visibilityState=%s", async (state) => {
        visibility.mockReturnValue(state);
        setup(); await tick(4000);
        expect(markThreadRead).not.toHaveBeenCalled();
    });
    it("no marca sin foco, y recuperar foco inicia un debounce completo", async () => {
        focus.mockReturnValue(false);
        setup(); await tick(2000);
        expect(markThreadRead).not.toHaveBeenCalled();
        focus.mockReturnValue(true); fireEvent.focus(window);
        await tick(1499); expect(markThreadRead).not.toHaveBeenCalled();
        await tick(1); expect(markThreadRead).toHaveBeenCalledTimes(1);
    });
    it.each(["blur", "visibilitychange"])("%s antes del plazo cancela la lectura", async (event) => {
        setup(); await tick(1000);
        if (event === "blur") { focus.mockReturnValue(false); fireEvent.blur(window); }
        else { visibility.mockReturnValue("hidden"); fireEvent(document, new Event("visibilitychange")); }
        await tick(3000);
        expect(markThreadRead).not.toHaveBeenCalled();
    });
    it("comprueba foco de nuevo al vencer, aunque no llegue el evento", async () => {
        setup(); focus.mockReturnValue(false); await tick(2000);
        expect(markThreadRead).not.toHaveBeenCalled();
    });
    it("una ráfaga nueva reinicia el plazo y usa el último id", async () => {
        const hook = setup(); await tick(1000);
        markThreadRead.mockResolvedValue(ack(4));
        act(() => hook.result.current.receiveReadState(a, data({ latest_visible_inbound_id: 4, unread_count: 3 })));
        await tick(1499); expect(markThreadRead).not.toHaveBeenCalled();
        await tick(1); expect(markThreadRead.mock.calls[0][2]).toBe(4);
    });
    it("un poll idéntico no posterga el plazo ni duplica un POST confirmado", async () => {
        const hook = setup(); await tick(1000);
        act(() => hook.result.current.receiveReadState(a, data()));
        await tick(500); expect(markThreadRead).toHaveBeenCalledTimes(1);
        act(() => hook.result.current.receiveReadState(a, data())); // snapshot anterior al acuse
        await tick(5000); expect(markThreadRead).toHaveBeenCalledTimes(1);
    });
    it("el fallo espera al siguiente poll para reintentar", async () => {
        markThreadRead.mockRejectedValueOnce(new Error("offline"));
        const hook = setup(); await tick(1500);
        expect(hook.onMarked).not.toHaveBeenCalled();
        expect(hook.onDivider).toHaveBeenLastCalledWith(2);
        fireEvent.focus(window); await tick(20000);
        expect(markThreadRead).toHaveBeenCalledTimes(1);
        act(() => hook.result.current.receiveReadState(a, data()));
        await tick(1500); expect(markThreadRead).toHaveBeenCalledTimes(2);
        expect(hook.onDivider).toHaveBeenLastCalledWith(null);
    });
    it("cambiar de cuenta cancela el debounce del hilo anterior", async () => {
        const hook = setup(); await tick(1000);
        act(() => hook.result.current.resetRead(b)); await tick(3000);
        expect(markThreadRead).not.toHaveBeenCalled();
    });
    it("A→B→A ignora un acuse tardío de la primera apertura", async () => {
        const pending = deferred(); markThreadRead.mockReturnValueOnce(pending.promise);
        const hook = setup(); await tick(1500);
        const signal = markThreadRead.mock.calls[0][3].signal;
        act(() => { hook.result.current.resetRead(b); hook.result.current.resetRead(a); });
        expect(signal.aborted).toBe(true);
        await act(async () => pending.resolve(ack()));
        expect(hook.onMarked).not.toHaveBeenCalled();
    });
    it("desmontar aborta el POST y no publica su respuesta", async () => {
        const pending = deferred(); markThreadRead.mockReturnValue(pending.promise);
        const hook = setup(); await tick(1500); hook.unmount();
        expect(markThreadRead.mock.calls[0][3].signal.aborted).toBe(true);
        await act(async () => pending.resolve(ack()));
        expect(hook.onMarked).not.toHaveBeenCalled();
    });
    it("no solapa POSTs y conserva llegadas posteriores al id confirmado", async () => {
        const pending = deferred(); markThreadRead.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ack(4));
        const hook = setup(); await tick(1500);
        act(() => hook.result.current.receiveReadState(a, data({ latest_visible_inbound_id: 4, first_unread_message_id: 4 })));
        await tick(2000); expect(markThreadRead).toHaveBeenCalledTimes(1);
        await act(async () => pending.resolve(ack()));
        expect(hook.onDivider).toHaveBeenLastCalledWith(4);
        await tick(1500); expect(markThreadRead).toHaveBeenCalledTimes(2);
        expect(markThreadRead.mock.calls[1][2]).toBe(4);
    });
    it.each([
        { unread_count: 0, first_unread_message_id: null },
        { conversation: null },
        { latest_visible_inbound_id: null, first_unread_message_id: null },
    ])("no inventa lectura ni divisor sin destino válido %j", async (extra) => {
        const hook = setup(data(extra)); await tick(3000);
        expect(markThreadRead).not.toHaveBeenCalled();
        if (!extra.conversation || extra.first_unread_message_id === null) {
            expect(hook.onDivider).toHaveBeenLastCalledWith(null);
        }
    });
});
