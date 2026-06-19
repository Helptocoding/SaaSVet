import { describe, it, expect } from "vitest";
import { groupImportIssues } from "./groupImportIssues";

const LABELS = {
    "pet.name": "Nombre de la mascota",
    "owner.name": "Nombre del cliente",
    "owner.phone": "Teléfono del cliente",
    "pet.species": "Especie",
};

const ACTIONS = {
    "pet.name": "Agrega el nombre en la columna asignada como Nombre de la mascota.",
    "owner.phone": "Corrige el teléfono: deben ser 10 dígitos, o deja la celda vacía.",
};

describe("groupImportIssues", () => {
    it("devuelve array vacío si no hay ítems", () => {
        expect(groupImportIssues([], LABELS)).toEqual([]);
        expect(groupImportIssues(null, LABELS)).toEqual([]);
        expect(groupImportIssues(undefined, LABELS)).toEqual([]);
    });

    it("agrupa por field", () => {
        const items = [
            { row: 2, field: "pet.name", message: "El nombre de la mascota es requerido." },
            { row: 7, field: "pet.name", message: "El nombre de la mascota es requerido." },
            { row: 3, field: "owner.phone", message: "El teléfono debe tener 10 dígitos." },
        ];
        const groups = groupImportIssues(items, LABELS, ACTIONS);
        expect(groups).toHaveLength(2);
        expect(groups[0].field).toBe("pet.name");
        expect(groups[0].count).toBe(2);
        expect(groups[0].label).toBe("Nombre de la mascota");
        expect(groups[1].field).toBe("owner.phone");
        expect(groups[1].count).toBe(1);
    });

    it("ordena por count descendente", () => {
        const items = [
            { row: 1, field: "owner.phone", message: "..." },
            { row: 2, field: "pet.name", message: "..." },
            { row: 3, field: "pet.name", message: "..." },
            { row: 4, field: "pet.name", message: "..." },
            { row: 5, field: "owner.name", message: "..." },
        ];
        const groups = groupImportIssues(items, LABELS, ACTIONS);
        expect(groups[0].field).toBe("pet.name");
        expect(groups[0].count).toBe(3);
        expect(groups[1].count).toBe(1);
        expect(groups[2].count).toBe(1);
    });

    it("samples limitados a 5", () => {
        const items = Array.from({ length: 10 }, (_, i) => ({
            row: i + 1,
            field: "pet.name",
            message: "Falta el nombre.",
        }));
        const groups = groupImportIssues(items, LABELS, ACTIONS);
        expect(groups[0].samples).toHaveLength(5);
        expect(groups[0].count).toBe(10);
    });

    it("usa mensaje 'qué hacer' específico por field", () => {
        const items = [
            { row: 1, field: "pet.name", message: "Falta el nombre." },
            { row: 2, field: "owner.phone", message: "Teléfono inválido." },
        ];
        const groups = groupImportIssues(items, LABELS, ACTIONS);
        expect(groups.find((g) => g.field === "pet.name").action).toContain("Nombre de la mascota");
        expect(groups.find((g) => g.field === "owner.phone").action).toContain("10 dígitos");
    });

    it("field null/undefined → grupo 'unknown'", () => {
        const items = [
            { row: 1, field: null, message: "Error desconocido." },
            { row: 2, field: undefined, message: "Otro error." },
        ];
        const groups = groupImportIssues(items, LABELS, ACTIONS);
        expect(groups).toHaveLength(1);
        expect(groups[0].field).toBe("unknown");
        expect(groups[0].count).toBe(2);
    });

    it("usa label genérico si no existe en labelByKey", () => {
        const items = [
            { row: 1, field: "custom.field", message: "..." },
        ];
        const groups = groupImportIssues(items, LABELS, ACTIONS);
        expect(groups[0].label).toBe("custom.field");
    });

    it("mismo field con samples preserva las primeras 5 filas", () => {
        const items = Array.from({ length: 8 }, (_, i) => ({
            row: i + 1,
            field: "owner.phone",
            message: `Error en fila ${i + 1}`,
        }));
        const groups = groupImportIssues(items, LABELS, ACTIONS);
        expect(groups[0].samples).toHaveLength(5);
        expect(groups[0].samples[0].row).toBe(1);
        expect(groups[0].samples[4].row).toBe(5);
    });
});
