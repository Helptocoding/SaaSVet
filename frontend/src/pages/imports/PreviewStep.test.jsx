import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import PreviewStep from "./PreviewStep";

// PreviewStep — Vista previa humana, no técnica.
// - SE CREARÁN: preview table + warning notice
// - ReviewPanel: solo errores bloqueantes
// - NO SE IMPORTARÁN: unificado con motivos humanos
//   - "Ya estaban registrados" (skipped + high-confidence)
//   - "Mismo expediente con datos diferentes" (uncertain)

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
    skipped_conflicts: 2,
    conflicts_high: 1,
    conflicts_uncertain: 1,
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
    conflicts_high: 0,
    conflicts_uncertain: 2,
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
    conflicts_high: 0,
    conflicts_uncertain: 0,
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
    conflicts_high: 0,
    conflicts_uncertain: 0,
    blocking_rows: 0,
    errors: [],
    blocking: [],
    conflicts: [],
    warnings: [],
};

const RESULT_WITH_PREVIEW = {
    created_owners: 1500,
    reused_owners: 0,
    created_pets: 1500,
    skipped_duplicates: 10,
    skipped_conflicts: 5,
    conflicts_high: 5,
    conflicts_uncertain: 0,
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
    ],
    warnings: [
        { row: 3, field: "pet.species", message: "Mascota sin especie — se importará como pendiente." },
    ],
    preview: [
        { row: 1, pet_name: "Bella", owner_name: "Ana López", pet_species: "canino", owner_phone: "8181234567", pet_breed: "", pet_sex: "", pet_birth_date: "", pet_color: "", pet_legacy_id: "" },
        { row: 2, pet_name: "Rocky", owner_name: "Luis Pérez", pet_species: "felino", owner_phone: "", pet_breed: "", pet_sex: "", pet_birth_date: "", pet_color: "", pet_legacy_id: "" },
    ],
    preview_total: 1500,
    skipped: [
        { row: 4, pet_name: "Max", owner_name: "Juan Pérez", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
    ],
    skipped_total: 10,
};

const RESULT_WITH_SKIPPED_GAP = {
    created_owners: 0,
    reused_owners: 0,
    created_pets: 0,
    skipped_duplicates: 1500,
    skipped_conflicts: 0,
    conflicts_high: 0,
    conflicts_uncertain: 0,
    blocking_rows: 0,
    errors: [],
    blocking: [],
    conflicts: [],
    warnings: [],
    skipped: [
        { row: 1, pet_name: "Thor", owner_name: "Fernando Ruiz", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 2, pet_name: "Thor", owner_name: "Fernando Hernández", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 3, pet_name: "Rocky", owner_name: "Daniel Rodríguez", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 4, pet_name: "Toby", owner_name: "Gabriela Ramírez", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 5, pet_name: "Max", owner_name: "Juan Ramírez", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 6, pet_name: "Kira", owner_name: "Alejandro Pérez", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 7, pet_name: "Max", owner_name: "Jorge López", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 8, pet_name: "Toby", owner_name: "Daniel Rodríguez", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 9, pet_name: "Luna", owner_name: "Verónica Flores", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
        { row: 10, pet_name: "Maya", owner_name: "Laura Hernández", pet_species: "canino", reason: "duplicate", message: "Ya existe un paciente con el mismo nombre para este cliente." },
    ],
    skipped_total: 1500,
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
    it("muestra mascotas que se crearán, duplicados omitidos, necesitan revisión", () => {
        renderPreview();
        expect(screen.getByText(/Se crearán 1 mascota/)).toBeInTheDocument();
        expect(screen.getByText(/2 omitidos/)).toBeInTheDocument();
        expect(screen.getByText(/2 en revisión/)).toBeInTheDocument();
    });

    it("con bloqueantes muestra sidebar y pill de corrección", () => {
        renderPreview({ result: RESULT_WITH_BLOCKING });
        // El sidebar izquierdo tiene el título "Necesitan corrección"
        expect(screen.getByText("Necesitan corrección")).toBeInTheDocument();
        // El pill de estado muestra "5 necesitan corrección"
        expect(screen.getByText(/5 necesitan corrección/)).toBeInTheDocument();
    });
});

describe("PreviewStep — No se importarán: Ya estaban registrados", () => {
    it("high-confidence aparece agrupado como 'Ya estaban registrados' con total real", () => {
        renderPreview();
        // RESULT_WITH_CONFLICTS: skipped_total no definido → cae a skipped_duplicates=2, + highConfidence=1 = 3
        expect(screen.getByText(/Ya estaban registrados \(3\)/)).toBeInTheDocument();
    });

    it("el intro general de NO SE IMPORTARÁN es tranquilizador", () => {
        renderPreview();
        expect(screen.getByText(/No es un error/)).toBeInTheDocument();
    });

    it("high muestra 'Parece el mismo paciente' en la card", () => {
        renderPreview();
        expect(screen.getByText("Parece el mismo paciente.")).toBeInTheDocument();
    });
});

