import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MappingStep from "./MappingStep";

// MappingStep conecta la interacción humana (elegir el campo destino por columna)
// con el contrato del importador: el padre recibe el mapping limpio en onContinue
// y "Continuar" se bloquea hasta que todos los campos obligatorios estén asignados.
// Se prueba comportamiento observable (selects, botón, texto), no estado interno.

// field_catalog tal como lo entrega el backend: labels amistosos + group + required.
// IMPORTANTE: legacy_id se muestra SIEMPRE por su label ("Nº de expediente
// anterior"), nunca como la cadena cruda "legacy_id".
const FIELD_CATALOG = [
    { key: "owner.name", label: "Cliente · Nombre", group: "Cliente", required: true },
    { key: "owner.phone", label: "Cliente · Teléfono", group: "Cliente", required: false },
    { key: "owner.legacy_id", label: "Cliente · Nº de cliente anterior", group: "Cliente", required: false },
    { key: "pet.name", label: "Mascota · Nombre", group: "Mascota", required: true },
    { key: "pet.species", label: "Mascota · Especie", group: "Mascota", required: true },
    { key: "pet.legacy_id", label: "Mascota · Nº de expediente anterior", group: "Mascota", required: false },
];

const SOURCE_COLUMNS = ["Dueño", "Teléfono", "Paciente", "Tipo", "Expediente"];

const SAMPLE_ROWS = [
    ["Juan", "8112345678", "Max", "Perro", "00231"],
    ["Ana", "8119998888", "Luna", "Gato", "00232"],
];

const SUGGESTED = {
    "Dueño": "owner.name",
    "Teléfono": "owner.phone",
    "Paciente": "pet.name",
    "Tipo": "pet.species",
    // "Expediente" intencionalmente sin sugerir → queda en (no importar)
};

function renderStep(props = {}) {
    const onContinue = vi.fn();
    render(
        <MappingStep
            sourceColumns={SOURCE_COLUMNS}
            sampleRows={SAMPLE_ROWS}
            fieldCatalog={FIELD_CATALOG}
            initialMapping={props.initialMapping ?? SUGGESTED}
            onContinue={onContinue}
            onBack={() => {}}
            {...props}
        />
    );
    return { onContinue };
}

// El <select> de una columna se localiza por su aria-label.
const selectFor = (col) =>
    screen.getByRole("combobox", { name: new RegExp(`columna ${col}`, "i") });
const continueBtn = () => screen.getByRole("button", { name: /continuar/i });

describe("MappingStep — render y pre-fill", () => {
    it("una fila por columna del archivo, con su nombre visible", () => {
        renderStep();
        for (const col of SOURCE_COLUMNS) {
            expect(screen.getByText(col)).toBeInTheDocument();
        }
        // 5 selects, uno por columna
        expect(screen.getAllByRole("combobox")).toHaveLength(SOURCE_COLUMNS.length);
    });

    it("pre-llena cada select desde suggested_mapping", () => {
        renderStep();
        expect(selectFor("Dueño")).toHaveValue("owner.name");
        expect(selectFor("Teléfono")).toHaveValue("owner.phone");
        expect(selectFor("Paciente")).toHaveValue("pet.name");
        expect(selectFor("Tipo")).toHaveValue("pet.species");
        // columna no sugerida → (no importar) = valor vacío
        expect(selectFor("Expediente")).toHaveValue("");
    });

    it("muestra el label amistoso de legacy_id, nunca la cadena 'legacy_id'", () => {
        renderStep();
        // Aparece como <option> en cada select → getAllByText (>=1 ocurrencia).
        expect(screen.getAllByText(/Nº de expediente anterior/).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/Nº de cliente anterior/).length).toBeGreaterThan(0);
        // Nunca se muestra la cadena cruda del campo interno.
        expect(screen.queryByText(/legacy_id/)).not.toBeInTheDocument();
    });

    it("muestra valores de muestra de la columna", () => {
        renderStep();
        // primeros valores de la columna Dueño
        expect(screen.getByText(/Juan/)).toBeInTheDocument();
    });
});

describe("MappingStep — campos obligatorios", () => {
    it("con todos los obligatorios mapeados, 'Continuar' está habilitado", () => {
        renderStep();
        expect(continueBtn()).toBeEnabled();
    });

    it("si falta un obligatorio, 'Continuar' se bloquea y se nombra el faltante (por su label)", () => {
        // pet.species sin asignar → falta un obligatorio
        const partial = { ...SUGGESTED };
        delete partial["Tipo"];
        renderStep({ initialMapping: partial });

        expect(continueBtn()).toBeDisabled();
        // El faltante se nombra por su label en la lista de obligatorios (<li>).
        const missingItems = screen.getAllByRole("listitem").map(li => li.textContent);
        expect(missingItems).toContain("Mascota · Especie");
    });
});

describe("MappingStep — interacción (cambiar select)", () => {
    it("asignar el campo faltante habilita 'Continuar'", async () => {
        const user = userEvent.setup();
        const partial = { ...SUGGESTED };
        delete partial["Tipo"];
        renderStep({ initialMapping: partial });

        expect(continueBtn()).toBeDisabled();
        await user.selectOptions(selectFor("Tipo"), "pet.species");
        expect(selectFor("Tipo")).toHaveValue("pet.species");
        expect(continueBtn()).toBeEnabled();
    });

    it("'Continuar' entrega al padre el mapping limpio (sin las columnas en 'no importar')", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();

        // mapear la columna Expediente al nº de expediente anterior
        await user.selectOptions(selectFor("Expediente"), "pet.legacy_id");
        await user.click(continueBtn());

        expect(onContinue).toHaveBeenCalledTimes(1);
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Teléfono": "owner.phone",
            "Paciente": "pet.name",
            "Tipo": "pet.species",
            "Expediente": "pet.legacy_id",
        });
    });

    it("poner una columna en (no importar) la excluye del mapping entregado", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();

        await user.selectOptions(selectFor("Teléfono"), ""); // (no importar)
        await user.click(continueBtn());

        const sent = onContinue.mock.calls[0][0];
        expect(sent).not.toHaveProperty("Teléfono");
        expect(sent["Dueño"]).toBe("owner.name");
    });
});
