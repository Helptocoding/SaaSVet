import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MappingStep from "./MappingStep";

// Enfoque "revisar excepciones": las columnas reconocidas NO son protagonistas
// (van en una sección colapsada); las desconocidas sí (cards). El usuario solo
// corrige excepciones. Se prueba comportamiento observable.

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
const SUGGESTED = { "Dueño": "owner.name", "Mascota": "pet.name" }; // Fecha Alta → pendiente

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

describe("MappingStep — header de resumen", () => {
    it("muestra detectadas / listas / necesitan revisión", () => {
        renderStep();
        expect(screen.getByText("3 columnas detectadas")).toBeInTheDocument();
        expect(screen.getByText(/2 listas/)).toBeInTheDocument();
        expect(screen.getByText(/1 necesitan revisión/)).toBeInTheDocument();
    });
});

describe("MappingStep — reconocidas no son protagonistas", () => {
    it("las columnas reconocidas NO se muestran como cards por defecto", () => {
        renderStep();
        // Dueño/Mascota están en la sección colapsada → no visibles aún
        expect(screen.queryByText("Dueño")).not.toBeInTheDocument();
        expect(btn(/2 columnas listas/i)).toBeInTheDocument();
    });

    it("al abrir la sección se ven 'Columna → Campo' y 'Modificar'", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn(/2 columnas listas/i));
        expect(screen.getByText("Dueño")).toBeInTheDocument();
        expect(screen.getByText("Nombre del cliente")).toBeInTheDocument();
        expect(btn(/Modificar columna Dueño/i)).toBeInTheDocument();
    });
});

describe("MappingStep — excepciones (pendientes)", () => {
    it("muestra una card protagonista para la columna desconocida", () => {
        renderStep();
        expect(screen.getByText("No reconocimos «Fecha Alta»")).toBeInTheDocument();
        expect(screen.getByText("¿Qué contiene esta columna?")).toBeInTheDocument();
        expect(btn("Guardarlo como dato del cliente")).toBeInTheDocument();
        expect(btn("Guardarlo como dato de la mascota")).toBeInTheDocument();
        expect(btn("No importar esta columna")).toBeInTheDocument();
    });

    it("bloquea continuar mientras haya pendientes", () => {
        renderStep();
        expect(continueBtn()).toBeDisabled();
    });

    it("al resolver la pendiente: continuar se habilita y el header se actualiza", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn("Guardarlo como dato de la mascota"));
        expect(continueBtn()).toBeEnabled();
        expect(screen.getByText(/3 listas/)).toBeInTheDocument();
        expect(screen.queryByText(/necesitan revisión/)).not.toBeInTheDocument();
    });

    it("entrega el mapping con el sistema + la decisión extra", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await user.click(btn("Guardarlo como dato de la mascota"));
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Fecha Alta": "pet.extra",
        });
    });

    it("ofrece picker del sistema como opción secundaria", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn(/¿Es un campo del sistema/i));
        expect(screen.getByLabelText(/Buscar campo del sistema para Fecha Alta/i)).toBeInTheDocument();
    });
});

describe("MappingStep — modificar una reconocida", () => {
    it("no permite asignar el mismo campo del sistema a dos columnas", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn(/2 columnas listas/i));        // abre la sección
        await user.click(btn(/Modificar columna Mascota/i)); // edita Mascota
        // owner.name ya está en Dueño → su botón está deshabilitado en el picker
        expect(btn("Nombre del cliente")).toBeDisabled();
    });
});
