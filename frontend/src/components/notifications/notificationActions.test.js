import { describe, expect, it } from "vitest";
import { formatRelativeTime, getNotificationAction } from "./notificationActions";

describe("notificationActions", () => {
  it("mapea cada tipo a su CTA con ruta real", () => {
    expect(getNotificationAction({ type: "appointment_upcoming" })).toEqual({
      label: "Ver cita", to: "/appointments",
    });
    expect(getNotificationAction({ type: "appointment_delayed" })).toEqual({
      label: "Ver cita", to: "/appointments",
    });
    expect(getNotificationAction({ type: "stock_low_entered" })).toEqual({
      label: "Ver inventario", to: "/inventory",
    });
    expect(getNotificationAction({ type: "stock_out" })).toEqual({
      label: "Ver inventario", to: "/inventory",
    });
    expect(getNotificationAction({ type: "cash_difference" })).toEqual({
      label: "Ver caja", to: "/cash",
    });
  });

  it("nunca persiste href: solo label + ruta", () => {
    const action = getNotificationAction({ type: "stock_out" });
    expect(action).not.toHaveProperty("href");
  });

  it("tipo desconocido no tiene acción", () => {
    expect(getNotificationAction({ type: "unknown_type" })).toBeNull();
    expect(getNotificationAction(null)).toBeNull();
  });
});

describe("formatRelativeTime", () => {
  it("formatea minutos, horas y días en español", () => {
    const now = Date.now();
    expect(formatRelativeTime(new Date(now - 10_000).toISOString())).toBe("ahora mismo");
    expect(formatRelativeTime(new Date(now - 10 * 60_000).toISOString())).toBe("hace 10 min");
    expect(formatRelativeTime(new Date(now - 3 * 3_600_000).toISOString())).toBe("hace 3 h");
    expect(formatRelativeTime(new Date(now - 2 * 86_400_000).toISOString())).toBe("hace 2 d");
  });

  it("formatea correctamente una cita futura", () => {
    const now = Date.now();
    expect(formatRelativeTime(new Date(now + 10 * 60_000).toISOString())).toBe("en 10 min");
  });

  it("vacio ante entrada inválida", () => {
    expect(formatRelativeTime(null)).toBe("");
    expect(formatRelativeTime("no-fecha")).toBe("");
  });
});
