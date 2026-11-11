import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConflictPages from "./ConflictPages";
import { getEntityConfig } from "./entityConfig";
import { getImportConflicts } from "../../api/imports";

vi.mock("../../api/imports", () => ({ getImportConflicts: vi.fn() }));

const cfg = getEntityConfig("inventory");

describe("páginas de conflictos", () => {
    it("consulta páginas reales con versión y permite volver sin inventar totales", async () => {
        getImportConflicts.mockResolvedValueOnce({
            total: 101, complete: true, next_cursor: "next",
            results: [{
                row: 1, match_confidence: "high", message: "Ya existe un producto con este código interno.",
                incoming: { name: "Gasa", internal_code: "G-1" }, existing: { name: "Gasa", public_id: "p1" },
            }],
        });
        getImportConflicts.mockResolvedValueOnce({
            total: 101, complete: true, next_cursor: null,
            results: [{
                row: 101, match_confidence: "uncertain", message: "Ya existe un producto con este código interno.",
                incoming: { name: "Otra gasa", internal_code: "G-1" }, existing: { name: "Gasa", public_id: "p1" },
            }],
        });
        render(<ConflictPages publicId="job" report={{ version: "v1", total: 101 }} highTotal={50} uncertainTotal={51} cfg={cfg} />);
        fireEvent.click(screen.getByRole("button", { name: "Ver detalle" }));
        expect(await screen.findByText("Parece el mismo producto.")).toBeInTheDocument();
        expect(screen.getByText(/Mostrando 1 de 101/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
        expect(await screen.findByText("Otra gasa")).toBeInTheDocument();
        expect(getImportConflicts).toHaveBeenLastCalledWith("job", { version: "v1", cursor: "next" });
        await waitFor(() => expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled());
        expect(screen.getByRole("button", { name: "Anterior" })).toBeEnabled();
    });

    it("muestra cada conflicto con las etiquetas de la muestra y su motivo concreto, sin claves internas", async () => {
        getImportConflicts.mockResolvedValueOnce({
            total: 1, complete: true, next_cursor: null,
            results: [{
                row: 7, match_confidence: "uncertain", message: "Ya existe un producto con este código interno.",
                incoming: { name: "Otro nombre", internal_code: "I03-007" },
                existing: { name: "Producto 007", public_id: "p7" },
            }],
        });
        render(<ConflictPages publicId="job" report={{ version: "v1", total: 1 }} highTotal={0} uncertainTotal={1} cfg={cfg} />);
        fireEvent.click(screen.getByRole("button", { name: "Ver detalle" }));
        expect(await screen.findByText("Fila #7")).toBeInTheDocument();
        expect(screen.getByText("En tu archivo")).toBeInTheDocument();
        expect(screen.getByText("Ya registrado")).toBeInTheDocument();
        expect(screen.getByText("Otro nombre")).toBeInTheDocument();
        expect(screen.getByText("Producto 007")).toBeInTheDocument();
        expect(screen.getByText("Ya existe un producto con este código interno.")).toBeInTheDocument();
        expect(screen.queryByText(/internal_code:|name:|public_id/)).not.toBeInTheDocument();
    });
});
