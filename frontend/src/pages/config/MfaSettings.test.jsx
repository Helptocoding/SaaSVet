/**
 * Verificación en dos pasos en Configuración → Cuenta (ADR p68): activar con
 * contraseña, clave y primer código; ver los códigos de respaldo una vez;
 * desactivar con contraseña y código. Solo aparece si la cuenta puede usarla.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("../../api/client", () => ({
    default: { get: (...a) => get(...a), post: (...a) => post(...a) },
}));
vi.mock("../../auth/authContext", () => ({
    useAuth: () => ({ user: { organization_timezone: "UTC" } }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { toast } from "sonner";
import MfaSettings from "./MfaSettings";

const OFF = { available: true, enabled: false, enabled_at: null, recovery_codes_remaining: 0 };
const ON = { available: true, enabled: true, enabled_at: "2026-11-24T10:00:00Z", recovery_codes_remaining: 10 };
const CODES = Array.from({ length: 10 }, (_, i) => `abcde-fgh${i}k`);

beforeEach(() => {
    vi.clearAllMocks();
});

describe("MfaSettings", () => {
    it("no aparece si la cuenta no puede usarla", async () => {
        get.mockResolvedValue({ data: { ...OFF, available: false } });
        const { container } = render(<MfaSettings />);
        await waitFor(() => expect(get).toHaveBeenCalledWith("users/mfa/"));
        expect(container).toBeEmptyDOMElement();
    });

    it("activa con contraseña, clave y código, y muestra los códigos de respaldo", async () => {
        const user = userEvent.setup({ delay: null });
        get.mockResolvedValue({ data: OFF });
        post.mockImplementation((url) => Promise.resolve({
            data: url === "users/mfa/setup/"
                ? { secret: "ABCD EFGH IJKL", otpauth_uri: "otpauth://totp/x" }
                : { ...ON, recovery_codes: CODES },
        }));
        render(<MfaSettings />);
        await user.click(await screen.findByRole("button", { name: "Activar" }));
        await user.type(screen.getByLabelText("CONFIRMA TU CONTRASEÑA"), "secreta");
        await user.click(screen.getByRole("button", { name: "Continuar" }));
        expect(post).toHaveBeenCalledWith("users/mfa/setup/", { password: "secreta" });
        expect(await screen.findByTestId("mfa-secret")).toHaveTextContent("ABCD EFGH IJKL");
        await user.type(screen.getByLabelText("CÓDIGO DE LA APP"), "123456");
        await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Activar" }));
        expect(post).toHaveBeenCalledWith("users/mfa/enable/", { code: "123456" });
        const list = await screen.findByRole("list", { name: "Códigos de respaldo" });
        expect(list.children).toHaveLength(10);
        expect(toast.success).toHaveBeenCalledWith("Verificación en dos pasos activada");
        await user.click(screen.getByRole("button", { name: "Ya los guardé" }));
        expect(screen.getByText(/10 códigos de respaldo/)).toBeInTheDocument();
    });

    it("muestra el error de contraseña en su campo", async () => {
        const user = userEvent.setup({ delay: null });
        get.mockResolvedValue({ data: OFF });
        post.mockRejectedValue({ response: { status: 400, data: {
            code: "validation_error", errors: { password: ["La contraseña no es correcta."] } } } });
        render(<MfaSettings />);
        await user.click(await screen.findByRole("button", { name: "Activar" }));
        await user.type(screen.getByLabelText("CONFIRMA TU CONTRASEÑA"), "mala");
        await user.click(screen.getByRole("button", { name: "Continuar" }));
        expect(await screen.findByText("La contraseña no es correcta.")).toBeInTheDocument();
    });

    it("desactiva con contraseña y código", async () => {
        const user = userEvent.setup({ delay: null });
        get.mockResolvedValue({ data: ON });
        post.mockResolvedValue({ data: OFF });
        render(<MfaSettings />);
        await user.click(await screen.findByRole("button", { name: "Desactivar" }));
        await user.type(screen.getByLabelText("CONTRASEÑA"), "secreta");
        await user.type(screen.getByLabelText("CÓDIGO DE LA APP O DE RESPALDO"), "123456");
        await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Desactivar" }));
        await waitFor(() => expect(post).toHaveBeenCalledWith("users/mfa/disable/", {
            password: "secreta", code: "123456" }));
        expect(await screen.findByRole("button", { name: "Activar" })).toBeInTheDocument();
    });
});
