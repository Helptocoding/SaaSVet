/**
 * mapFieldErrors — Normaliza respuestas DRF a claves planas (opción A determinista).
 *
 * Cada error anidado se publica con DOS claves: la plana de raíz y la dotted.
 * Ambas son contrato: el wizard de inventario las consume como fallback.
 *
 * Comportamiento:
 *   - Top-level: { sale_price: ["X"] } → { sale_price: "X" }
 *   - Anidado sin colisión: { presentation_input: { sale_price: ["Y"] } }
 *     → { sale_price: "Y", "presentation_input.sale_price": "Y" }
 *   - Colisión: { sale_price: ["X"], presentation_input: { sale_price: ["Y"] } }
 *     → { sale_price: "X", "presentation_input.sale_price": "Y" }
 *
 * Reglas:
 *   1. Un error top-level siempre ocupa su clave plana.
 *   2. Un error anidado ocupa la clave plana solo si aún está libre.
 *   3. La clave dotted se escribe siempre.
 *   4. De cada lista se toma únicamente el primer mensaje.
 */
export default function mapFieldErrors(data = {}) {
  const result = {};

  if (!data || typeof data !== "object") {
    return result;
  }

  // Procesa top-level y nested entries
  Object.entries(data).forEach(([key, value]) => {
    if (Array.isArray(value) || typeof value !== "object") {
      // Top-level field: sale_price: ["X"] → sale_price: "X"
      const plainVal = Array.isArray(value) ? value[0] : String(value);
      result[key] = plainVal;
      return;
    }

    // Nested object: presentation_input: { sale_price: ["Y"], stock: ["Z"] }
    Object.entries(value).forEach(([innerKey, innerVal]) => {
      const plainVal = Array.isArray(innerVal) ? innerVal[0] : String(innerVal);

      // Intenta escribir en root primero
      if (!Object.prototype.hasOwnProperty.call(result, innerKey)) {
        // No existe en root → guarda aquí
        result[innerKey] = plainVal;
      } else {
        // Colisión: ya existe en root, guarda además la versión nested
        // Nunca sobrescribe la raíz
      }

      // Siempre guarda la versión nested (presentation_input.sale_price)
      const nestedKey = `${key}.${innerKey}`;
      if (!Object.prototype.hasOwnProperty.call(result, nestedKey)) {
        result[nestedKey] = plainVal;
      }
    });
  });

  return result;
}
