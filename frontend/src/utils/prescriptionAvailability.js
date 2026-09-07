/**
 * Read the backend-owned maximum. This module intentionally performs no
 * prescription, conversion-factor, stock or lot arithmetic.
 */
export const authoritativePresentationMax = (presentation) => {
    const maximum = Number(presentation?.max_selectable_quantity);
    return Number.isSafeInteger(maximum) && maximum >= 0 ? maximum : 0;
};
