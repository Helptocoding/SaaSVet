/**
 * ActionMenu (Fase 1 Equipo): menú contextual de acciones de fila, en portal,
 * accesible con teclado.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ActionMenu from "./ActionMenu";

const items = (onReset = vi.fn(), onDeactivate = vi.fn()) => [
    { id: "reset", label: "Restablecer contraseña", onSelect: onReset },
    { id: "deactivate", label: "Desactivar acceso", danger: true, onSelect: onDeactivate },
];

describe("ActionMenu", () => {
    it("sin opciones no pinta nada", () => {
        const { container } = render(<ActionMenu label="Más acciones" items={[]} />);
        expect(container).toBeEmptyDOMElement();
    });

    it("abre un menú con sus opciones y ejecuta la elegida", async () => {
        const user = userEvent.setup({ delay: null });
        const onDeactivate = vi.fn();
        render(<ActionMenu label="Más acciones para Ana" items={items(vi.fn(), onDeactivate)} />);
        const trigger = screen.getByRole("button", { name: "Más acciones para Ana" });
        expect(trigger).toHaveAttribute("aria-haspopup", "menu");
        expect(trigger).toHaveAttribute("aria-expanded", "false");

        await user.click(trigger);
        expect(trigger).toHaveAttribute("aria-expanded", "true");
        const options = screen.getAllByRole("menuitem");
        expect(options.map((o) => o.textContent)).toEqual(["Restablecer contraseña", "Desactivar acceso"]);
        expect(options[0]).toHaveFocus();

        await user.click(options[1]);
        expect(onDeactivate).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole("menu")).not.toBeInTheDocument();
        expect(trigger).toHaveFocus();
    });

    it("se recorre con las flechas y Escape devuelve el foco al botón", async () => {
        const user = userEvent.setup({ delay: null });
        const onReset = vi.fn();
        render(<ActionMenu label="Más acciones" items={items(onReset)} />);
        const trigger = screen.getByRole("button", { name: "Más acciones" });
        trigger.focus();
        await user.keyboard("{ArrowDown}");
        const [first, second] = screen.getAllByRole("menuitem");
        expect(first).toHaveFocus();
        await user.keyboard("{ArrowDown}");
        expect(second).toHaveFocus();
        await user.keyboard("{ArrowDown}");
        expect(first).toHaveFocus();
        await user.keyboard("{End}");
        expect(second).toHaveFocus();
        await user.keyboard("{Escape}");
        expect(screen.queryByRole("menu")).not.toBeInTheDocument();
        expect(trigger).toHaveFocus();
        expect(onReset).not.toHaveBeenCalled();
    });

    it("un clic fuera lo cierra sin ejecutar nada", async () => {
        const user = userEvent.setup({ delay: null });
        const onReset = vi.fn();
        render(<><p>Fuera</p><ActionMenu label="Más acciones" items={items(onReset)} /></>);
        await user.click(screen.getByRole("button", { name: "Más acciones" }));
        expect(screen.getByRole("menu")).toBeInTheDocument();
        await user.click(screen.getByText("Fuera"));
        expect(screen.queryByRole("menu")).not.toBeInTheDocument();
        expect(onReset).not.toHaveBeenCalled();
    });

    it("deshabilitado no se abre y, ocupado, lo anuncia", async () => {
        const user = userEvent.setup({ delay: null });
        render(<ActionMenu label="Más acciones" items={items()} disabled busy />);
        const trigger = screen.getByRole("button", { name: "Más acciones" });
        expect(trigger).toBeDisabled();
        expect(trigger).toHaveAttribute("aria-busy", "true");
        await user.click(trigger);
        expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    });
});
