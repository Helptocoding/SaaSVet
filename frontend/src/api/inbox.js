import api from "./client";

// Bandeja del agente WhatsApp (É-F0 PR-7). `publicId` = Conversation.public_id
// (ADR p18: UUID en URLs, jamás PK).

// `getConversations` se retiró: la bandeja agrupa por persona (`getThreads`).
// Devolvía una fila por EPISODIO, que es lo que hacía que un cliente con 19
// conversaciones apareciera 19 veces. El endpoint sigue vivo hasta su Sunset
// (2026-11-30) por si algún cliente desconocido lo llama — pero no desde aquí.

export const getConversationMessages = (publicId) =>
  api.get(`inbox/conversations/${publicId}/messages/`).then((r) => r.data);

// Private binary: use the normal Bearer/session handling, never a storage URL.
export const getInboxMedia = (publicId, { signal } = {}) =>
  api.get(`inbox/media/${encodeURIComponent(publicId)}/`,
    { responseType: "blob", ...(signal ? { signal } : {}) }).then((r) => r.data);

// Bandeja AGRUPADA por persona (plan de continuidad §4). Una fila por
// `(contacto, cuenta)`: en producción un mismo cliente tenía 19 conversaciones
// y la bandeja las pintaba como 19 filas distintas.
//
// La ruta es COMPUESTA a propósito: con solo el contacto, una clínica con dos
// números tendría dos filas colisionando en un id.
export const getThreads = (params = {}, { signal } = {}) =>
  api.get("inbox/threads/", { params, ...(signal ? { signal } : {}) }).then((r) => r.data);

// Transcript del hilo COMPLETO (cruza sesiones) + la sesión vigente, que es
// contra la que se actúa. `before` es el cursor hacia atrás.
export const getThreadMessages = (contactId, accountId, params = {}, { signal } = {}) =>
  api
    .get(`inbox/threads/${contactId}/${accountId}/messages/`, { params, ...(signal ? { signal } : {}) })
    .then((r) => r.data);

// Resumen no clínico del cliente ya vinculado, cargado al abrir el panel.
export const getThreadContext = (contactId, accountId, { signal } = {}) =>
  api.get(`inbox/threads/${contactId}/${accountId}/context/`, signal ? { signal } : {})
    .then((r) => r.data);

// Lectura propia del staff por hilo; no modifica acuses del cliente en WhatsApp.
export const markThreadRead = (contactId, accountId, messageId, { signal } = {}) =>
  api.post(`inbox/threads/${contactId}/${accountId}/read/`,
    { last_read_message_id: messageId }, signal ? { signal } : {}).then((r) => r.data);

// Los episodios del hilo, del más reciente al más viejo.
export const getThreadSessions = (contactId, accountId, params = {}) =>
  api
    .get(`inbox/threads/${contactId}/${accountId}/sessions/`, { params })
    .then((r) => r.data);

export const sendInboxMessage = (publicId, body, idempotencyKey, { signal, replyToId } = {}) => {
  const url = `inbox/conversations/${publicId}/send/`;
  const payload = { body, ...(replyToId != null ? { reply_to_id: replyToId } : {}) };
  const config = {
    ...(idempotencyKey
      ? { headers: { "X-Idempotency-Key": idempotencyKey } }
      : {}),
    ...(signal ? { signal } : {}),
  };
  const request = Object.keys(config).length > 0
    ? api.post(url, payload, config)
    : api.post(url, payload);
  return request.then((r) => r.data);
};

export const retryInboxMessage = (publicId, messageId, idempotencyKey, { signal } = {}) =>
  api.post(`inbox/conversations/${publicId}/messages/${messageId}/retry/`, {}, {
    ...(idempotencyKey ? { headers: { "X-Idempotency-Key": idempotencyKey } } : {}),
    ...(signal ? { signal } : {}),
  }).then((r) => r.data);

export const claimConversation = (publicId) =>
  api.post(`inbox/conversations/${publicId}/claim/`).then((r) => r.data);

export const getAssignableUsers = ({ signal } = {}) =>
  api.get("inbox/assignable-users/", signal ? { signal } : {}).then((r) => r.data);

export const assignConversation = (publicId, userPublicId) =>
  api.post(`inbox/conversations/${publicId}/assign/`, { user_public_id: userPublicId }).then((r) => r.data);

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
