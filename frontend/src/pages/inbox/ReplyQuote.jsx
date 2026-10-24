import styles from "./inbox.module.css";

const labels = { agent: "Asistente", system: "Automático", human_staff: "Staff" };

export default function ReplyQuote({ reply, contactName, onJump, busy = false }) {
    if (!reply || !Number.isSafeInteger(reply.id) || reply.id <= 0) return null;
    const author = reply.author_type === "client" ? contactName
        : (reply.human_author_name || labels[reply.author_type] || "Staff");
    const media = reply.payload_type && reply.payload_type !== "text";
    const notSent = ["discarded", "failed"].includes(reply.status);
    return (
        <button type="button" className={styles.replyQuote}
            aria-label={`Ir al mensaje original de ${author}`} aria-busy={busy} disabled={busy}
            onClick={() => onJump(reply.id)}>
            <strong>{author}</strong>
            {media && <span className={styles.quoteMedia}><span aria-hidden="true">📷 </span>{reply.payload_type}</span>}
            <span className={styles.quoteExcerpt}>{reply.excerpt || "Contenido no disponible"}</span>
            {notSent && <span className={styles.quoteNotSent}>Mensaje no enviado</span>}
        </button>
    );
}
