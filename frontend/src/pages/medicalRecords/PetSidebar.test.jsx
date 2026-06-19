/**
 * PetSidebar — buscador de mascota del historial clínico, server-side.
 *
 * Protege el rediseño de escalabilidad (ADR p44c): el sidebar busca contra el
 * backend (searchPets) con "Ver más" y NUNCA carga la lista completa; muestra
 * contexto (dueño) para diferenciar homónimos; al elegir entrega el objeto pet.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

const searchPets = vi.fn();
vi.mock("../../api/lookups", () => ({ searchPets: (...a) => searchPets(...a) }));

import PetSidebar from "./PetSidebar";

const pet = (n, owner) => ({
    public_id: `pid-${n}`,
    id: n,
    name: "Bella",
    species: "canino",
    breed: "Labrador",
    owner: { name: owner, phone: "8120000000" },
});

beforeEach(() => {
    searchPets.mockReset();
    searchPets.mockImplementation(({ page = 1 }) =>
        Promise.resolve(
            page === 1
                ? { items: [pet(0, "Luis Pérez"), pet(1, "Ana García")], hasMore: true }
                : { items: [pet(2, "Marta Ruiz")], hasMore: false }
        )
    );
});

const renderSidebar = (props = {}) =>
    render(
        <PetSidebar
            selectedPet=""
            selectedPetObj={null}
            onSelectPet={props.onSelectPet || (() => {})}
            collapsed={false}
            onToggleCollapse={() => {}}
        />
    );

describe("PetSidebar (server-side)", () => {
    it("busca en el backend al montar (no carga la lista completa) y muestra el dueño", async () => {
        renderSidebar();
        await screen.findByText(/Luis Pérez/);
        expect(searchPets).toHaveBeenCalledWith(expect.objectContaining({ query: "", page: 1 }));
        // Diferencia homónimos: dos "Bella" con dueños distintos.
        expect(screen.getByText(/Ana García/)).toBeInTheDocument();
        expect(screen.getAllByText("Bella")).toHaveLength(2);
    });

    it("escribir manda la búsqueda al backend (debounced)", async () => {
        const user = userEvent.setup();
        renderSidebar();
        await screen.findByText(/Luis Pérez/);

        await user.type(screen.getByPlaceholderText(/Nombre, cliente/), "luis");

        await waitFor(() =>
            expect(searchPets).toHaveBeenCalledWith(expect.objectContaining({ query: "luis", page: 1 }))
        );
    });

    it("'Ver más' trae la página 2", async () => {
        const user = userEvent.setup();
        renderSidebar();
        await screen.findByText(/Luis Pérez/);

        await user.click(screen.getByRole("button", { name: /ver más/i }));

        await screen.findByText(/Marta Ruiz/);
        expect(searchPets).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }));
    });

    it("al elegir, entrega el objeto pet completo", async () => {
        const onSelectPet = vi.fn();
        const user = userEvent.setup();
        renderSidebar({ onSelectPet });
        await screen.findByText(/Luis Pérez/);

        // El primer item (Bella · Luis Pérez).
        await user.click(screen.getByText(/Luis Pérez/));

        expect(onSelectPet).toHaveBeenCalledWith(expect.objectContaining({ public_id: "pid-0", name: "Bella" }));
    });
});
