import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MappingStep from "./MappingStep";

// MappingStep conecta la interacción humana (elegir el campo destino por columna)
// con el contrato del importador: el padre recibe el mapping limpio en onContinue
// y "Continuar" se bloquea hasta que todos los campos OBLIGATORIOS estén asignados.
// Obligatorios = solo Nombre del cliente y Nombre de la mascota; especie/teléfono
// son recomendados (no bloquean). Se prueba comportamiento observable.

// field_catalog tal como lo entrega el backend: labels humanos + group + importance
// (required | recommended | optional). legacy_id se muestra SIEMPRE por su label,
// nunca como la cadena cruda "legacy_id".
const FIELD_CATALOG = [
    { key: "owner.name", label: "Nombre del cliente", group: "Cliente", importance: "required" },
    { key: "owner.phone", label: "Teléfono del cliente", group: "Cliente", importance: "recommended" },
    { key: "owner.legacy_id", label: "Nº de cliente anterior", group: "Cliente", importance: "optional" },
    { key: "pet.name", label: "Nombre de la mascota", group: "Mascota", importance: "required" },
    { key: "pet.species", label: "Especie", group: "Mascota", importance: "recommended" },
    { key: "pet.legacy_id", label: "Nº de expediente anterior", group: "Mascota", importance: "optional" },
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
    // "Expediente" intencionalmente sin sugerir → queda en "No importar columna"
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

const selectFor = (col) =>
    screen.getByRole("combobox", { name: new RegExp(`columna ${col}`, "i") });
const continueBtn = () => screen.getByRole("button", { name: /continuar/i });

describe("MappingStep — render y pre-fill", () => {
    it("una fila por columna del archivo, con su nombre visible", () => {
        renderStep();
        for (const col of SOURCE_COLUMNS) {
            expect(screen.getByText(col)).toBeInTheDocument();
        }
        expect(screen.getAllByRole("combobox")).toHaveLength(SOURCE_COLUMNS.length);
    });

    it("pre-llena cada select desde suggested_mapping", () => {
        renderStep();
        expect(selectFor("Dueño")).toHaveValue("owner.name");
        expect(selectFor("Teléfono")).toHaveValue("owner.phone");
        expect(selectFor("Paciente")).toHaveValue("pet.name");
        expect(selectFor("Tipo")).toHaveValue("pet.species");
        // columna no sugerida → "No importar columna" = valor vacío
        expect(selectFor("Expediente")).toHaveValue("");
    });

    it("usa labels humanos (sin prefijos técnicos 'Cliente · ')", () => {
        renderStep();
        expect(screen.getAllByText("Nombre del cliente").length).toBeGreaterThan(0);
        expect(screen.queryByText(/Cliente · /)).not.toBeInTheDocument();
    });

    it("muestra el label amistoso de legacy_id, nunca la cadena 'legacy_id'", () => {
        renderStep();
        expect(screen.getAllByText(/Nº de expediente anterior/).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/Nº de cliente anterior/).length).toBeGreaterThan(0);
        expect(screen.queryByText(/legacy_id/)).not.toBeInTheDocument();
    });

    it("ofrece 'No importar columna' como opción", () => {
        renderStep();
        expect(screen.getAllByText("No importar columna").length).toBeGreaterThan(0);
    });

    it("muestra el tipo (Obligatorio/Recomendado/Opcional) del campo elegido", () => {
        renderStep();
        // Dueño→owner.name (obligatorio), Teléfono→owner.phone (recomendado)
        expect(screen.getAllByText("Obligatorio").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Recomendado").length).toBeGreaterThan(0);
        // Expediente sin mapear → "No se importa"
        expect(screen.getAllByText("No se importa").length).toBeGreaterThan(0);
    });

    it("muestra valores de muestra de la columna", () => {
        renderStep();
        expect(screen.getByText(/Juan/)).toBeInTheDocument();
    });
});

describe("MappingStep — campos obligatorios", () => {
    it("con todos los obligatorios mapeados, 'Continuar' está habilitado", () => {
        renderStep();
        expect(continueBtn()).toBeEnabled();
    });

    it("si falta un obligatorio, 'Continuar' se bloquea y se nombra el faltante (por su label)", () => {
        // pet.name sin asignar → falta un obligatorio
        const partial = { ...SUGGESTED };
        delete partial["Paciente"];
        renderStep({ initialMapping: partial });

        expect(continueBtn()).toBeDisabled();
        const missingItems = screen.getAllByRole("listitem").map(li => li.textContent);
        expect(missingItems).toContain("Nombre de la mascota");
    });

    it("un campo SOLO recomendado sin asignar NO bloquea 'Continuar'", () => {
        // pet.species (recomendado) sin asignar → puede continuar igual
        const partial = { ...SUGGESTED };
        delete partial["Tipo"];
        renderStep({ initialMapping: partial });

        expect(continueBtn()).toBeEnabled();
        // y se sugiere (sin bloquear) asignar la especie
        expect(screen.getByText(/Te recomendamos también asignar/)).toHaveTextContent("Especie");
    });
});

describe("MappingStep — interacción (cambiar select)", () => {
    it("asignar el campo obligatorio faltante habilita 'Continuar'", async () => {
        const user = userEvent.setup();
        const partial = { ...SUGGESTED };
        delete partial["Paciente"];
        renderStep({ initialMapping: partial });

        expect(continueBtn()).toBeDisabled();
        await user.selectOptions(selectFor("Paciente"), "pet.name");
        expect(selectFor("Paciente")).toHaveValue("pet.name");
        expect(continueBtn()).toBeEnabled();
    });

    it("'Continuar' entrega al padre el mapping limpio (sin las columnas en 'No importar')", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();

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

    it("poner una columna en 'No importar columna' la excluye del mapping entregado", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();

        await user.selectOptions(selectFor("Teléfono"), ""); // No importar columna
        await user.click(continueBtn());

        const sent = onContinue.mock.calls[0][0];
        expect(sent).not.toHaveProperty("Teléfono");
        expect(sent["Dueño"]).toBe("owner.name");
    });
});
