import api from "./client";

export async function getNotificationFeed(limit = 20) {
  const { data } = await api.get("v1/notifications/feed/", { params: { limit } });
  return data;
}

export async function markNotificationSeen(key) {
  const { data } = await api.post(`v1/notifications/${encodeURIComponent(key)}/seen/`);
  return data;
}

export async function markAllNotificationsSeen() {
  const { data } = await api.post("v1/notifications/seen-all/");
  return data;
}
