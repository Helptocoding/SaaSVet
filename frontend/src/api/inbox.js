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

// Revoca un vínculo familiar secundario (PR-17b).
export const unlinkFamily = (publicId) =>
  api.post(`inbox/conversations/${publicId}/unlink-family/`).then((r) => r.data);

// Resetea la identidad del contacto a "unknown" (cualquier vínculo, no solo
// familiar) y cierra el hilo activo. Solo ADMIN.
export const resetContactIdentity = (publicId) =>
  api.post(`inbox/conversations/${publicId}/reset-identity/`).then((r) => r.data);

// FLUJO-C (ADR p57 §5.5): verificar y autorizar son DOS acciones, no una con
// un booleano. La primera registra el juicio humano (no vincula nada); la
// segunda ejecuta la consecuencia y exige una verificación aprobada de ESTE
// mismo caso y candidato. Ambas piden `agentinbox.identity_verify`.
export const verifyContactIdentity = (publicId, data) =>
  api
    .post(`inbox/conversations/${publicId}/verify-identity/`, data)
    .then((r) => r.data);

export const authorizeIdentityLink = (publicId, ownerPublicId) =>
  api
    .post(`inbox/conversations/${publicId}/authorize-identity/`, {
      owner_public_id: ownerPublicId,
    })
    .then((r) => r.data);

export const getAgentSettings = () =>
  api.get("inbox/settings/").then((r) => r.data);

export const updateAgentSettings = (data) =>
  api.patch("inbox/settings/", data).then((r) => r.data);

// Métricas de negocio del piloto F2 (spec §8). params: { from, to } YYYY-MM-DD.
export const getInboxMetrics = (params = {}) =>
  api.get("inbox/metrics/", { params }).then((r) => r.data);

// Token de WhatsApp (write-only). GET → { configured, last4 }; POST { token }.
export const getWhatsappToken = () =>
  api.get("inbox/whatsapp-token/").then((r) => r.data);
export const setWhatsappToken = (token) =>
  api.post("inbox/whatsapp-token/", { token }).then((r) => r.data);
