import api from "./client";

// Bandeja del agente WhatsApp (É-F0 PR-7). `publicId` = Conversation.public_id
// (ADR p18: UUID en URLs, jamás PK).

export const getConversations = (params = {}) =>
  api.get("inbox/conversations/", { params }).then((r) => r.data);

export const getConversationMessages = (publicId) =>
  api.get(`inbox/conversations/${publicId}/messages/`).then((r) => r.data);

export const sendInboxMessage = (publicId, body) =>
  api.post(`inbox/conversations/${publicId}/send/`, { body }).then((r) => r.data);

export const claimConversation = (publicId) =>
  api.post(`inbox/conversations/${publicId}/claim/`).then((r) => r.data);

export const closeConversation = (publicId) =>
  api.post(`inbox/conversations/${publicId}/close/`).then((r) => r.data);

export const releaseConversation = (publicId) =>
  api.post(`inbox/conversations/${publicId}/release/`).then((r) => r.data);

export const getAgentSettings = () =>
  api.get("inbox/settings/").then((r) => r.data);

export const updateAgentSettings = (data) =>
  api.patch("inbox/settings/", data).then((r) => r.data);

// Métricas de negocio del piloto F2 (spec §8). params: { from, to } YYYY-MM-DD.
export const getInboxMetrics = (params = {}) =>
  api.get("inbox/metrics/", { params }).then((r) => r.data);
