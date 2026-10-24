import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ContactVerificationBadge from "./ContactVerificationBadge";

describe("WA-VER-01 — niveles de verificación", () => {
    it.each([
        ["staff_verified", "Verificado", "badge-success", "Identidad verificada por el personal de la clínica."],
        ["confirmed_in_chat", "Verificado", "badge-success", "Identidad confirmada mediante verificación en la conversación."],
        ["phone_match", "Teléfono coincide", "badge-warning", "El teléfono coincide con un cliente registrado; la identidad aún no está verificada."],
    ])("explica %s sin equiparar coincidencia de teléfono con verificación", (level, label, className, description) => {
        render(<ContactVerificationBadge level={level} />);
        expect(screen.getByText(label)).toHaveClass(className);
        expect(screen.getByText(label)).toHaveAttribute("title", description);
    });

    it.each(["unknown", undefined, "future_level", "toString"])("no inventa una verificación para %s", (level) => {
        const { container } = render(<ContactVerificationBadge level={level} />);
        expect(container).toBeEmptyDOMElement();
    });
});
