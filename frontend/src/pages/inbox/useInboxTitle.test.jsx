import { StrictMode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useInboxTitle from "./useInboxTitle";

const threads = [{ has_unanswered: true }, { has_unanswered: false },
    { has_unanswered: true }, {}, { has_unanswered: true }];
let hidden, focused;

beforeEach(() => {
    document.title = "SaaslyVet";
    hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    focused = vi.spyOn(document, "hasFocus").mockReturnValue(true);
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    document.title = "SaaslyVet";
});

describe("WA-TAB-01 — pendientes en la pestaña", () => {
    it("mantiene el título normal mientras recepción tiene el foco", () => {
        renderHook(() => useInboxTitle(threads));
        expect(document.title).toBe("SaaslyVet");
    });
    it("cuenta sólo hilos pendientes en una pestaña oculta", () => {
        hidden.mockReturnValue(true);
        renderHook(() => useInboxTitle(threads));
        expect(document.title).toBe("(3) SaaslyVet");
    });
    it("actualiza el último conteo sin acumular prefijos y elimina el cero", () => {
        focused.mockReturnValue(false);
        const { rerender } = renderHook(({ rows }) => useInboxTitle(rows), { initialProps: { rows: threads } });
        expect(document.title).toBe("(3) SaaslyVet");
        rerender({ rows: [{ has_unanswered: true }] });
        expect(document.title).toBe("(1) SaaslyVet");
        rerender({ rows: [] });
        expect(document.title).toBe("SaaslyVet");
    });
    it("restaura al foco y vuelve a contar al ocultar o desenfocar", () => {
        renderHook(() => useInboxTitle(threads));
        focused.mockReturnValue(false);
        act(() => window.dispatchEvent(new Event("blur")));
        expect(document.title).toBe("(3) SaaslyVet");
        focused.mockReturnValue(true);
        act(() => window.dispatchEvent(new Event("focus")));
        expect(document.title).toBe("SaaslyVet");
        hidden.mockReturnValue(true);
        act(() => document.dispatchEvent(new Event("visibilitychange")));
        expect(document.title).toBe("(3) SaaslyVet");
        hidden.mockReturnValue(false);
        act(() => document.dispatchEvent(new Event("visibilitychange")));
        expect(document.title).toBe("SaaslyVet");
    });
    it("restaura el título y retira listeners al salir del Inbox", () => {
        focused.mockReturnValue(false);
        const { unmount } = renderHook(() => useInboxTitle(threads));
        unmount();
        expect(document.title).toBe("SaaslyVet");
        document.title = "Otra página";
        act(() => {
            window.dispatchEvent(new Event("blur"));
            document.dispatchEvent(new Event("visibilitychange"));
        });
        expect(document.title).toBe("Otra página");
    });
    it("conserva el título base en el montaje doble de StrictMode", () => {
        focused.mockReturnValue(false);
        const { unmount } = renderHook(() => useInboxTitle(threads), { wrapper: StrictMode });
        expect(document.title).toBe("(3) SaaslyVet");
        unmount();
        expect(document.title).toBe("SaaslyVet");
    });
});
