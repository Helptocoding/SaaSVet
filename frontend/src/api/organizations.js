import api from "./client";

export const getOrgSettings = () =>
    api.get("organizations/settings/").then(r => r.data);

export const updateOrgSettings = (data) =>
    api.patch("organizations/settings/", data).then(r => r.data);

export const updateOrg = (data) =>
    api.patch("organizations/me/", data).then(r => r.data);

export const getConfiguration = () =>
    api.get("settings/configuration/").then(r => r.data);

export const getSchedule = () =>
    api.get("organizations/schedule/").then(r => r.data);

export const replaceSchedule = (data) =>
    api.put("organizations/schedule/", data).then(r => r.data);

// ADR p70 D9: historial de cambios de Configuración, paginado (25 por página).
export const getConfigHistory = ({ page = 1 } = {}) =>
    api.get("organizations/config-history/", { params: { page } }).then(r => r.data);

// ADR p70 D6 (plan F2.1): cierres excepcionales. GET da los vigentes desde hoy.
export const getClosures = () =>
    api.get("organizations/closures/").then(r => r.data);

export const createClosure = (data) =>
    api.post("organizations/closures/", data).then(r => r.data);

export const cancelClosure = (publicId) =>
    api.post(`organizations/closures/${publicId}/cancel/`).then(r => r.data);
