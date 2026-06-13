// Filtros de mascota compartidos entre la vista de Mascotas y Recetas.
// Fuente única de verdad: no reimplementar especie/edad por módulo.

// ─── Detección de especie ───────────────────────────────────────────────
export const isCanino = (p) => /perro|canino|dog/i.test(p?.species || "");
export const isFelino = (p) => /gato|felino|cat/i.test(p?.species || "");

// ─── Utilidades de edad ─────────────────────────────────────────────────
export const getAgeYears = (bd) => {
    if (!bd) return null;
    return (Date.now() - new Date(bd).getTime()) / (365.25 * 24 * 3600 * 1000);
};

export const getAgeGroup = (bd) => {
    const y = getAgeYears(bd);
    if (y === null) return null;
    if (y < 1) return "cachorro";
    if (y < 3) return "joven";
    if (y < 8) return "adulto";
    return "senior";
};
