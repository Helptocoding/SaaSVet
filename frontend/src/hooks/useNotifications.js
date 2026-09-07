import { useCallback, useEffect, useRef, useState } from "react";
import { getNotificationFeed, markAllNotificationsSeen, markNotificationSeen } from "../api/notifications";
import { apiError } from "../utils/apiError";

const POLL_INTERVAL = 60_000;

export function useNotifications() {
  const [items, setItems] = useState([]);
  const [unseenCount, setUnseenCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);
  const mountedRef = useRef(true);

  const fetch = useCallback(async () => {
    try {
      const data = await getNotificationFeed(20);
      if (mountedRef.current) {
        setItems(data.items || []);
        setUnseenCount(data.unseen_count || 0);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(apiError(err, "No se pudieron cargar las notificaciones"));
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetch();
    timerRef.current = setInterval(fetch, POLL_INTERVAL);
    const onRefresh = () => fetch();
    const onFocus = () => fetch();
    window.addEventListener("dashboard:refresh", onRefresh);
    window.addEventListener("notifications:refresh", onRefresh);
    window.addEventListener("focus", onFocus);
    return () => {
      mountedRef.current = false;
      clearInterval(timerRef.current);
      window.removeEventListener("dashboard:refresh", onRefresh);
      window.removeEventListener("notifications:refresh", onRefresh);
      window.removeEventListener("focus", onFocus);
    };
  }, [fetch]);

  const seen = useCallback(async (key) => {
    setItems((prev) => prev.map((i) => (i.key === key ? { ...i, seen: true } : i)));
    setUnseenCount((prev) => Math.max(0, prev - 1));
    try {
      await markNotificationSeen(key);
      window.dispatchEvent(new CustomEvent("notifications:refresh"));
    } catch {
      fetch();
    }
  }, [fetch]);

  const seenAll = useCallback(async () => {
    setItems((prev) => prev.map((i) => ({ ...i, seen: true })));
    setUnseenCount(0);
    try {
      await markAllNotificationsSeen();
      window.dispatchEvent(new CustomEvent("notifications:refresh"));
    } catch {
      fetch();
    }
  }, [fetch]);

  return { items, unseenCount, loading, error, refetch: fetch, seen, seenAll };
}
