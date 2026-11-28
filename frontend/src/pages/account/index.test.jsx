/**
 * Mi cuenta (ADR p70 D8, plan F1.2): para todo usuario autenticado, sin
 * depender de los permisos de Configuración.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

let auth;
vi.mock("../../auth/authContext", () => ({ useAuth: () => auth }));
vi.mock("../../components/ChangePasswordForm", () => ({ default: () => <form aria-label="Cambiar contraseña" /> }));
vi.mock("../config/MfaSettings", () => ({ default: () => <p>Verificación en dos pasos</p> }));

import Account from "./index";

const as = (user) => {
    auth = { user, can: () => false, canAny: () => false };
    return render(<MemoryRouter><Account /></MemoryRouter>);
};

describe("Mi cuenta", () => {
    it("un VET ve sus datos, su contraseña y la verificación", () => {
        as({ role: "VET", first_name: "Luis", last_name: "Mora", username: "luis",
             email: "luis@example.com", organization_name: "Clínica Luna" });
        expect(screen.getByRole("heading", { name: "Mi cuenta" })).toBeInTheDocument();
        expect(screen.getByText("Luis Mora")).toBeInTheDocument();
        expect(screen.getByText("luis@example.com")).toBeInTheDocument();
        expect(screen.getByRole("form", { name: "Cambiar contraseña" })).toBeInTheDocument();
        expect(screen.getByText("Verificación en dos pasos")).toBeInTheDocument();
    });

    it("un ADMIN sin permisos de configuración conserva su cuenta", () => {
        as({ role: "ADMIN", username: "admin", organization_name: "Clínica Luna" });
        expect(screen.getByRole("form", { name: "Cambiar contraseña" })).toBeInTheDocument();
        expect(screen.getByText("Sin capturar")).toBeInTheDocument();
    });

    it("en la demo no se ofrece cambiar la contraseña", () => {
        as({ role: "ADMIN", username: "demo", is_demo: true });
        expect(screen.queryByRole("form", { name: "Cambiar contraseña" })).toBeNull();
        expect(screen.getByText("En la demo la contraseña no se cambia.")).toBeInTheDocument();
    });
});
