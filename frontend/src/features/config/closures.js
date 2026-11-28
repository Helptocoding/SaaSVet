// Cierres excepcionales (ADR p70 D6, plan F2.1): validación previa con los
// mismos mensajes que el servidor (`organizations.services._clean_closure`).
// Las fechas son locales de la clínica (`YYYY-MM-DD`) y se comparan como texto.

export const CLOSURE_REASON_MAX = 120;

export function closureErrorsFor(form) {
    const errors = {};
    if (!form.start_date) errors.start_date = "Elige el primer día.";
    if (!form.end_date) errors.end_date = "Elige el último día.";
    else if (form.start_date && form.end_date < form.start_date) {
        errors.end_date = "La fecha final no puede ser anterior a la inicial.";
    }
    if (!form.reason.trim()) errors.reason = "Escribe el motivo del cierre (por ejemplo, «Día festivo»).";
    return errors;
}
