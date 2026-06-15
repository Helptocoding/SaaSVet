import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import UploadStep from "./UploadStep";

// La validación de archivo (extensión + tamaño) ocurre en el cliente y debe
// avisar con toast (consistente con el resto del sistema), sin disparar la
// subida. El tope de 5 MB se pre-chequea aquí para feedback inmediato.
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import { toast } from "sonner";

function fileOfSize(name, bytes, type = "text/csv") {
    const f = new File(["x"], name, { type });
    Object.defineProperty(f, "size", { value: bytes });
    return f;
}

const fileInput = (container) => container.querySelector('input[type="file"]');

describe("UploadStep — validación de archivo", () => {
    beforeEach(() => vi.clearAllMocks());

    it("rechaza un archivo que excede 5 MB con toast y no lo selecciona", () => {
        const onUpload = vi.fn();
        const { container } = render(<UploadStep onUpload={onUpload} uploading={false} />);

        fireEvent.change(fileInput(container), {
            target: { files: [fileOfSize("grande.csv", 6 * 1024 * 1024)] },
        });

        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("máximo es 5 MB"));
        expect(onUpload).not.toHaveBeenCalled();
        expect(screen.queryByText("grande.csv")).not.toBeInTheDocument();
    });

    it("rechaza una extensión no soportada con toast", () => {
        const onUpload = vi.fn();
        const { container } = render(<UploadStep onUpload={onUpload} uploading={false} />);

        fireEvent.change(fileInput(container), {
            target: { files: [fileOfSize("datos.pdf", 1000, "application/pdf")] },
        });

        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining(".csv"));
        expect(onUpload).not.toHaveBeenCalled();
    });

    it("acepta un archivo válido y muestra su chip", () => {
        const onUpload = vi.fn();
        const { container } = render(<UploadStep onUpload={onUpload} uploading={false} />);

        fireEvent.change(fileInput(container), {
            target: { files: [fileOfSize("clientes.csv", 2048)] },
        });

        expect(screen.getByText("clientes.csv")).toBeInTheDocument();
        expect(toast.error).not.toHaveBeenCalled();
    });
});
