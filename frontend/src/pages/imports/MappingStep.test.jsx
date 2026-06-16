import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MappingStep from "./MappingStep";

// Rediseño UX (Fase D): UNA decisión por columna vía modal DestinationPicker.
// Reconocidas → resumen colapsable. Desconocidas → cards compactas
// (pendiente "Seleccionar destino" / resuelta "✓ … Cambiar"). Sin conceptos
// internos expuestos ni listas abiertas en la card. Se prueba comportamiento
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

// Abre el modal de destino de la columna "Color fav" (card pendiente).
async function openPicker(user) {
    await user.click(btn(/Seleccionar destino/i));
    return screen.getByRole("dialog");
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
        // NADA de botones de destino directos dentro de la card.
        expect(queryBtn("Histórico cliente")).not.toBeInTheDocument();
        expect(queryBtn("Histórico mascota")).not.toBeInTheDocument();
        expect(queryBtn("No importar")).not.toBeInTheDocument();
    });

    it("bloquea continuar hasta decidir la columna pendiente", async () => {
        const user = userEvent.setup();
        renderStep();
        expect(continueBtn()).toBeDisabled();
        await openPicker(user);
        await user.click(btn(/Conservar como información anterior de la mascota/i));
        expect(continueBtn()).toBeEnabled();
    });
});

describe("MappingStep — selector de destino (modal)", () => {
    it("abre modal con búsqueda + grupos sistema/histórico/no importar", async () => {
        const user = userEvent.setup();
        renderStep();
        await openPicker(user);
        expect(screen.getByLabelText("Buscar destino")).toBeInTheDocument();
        // owner.name + pet.name ya están asignados a Dueño/Mascota → aparecen
        // deshabilitados con "· ya asignado" (regex tolera el sufijo).
        expect(btn(/Nombre de la mascota/)).toBeInTheDocument();
        expect(btn("Especie")).toBeInTheDocument();
        expect(btn(/Conservar como información anterior del cliente/i)).toBeInTheDocument();
        expect(btn(/Conservar como información anterior de la mascota/i)).toBeInTheDocument();
        expect(btn("No importar esta columna")).toBeInTheDocument();
    });

    it("la búsqueda filtra las opciones del sistema", async () => {
        const user = userEvent.setup();
        renderStep();
        await openPicker(user);
        await user.type(screen.getByLabelText("Buscar destino"), "teléf");
        expect(btn("Teléfono del cliente")).toBeInTheDocument();
        expect(queryBtn("Especie")).not.toBeInTheDocument();
    });

    it("no permite el mismo campo del sistema en dos columnas", async () => {
        const user = userEvent.setup();
        renderStep();   // Dueño ya usa "Nombre del cliente"
        await openPicker(user);
        expect(btn(/Nombre del cliente/i)).toBeDisabled();
    });

    it("elegir un campo del sistema deja la card resuelta + payload string", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await openPicker(user);
        await user.click(btn("Especie"));
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
        await user.click(btn(/Conservar como información anterior de la mascota/i));
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
        await user.click(btn(/Conservar como información anterior de la mascota/i));
        // reabrir y cambiar a no importar
        await user.click(btn(/Cambiar destino de Color fav/i));
        await user.click(btn("No importar esta columna"));
        expect(screen.getByText("No se importará")).toBeInTheDocument();
        expect(continueBtn()).toBeEnabled();
    });

    it("renombra el nombre visible del dato histórico (no cambia la columna)", async () => {
        const user = userEvent.setup();
        const { onContinue } = renderStep();
        await openPicker(user);
        await user.click(btn(/Conservar como información anterior de la mascota/i));
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
