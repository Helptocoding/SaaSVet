const LEVELS = {
    staff_verified: {
        label: "Verificado",
        className: "badge-success",
        description: "Identidad verificada por el personal de la clínica.",
    },
    confirmed_in_chat: {
        label: "Verificado",
        className: "badge-success",
        description: "Identidad confirmada mediante verificación en la conversación.",
    },
    phone_match: {
        label: "Teléfono coincide",
        className: "badge-warning",
        description: "El teléfono coincide con un cliente registrado; la identidad aún no está verificada.",
    },
};

export default function ContactVerificationBadge({ level }) {
    const badge = Object.hasOwn(LEVELS, level) ? LEVELS[level] : null;
    if (!badge) return null;
    return <span className={`badge ${badge.className}`} title={badge.description}>{badge.label}</span>;
}
