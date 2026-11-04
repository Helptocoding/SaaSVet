import api from "./client";

// Importador CSV/Excel (migración de clientes + mascotas).
// El backend es la fuente de verdad: este módulo solo transporta el ImportJob.
// IDs en URLs = public_id (UUID), nunca el PK entero (ADR p18).

// Sube el archivo (.csv / .xlsx) y crea el ImportJob. Multipart explícito.
export const uploadImport = (file, entityType = "owner_pet") => {
    const form = new FormData();
    form.append("entity_type", entityType);
    form.append("file", file);
    return api
        .post("imports/", form, { headers: { "Content-Type": "multipart/form-data" } })
        .then(r => r.data);
};

export const listImports = () =>
    api.get("imports/").then(r => r.data);

export const getImport = (publicId) =>
    api.get(`imports/${publicId}/`).then(r => r.data);

export const getImportConflicts = (publicId, params) =>
    api.get(`imports/${publicId}/conflicts/`, { params }).then(r => r.data);

// Confirma el mapeo columna→campo (y opcionalmente la estrategia de duplicados).
export const setMapping = (publicId, { mapping, dedup_strategy } = {}) => {
    const body = { mapping };
    if (dedup_strategy !== undefined) body.dedup_strategy = dedup_strategy;
    return api.patch(`imports/${publicId}/mapping/`, body).then(r => r.data);
};

// Dry-run: valida fila×fila sin escribir nada. Llena `result`.
export const validateImport = (publicId) =>
    api.post(`imports/${publicId}/validate/`).then(r => r.data);

// Escribe en la base. Idempotente: re-commit → 409.
export const commitImport = (publicId) =>
    api.post(`imports/${publicId}/commit/`).then(r => r.data);
