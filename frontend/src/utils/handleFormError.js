import mapFieldErrors from "./mapFieldErrors";
import { apiError } from "./apiError";
import { toast } from "sonner";

// Claves del sobre `{code, message}` del backend: nunca son campos de un formulario.
const ENVELOPE_KEYS = new Set(["code", "message", "detail", "error", "non_field_errors"]);
// Dentro de `errors`, estas tampoco corresponden a un campo.
const NON_FIELD_KEYS = new Set(["detail", "error", "non_field_errors"]);

/**
 * handleFormError — Handler centralizado para errores en formularios
 *
 * Comportamiento:
 *   - Errores de campo → setErrors con merge + limpieza
 *   - Sin errores de campo → toast con mensaje global (permisos, conflictos, red)
 *   - Ambos → los dos: un mensaje global no tiene dónde pintarse en el form
 *
 * Formas de error del backend:
 *   - {code, message, ...}: error global, con o sin datos extra como `candidate`
 *   - {code, errors: {campo: [...]}}: validación
 *   - {campo: [...]}: forma DRF sin sobre
 *
 * Parámetros:
 *   err: axios error
 *   setErrors: React setState para estado de errores del formulario
 *   opts.merge: true (default) — merge con errores previos; false — reemplaza todo
 *
 * Uso:
 *   try {
 *     await apiCall(payload);
 *   } catch (err) {
 *     handleFormError(err, setFormErrors);
 *   }
 */
export default function handleFormError(err, setErrors, opts = { merge: true }) {
  const data = err?.response?.data;
  const { fieldErrors, globalMessage } = splitErrors(data);

  if (Object.keys(fieldErrors).length === 0) {
    toast.error(globalMessage || apiError(err));
    return;
  }

  if (opts.merge) {
    setErrors(prev => {
      const clean = { ...(prev || {}) };
      // Eliminar claves que van a ser reemplazadas para evitar errores "pegados"
      Object.keys(fieldErrors).forEach(k => delete clean[k]);
      return { ...clean, ...fieldErrors };
    });
  } else {
    setErrors(fieldErrors);
  }
  if (globalMessage) toast.error(globalMessage);
}

function splitErrors(data) {
  if (!data || typeof data !== "object") return { fieldErrors: {}, globalMessage: "" };

  const hasCode = typeof data.code === "string";
  const nested = data.errors && typeof data.errors === "object" && !Array.isArray(data.errors);
  // `{code, message, candidate}`: `candidate` son datos del conflicto, no campos.
  if (hasCode && !nested) return { fieldErrors: {}, globalMessage: "" };

  const source = nested ? data.errors : data;
  const excluded = nested ? NON_FIELD_KEYS : ENVELOPE_KEYS;
  const fieldErrors = {};
  let globalMessage = "";
  Object.entries(mapFieldErrors(source)).forEach(([key, value]) => {
    if (!excluded.has(key)) fieldErrors[key] = value;
    else if (!globalMessage && NON_FIELD_KEYS.has(key)) globalMessage = value;
  });
  return { fieldErrors, globalMessage };
}
