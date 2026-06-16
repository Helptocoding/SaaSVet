import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import PreviewStep from "./PreviewStep";

// PreviewStep renderiza el `result` del dry-run (validate). Fase 3: agrupa
// conflictos (posibles duplicados), bloqueantes (faltan datos) y avisos.
// La UI es lenguaje humano, sin tokens técnicos (legacy_id, constraint).

const FIELD_CATALOG = [
    { key: "owner.name", label: "Nombre del cliente", group: "Cliente", importance: "required" },
    { key: "owner.phone", label: "Teléfono del cliente", group: "Cliente", importance: "recommended" },
    { key: "pet.name", label: "Nombre de la mascota", group: "Mascota", importance: "required" },
    { key: "pet.species", label: "Especie", group: "Mascota", importance: "recommended" },
    { key: "pet.legacy_id", label: "Nº de expediente anterior", group: "Mascota", importance: "optional" },
];

const RESULT_WITH_CONFLICTS = {
    created_owners: 1,
    reused_owners: 0,
    created_pets: 1,
    skipped_duplicates: 2,
    skipped_conflicts: 3,
    blocking_rows: 0,
    errors: [],
    blocking: [],
    conflicts: [
        {
            row: 5,
            type: "duplicate_legacy_id",
            severity: "conflict",
            scope: "pet",
            match_confidence: "high",
            message: "Ya existe una mascota con este expediente.",
            incoming: { pet_name: "Luna", owner_name: "Ana López", legacy_id: "126" },
            existing: { pet_name: "Luna", owner_name: "Ana López", public_id: "abc-123" },
        },
        {
            row: 8,
            type: "duplicate_legacy_id",
            severity: "conflict",
            scope: "pet",
            match_confidence: "uncertain",
            message: "Ya existe una mascota con este expediente.",
            incoming: { pet_name: "Rocky", owner_name: "Pedro", legacy_id: "200" },
            existing: { pet_name: "Max", owner_name: "Juan", public_id: "def-456" },
        },
    ],
    warnings: [],
};

const RESULT_WITH_BLOCKING = {
    created_owners: 0,
    reused_owners: 0,
    created_pets: 0,
    skipped_duplicates: 0,
    skipped_conflicts: 0,
    blocking_rows: 2,
    errors: [
        { row: 2, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 7, field: "owner.phone", message: "El teléfono debe tener 10 dígitos." },
    ],
    blocking: [
        { row: 2, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 7, field: "owner.phone", message: "El teléfono debe tener 10 dígitos." },
    ],
    conflicts: [],
    warnings: [
        { row: 4, field: "owner.phone", message: "Cliente sin teléfono — se importará igual." },
    ],
};

const RESULT_CLEAN = {
    created_owners: 5,
    reused_owners: 0,
    created_pets: 5,
    skipped_duplicates: 0,
    skipped_conflicts: 0,
    blocking_rows: 0,
    errors: [],
    blocking: [],
    conflicts: [],
    warnings: [],
};

function renderPreview(props = {}) {
    const onConfirm = vi.fn();
    const onBack = vi.fn();
    render(
        <PreviewStep
            result={props.result ?? RESULT_WITH_CONFLICTS}
            fieldCatalog={FIELD_CATALOG}
            onBack={onBack}
            onConfirm={onConfirm}
            committing={false}
            canCommit={props.canCommit ?? true}
        />
    );
    return { onConfirm, onBack };
}

describe("PreviewStep — resumen humano", () => {
    it("muestra pacientes listos, duplicados omitidos, necesitan revisión", () => {
        renderPreview();
        expect(screen.getByText(/1 paciente listo para importar/)).toBeInTheDocument();
        // "2 duplicados se omitirán" aparece en resumen + consecuencia → getAllByText
        expect(screen.getAllByText(/2 duplicados se omitirán/).length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText(/3 necesitan revisión/)).toBeInTheDocument();
    });

    it("con bloqueantes muestra 'no se pueden importar'", () => {
        renderPreview({ result: RESULT_WITH_BLOCKING });
        expect(screen.getByText(/2 no se pueden importar/)).toBeInTheDocument();
    });

    it("sin nada muestra estado vacío", () => {
        renderPreview({ result: RESULT_CLEAN });
        expect(screen.getByText(/Sin errores ni advertencias/)).toBeInTheDocument();
    });
});

describe("PreviewStep — conflictos (posibles duplicados)", () => {
    it("muestra comparación lado a lado con nombres humanos", () => {
        renderPreview();
        // Nombres de mascota en la comparación (aparecen en ambas columnas)
        expect(screen.getAllByText("Luna").length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText("Rocky")).toBeInTheDocument();
        expect(screen.getByText("Max")).toBeInTheDocument();
        // Nombres de dueño
        expect(screen.getAllByText("Ana López").length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText("Pedro")).toBeInTheDocument();
        expect(screen.getByText("Juan")).toBeInTheDocument();
        // Sin tokens técnicos
        expect(screen.queryByText(/legacy_id/)).not.toBeInTheDocument();
        expect(screen.queryByText(/constraint/)).not.toBeInTheDocument();
    });

    it("muestra 'Parece el mismo paciente' cuando match_confidence es high", () => {
        renderPreview();
        expect(screen.getByText("Parece el mismo paciente.")).toBeInTheDocument();
    });

    it("muestra 'Mismo expediente, datos distintos' cuando uncertain", () => {
        renderPreview();
        expect(screen.getByText("Mismo expediente, datos distintos — revísalo.")).toBeInTheDocument();
    });

    it("el link 'Ver paciente' apunta con public_id y target _blank", () => {
        renderPreview();
        const links = screen.getAllByText("Ver paciente");
        expect(links).toHaveLength(2);
        // Primer link apunta a /pets/abc-123
        expect(links[0].href).toContain("/pets/abc-123");
        expect(links[0].target).toBe("_blank");
        expect(links[0].rel).toContain("noopener");
        expect(links[0].rel).toContain("noreferrer");
    });
});

describe("PreviewStep — consecuencias y CTA", () => {
    it("muestra la consecuencia antes de confirmar con conteos reales", () => {
        renderPreview();
        expect(screen.getByText(/Al continuar/)).toBeInTheDocument();
        expect(screen.getByText(/1 registro/)).toBeInTheDocument();
        expect(screen.getByText(/3 posibles duplicados se omitirán/)).toBeInTheDocument();
    });

    it("con registros importables muestra el botón de confirmar", () => {
        renderPreview({ canCommit: true });
        expect(screen.getByRole("button", { name: /confirmar importación/i })).toBeInTheDocument();
    });

    it("sin registros importables bloquea el CTA", () => {
        renderPreview({ result: RESULT_WITH_BLOCKING, canCommit: true });
        expect(screen.queryByRole("button", { name: /confirmar importación/i })).not.toBeInTheDocument();
        expect(screen.getByText(/Corrige los errores para poder importar/)).toBeInTheDocument();
    });

    it("sin permiso no muestra el botón e informa", () => {
        renderPreview({ canCommit: false });
        expect(screen.queryByRole("button", { name: /confirmar importación/i })).not.toBeInTheDocument();
        expect(screen.getByText(/no tienes permiso/i)).toBeInTheDocument();
    });
});

describe("PreviewStep — avisos", () => {
    it("muestra los avisos de datos opcionales", () => {
        renderPreview({ result: RESULT_WITH_BLOCKING });
        expect(screen.getByText(/Avisos/)).toBeInTheDocument();
        expect(screen.getByText(/se importará igual/)).toBeInTheDocument();
    });
});
