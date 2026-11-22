// El mensaje del login dice lo que realmente pasó. Antes todo lo que no era 401
// decía «Error de conexión. Verifica tu internet», incluido un bloqueo por CORS
// en local, el límite de intentos (429) o una clínica desactivada.
import { describe, expect, it } from "vitest";
import { loginErrorMessage } from "./useLoginForm";

const httpError = (status, data = {}) => ({ response: { status, data } });

describe("loginErrorMessage", () => {
    it("sin respuesta (red, backend apagado o CORS) habla del servidor, no de la contraseña", () => {
        expect(loginErrorMessage(new Error("Network Error")))
            .toBe("No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.");
    });

    it("401: credenciales", () => {
        expect(loginErrorMessage(httpError(401, { code: "authentication_failed" })))
            .toBe("Usuario o contraseña incorrectos.");
    });

    it("403 con contraseña temporal vencida", () => {
        expect(loginErrorMessage(httpError(403, { code: "temp_password_expired" })))
            .toMatch(/contraseña temporal expiró/);
    });

    it("403 con la clínica desactivada", () => {
        expect(loginErrorMessage(httpError(403, { code: "organization_inactive" })))
            .toMatch(/clínica está desactivada/);
    });

    it("429: límite de intentos, sin culpar a la conexión", () => {
        const msg = loginErrorMessage(httpError(429, { code: "throttled", message: "Demasiadas solicitudes." }));
        expect(msg).toMatch(/Demasiados intentos/);
        expect(msg).not.toMatch(/conexión/);
    });

    it("5xx: problema del servidor", () => {
        expect(loginErrorMessage(httpError(502))).toMatch(/servidor tuvo un problema/);
    });

    it("otro error usa el mensaje del backend", () => {
        expect(loginErrorMessage(httpError(400, { code: "validation_error", errors: { username: ["Este campo es requerido."] } })))
            .toMatch(/Este campo es requerido/);
    });
});
