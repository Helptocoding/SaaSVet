import { useEffect, useRef, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useConfirm } from "../components/ConfirmDialog";
import { apiError } from "../utils/apiError";
import {
    getInvoices, getInvoice, createInvoice, confirmInvoice, payInvoice, directPayInvoice,
    addInvoiceItem, getServices, downloadInvoicePDF, refundInvoice, reverseCreditNote,
    dispensePrescription,
} from "../api/billing";
import { extractFilename, triggerDownload } from "../utils/downloadBlob";
import { getPresentations } from "../api/inventory";
import { getOwners, getPets } from "../api/pets";
import { getCurrentSession } from "../api/cash";
import { getOrgSettings } from "../api/organizations";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import { toast } from "sonner";
import SearchSelect from "../components/SearchSelect";
import DateRangePicker from "../components/DateRangePicker";
import CajaBar from "../components/CajaBar";
import s from "./billing.module.css";

const FILTER_KEYS = ["status", "invoice_type", "created_from", "created_to", "paid_from", "paid_to"];
const STATUS_LABELS = { draft: "Borrador", confirmed: "Confirmada", paid: "Pagada", cancelled: "Cancelada" };
const TYPE_LABELS = { consultation: "Consulta", direct_sale: "Venta directa" };
const PAYMENT_METHODS = [
    { value: "cash", label: "Efectivo" },
    { value: "card", label: "Tarjeta" },
    { value: "transfer", label: "Transferencia" },
    { value: "other", label: "Otro" },
];

const DOT_COLOR = {
    draft: "var(--c-text-4)",
    confirmed: "var(--c-info-text)",
    paid: "var(--c-success-text)",
    cancelled: "var(--c-danger-text)",
};

// ADR p29: causas de devolución (deben coincidir con CREDIT_NOTE_REASON_CODES del backend).
const REASON_CODES = [
    { value: "customer_return", label: "Devolución del cliente" },
    { value: "damaged_product", label: "Producto dañado" },
    { value: "expired_product", label: "Producto caducado" },
    { value: "duplicate_charge", label: "Cargo duplicado" },
    { value: "pricing_error", label: "Error de precio" },
    { value: "goodwill", label: "Cortesía" },
    { value: "clinical_cancellation", label: "Cancelación clínica" },
    { value: "other", label: "Otro" },
];
const REASON_LABELS = Object.fromEntries(REASON_CODES.map(r => [r.value, r.label]));

