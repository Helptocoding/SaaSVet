import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MappingStep from "./MappingStep";

// Rediseño UX (Fase D): UNA decisión por columna vía modal DestinationPicker, que
// es un ACORDEÓN de categorías (una abierta a la vez, sin buscador). Reconocidas →
// resumen colapsable compacto. Desconocidas → cards compactas (pendiente
// "Seleccionar destino" / resuelta "✓ … Cambiar"). Se prueba comportamiento
// observable (roles, texto, payload).

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
const SUGGESTED = { "Dueño": "owner.name", "Mascota": "pet.name" }; // Color fav → a revisar

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
const queryBtn = (name) => screen.queryByRole("button", { name });
const dialog = () => screen.getByRole("dialog");
const inDialog = (name) => within(dialog()).getByRole("button", { name });
const queryInDialog = (name) => within(dialog()).queryByRole("button", { name });

// Abre el modal de destino de "Color fav" (card pendiente).
async function openPicker(user) {
    await user.click(btn(/Seleccionar destino/i));
    return dialog();
}
// Despliega una categoría del acordeón (Cliente / Mascota / …).
async function expandSection(user, name) {
    await user.click(within(dialog()).getByRole("button", { name }));
}

describe("MappingStep — header + reconocidas compactas", () => {
    it("muestra detectadas / listas / necesitan revisión", () => {
        renderStep();
        expect(screen.getByText("3 columnas detectadas")).toBeInTheDocument();
        expect(screen.getByText(/2 listas/)).toBeInTheDocument();
        expect(screen.getByText(/1 necesitan revisión/)).toBeInTheDocument();
    });

    it("las reconocidas van en un resumen colapsable (no como cards)", async () => {
        const user = userEvent.setup();
        renderStep();
        expect(screen.queryByText("Dueño")).not.toBeInTheDocument();
        const toggle = btn(/2 columnas reconocidas automáticamente/i);
        expect(toggle).toBeInTheDocument();
        await user.click(toggle);
        expect(screen.getByText("Dueño")).toBeInTheDocument();
        expect(screen.getByText("Nombre del cliente")).toBeInTheDocument();
    });
});

describe("MappingStep — card de columna a revisar", () => {
    it("card compacta: título, ejemplos y un solo botón (sin opciones abiertas)", () => {
        renderStep();
        expect(screen.getByText("Color fav")).toBeInTheDocument();
        expect(screen.getByText(/Ejemplos:/)).toHaveTextContent("Rojo");
        expect(btn(/Seleccionar destino/i)).toBeInTheDocument();
        // Nada de opciones de destino visibles en la card.
        expect(queryBtn(/Conservar como información anterior/i)).not.toBeInTheDocument();
        expect(queryBtn("No importar esta columna")).not.toBeInTheDocument();
    });

    it("bloquea continuar hasta decidir la columna pendiente", async () => {
        const user = userEvent.setup();
        renderStep();
        expect(continueBtn()).toBeDisabled();
        await openPicker(user);
        await expandSection(user, "Datos del sistema anterior");
        await user.click(inDialog(/Conservar como información anterior de la mascota/i));
        expect(continueBtn()).toBeEnabled();
    });
});

describe("MappingStep — selector de destino (acordeón)", () => {
    it("abre modal con categorías colapsadas (opciones ocultas hasta desplegar)", async () => {
        const user = userEvent.setup();
        renderStep();
        await openPicker(user);
        // Headers de categoría presentes.
        expect(inDialog("Cliente")).toBeInTheDocument();
        expect(inDialog("Mascota")).toBeInTheDocument();
        expect(inDialog("Datos del sistema anterior")).toBeInTheDocument();
        expect(inDialog("No usar")).toBeInTheDocument();
        // Sin buscador y sin opciones abiertas.
        expect(screen.queryByLabelText("Buscar destino")).not.toBeInTheDocument();
        expect(queryInDialog("Especie")).not.toBeInTheDocument();
    });

    it("solo una categoría abierta a la vez (abrir otra cierra la anterior)", async () => {
        const user = userEvent.setup();
        renderStep();
        await openPicker(user);
        await expandSection(user, "Cliente");
        expect(inDialog(/Nombre del cliente/)).toBeInTheDocument();
        await expandSection(user, "Mascota");
        expect(queryInDialog(/Nombre del cliente/)).not.toBeInTheDocument(); // Cliente se cerró
        expect(inDialog("Especie")).toBeInTheDocument();
    });

    it("no permite el mismo campo del sistema en dos columnas", async () => {
        const user = userEvent.setup();
        renderStep();   // Dueño ya usa "Nombre del cliente"
        await openPicker(user);
        await expandSection(user, "Cliente");
        expect(inDialog(/Nombre del cliente/)).toBeDisabled();
    });

    it("elegir un campo del sistema deja la card resuelta + payload string", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await openPicker(user);
        await expandSection(user, "Mascota");
        await user.click(inDialog("Especie"));
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(screen.getByText(/Se importará como Especie/)).toBeInTheDocument();
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Color fav": "pet.species",
        });
    });
});

describe("MappingStep — histórico + reversibilidad + renombrar", () => {
    it("elegir histórico → card 'se conservará como…' + payload {target, label}", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await openPicker(user);
        await expandSection(user, "Datos del sistema anterior");
        await user.click(inDialog(/Conservar como información anterior de la mascota/i));
        expect(screen.getByText(/Se conservará como Información anterior de la mascota/)).toBeInTheDocument();
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Color fav": { target: "pet.extra", label: "Color fav" },
        });
    });

    it("la decisión nunca es irreversible: Cambiar reabre el modal", async () => {
        const user = userEvent.setup();
        renderStep();
        await openPicker(user);
        await expandSection(user, "Datos del sistema anterior");
        await user.click(inDialog(/Conservar como información anterior de la mascota/i));
        // reabrir y cambiar a no importar
        await user.click(btn(/Cambiar destino de Color fav/i));
        await expandSection(user, "No usar");
        await user.click(inDialog("No importar esta columna"));
        expect(screen.getByText("No se importará")).toBeInTheDocument();
        expect(continueBtn()).toBeEnabled();
    });

    it("renombra el nombre visible del dato histórico (no cambia la columna)", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await openPicker(user);
        await expandSection(user, "Datos del sistema anterior");
        await user.click(inDialog(/Conservar como información anterior de la mascota/i));
        await user.click(btn(/Renombrar Color fav/i));
        const input = screen.getByLabelText(/Nombre visible para Color fav/i);
        await user.clear(input);
        await user.type(input, "Color favorito");
        await user.click(continueBtn());
        expect(onContinue).toHaveBeenCalledWith({
            "Dueño": "owner.name",
            "Mascota": "pet.name",
            "Color fav": { target: "pet.extra", label: "Color favorito" },
        });
    });
});
