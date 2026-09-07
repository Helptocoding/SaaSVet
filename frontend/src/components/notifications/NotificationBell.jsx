import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../icons";
import { useNotifications } from "../../hooks/useNotifications";
import { formatRelativeTime, getNotificationAction } from "./notificationActions";
import styles from "./NotificationBell.module.css";

const TYPE_ICON = {
  appointment_upcoming: "CalendarClock",
  appointment_delayed: "AlertTriangle",
  stock_low_entered: "Boxes",
  stock_out: "AlertOctagon",
  cash_difference: "Wallet",
};

function Item({ item, onSeen, onNavigate }) {
  const action = getNotificationAction(item);
  const iconName = TYPE_ICON[item.type] || "Info";
  const ItemIcon = Icon[iconName] || Icon.Info;
  return (
    <div
      className={`${styles.item} ${item.seen ? styles.itemSeen : styles.itemNew}`}
      role="option"
      aria-selected={!item.seen}
      tabIndex={0}
      onClick={() => onSeen(item)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSeen(item);
      }}
    >
      <span className={`${styles.dot} ${item.seen ? styles.dotSeen : styles[`dot_${item.priority}`] || styles.dot_attention}`} />
      <span className={styles.itemIcon}>
        <ItemIcon s={18} />
      </span>
      <span className={styles.itemBody}>
        <span className={styles.itemTitle}>{item.title}</span>
        {item.body && <span className={styles.itemContext}>{item.body}</span>}
        <span className={styles.itemMeta}>
          {formatRelativeTime(item.occurred_at)}
          {action && (
            <button
              className={styles.itemCta}
              onClick={(e) => {
                e.stopPropagation();
                onNavigate(item, action);
              }}
            >
              {action.label}
            </button>
          )}
        </span>
      </span>
    </div>
  );
}

export default function NotificationBell() {
  const { items, unseenCount, loading, error, refetch, seen, seenAll } = useNotifications();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (e.key === "Escape") setOpen(false);
      if (e.type === "mousedown" && wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onDown);
    };
  }, [open ]);

  const handleSeen = (item) => {
    if (!item.seen) seen(item.key);
  };

  const handleNavigate = (item, action) => {
    if (!item.seen) seen(item.key);
    setOpen(false);
    navigate(action.to);
  };

  const fresh = items.filter((i) => !i.seen);
  const previous = items.filter((i) => i.seen);
  const label = unseenCount > 9 ? "9+" : String(unseenCount);

  return (
    <div className={styles.wrap} ref={wrapRef}>
      <button
        className={styles.bell}
        onClick={() => setOpen((v) => !v)}
        aria-label={unseenCount > 0 ? `Notificaciones, ${unseenCount} sin leer` : "Notificaciones"}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <Icon.Bell s={20} />
        {unseenCount > 0 && <span className={styles.badge}>{label}</span>}
      </button>
      {open && (
        <div className={styles.popover} role="dialog" aria-label="Notificaciones">
          <div className={styles.head}>
            <span className={styles.title}>Notificaciones</span>
            <button className={styles.markAll} onClick={seenAll} disabled={unseenCount === 0}>
              Marcar todas como leídas
            </button>
          </div>
          <div className={styles.list} role="listbox" aria-label="Lista de notificaciones">
            {loading && <p className={styles.state}>Cargando…</p>}
            {!loading && error && (
              <p className={styles.state}>
                {error} <button className={styles.retry} onClick={refetch}>Reintentar</button>
              </p>
            )}
            {!loading && !error && items.length === 0 && (
              <p className={styles.state}>Todo al día. Sin notificaciones nuevas.</p>
            )}
            {!loading && !error && fresh.length > 0 && (
              <>
                <p className={styles.section}>Nuevas</p>
                {fresh.map((item) => (
                  <Item key={item.key} item={item} onSeen={handleSeen} onNavigate={handleNavigate} />
                ))}
              </>
            )}
            {!loading && !error && previous.length > 0 && (
              <>
                <p className={styles.section}>Anteriores</p>
                {previous.map((item) => (
                  <Item key={item.key} item={item} onSeen={handleSeen} onNavigate={handleNavigate} />
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
