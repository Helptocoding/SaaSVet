// ADR p65 (D14): reintento único de un 401 cuya petición viajó con un access
// token que ya no es el almacenado. Adaptador de axios simulado con una función:
// sin dependencias nuevas. El cierre de sesión se observa por el almacenamiento
// vacío (`clearTokens` y la redirección van juntos en la misma rama).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let api;
let tokenStorage;
let calls;
let respond;
let alertSpy;

const fail = (config, status) => {
    const error = new Error(`Request failed with status code ${status}`);
    error.config = config;
    error.response = { status, data: {}, headers: {}, config };
    error.isAxiosError = true;
    return error;
};

const adapter = async (config) => {
    calls.push({
        url: config.url,
        auth: config.headers.Authorization,
        data: config.data,
        requestId: config.headers["X-Request-ID"],
        idempotencyKey: config.headers["X-Idempotency-Key"],
    });
    const status = await respond(config);
    if (status >= 400) throw fail(config, status);
    return { data: { ok: true }, status, statusText: "OK", headers: {}, config };
};

const access = () => tokenStorage.getItem("access_token");
const loggedOut = () => access() === null && tokenStorage.isLoggingOut();

// Retiene las respuestas de las primeras `n` peticiones hasta que llegan todas;
// entonces ejecuta `onRelease` (p. ej. la renovación del token) y las suelta.
const barrier = (n, onRelease) => {
    let arrived = 0;
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    return async () => {
        arrived += 1;
        if (arrived === n) {
            onRelease();
            release();
        }
        await gate;
    };
};

beforeEach(async () => {
    vi.stubEnv("VITE_API_URL", "http://api.test/api/");
    vi.resetModules();
    localStorage.clear();
    sessionStorage.clear();
    tokenStorage = await import("../auth/tokenStorage");
    ({ default: api } = await import("./client"));
    api.defaults.adapter = adapter;
    calls = [];
    tokenStorage.setTokens({ access: "old", refresh: "refresh-1", remember: true });
    alertSpy = vi.fn();
    vi.stubGlobal("alert", alertSpy);
});

afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
});

describe("reintento único tras un 401 con un token ya renovado (D14)", () => {
    it("reintenta una vez con el token vigente y conserva cuerpo y cabeceras", async () => {
        respond = (config) => {
            if (config.headers.Authorization === "Bearer old") {
                tokenStorage.setAccessToken("new"); // se renovó mientras viajaba
                return 401;
            }
            return 200;
        };
        const res = await api.post("staff/", { a: 1 }, { headers: { "X-Idempotency-Key": "k-1" } });

        expect(res.status).toBe(200);
        expect(calls.map((c) => c.auth)).toEqual(["Bearer old", "Bearer new"]);
        expect(calls[1].data).toBe(calls[0].data);
        expect(calls[1].requestId).toBe(calls[0].requestId);
        expect(calls[1].idempotencyKey).toBe("k-1");
        expect(access()).toBe("new");
    });

    it("si el reintento también es 401, cierra la sesión y no repite", async () => {
        respond = (config) => {
            if (config.headers.Authorization === "Bearer old") tokenStorage.setAccessToken("new");
            return 401;
        };
        await expect(api.get("me/")).rejects.toMatchObject({ response: { status: 401 } });

        expect(calls).toHaveLength(2);
        expect(loggedOut()).toBe(true);
    });

    it("aunque el token cambie en cada intento, se reintenta una sola vez", async () => {
        let attempt = 0;
        respond = () => {
            attempt += 1;
            if (attempt > 5) return 200; // tope de la prueba: sin la guarda sería un bucle
            tokenStorage.setAccessToken(`t${attempt}`);
            return 401;
        };
        await expect(api.post("staff/", { a: 1 })).rejects.toMatchObject({ response: { status: 401 } });

        expect(calls).toHaveLength(2);
        expect(loggedOut()).toBe(true);
    });

    it("un 401 con el token vigente cierra la sesión sin reintentar", async () => {
        respond = () => 401;
        await expect(api.get("me/")).rejects.toBeTruthy();

        expect(calls).toHaveLength(1);
        expect(loggedOut()).toBe(true);
    });

    it("el login conserva su excepción: ni reintento ni cierre de sesión", async () => {
        respond = () => {
            tokenStorage.setAccessToken("new");
            return 401;
        };
        await expect(api.post("token/", { username: "u", password: "p" })).rejects.toBeTruthy();

        expect(calls).toHaveLength(1);
        expect(access()).toBe("new");
    });

    it.each(["token/refresh/", "token/logout/"])("no reintenta %s", async (url) => {
        respond = () => {
            tokenStorage.setAccessToken("new");
            return 401;
        };
        await expect(api.post(url, { refresh: "r" })).rejects.toBeTruthy();

        expect(calls).toHaveLength(1);
    });

    it("no reintenta una petición que viajó sin token", async () => {
        localStorage.removeItem("access_token");
        respond = () => {
            tokenStorage.setAccessToken("new");
            return 401;
        };
        await expect(api.get("me/")).rejects.toBeTruthy();

        expect(calls).toHaveLength(1);
        expect(calls[0].auth).toBeUndefined();
        expect(loggedOut()).toBe(true);
    });

    it("no reintenta si ya no hay token almacenado", async () => {
        respond = () => {
            localStorage.removeItem("access_token");
            return 401;
        };
        await expect(api.get("me/")).rejects.toBeTruthy();

        expect(calls).toHaveLength(1);
        expect(loggedOut()).toBe(true);
    });

    it("no reintenta durante un cierre de sesión", async () => {
        respond = () => {
            tokenStorage.clearTokens();
            localStorage.setItem("access_token", "new");
            return 401;
        };
        await expect(api.get("me/")).rejects.toBeTruthy();

        expect(calls).toHaveLength(1);
    });

    it.each([403, 404, 500])("si el reintento devuelve %i, lo propaga sin repetir ni cerrar sesión", async (code) => {
        respond = (config) => {
            if (config.headers.Authorization === "Bearer old") {
                tokenStorage.setAccessToken("new");
                return 401;
            }
            return code;
        };
        await expect(api.post("staff/", { a: 1 })).rejects.toMatchObject({ response: { status: code } });

        expect(calls.map((c) => c.auth)).toEqual(["Bearer old", "Bearer new"]);
        expect(access()).toBe("new");
        expect(tokenStorage.isLoggingOut()).toBe(false);
        expect(alertSpy).toHaveBeenCalledTimes(code >= 500 ? 1 : 0);
    });

    it("un 403 con un token ya renovado no se reintenta", async () => {
        respond = () => {
            tokenStorage.setAccessToken("new");
            return 403;
        };
        await expect(api.post("staff/", { a: 1 })).rejects.toMatchObject({ response: { status: 403 } });

        expect(calls).toHaveLength(1);
        expect(access()).toBe("new");
        expect(tokenStorage.isLoggingOut()).toBe(false);
    });

    it("los errores que no son 401 siguen igual", async () => {
        respond = () => 500;
        await expect(api.get("me/")).rejects.toMatchObject({ response: { status: 500 } });
        expect(alertSpy).toHaveBeenCalledTimes(1);

        respond = () => 404;
        await expect(api.get("me/")).rejects.toMatchObject({ response: { status: 404 } });

        expect(calls).toHaveLength(2);
        expect(access()).toBe("old");
    });
});

