/**
 * Login con verificación en dos pasos (ADR p68): la contraseña correcta de una
 * cuenta con MFA devuelve un reto, el formulario pide el código y solo entonces
 * se inicia la sesión. Un reto vencido vuelve a pedir la contraseña.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const loginRequest = vi.fn();
const loginMfaRequest = vi.fn();
const getMe = vi.fn();
vi.mock("../auth/login", () => ({
    loginRequest: (...a) => loginRequest(...a),
    loginMfaRequest: (...a) => loginMfaRequest(...a),
    getMe: (...a) => getMe(...a),
}));
const login = vi.fn();
const setUserData = vi.fn();
vi.mock("../auth/authContext", () => ({ useAuth: () => ({ login, setUserData }) }));
const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() } }));

import { toast } from "sonner";
import { loginErrorMessage, useLoginForm } from "./useLoginForm";

const httpError = (status, data = {}) => ({ response: { status, data } });

beforeEach(() => {
    vi.clearAllMocks();
    getMe.mockResolvedValue({ must_change_password: false });
});

async function typeCredentials(result) {
    act(() => {
        result.current.setUsername("ana");
        result.current.setPassword("secreta");
    });
}

describe("login con verificación en dos pasos", () => {
    it("pide el código y solo entra con él", async () => {
        loginRequest.mockResolvedValue({ mfa_required: true, mfa_token: "reto-1" });
        loginMfaRequest.mockResolvedValue({ access: "a", refresh: "r" });
        const { result } = renderHook(() => useLoginForm());
        await typeCredentials(result);
        await act(() => result.current.handleSubmit());
        expect(result.current.mfaRequired).toBe(true);
        expect(login).not.toHaveBeenCalled();

        act(() => result.current.setMfaCode(" 123456 "));
        await act(() => result.current.handleSubmit());
        expect(loginMfaRequest).toHaveBeenCalledWith("reto-1", "123456");
        expect(login).toHaveBeenCalledWith("a", "r", true);
        expect(navigate).toHaveBeenCalledWith("/");
    });

    it("un código de respaldo avisa cuántos quedan", async () => {
        loginRequest.mockResolvedValue({ mfa_required: true, mfa_token: "reto-1" });
        loginMfaRequest.mockResolvedValue({ access: "a", refresh: "r", recovery_codes_remaining: 2 });
        const { result } = renderHook(() => useLoginForm());
        await typeCredentials(result);
        await act(() => result.current.handleSubmit());
        act(() => result.current.setMfaCode("abcde-fghjk"));
        await act(() => result.current.handleSubmit());
        expect(toast.warning).toHaveBeenCalledWith(expect.stringMatching(/te quedan 2\. Genera nuevos/));
    });

    it("un reto vencido vuelve a la contraseña; un código mal escrito no", async () => {
        loginRequest.mockResolvedValue({ mfa_required: true, mfa_token: "reto-1" });
        const { result } = renderHook(() => useLoginForm());
        await typeCredentials(result);
        await act(() => result.current.handleSubmit());

        loginMfaRequest.mockRejectedValueOnce(httpError(401, { code: "mfa_code_invalid" }));
        act(() => result.current.setMfaCode("000000"));
        await act(() => result.current.handleSubmit());
        expect(result.current.mfaRequired).toBe(true);

        loginMfaRequest.mockRejectedValueOnce(httpError(401, { code: "mfa_challenge_invalid" }));
        await act(() => result.current.handleSubmit());
        expect(result.current.mfaRequired).toBe(false);
        expect(result.current.password).toBe("");
        expect(toast.error).toHaveBeenLastCalledWith("La verificación expiró. Vuelve a escribir tu contraseña.");
    });

    it("sin MFA el login sigue igual", async () => {
        loginRequest.mockResolvedValue({ access: "a", refresh: "r" });
        const { result } = renderHook(() => useLoginForm());
        await typeCredentials(result);
        await act(() => result.current.handleSubmit());
        expect(loginMfaRequest).not.toHaveBeenCalled();
        expect(login).toHaveBeenCalledWith("a", "r", true);
    });

    it("traduce los errores del segundo paso", () => {
        expect(loginErrorMessage(httpError(401, { code: "mfa_code_invalid" }))).toMatch(/código no es válido/);
        expect(loginErrorMessage(httpError(401, { code: "authentication_failed" })))
            .toBe("Usuario o contraseña incorrectos.");
    });
});
