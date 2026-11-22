import { useState } from "react";
import { apiError } from "../../utils/apiError";
import { refundInvoice } from "../../api/billing";
import { Icon } from "../icons";
import { toast } from "sonner";
import PaymentLinesEditor from "../PaymentLinesEditor";
import { paymentLinesValid } from "../../utils/payments";
import { newIdempotencyKey } from "../../utils/idempotency";
import { REASON_CODES } from "./refundReasons";
import s from "../../pages/billing.module.css";

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
    const refundValid = paymentLinesValid(refundLines, refundTotal);
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
                    <h3 style={{ fontSize: "16px", fontWeight: 600, color: "var(--c-text)" }}>
                        Devolución — Cobro #{invoice.id}
                    </h3>
                    <button className="modal-close" onClick={onClose} disabled={submitting}><Icon.X s={14} /></button>
                </div>
                <div className="modal-body" style={{ overflowY: "auto" }}>
                    <p className={s.eyebrow}>
                        Conceptos a devolver
                    </p>
                    <div className="table-wrap"><table className="table">
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
                                                <option value="retained">Cliente lo conserva</option>
                                            </select>
                                        ) : (
                                            <span style={{ fontSize: "11px", color: "var(--c-text-4)" }}>—</span>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table></div>

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

export default RefundModal;
