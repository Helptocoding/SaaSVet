import EmptyState from "../../components/EmptyState";
import styles from "./inbox.module.css";

export function InboxLoading({ label }) {
    return (
        <div className={styles.loadingState} role="status" aria-label={label}>
            <span>{label}…</span>
            {[0, 1, 2].map((row) => <span key={row} className={styles.loadingRow} aria-hidden="true" />)}
        </div>
    );
}

export function InboxLoadError({ title, error, onRetry }) {
    return (
        <div role="alert" aria-label={title}>
            <EmptyState compact title={title} body={error}
                actions={onRetry ? [{ label: "Reintentar ahora", onClick: onRetry }] : []} />
        </div>
    );
}

export function InboxConnectionBanner({ panel, retrying, onRetry }) {
    return (
        <div className={styles.connectionBanner} role="status" aria-label={`${panel}: sin conexión`}>
            <span><strong>{panel}</strong> · Sin conexión — reintentando…</span>
            <button type="button" className="btn btn-secondary btn-xs" disabled={retrying} onClick={onRetry}>
                {retrying ? "Reintentando…" : "Reintentar ahora"}
            </button>
        </div>
    );
}
