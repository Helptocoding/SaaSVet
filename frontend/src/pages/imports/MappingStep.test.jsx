import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MappingStep from "./MappingStep";

// Iteración compacta (tabla rápida): las columnas a clasificar son un grid de
// tarjetas con selector Cliente/Mascota/No importar SIEMPRE visible y cambiable +
// renombrar el dato; las reconocidas van en un resumen colapsable. Se prueba
// comportamiento observable.

const FIELD_CATALOG = [
    { key: "owner.name", label: "Nombre del cliente", group: "Cliente", importance: "required" },
    { key: "owner.phone", label: "Teléfono del cliente", group: "Cliente", importance: "recommended" },
    { key: "owner.extra", label: "Dato del cliente", group: "Cliente", importance: "optional", is_extra: true },
    { key: "pet.name", label: "Nombre de la mascota", group: "Mascota", importance: "required" },
    { key: "pet.species", label: "Especie", group: "Mascota", importance: "recommended" },
    { key: "pet.extra", label: "Dato de la mascota", group: "Mascota", importance: "optional", is_extra: true },
];

const SOURCE_COLUMNS = ["Dueño", "Mascota", "Color fav"];
const SAMPLE_ROWS = [["Juan", "Max", "Rojo"]];
const SUGGESTED = { "Dueño": "owner.name", "Mascota": "pet.name" }; // Color fav → excepción

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

describe("MappingStep — header + reconocidas compactas", () => {
    it("muestra detectadas / reconocidas / por revisar", () => {
        renderStep();
        expect(screen.getByText("3 columnas detectadas")).toBeInTheDocument();
        expect(screen.getByText(/2 reconocidas/)).toBeInTheDocument();
        expect(screen.getByText(/1 por revisar/)).toBeInTheDocument();
    });

    it("las reconocidas van en un resumen colapsable, no como cards", () => {
        renderStep();
        expect(screen.queryByText("Dueño")).not.toBeInTheDocument();
        expect(btn(/Reconocidas automáticamente \(2\)/i)).toBeInTheDocument();
    });
});

describe("MappingStep — tarjeta de excepción", () => {
    it("muestra label, ejemplos y selector de 3 opciones", () => {
        renderStep();
        expect(screen.getByText("Color fav")).toBeInTheDocument();
        expect(screen.getByText(/Ejemplos:/)).toHaveTextContent("Rojo");
        expect(btn("Cliente")).toBeInTheDocument();
        expect(btn("Mascota")).toBeInTheDocument();
        expect(btn("No importar")).toBeInTheDocument();
    });

    it("el selector es cambiable y nunca se oculta", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn("Cliente"));
        expect(btn("Cliente")).toHaveAttribute("aria-pressed", "true");
        // cambiar de opinión: ahora Mascota
        await user.click(btn("Mascota"));
        expect(btn("Mascota")).toHaveAttribute("aria-pressed", "true");
        expect(btn("Cliente")).toHaveAttribute("aria-pressed", "false");
        // las 3 opciones siguen visibles
        expect(btn("No importar")).toBeInTheDocument();
    });

    it("bloquea continuar hasta decidir la excepción", async () => {
        const user = userEvent.setup();
        renderStep();
        expect(continueBtn()).toBeDisabled();
        await user.click(btn("Mascota"));
        expect(continueBtn()).toBeEnabled();
    });

    it("entrega el mapping con {target, label} para el dato extra", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await user.click(btn("Mascota"));
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Color fav": { target: "pet.extra", label: "Color fav" },
        });
    });
});

describe("MappingStep — renombrar el dato", () => {
    it("permite editar el label visible y lo envía en el payload", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await user.click(btn(/Renombrar Color fav/i));
        const input = screen.getByLabelText(/Nombre del dato para Color fav/i);
        await user.clear(input);
        await user.type(input, "Color favorito");
        await user.click(btn("Mascota"));
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Color fav": { target: "pet.extra", label: "Color favorito" },
        });
    });
});

describe("MappingStep — modificar una reconocida", () => {
    it("no permite asignar el mismo campo del sistema a dos columnas", async () => {
        const user = userEvent.setup();
        renderStep();
        await user.click(btn(/Reconocidas automáticamente \(2\)/i));
        await user.click(btn(/Modificar columna Mascota/i));
        expect(btn("Nombre del cliente")).toBeDisabled();
    });
});
