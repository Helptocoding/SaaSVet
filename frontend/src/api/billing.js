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
// Checkout aditivo: preparación comercial separada de Invoice.
export const getCheckouts = (params = {}) =>
    api.get("billing/checkouts/", { params }).then(r => r.data);

export const getCheckout = (id) =>
    api.get(`billing/checkouts/${id}/`).then(r => r.data);

export const createDirectSaleCheckout = (data) =>
    api.post("billing/checkouts/direct-sale/", data).then(r => r.data);

export const addCheckoutItem = (checkoutId, data) =>
    api.post(`billing/checkouts/${checkoutId}/items/`, data).then(r => r.data);

export const updateCheckoutItem = (checkoutId, itemId, data) =>
    api.patch(`billing/checkouts/${checkoutId}/items/${itemId}/`, data).then(r => r.data);

export const deleteCheckoutItem = (checkoutId, itemId, data = {}) =>
    api.delete(`billing/checkouts/${checkoutId}/items/${itemId}/`, { data }).then(r => r.data);

export const attestExternalPrescription = (checkoutId, itemId, {
    prescriberName, prescriptionFolio = "", notes = "", correctionReason = "",
    expectedVersion, idempotencyKey,
} = {}) => api.post(
    `billing/checkouts/${checkoutId}/items/${itemId}/external-prescription-attestations/`,
    {
        prescriber_name: prescriberName,
        prescription_folio: prescriptionFolio,
        notes,
        correction_reason: correctionReason,
        expected_version: expectedVersion,
    },
    _idemConfig(idempotencyKey),
).then(r => r.data);

export const createPrescriptionSupplement = (medicalRecordId, { idempotencyKey } = {}) =>
    api.post(
        `medical-records/${medicalRecordId}/prescription-supplements/`,
        {},
        _idemConfig(idempotencyKey),
    ).then(r => r.data);

export const postCheckout = (id, {
    expectedVersion, dueAt, creditReason, obligationEvidence, idempotencyKey,
} = {}) =>
    api.post(`billing/checkouts/${id}/post/`, {
        expected_version: expectedVersion,
        due_at: dueAt,
        credit_reason: creditReason,
        obligation_evidence: obligationEvidence,
    }, _idemConfig(idempotencyKey)).then(r => r.data);

export const decidePrescriptionItem = (checkoutId, prescriptionItemId, {
    decision, reasonCode, expectedVersion,
} = {}) => api.post(
    `billing/checkouts/${checkoutId}/prescriptions/${prescriptionItemId}/decision/`,
    { decision, reason_code: reasonCode, expected_version: expectedVersion },
).then(r => r.data);

export const issueCheckoutEstimate = (id, { expectedVersion, idempotencyKey } = {}) =>
    api.post(`billing/checkouts/${id}/estimate/`, {
        expected_version: expectedVersion,
    }, _idemConfig(idempotencyKey)).then(r => r.data);

export const downloadCheckoutEstimatePDF = (id) =>
    api.get(`billing/checkout-estimates/${id}/pdf/`, { responseType: 'blob' })
        .then(r => ({ blob: r.data, contentDisposition: r.headers['content-disposition'] }));

export const payCheckout = (id, { paymentLines, paymentMethod, expectedVersion, idempotencyKey } = {}) =>
    api.post(`billing/checkouts/${id}/pay/`, {
        ..._payBody({ paymentLines, paymentMethod }),
        expected_version: expectedVersion,
    }, _idemConfig(idempotencyKey)).then(r => r.data);

export const completeCheckoutNoCharge = (id, { reason, expectedVersion, idempotencyKey } = {}) =>
    api.post(`billing/checkouts/${id}/complete-no-charge/`, {
        reason,
        expected_version: expectedVersion,
    }, _idemConfig(idempotencyKey)).then(r => r.data);

export const abandonCheckout = (id, { reason, expectedVersion, idempotencyKey } = {}) =>
    api.post(`billing/checkouts/${id}/abandon/`, {
        reason,
        expected_version: expectedVersion,
    }, _idemConfig(idempotencyKey)).then(r => r.data);

export const openCheckoutDispute = (id, {
    itemIds, statement, owner, reviewDueAt, evidence = {}, expectedVersion, idempotencyKey,
} = {}) => api.post(`billing/checkouts/${id}/disputes/`, {
    item_ids: itemIds,
    statement,
    owner,
    review_due_at: reviewDueAt,
    evidence,
    expected_version: expectedVersion,
}, _idemConfig(idempotencyKey)).then(r => r.data);

export const resolveCheckoutDispute = (id, {
    resolution, reason, resolutionEvidence = {}, adjustments = [], dueAt,
    obligationEvidence = {}, expectedVersion, idempotencyKey,
} = {}) => api.post(`billing/checkout-disputes/${id}/resolve/`, {
    resolution,
    reason,
    resolution_evidence: resolutionEvidence,
    adjustments,
    due_at: dueAt,
    obligation_evidence: obligationEvidence,
    expected_version: expectedVersion,
}, _idemConfig(idempotencyKey)).then(r => r.data);