// ADR p27: clave de idempotencia por intento de cobro (anti doble-cobro en
// reintento de red). Se reusa mientras el modal de pago siga abierto.
const newIdempotencyKey = () =>
    (typeof crypto !== "undefined" && crypto.randomUUID)
        ? crypto.randomUUID()
        : `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;

// Valida líneas de pago contra el total.
//  - allowPartial=true  → admite pagar menos (no se usa para cobros nuevos: ADR p30
//    rev exige total exacto siempre). Se conserva para casos futuros / refund parcial.
//  - allowChange=true   → admite efectivo recibido MAYOR al total; el excedente es
//    cambio, no se registra. Aplica a TODO cobro (ADR p30 rev).
//  - ambos false        → exige monto exacto (refund).
const paymentLinesValid = (lines, total, allowPartial, allowChange = false) => {
    if (lines.some(l => Number(l.amount) < 0)) return false;
    const positive = lines.map(l => Number(l.amount)).filter(n => n > 0);
    if (positive.length === 0) return false;
    const sum = Number(positive.reduce((a, n) => a + n, 0).toFixed(2));
    const t = Number(Number(total).toFixed(2));
    if (sum > t) return allowChange;          // sobrepago solo válido si se da cambio
    if (!allowPartial && sum !== t) return false;
    return true;
};

/* ── PaymentLinesEditor — pago único o split, total exacto (ADR p30 rev) ── */
const PaymentLinesEditor = ({ total, allowPartial, allowChange = false, lines, setLines, disabled }) => {
    const sum = Number(lines.reduce((a, l) => a + (Number(l.amount) || 0), 0).toFixed(2));
    const remaining = Number((Number(total) - sum).toFixed(2));
    const change = remaining < 0 ? Math.abs(remaining) : 0;
    const setLine = (i, patch) => setLines(prev => prev.map((l, idx) => idx === i ? { ...l, ...patch } : l));
    const addLine = () => setLines(prev => [...prev, { method: "card", amount: remaining > 0 ? remaining.toFixed(2) : "" }]);
    const removeLine = (i) => setLines(prev => prev.filter((_, idx) => idx !== i));
    return (
        <div>
            {lines.map((l, i) => (
                <div key={i} style={{ display: "flex", gap: "6px", marginBottom: "6px", alignItems: "center" }}>
                    <select
                        className="input" style={{ flex: 1, height: "34px" }}
                        value={l.method} disabled={disabled}
                        onChange={e => setLine(i, { method: e.target.value })}
                    >
                        {PAYMENT_METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                    <input
                        type="number" className="input"
                        style={{ width: "110px", height: "34px", textAlign: "right" }}
                        min="0" step="0.01" placeholder="0.00" value={l.amount} disabled={disabled}
                        onChange={e => setLine(i, { amount: e.target.value })}
                    />
                    <button
                        className={s.actionBtn} onClick={() => removeLine(i)}
                        disabled={disabled || lines.length <= 1}
                        style={{ visibility: lines.length > 1 ? "visible" : "hidden" }}
                    >
                        <Icon.Trash s={13} />
                    </button>
                </div>
            ))}
            <button className="btn btn-ghost btn-xs" onClick={addLine} disabled={disabled}>+ Otro método</button>
            <div style={{ marginTop: "10px", fontSize: "12px", display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--c-text-3)" }}>
                    Total ${Number(total).toFixed(2)} · Ingresado ${sum.toFixed(2)}
                </span>
                <span style={{ fontWeight: 600, color: remaining === 0 ? "var(--c-success-text)" : (remaining < 0 ? (allowChange ? "var(--c-success-text)" : "var(--c-danger-text)") : "var(--c-text-3)") }}>
                    {remaining > 0
                        ? `Falta $${remaining.toFixed(2)}`
                        : remaining < 0
                            ? (allowChange ? `Cambio $${change.toFixed(2)}` : `Excede $${change.toFixed(2)}`)
                            : (allowPartial ? "Pago completo" : "Exacto")}
                </span>
            </div>
            {allowChange && change > 0 && (
                <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>
                    Se cobra el total ${Number(total).toFixed(2)}; el cambio ${change.toFixed(2)} no se registra.
                </p>
            )}
            {allowPartial && remaining > 0 && sum > 0 && (
                <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>
                    Pago parcial: la factura quedará confirmada con saldo pendiente.
                </p>
            )}
        </div>
    );
};

/* ── RefundModal — devolución (nota de crédito + reembolso), ADR p29 ── */
const RefundModal = ({ invoice, onClose, onDone }) => {
    // Una fila por concepto de la factura. Por defecto: todo seleccionado, monto
    // y cantidad completos, reingreso a stock. El backend valida límites reales
    // (over-refund por devoluciones previas) y responde con mensaje claro.
    const [rows, setRows] = useState(() =>
        (invoice.items || []).map(it => ({
            id: it.id,
            description: it.description,
            maxQty: Number(it.quantity),
            maxAmount: Number(it.subtotal),
            hasPresentation: !!it.presentation,
            selected: true,
            quantity: String(it.quantity),
            amount: Number(it.subtotal).toFixed(2),
            disposition: "restock",
        }))
    );
    const [refundLines, setRefundLines] = useState(
        () => [{ method: "cash", amount: Number(invoice.total).toFixed(2) }]
    );
    const [reasonCode, setReasonCode] = useState("customer_return");
    const [reasonNotes, setReasonNotes] = useState("");
    const [idemKey] = useState(newIdempotencyKey);
    const [submitting, setSubmitting] = useState(false);

    const setRow = (id, patch) => setRows(prev => prev.map(r => r.id === id ? { ...r, ...patch } : r));

    const selectedRows = rows.filter(r => r.selected);
    const refundTotal = Number(
        selectedRows.reduce((a, r) => a + (Number(r.amount) || 0), 0).toFixed(2)
    );

    const creditValid = selectedRows.length > 0 && selectedRows.every(r =>
        Number(r.quantity) > 0 && Number(r.quantity) <= r.maxQty + 1e-9 &&
        Number(r.amount) >= 0 && Number(r.amount) <= r.maxAmount + 1e-9
    );
    const refundValid = paymentLinesValid(refundLines, refundTotal, false);
    const canSubmit = creditValid && refundValid && refundTotal > 0 && !!reasonCode && !submitting;

    const matchRefundToTotal = () =>
        setRefundLines([{ method: refundLines[0]?.method || "cash", amount: refundTotal.toFixed(2) }]);

    const submit = async () => {
        const creditLines = selectedRows.map(r => ({
            invoice_item: r.id,
            quantity: Number(r.quantity).toFixed(2),
            amount: Number(r.amount).toFixed(2),
            // Para servicios (sin presentación) el restock es no-op en backend.
            disposition: r.hasPresentation ? r.disposition : "restock",
        }));
        const rLines = refundLines
            .filter(l => Number(l.amount) > 0)
            .map(l => ({ method: l.method, amount: Number(l.amount).toFixed(2) }));
        setSubmitting(true);
        try {
            await toast.promise(
                refundInvoice(invoice.public_id, {
                    creditLines, refundLines: rLines,
                    reasonCode, reasonNotes, idempotencyKey: idemKey,
                }),
                {
                    loading: "Procesando devolución...",
                    success: "Devolución emitida",
                    error: (err) => apiError(err, "Error al procesar la devolución"),
                }
            );
            onDone();
        } catch {
            // toast.promise ya mostró el error; el modal queda abierto para corregir
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="modal-overlay" style={{ zIndex: 1001 }} onClick={submitting ? undefined : onClose}>
            <div className="modal modal-lg" onClick={e => e.stopPropagation()} style={{ maxHeight: "90vh", display: "flex", flexDirection: "column" }}>
                <div className="modal-header">
                    <h3 style={{ fontSize: "15px", fontWeight: 600, color: "var(--c-text)" }}>
                        Devolución — Cobro #{invoice.id}
                    </h3>
                    <button className="modal-close" onClick={onClose} disabled={submitting}><Icon.X s={14} /></button>
                </div>
                <div className="modal-body" style={{ overflowY: "auto" }}>
                    <p style={{ fontSize: "11px", fontWeight: 500, color: "var(--c-text-3)", marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Conceptos a devolver
                    </p>
                    <table className={s.tableCompact} style={{ border: "1px solid var(--c-border)" }}>
                        <thead>
                            <tr>
                                <th style={{ width: "28px" }}></th>
                                <th>Descripción</th>
                                <th style={{ width: "70px" }}>Cant.</th>
                                <th style={{ width: "100px", textAlign: "right" }}>Monto</th>
                                <th style={{ width: "130px" }}>Destino</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map(r => (
                                <tr key={r.id} style={{ opacity: r.selected ? 1 : 0.45 }}>
                                    <td>
                                        <input
                                            type="checkbox" checked={r.selected} disabled={submitting}
                                            onChange={e => setRow(r.id, { selected: e.target.checked })}
                                        />
                                    </td>
                                    <td>{r.description}</td>
                                    <td>
                                        <input
                                            type="number" className="input"
                                            style={{ width: "60px", height: "30px", textAlign: "right" }}
                                            min="0" max={r.maxQty} step="1"
                                            value={r.quantity} disabled={!r.selected || submitting}
                                            onChange={e => setRow(r.id, { quantity: e.target.value })}
                                        />
                                    </td>
                                    <td style={{ textAlign: "right" }}>
                                        <input
                                            type="number" className="input"
                                            style={{ width: "90px", height: "30px", textAlign: "right" }}
                                            min="0" max={r.maxAmount} step="0.01"
                                            value={r.amount} disabled={!r.selected || submitting}
                                            onChange={e => setRow(r.id, { amount: e.target.value })}
                                        />
                                    </td>
                                    <td>
                                        {r.hasPresentation ? (
                                            <select
                                                className="input" style={{ height: "30px" }}
                                                value={r.disposition} disabled={!r.selected || submitting}
                                                onChange={e => setRow(r.id, { disposition: e.target.value })}
                                            >
                                                <option value="restock">Reingresa a stock</option>
                                                <option value="discard">Descartar</option>
                                            </select>
                                        ) : (
                                            <span style={{ fontSize: "11px", color: "var(--c-text-4)" }}>—</span>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>

                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "14px 0 8px" }}>
                        <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)" }}>
                            Reembolso (debe igualar ${refundTotal.toFixed(2)})
                        </label>
                        <button className="btn btn-ghost btn-xs" onClick={matchRefundToTotal} disabled={submitting || refundTotal <= 0}>
                            Igualar al total
                        </button>
                    </div>
                    <PaymentLinesEditor
                        total={refundTotal}
                        allowPartial={false}
                        lines={refundLines}
                        setLines={setRefundLines}
                        disabled={submitting}
                    />

                    <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", margin: "14px 0 6px" }}>
                        Causa de la devolución
                    </label>
                    <select
                        className="input" style={{ height: "34px", width: "100%" }}
                        value={reasonCode} disabled={submitting}
                        onChange={e => setReasonCode(e.target.value)}
                    >
                        {REASON_CODES.map(rc => <option key={rc.value} value={rc.value}>{rc.label}</option>)}
                    </select>
                    <textarea
                        className="input" rows={2} placeholder="Notas (opcional)"
                        style={{ width: "100%", marginTop: "8px", resize: "vertical" }}
                        value={reasonNotes} disabled={submitting}
                        onChange={e => setReasonNotes(e.target.value)}
                    />
                </div>
                <div className="modal-footer">
                    <button className="btn btn-secondary btn-sm" onClick={onClose} disabled={submitting}>Cancelar</button>
                    <button
                        className="btn btn-danger btn-sm"
                        onClick={submit}
                        disabled={!canSubmit}
                        title={!creditValid ? "Revisa cantidades/montos" : !refundValid ? "El reembolso debe igualar el total a devolver" : ""}
                    >
                        {submitting ? <Icon.Loader s={14} /> : "Emitir devolución"}
                    </button>
                </div>
            </div>
        </div>
    );
};

/* ── PrescriptionDispensePanel — dispensar receta interna (ADR p30) ── */
const PrescriptionDispensePanel = ({ invoice, onDispensed }) => {
    const suggestions = invoice.prescription_suggestions || [];
    const [rows, setRows] = useState(() =>
        suggestions.map(s => ({
            key: s.prescription_item_id,
            productName: s.product_name,
            dose: s.dose,
            presentations: s.presentations || [],
            // Por defecto seleccionado solo si hay presentación vendible.
            selected: (s.presentations || []).length > 0,
            presentationId: (s.presentations || [])[0]?.id ? String(s.presentations[0].id) : "",
            quantity: s.suggested_quantity || "1",
        }))
    );
    const [submitting, setSubmitting] = useState(false);
    const setRow = (key, patch) => setRows(prev => prev.map(r => r.key === key ? { ...r, ...patch } : r));

    const selected = rows.filter(r => r.selected && r.presentationId && Number(r.quantity) > 0);
    const canSubmit = selected.length > 0 && !submitting;

    const submit = async () => {
        const lines = selected.map(r => ({
            presentation: Number(r.presentationId),
            quantity: Number(r.quantity),
            prescription_item: r.key,
        }));
        setSubmitting(true);
        // sonner v2: toast.promise NO resuelve a la data — await la promesa real
        // para obtener la factura de consulta actualizada.
        const req = dispensePrescription(invoice.prescription_public_id, { lines });
        toast.promise(req, {
            loading: "Agregando al cobro...",
            success: "Productos agregados al cobro",
            error: (err) => apiError(err, "Error al dispensar la receta"),
        });
        try {
            const updated = await req;
            onDispensed(updated);
        } catch {
            // toast.promise ya mostró el error
        } finally {
            setSubmitting(false);
        }
    };

    // Solo se dispensa mientras el cobro está en borrador (los ítems se agregan
    // a esta factura antes de confirmar). Confirmada/pagada → sin panel.
    if (!invoice.prescription_public_id || suggestions.length === 0 || invoice.status !== "draft") return null;

    return (
        <div style={{ marginTop: "20px" }}>
            <p style={{ fontSize: "11px", fontWeight: 500, color: "var(--c-text-3)", marginBottom: "4px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Medicamentos recetados (opcionales)
            </p>
            <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginBottom: "10px" }}>
                Los siguientes medicamentos fueron recetados por el veterinario. Solo agrega los que el cliente decida comprar; lo demás no toca inventario.
            </p>
            <table className={s.tableCompact} style={{ border: "1px solid var(--c-border)" }}>
                <thead>
                    <tr>
                        <th style={{ width: "28px" }}></th>
                        <th>Medicamento</th>
                        <th style={{ width: "180px" }}>Presentación</th>
                        <th style={{ width: "70px" }}>Cant.</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(r => {
                        const noPres = r.presentations.length === 0;
                        return (
                            <tr key={r.key} style={{ opacity: r.selected ? 1 : 0.45 }}>
                                <td>
                                    <input
                                        type="checkbox" checked={r.selected}
                                        disabled={submitting || noPres}
                                        onChange={e => setRow(r.key, { selected: e.target.checked })}
                                    />
                                </td>
                                <td>
                                    <div>{r.productName}</div>
                                    {r.dose && <div style={{ fontSize: "11px", color: "var(--c-text-3)" }}>{r.dose}</div>}
                                </td>
                                <td>
                                    {noPres ? (
                                        <span style={{ fontSize: "11px", color: "var(--c-danger-text)" }}>Sin presentación de venta</span>
                                    ) : (
                                        <select
                                            className="input" style={{ height: "30px" }}
                                            value={r.presentationId} disabled={!r.selected || submitting}
                                            onChange={e => setRow(r.key, { presentationId: e.target.value })}
                                        >
                                            {r.presentations.map(p => (
                                                <option key={p.id} value={p.id}>
                                                    {p.name} — ${Number(p.sale_price).toFixed(2)} (stock {p.stock})
                                                </option>
                                            ))}
                                        </select>
                                    )}
                                </td>
                                <td>
                                    <input
                                        type="number" className="input"
                                        style={{ width: "60px", height: "30px", textAlign: "right" }}
                                        min="1" step="1"
                                        value={r.quantity} disabled={!r.selected || submitting || noPres}
                                        onChange={e => setRow(r.key, { quantity: e.target.value })}
                                    />
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "10px" }}>
                <button className="btn btn-primary btn-sm" onClick={submit} disabled={!canSubmit}>
                    {submitting ? <Icon.Loader s={14} /> : "Agregar al cobro"}
                </button>
            </div>
        </div>
    );
};

const Billing = () => {
    const { token, initializing, can } = useAuth();
    const confirm = useConfirm();
    const [searchParams, setSearchParams] = useSearchParams();
    const [loading, setLoading] = useState(true);
    const requestIdRef = useRef(0);

    const [invoices, setInvoices] = useState([]);
    const [genericOwner, setGenericOwner] = useState(null);

    const [filters, setFilters] = useState(() => {
        const initial = {};
        for (const key of FILTER_KEYS) initial[key] = searchParams.get(key) || "";
        return initial;
    });

    const [selectedInvoice, setSelectedInvoice] = useState(null);
    const [showDetailModal, setShowDetailModal] = useState(false);
    const [showPayModal, setShowPayModal] = useState(false);
    const [payLines, setPayLines] = useState([{ method: "cash", amount: "" }]);
    const [payIdemKey, setPayIdemKey] = useState(null);
    const [paying, setPaying] = useState(false);
    const [downloadingInvoiceId, setDownloadingInvoiceId] = useState(null);

    const [showNewInvoiceModal, setShowNewInvoiceModal] = useState(false);
    const [showRefundModal, setShowRefundModal] = useState(false);
    const [reversingCnId, setReversingCnId] = useState(null);

    // Caja (ADR p28): turno actual + si la org exige caja abierta para cobrar.
    const [cashSession, setCashSession] = useState(undefined); // undefined=cargando | null=cerrada | obj=abierta
    const [requireCash, setRequireCash] = useState(false);

    const loadInvoices = async (currentFilters) => {
        const requestId = ++requestIdRef.current;
        try {
            const params = {};
            for (const key of FILTER_KEYS) if (currentFilters[key]) params[key] = currentFilters[key];
            const data = await getInvoices(params);
            if (requestId === requestIdRef.current) setInvoices(data);
        } catch {
            // Silencioso — el usuario ve lista vacía
        }
    };

    // Caja: turno actual + flag de la org. Silencioso: si falla, asume cerrada.
    const loadCashStatus = async () => {
        const [settings, current] = await Promise.all([
            getOrgSettings().catch(() => null),
            getCurrentSession().catch(() => null),
        ]);
        setRequireCash(!!settings?.require_open_cash_session);
        setCashSession(current && current.public_id ? current : null);
    };

    const loadAll = async () => {
        setLoading(requestIdRef.current === 0);
        try {
            const owners = await getOwners({ is_generic: "true" });
            setGenericOwner((Array.isArray(owners) ? owners : owners?.results || [])[0] || null);
            await loadInvoices(filters);
            loadCashStatus();
        } catch {
            // Silencioso — loadInvoices maneja su error
        } finally { setLoading(false); }
    };

    useEffect(() => { if (token) { loadAll(); } }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => {
        const timer = setTimeout(() => loadInvoices(filters), 300);
        return () => clearTimeout(timer);
    }, [filters.status, filters.invoice_type, filters.created_from, filters.created_to, filters.paid_from, filters.paid_to]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'F11' && can("invoice.create") && !showNewInvoiceModal && !showDetailModal) {
                e.preventDefault();
                setShowNewInvoiceModal(true);
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [can, showNewInvoiceModal, showDetailModal]);

    useEffect(() => {
        const invoiceParam = searchParams.get("invoice");
        if (invoiceParam && token && !loading) {
            getInvoice(invoiceParam).then((detail) => {
                setSelectedInvoice(detail);
                setShowDetailModal(true);
            }).catch(() => {});
        }
    }, [token, loading]); // eslint-disable-line react-hooks/exhaustive-deps

    const updateFilter = (key, value) => {
        const next = { ...filters, [key]: value };
        setFilters(next);
        const params = new URLSearchParams();
        for (const k of FILTER_KEYS) if (next[k]) params.set(k, next[k]);
        setSearchParams(params, { replace: true });
    };

    const clearFilters = () => {
        const empty = {};
        for (const key of FILTER_KEYS) empty[key] = "";
        setFilters(empty);
        setSearchParams({}, { replace: true });
    };

    const openInvoiceDetail = async (invoice) => {
        try {
            const detail = await getInvoice(invoice.public_id);
            setSelectedInvoice(detail);
            setShowDetailModal(true);
        } catch { toast.error("Error al cargar la factura"); }
    };

    const closeDetailModal = () => {
        setShowDetailModal(false);
        setSelectedInvoice(null);
        setShowPayModal(false);
        setShowRefundModal(false);
    };

    const handleDownloadInvoicePDF = async (publicId) => {
        setDownloadingInvoiceId(publicId);
        try {
            const { blob, contentDisposition } = await downloadInvoicePDF(publicId);
            const filename = extractFilename(contentDisposition, "factura.pdf");
            triggerDownload(blob, filename);
        } catch (err) { toast.error(apiError(err, "Error al descargar PDF")); }
        finally { setDownloadingInvoiceId(null); }
    };

    const handleConfirm = async () => {
        // sonner v2: toast.promise NO resuelve a la data — hay que await la
        // promesa real para obtener la factura actualizada.
        const req = confirmInvoice(selectedInvoice.public_id);
        toast.promise(req, {
            loading: 'Confirmando...', success: 'Confirmada', error: (err) => apiError(err, "Error")
        });
        try {
            const updated = await req;
            setSelectedInvoice(updated);
            loadInvoices(filters);
        } catch {
            // toast.promise ya muestra el error
        }
    };

    const openPayModal = () => {
        const direct = selectedInvoice?.invoice_type === "direct_sale" && selectedInvoice?.status === "draft";
        const target = direct ? Number(selectedInvoice.total) : Number(selectedInvoice.remaining_balance);
        setPayLines([{ method: "cash", amount: target > 0 ? target.toFixed(2) : "" }]);
        setPayIdemKey(newIdempotencyKey());
        setShowPayModal(true);
    };

    // ADR p30 (rev): toda factura exige total exacto — sin parcial. Si recibe
    // efectivo > total, se registra SOLO el total (el excedente es cambio para
    // el cliente, no se persiste). Aplica a venta directa Y a consulta.
    const submitPayment = async () => {
        const direct = selectedInvoice?.invoice_type === "direct_sale" && selectedInvoice?.status === "draft";
        const target = Number(Number(direct ? selectedInvoice.total : selectedInvoice.remaining_balance).toFixed(2));
        const sum = Number(payLines.reduce((a, l) => a + (Number(l.amount) || 0), 0).toFixed(2));
        const paymentLines = (sum > target)
            ? [{ method: payLines[0].method, amount: target.toFixed(2) }]
            : payLines
                .filter(l => Number(l.amount) > 0)
                .map(l => ({ method: l.method, amount: Number(l.amount).toFixed(2) }));
        const call = direct
            ? directPayInvoice(selectedInvoice.public_id, { paymentLines, idempotencyKey: payIdemKey })
            : payInvoice(selectedInvoice.public_id, { paymentLines, idempotencyKey: payIdemKey });
        setPaying(true);
        // sonner v2: toast.promise NO resuelve a la data — await la promesa real.
        toast.promise(call, {
            loading: direct ? 'Cobrando...' : 'Registrando...',
            success: direct ? 'Cobrada' : 'Pago registrado',
            error: (err) => apiError(err, "Error"),
        });
        try {
            const updated = await call;
            setSelectedInvoice(updated);
            setShowPayModal(false);
            loadInvoices(filters);
        } catch {
            // toast.promise ya muestra el error; el modal queda abierto para reintentar
        } finally {
            setPaying(false);
        }
    };

    // ADR p29: refresca el detalle (incluye credit_notes) + la lista tras una
    // devolución o su reverso.
    const refreshSelectedInvoice = async () => {
        try {
            const detail = await getInvoice(selectedInvoice.public_id);
            setSelectedInvoice(detail);
        } catch { /* conserva el detalle actual */ }
        loadInvoices(filters);
    };

    const onRefundDone = async () => {
        setShowRefundModal(false);
        await refreshSelectedInvoice();
    };

    // ADR p30: los productos dispensados se agregan a ESTA misma factura de
    // consulta. Refresca el detalle abierto (muestra las nuevas líneas) y la
    // lista (totales). No se abre otra factura.
    const handleDispensed = async () => {
        await refreshSelectedInvoice();
        await loadInvoices(filters);
    };

    const handleReverseCreditNote = async (cn) => {
        const ok = await confirm({
            title: "Revertir devolución",
            message: `Se revertirá la nota de crédito por $${Number(cn.total_refunded).toFixed(2)} con un contra-asiento (el registro no se borra). ¿Continuar?`,
            confirmText: "Revertir",
            dangerMode: true,
        });
        if (!ok) return;
        setReversingCnId(cn.public_id);
        try {
            await toast.promise(
                reverseCreditNote(cn.public_id, { idempotencyKey: newIdempotencyKey() }),
                { loading: "Revirtiendo...", success: "Devolución revertida", error: (err) => apiError(err, "Error") }
            );
            await refreshSelectedInvoice();
        } catch { /* toast.promise ya mostró el error */ }
        finally { setReversingCnId(null); }
    };

    const formatDate = (dateString) => dateString ? new Date(dateString).toLocaleDateString("es-ES", { year: "numeric", month: "short", day: "numeric" }) : "—";
    const formatCurrency = (amount) => Number(amount || 0).toFixed(2);

    if (initializing || loading) return <div style={{ display: "flex", justifyContent: "center", padding: "100px", color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</div>;

    const isDirectSaleDraft = selectedInvoice?.invoice_type === "direct_sale" && selectedInvoice?.status === "draft";
    // ADR p30 (rev): toda factura exige total exacto — sin parcial. Venta
    // directa cobra `total`; consulta confirmada cobra `remaining_balance`
    // (igual al total mientras no haya pagos previos). `allowChange` aplica
    // siempre: efectivo recibido > total muestra cambio (no se persiste).
    const payTarget = selectedInvoice
        ? Number(isDirectSaleDraft ? selectedInvoice.total : selectedInvoice.remaining_balance)
        : 0;
    const payAllowPartial = false;
    // Solo bloquea si la org exige caja Y sabemos que está cerrada (no en carga).
    const cashBlocked = requireCash && cashSession === null;

    return (
        <div className={s.billingContainer}>
            <div className={s.pageHeader}>
                <h1 className={s.mainTitle}>Cobros</h1>
            </div>

            {cashBlocked && (
                <div className="form-alert form-alert-warning" style={{ alignItems: "center" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <Icon.AlertTriangle s={16} />
                        <span><strong>No hay una caja abierta.</strong> Debes abrir una caja para registrar pagos.</span>
                    </span>
                    <Link to="/cash" className="btn btn-primary btn-sm" style={{ textDecoration: "none", flexShrink: 0 }}>
                        Abrir caja
                    </Link>
                </div>
            )}

            <CajaBar onChange={loadCashStatus} />

            <div className={s.filterBar}>
                <div className={s.filterItem}>
                    <Icon.Filter s={12} c="var(--c-text-4)" />
                    <select value={filters.status} onChange={e => updateFilter("status", e.target.value)}>
                        <option value="">Estado</option>
                        {Object.entries(STATUS_LABELS).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
                    </select>
                </div>
                <div className={s.filterItem}>
                    <Icon.Receipt s={12} c="var(--c-text-4)" />
                    <select value={filters.invoice_type} onChange={e => updateFilter("invoice_type", e.target.value)}>
                        <option value="">Tipo</option>
                        {Object.entries(TYPE_LABELS).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
                    </select>
                </div>
                <DateRangePicker from={filters.created_from} to={filters.created_to} onChange={(f, t) => { updateFilter("created_from", f); updateFilter("created_to", t); }} placeholder="Creado" />
                <button className="btn btn-ghost btn-xs" onClick={clearFilters} style={{ color: "var(--c-text-4)" }}>Limpiar</button>
                {can("invoice.create") && (
                    <button
                        className="btn btn-primary btn-sm"
                        style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "6px" }}
                        onClick={() => setShowNewInvoiceModal(true)}
                        title="Atajo: F11"
                    >
                        + Cobro
                        <kbd style={{
                            fontSize: "10px", fontWeight: 600, padding: "1px 5px",
                            borderRadius: "3px", border: "1px solid rgba(255,255,255,0.3)",
                            background: "rgba(255,255,255,0.15)", color: "inherit",
                            lineHeight: "16px",
                        }}>F11</kbd>
                    </button>
                )}
            </div>

            {invoices.length === 0 ? <div className="empty-state"><p className="empty-state-title">No hay cobros</p></div> : (
                <table className={s.tableCompact}>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Paciente / Cliente</th>
                            <th>Tipo</th>
                            <th>Estado</th>
                            <th>Fecha</th>
                            <th style={{ textAlign: "right" }}>Total</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {invoices.map(inv => (
                            <tr key={inv.id}>
                                <td style={{ color: "var(--c-text-3)" }}>#{inv.id}</td>
                                <td>
                                    <div style={{ color: "var(--c-text)" }}>{inv.pet_name}</div>
                                    <div style={{ fontSize: "11px", color: "var(--c-text-3)" }}>{inv.owner_name}</div>
                                </td>
                                <td style={{ fontSize: "12px" }}>{inv.invoice_type === "direct_sale" ? "Venta directa" : "Consulta"}</td>
                                <td>
                                    <div className={s.statusContainer}>
                                        <span className={s.statusDot} style={{ background: DOT_COLOR[inv.status] }} />
                                        {STATUS_LABELS[inv.status]}
                                    </div>
                                </td>
                                <td style={{ color: "var(--c-text-3)" }}>{formatDate(inv.created_at)}</td>
                                <td style={{ textAlign: "right", color: "var(--c-text)" }}>${formatCurrency(inv.total)}</td>
                                <td style={{ textAlign: "right" }}>
                                    <button className={s.actionBtn} onClick={() => openInvoiceDetail(inv)}><Icon.Eye s={14} /></button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}

            {/* Detail Modal */}
            {showDetailModal && selectedInvoice && (
                <div className="modal-overlay">
                    <div className="modal modal-lg">
                        <div className="modal-header">
                            <div>
                                <h3 className={s.mainTitle} style={{ fontSize: "16px" }}>#{selectedInvoice.id}</h3>
                                <div className={s.statusContainer} style={{ marginTop: "4px" }}>
                                    <span className={s.statusDot} style={{ background: DOT_COLOR[selectedInvoice.status] }} />
                                    {STATUS_LABELS[selectedInvoice.status]}
                                </div>
                            </div>
                            <div style={{ display: "flex", gap: "8px" }}>
                                <button className="btn btn-secondary btn-sm" onClick={() => handleDownloadInvoicePDF(selectedInvoice.public_id)} disabled={downloadingInvoiceId === selectedInvoice.public_id}>
                                    {downloadingInvoiceId === selectedInvoice.public_id ? <Icon.Loader s={12} /> : <Icon.Download s={12} />} PDF
                                </button>
                                <button className="modal-close" onClick={closeDetailModal}><Icon.X s={14} /></button>
                            </div>
                        </div>
                        <div className="modal-body">
                            <div className={s.infoGrid}>
                                <div><p className={s.infoLabel}>Paciente</p><p className={s.infoValue}>{selectedInvoice.pet_name}</p></div>
                                <div><p className={s.infoLabel}>Propietario</p><p className={s.infoValue}>{selectedInvoice.owner_name}</p></div>
                                <div><p className={s.infoLabel}>Fecha</p><p className={s.infoValue}>{formatDate(selectedInvoice.created_at)}</p></div>
                            </div>

                            <p style={{ fontSize: "11px", fontWeight: "500", color: "var(--c-text-3)", marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Conceptos</p>
                            <table className={s.tableCompact} style={{ border: "1px solid var(--c-border)" }}>
                                <thead>
                                    <tr>
                                        <th>Descripción</th>
                                        <th>Cant.</th>
                                        <th style={{ textAlign: "right" }}>Total</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {selectedInvoice.items.map(item => (
                                        <tr key={item.id}>
                                            <td>
                                                {item.description}
                                                {item.dispensed && (
                                                    <span style={{ marginLeft: "6px", fontSize: "10px", fontWeight: 600, color: "var(--c-accent-text, var(--c-text-3))", border: "1px solid var(--c-border)", borderRadius: "4px", padding: "1px 5px", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                                        Para llevar
                                                    </span>
                                                )}
                                            </td>
                                            <td>{item.quantity}</td>
                                            <td style={{ textAlign: "right" }}>${formatCurrency(item.subtotal)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>

                            <div className={s.totalsSection}>
                                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                                    <div style={{ minWidth: "200px" }}>
                                        <div className={s.totalRow}><span>Subtotal</span><span>${formatCurrency(selectedInvoice.subtotal)}</span></div>
                                        <div className={s.totalRow}><span>IVA</span><span>${formatCurrency(selectedInvoice.tax_amount)}</span></div>
                                        <div className={s.grandTotal}><span>Total</span><span>${formatCurrency(selectedInvoice.total)}</span></div>
                                    </div>
                                </div>
                            </div>

                            {selectedInvoice.credit_notes?.length > 0 && (
                                <div style={{ marginTop: "16px" }}>
                                    <p style={{ fontSize: "11px", fontWeight: 500, color: "var(--c-text-3)", marginBottom: "8px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                                        Devoluciones
                                    </p>
                                    {selectedInvoice.credit_notes.map(cn => (
                                        <div key={cn.public_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", padding: "8px 10px", border: "1px solid var(--c-border)", borderRadius: "6px", marginBottom: "6px" }}>
                                            <div>
                                                <div style={{ fontSize: "13px", color: "var(--c-text)" }}>
                                                    ${formatCurrency(cn.total_refunded)} · {REASON_LABELS[cn.reason_code] || cn.reason_code}
                                                    {cn.reversed && <span style={{ marginLeft: "6px", fontSize: "11px", color: "var(--c-danger-text)" }}>(revertida)</span>}
                                                </div>
                                                {cn.reason_notes && <div style={{ fontSize: "11px", color: "var(--c-text-3)" }}>{cn.reason_notes}</div>}
                                                <div style={{ fontSize: "11px", color: "var(--c-text-4)" }}>{formatDate(cn.issued_at)}</div>
                                            </div>
                                            {can("billing.refund") && !cn.reversed && (
                                                <button className="btn btn-secondary btn-xs" onClick={() => handleReverseCreditNote(cn)} disabled={reversingCnId === cn.public_id}>
                                                    {reversingCnId === cn.public_id ? <Icon.Loader s={12} /> : "Revertir"}
                                                </button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}

                            <PrescriptionDispensePanel
                                key={selectedInvoice.public_id}
                                invoice={selectedInvoice}
                                onDispensed={handleDispensed}
                            />
                        </div>
                        <div className="modal-footer">
                            <div style={{ display: "flex", gap: "8px", width: "100%" }}>
                                {isDirectSaleDraft && (
                                    <button className="btn btn-primary btn-md" style={{ flex: 1, background: "var(--c-success-text)", borderColor: "var(--c-success-text)", color: "#fff" }} onClick={openPayModal} disabled={cashBlocked} title={cashBlocked ? "Abre una caja para cobrar" : undefined}>
                                        Cobrar
                                    </button>
                                )}
                                {selectedInvoice.status === "draft" && !isDirectSaleDraft && (
                                    <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleConfirm}>Confirmar</button>
                                )}
                                {selectedInvoice.status === "confirmed" && (
                                    <button className="btn btn-primary btn-md" style={{ flex: 1, background: "var(--c-success-text)", borderColor: "var(--c-success-text)", color: "#fff" }} onClick={openPayModal} disabled={cashBlocked} title={cashBlocked ? "Abre una caja para cobrar" : undefined}>Registrar Pago</button>
                                )}
                                {selectedInvoice.status === "paid" && can("billing.refund") && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={() => setShowRefundModal(true)}>Devolver</button>
                                )}
                                <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={closeDetailModal}>Cerrar</button>
                            </div>
                        </div>
                    </div>

                    {/* Pay Method Modal */}
                    {showPayModal && (
                        <div className="modal-overlay" style={{ zIndex: 1001 }}>
                            <div className="modal" style={{ maxWidth: "360px" }}>
                                <div className="modal-header">
                                    <h3 style={{ fontSize: "15px", fontWeight: 600, color: "var(--c-text)" }}>
                                        {isDirectSaleDraft ? "Cobrar venta directa" : "Registrar pago"}
                                    </h3>
                                    <button className="modal-close" onClick={() => setShowPayModal(false)} disabled={paying}><Icon.X s={14} /></button>
                                </div>
                                <div className="modal-body">
                                    <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", marginBottom: "8px" }}>
                                        Método{payLines.length > 1 ? "s" : ""} de pago
                                    </label>
                                    <PaymentLinesEditor
                                        total={payTarget}
                                        allowPartial={payAllowPartial}
                                        allowChange={true}
                                        lines={payLines}
                                        setLines={setPayLines}
                                        disabled={paying}
                                    />
                                </div>
                                <div className="modal-footer">
                                    <button className="btn btn-secondary btn-sm" onClick={() => setShowPayModal(false)} disabled={paying}>Cancelar</button>
                                    <button
                                        className="btn btn-primary btn-sm"
                                        style={{ background: "var(--c-success-text)", borderColor: "var(--c-success-text)", color: "#fff" }}
                                        onClick={submitPayment}
                                        disabled={paying || !paymentLinesValid(payLines, payTarget, payAllowPartial, true)}
                                    >
                                        {paying ? <Icon.Loader s={14} /> : (isDirectSaleDraft ? "Cobrar" : "Registrar Pago")}
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Refund Modal (ADR p29) */}
                    {showRefundModal && (
                        <RefundModal
                            invoice={selectedInvoice}
                            onClose={() => setShowRefundModal(false)}
                            onDone={onRefundDone}
                        />
                    )}
                </div>
            )}

            {/* New Invoice Modal (Venta Directa) */}
            {showNewInvoiceModal && (
                <NewInvoiceModal
                    genericOwner={genericOwner}
                    onClose={() => setShowNewInvoiceModal(false)}
                    onPaid={() => { setShowNewInvoiceModal(false); loadInvoices(filters); }}
                    confirm={confirm}
                />
            )}
        </div>
    );
};

/* ── NewInvoiceModal Component ── */
const NewInvoiceModal = ({ genericOwner, onClose, onPaid, confirm }) => {
    const [items, setItems] = useState([]);
    const [presentationLine, setPresentationLine] = useState({ presentation: null, quantity: "1", rxAttested: false, prescriberName: "", prescriptionFolio: "" });
    const [serviceLine, setServiceLine] = useState({ service: null, quantity: "1" });
    const [paymentMethod, setPaymentMethod] = useState("cash");
    const [processing, setProcessing] = useState(false);
    // ADR p25: cliente opcional. owner=null → "Público General" (genérico).
    // owner lleva public_id (para filtrar pets vía ?owner=) e id (PK, body).
    const [customer, setCustomer] = useState({ owner: null, pet: null });
    const [presentationCache, setPresentationCache] = useState([]);
    const [serviceCache, setServiceCache] = useState([]);

    useEffect(() => {
        getPresentations({ active: "true" }).then(data => {
            setPresentationCache(Array.isArray(data) ? data : data?.results || []);
        }).catch(() => {});
        getServices({ active: "true" }).then(data => {
            setServiceCache(Array.isArray(data) ? data : data?.results || []);
        }).catch(() => {});
    }, []);

    const handleClose = async () => {
        if (items.length > 0) {
            const ok = await confirm(
                "¿Descartar este cobro?",
                "Los ítems no se guardarán.",
                "Descartar",
                "Continuar editando"
            );
            if (!ok) return;
        }
        onClose();
    };

    const handleOwnerSearch = async (q) => {
        const data = await getOwners({ search: q, is_generic: "false" })
            .then(d => Array.isArray(d) ? d : d?.results || [])
            .catch(() => []);
        return data.slice(0, 8).map(o => ({
            id: o.id,
            public_id: o.public_id,
            label: o.phone ? `${o.name} — ${o.phone}` : o.name,
        }));
    };

    const handlePetSearch = async (q) => {
        if (!customer.owner) return [];
        const data = await getPets({ owner: customer.owner.public_id, search: q })
            .then(d => Array.isArray(d) ? d : d?.results || [])
            .catch(() => []);
        return data
            .filter(p => !p.is_generic)
            .slice(0, 8)
            .map(p => ({ id: p.id, label: p.name }));
    };

    const handleProductSearch = async (q) => {
        const lower = q.trim().toLowerCase();
        const source = lower
            ? await getPresentations({ search: q }).then(d => Array.isArray(d) ? d : d?.results || []).catch(() => [])
            : presentationCache;
        const filtered = lower
            ? source.filter(p => p.product_name?.toLowerCase().includes(lower) || p.name?.toLowerCase().includes(lower))
            : source;
        return filtered.slice(0, 8).map(p => ({
            id: p.id,
            label: `${p.product_name} — ${p.name} ($${Number(p.sale_price).toFixed(2)})${p.requires_prescription ? " · Rx" : ""}`,
            requires_prescription: !!p.requires_prescription,
        }));
    };

    const handleServiceSearch = async (q) => {
        const lower = q.trim().toLowerCase();
        const source = lower
            ? await getServices({ active: "true", search: q }).then(d => Array.isArray(d) ? d : d?.results || []).catch(() => [])
            : serviceCache;
        const filtered = lower
            ? source.filter(s => s.name?.toLowerCase().includes(lower))
            : source;
        return filtered.slice(0, 8).map(s => ({
            id: s.id,
            label: `${s.name} — $${Number(s.base_price).toFixed(2)}`,
        }));
    };

    const addPresentationItem = () => {
        if (!presentationLine.presentation) return;
        const pres = presentationCache.find(p => p.id === presentationLine.presentation.id);
        if (!pres) return;
        const qty = Math.max(1, parseInt(presentationLine.quantity) || 1);
        if (pres.stock < qty) {
            toast.error(`Stock insuficiente (${pres.stock} disponible).`);
            return;
        }
        // ADR p26: producto con receta exige atestación (cliente presentó receta + médico).
        const needsRx = !!pres.requires_prescription;
        if (needsRx && (!presentationLine.rxAttested || !presentationLine.prescriberName.trim())) {
            toast.error("Este producto requiere receta: confirma que el cliente la presentó e indica el médico.");
            return;
        }
        const existing = items.find(i => i.type === "product" && i.id === pres.id);
        if (existing) {
            const newQty = existing.quantity + qty;
            if (pres.stock < newQty) {
                toast.error(`Stock insuficiente (${pres.stock} disponible, ya tienes ${existing.quantity}).`);
                return;
            }
            setItems(prev => prev.map(i => i.id === pres.id && i.type === "product"
                ? { ...i, quantity: newQty }
                : i
            ));
        } else {
            setItems(prev => [...prev, {
                type: "product",
                id: pres.id,
                name: `${pres.product_name} — ${pres.name}`,
                quantity: qty,
                unit_price: pres.sale_price,
                requires_prescription: needsRx,
                prescriberName: needsRx ? presentationLine.prescriberName.trim() : "",
                prescriptionFolio: needsRx ? presentationLine.prescriptionFolio.trim() : "",
            }]);
        }
        setPresentationLine({ presentation: null, quantity: "1", rxAttested: false, prescriberName: "", prescriptionFolio: "" });
    };

    const addServiceItem = () => {
        if (!serviceLine.service) return;
        const svc = serviceCache.find(s => s.id === serviceLine.service.id);
        if (!svc) return;
        const qty = Math.max(1, parseInt(serviceLine.quantity) || 1);
        const existing = items.find(i => i.type === "service" && i.id === svc.id);
        if (existing) {
            setItems(prev => prev.map(i => i.id === svc.id && i.type === "service"
                ? { ...i, quantity: existing.quantity + qty }
                : i
            ));
        } else {
            setItems(prev => [...prev, {
                type: "service",
                id: svc.id,
                name: svc.name,
                quantity: qty,
                unit_price: svc.base_price,
            }]);
        }
        setServiceLine({ service: null, quantity: "1" });
    };

    const removeItem = (idx) => {
        setItems(prev => prev.filter((_, i) => i !== idx));
    };

    const subtotal = items.reduce((sum, i) => sum + i.quantity * Number(i.unit_price), 0);

    const handleCobrar = async () => {
        if (items.length === 0) {
            toast.error("Agrega al menos un ítem.");
            return;
        }
        if (!customer.owner && !genericOwner) {
            toast.error("No se encontró el propietario genérico. Verifica la configuración.");
            return;
        }
        setProcessing(true);
        try {
            // ADR p25: owner real elegido, o genérico por default. invoice_type
            // explícito 'direct_sale' para que un owner real no caiga en el
            // default 'consultation' (que exigiría pet).
            const ownerId = customer.owner ? customer.owner.id : genericOwner.id;
            const payload = { owner: ownerId, invoice_type: "direct_sale" };
            if (customer.pet) payload.pet = customer.pet.id;
            const invoice = await createInvoice(payload);
            for (const item of items) {
                let payload;
                if (item.type === "product") {
                    payload = { presentation: item.id, quantity: String(item.quantity) };
                    if (item.requires_prescription) {
                        // ADR p26: atestación de receta externa.
                        payload.rx_attested = true;
                        payload.prescriber_name = item.prescriberName;
                        payload.prescription_folio = item.prescriptionFolio || "";
                    }
                } else {
                    payload = { service: item.id, quantity: String(item.quantity) };
                }
                await addInvoiceItem(invoice.public_id, payload);
            }
            await directPayInvoice(invoice.public_id, { paymentMethod });
            toast.success("Venta directa cobrada");
            onPaid();
        } catch (err) {
            toast.error(apiError(err, "Error al procesar el cobro. Intenta de nuevo."));
        } finally {
            setProcessing(false);
        }
    };

    return (
        <div className="modal-overlay" onClick={handleClose}>
            <div className="modal modal-lg" onClick={e => e.stopPropagation()} style={{ maxHeight: "90vh", display: "flex", flexDirection: "column" }}>
                <div className="modal-header" style={{ flexShrink: 0 }}>
                    <div>
                        <h3 style={{ fontSize: "16px", fontWeight: 600, color: "var(--c-text)" }}>Nuevo Cobro</h3>
                        <span style={{ fontSize: "12px", color: "var(--c-text-3)" }}>Venta directa</span>
                    </div>
                    <button className="modal-close" onClick={handleClose}><Icon.X s={14} /></button>
                </div>

                {/* Step 1: Add items */}
                <div className="modal-body" style={{ flex: 1, overflow: "auto" }}>
                    {/* Cliente (ADR p25) — opcional; default "Público General" */}
                    <div style={{ display: "flex", gap: "12px", marginBottom: "16px", flexWrap: "wrap" }}>
                        <div style={{ flex: "1 1 260px" }}>
                            <label style={{ fontSize: "11px", fontWeight: 600, color: "var(--c-text-3)", display: "block", marginBottom: "4px", textTransform: "uppercase" }}>Cliente</label>
                            <SearchSelect
                                placeholder="Público General (buscar cliente…)"
                                value={customer.owner}
                                onChange={item => setCustomer({ owner: item, pet: null })}
                                onSearch={handleOwnerSearch}
                            />
                        </div>
                        {customer.owner && (
                            <div style={{ flex: "1 1 260px" }}>
                                <label style={{ fontSize: "11px", fontWeight: 600, color: "var(--c-text-3)", display: "block", marginBottom: "4px", textTransform: "uppercase" }}>Mascota (opcional)</label>
                                <SearchSelect
                                    placeholder="Buscar mascota del cliente…"
                                    value={customer.pet}
                                    onChange={item => setCustomer(prev => ({ ...prev, pet: item }))}
                                    onSearch={handlePetSearch}
                                />
                            </div>
                        )}
                    </div>

                    <div style={{ display: "flex", gap: "12px", marginBottom: "16px", flexWrap: "wrap" }}>
                        {/* Product */}
                        <div style={{ flex: "1 1 300px" }}>
                            <label style={{ fontSize: "11px", fontWeight: 600, color: "var(--c-text-3)", display: "block", marginBottom: "4px", textTransform: "uppercase" }}>Producto</label>
                            <div style={{ display: "flex", gap: "8px" }}>
                                <div style={{ flex: 1 }}>
                                    <SearchSelect
                                        placeholder="Buscar producto..."
                                        value={presentationLine.presentation}
                                        onChange={item => setPresentationLine(prev => ({ ...prev, presentation: item }))}
                                        onSearch={handleProductSearch}
                                    />
                                </div>
                                <input
                                    type="number"
                                    className="input"
                                    style={{ width: "70px", height: "38px", textAlign: "center" }}
                                    value={presentationLine.quantity}
                                    onChange={e => setPresentationLine(prev => ({ ...prev, quantity: e.target.value }))}
                                    min="1"
                                />
                                <button className="btn btn-primary btn-sm" onClick={addPresentationItem} disabled={!presentationLine.presentation}>
                                    <Icon.Plus s={14} />
                                </button>
                            </div>
                            {/* ADR p26: atestación de receta externa para productos Rx */}
                            {presentationLine.presentation?.requires_prescription && (
                                <div style={{ marginTop: "8px", padding: "8px 10px", border: "1px solid var(--c-border)", borderRadius: "6px", background: "rgba(245,158,11,0.07)" }}>
                                    <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", color: "var(--c-text)", cursor: "pointer" }}>
                                        <input
                                            type="checkbox"
                                            checked={presentationLine.rxAttested}
                                            onChange={e => setPresentationLine(prev => ({ ...prev, rxAttested: e.target.checked }))}
                                        />
                                        El cliente presentó receta médica válida
                                    </label>
                                    {presentationLine.rxAttested && (
                                        <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                                            <input
                                                type="text" className="input" style={{ flex: 2 }}
                                                placeholder="Médico que emitió la receta"
                                                value={presentationLine.prescriberName}
                                                onChange={e => setPresentationLine(prev => ({ ...prev, prescriberName: e.target.value }))}
                                            />
                                            <input
                                                type="text" className="input" style={{ flex: 1 }}
                                                placeholder="Folio (opcional)"
                                                value={presentationLine.prescriptionFolio}
                                                onChange={e => setPresentationLine(prev => ({ ...prev, prescriptionFolio: e.target.value }))}
                                            />
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Service */}
                        <div style={{ flex: "1 1 300px" }}>
                            <label style={{ fontSize: "11px", fontWeight: 600, color: "var(--c-text-3)", display: "block", marginBottom: "4px", textTransform: "uppercase" }}>Servicio</label>
                            <div style={{ display: "flex", gap: "8px" }}>
                                <div style={{ flex: 1 }}>
                                    <SearchSelect
                                        placeholder="Buscar servicio..."
                                        value={serviceLine.service}
                                        onChange={item => setServiceLine(prev => ({ ...prev, service: item }))}
                                        onSearch={handleServiceSearch}
                                    />
                                </div>
                                <input
                                    type="number"
                                    className="input"
                                    style={{ width: "70px", height: "38px", textAlign: "center" }}
                                    value={serviceLine.quantity}
                                    onChange={e => setServiceLine(prev => ({ ...prev, quantity: e.target.value }))}
                                    min="1"
                                />
                                <button className="btn btn-primary btn-sm" onClick={addServiceItem} disabled={!serviceLine.service}>
                                    <Icon.Plus s={14} />
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Items Table */}
                    <table className={s.tableCompact} style={{ border: "1px solid var(--c-border)" }}>
                        <thead>
                            <tr>
                                <th>Tipo</th>
                                <th>Concepto</th>
                                <th>Cant.</th>
                                <th style={{ textAlign: "right" }}>P. Unit</th>
                                <th style={{ textAlign: "right" }}>Subtotal</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.length === 0 ? (
                                <tr>
                                    <td colSpan="6" style={{ textAlign: "center", padding: "24px", color: "var(--c-text-3)" }}>
                                        Agrega productos o servicios para comenzar.
                                    </td>
                                </tr>
                            ) : items.map((item, idx) => (
                                <tr key={`${item.type}-${item.id}-${idx}`}>
                                    <td style={{ fontSize: "11px", color: "var(--c-text-3)" }}>
                                        {item.type === "product" ? <Icon.Package s={12} /> : <Icon.Stethoscope s={12} />}
                                    </td>
                                    <td style={{ fontWeight: 500 }}>{item.name}</td>
                                    <td style={{ textAlign: "center" }}>{item.quantity}</td>
                                    <td style={{ textAlign: "right" }}>${Number(item.unit_price).toFixed(2)}</td>
                                    <td style={{ textAlign: "right", fontWeight: 500 }}>
                                        ${(item.quantity * Number(item.unit_price)).toFixed(2)}
                                    </td>
                                    <td style={{ textAlign: "right" }}>
                                        <button className={s.actionBtn} onClick={() => removeItem(idx)} disabled={processing}>
                                            <Icon.Trash s={13} />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>

                    {/* Total */}
                    {items.length > 0 && (
                        <div style={{ marginTop: "16px", display: "flex", justifyContent: "flex-end" }}>
                            <div style={{ minWidth: "180px" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px", color: "var(--c-text-2)" }}>
                                    <span>Subtotal</span>
                                    <span>${subtotal.toFixed(2)}</span>
                                </div>
                                {/* Note: IVA se calcula en backend con tax_rate de la org */}
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 0 4px", borderTop: "1px solid var(--c-subtle)", fontSize: "16px", fontWeight: 600, color: "var(--c-text)" }}>
                                    <span>Total estimado</span>
                                    <span>${subtotal.toFixed(2)}</span>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer: Payment method + Cobrar */}
                <div className="modal-footer" style={{ flexShrink: 0, borderTop: "1px solid var(--c-border)", paddingTop: "12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "12px", width: "100%" }}>
                        <div style={{ flex: 1 }}>
                            <label style={{ fontSize: "11px", fontWeight: 500, color: "var(--c-text-3)", display: "block", marginBottom: "4px" }}>
                                Método de pago
                            </label>
                            <div style={{ display: "flex", gap: "6px" }}>
                                {PAYMENT_METHODS.map(m => (
                                    <button
                                        key={m.value}
                                        className={`btn ${paymentMethod === m.value ? "btn-primary" : "btn-secondary"} btn-xs`}
                                        onClick={() => setPaymentMethod(m.value)}
                                        disabled={processing}
                                    >
                                        {m.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <button className="btn btn-secondary btn-sm" onClick={handleClose} disabled={processing}>
                            Cancelar
                        </button>
                        <button
                            className="btn btn-primary btn-sm"
                            style={{ background: "var(--c-success-text)", borderColor: "var(--c-success-text)", color: "#fff", minWidth: "100px" }}
                            onClick={handleCobrar}
                            disabled={items.length === 0 || processing || (!customer.owner && !genericOwner)}
                        >
                            {processing ? <Icon.Loader s={14} /> : "Cobrar"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Billing;
