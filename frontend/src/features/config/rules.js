// Reglas de operación por apartado (ADR p70, plan F1.2 y F1.5). Cada una dice
// qué hace exactamente. «Urgencias sin cita» no aparece: no tiene efecto y se
// retira (D5, F1.6). Las que cambian cómo se cobra piden confirmación al
// activarlas o desactivarlas (`confirm`).
export const CARE_RULES = [
    {
        key: "require_confirmation_before_start",
        label: "Confirmar la cita antes de atenderla",
        description: "Una cita solo puede pasar a consulta si antes se marcó como confirmada.",
    },
    {
        key: "allow_anonymous_walkin",
        label: "Atender sin registrar la mascota",
        description: "Una atención sin cita puede empezar sin elegir la mascota; se vincula después, antes de completar la cita.",
    },
    {
        key: "auto_create_medical_record",
        label: "Al completar una cita, crear su expediente si no lo tiene",
        description: "Si una cita se marca como completada sin consulta, se abre una vacía para llenarla después.",
    },
    {
        key: "show_status_change_history",
        label: "Mostrar el historial de estados de la cita",
        description: "En el detalle de cada cita se ve quién cambió su estado y cuándo.",
    },
];

// F2.3: la agenda calcula con ella la hora de fin de una cita nueva. Mismo rango y
// mensaje que el servidor (`validate_default_appointment_duration_minutes`).
export const DURATION_RANGE = { min: 5, max: 240 };
export const DURATION_MESSAGE = "La duración debe estar entre 5 y 240 minutos.";

export function durationError(value) {
    const number = Number(value);
    if (value === "" || !Number.isInteger(number)) return DURATION_MESSAGE;
    if (number < DURATION_RANGE.min || number > DURATION_RANGE.max) return DURATION_MESSAGE;
    return null;
}

export const BILLING_RULES = [
    {
        key: "require_open_cash_session",
        label: "Caja abierta obligatoria",
        description: "Para registrar un cobro o una devolución, quien lo hace necesita un turno de caja abierto a su nombre.",
        confirm: {
            on: {
                title: "Exigir caja abierta",
                message: "Cuando guardes, nadie podrá cobrar ni hacer devoluciones sin un turno de caja abierto a su nombre.",
                confirmText: "Exigir caja abierta",
            },
            off: {
                title: "Dejar de exigir caja abierta",
                message: "Cuando guardes, se podrá cobrar sin turno de caja. Esos cobros no entran en ningún corte de caja.",
                confirmText: "Dejar de exigirla",
            },
        },
    },
    {
        key: "allow_post_unpaid",
        label: "Permitir cobros a crédito",
        description: "Se puede emitir un cobro sin pagarlo en el momento, con vencimiento y la aceptación del cliente. Se paga después por el total; no hay pagos parciales.",
        confirm: {
            on: {
                title: "Permitir cobros a crédito",
                message: "Cuando guardes, se podrán emitir cobros sin pagarlos en el momento, con fecha de vencimiento y la aceptación del cliente.",
                confirmText: "Permitir crédito",
            },
            off: {
                title: "Dejar de permitir crédito",
                message: "Cuando guardes, todo cobro nuevo tendrá que pagarse completo al emitirlo. Los cobros a crédito que ya existen siguen pendientes de pago.",
                confirmText: "Dejar de permitirlo",
            },
        },
    },
];
