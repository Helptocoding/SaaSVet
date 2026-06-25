import api from "./client";

// ADR p46 — aceptación legal. La app NO duplica el texto legal (vive en la
// landing, www.saaslyvet.com); aquí solo se listan los documentos vigentes
// requeridos para el rol del usuario y se registra la aceptación.

export const getCurrentLegal = async () => {
    const res = await api.get("legal/current/");
    return res.data; // { documents: [{public_id, doc_type, version, landing_url, accepted}], acceptance_required }
};

export const acceptLegal = async (publicIds) => {
    const res = await api.post("legal/accept/", { document_public_ids: publicIds });
    return res.data; // { acceptance_required }
};
