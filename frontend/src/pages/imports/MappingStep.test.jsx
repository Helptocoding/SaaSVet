import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MappingStep from "./MappingStep";

// Rediseño Fase D: columnas reconocidas se confirman; las desconocidas piden una
// decisión humana (cliente / mascota / no importar) y BLOQUEAN continuar hasta
// decidir. Picker compacto con búsqueda (no <select> gigante). Se prueba el
// comportamiento observable (texto, botones, callback).

const FIELD_CATALOG = [
    { key: "owner.name", label: "Nombre del cliente", group: "Cliente", importance: "required" },
    { key: "owner.phone", label: "Teléfono del cliente", group: "Cliente", importance: "recommended" },
    { key: "owner.extra", label: "Dato del cliente", group: "Cliente", importance: "optional", is_extra: true },
    { key: "pet.name", label: "Nombre de la mascota", group: "Mascota", importance: "required" },
    { key: "pet.species", label: "Especie", group: "Mascota", importance: "recommended" },
    { key: "pet.extra", label: "Dato de la mascota", group: "Mascota", importance: "optional", is_extra: true },
];

const SOURCE_COLUMNS = ["Dueño", "Mascota", "Fecha Alta"];
const SAMPLE_ROWS = [["Juan", "Max", "2018-01-01"]];
// Dueño y Mascota reconocidas; "Fecha Alta" sin sugerencia → pendiente.
const SUGGESTED = { "Dueño": "owner.name", "Mascota": "pet.name" };

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

const continueBtn = () => screen.getByRole("button", { name: /continuar/i });
const btn = (name) => screen.getByRole("button", { name });

describe("MappingStep — reconocidas vs por decidir", () => {
    it("muestra una tarjeta por columna; las reconocidas se confirman", () => {
        renderStep();
        // "Dueño"/"Fecha Alta" son únicos; "Mascota" colisiona con el nombre de
        // grupo del picker → se valida vía las etiquetas confirmadas «...».
        expect(screen.getByText("Dueño")).toBeInTheDocument();
        expect(screen.getByText("Fecha Alta")).toBeInTheDocument();
        expect(screen.getAllByText(/Se importará como/)).toHaveLength(2);
        expect(screen.getByText("«Nombre del cliente»")).toBeInTheDocument();
        expect(screen.getByText("«Nombre de la mascota»")).toBeInTheDocument();
    });

    it("una columna desconocida pregunta qué hacer, con opciones humanas", () => {
        renderStep();
        expect(screen.getByText("¿Qué hacemos con «Fecha Alta»?")).toBeInTheDocument();
        expect(btn("Guardar como dato del cliente")).toBeInTheDocument();
        expect(btn("Guardar como dato de la mascota")).toBeInTheDocument();
        expect(btn("No necesito esta columna")).toBeInTheDocument();
    });

    it("bloquea continuar mientras haya columnas por decidir", () => {
        renderStep();
        expect(continueBtn()).toBeDisabled();
        expect(screen.getByText(/Elige qué hacer con cada una/)).toBeInTheDocument();
    });
});

describe("MappingStep — decidir columnas", () => {
    it("al decidir la columna pendiente se confirma y habilita continuar", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn("Guardar como dato de la mascota"));
        expect(screen.getByText("Se guardará como dato de la mascota")).toBeInTheDocument();
        expect(continueBtn()).toBeEnabled();
    });

    it("entrega al padre el mapping con campos del sistema + extra", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await user.click(btn("Guardar como dato de la mascota"));   // Fecha Alta → pet.extra
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Fecha Alta": "pet.extra",
        });
    });

    it("'No necesito esta columna' la marca como no importada", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await user.click(btn("No necesito esta columna"));
        expect(screen.getByText("No se importará")).toBeInTheDocument();
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Fecha Alta": "",
        });
    });
});

describe("MappingStep — picker (cambiar)", () => {
    it("no permite asignar el mismo campo del sistema a dos columnas", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn("No necesito esta columna"));        // colapsa Fecha Alta
        await user.click(btn(/Cambiar columna Mascota/i));         // abre picker de Mascota
        // owner.name ya está en "Dueño" → su botón está deshabilitado aquí
        expect(btn("Nombre del cliente")).toBeDisabled();
    });

    it("el buscador filtra los campos del sistema", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn("No necesito esta columna"));         // colapsa Fecha Alta
        await user.click(btn(/Cambiar columna Dueño/i));           // abre picker de Dueño
        await user.type(screen.getByLabelText(/Buscar campo del sistema para Dueño/i), "tel");
        expect(btn("Teléfono del cliente")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Especie" })).not.toBeInTheDocument();
    });

    it("bloquea continuar si falta un campo obligatorio y lo nombra", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn("No necesito esta columna"));         // colapsa Fecha Alta
        await user.click(btn(/Cambiar columna Dueño/i));           // abre picker de Dueño
        await user.click(btn("No necesito esta columna"));         // Dueño → no importar (quita owner.name)
        expect(continueBtn()).toBeDisabled();
        const items = screen.getAllByRole("listitem").map(li => li.textContent);
        expect(items).toContain("Nombre del cliente");
    });
});
