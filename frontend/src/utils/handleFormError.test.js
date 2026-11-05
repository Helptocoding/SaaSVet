import { describe, it, expect, vi, beforeEach } from "vitest";

// sonner.toast es un side-effect global; lo mockeamos para verificar la rama de
// "error global". Único mock necesario — el resto es comportamiento puro.
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
import { toast } from "sonner";
import handleFormError from "./handleFormError";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("handleFormError — ruteo de errores DRF a form vs toast", () => {
  it("errores de campo → setErrors (merge), sin toast global", () => {
    const setErrors = vi.fn();
    handleFormError({ response: { data: { name: ["Requerido"] } } }, setErrors);

    expect(setErrors).toHaveBeenCalledTimes(1);
    expect(toast.error).not.toHaveBeenCalled();

    // merge default: setErrors recibe un updater funcional
    const updater = setErrors.mock.calls[0][0];
    expect(typeof updater).toBe("function");
    expect(updater({})).toEqual({ name: "Requerido" });
  });

  it("merge limpia la clave previa antes de fusionar (sin errores 'pegados')", () => {
    const setErrors = vi.fn();
    handleFormError({ response: { data: { name: ["Nuevo"] } } }, setErrors);
    const updater = setErrors.mock.calls[0][0];
    // 'name' se reemplaza; 'otro' se conserva
    expect(updater({ name: "Viejo", otro: "intacto" })).toEqual({
      name: "Nuevo",
      otro: "intacto",
    });
  });

  it("opts.merge=false → reemplaza el estado completo (objeto directo, no updater)", () => {
    const setErrors = vi.fn();
    handleFormError(
      { response: { data: { name: ["Requerido"], email: ["Inválido"] } } },
      setErrors,
      { merge: false }
    );
    expect(setErrors).toHaveBeenCalledWith({ name: "Requerido", email: "Inválido" });
  });

  it("varios campos → todos llegan al form", () => {
    const setErrors = vi.fn();
    handleFormError(
      { response: { data: { pet: ["Fuera de tu organización"], reason: ["Requerido"] } } },
      setErrors,
      { merge: false }
    );
    expect(setErrors).toHaveBeenCalledWith({
      pet: "Fuera de tu organización",
      reason: "Requerido",
    });
  });

  it("sin errores de campo (red/permiso) → toast global, sin tocar el form", () => {
    const setErrors = vi.fn();
    handleFormError({}, setErrors); // sin response → no hay field errors

    expect(setErrors).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith("Error inesperado");
  });

  it("data vacía → toast con fallback, sin form", () => {
    const setErrors = vi.fn();
    handleFormError({ response: { data: {} } }, setErrors);
    expect(setErrors).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith("Error inesperado");
  });

  it("403 {code, message} → toast con el mensaje, sin tocar el form", () => {
    const setErrors = vi.fn();
    handleFormError(
      { response: { status: 403, data: { code: "permission_denied", message: "Sin permiso" } } },
      setErrors
    );
    expect(setErrors).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith("Sin permiso");
  });

  it("409 con datos extra → toast: `candidate` no son campos del form", () => {
    const setErrors = vi.fn();
    handleFormError(
      {
        response: {
          status: 409,
          data: {
            code: "owner_exists",
            message: "Ese teléfono ya tiene expediente",
            candidate: { public_id: "uuid", name: "Ana" },
          },
        },
      },
      setErrors
    );
    expect(setErrors).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith("Ese teléfono ya tiene expediente");
  });

  it("validación {code, errors} → solo los campos llegan al form", () => {
    const setErrors = vi.fn();
    handleFormError(
      { response: { status: 400, data: { code: "validation_error", errors: { name: ["Requerido"] } } } },
      setErrors,
      { merge: false }
    );
    expect(setErrors).toHaveBeenCalledWith({ name: "Requerido" });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("validación anidada conserva la clave plana y la completa", () => {
    const setErrors = vi.fn();
    handleFormError(
      {
        response: {
          status: 400,
          data: { code: "validation_error", errors: { owner: { phone: ["Inválido"] } } },
        },
      },
      setErrors,
      { merge: false }
    );
    expect(setErrors).toHaveBeenCalledWith({ phone: "Inválido", "owner.phone": "Inválido" });
  });

  it("slot_taken: un `errors.error` no es un campo, va a toast", () => {
    const setErrors = vi.fn();
    handleFormError(
      {
        response: {
          status: 400,
          data: { code: "slot_taken", message: "Horario ocupado", errors: { error: ["Horario ocupado"] } },
        },
      },
      setErrors
    );
    expect(setErrors).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith("Horario ocupado");
  });

  it("campo y mensaje global a la vez → form y toast", () => {
    const setErrors = vi.fn();
    handleFormError(
      {
        response: {
          status: 400,
          data: {
            code: "validation_error",
            errors: { name: ["Requerido"], non_field_errors: ["Combinación inválida"] },
          },
        },
      },
      setErrors,
      { merge: false }
    );
    expect(setErrors).toHaveBeenCalledWith({ name: "Requerido" });
    expect(toast.error).toHaveBeenCalledWith("Combinación inválida");
  });

  it("un campo llamado `code` dentro de `errors` sí es un campo", () => {
    const setErrors = vi.fn();
    handleFormError(
      { response: { status: 400, data: { code: "validation_error", errors: { code: ["Repetido"] } } } },
      setErrors,
      { merge: false }
    );
    expect(setErrors).toHaveBeenCalledWith({ code: "Repetido" });
  });
});
