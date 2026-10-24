const MAX_GROUP_GAP_MS = 5 * 60 * 1000;

const sameAuthor = (previous, current) => {
    if (previous.direction !== current.direction) return false;
    // La entrada ya pertenece a un único hilo (contacto + cuenta).
    if (current.direction === "in") return true;
    if (current.direction !== "out" || previous.author_type !== current.author_type) return false;
    if (current.author_type === "human_staff") {
        // Sin identidad (legacy o temporal optimista), mantener la burbuja
        // separada. Ni el nombre ni el cuerpo prueban que sea la misma persona.
        return Boolean(current.human_author_public_id)
            && previous.human_author_public_id === current.human_author_public_id;
    }
    return current.author_type === "agent" || current.author_type === "system";
};

// Recibe los mensajes de UN día local, ya ordenados por el transcript.
// Sólo agrupa presentación: conserva referencias, ids, orden y estados.
export const groupConsecutiveMessages = (messages) => {
    const groups = [];
    for (const message of messages) {
        const last = groups[groups.length - 1];
        const previous = last?.messages[last.messages.length - 1];
        const gap = previous ? Date.parse(message.created_at) - Date.parse(previous.created_at) : NaN;
        if (previous && Number.isFinite(gap) && gap >= 0 && gap < MAX_GROUP_GAP_MS
            && sameAuthor(previous, message)) {
            last.messages.push(message);
        } else {
            groups.push({ key: message.id, messages: [message] });
        }
    }
    return groups;
};
