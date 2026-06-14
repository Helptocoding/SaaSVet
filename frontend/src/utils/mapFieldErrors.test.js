import { describe, it, expect } from "vitest";
import mapFieldErrors from "./mapFieldErrors";

describe("mapFieldErrors — normalización de errores DRF", () => {
  it("debe mapear errores top-level a claves planas", () => {
    const input = {
      name: ["El nombre es requerido."],
      email: ["Email inválido."],
    };
    const result = mapFieldErrors(input);
    expect(result).toEqual({
      name: "El nombre es requerido.",
      email: "Email inválido.",
    });
  });

  it("debe extraer el primer mensaje de arrays", () => {
    const input = {
      field: ["Mensaje 1", "Mensaje 2"],
    };
    const result = mapFieldErrors(input);
    expect(result.field).toBe("Mensaje 1");
  });

  it("debe mapear objetos anidados a clave dotted Y a clave plana de raíz libre", () => {
    // Comportamiento real (load-bearing): cada error anidado se aplana a DOS claves
    // cuando la raíz está libre — la dotted (presentation_input.sale_price) y la bare
    // (sale_price). El wizard de inventario consume ambas como fallback
    // (inventory.jsx: wizardErrors["presentation_input.sale_price"] || wizardErrors.sale_price).
    const input = {
      presentation_input: {
        sale_price: ["El precio debe ser mayor a 0."],
        stock: ["El stock no puede ser negativo."],
      },
    };
    const result = mapFieldErrors(input);
    expect(result).toEqual({
      sale_price: "El precio debe ser mayor a 0.",
      stock: "El stock no puede ser negativo.",
      "presentation_input.sale_price": "El precio debe ser mayor a 0.",
      "presentation_input.stock": "El stock no puede ser negativo.",
    });
  });

  it("debe manejar colisiones: preservar raíz y nested (determinista)", () => {
    const input = {
      sale_price: ["Error raíz"],
      presentation_input: {
        sale_price: ["Error nested"],
      },
    };
    const result = mapFieldErrors(input);
    // Opción A determinista: raíz siempre gana, pero ambas se guardan
    expect(result).toEqual({
      sale_price: "Error raíz",
      "presentation_input.sale_price": "Error nested",
    });
  });

  it("debe preservar ambas versiones de campo que existe en root y nested", () => {
    const input = {
      stock: ["Stock error at root"],
      presentation_input: {
        stock: ["Stock error at nested"],
        sale_price: ["Price error"],
      },
    };
    const result = mapFieldErrors(input);
    expect(result).toEqual({
      stock: "Stock error at root", // Colisión: la raíz NO se sobrescribe (gana el top-level)
      "presentation_input.stock": "Stock error at nested", // Nested colisionado → solo dotted
      sale_price: "Price error", // Sin colisión → también se escribe la clave plana
      "presentation_input.sale_price": "Price error",
    });
  });

  it("debe devolver objeto vacío si entrada es null/undefined", () => {
    expect(mapFieldErrors(null)).toEqual({});
    expect(mapFieldErrors(undefined)).toEqual({});
    expect(mapFieldErrors()).toEqual({});
  });

  it("debe devolver objeto vacío si entrada no es objeto", () => {
    expect(mapFieldErrors("string")).toEqual({});
    expect(mapFieldErrors(123)).toEqual({});
    expect(mapFieldErrors([])).toEqual({});
  });

  it("debe manejar valores no-array en top-level", () => {
    const input = {
      error_field: "Simple string error",
    };
    const result = mapFieldErrors(input);
    expect(result.error_field).toBe("Simple string error");
  });

  it("debe manejar valores no-array en nested", () => {
    const input = {
      nested: {
        field: "String error without array",
      },
    };
    const result = mapFieldErrors(input);
    expect(result["nested.field"]).toBe("String error without array");
  });

  it("case real: inventario con presentation_input anidado", () => {
    const apiError = {
      name: ["El nombre del producto es requerido."],
      presentation_input: {
        sale_price: ["El precio debe ser mayor a 0."],
        stock: ["El stock no puede ser negativo."],
        min_stock: ["El stock mínimo no puede ser negativo."],
      },
    };
    const result = mapFieldErrors(apiError);
    expect(result).toEqual({
      name: "El nombre del producto es requerido.",
      // anidados: clave plana (raíz libre) + clave dotted — ambas consumidas por el wizard
      sale_price: "El precio debe ser mayor a 0.",
      stock: "El stock no puede ser negativo.",
      min_stock: "El stock mínimo no puede ser negativo.",
      "presentation_input.sale_price": "El precio debe ser mayor a 0.",
      "presentation_input.stock": "El stock no puede ser negativo.",
      "presentation_input.min_stock": "El stock mínimo no puede ser negativo.",
    });
  });

  it("case real: cita con errores múltiples", () => {
    const apiError = {
      pet: ["Mascota fuera de tu organización"],
      veterinarian: ["El usuario no tiene permiso para ser veterinario en citas."],
      reason: ["El motivo de la consulta es requerido."],
    };
    const result = mapFieldErrors(apiError);
    expect(result).toEqual({
      pet: "Mascota fuera de tu organización",
      veterinarian: "El usuario no tiene permiso para ser veterinario en citas.",
      reason: "El motivo de la consulta es requerido.",
    });
  });
});
