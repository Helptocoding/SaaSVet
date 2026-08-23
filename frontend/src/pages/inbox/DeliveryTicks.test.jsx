import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DeliveryTicks from "./DeliveryTicks";

describe("DeliveryTicks", () => {
    it.each([
        ["pending", "Pendiente de envío", "⏱"],
        ["sent", "Enviado", "✓"],
        ["delivered", "Entregado", "✓✓"],
        ["read", "Leído", "✓✓"],
        ["failed-local", "No se pudo enviar", "⚠"],
        ["discarded", "Descartado", "⚠"],
    ])("representa %s con nombre y título accesibles", (status, label, glyph) => {
        render(<DeliveryTicks status={status} direction="out" />);

        const tick = screen.getByLabelText(label);
        expect(tick).toHaveTextContent(glyph);
        expect(tick).toHaveAttribute("title", label);
    });

    it("expone el motivo de fallo sin convertirlo en texto visible del transcript", () => {
        render(
            <DeliveryTicks
                status="failed"
                direction="out"
                failure_reason="Ventana de atención cerrada"
            />
        );

        const label = "No entregado: Ventana de atención cerrada";
        const tick = screen.getByLabelText(label);
        expect(tick).toHaveTextContent("⚠");
        expect(tick).toHaveAttribute("title", label);
    });

    it("marca visualmente read como leído y no solo como entregado", () => {
        render(<DeliveryTicks status="read" direction="out" />);

        expect(screen.getByLabelText("Leído").className)
            .toContain("deliveryTickRead");
    });

    it.each(["pending", "sent", "delivered", "read", "failed", "failed-local", "discarded"])(
        "no muestra %s en mensajes entrantes",
        (status) => {
            const { container } = render(
                <DeliveryTicks status={status} direction="in" failure_reason="detalle" />
            );

            expect(container).toBeEmptyDOMElement();
        }
    );

    it("omite estados de salida desconocidos", () => {
        const { container } = render(
            <DeliveryTicks status="processed" direction="out" />
        );

        expect(container).toBeEmptyDOMElement();
    });
});
