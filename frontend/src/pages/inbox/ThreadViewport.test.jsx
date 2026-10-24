import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ThreadViewport from "./ThreadViewport";

describe("WA-HIST-01 — umbral del viewport", () => {
    it.each([0, 159, 160])("a scrollTop=%i sólo pide anteriores bajo 160 px", (top) => {
        const onReachStart = vi.fn();
        render(<ThreadViewport onReachStart={onReachStart} />);
        const area = scrollAt(600 - top);
        expect(area.scrollTop).toBe(top);
        expect(onReachStart).toHaveBeenCalledTimes(top < 160 ? 1 : 0);
    });
});

function scrollAt(distance) {
    const area = screen.getByRole("region", { name: "Mensajes de la conversación" });
    Object.defineProperties(area, {
        scrollHeight: { configurable: true, value: 1000 },
        clientHeight: { configurable: true, value: 400 },
        scrollTop: { configurable: true, writable: true, value: 600 - distance },
    });
    fireEvent.scroll(area);
    return area;
}

describe("WA-GTF-01 — Ir al final", () => {
    it.each([[201, true], [200, false], [199, false], [0, false], [-20, false]])(
        "a %i px del fondo: visible=%s", (distance, visible) => {
            render(<ThreadViewport><p>Mensaje conservado</p></ThreadViewport>);
            scrollAt(distance);
            if (visible) expect(screen.getByRole("button", { name: "Ir al final" })).toBeVisible();
            else expect(screen.queryByRole("button", { name: "Ir al final" })).not.toBeInTheDocument();
            expect(screen.getByText("Mensaje conservado")).toBeInTheDocument();
        },
    );

    it("no aparece en un historial que cabe completo", () => {
        render(<ThreadViewport><p>Mensaje único</p></ThreadViewport>);
        const area = screen.getByRole("region");
        Object.defineProperties(area, { scrollHeight: { value: 300 }, clientHeight: { value: 400 } });
        fireEvent.scroll(area);
        expect(screen.queryByRole("button", { name: "Ir al final" })).not.toBeInTheDocument();
    });

    it("desaparece al volver cerca del fondo y reaparece al subir", () => {
        render(<ThreadViewport />);
        scrollAt(500);
        expect(screen.getByRole("button", { name: "Ir al final" })).toBeVisible();
        scrollAt(50);
        expect(screen.queryByRole("button", { name: "Ir al final" })).not.toBeInTheDocument();
        scrollAt(300);
        expect(screen.getByRole("button", { name: "Ir al final" })).toBeVisible();
    });

    it("Enter vuelve al fondo del panel y conserva el foco para seguir leyendo", async () => {
        const user = userEvent.setup();
        render(<ThreadViewport><p>Historial</p></ThreadViewport>);
        const area = scrollAt(500);
        area.scrollTo = vi.fn();
        screen.getByRole("button", { name: "Ir al final" }).focus();
        await user.keyboard("{Enter}");
        expect(area.scrollTo).toHaveBeenCalledExactlyOnceWith({ top: 1000, behavior: "auto" });
        expect(area).toHaveFocus();
        expect(screen.queryByRole("button", { name: "Ir al final" })).not.toBeInTheDocument();
    });
});

describe("WA-HIST-02 — control de mensajes nuevos", () => {
    it.each([[1, "1 mensaje nuevo"], [5, "5 mensajes nuevos"]])("anuncia %i incluso a menos de 200 px del fondo", (newBelow, label) => {
        render(<ThreadViewport newBelow={newBelow} />);
        scrollAt(100);
        expect(screen.getByRole("button", { name: label })).toBeVisible();
        expect(screen.queryByRole("button", { name: "Ir al final" })).not.toBeInTheDocument();
    });
});
