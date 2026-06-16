/**
 * ResultStep — resumen de importación. Protege la estrategia C de datos
 * incompletos: los warnings (datos OPCIONALES faltantes) se agregan una vez
 * aquí ("N mascotas sin fecha de nacimiento"), no como alerta global.
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));

import ResultStep from "./ResultStep";

describe("ResultStep — resumen de datos incompletos (C)", () => {
    it("agrega los warnings por campo con etiqueta humana", () => {
        const result = {
            created_owners: 2,
            created_pets: 3,
            warnings: [
                { row: 1, field: "pet.birth_date" },
                { row: 2, field: "pet.birth_date" },
                { row: 3, field: "pet.species" },
                { row: 4, field: "owner.phone" },
            ],
        };
        render(<ResultStep result={result} onReset={() => {}} />);

        expect(screen.getByText("Datos opcionales pendientes")).toBeInTheDocument();
        expect(screen.getByText(/sin fecha de nacimiento/)).toHaveTextContent("2 mascotas sin fecha de nacimiento");
        expect(screen.getByText(/sin especie/)).toHaveTextContent("1 mascotas sin especie");
        expect(screen.getByText(/sin teléfono/)).toHaveTextContent("1 clientes sin teléfono");
    });

    it("no muestra la sección si no hay warnings", () => {
        render(<ResultStep result={{ created_pets: 5, warnings: [] }} onReset={() => {}} />);
        expect(screen.queryByText("Datos opcionales pendientes")).not.toBeInTheDocument();
    });
});
