/**
 * EntitySearch — combobox relacional con paginación incremental.
 *
 * Protege el contrato que pidió el rediseño: NO hay tope invisible (muestra 8 y
 * trae más con "Ver más"), busca server-side (debounce), y devuelve el item
 * seleccionado. Es la base de los selectores de citas/historial/POS/recetas.
 */
import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
}));

import EntitySearch from "./EntitySearch";

const PAGE_SIZE = 8;

// fetchPage de prueba: 12 resultados en 2 páginas (8 + 4).
const fetchPage = vi.fn(({ page }) => {
    const total = 12;
    const start = (page - 1) * PAGE_SIZE;
    const count = Math.min(PAGE_SIZE, total - start);
    const items = Array.from({ length: count }, (_, i) => ({
        id: start + i,
        public_id: `pid-${start + i}`,
        name: `Mascota ${start + i}`,
    }));
    return Promise.resolve({ items, hasMore: page * PAGE_SIZE < total });
});

function Host() {
    const [val, setVal] = useState(null);
    return (
        <EntitySearch
            value={val}
            onChange={setVal}
            fetchPage={fetchPage}
            renderItem={(it) => <span>{it.name}</span>}
            getOptionLabel={(it) => it.name}
            placeholder="Buscar mascota"
        />
    );
}

const listbox = () => screen.getByRole("listbox");

beforeEach(() => {
    fetchPage.mockClear();
});

describe("EntitySearch", () => {
    it("muestra la primera página (8) y ofrece 'Ver más', sin tope invisible", async () => {
        const user = userEvent.setup();
        render(<Host />);

        await user.click(screen.getByPlaceholderText("Buscar mascota"));

        await screen.findByText("Mascota 0");
        expect(within(listbox()).getAllByRole("option")).toHaveLength(8);
        expect(screen.getByRole("button", { name: /ver más/i })).toBeInTheDocument();
        expect(fetchPage).toHaveBeenCalledWith(expect.objectContaining({ page: 1 }));
    });

    it("'Ver más' agrega la página 2 y desaparece al agotar", async () => {
        const user = userEvent.setup();
        render(<Host />);
        await user.click(screen.getByPlaceholderText("Buscar mascota"));
        await screen.findByText("Mascota 0");

        await user.click(screen.getByRole("button", { name: /ver más/i }));

        await screen.findByText("Mascota 11");
        expect(within(listbox()).getAllByRole("option")).toHaveLength(12);
        expect(fetchPage).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }));
        expect(screen.queryByRole("button", { name: /ver más/i })).not.toBeInTheDocument();
    });

    it("la búsqueda se manda al fetcher (debounced)", async () => {
        const user = userEvent.setup();
        render(<Host />);

        await user.type(screen.getByPlaceholderText("Buscar mascota"), "luis");

        await waitFor(() =>
            expect(fetchPage).toHaveBeenCalledWith(expect.objectContaining({ query: "luis", page: 1 }))
        );
    });

    it("seleccionar devuelve el item y refleja su label en el input", async () => {
        const user = userEvent.setup();
        render(<Host />);
        await user.click(screen.getByPlaceholderText("Buscar mascota"));
        await screen.findByText("Mascota 3");

        await user.click(screen.getByText("Mascota 3"));

        expect(screen.getByPlaceholderText("Buscar mascota")).toHaveValue("Mascota 3");
        expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });
});
