import { getPets, getOwners } from "./pets";
import { toList } from "../utils/toList";

/**
 * Fetchers normalizados para `EntitySearch` (contrato: {items, hasMore}).
 *
 * Reusan los endpoints de lista paginados (ADR p44 pets, ADR p44b owners): al
 * mandar `page` el backend devuelve el envelope `{count, next, results}` y
 * `next` indica si hay más → "Ver más". Sin `page` los endpoints conservan su
 * contrato legacy de array plano (dropdowns viejos no migrados).
 */
export const searchPets = async ({ query, page = 1, pageSize = 8, ownerPublicId } = {}) => {
    const params = { page, page_size: pageSize };
    if (query) params.search = query;
    if (ownerPublicId) params.owner = ownerPublicId;
    const data = await getPets(params);
    // La mascota genérica ("Paciente Anónimo") nunca es un resultado elegible.
    const items = toList(data).filter(p => !p.is_generic);
    return { items, hasMore: Boolean(data?.next) };
};

export const searchOwners = async ({ query, page = 1, pageSize = 8 } = {}) => {
    const params = { page, page_size: pageSize, is_generic: "false" };
    if (query) params.search = query;
    const data = await getOwners(params);
    return { items: toList(data), hasMore: Boolean(data?.next) };
};