describe("peticiones concurrentes (D14)", () => {
    it("varias peticiones con el token anterior se reintentan una vez cada una", async () => {
        const wait = barrier(3, () => tokenStorage.setAccessToken("new"));
        respond = async (config) => {
            if (config.headers.Authorization === "Bearer old") {
                await wait();
                return 401;
            }
            return 200;
        };
        const results = await Promise.all([api.get("a/"), api.get("b/"), api.get("c/")]);

        expect(results.map((r) => r.status)).toEqual([200, 200, 200]);
        expect(calls).toHaveLength(6);
        for (const url of ["a/", "b/", "c/"]) {
            expect(calls.filter((c) => c.url === url).map((c) => c.auth)).toEqual(["Bearer old", "Bearer new"]);
        }
        expect(access()).toBe("new");
    });

    it("si el token vigente también es inválido, todas terminan en el cierre de sesión", async () => {
        const wait = barrier(3, () => tokenStorage.setAccessToken("new"));
        respond = async (config) => {
            if (config.headers.Authorization === "Bearer old") await wait();
            return 401;
        };
        const results = await Promise.allSettled([api.get("a/"), api.get("b/"), api.get("c/")]);

        expect(results.every((r) => r.status === "rejected")).toBe(true);
        for (const url of ["a/", "b/", "c/"]) {
            expect(calls.filter((c) => c.url === url).length).toBeLessThanOrEqual(2);
        }
        expect(loggedOut()).toBe(true);
    });

    it("una petición con el token anterior no se reintenta si otra ya cerró la sesión", async () => {
        let releaseA;
        const gateA = new Promise((resolve) => { releaseA = resolve; });
        respond = async (config) => {
            if (config.url === "a/") await gateA;
            return 401; // b/ viaja con el token vigente y también está revocado
        };
        const a = api.post("a/", { x: 1 });
        await vi.waitFor(() => expect(calls).toHaveLength(1)); // a/ ya salió con "old"
        tokenStorage.setAccessToken("new");

        await expect(api.get("b/")).rejects.toBeTruthy();
        expect(loggedOut()).toBe(true);

        releaseA();
        await expect(a).rejects.toMatchObject({ response: { status: 401 } });

        expect(calls.map((c) => [c.url, c.auth])).toEqual([
            ["a/", "Bearer old"],
            ["b/", "Bearer new"],
        ]);
        expect(loggedOut()).toBe(true);
    });

    it("un reintento que termina después de otro login no lo deshace", async () => {
        // a/ viaja con "old", se renueva a "new" y su reintento sale con "new";
        // mientras tanto otra pestaña inicia sesión de nuevo ("newer"). Un 200
        // del reintento no toca el almacenamiento.
        let releaseRetry;
        const gateRetry = new Promise((resolve) => { releaseRetry = resolve; });
        respond = async (config) => {
            if (config.headers.Authorization === "Bearer old") {
                tokenStorage.setAccessToken("new");
                return 401;
            }
            await gateRetry;
            return 200;
        };
        const a = api.get("a/");
        await vi.waitFor(() => expect(calls).toHaveLength(2));
        tokenStorage.setTokens({ access: "newer", refresh: "refresh-2", remember: true });
        releaseRetry();

        expect((await a).status).toBe(200);
        expect(calls).toHaveLength(2);
        expect(access()).toBe("newer");
        expect(tokenStorage.isLoggingOut()).toBe(false);
    });
});
