import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import PreviewStep from "./PreviewStep";

// PreviewStep renderiza el `result` del dry-run (validate): el resumen de cuántos
// registros se crearán/omitirán/fallarán y el detalle por fila de errores y
// advertencias. Se prueba el render observable a partir de un result dado.

const FIELD_CATALOG = [
    { key: "owner.name", label: "Cliente · Nombre", group: "Cliente", required: true },
    { key: "owner.phone", label: "Cliente · Teléfono", group: "Cliente", required: false },
    { key: "pet.species", label: "Mascota · Especie", group: "Mascota", required: true },
];

const RESULT = {
    created_owners: 12,
    reused_owners: 3,
    created_pets: 15,
    skipped_duplicates: 4,
    error_rows: 2,
    errors: [
        { row: 5, field: "pet.species", message: "Especie no reconocida: 'Dinosaurio'." },
        { row: 9, field: "owner.name", message: "El nombre contiene caracteres no permitidos." },
    ],
    warnings: [
        { row: 7, field: "owner.phone", message: "Cliente sin teléfono; se importará sin dedup." },
    ],
};

function renderPreview(props = {}) {
    const onConfirm = vi.fn();
    const onBack = vi.fn();
    render(
        <PreviewStep
            result={props.result ?? RESULT}
            fieldCatalog={FIELD_CATALOG}
            onBack={onBack}
            onConfirm={onConfirm}
            committing={false}
            canCommit={props.canCommit ?? true}
        />
    );
    return { onConfirm, onBack };
}

describe("PreviewStep — resumen de conteos", () => {
    it("muestra clientes, mascotas, reutilizados, duplicados y filas con error", () => {
        renderPreview();
        // tarjetas del resumen
        expect(screen.getByText("Clientes nuevos")).toBeInTheDocument();
        expect(screen.getByText("Mascotas nuevas")).toBeInTheDocument();
        expect(screen.getByText("Clientes reutilizados")).toBeInTheDocument();
        expect(screen.getByText("Duplicados omitidos")).toBeInTheDocument();
        expect(screen.getByText("Filas con error")).toBeInTheDocument();

        // valores (font-mono) presentes
        expect(screen.getByText("12")).toBeInTheDocument(); // clientes nuevos
        expect(screen.getByText("15")).toBeInTheDocument(); // mascotas nuevas
    });

    it("la línea de resumen redacta el conteo en lenguaje claro", () => {
        renderPreview();
        // se crearán 12 clientes y 15 mascotas
        expect(screen.getByText(/12 clientes/)).toBeInTheDocument();
        expect(screen.getByText(/15 mascotas/)).toBeInTheDocument();
        expect(screen.getByText(/4 duplicados se omitir/)).toBeInTheDocument();
        expect(screen.getByText(/2 filas con error/)).toBeInTheDocument();
    });
});

describe("PreviewStep — errores y advertencias por fila", () => {
    it("lista cada error con su nº de fila, label del campo y mensaje", () => {
        renderPreview();
        expect(screen.getByText("Errores (2)")).toBeInTheDocument();

        expect(screen.getByText("#5")).toBeInTheDocument();
        expect(screen.getByText(/Especie no reconocida/)).toBeInTheDocument();
        // el campo se muestra con su label amistoso del catálogo
        expect(screen.getAllByText("Mascota · Especie").length).toBeGreaterThan(0);

        expect(screen.getByText("#9")).toBeInTheDocument();
        expect(screen.getByText(/caracteres no permitidos/)).toBeInTheDocument();
    });

    it("lista las advertencias con su fila y mensaje", () => {
        renderPreview();
        expect(screen.getByText("Advertencias (1)")).toBeInTheDocument();
        expect(screen.getByText("#7")).toBeInTheDocument();
        expect(screen.getByText(/se importará sin dedup/)).toBeInTheDocument();
    });

    it("sin errores ni advertencias muestra el estado vacío", () => {
        renderPreview({
            result: {
                created_owners: 5, reused_owners: 0, created_pets: 5,
                skipped_duplicates: 0, error_rows: 0, errors: [], warnings: [],
            },
        });
        expect(screen.getByText(/Sin errores ni advertencias/)).toBeInTheDocument();
        expect(screen.queryByText(/^Errores/)).not.toBeInTheDocument();
        expect(screen.queryByText(/^Advertencias/)).not.toBeInTheDocument();
    });
});

describe("PreviewStep — gating del commit (can('import.commit'))", () => {
    it("con permiso muestra el botón de confirmar y dispara onConfirm al hacer clic", async () => {
        const { onConfirm } = renderPreview({ canCommit: true });
        const btn = screen.getByRole("button", { name: /confirmar importación/i });
        expect(btn).toBeInTheDocument();
        btn.click();
        expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it("sin permiso NO muestra el botón de confirmar e informa la falta de permiso", () => {
        renderPreview({ canCommit: false });
        expect(screen.queryByRole("button", { name: /confirmar importación/i })).not.toBeInTheDocument();
        expect(screen.getByText(/no tienes permiso/i)).toBeInTheDocument();
    });
});
