import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ImportedDataSection from "./ImportedDataSection";

// Muestra datos históricos importados (read-only). Lenguaje de migración a
// propósito; oculto si no hay datos.

describe("ImportedDataSection", () => {
    it("no renderiza nada si no hay datos", () => {
        const { container } = render(<ImportedDataSection items={[]} />);
        expect(container).toBeEmptyDOMElement();
        const { container: c2 } = render(<ImportedDataSection items={undefined} />);
        expect(c2).toBeEmptyDOMElement();
    });

    it("lista label/value con el encabezado de migración", () => {
        render(
            <ImportedDataSection
                items={[
                    { label: "Fecha Alta", value: "2018-01-01" },
                    { label: "Última vacuna", value: "Rabia 2023" },
                ]}
            />
        );
        expect(screen.getByText("Información del sistema anterior")).toBeInTheDocument();
        expect(screen.getByText("Fecha Alta")).toBeInTheDocument();
        expect(screen.getByText("2018-01-01")).toBeInTheDocument();
        expect(screen.getByText("Última vacuna")).toBeInTheDocument();
        expect(screen.getByText("Rabia 2023")).toBeInTheDocument();
    });

    it("muestra — cuando el valor está vacío", () => {
        render(<ImportedDataSection items={[{ label: "Facebook", value: "" }]} />);
        expect(screen.getByText("Facebook")).toBeInTheDocument();
        expect(screen.getByText("—")).toBeInTheDocument();
    });

    it("no usa lenguaje editable (Notas / Información adicional)", () => {
        render(<ImportedDataSection items={[{ label: "X", value: "y" }]} />);
        expect(screen.queryByText(/Notas/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Información adicional/i)).not.toBeInTheDocument();
    });
});
