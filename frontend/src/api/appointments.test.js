/**
 * F5 Fase 2 — el frontend envía la precondición de estado (INV-A, ADR p57).
 *
 * Lo que se protege aquí es una propiedad fácil de romper sin darse cuenta:
 * `expected_state` describe lo que el usuario tenía EN PANTALLA. Si alguien
 * "arregla" el código releyendo la cita justo antes de guardar, la precondición
 * pasa a describir el mundo de después y deja de proteger nada — el test
 * seguiría en verde salvo que se afirme la forma exacta del payload.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("./client", () => ({
  default: { patch: vi.fn(() => Promise.resolve({ data: {} })) },
}));

import api from "./client";
import {
  assignPatient,
  expectedStateOf,
  updateAppointment,
  updateAppointmentStatus,
} from "./appointments";

const APPT = {
  public_id: "abc",
  status: "scheduled",
  date: "2026-09-01",
  start_time: "10:00:00",
};

beforeEach(() => {
  api.patch.mockClear();
});

describe("expectedStateOf", () => {
  it("proyecta la tupla semántica y recorta los segundos", () => {
    expect(expectedStateOf(APPT)).toEqual({
      expected_state: { status: "scheduled", date: "2026-09-01", start_time: "10:00" },
    });
  });

  it("omite la clave si la cita no trae la tupla completa", () => {
    // Enviar `expected_state: null` es un 400 deliberado en el backend, y
    // fabricar una tupla a medias sería una precondición falsa. Omitir es el
    // opt-in del rollout.
    expect(expectedStateOf(null)).toEqual({});
    expect(expectedStateOf({ status: "scheduled" })).toEqual({});
    expect(expectedStateOf({ ...APPT, date: undefined })).toEqual({});
  });
});

describe("las mutaciones viajan con la precondición", () => {
  it("updateAppointmentStatus la incluye cuando se le pasa la cita", async () => {
    await updateAppointmentStatus("t", "abc", "canceled", APPT);
    const [, body] = api.patch.mock.calls[0];
    expect(body).toEqual({
      status: "canceled",
      expected_state: { status: "scheduled", date: "2026-09-01", start_time: "10:00" },
    });
  });

  it("updateAppointment la incluye junto a los campos editados", async () => {
    await updateAppointment("t", "abc", { reason: "control" }, APPT);
    const [, body] = api.patch.mock.calls[0];
    expect(body.reason).toBe("control");
    expect(body.expected_state.status).toBe("scheduled");
  });

  it("assignPatient la incluye — muta la cita y escribe auditoría", async () => {
    await assignPatient("abc", 7, APPT);
    const [, body] = api.patch.mock.calls[0];
    expect(body.pet).toBe(7);
    expect(body.expected_state.date).toBe("2026-09-01");
  });

  it("sin cita en pantalla NO inventa una precondición", async () => {
    // Compatibilidad del rollout: la precondición es opt-in hasta la Fase 3.
    await updateAppointmentStatus("t", "abc", "confirmed");
    const [, body] = api.patch.mock.calls[0];
    expect(body).toEqual({ status: "confirmed" });
    expect("expected_state" in body).toBe(false);
  });
});
