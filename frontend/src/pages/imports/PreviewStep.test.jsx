import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import PreviewStep from "./PreviewStep";

// PreviewStep — agrupa conflictos por match_confidence:
//   high     → "Posibles duplicados"
//   uncertain → "Conflictos de expediente"
// Lenguaje humano, sin tokens técnicos (legacy_id, constraint).

const FIELD_CATALOG = [
    { key: "owner.name", label: "Nombre del cliente", group: "Cliente", importance: "required" },
    { key: "owner.phone", label: "Teléfono del cliente", group: "Cliente", importance: "recommended" },
    { key: "pet.name", label: "Nombre de la mascota", group: "Mascota", importance: "required" },
    { key: "pet.species", label: "Especie", group: "Mascota", importance: "recommended" },
    { key: "pet.legacy_id", label: "Nº de expediente anterior", group: "Mascota", importance: "optional" },
];

// Un conflicto high (mismos nombres) + uno uncertain (datos distintos)
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

// Solo uncertain — para probar el grupo de conflictos de expediente aislado
const RESULT_UNCERTAIN_ONLY = {
    created_owners: 0,
    reused_owners: 0,
    created_pets: 0,
    skipped_duplicates: 0,
    skipped_conflicts: 2,
    blocking_rows: 0,
    errors: [],
    blocking: [],
    conflicts: [
        {
            row: 3,
            type: "duplicate_legacy_id",
            severity: "conflict",
            scope: "pet",
            match_confidence: "uncertain",
            message: "Ya existe una mascota con este expediente.",
            incoming: { pet_name: "Rocky", owner_name: "Roberto Gutiérrez", legacy_id: "1" },
            existing: { pet_name: "Bella", owner_name: "Ana Vázquez", public_id: "xyz-789" },
        },
        {
            row: 7,
            type: "duplicate_legacy_id",
            severity: "conflict",
            scope: "pet",
            match_confidence: "uncertain",
            message: "Ya existe una mascota con este expediente.",
            incoming: { pet_name: "Rex", owner_name: "Carlos", legacy_id: "5" },
            existing: { pet_name: "Toby", owner_name: "María", public_id: "uvw-456" },
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
    blocking_rows: 5,
    errors: [
        { row: 2, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 7, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 12, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 5, field: "owner.phone", message: "El teléfono debe tener 10 dígitos." },
        { row: 9, field: "owner.phone", message: "El teléfono debe tener 10 dígitos." },
    ],
    blocking: [
        { row: 2, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 7, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 12, field: "pet.name", message: "El nombre de la mascota es requerido." },
        { row: 5, field: "owner.phone", message: "El teléfono debe tener 10 dígitos." },
        { row: 9, field: "owner.phone", message: "El teléfono debe tener 10 dígitos." },
    ],
    conflicts: [],
    warnings: [],
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
        expect(screen.getByText(/1 paciente listo/)).toBeInTheDocument();
        expect(screen.getByText(/2 omitidos/)).toBeInTheDocument();
        expect(screen.getByText(/3 en revisión/)).toBeInTheDocument();
    });

    it("con bloqueantes muestra 'Necesitan corrección'", () => {
        renderPreview({ result: RESULT_WITH_BLOCKING });
        expect(screen.getByText(/Necesitan corrección \(5\)/)).toBeInTheDocument();
        expect(screen.getByText(/5 necesitan corrección/)).toBeInTheDocument();
    });
});

describe("PreviewStep — Posibles duplicados (match_confidence = high)", () => {
    it("high aparece en el grupo 'Posibles duplicados'", () => {
        renderPreview();
        expect(screen.getByText(/Posibles duplicados \(1\)/)).toBeInTheDocument();
    });

    it("muestra el intro clásico de re-importación", () => {
        renderPreview();
        expect(screen.getByText(/Puede que estos pacientes ya estén registrados/)).toBeInTheDocument();
    });

    it("high muestra 'Parece el mismo paciente'", () => {
        renderPreview();
        expect(screen.getByText("Parece el mismo paciente.")).toBeInTheDocument();
    });
});

