// Tests de la parametrización por entidad del wizard (entityConfig).
// Owner_pet queda cubierto por los suites existentes (defaults idénticos);
// aquí se verifica que entityType='inventory' renderiza su dominio.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import PreviewStep from "./PreviewStep";
import ResultStep from "./ResultStep";
import UploadStep from "./UploadStep";
import { INVENTORY_CONFIG } from "./entityConfig";

const RESULT_INV = {
    created_products: 2,
    created_presentations: 2,
    initial_stock_movements: 1,
    skipped_duplicates: 0,
    skipped_conflicts: 0,
    conflicts_high: 0,
    conflicts_uncertain: 0,
    blocking_rows: 0,
    blocking: [],
    warnings: [],
    preview: [
        { row: 1, name: "Jeringa 3ml", internal_code: "JER-001", category: "other", base_unit: "piece", stock: "10", sale_price: "15.50", barcode: "" },
        { row: 2, name: "Solución", internal_code: "SOL-001", category: "medication", base_unit: "ml", stock: "6", sale_price: "40", barcode: "" },
    ],
    preview_total: 2,
};

describe("Wizard con entityType=inventory", () => {
    it("UploadStep muestra el copy de inventario", () => {
        render(<UploadStep onUpload={() => {}} uploading={false} config={INVENTORY_CONFIG} />);
        expect(screen.getByText("Sube tu archivo de productos")).toBeInTheDocument();
        expect(screen.getByText(/catálogo de productos/)).toBeInTheDocument();
    });

    it("PreviewStep renderiza columnas de producto y contadores", () => {
        render(
            <PreviewStep
                result={RESULT_INV}
                fieldCatalog={[]}
                entityType="inventory"
                onBack={() => {}}
                onConfirm={() => {}}
                committing={false}
                canCommit
            />,
        );
        expect(screen.getByText("(2 productos)")).toBeInTheDocument();
        expect(screen.getByText("Producto")).toBeInTheDocument();
        expect(screen.getByText("Código")).toBeInTheDocument();
        expect(screen.getByText("Jeringa 3ml")).toBeInTheDocument();
        expect(screen.getByText("JER-001")).toBeInTheDocument();
        // El copy de mascotas NO aparece
        expect(screen.queryByText(/mascota/i)).not.toBeInTheDocument();
    });

    it("ResultStep muestra tarjetas de inventario y CTA a /inventory", () => {
        render(
            <MemoryRouter>
                <ResultStep
                    result={RESULT_INV}
                    job={{ original_filename: "inv.xlsx" }}
                    fieldCatalog={[]}
                    entityType="inventory"
                    onReset={() => {}}
                />
            </MemoryRouter>,
        );
        expect(screen.getByText("Productos creados")).toBeInTheDocument();
        expect(screen.getByText("Presentaciones creadas")).toBeInTheDocument();
        expect(screen.getByText("Con stock inicial")).toBeInTheDocument();
        const cta = screen.getByText("Ver inventario");
        expect(cta).toBeInTheDocument();
    });

    it("ResultStep cuenta las filas omitidas por conflicto, que en inventario son los duplicados", () => {
        render(
            <MemoryRouter>
                <ResultStep
                    result={{ ...RESULT_INV, skipped_conflicts: 130, conflicts_high: 110, conflicts_uncertain: 20 }}
                    job={{ original_filename: "inv.xlsx" }}
                    fieldCatalog={[]}
                    entityType="inventory"
                    onReset={() => {}}
                />
            </MemoryRouter>,
        );
        const card = screen.getByText("Posibles duplicados omitidos").parentElement;
        expect(card).toHaveTextContent("130");
        expect(screen.queryByText("Duplicados omitidos")).not.toBeInTheDocument();
    });
});
