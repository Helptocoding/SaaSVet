import api from "./client";

export const getDashboardSummary = () =>
    api.get("v1/dashboard/summary/").then((r) => r.data);

// Activación de la clínica (primer uso): existencia real de los hitos de arranque.
// Read-only, sin flags persistidos. Alimenta el SetupChecklist del dashboard.
export const getActivation = () =>
    api.get("v1/dashboard/activation/").then((r) => r.data);