describe("PreviewStep — Conflictos de expediente (match_confidence = uncertain)", () => {
    it("uncertain aparece en grupo separado 'Conflictos de expediente'", () => {
        renderPreview();
        expect(screen.getByText(/Conflictos de expediente \(1\)/)).toBeInTheDocument();
    });

    it("muestra el intro de múltiples orígenes posibles", () => {
        renderPreview();
        // El intro y el hint de cada card contienen la misma frase base.
        // Verificamos que ambas apariciones existen.
        const matches = screen.getAllByText(/El número de expediente ya pertenece a otro paciente/);
        expect(matches.length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText(/estás importando información de otra clínica/)).toBeInTheDocument();
        expect(screen.getByText(/el sistema anterior reinició numeraciones/)).toBeInTheDocument();
    });

    it("NO muestra como posible duplicado el uncertain", () => {
        renderPreview({ result: RESULT_UNCERTAIN_ONLY });
        expect(screen.queryByText(/Posibles duplicados/)).not.toBeInTheDocument();
        expect(screen.getByText(/Conflictos de expediente \(2\)/)).toBeInTheDocument();
    });

    it("muestra 'El número de expediente ya pertenece a otro paciente' en uncertain", () => {
        renderPreview({ result: RESULT_UNCERTAIN_ONLY });
        expect(screen.getAllByText("El número de expediente ya pertenece a otro paciente.").length).toBeGreaterThanOrEqual(1);
    });
});

describe("PreviewStep — nombres y comparación", () => {
    it("muestra nombres humanos en la comparación lado a lado", () => {
        renderPreview();
        expect(screen.getAllByText("Luna").length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText("Rocky")).toBeInTheDocument();
        expect(screen.getByText("Max")).toBeInTheDocument();
        expect(screen.getAllByText("Ana López").length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText("Pedro")).toBeInTheDocument();
        expect(screen.getByText("Juan")).toBeInTheDocument();
        expect(screen.queryByText(/legacy_id/)).not.toBeInTheDocument();
        expect(screen.queryByText(/constraint/)).not.toBeInTheDocument();
    });

    it("'Ver paciente' usa public_id con target _blank", () => {
        renderPreview();
        const links = screen.getAllByText("Ver paciente");
        expect(links).toHaveLength(2);
        expect(links[0].href).toContain("/pets/abc-123");
        expect(links[0].target).toBe("_blank");
        expect(links[0].rel).toContain("noopener");
        expect(links[0].rel).toContain("noreferrer");
    });
});

describe("PreviewStep — consecuencias y CTA", () => {
    it("con registros importables y sin blocking muestra el botón de confirmar", () => {
        renderPreview({ canCommit: true });
        expect(screen.getByRole("button", { name: /confirmar importación/i })).toBeInTheDocument();
    });

    it("con blocking errors oculta el botón y muestra mensaje de corrección", () => {
        renderPreview({ result: RESULT_WITH_BLOCKING, canCommit: true });
        expect(screen.queryByRole("button", { name: /confirmar importación/i })).not.toBeInTheDocument();
        expect(screen.getByText(/Corrige los 5 errores para poder importar/)).toBeInTheDocument();
    });

    it("sin blocking ni registros muestra 'No hay registros nuevos'", () => {
        const empty = { ...RESULT_WITH_BLOCKING, blocking_rows: 0, blocking: [], errors: [] };
        renderPreview({ result: empty, canCommit: true });
        expect(screen.queryByRole("button", { name: /confirmar importación/i })).not.toBeInTheDocument();
        expect(screen.getByText(/No hay registros nuevos para importar/)).toBeInTheDocument();
    });

    it("sin permiso no muestra el botón e informa", () => {
        renderPreview({ canCommit: false });
        expect(screen.queryByRole("button", { name: /confirmar importación/i })).not.toBeInTheDocument();
        expect(screen.getByText(/no tienes permiso/i)).toBeInTheDocument();
    });
});
