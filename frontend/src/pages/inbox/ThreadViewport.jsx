import { useRef, useState } from "react";
import styles from "./inbox.module.css";

export default function ThreadViewport({ children, viewportRef, onReachStart, onViewportScroll, onGoToEnd, newBelow = 0 }) {
    const localScrollRef = useRef(null);
    const scrollRef = viewportRef || localScrollRef;
    const [awayFromBottom, setAwayFromBottom] = useState(false);

    const handleScroll = ({ currentTarget }) => {
        const distance = currentTarget.scrollHeight - currentTarget.clientHeight - currentTarget.scrollTop;
        setAwayFromBottom(distance > 200);
        onViewportScroll?.(currentTarget);
        if (currentTarget.scrollTop < 160) onReachStart?.();
    };
    const goToEnd = () => {
        const area = scrollRef.current;
        if (!area) return;
        if (onGoToEnd) onGoToEnd();
        else {
            area.scrollTo({ top: area.scrollHeight, behavior: "auto" });
            area.focus({ preventScroll: true });
        }
        setAwayFromBottom(false);
    };

    const label = newBelow > 0
        ? `${newBelow} ${newBelow === 1 ? "mensaje nuevo" : "mensajes nuevos"}`
        : "Ir al final";
    return (
        <div className={styles.threadViewport}>
            <div ref={scrollRef} className={styles.thread} onScroll={handleScroll}
                role="region" aria-label="Mensajes de la conversación" tabIndex={0}>
                {children}
            </div>
            {(newBelow > 0 || awayFromBottom) && (
                <button type="button" className={styles.goToEnd} aria-label={label}
                    aria-live={newBelow > 0 ? "polite" : undefined}
                    onClick={goToEnd}>
                    <span aria-hidden="true">↓ </span>{label}
                </button>
            )}
        </div>
    );
}
