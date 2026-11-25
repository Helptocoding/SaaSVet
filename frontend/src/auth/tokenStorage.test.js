import { beforeEach, describe, expect, it } from "vitest";
import { clearTokens, getRemember, setTokens } from "./tokenStorage";

describe("tokenStorage — Recordarme", () => {
    beforeEach(() => clearTokens());

    it("remember=false guarda en sessionStorage y limpia localStorage", () => {
        localStorage.setItem("access_token", "old-local");

        setTokens({ access: "access-1", refresh: "refresh-1", remember: false });

        expect(sessionStorage.getItem("access_token")).toBe("access-1");
        expect(sessionStorage.getItem("refresh_token")).toBe("refresh-1");
        expect(sessionStorage.getItem("auth_persist")).toBe("0");
        expect(localStorage.getItem("access_token")).toBeNull();
        expect(localStorage.getItem("refresh_token")).toBeNull();
        expect(localStorage.getItem("auth_persist")).toBeNull();
    });

    it("remember=true guarda en localStorage y limpia sessionStorage", () => {
        sessionStorage.setItem("access_token", "old-session");

        setTokens({ access: "access-2", refresh: "refresh-2", remember: true });

        expect(localStorage.getItem("access_token")).toBe("access-2");
        expect(localStorage.getItem("refresh_token")).toBe("refresh-2");
        expect(localStorage.getItem("auth_persist")).toBe("1");
        expect(sessionStorage.getItem("access_token")).toBeNull();
        expect(sessionStorage.getItem("refresh_token")).toBeNull();
        expect(sessionStorage.getItem("auth_persist")).toBeNull();
    });

    it("getRemember devuelve la decisión persistida", () => {
        expect(getRemember()).toBe(true);

        setTokens({ access: "a", refresh: "r", remember: false });
        expect(getRemember()).toBe(false);

        setTokens({ access: "a", refresh: "r", remember: true });
        expect(getRemember()).toBe(true);
    });
});
