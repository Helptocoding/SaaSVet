/**
 * F5 Fase 2 — reconocer el conflicto de INV-A (ADR p57 §5.1).
 *
 * `409 appointment_changed` **no es una avería**: es un resultado de negocio.
 * Distinguirlo importa porque la conducta correcta es la contraria a la de un
 * error: no reintentar, recargar y volver a preguntar. Si la UI lo tratara como
 * "error al guardar", el usuario reintentaría — y reintentar sin precondición
 * es exactamente la sobrescritura que INV-A existe para impedir.
 */
import { describe, expect, it } from "vitest";

import {
  apiError,
  appointmentChangedCurrent,
  isAppointmentChanged,
} from "./apiError";

const conflict = {
  response: {
    status: 409,
    data: {
      code: "appointment_changed",
      message: "La cita cambió desde que se propuso.",
      current: { status: "canceled", date: "2026-09-01", start_time: "10:00" },
    },
  },
};

describe("isAppointmentChanged", () => {
  it("reconoce el 409 tipificado", () => {
    expect(isAppointmentChanged(conflict)).toBe(true);
  });

  it("no confunde otros 409 del contrato con este", () => {
    // `owner_exists`, `owner_ambiguous`, `release_conflict` y
    // `resource_has_dependencies` también son 409 y NO se manejan así.
    for (const code of ["owner_exists", "owner_ambiguous", "release_conflict"]) {
      expect(isAppointmentChanged({ response: { status: 409, data: { code } } })).toBe(false);
    }
  });

  it("no se dispara con errores normales ni con undefined", () => {
    expect(isAppointmentChanged({ response: { status: 400, data: {} } })).toBe(false);
    expect(isAppointmentChanged(undefined)).toBe(false);
    expect(isAppointmentChanged(new Error("boom"))).toBe(false);
  });
});

describe("appointmentChangedCurrent", () => {
  it("expone el estado REAL para poder decir qué cambió", () => {
    // Nunca "falló, reintenta": el usuario decide otra vez con esto delante.
    expect(appointmentChangedCurrent(conflict)).toEqual({
      status: "canceled",
      date: "2026-09-01",
      start_time: "10:00",
    });
  });

  it("es null si el cuerpo no lo trae", () => {
    expect(appointmentChangedCurrent({ response: { status: 409, data: {} } })).toBeNull();
    expect(appointmentChangedCurrent(undefined)).toBeNull();
  });
});

describe("apiError sigue sirviendo de fallback", () => {
  it("extrae el mensaje del propio 409", () => {
    expect(apiError(conflict)).toBe("La cita cambió desde que se propuso.");
  });
});
