import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getInboxMedia: vi.fn() }));
const auth = vi.hoisted(() => ({ user: { id: 1, organization: "clinic-a" } }));
vi.mock("../../api/inbox", () => api);
vi.mock("../../auth/authContext", () => ({ useAuth: () => auth }));
import MediaBubble from "./MediaBubble";
import useMediaUrl, { acquireMediaUrl } from "./useMediaUrl";

const ready = (extra = {}) => ({ public_id: "media-1", status: "ready", mime_type: "image/png", file_size: 1024,
    filename: "photo.png", expires_at: "2099-01-01T00:00:00Z", ...extra });
const flush = async () => { await act(async () => {}); };
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
let number;
beforeEach(() => {
    number = 0;
    api.getInboxMedia.mockReset().mockResolvedValue(new Blob(["synthetic media"], { type: "image/png" }));
    auth.user = { id: 1, organization: "clinic-a" };
    vi.stubGlobal("IntersectionObserver", undefined);
    URL.createObjectURL = vi.fn(() => `blob:private-${++number}`);
    URL.revokeObjectURL = vi.fn();
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
        configurable: true, value: vi.fn(function () { this.open = true; }),
    });
    Object.defineProperty(HTMLDialogElement.prototype, "close", {
        configurable: true, value: vi.fn(function () { this.open = false; }),
    });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("MED-05 — private blob lifecycle", () => {
    it("deduplicates consumers, keeps one live URL and revokes only on final release", async () => {
        const one = acquireMediaUrl("shared", "clinic");
        const two = acquireMediaUrl("shared", "clinic");
        expect(await one.promise).toBe(await two.promise);
        expect(api.getInboxMedia).toHaveBeenCalledTimes(1);
        one.release(); one.release();
        expect(URL.revokeObjectURL).not.toHaveBeenCalled();
        two.release();
        expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:private-1");
    });
    it("separates clinics and aborts pending I/O on final release", async () => {
        const wait = deferred(); api.getInboxMedia.mockReturnValue(wait.promise);
        const one = acquireMediaUrl("same", "clinic-a"), two = acquireMediaUrl("same", "clinic-b");
        const handled = Promise.allSettled([one.promise, two.promise]);
        one.release(); two.release();
        expect(api.getInboxMedia).toHaveBeenCalledTimes(2);
        expect(api.getInboxMedia.mock.calls.every((call) => call[1].signal.aborted)).toBe(true);
        wait.resolve(new Blob(["late"]));
        expect((await handled).every((row) => row.status === "rejected")).toBe(true);
        expect(URL.createObjectURL).not.toHaveBeenCalled();
    });
    it("does not reuse a revoked URL after leaving and reentering viewport", async () => {
        const hook = renderHook(({ enabled }) => useMediaUrl("view", { enabled, scope: "clinic" }), { initialProps: { enabled: true } });
        await flush(); const first = hook.result.current.url;
        hook.rerender({ enabled: false }); expect(hook.result.current.url).toBeNull();
        hook.rerender({ enabled: true }); await flush();
        expect(hook.result.current.url).not.toBe(first);
        expect(api.getInboxMedia).toHaveBeenCalledTimes(2);
        hook.unmount();
    });
    it("late responses from a previous clinic cannot replace current content", async () => {
        const wait = deferred(); api.getInboxMedia.mockReturnValueOnce(wait.promise);
        const hook = renderHook(({ scope }) => useMediaUrl("view", { enabled: true, scope }), { initialProps: { scope: "old" } });
        hook.rerender({ scope: "new" }); await flush();
        const current = hook.result.current.url;
        await act(async () => wait.resolve(new Blob(["old"])));
        expect(hook.result.current.url).toBe(current);
        expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
        hook.unmount();
    });
});

