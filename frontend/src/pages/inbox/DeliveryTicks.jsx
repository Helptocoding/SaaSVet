import styles from "./inbox.module.css";

const DELIVERY_STATE = {
    pending: { glyph: "⏱", label: "Pendiente de envío", tone: "pending" },
    sent: { glyph: "✓", label: "Enviado" },
    delivered: { glyph: "✓✓", label: "Entregado" },
    read: { glyph: "✓✓", label: "Leído", tone: "read" },
    failed: { glyph: "⚠", label: "No entregado", tone: "failed" },
    "failed-local": { glyph: "⚠", label: "No se pudo enviar", tone: "failed" },
    discarded: { glyph: "⚠", label: "Descartado", tone: "failed" },
};

const TONE_CLASS = {
    pending: styles.deliveryTickPending,
    read: styles.deliveryTickRead,
    failed: styles.deliveryTickFailed,
};

/** Estado de entrega del canal. Los entrantes no tienen recibo de salida. */
const DeliveryTicks = ({ status, direction, failure_reason: failureReason }) => {
    if (direction !== "out") return null;
    const state = DELIVERY_STATE[status];
    if (!state) return null;

    const detail = failureReason?.trim();
    const accessibleLabel = detail && ["failed", "failed-local", "discarded"].includes(status)
        ? `${state.label}: ${detail}`
        : state.label;

    return (
        <span
            className={[styles.deliveryTick, TONE_CLASS[state.tone]].filter(Boolean).join(" ")}
            aria-label={accessibleLabel}
            title={accessibleLabel}
        >
            {state.glyph}
        </span>
    );
};

export default DeliveryTicks;