export const resolveCollectionCase = (id, {
    resolution = "customer_withdrew", reason, evidence = {}, idempotencyKey,
} = {}) => api.post(`billing/collection-cases/${id}/resolve/`, {
    resolution,
    reason,
    evidence,
}, _idemConfig(idempotencyKey)).then(r => r.data);

export const adjustReplacementExposure = (id, {
    itemId, amount, reasonCode, note, evidence = {}, expectedVersion, idempotencyKey,
} = {}) => api.post(`billing/checkouts/${id}/adjust-replacement-exposure/`, {
    item_id: itemId,
    amount,
    reason_code: reasonCode,
    note,
    evidence,
    expected_version: expectedVersion,
}, _idemConfig(idempotencyKey)).then(r => r.data);

export const assignReplacementOwner = (id, {
    owner, correctionDueAt, reasonCode, expectedVersion, idempotencyKey,
} = {}) => api.post(`billing/checkouts/${id}/assign-replacement-owner/`, {
    owner,
    correction_due_at: correctionDueAt,
    reason_code: reasonCode,
    expected_version: expectedVersion,
}, _idemConfig(idempotencyKey)).then(r => r.data);

export const waiveReplacement = (id, { reasonCode, evidence = {}, expectedVersion, idempotencyKey } = {}) =>
    api.post(`billing/checkouts/${id}/waive-replacement/`, {
        reason_code: reasonCode,
        evidence,
        expected_version: expectedVersion,
    }, _idemConfig(idempotencyKey)).then(r => r.data);

export const getInvoices = (params = {}) =>
    api.get("billing/invoices/", { params }).then(r => r.data);

export const getInvoice = (id) =>
    api.get(`billing/invoices/${id}/`).then(r => r.data);

// Un comando de pago puede contener varias líneas (split), pero siempre cubre
// exactamente el total pendiente. La clave idempotente evita doble cobro.
const _payBody = ({ paymentLines, paymentMethod }) =>
    paymentLines && paymentLines.length
        ? { payment_lines: paymentLines }
        : { payment_method: paymentMethod };

const _idemConfig = (idempotencyKey) =>
    idempotencyKey ? { headers: { "X-Idempotency-Key": idempotencyKey } } : {};

export const voidAndPrepareReplacement = (invoiceId, {
    reason = "correction", correctionDueAt, dispositions = [], idempotencyKey,
} = {}) =>
    api.post(`billing/invoices/${invoiceId}/void-and-prepare-replacement/`, {
        reason,
        correction_due_at: correctionDueAt,
        dispositions,
    }, _idemConfig(idempotencyKey)).then(r => r.data);

export const voidInvoiceTerminal = (invoiceId, {
    reasonCode, reasonNotes, dispositions = [], idempotencyKey,
} = {}) => api.post(`billing/invoices/${invoiceId}/void/`, {
    reason_code: reasonCode,
    reason_notes: reasonNotes,
    dispositions,
}, _idemConfig(idempotencyKey)).then(r => r.data);

export const payInvoice = (id, { paymentLines, paymentMethod, idempotencyKey } = {}) =>
    api.patch(`billing/invoices/${id}/pay/`, _payBody({ paymentLines, paymentMethod }), _idemConfig(idempotencyKey))
        .then(r => r.data);

// ADR p29: devolución (nota de crédito + reembolso) sobre factura pagada.
// creditLines = [{ invoice_item: <PK>, quantity, amount, disposition }],
// refundLines = [{ method, amount }]; refund_sum debe igualar Σ credit amounts.
// idempotencyKey obligatorio (X-Idempotency-Key, anti doble-reembolso).
export const refundInvoice = (
    id,
    { creditLines, refundLines, reasonCode, reasonNotes = "", idempotencyKey } = {},
) =>
    api.post(
        `billing/invoices/${id}/refund/`,
        {
            credit_lines: creditLines,
            refund_lines: refundLines,
            reason_code: reasonCode,
            reason_notes: reasonNotes,
        },
        _idemConfig(idempotencyKey),
    ).then(r => r.data);

// ADR p29: contra-asiento de una nota de crédito (revertir devolución emitida
// por error). Append-only — no edita ni borra.
export const reverseCreditNote = (
    publicId,
    { reasonCode = "", reasonNotes = "", idempotencyKey } = {},
) =>
    api.post(
        `billing/credit-notes/${publicId}/reverse/`,
        { reason_code: reasonCode, reason_notes: reasonNotes },
        _idemConfig(idempotencyKey),
    ).then(r => r.data);

// La dispensación selecciona productos en el Checkout. No crea Invoice ni
// mueve stock hasta el post autoritativo.
export const dispensePrescription = (prescriptionPublicId, {
    lines, expectedVersion, idempotencyKey,
} = {}) =>
    api.post(`billing/prescriptions/${prescriptionPublicId}/dispense/`, {
        lines,
        expected_version: expectedVersion,
    }, _idemConfig(idempotencyKey))
        .then(r => r.data);

export const downloadInvoicePDF = (publicId) =>
    api.get(`billing/invoices/${publicId}/pdf/`, { responseType: "blob" })
        .then(r => ({ blob: r.data, contentDisposition: r.headers["content-disposition"] }));