describe("PreviewStep — No se importarán: Mismo expediente con datos diferentes", () => {
    it("uncertain aparece como 'Mismo expediente con datos diferentes'", () => {
        renderPreview();
        expect(screen.getByText(/Mismo expediente con datos diferentes \(1\)/)).toBeInTheDocument();
    });

    it("muestra descripción sobre múltiples orígenes posibles", () => {
        renderPreview();
        expect(screen.getByText(/importas información de otra clínica/)).toBeInTheDocument();
        expect(screen.getByText(/reinició numeraciones/)).toBeInTheDocument();
    });

    it("solo uncertain: no muestra 'Ya estaban registrados'", () => {
        renderPreview({ result: RESULT_UNCERTAIN_ONLY });
        expect(screen.queryByText(/Ya estaban registrados/)).not.toBeInTheDocument();
        expect(screen.getByText(/Mismo expediente con datos diferentes \(2\)/)).toBeInTheDocument();
    });

    it("muestra el mensaje de conflicto en la card", () => {
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

describe("PreviewStep — SE CREARÁN (preview table)", () => {
    it("muestra tabla con columnas Mascota, Cliente, Especie, Teléfono", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText("SE CREARÁN")).toBeInTheDocument();
        expect(screen.getByText("Mascota")).toBeInTheDocument();
        expect(screen.getByText("Cliente")).toBeInTheDocument();
        const speciesHeaders = screen.getAllByText("Especie");
        expect(speciesHeaders.length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("Teléfono")).toBeInTheDocument();
    });

    it("muestra los registros del preview en la tabla", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText("Bella")).toBeInTheDocument();
        const anaMatches = screen.getAllByText("Ana López");
        expect(anaMatches.length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("Rocky")).toBeInTheDocument();
        expect(screen.getByText("Luis Pérez")).toBeInTheDocument();
    });

    it("muestra 'Mostrando N de M' cuando hay más registros que preview", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText(/Mostrando 2 de 1500/)).toBeInTheDocument();
    });

    it("no muestra 'Mostrando N de M' cuando el total cabe en el preview", () => {
        const small = {
            ...RESULT_CLEAN,
            created_pets: 2,
            created_owners: 2,
            preview: [
                { row: 1, pet_name: "Bella", owner_name: "Ana López", pet_species: "canino", owner_phone: "8181234567", pet_breed: "", pet_sex: "", pet_birth_date: "", pet_color: "", pet_legacy_id: "" },
                { row: 2, pet_name: "Rocky", owner_name: "Luis", pet_species: "felino", owner_phone: "", pet_breed: "", pet_sex: "", pet_birth_date: "", pet_color: "", pet_legacy_id: "" },
            ],
            preview_total: 2,
        };
        renderPreview({ result: small, canCommit: true });
        expect(screen.getByText("SE CREARÁN")).toBeInTheDocument();
        expect(screen.queryByText(/Mostrando/)).not.toBeInTheDocument();
    });

    it("celdas vacías muestran guion (—)", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        const dashElements = screen.getAllByText("—");
        expect(dashElements.length).toBeGreaterThanOrEqual(1);
    });

    it("no muestra la tabla cuando no hay preview", () => {
        renderPreview({ result: RESULT_CLEAN, canCommit: true });
        expect(screen.queryByText("SE CREARÁN")).not.toBeInTheDocument();
    });

    it("muestra el total de mascotas en el encabezado", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        const mascotaMatches = screen.getAllByText(/1500\s+mascotas/);
        expect(mascotaMatches.length).toBeGreaterThanOrEqual(1);
    });
});

describe("PreviewStep — NO SE IMPORTARÁN (unificado)", () => {
    it("muestra sección unificada con el total combinado", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText(/No se importarán \(15\)/)).toBeInTheDocument();
    });

    it("muestra 'Ya estaban registrados' con el total real, no la muestra", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        // skipped_total=10 (dups) + conflicts_high=5 (agregado) = 15 — usa agregados,
        // no length de la muestra (que solo trae 1 conflicto high).
        expect(screen.getByText(/Ya estaban registrados \(15\)/)).toBeInTheDocument();
    });

    it("muestra el nombre de la mascota y cliente omitidos (skipped)", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText("Max")).toBeInTheDocument();
        expect(screen.getByText("Juan Pérez")).toBeInTheDocument();
    });

    it("muestra el motivo del omitido por duplicado", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText(/Ya existe un paciente con el mismo nombre/)).toBeInTheDocument();
    });

    it("no muestra sección cuando no hay omitidos ni conflictos", () => {
        renderPreview({ result: RESULT_CLEAN, canCommit: true });
        expect(screen.queryByText(/No se importarán/)).not.toBeInTheDocument();
    });

    it("muestra 'Mostrando N de M' cuando la muestra no cubre el total", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        // skippedTotal=10, skipped.length=1 → gap
        expect(screen.getByText(/Mostrando 1 de 10/)).toBeInTheDocument();
    });

    it("gap grande: skippedTotal=1500 con 10 samples muestra 1500 en contador y 10 de 1500", () => {
        renderPreview({ result: RESULT_WITH_SKIPPED_GAP, canCommit: true });
        // Contador usa el total real, no la muestra
        expect(screen.getByText(/Ya estaban registrados \(1500\)/)).toBeInTheDocument();
        // Indicador de muestra
        expect(screen.getByText(/Mostrando 10 de 1500/)).toBeInTheDocument();
        // El toggle de la sección también usa el total real
        expect(screen.getByText(/No se importarán \(1500\)/)).toBeInTheDocument();
    });
});