describe("MED-05 — media controls and states", () => {
    it("loads a thumbnail through authenticated fetch and opens/closes the lightbox", async () => {
        const view = render(<MediaBubble media={ready()} kind="image" caption="Herida en pata" />);
        expect(screen.getByRole("status")).toHaveTextContent("Cargando archivo");
        await flush();
        expect(screen.getByRole("img", { name: "Herida en pata" })).toHaveAttribute("src", "blob:private-1");
        expect(api.getInboxMedia).toHaveBeenCalledWith("media-1", { signal: expect.any(AbortSignal) });
        const thumbnail = screen.getByRole("button", { name: "Ampliar imagen" });
        fireEvent.click(thumbnail);
        expect(screen.getByRole("dialog", { name: "Imagen ampliada" })).toBeVisible();
        fireEvent.click(screen.getByRole("button", { name: "Cerrar imagen" }));
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(thumbnail).toHaveFocus();
        view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-1");
    });
    it("waits until an image approaches the viewport", async () => {
        let notify;
        vi.stubGlobal("IntersectionObserver", class {
            constructor(callback) { notify = callback; } observe() {} disconnect() {}
        });
        render(<MediaBubble media={ready()} kind="image" />);
        await flush(); expect(api.getInboxMedia).not.toHaveBeenCalled();
        await act(async () => notify([{ isIntersecting: true }]));
        expect(api.getInboxMedia).toHaveBeenCalledTimes(1);
    });
    it.each(["audio", "video"])("%s requires a click, shows weight and never autoplays", async (kind) => {
        const view = render(<MediaBubble media={ready({ file_size: 2 * 1024 * 1024 })} kind={kind} />);
        await flush(); expect(api.getInboxMedia).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: new RegExp(`Cargar ${kind}.*2.0 MB`) }));
        await flush();
        const control = view.container.querySelector(kind);
        expect(control).toHaveAttribute("controls");
        expect(control).not.toHaveAttribute("autoplay");
        expect(control).toHaveAttribute("src", "blob:private-1");
    });
    it("large image advertises weight before explicit fetch", async () => {
        render(<MediaBubble media={ready({ file_size: 7 * 1024 * 1024 })} kind="image" />);
        await flush(); expect(api.getInboxMedia).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: /Cargar imagen.*7.0 MB/ }));
        await flush(); expect(api.getInboxMedia).toHaveBeenCalledTimes(1);
    });
    it("document downloads only on click and releases its temporary URL", async () => {
        vi.useFakeTimers();
        const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
        render(<MediaBubble media={ready({ filename: "study.pdf", mime_type: "application/pdf" })} kind="document" />);
        expect(screen.getByText("study.pdf")).toBeVisible();
        expect(api.getInboxMedia).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: "Descargar documento" })); await flush();
        expect(click).toHaveBeenCalledTimes(1);
        expect(click.mock.instances[0].download).toBe("study.pdf");
        await act(async () => vi.advanceTimersByTime(1001));
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-1");
    });
    it.each(["pending", "downloading", "failed", "expired"])("pipeline state %s has no fetch/retry loop", async (status) => {
        render(<MediaBubble media={ready({ status })} kind="image" />); await flush();
        expect(screen.getByRole("status")).toHaveTextContent(status === "expired" ? "Archivo expirado" :
            status === "failed" ? "Archivo no disponible" : "Recibiendo archivo");
        expect(api.getInboxMedia).not.toHaveBeenCalled();
        expect(screen.queryByRole("button", { name: "Reintentar archivo" })).not.toBeInTheDocument();
    });
    it("network errors offer explicit retry and then recover", async () => {
        api.getInboxMedia.mockRejectedValueOnce(new Error("synthetic"));
        render(<MediaBubble media={ready()} kind="image" />); await flush();
        expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar");
        expect(api.getInboxMedia).toHaveBeenCalledTimes(1);
        fireEvent.click(screen.getByRole("button", { name: "Reintentar archivo" })); await flush();
        expect(screen.getByRole("button", { name: "Ampliar imagen" })).toBeVisible();
        expect(api.getInboxMedia).toHaveBeenCalledTimes(2);
    });
    it("410 displays expired without retry or repeated requests", async () => {
        api.getInboxMedia.mockRejectedValueOnce({ response: { status: 410 } });
        render(<MediaBubble media={ready()} kind="image" />); await flush();
        expect(screen.getByRole("status")).toHaveTextContent("Archivo expirado");
        expect(screen.queryByRole("button")).not.toBeInTheDocument();
        expect(api.getInboxMedia).toHaveBeenCalledTimes(1);
    });
    it("deadline revokes the blob and displays expired even without a poll", async () => {
        vi.useFakeTimers();
        render(<MediaBubble media={ready({ expires_at: new Date(Date.now() + 1000).toISOString() })} kind="image" />);
        await flush(); expect(screen.getByRole("img")).toBeVisible();
        await act(async () => vi.advanceTimersByTime(1002));
        expect(screen.getByRole("status")).toHaveTextContent("Archivo expirado");
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-1");
    });
});
