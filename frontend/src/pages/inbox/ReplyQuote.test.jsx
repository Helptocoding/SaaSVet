import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ReplyQuote from "./ReplyQuote";

const quote = { id: 7, author_type: "client", excerpt: "Consulta sobre Luna", payload_type: "text", status: "processed" };

describe("WA-RPL-04 — bloque de cita", () => {
    it("identifica al cliente, muestra el extracto y navega con el ID original", () => {
        const onJump = vi.fn(); render(<ReplyQuote reply={quote} contactName="Ana" onJump={onJump} />);
        const button = screen.getByRole("button", { name: "Ir al mensaje original de Ana" });
        expect(button).toHaveTextContent("Consulta sobre Luna"); fireEvent.click(button);
        expect(onJump).toHaveBeenCalledExactlyOnceWith(7);
    });
    it.each([["human_staff", "Lucía", "Lucía"], ["agent", null, "Asistente"], ["system", null, "Automático"]])(
        "reutiliza la etiqueta del autor %s", (author_type, human_author_name, name) => {
            render(<ReplyQuote reply={{ ...quote, author_type, human_author_name }} onJump={vi.fn()} />);
            expect(screen.getByRole("button", { name: `Ir al mensaje original de ${name}` })).toBeVisible();
        },
    );
    it.each(["failed", "discarded"])("explica que el destino %s no se envió sin impedir el salto", (status) => {
        render(<ReplyQuote reply={{ ...quote, status }} contactName="Ana" onJump={vi.fn()} />);
        expect(screen.getByText("Mensaje no enviado")).toBeVisible(); expect(screen.getByRole("button")).toBeEnabled();
    });
    it("media muestra tipo y respaldo sin inventar contenido", () => {
        render(<ReplyQuote reply={{ ...quote, excerpt: "", payload_type: "image" }} contactName="Ana" onJump={vi.fn()} />);
        expect(screen.getByText("image", { exact: false })).toBeVisible();
        expect(screen.getByText("Contenido no disponible")).toBeVisible();
    });
    it.each([null, undefined, { ...quote, id: "tmp:7" }, { ...quote, id: -1 }])("omite referencias inexistentes o inválidas %#", (reply) => {
        const { container } = render(<ReplyQuote reply={reply} contactName="Ana" onJump={vi.fn()} />);
        expect(container).toBeEmptyDOMElement();
    });
    it("mantiene un nivel e interpreta HTML como texto", () => {
        const { container } = render(<ReplyQuote reply={{ ...quote, excerpt: "<img src=x onerror=alert(1)>", reply_to: quote }}
            contactName="Ana" onJump={vi.fn()} />);
        expect(container.querySelector("img")).toBeNull(); expect(screen.getAllByRole("button")).toHaveLength(1);
        expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
    });
    it("indica y bloquea la carga actual", () => {
        render(<ReplyQuote reply={quote} contactName="Ana" busy onJump={vi.fn()} />);
        expect(screen.getByRole("button")).toBeDisabled(); expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
    });
});