describe("PreviewStep — integración", () => {
    it("muestra SE CREARÁN y NO SE IMPORTARÁN simultáneamente", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText("SE CREARÁN")).toBeInTheDocument();
        expect(screen.getByText(/No se importarán/)).toBeInTheDocument();
    });

    it("warnings aparecen dentro de SE CREARÁN como aviso colapsable", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText(/1 registro se importará con algunos datos faltantes/)).toBeInTheDocument();
    });

    it("el aviso de warnings muestra 'ver detalle'", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText(/ver detalle/)).toBeInTheDocument();
    });

    it("barra de estado mantiene el pill de datos incompletos", () => {
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText(/1 con datos incompletos/)).toBeInTheDocument();
    });
});

// Extrae el número de un encabezado tipo "Texto (N)".
const countIn = (re) => {
    const el = screen.getByText(re);
    const m = el.textContent.match(/\((\d+)\)/);
    return m ? Number(m[1]) : null;
};

describe("PreviewStep — los números siempre cuadran", () => {
    it("mixto: padre 'No se importarán' == suma de los hijos visibles", () => {
        renderPreview({ result: RESULT_WITH_CONFLICTS });
        const parent = countIn(/No se importarán \(\d+\)/);
        const registrados = countIn(/Ya estaban registrados \(\d+\)/);
        const expediente = countIn(/Mismo expediente con datos diferentes \(\d+\)/);
        expect(registrados + expediente).toBe(parent); // registrados(3=2dup+1high) + expediente(1) === "No se importarán"(4)
    });

    it("conflictos muestreados (agregado > muestra): el total no se rompe", () => {
        // RESULT_WITH_PREVIEW: skipped_conflicts=5 pero el array trae 1 conflicto.
        // Padre=15, "Ya estaban"=15 (10 dups + 5 high), sin bloque uncertain (0).
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(countIn(/No se importarán \(\d+\)/)).toBe(15);
        expect(countIn(/Ya estaban registrados \(\d+\)/)).toBe(15);
        expect(screen.queryByText(/Mismo expediente con datos diferentes/)).not.toBeInTheDocument();
    });

    it("solo uncertain: padre == hijo uncertain (sin bloque 'Ya estaban')", () => {
        renderPreview({ result: RESULT_UNCERTAIN_ONLY });
        expect(countIn(/Mismo expediente con datos diferentes \(\d+\)/))
            .toBe(countIn(/No se importarán \(\d+\)/)); // 2 === 2
        expect(screen.queryByText(/Ya estaban registrados/)).not.toBeInTheDocument();
    });
});

describe("PreviewStep — caps (muestra < total)", () => {
    it("conflictos high muestreados: indicador 'Mostrando N de M'", () => {
        // conflicts_high=5 pero el array trae 1 high → indicador de muestra.
        renderPreview({ result: RESULT_WITH_PREVIEW, canCommit: true });
        expect(screen.getByText(/Mostrando 1 de 5/)).toBeInTheDocument();
    });

    it("preview en el tope exacto (20) con total mayor: 'Mostrando 20 de 25'", () => {
        const rows = Array.from({ length: 20 }, (_, i) => ({
            row: i + 1, pet_name: `Pet${i + 1}`, owner_name: `Owner${i + 1}`,
            pet_species: "canino", owner_phone: "", pet_breed: "", pet_sex: "",
            pet_birth_date: "", pet_color: "", pet_legacy_id: "",
        }));
        const capped = {
            ...RESULT_CLEAN, created_pets: 25, created_owners: 25,
            preview: rows, preview_total: 25,
        };
        renderPreview({ result: capped, canCommit: true });
        expect(screen.getByText(/Mostrando 20 de 25/)).toBeInTheDocument();
    });
});

describe("PreviewStep — regresión: 0 explícito no se enmascara", () => {
    it("preview_total=0 se respeta (no cae a created_pets)", () => {
        // Drift de contrato: created_pets=5 pero preview_total=0 explícito. El
        // header de SE CREARÁN debe mostrar 0, no 5 (antes `|| createdPets` lo tapaba).
        const drift = {
            ...RESULT_CLEAN, created_pets: 5, created_owners: 5,
            preview: [{ row: 1, pet_name: "Bella", owner_name: "Ana", pet_species: "canino", owner_phone: "", pet_breed: "", pet_sex: "", pet_birth_date: "", pet_color: "", pet_legacy_id: "" }],
            preview_total: 0,
        };
        renderPreview({ result: drift, canCommit: true });
        expect(screen.getByText(/\(0 mascotas\)/)).toBeInTheDocument();
        expect(screen.queryByText(/\(5 mascotas\)/)).not.toBeInTheDocument();
    });
});
