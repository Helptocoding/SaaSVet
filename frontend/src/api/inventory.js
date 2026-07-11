import api from "./client";

export const getProducts = (params = {}) =>
    api.get("inventory/products/", { params }).then(r => r.data);

export const getLowStockProducts = () =>
    api.get("inventory/products/low-stock/").then(r => r.data);

export const createProduct = (data) =>
    api.post("inventory/products/", data).then(r => r.data);

export const updateProduct = (id, data) =>
    api.patch(`inventory/products/${id}/`, data).then(r => r.data);

export const deleteProduct = (id) =>
    api.delete(`inventory/products/${id}/`);

export const adjustStock = (id, data) =>
    api.post(`inventory/products/${id}/adjust/`, data).then(r => r.data);

// Ajuste a una presentación específica (respeta su conversion_factor).
// Usado por la Entrada rápida de stock para soportar multi-presentación.
export const adjustPresentationStock = (presentationPublicId, data) =>
    api.post(`inventory/presentations/${presentationPublicId}/adjust/`, data).then(r => r.data);

export const getPresentationByBarcode = (barcode) =>
    api.get("inventory/presentations/barcode/", { params: { barcode } }).then(r => r.data);

// Recepción de mercancía multi-lote (B1). data = { supplier_name?, received_at?, lots: [{lot_number, expiry_date?, quantity}] }.
// Solo para productos con tracks_lots; el backend valida y convierte por conversion_factor.
export const receiveStock = (presentationPublicId, data) =>
    api.post(`inventory/presentations/${presentationPublicId}/receive/`, data).then(r => r.data);

// Lotes de un producto (orden FEFO). params: { with_stock: 'true' } para solo con saldo.
export const getProductLots = (productPublicId, params = {}) =>
    api.get(`inventory/products/${productPublicId}/lots/`, { params }).then(r => r.data);

// B2c — alertas de caducidad: { expiring_soon: [], expired_with_stock: [] }.
export const getLotAlerts = (params = {}) =>
    api.get("inventory/lots/alerts/", { params }).then(r => r.data);

// B2c — merma/descarte de un lote. data = { quantity?, reason? } (quantity en base-units; default = saldo).
export const discardLot = (lotPublicId, data = {}) =>
    api.post(`inventory/lots/${lotPublicId}/discard/`, data).then(r => r.data);

// B2c — estado del lote: { status: 'active' | 'quarantined' | 'recalled' }.
export const setLotStatus = (lotPublicId, data) =>
    api.post(`inventory/lots/${lotPublicId}/status/`, data).then(r => r.data);

export const getMovements = (params = {}) =>
    api.get("inventory/movements/", { params }).then(r => r.data);

export const getMedicalRecordProducts = (medicalRecordId) =>
    api.get(`medical-records/${medicalRecordId}/products/`).then(r => r.data);

export const addMedicalRecordProduct = (medicalRecordId, data) =>
    api.post(`medical-records/${medicalRecordId}/products/`, data).then(r => r.data);

export const removeMedicalRecordProduct = (medicalRecordId, id) =>
    api.delete(`medical-records/${medicalRecordId}/products/${id}/`);

export const getUnitChoices = () =>
    api.get("inventory/units/").then(r => r.data);

export const getPresentations = (params = {}) =>
    api.get("inventory/presentations/", { params }).then(r => r.data);

export const createPresentation = (productPublicId, data) =>
    api.post(`inventory/products/${productPublicId}/presentations/`, data).then(r => r.data);

export const updatePresentation = (presentationPublicId, data) =>
    api.patch(`inventory/presentations/${presentationPublicId}/`, data).then(r => r.data);
