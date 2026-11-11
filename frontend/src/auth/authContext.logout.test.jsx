import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./authContext";
import { clearTokens, getItem, setTokens } from "./tokenStorage";

const jwt = (secondsFromNow) => {
    const exp = Math.floor(Date.now() / 1000) + secondsFromNow;
    return `a.${btoa(JSON.stringify({ exp }))}.c`;
};
const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

const Probe = () => {
    const { logout, user } = useAuth();
    return <button onClick={logout}>{user ? "salir" : "sin sesión"}</button>;
};

const logoutCalls = () => fetch.mock.calls.filter(([url]) => String(url).includes("token/logout/"));

describe("cierre de sesión", () => {
    beforeEach(() => {
        clearTokens();
        vi.stubGlobal("fetch", vi.fn(async (url) => {
            if (String(url).includes("me/")) return json({ username: "ana", permissions: [] });
            return json({});
        }));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        clearTokens();
    });

    const signedIn = async () => {
        setTokens({ access: jwt(3600), refresh: "refresh-1", remember: true });
        render(<AuthProvider><Probe /></AuthProvider>);
        await screen.findByText("salir");
    };

    it("envía el refresh vigente antes de limpiar el almacenamiento", async () => {
        await signedIn();
        let storedWhenSent;
        fetch.mockImplementation(async (url) => {
            if (String(url).includes("token/logout/")) storedWhenSent = getItem("refresh_token");
            return json({});
        });
        await act(async () => screen.getByText("salir").click());
        expect(logoutCalls()).toHaveLength(1);
        expect(JSON.parse(logoutCalls()[0][1].body)).toEqual({ refresh: "refresh-1" });
        expect(storedWhenSent).toBe("refresh-1");
        expect(getItem("refresh_token")).toBeNull();
    });

    it("cierra la sesión local aunque el endpoint falle", async () => {
        await signedIn();
        fetch.mockImplementation(async () => { throw new Error("red caída"); });
        await act(async () => screen.getByText("salir").click());
        expect(getItem("access_token")).toBeNull();
        expect(getItem("refresh_token")).toBeNull();
        await screen.findByText("sin sesión");
    });

    it("no llama al endpoint cuando falla el refresh automático", async () => {
        setTokens({ access: jwt(-60), refresh: "caducado", remember: true });
        fetch.mockImplementation(async () => json({}, 401));
        render(<AuthProvider><Probe /></AuthProvider>);
        await waitFor(() => expect(getItem("refresh_token")).toBeNull());
        expect(logoutCalls()).toHaveLength(0);
    });

    it("no llama al endpoint si /me/ rechaza la sesión", async () => {
        setTokens({ access: jwt(3600), refresh: "refresh-1", remember: true });
        fetch.mockImplementation(async () => json({}, 401));
        render(<AuthProvider><Probe /></AuthProvider>);
        await waitFor(() => expect(getItem("refresh_token")).toBeNull());
        expect(logoutCalls()).toHaveLength(0);
    });

    it("un refresh en vuelo no revive la sesión tras cerrarla", async () => {
        setTokens({ access: jwt(1), refresh: "refresh-1", remember: true });
        let finishRefresh;
        fetch.mockImplementation((url) => {
            if (String(url).includes("token/refresh/")) {
                return new Promise((resolve) => { finishRefresh = resolve; });
            }
            return Promise.resolve(json({ username: "ana", permissions: [] }));
        });
        render(<AuthProvider><Probe /></AuthProvider>);
        await screen.findByText("salir");
        await waitFor(() => expect(finishRefresh).toBeTypeOf("function"), { timeout: 3000 });
        await act(async () => screen.getByText("salir").click());
        await act(async () => finishRefresh(json({ access: jwt(3600), refresh: "refresh-2" })));
        expect(getItem("refresh_token")).toBeNull();
        expect(getItem("access_token")).toBeNull();
    });
});
