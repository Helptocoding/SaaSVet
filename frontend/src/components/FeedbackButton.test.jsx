// Plan UX D3: «Reportar un problema» es un botón de la barra superior con nombre
// accesible (antes un «?» flotante que tapaba acciones de las tablas).
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendSupportMessage = vi.fn();
vi.mock("../api/support", () => ({ sendSupportMessage: (...a) => sendSupportMessage(...a) }));
const toastError = vi.fn();
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: (...a) => toastError(...a), success: vi.fn() }),
}));

import FeedbackButton from "./FeedbackButton";

beforeEach(() => {
    sendSupportMessage.mockReset();
    toastError.mockReset();
});

describe("FeedbackButton", () => {
    it("el disparador dice lo que hace y abre el diálogo", () => {
        render(<FeedbackButton />);
        fireEvent.click(screen.getByRole("button", { name: "Reportar un problema" }));
        expect(screen.getByRole("dialog", { name: "Reportar un problema" })).toBeInTheDocument();
    });

    it("no envía un reporte vacío", () => {
        render(<FeedbackButton />);
        fireEvent.click(screen.getByRole("button", { name: "Reportar un problema" }));
        fireEvent.click(screen.getByRole("button", { name: "Enviar reporte" }));
        expect(sendSupportMessage).not.toHaveBeenCalled();
        expect(toastError).toHaveBeenCalledWith("Describe el problema.");
    });

    it("se cierra con Escape", () => {
        render(<FeedbackButton />);
        fireEvent.click(screen.getByRole("button", { name: "Reportar un problema" }));
        fireEvent.keyDown(window, { key: "Escape" });
        expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("el diálogo se monta en document.body, fuera de la barra superior", () => {
        const { container } = render(<FeedbackButton />);
        fireEvent.click(screen.getByRole("button", { name: "Reportar un problema" }));
        expect(container.querySelector("[role=dialog]")).toBeNull();
        expect(document.body.querySelector("[role=dialog]")).not.toBeNull();
    });
});
