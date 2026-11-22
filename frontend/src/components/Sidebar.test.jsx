// Plan UX F1.10: el menú decide por capacidad (`can()`), nunca por `user.role`
// (regla del frontend). Configuración depende de `organization.update`.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

let auth;
vi.mock("../auth/authContext", () => ({ useAuth: () => auth }));

import Sidebar from "./Sidebar";

const withPerms = (role, perms) => {
    const set = new Set(perms);
    auth = {
        user: { role, first_name: "Ana", organization_name: "Clínica" },
        initializing: false,
        can: (code) => set.has(code),
        canAny: (codes) => codes.some((c) => set.has(c)),
    };
};

const renderSidebar = () => render(
    <MemoryRouter initialEntries={["/"]}>
        <Sidebar onLogout={() => {}} />
    </MemoryRouter>
);

describe("Sidebar — permisos por capacidad", () => {
    beforeEach(() => withPerms("VET", []));

    it("muestra Configuración a quien puede editar la clínica", () => {
        withPerms("ADMIN", ["organization.update"]);
        renderSidebar();
        expect(screen.getByRole("link", { name: /Configuración/ })).toBeInTheDocument();
    });

    it("el rol ADMIN sin la capacidad no basta", () => {
        withPerms("ADMIN", []);
        renderSidebar();
        expect(screen.queryByRole("link", { name: /Configuración/ })).toBeNull();
    });

    it("quien gestiona personal ve Equipo pero no Configuración", () => {
        withPerms("ASSISTANT", ["staff.create"]);
        renderSidebar();
        expect(screen.getByRole("link", { name: /Equipo/ })).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: /Configuración/ })).toBeNull();
    });

    it("sin capacidades de administración no hay sección Admin", () => {
        renderSidebar();
        expect(screen.queryByText("Admin")).toBeNull();
    });
});
