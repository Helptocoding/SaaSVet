import api from "./client";

// Servicios
export const getServices = (params = {}) =>
    api.get("billing/services/", { params }).then(r => r.data);

export const createService = (data) =>
    api.post("billing/services/", data).then(r => r.data);

export const updateService = (id, data) =>
    api.patch(`billing/services/${id}/`, data).then(r => r.data);

export const deleteService = (id) =>
    api.delete(`billing/services/${id}/`);

// Facturas
export const getInvoices = (params = {}) =>
    api.get("billing/invoices/", { params }).then(r => r.data);

export const getInvoice = (id) =>
    api.get(`billing/invoices/${id}/`).then(r => r.data);

export const createInvoice = (data) =>
    api.post("billing/invoices/", data).then(r => r.data);

export const updateInvoice = (id, data) =>
    api.patch(`billing/invoices/${id}/`, data).then(r => r.data);

export const confirmInvoice = (id) =>
    api.patch(`billing/invoices/${id}/confirm/`).then(r => r.data);

// ADR p27: pago único (legacy `paymentMethod`), split o parcial (`paymentLines`
// = [{ method, amount }]), con `idempotencyKey` opcional (anti doble-cobro en
// reintento de red — header X-Idempotency-Key).
const _payBody = ({ paymentLines, paymentMethod }) =>
    paymentLines && paymentLines.length
        ? { payment_lines: paymentLines }
        : { payment_method: paymentMethod };

const _idemConfig = (idempotencyKey) =>
    idempotencyKey ? { headers: { "X-Idempotency-Key": idempotencyKey } } : {};

export const payInvoice = (id, { paymentLines, paymentMethod, idempotencyKey } = {}) =>
    api.patch(`billing/invoices/${id}/pay/`, _payBody({ paymentLines, paymentMethod }), _idemConfig(idempotencyKey))
        .then(r => r.data);

export const directPayInvoice = (id, { paymentLines, paymentMethod, idempotencyKey } = {}) =>
    api.post(`billing/invoices/${id}/direct-pay/`, _payBody({ paymentLines, paymentMethod }), _idemConfig(idempotencyKey))
        .then(r => r.data);

// Ítems de factura
export const addInvoiceItem = (invoiceId, data) =>
    api.post(`billing/invoices/${invoiceId}/items/`, data).then(r => r.data);

export const updateInvoiceItem = (invoiceId, itemId, data) =>
    api.patch(`billing/invoices/${invoiceId}/items/${itemId}/`, data).then(r => r.data);

export const deleteInvoiceItem = (invoiceId, itemId) =>
    api.delete(`billing/invoices/${invoiceId}/items/${itemId}/`);

export const downloadInvoicePDF = (publicId) =>
    api.get(`billing/invoices/${publicId}/pdf/`, { responseType: "blob" })
        .then(r => ({ blob: r.data, contentDisposition: r.headers["content-disposition"] }));
