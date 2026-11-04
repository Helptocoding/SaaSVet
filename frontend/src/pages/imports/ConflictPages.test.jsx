import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConflictPages from "./ConflictPages";
import { getImportConflicts } from "../../api/imports";

vi.mock("../../api/imports", () => ({ getImportConflicts: vi.fn() }));

describe("páginas de conflictos", () => {
    it("consulta páginas reales con versión y permite volver sin inventar totales", async () => {
        getImportConflicts.mockResolvedValueOnce({ total: 101, complete: true, results: [{ row: 1, match_confidence: "high", message: "Primero" }], next_cursor: "next" });
        getImportConflicts.mockResolvedValueOnce({ total: 101, complete: true, results: [{ row: 101, match_confidence: "uncertain", message: "Último" }], next_cursor: null });
        render(<ConflictPages publicId="job" report={{ version: "v1", total: 101 }} highTotal={50} uncertainTotal={51} />);
        fireEvent.click(screen.getByRole("button", { name: "Ver detalle" }));
        expect(await screen.findByText("Primero")).toBeInTheDocument();
        expect(screen.getByText(/Mostrando 1 de 101/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
        expect(await screen.findByText("Último")).toBeInTheDocument();
        expect(getImportConflicts).toHaveBeenLastCalledWith("job", { version: "v1", cursor: "next" });
        await waitFor(() => expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled());
        expect(screen.getByRole("button", { name: "Anterior" })).toBeEnabled();
    });
});
