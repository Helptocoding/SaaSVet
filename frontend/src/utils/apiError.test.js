import { describe, it, expect } from "vitest";
import { apiError } from "./apiError";

// apiError es la ÚNICA fuente de mensajes de error legibles en todos los forms.
// Si la cadena de prioridad se rompe, el operador ve "Error inesperado" en un cobro
// fallido sin saber qué pasó. Probamos el contrato de extracción, no la implementación.

const withData = (data, status) => ({ response: { status, data } });

describe("apiError — cadena de prioridad de extracción", () => {
  it("sin response.data → fallback (default)", () => {
    expect(apiError({})).toBe("Error inesperado");
    expect(apiError(undefined)).toBe("Error inesperado");
  });

  it("respeta el fallback custom cuando no hay data", () => {
    expect(apiError({}, "Algo salió mal")).toBe("Algo salió mal");
  });

  it("429 → mensaje de throttle fijo cuando no hay message/detail", () => {
    expect(apiError(withData({}, 429))).toBe("Demasiadas solicitudes. Intenta en unos minutos.");
  });

  it("429 → usa data.message si viene", () => {
    expect(apiError(withData({ message: "Espera 1 minuto" }, 429))).toBe("Espera 1 minuto");
  });

  it("429 corta ANTES que data.error (prioridad máxima)", () => {
    // Si 429 no tuviera prioridad, devolvería data.error. Debe devolver el throttle.
    expect(apiError(withData({ error: "ignorado" }, 429))).toBe(
      "Demasiadas solicitudes. Intenta en unos minutos."
    );
  });

  it("data como string plano → se devuelve tal cual", () => {
    expect(apiError(withData("Texto plano del servidor"))).toBe("Texto plano del servidor");
  });

  it("detail (auth/permisos) tiene prioridad sobre message", () => {
    expect(apiError(withData({ detail: "No autorizado", message: "otro" }))).toBe("No autorizado");
  });

  it("error (errores manuales en views) tiene prioridad sobre message", () => {
    expect(apiError(withData({ error: "Operación no permitida", message: "otro" }))).toBe(
      "Operación no permitida"
    );
  });

  it("errors[] (array plano) → primer mensaje", () => {
    expect(apiError(withData({ errors: ["Primero", "Segundo"] }))).toBe("Primero");
  });

  it("errors{} por campo → traduce la key vía FIELD_MAP y muestra el primer mensaje", () => {
    expect(apiError(withData({ errors: { sale_price: ["Debe ser mayor a 0"] } }))).toBe(
      "Precio de venta: Debe ser mayor a 0"
    );
  });

  it("errors{} con key desconocida → humaniza el nombre del campo", () => {
    expect(apiError(withData({ errors: { custom_field: ["inválido"] } }))).toBe(
      "Custom Field: inválido"
    );
  });

  it("errors{} cuyo valor es string (no array) → toma el string directo", () => {
    expect(apiError(withData({ errors: { name: "Requerido" } }))).toBe("Nombre: Requerido");
  });

  it("message (formato estándar {code, message}) cuando no hay nada de mayor prioridad", () => {
    expect(apiError(withData({ code: "x", message: "Stock insuficiente" }))).toBe(
      "Stock insuficiente"
    );
  });

  it("data como array (errores non-field) → primer elemento", () => {
    expect(apiError(withData(["Primer error", "Segundo"]))).toBe("Primer error");
  });

  it("data array vacío → fallback (no devuelve undefined)", () => {
    expect(apiError(withData([]))).toBe("Error inesperado");
  });

  it("último recurso: Object.values aplanado cuando no matchea ninguna clave conocida", () => {
    expect(apiError(withData({ foo: ["bar"] }))).toBe("bar");
  });

  it("objeto totalmente vacío → fallback", () => {
    expect(apiError(withData({}))).toBe("Error inesperado");
  });
});
