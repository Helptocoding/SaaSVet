export const notificationActions = {
  appointment_upcoming: () => ({ label: "Ver cita", to: "/appointments" }),
  appointment_delayed: () => ({ label: "Ver cita", to: "/appointments" }),
  stock_low_entered: () => ({ label: "Ver inventario", to: "/inventory" }),
  stock_out: () => ({ label: "Ver inventario", to: "/inventory" }),
  cash_difference: () => ({ label: "Ver caja", to: "/cash" }),
};

export function getNotificationAction(item) {
  const fn = notificationActions[item?.type];
  return fn ? fn(item) : null;
}

export function formatRelativeTime(isoString) {
  if (!isoString) return "";
  const then = new Date(isoString).getTime();
  if (Number.isNaN(then)) return "";
  const diffMin = Math.round((Date.now() - then) / 60000);
  if (diffMin < 0) {
    const untilMin = Math.abs(diffMin);
    if (untilMin < 1) return "en menos de 1 min";
    if (untilMin < 60) return `en ${untilMin} min`;
    const hours = Math.round(untilMin / 60);
    if (hours < 24) return `en ${hours} h`;
    return `en ${Math.round(hours / 24)} d`;
  }
  if (diffMin < 1) return "ahora mismo";
  if (diffMin < 60) return `hace ${diffMin} min`;
  const hours = Math.round(diffMin / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.round(hours / 24);
  return `hace ${days} d`;
}
