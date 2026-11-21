import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StatSection, StatTile } from "./StatTiles";

describe("StatTiles (indicadores compartidos)", () => {
    it("sin onClick es informativo: no hay botón y muestra valor, insignia y pie", () => {
        render(
            <StatSection label="Resumen">
                <StatTile label="Caninos" value={12} badge="60%" foot="Del total de mascotas" />
            </StatSection>
        );
        const summary = screen.getByRole("region", { name: "Resumen" });
        expect(within(summary).queryByRole("button")).toBeNull();
        expect(within(summary).getByText("12")).toBeInTheDocument();
        expect(within(summary).getByText("60%")).toBeInTheDocument();
        expect(within(summary).getByText("Del total de mascotas")).toBeInTheDocument();
    });

    it("sin insignia no deja una píldora vacía", () => {
        const { container } = render(<StatTile label="Felinos" value={0} badge={null} foot="Del total" />);
        expect(container.textContent).toBe("Felinos0Del total");
    });

    it("con onClick es un conmutador accesible con su número en el nombre", () => {
        const onClick = vi.fn();
        render(<StatTile label="Bajo stock" value={3} foot="Ver productos" onClick={onClick} pressed />);
        const tile = screen.getByRole("button", { name: "Bajo stock: 3" });
        expect(tile).toHaveAttribute("aria-pressed", "true");
        fireEvent.click(tile);
        expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("el eyebrow es opcional", () => {
        render(<StatSection label="Resumen" eyebrow={null}><StatTile label="X" value={1} /></StatSection>);
        expect(screen.queryByText("Linear Insights")).toBeNull();
    });
});
