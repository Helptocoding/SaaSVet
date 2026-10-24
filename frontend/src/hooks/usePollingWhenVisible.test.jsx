import { StrictMode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import usePollingWhenVisible from "./usePollingWhenVisible";

let hidden;
const visibility = (value) => {
    hidden.mockReturnValue(value);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
};
const advance = (ms) => act(() => vi.advanceTimersByTime(ms));

beforeEach(() => {
    vi.useFakeTimers();
    hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe("WA-VIS-01 — polling visible", () => {
    it("carga al montar y conserva la cadencia con una sola carga inicial", () => {
        const callback = vi.fn();
        renderHook(() => usePollingWhenVisible(callback, 10_000));
        expect(callback).toHaveBeenCalledExactlyOnceWith({ initial: true });
        advance(9_999);
        expect(callback).toHaveBeenCalledTimes(1);
        advance(1);
        expect(callback).toHaveBeenLastCalledWith({ initial: false });
        expect(callback).toHaveBeenCalledTimes(2);
    });

    it("no consulta ni arma intervalos si monta oculto", () => {
        hidden.mockReturnValue(true);
        const callback = vi.fn();
        renderHook(() => usePollingWhenVisible(callback, 10_000));
        advance(120_000);
        expect(callback).not.toHaveBeenCalled();
        expect(vi.getTimerCount()).toBe(0);
        visibility(false);
        expect(callback).toHaveBeenCalledExactlyOnceWith({ initial: true });
    });

    it("detiene al ocultar y refresca inmediatamente una sola vez al volver", () => {
        const callback = vi.fn();
        renderHook(() => usePollingWhenVisible(callback, 10_000));
        advance(5_000);
        visibility(true);
        expect(vi.getTimerCount()).toBe(0);
        advance(120_000);
        expect(callback).toHaveBeenCalledTimes(1);
        visibility(false);
        expect(callback).toHaveBeenCalledTimes(2);
        expect(callback).toHaveBeenLastCalledWith({ initial: false });
        visibility(false);
        expect(callback).toHaveBeenCalledTimes(2);
        expect(vi.getTimerCount()).toBe(1);
        advance(10_000);
        expect(callback).toHaveBeenCalledTimes(3);
    });

    it("protege un tick si hidden cambia antes de recibir visibilitychange", () => {
        const callback = vi.fn();
        renderHook(() => usePollingWhenVisible(callback, 10_000));
        hidden.mockReturnValue(true);
        advance(10_000);
        expect(callback).toHaveBeenCalledTimes(1);
    });

    it("al cambiar destino oculto usa sólo el nuevo callback al volver", () => {
        const previous = vi.fn();
        const current = vi.fn();
        const { rerender } = renderHook(({ callback }) => usePollingWhenVisible(callback, 10_000),
            { initialProps: { callback: previous } });
        visibility(true);
        rerender({ callback: current });
        advance(60_000);
        expect(current).not.toHaveBeenCalled();
        visibility(false);
        advance(10_000);
        expect(previous).toHaveBeenCalledTimes(1);
        expect(current).toHaveBeenCalledTimes(2);
    });

    it("deshabilitar y desmontar retiran intervalos y listeners", () => {
        const callback = vi.fn();
        const { rerender, unmount } = renderHook(({ enabled }) => usePollingWhenVisible(callback, 10_000, enabled),
            { initialProps: { enabled: false } });
        visibility(true);
        visibility(false);
        expect(callback).not.toHaveBeenCalled();
        rerender({ enabled: true });
        expect(callback).toHaveBeenCalledTimes(1);
        rerender({ enabled: false });
        advance(60_000);
        visibility(true);
        visibility(false);
        expect(callback).toHaveBeenCalledTimes(1);
        rerender({ enabled: true });
        unmount();
        visibility(true);
        visibility(false);
        advance(60_000);
        expect(callback).toHaveBeenCalledTimes(2);
        expect(vi.getTimerCount()).toBe(0);
    });

    it("StrictMode mantiene un único intervalo activo tras el montaje doble", () => {
        const callback = vi.fn();
        const { unmount } = renderHook(() => usePollingWhenVisible(callback, 10_000), { wrapper: StrictMode });
        const initialCalls = callback.mock.calls.length;
        expect(vi.getTimerCount()).toBe(1);
        advance(10_000);
        expect(callback).toHaveBeenCalledTimes(initialCalls + 1);
        unmount();
        expect(vi.getTimerCount()).toBe(0);
    });
});
