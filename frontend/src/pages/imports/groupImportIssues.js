/**
 * Agrupa ítems de importación (blocking/warnings) por field para presentación.
 *
 * @param {Array} items - Array de {row, field, message}
 * @param {Object} labelByKey - Mapa fieldKey → label humano (del fieldCatalog)
 * @param {Object} [actionsByField] - Mapa fieldKey → instrucción "qué hacer"
 * @returns {Array} Grupos ordenados por count descendente.
 *   [{ field, label, count, action, samples: [{row, message}] }]
 */
export function groupImportIssues(items, labelByKey, actionsByField = {}) {
    if (!items || items.length === 0) return [];

    const groups = {};
    for (const item of items) {
        const key = item.field || "unknown";
        if (!groups[key]) {
            groups[key] = {
                field: key,
                label: labelByKey[key] || key,
                count: 0,
                action:
                    actionsByField[key] ||
                    "Revisa esta columna en tu archivo y corrige el valor.",
                samples: [],
            };
        }
        groups[key].count++;
        if (groups[key].samples.length < 5) {
            groups[key].samples.push(item);
        }
    }
    return Object.values(groups).sort((a, b) => b.count - a.count);
}
