/**
 * Paso del código en el formulario de login (ADR p68).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const cancelMfa = vi.fn();
const setMfaCode = vi.fn();
vi.mock("../hooks/useLoginForm", () => ({
    useLoginForm: () => ({
        username: "ana", setUsername: () => {}, password: "x", setPassword: () => {},
        remember: true, setRemember: () => {}, loading: false, handleSubmit: () => {},
        mfaRequired: true, mfaCode: "", setMfaCode, cancelMfa,
    }),
}));

import { LoginForm } from "./LoginForm";

describe("LoginForm con verificación en dos pasos", () => {
    it("pide el código en lugar de la contraseña", () => {
        render(<LoginForm />);
        expect(screen.getByLabelText("Código de verificación")).toBeInTheDocument();
        expect(screen.queryByLabelText("Correo o usuario")).toBeNull();
        expect(screen.getByTestId("mfa-submit-button")).toBeDisabled();
        fireEvent.click(screen.getByRole("button", { name: "Volver" }));
        expect(cancelMfa).toHaveBeenCalled();
    });
});
