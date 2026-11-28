// Plan UX F1.10: el menú decide por capacidad (`can()`), nunca por `user.role`
// (regla del frontend). Configuración depende de `organization.update`.
import { fireEvent, render, screen, within } from "@testing-library/react";
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

    it("quien gestiona el catálogo de servicios también ve Configuración (ADR p70 D8)", () => {
        withPerms("ASSISTANT", ["service.update"]);
        renderSidebar();
        expect(screen.getByRole("link", { name: /Configuración/ })).toBeInTheDocument();
    });

    it("el encabezado lleva el nombre público de la clínica (ADR p70 D5)", () => {
        withPerms("VET", []);
        auth.user = { ...auth.user, organization_name: "Servicios Vet SA", organization_public_name: "Clínica Luna" };
        renderSidebar();
        expect(screen.getByText("Clínica Luna")).toBeInTheDocument();
        expect(screen.queryByText("Servicios Vet SA")).toBeNull();
    });

    it("todos llegan a Mi cuenta desde su bloque de usuario", () => {
        renderSidebar();
        expect(screen.getByRole("link", { name: "Mi cuenta" })).toHaveAttribute("href", "/account");
    });

    it("sin capacidades de administración no hay sección Admin", () => {
        renderSidebar();
        expect(screen.queryByText("Admin")).toBeNull();
    });
});

// Plan UX D9 (ley de Hick): el menú va en grupos con nombre.
describe("Sidebar — grupos", () => {
    it("agrupa las entradas en Atención, Ventas y Operación", () => {
        withPerms("ADMIN", ["agentinbox.view"]);
        renderSidebar();
        const atencion = screen.getByRole("group", { name: "Atención" });
        expect(within(atencion).getByRole("link", { name: /Citas/ })).toBeInTheDocument();
        expect(within(atencion).getByRole("link", { name: /Historial clínico/ })).toBeInTheDocument();
        const ventas = screen.getByRole("group", { name: "Ventas" });
        expect(within(ventas).getByRole("link", { name: /Punto de venta/ })).toBeInTheDocument();
        expect(within(ventas).getByRole("link", { name: /Caja/ })).toBeInTheDocument();
        const operacion = screen.getByRole("group", { name: "Operación" });
        expect(within(operacion).getByRole("link", { name: /WhatsApp/ })).toBeInTheDocument();
    });

    it("una entrada sin permiso no aparece en su grupo", () => {
        withPerms("VET", []);
        renderSidebar();
        const operacion = screen.getByRole("group", { name: "Operación" });
        expect(within(operacion).queryByRole("link", { name: /WhatsApp/ })).toBeNull();
        expect(within(operacion).getByRole("link", { name: /Inventario/ })).toBeInTheDocument();
    });
});

// Plan UX D11: en móvil el menú es un panel; abierto, toma el foco, se cierra con
// Escape y al navegar.
describe("Sidebar — panel móvil", () => {
    const renderOpen = (props) => render(
        <MemoryRouter initialEntries={["/"]}>
            <Sidebar onLogout={() => {}} mobileOpen {...props} />
        </MemoryRouter>
    );

    it("abierto, pone el foco dentro del panel", () => {
        withPerms("ADMIN", []);
        renderOpen({ onClose: vi.fn(), onNavigate: vi.fn() });
        expect(document.getElementById("app-sidebar").contains(document.activeElement)).toBe(true);
    });

    it("Escape lo cierra", () => {
        withPerms("ADMIN", []);
        const onClose = vi.fn();
        renderOpen({ onClose, onNavigate: vi.fn() });
        fireEvent.keyDown(document, { key: "Escape" });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("navegar desde el panel lo cierra", () => {
        withPerms("ADMIN", []);
        const onNavigate = vi.fn();
        renderOpen({ onClose: vi.fn(), onNavigate });
        fireEvent.click(screen.getByRole("link", { name: /Citas/ }));
        expect(onNavigate).toHaveBeenCalledTimes(1);
    });

    it("cerrado no reacciona a Escape", () => {
        withPerms("ADMIN", []);
        const onClose = vi.fn();
        render(<MemoryRouter><Sidebar onLogout={() => {}} onClose={onClose} /></MemoryRouter>);
        fireEvent.keyDown(document, { key: "Escape" });
        expect(onClose).not.toHaveBeenCalled();
    });
});
