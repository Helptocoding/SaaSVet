import { describe, it, expect } from "vitest";
import { toList } from "./toList";

describe("toList — normalización array | paginado DRF", () => {
  it("devuelve el array tal cual cuando la respuesta ya es array", () => {
    const arr = [{ id: 1 }, { id: 2 }];
    expect(toList(arr)).toBe(arr);
  });

  it("array vacío se mantiene", () => {
    expect(toList([])).toEqual([]);
  });

  it("extrae `results` de la respuesta paginada DRF", () => {
    const paged = { count: 2, next: null, previous: null, results: [{ id: 1 }, { id: 2 }] };
    expect(toList(paged)).toEqual([{ id: 1 }, { id: 2 }]);
  });

  it("results vacío devuelve array vacío", () => {
    expect(toList({ count: 0, results: [] })).toEqual([]);
  });

  it("null / undefined → array vacío (no crashea consumidores .map)", () => {
    expect(toList(null)).toEqual([]);
    expect(toList(undefined)).toEqual([]);
  });

  it("objeto sin results → array vacío", () => {
    expect(toList({ foo: "bar" })).toEqual([]);
  });

  it("es idempotente sobre su propia salida", () => {
    const paged = { results: [{ id: 9 }] };
    expect(toList(toList(paged))).toEqual([{ id: 9 }]);
  });
});
