/**
 * Normaliza la respuesta de un endpoint de lista a un array plano.
 *
 * El backend convive con dos formas (rollout incremental de paginación, P1-2):
 *   - Array crudo:        [ {...}, {...} ]            ← endpoints aún sin paginar
 *   - Paginado DRF:       { count, next, previous, results: [...] }
 *
 * `toList(data)` devuelve siempre el array de items, o `[]` si la respuesta
 * es null/undefined/forma inesperada. Idempotente sobre arrays.
 *
 * Para leer metadata de paginación (count/next) usar la respuesta cruda;
 * este helper sirve para consumidores que solo necesitan las filas.
 */
export const toList = (data) =>
    Array.isArray(data) ? data : (data?.results ?? []);

export default toList;
