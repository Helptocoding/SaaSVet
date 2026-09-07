import styles from "./KpiStrip.module.css";

function formatValue(item) {
  const v = item.value;
  if (v == null) return "—";
  if (item.format === "currency") {
    return `$${Number(v).toLocaleString("es-MX")}`;
  }
  return v;
}

const TONE_CLASS = {
  default: styles.numberDefault,
  warning: styles.numberWarning,
  danger:  styles.numberDanger,
};

const CARD_TONE_CLASS = {
  default: styles.cardDefault,
  warning: styles.cardWarning,
  danger:  styles.cardDanger,
};

export default function KpiStrip({ items }) {
  if (!items || items.length === 0) return null;

  return (
    <div className={styles.strip}>
      {items.map((item) => {
        const isZero  = item.value == null || Number(item.value) === 0;
        const toneKey = isZero ? "default" : (item.tone || "default");
        const numberClass = `${styles.number} ${TONE_CLASS[toneKey] || styles.numberDefault}`;
        const cardClass = `${styles.card} ${CARD_TONE_CLASS[toneKey] || styles.cardDefault}`;

        return (
          <article key={item.label} className={cardClass}>
            <div className={styles.header}>
              <span className={styles.label}>{item.label}</span>
              <span className={styles.toneMark} aria-hidden="true" />
            </div>
            <span className={numberClass}>{formatValue(item)}</span>
            <div className={styles.footer}>
              {item.live ? (
                <span className={styles.pill}>
                  <span className={styles.pillDot} />
                  en vivo
                </span>
              ) : (
                <span className={styles.updated}>Resumen de hoy</span>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}
