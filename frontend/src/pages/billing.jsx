import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useConfirm } from "../components/useConfirm";
import { apiError } from "../utils/apiError";
import {
    getInvoices, getInvoice, getCheckouts, getCheckout, payCheckout,
    postCheckout, completeCheckoutNoCharge, payInvoice,
    downloadInvoicePDF, refundInvoice, reverseCreditNote,
    dispensePrescription, decidePrescriptionItem,
    issueCheckoutEstimate, downloadCheckoutEstimatePDF,
    voidAndPrepareReplacement, voidInvoiceTerminal, waiveReplacement,
    openCheckoutDispute, resolveCheckoutDispute, adjustReplacementExposure,
    assignReplacementOwner,
} from "../api/billing";
import { extractFilename, triggerDownload } from "../utils/downloadBlob";
import { getOrgSettings } from "../api/organizations";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import { toast } from "sonner";
import PaymentLinesEditor from "../components/PaymentLinesEditor";
import { buildPaymentLines, paymentLinesValid } from "../utils/payments";
import { newIdempotencyKey } from "../utils/idempotency";
import { authoritativePresentationMax } from "../utils/prescriptionAvailability";
import { toList } from "../utils/toList";
import DateRangePicker from "../components/DateRangePicker";
import CajaBar from "../components/CajaBar";
import SortHeader from "../components/SortHeader";
import Pagination from "../components/Pagination";
import s from "./billing.module.css";

const FILTER_KEYS = ["status", "invoice_type", "created_from", "created_to", "paid_from", "paid_to"];
const STATUS_LABELS = { posted: "Pendiente", paid: "Pagada", voided: "Anulada" };
const TYPE_LABELS = { consultation: "Consulta", direct_sale: "Venta directa" };

const DOT_COLOR = {
    posted: "var(--c-info-text)",
    paid: "var(--c-success-text)",
    voided: "var(--c-danger-text)",
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
                    <h3 style={{ fontSize: "15px", fontWeight: 600, color: "var(--c-text)" }}>
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

/* Override opcional de lote; vacío conserva FEFO multi-lote del backend. */
const DispenseLotSelect = ({ row, setRow, disabled }) => {
    const presentation = row.presentations.find(
        item => String(item.id) === String(row.presentationId),
    );
    const lots = presentation?.lots || [];

    return (
        <select
            className="input" style={{ height: "30px" }}
            value={row.lot?.id ?? ""} disabled={disabled}
            onChange={e => setRow(row.key, { lot: lots.find(l => String(l.id) === e.target.value) || null })}
        >
            <option value="">FEFO automático</option>
            {lots.map(l => (
                <option key={l.id} value={l.id}>
                    {l.lot_number}{l.expiry_date ? ` · ${l.expiry_date}` : ""} · {l.available_quantity_base}
                </option>
            ))}
        </select>
    );
};

/* ── PrescriptionDispensePanel — dispensar receta interna (ADR p30) ── */
const PRESCRIPTION_BLOCK_REASON = {
    checkout_not_open: "Cobro cerrado",
    prescription_fulfilled: "Receta surtida",
    below_presentation_size: "El remanente no completa esta presentación",
    no_consumable_lot: "Sin lote consumible",
    out_of_stock: "Sin stock",
    stock_below_presentation_size: "El stock no completa esta presentación",
};

const PrescriptionDispensePanel = ({ invoice, onDispensed }) => {
    const suggestions = invoice.prescription_suggestions || [];
    const [rows, setRows] = useState(() =>
        suggestions.map(s => {
            const presentations = s.presentations || [];
            const initialPresentation = presentations.find(
                p => authoritativePresentationMax(p) > 0,
            ) || presentations[0];
            const firstMax = authoritativePresentationMax(initialPresentation);
            return {
                key: s.prescription_item_id,
                productName: s.product_name,
                dose: s.dose,
                baseUnit: s.base_unit_display || s.base_unit || "",
                prescribed: Number(s.prescribed_quantity_base),
                fulfilled: Number(s.fulfilled_quantity_base),
                selectedBase: Number(s.selected_quantity_base),
                remainingBase: Number(s.legal_remaining_quantity_base),
                presentations,
                // La receta es una sugerencia clínica: nunca se preselecciona.
                selected: false,
                decision: s.decision || "pending",
                presentationId: initialPresentation?.id ? String(initialPresentation.id) : "",
                quantity: firstMax > 0 ? "1" : "0",
                // Trazabilidad por lote (B2c): picker FEFO si el producto lo usa.
                tracksLots: !!s.tracks_lots,
                lot: null,
            };
        })
    );
    const [submitting, setSubmitting] = useState(false);
    const [dispenseIdempotencyKey] = useState(() => newIdempotencyKey());
    const setRow = (key, patch) => setRows(prev => prev.map(r => r.key === key ? { ...r, ...patch } : r));

    // El backend es la única autoridad clínica/de inventario. El frontend solo
    // presenta el máximo adicional resuelto en unidades de presentación.
    const maxQtyFor = (r, presentationId = r.presentationId) => {
        const p = r.presentations.find(x => String(x.id) === String(presentationId));
        return authoritativePresentationMax(p);
    };

    const selected = rows.filter(r =>
        r.selected && r.presentationId &&
        Number(r.quantity) > 0 && Number(r.quantity) <= maxQtyFor(r)
    );
    const overCap = rows.some(r =>
        r.selected && r.presentationId && Number(r.quantity) > maxQtyFor(r)
    );
    const canSubmit = selected.length > 0 && !overCap && !submitting;

    const submit = async () => {
        const lines = selected.map(r => ({
            presentation: Number(r.presentationId),
            quantity: Number(r.quantity),
            prescription_item: r.key,
            ...(r.tracksLots && r.lot?.id ? { lot: r.lot.id } : {}),
        }));
        setSubmitting(true);
        // sonner v2: toast.promise NO resuelve a la data — await la promesa real
        // para obtener la factura de consulta actualizada.
        const req = dispensePrescription(invoice.prescription_public_id, {
            lines,
            expectedVersion: invoice.version,
            idempotencyKey: dispenseIdempotencyKey,
        });
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

    const decline = async (row) => {
        setSubmitting(true);
        try {
            const updated = await toast.promise(
                decidePrescriptionItem(invoice.public_id, row.key, {
                    decision: "declined",
                    reasonCode: "not_now",
                    expectedVersion: invoice.version,
                }),
                {
                    loading: "Registrando decisión...",
                    success: "Medicamento rechazado para esta compra",
                    error: (err) => apiError(err, "No se pudo registrar la decisión"),
                },
            );
            onDispensed(updated);
        } finally {
            setSubmitting(false);
        }
    };

    // Solo se dispensa mientras la preparación comercial sigue abierta.
    // a esta factura antes de confirmar). Confirmada/pagada → sin panel.
    if (!invoice.prescription_public_id || suggestions.length === 0 || invoice.lifecycle !== "open") return null;

    return (
        <div style={{ marginTop: "20px" }}>
            <p className={s.eyebrow} style={{ marginBottom: "4px" }}>
                Medicamentos recetados (opcionales)
            </p>
            <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginBottom: "10px" }}>
                Los siguientes medicamentos fueron recetados por el veterinario. Solo agrega los que el cliente decida comprar; lo demás no toca inventario.
            </p>
            <div className="table-wrap"><table className="table">
                <thead>
                    <tr>
                        <th style={{ width: "28px" }}></th>
                        <th>Medicamento</th>
                        <th style={{ width: "180px" }}>Presentación</th>
                        <th style={{ width: "150px" }}>Lote</th>
                        <th style={{ width: "70px" }}>Cant.</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(r => {
                        const noPres = r.presentations.length === 0;
                        const exhausted = r.remainingBase <= 0;
                        const max = maxQtyFor(r);
                        const currentPresentation = r.presentations.find(
                            presentation => String(presentation.id) === String(r.presentationId),
                        );
                        const blockingReason = currentPresentation?.blocking_reasons
                            ?.map(code => PRESCRIPTION_BLOCK_REASON[code] || code)
                            .join(" · ");
                        const noSelectable = !r.presentations.some(
                            presentation => maxQtyFor(r, presentation.id) > 0,
                        );
                        const over = r.selected && Number(r.quantity) > max;
                        const unitLabel = r.baseUnit ? ` ${r.baseUnit.toLowerCase()}` : "";
                        return (
                            <tr key={r.key} style={{ opacity: r.selected ? 1 : 0.45 }}>
                                <td>
                                    <input
                                        type="checkbox" checked={r.selected}
                                        disabled={submitting || noPres || exhausted || noSelectable}
                                        onChange={e => setRow(r.key, { selected: e.target.checked })}
                                    />
                                </td>
                                <td>
                                    <div>{r.productName}</div>
                                    {r.dose && <div style={{ fontSize: "11px", color: "var(--c-text-3)" }}>{r.dose}</div>}
                                    <div style={{ fontSize: "11px", color: exhausted ? "var(--c-success-text)" : "var(--c-text-3)" }}>
                                        {exhausted
                                            ? "Dispensado por completo"
                                            : `Recetado ${r.prescribed}${unitLabel}${r.fulfilled > 0 ? ` · surtido ${r.fulfilled}` : ""}${r.selectedBase > 0 ? ` · seleccionado ${r.selectedBase}` : ""} · restante legal ${r.remainingBase}`}
                                    </div>
                                    {r.decision === "pending" && !r.selected && !exhausted && (
                                        <button className="btn btn-ghost btn-xs" onClick={() => decline(r)} disabled={submitting}>
                                            No lo llevará
                                        </button>
                                    )}
                                    {r.decision === "declined" && (
                                        <div style={{ fontSize: "11px", color: "var(--c-text-3)" }}>Rechazado en esta compra</div>
                                    )}
                                </td>
                                <td>
                                    {noPres ? (
                                        <span style={{ fontSize: "11px", color: "var(--c-danger-text)" }}>Sin presentación de venta</span>
                                    ) : exhausted ? (
                                        <span style={{ fontSize: "11px", color: "var(--c-text-4)" }}>—</span>
                                    ) : (
                                        <select
                                            className="input" style={{ height: "30px" }}
                                            value={r.presentationId} disabled={!r.selected || submitting}
                                            onChange={e => {
                                                const nextMax = maxQtyFor(r, e.target.value);
                                                setRow(r.key, {
                                                    presentationId: e.target.value,
                                                    lot: null,
                                                    // Clamp al nuevo máximo del formato elegido.
                                                    quantity: String(Math.min(Math.max(Number(r.quantity) || 1, 1), Math.max(nextMax, 0))),
                                                });
                                            }}
                                        >
                                            {r.presentations.map(p => (
                                                <option key={p.id} value={p.id} disabled={authoritativePresentationMax(p) <= 0}>
                                                    {p.name} — ${Number(p.sale_price).toFixed(2)} (disponible {p.available_stock_quantity_presentations})
                                                </option>
                                            ))}
                                        </select>
                                    )}
                                </td>
                                <td>
                                    {r.tracksLots && r.selected && !noPres && !exhausted ? (
                                        <DispenseLotSelect row={r} setRow={setRow} disabled={submitting} />
                                    ) : (
                                        <span style={{ fontSize: "11px", color: "var(--c-text-4)" }}>—</span>
                                    )}
                                </td>
                                <td>
                                    <input
                                        type="number" className="input"
                                        style={{ width: "60px", height: "30px", textAlign: "right", borderColor: over ? "var(--c-danger-text)" : undefined }}
                                        min="1" max={max} step="1"
                                        value={r.quantity} disabled={!r.selected || submitting || noPres || exhausted}
                                        onChange={e => setRow(r.key, { quantity: e.target.value })}
                                    />
                                    {!noPres && !exhausted && (
                                        <div style={{ fontSize: "10px", textAlign: "right", marginTop: "2px", color: over ? "var(--c-danger-text)" : "var(--c-text-4)" }}>
                                            máx {max}
                                            {max === 0 && blockingReason ? <><br />{blockingReason}</> : null}
                                        </div>
                                    )}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table></div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "10px" }}>
                <button className="btn btn-primary btn-sm" onClick={submit} disabled={!canSubmit}>
                    {submitting ? <Icon.Loader s={14} /> : "Agregar al cobro"}
                </button>
            </div>
        </div>
    );
};

const Billing = () => {
    const { token, user, initializing, can } = useAuth();
    const confirm = useConfirm();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const [loading, setLoading] = useState(true);
    const requestIdRef = useRef(0);

    const [invoices, setInvoices] = useState([]);
    const [checkouts, setCheckouts] = useState([]);

    // P1-2: paginación server-side (PageNumber 25) + ordering server-side.
    const PAGE_SIZE = 25;
    const [page, setPage] = useState(1);
    const [invoiceCount, setInvoiceCount] = useState(0);
    // Sort server-side: (sortCol, sortDir) → `?ordering`. Declarado aquí arriba
    // porque los efectos de carga lo leen en su dependency array (evita TDZ).
    const [sortCol, setSortCol] = useState("created_at");
    const [sortDir, setSortDir] = useState("desc");
    const handleSort = (col) => {
        if (sortCol === col) {
            setSortDir(d => (d === "asc" ? "desc" : "asc"));
        } else {
            setSortCol(col);
            setSortDir(col === "created_at" ? "desc" : "asc");
        }
        setPage(1);  // cambiar orden vuelve a la primera página
    };

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

    const [showRefundModal, setShowRefundModal] = useState(false);
    const [reversingCnId, setReversingCnId] = useState(null);
    const [showReplacementModal, setShowReplacementModal] = useState(false);
    const [replacementReason, setReplacementReason] = useState("correction");
    const [replacementMode, setReplacementMode] = useState("replacement");
    const [terminalReasonCode, setTerminalReasonCode] = useState("full_return");
    const [terminalReasonNotes, setTerminalReasonNotes] = useState("");
    const [replacementDispositions, setReplacementDispositions] = useState([]);
    const [replacing, setReplacing] = useState(false);
    const [disputeBusy, setDisputeBusy] = useState(false);

    // Caja (ADR p28): turno actual + si la org exige caja abierta para cobrar.
    const [cashSession, setCashSession] = useState(undefined); // undefined=cargando | null=cerrada | obj=abierta
    const [requireCash, setRequireCash] = useState(false);
    const [allowPostUnpaid, setAllowPostUnpaid] = useState(false);
    const [creditDefaultDays, setCreditDefaultDays] = useState(30);

    // Feedback de filtros: atenúa la tabla mientras hay un fetch en vuelo.
    const [fetching, setFetching] = useState(false);

    const loadInvoices = async (currentFilters, pageArg = 1, ordering = "-created_at") => {
        const requestId = ++requestIdRef.current;
        setFetching(true);
        try {
            const params = {};
            for (const key of FILTER_KEYS) if (currentFilters[key]) params[key] = currentFilters[key];
            params.page = pageArg;
            params.ordering = ordering;
            const data = await getInvoices(params);
            if (requestId === requestIdRef.current) {
                setInvoices(toList(data));
                // PageNumber expone `count` total; si el backend aún devolviera
                // array plano (rollback), el conteo cae a la longitud local.
                setInvoiceCount(Array.isArray(data) ? data.length : (data?.count ?? 0));
            }
        } catch (err) {
            if (requestId === requestIdRef.current) toast.error(apiError(err, "No se pudieron cargar los cobros"));
        } finally {
            if (requestId === requestIdRef.current) setFetching(false);
        }
    };

    const loadCheckouts = async () => {
        const data = await getCheckouts({ lifecycle: "open" });
        setCheckouts(toList(data));
    };

    // Caja: la sesión llega vía CajaBar (onSession) — sin GET duplicado.
    // Aquí solo se carga el flag de la org. Silencioso: si falla, no bloquea.
    const loadCashSettings = async () => {
        const settings = await getOrgSettings().catch(() => null);
        setRequireCash(!!settings?.require_open_cash_session);
        setAllowPostUnpaid(!!settings?.allow_post_unpaid);
        setCreditDefaultDays(Number(settings?.credit_default_days) || 30);
    };

    const loadAll = async () => {
        setLoading(requestIdRef.current === 0);
        try {
            await Promise.all([loadInvoices(filters), loadCheckouts(), loadCashSettings()]);
        } catch {
            // Silencioso — loadInvoices maneja su error
        } finally { setLoading(false); }
    };

    useEffect(() => { if (token) { loadAll(); } }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => {
        const ordering = (sortDir === "desc" ? "-" : "") + sortCol;
        const timer = setTimeout(() => loadInvoices(filters, page, ordering), 300);
        return () => clearTimeout(timer);
    }, [filters.status, filters.invoice_type, filters.created_from, filters.created_to, filters.paid_from, filters.paid_to, page, sortCol, sortDir]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        // F11 = nueva venta → vive en el POS (pantalla dedicada).
        const handleKeyDown = (e) => {
            if (e.key === 'F11' && can("invoice.create") && !showDetailModal) {
                e.preventDefault();
                navigate("/pos");
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [can, showDetailModal, navigate]);

    useEffect(() => {
        const invoiceParam = searchParams.get("invoice");
        const checkoutParam = searchParams.get("checkout");
        if (checkoutParam && token && !loading) {
            getCheckout(checkoutParam).then((detail) => {
                setSelectedInvoice({ ...detail, _isCheckout: true });
                setShowDetailModal(true);
            }).catch(() => {});
        } else if (invoiceParam && token && !loading) {
            getInvoice(invoiceParam).then((detail) => {
                setSelectedInvoice(detail);
                setShowDetailModal(true);
            }).catch(() => {});
        }
    }, [token, loading]); // eslint-disable-line react-hooks/exhaustive-deps

    // Acepta un patch con varias claves a la vez: el DateRangePicker actualiza
    // created_from y created_to juntos. Dos llamadas consecutivas a un setter
    // de una sola clave leían `filters` stale y la segunda pisaba a la primera
    // (se perdía created_from). Un solo setFilters por evento evita la carrera.
    const updateFilters = (patch) => {
        const next = { ...filters, ...patch };
        setFilters(next);
        setPage(1);  // cambiar filtros vuelve a la primera página
        const params = new URLSearchParams();
        for (const k of FILTER_KEYS) if (next[k]) params.set(k, next[k]);
        setSearchParams(params, { replace: true });
    };
    const updateFilter = (key, value) => updateFilters({ [key]: value });

    const clearFilters = () => {
        const empty = {};
        for (const key of FILTER_KEYS) empty[key] = "";
        setFilters(empty);
        setPage(1);
        setSearchParams({}, { replace: true });
    };

    const openInvoiceDetail = async (invoice) => {
        try {
            const detail = await getInvoice(invoice.public_id);
            setSelectedInvoice(detail);
            setShowDetailModal(true);
        } catch { toast.error("Error al cargar el cobro"); }
    };

    const openCheckoutDetail = async (checkout) => {
        try {
            const detail = await getCheckout(checkout.public_id);
            setSelectedInvoice({ ...detail, _isCheckout: true });
            setShowDetailModal(true);
        } catch { toast.error("Error al cargar la preparación de cobro"); }
    };

    const closeDetailModal = () => {
        setShowDetailModal(false);
        setSelectedInvoice(null);
        setShowPayModal(false);
        setShowRefundModal(false);
        setShowReplacementModal(false);
    };

    const handleDownloadInvoicePDF = async (publicId) => {
        setDownloadingInvoiceId(publicId);
        try {
            const { blob, contentDisposition } = await downloadInvoicePDF(publicId);
            const filename = extractFilename(contentDisposition, "cobro.pdf");
            triggerDownload(blob, filename);
        } catch (err) { toast.error(apiError(err, "Error al descargar PDF")); }
        finally { setDownloadingInvoiceId(null); }
    };

    const openPayModal = () => {
        const target = selectedInvoice?._isCheckout
            ? Number(selectedInvoice.total)
            : Number(selectedInvoice.remaining_balance);
        setPayLines([{ method: "cash", amount: target > 0 ? target.toFixed(2) : "" }]);
        setPayIdemKey(newIdempotencyKey());
        setShowPayModal(true);
    };

    // ADR p30 (rev): toda factura exige total exacto — sin parcial. Si recibe
    // efectivo > total, se registra SOLO el total (el excedente es cambio para
    // el cliente, no se persiste). Aplica a venta directa Y a consulta.
    const submitPayment = async () => {
        const paymentLines = buildPaymentLines(
            payLines, selectedInvoice._isCheckout ? selectedInvoice.total : selectedInvoice.remaining_balance
        );
        const call = selectedInvoice._isCheckout
            ? payCheckout(selectedInvoice.public_id, {
                paymentLines, expectedVersion: selectedInvoice.version,
                idempotencyKey: payIdemKey,
            })
            : payInvoice(selectedInvoice.public_id, { paymentLines, idempotencyKey: payIdemKey });
        setPaying(true);
        // sonner v2: toast.promise NO resuelve a la data — await la promesa real.
        toast.promise(call, {
            loading: 'Cobrando...',
            success: 'Pago registrado',
            error: (err) => apiError(err, "Error"),
        });
        try {
            const updated = await call;
            setSelectedInvoice(updated);
            setShowPayModal(false);
            await Promise.all([loadInvoices(filters), loadCheckouts()]);
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
        if (selectedInvoice?._isCheckout) {
            const detail = await getCheckout(selectedInvoice.public_id);
            setSelectedInvoice({ ...detail, _isCheckout: true });
            await loadCheckouts();
        } else {
            await refreshSelectedInvoice();
        }
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

    const handleCheckoutEstimate = async () => {
        const marker = `estimate:${selectedInvoice.public_id}`;
        setDownloadingInvoiceId(marker);
        try {
            const estimate = await issueCheckoutEstimate(selectedInvoice.public_id, {
                expectedVersion: selectedInvoice.version,
                idempotencyKey: newIdempotencyKey(),
            });
            const { blob, contentDisposition } = await downloadCheckoutEstimatePDF(estimate.public_id);
            triggerDownload(blob, extractFilename(contentDisposition, 'estimado-no-factura.pdf'));
        } catch (err) {
            toast.error(apiError(err, 'No se pudo generar el estimado'));
        } finally {
            setDownloadingInvoiceId(null);
        }
    };

    const handlePostCheckout = async () => {
        const accepted = await confirm({
            title: "Dejar cobro pendiente",
            message: `Confirma que el cliente aceptó el importe y que se entregaron los productos incluidos. Se creará una obligación con vencimiento a ${creditDefaultDays} días.`,
            confirmText: "Emitir pendiente",
        });
        if (!accepted) return;
        const dueAt = new Date();
        dueAt.setDate(dueAt.getDate() + creditDefaultDays);
        const req = postCheckout(selectedInvoice.public_id, {
            expectedVersion: selectedInvoice.version,
            dueAt: dueAt.toISOString(),
            creditReason: "customer_will_pay_later",
            obligationEvidence: {
                basis: "customer_acknowledgement",
                accepting_party: selectedInvoice.customer_name || "Cliente presente",
                channel: "in_person",
            },
            idempotencyKey: newIdempotencyKey(),
        });
        try {
            await toast.promise(req, {
                loading: "Emitiendo...", success: "Cobro emitido",
                error: (err) => apiError(err, "No se pudo emitir el cobro"),
            });
            closeDetailModal();
            await Promise.all([loadInvoices(filters), loadCheckouts()]);
        } catch { /* toast.promise mostró el error */ }
    };

    const handleNoCharge = async () => {
        const req = completeCheckoutNoCharge(selectedInvoice.public_id, {
            reason: "no_billable_items",
            expectedVersion: selectedInvoice.version,
            idempotencyKey: newIdempotencyKey(),
        });
        try {
            await toast.promise(req, {
                loading: "Completando...", success: "Consulta cerrada sin cargo",
                error: (err) => apiError(err, "No se pudo completar"),
            });
            closeDetailModal();
            await loadCheckouts();
        } catch { /* toast.promise mostró el error */ }
    };

    const openReplacementModal = (mode = "replacement") => {
        setReplacementMode(mode);
        setReplacementReason("correction");
        setTerminalReasonCode("full_return");
        setTerminalReasonNotes("");
        setReplacementDispositions(
            selectedInvoice.items
                .filter(item => item.has_stock_allocation)
                .map(item => ({
                    invoice_item: item.id,
                    outcome: mode === "terminal" ? "returned_restocked" : "goods_retained",
                })),
        );
        setShowReplacementModal(true);
    };

    const submitReplacement = async () => {
        setReplacing(true);
        try {
            if (replacementMode === "terminal") {
                await voidInvoiceTerminal(selectedInvoice.public_id, {
                    reasonCode: terminalReasonCode,
                    reasonNotes: terminalReasonNotes,
                    dispositions: replacementDispositions,
                    idempotencyKey: newIdempotencyKey(),
                });
                toast.success("Factura anulada terminalmente");
                closeDetailModal();
            } else {
                const replacement = await voidAndPrepareReplacement(selectedInvoice.public_id, {
                    reason: replacementReason,
                    dispositions: replacementDispositions,
                    idempotencyKey: newIdempotencyKey(),
                });
                toast.success("Factura anulada y corrección preparada");
                setSelectedInvoice({ ...replacement, _isCheckout: true });
            }
            setShowReplacementModal(false);
            await Promise.all([loadInvoices(filters), loadCheckouts()]);
        } catch (err) {
            toast.error(apiError(err, "No se pudo preparar la corrección"));
        } finally {
            setReplacing(false);
        }
    };

    const handleWaiveReplacement = async () => {
        const accepted = await confirm({
            title: "Condonar obligación corregida",
            message: "La corrección se cerrará sin reemitir el valor ya entregado. La condonación quedará auditada.",
            confirmText: "Condonar",
            dangerMode: true,
        });
        if (!accepted) return;
        try {
            await waiveReplacement(selectedInvoice.public_id, {
                reasonCode: "authorized_waiver",
                evidence: { channel: "in_app", note: "Condonación autorizada desde Cobros" },
                expectedVersion: selectedInvoice.version,
                idempotencyKey: newIdempotencyKey(),
            });
            toast.success("Obligación condonada");
            closeDetailModal();
            await loadCheckouts();
        } catch (err) {
            toast.error(apiError(err, "No se pudo registrar la condonación"));
        }
    };

    const formatDate = (dateString) => dateString ? new Date(dateString).toLocaleDateString("es-ES", { year: "numeric", month: "short", day: "numeric" }) : "—";
    const handleOpenDispute = async () => {
        const statement = window.prompt("Describe qué importe u obligación disputa el cliente:");
        if (!statement?.trim()) return;
        setDisputeBusy(true);
        try {
            await openCheckoutDispute(selectedInvoice.public_id, {
                itemIds: selectedInvoice.items.map(item => item.id),
                statement: statement.trim(), owner: user.id,
                reviewDueAt: new Date(Date.now() + 2 * 86400000).toISOString(),
                evidence: { channel: "in_person" },
                expectedVersion: selectedInvoice.version,
                idempotencyKey: newIdempotencyKey(),
            });
            const detail = await getCheckout(selectedInvoice.public_id);
            setSelectedInvoice({ ...detail, _isCheckout: true });
            await loadCheckouts();
            toast.success("Disputa registrada y cobro bloqueado");
        } catch (err) {
            toast.error(apiError(err, "No se pudo registrar la disputa"));
        } finally { setDisputeBusy(false); }
    };

    const handleAcceptDispute = async () => {
        const dispute = selectedInvoice.open_dispute;
        if (!dispute) return;
        const reason = window.prompt("Justificación de la aceptación:");
        if (!reason?.trim()) return;
        setDisputeBusy(true);
        try {
            await resolveCheckoutDispute(dispute.public_id, {
                resolution: "accepted", reason: reason.trim(),
                resolutionEvidence: { channel: "in_person" },
                expectedVersion: selectedInvoice.version,
                idempotencyKey: newIdempotencyKey(),
            });
            const detail = await getCheckout(selectedInvoice.public_id);
            setSelectedInvoice({ ...detail, _isCheckout: true });
            await loadCheckouts();
            toast.success("Disputa resuelta; el cobro vuelve a estar disponible");
        } catch (err) {
            toast.error(apiError(err, "No se pudo resolver la disputa"));
        } finally { setDisputeBusy(false); }
    };

    const handleAdjustReplacement = async () => {
        const baseline = selectedInvoice.items.find(item => item.required_replacement_baseline);
        if (!baseline) return;
        const amount = window.prompt("Monto de reducción parcial (debe quedar saldo positivo):");
        const note = amount && window.prompt("Justificación del ajuste:");
        if (!amount || !note?.trim()) return;
        try {
            const updated = await adjustReplacementExposure(selectedInvoice.public_id, {
                itemId: baseline.id, amount, reasonCode: "pricing_correction",
                note: note.trim(), evidence: { channel: "in_app" },
                expectedVersion: selectedInvoice.version, idempotencyKey: newIdempotencyKey(),
            });
            setSelectedInvoice({ ...updated, _isCheckout: true });
            await loadCheckouts();
            toast.success("Exposición de reemplazo ajustada");
        } catch (err) { toast.error(apiError(err, "No se pudo ajustar la exposición")); }
    };

    const handleTakeReplacement = async () => {
        try {
            const updated = await assignReplacementOwner(selectedInvoice.public_id, {
                owner: user.id,
                correctionDueAt: new Date(Date.now() + 2 * 86400000).toISOString(),
                reasonCode: "owner_takeover", expectedVersion: selectedInvoice.version,
                idempotencyKey: newIdempotencyKey(),
            });
            setSelectedInvoice({ ...updated, _isCheckout: true });
            await loadCheckouts();
            toast.success("Corrección asignada");
        } catch (err) { toast.error(apiError(err, "No se pudo asignar la corrección")); }
    };

    const formatCurrency = (amount) => Number(amount || 0).toFixed(2);

    if (initializing || loading) return <div style={{ display: "flex", justifyContent: "center", padding: "100px", color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</div>;

    const isCheckout = !!selectedInvoice?._isCheckout;
    const payTarget = selectedInvoice
        ? Number(isCheckout ? selectedInvoice.total : selectedInvoice.remaining_balance)
        : 0;
    // Solo bloquea si la org exige caja Y sabemos que está cerrada (no en carga).
    const cashBlocked = requireCash && cashSession === null;
    const checkoutAction = (name) => selectedInvoice?.actions?.[name] || null;
    const checkoutActionBlocked = (name) => checkoutAction(name)?.allowed === false;
    const checkoutActionTitle = (name) => {
        const blockers = checkoutAction(name)?.blockers || [];
        return blockers.map(blocker => blocker.message).join(" ") || undefined;
    };

    const hasActiveFilters = FILTER_KEYS.some(k => filters[k]);

    return (
        <div className={s.billingContainer}>
            <div className="page-header">
                <h1 className="page-title">Cobros</h1>
                {/* Estado de caja (Fase 3): estado + abrir/cerrar sin fila completa.
                    onSession alimenta cashBlocked — único GET de sesión de la página. */}
                <CajaBar variant="compact" onSession={setCashSession} />
            </div>

            {cashBlocked && (
                <div className={s.cashNotice} role="status">
                    <Icon.AlertTriangle s={15} />
                    <span><strong>No hay una caja abierta.</strong> Ábrela para registrar pagos.</span>
                </div>
            )}

            <div className={s.filterBar}>
                <select
                    className="select-input"
                    style={{ width: "auto", height: "36px", fontSize: "13px" }}
                    value={filters.status}
                    onChange={e => updateFilter("status", e.target.value)}
                >
                    <option value="">Todos los estados</option>
                    {Object.entries(STATUS_LABELS).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
                </select>
                <select
                    className="select-input"
                    style={{ width: "auto", height: "36px", fontSize: "13px" }}
                    value={filters.invoice_type}
                    onChange={e => updateFilter("invoice_type", e.target.value)}
                >
                    <option value="">Todos los tipos</option>
                    {Object.entries(TYPE_LABELS).map(([v, l]) => (<option key={v} value={v}>{l}</option>))}
                </select>
                <DateRangePicker from={filters.created_from} to={filters.created_to} onChange={(f, t) => updateFilters({ created_from: f, created_to: t })} placeholder="Creado" />
                {hasActiveFilters && (
                    <button className="btn btn-ghost btn-sm" onClick={clearFilters}>
                        <Icon.X s={12} />
                        Limpiar
                    </button>
                )}
                {can("invoice.create") && (
                    <button
                        className="btn btn-primary btn-sm"
                        style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "6px" }}
                        onClick={() => navigate("/pos")}
                        title="Atajo: F11 — abre el Punto de Venta"
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

            {checkouts.length > 0 && (
                <div className="table-wrap" style={{ marginBottom: "20px" }}>
                    <table className="table">
                        <thead><tr>
                            <th>Preparación</th><th>Mascota / Cliente</th><th>Origen</th>
                            <th>Estado</th><th style={{ textAlign: "right" }}>Total</th><th></th>
                        </tr></thead>
                        <tbody>{checkouts.map(checkout => (
                            <tr key={checkout.public_id}>
                                <td style={{ color: "var(--c-text-3)" }}>#{checkout.id}</td>
                                <td>
                                    <div>{checkout.pet_name || "Venta de mostrador"}</div>
                                    <div style={{ fontSize: "11px", color: "var(--c-text-3)" }}>{checkout.customer_name}</div>
                                </td>
                                <td>{checkout.origin === "consultation" ? "Consulta" : "Venta directa"}</td>
                                <td>{checkout.operational_hold === "dispute" ? "En disputa" : checkout.correction_status === "correction_overdue" ? "Corrección vencida" : "Por preparar"}</td>
                                <td style={{ textAlign: "right" }}>${formatCurrency(checkout.total)}</td>
                                <td style={{ textAlign: "right" }}>
                                    <button className="btn btn-ghost btn-icon" aria-label={`Abrir preparación ${checkout.id}`} onClick={() => openCheckoutDetail(checkout)}><Icon.Eye s={14} /></button>
                                </td>
                            </tr>
                        ))}</tbody>
                    </table>
                    <div className="table-footer">{checkouts.length} preparación{checkouts.length !== 1 ? "es" : ""} pendiente{checkouts.length !== 1 ? "s" : ""}</div>
                </div>
            )}

            {invoices.length === 0 ? (
                <div className="empty-state">
                    <p className="empty-state-title">{fetching ? "Buscando cobros..." : "No hay cobros"}</p>
                </div>
            ) : (
                <div className="table-wrap" style={{ opacity: fetching ? 0.6 : 1, transition: "opacity var(--t)" }}>
                    <table className="table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Mascota / Cliente</th>
                                <th>Tipo</th>
                                <th>Estado</th>
                                <SortHeader col="created_at" label="Fecha" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                                <SortHeader col="total" label="Total" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} align="right" />
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {invoices.map(inv => (
                                <tr key={inv.id}>
                                    <td style={{ color: "var(--c-text-3)" }}>#{inv.id}</td>
                                    <td>
                                        <div>{inv.pet_name}</div>
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
                                    <td style={{ textAlign: "right" }}>${formatCurrency(inv.total)}</td>
                                    <td style={{ textAlign: "right" }}>
                                        <button className="btn btn-ghost btn-icon" aria-label={`Ver cobro ${inv.id}`} onClick={() => openInvoiceDetail(inv)}><Icon.Eye s={14} /></button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    <div className="table-footer">
                        {fetching ? "Actualizando..." : `${invoiceCount} cobro${invoiceCount !== 1 ? "s" : ""}`}
                    </div>
                    <Pagination
                        page={page}
                        count={invoiceCount}
                        pageSize={PAGE_SIZE}
                        onPage={setPage}
                        fetching={fetching}
                    />
                </div>
            )}

            {/* Detail Modal */}
            {showDetailModal && selectedInvoice && (
                <div className="modal-overlay">
                    <div className="modal modal-lg">
                        <div className="modal-header">
                            <div>
                                <h3 style={{ fontSize: "16px", fontWeight: 700, color: "var(--c-text)" }}>#{selectedInvoice.id}</h3>
                                <div className={s.statusContainer} style={{ marginTop: "4px" }}>
                                    <span className={s.statusDot} style={{ background: isCheckout ? "var(--c-warning-text)" : DOT_COLOR[selectedInvoice.status] }} />
                                    {isCheckout ? (selectedInvoice.operational_hold === "dispute" ? "Preparación en disputa" : "Preparación abierta") : STATUS_LABELS[selectedInvoice.status]}
                                </div>
                            </div>
                            <div style={{ display: "flex", gap: "8px" }}>
                                {isCheckout && can('checkout.estimate.issue') && (
                                    <button className="btn btn-secondary btn-sm" onClick={handleCheckoutEstimate} disabled={downloadingInvoiceId === `estimate:${selectedInvoice.public_id}`}>
                                        {downloadingInvoiceId === `estimate:${selectedInvoice.public_id}` ? <Icon.Loader s={12} /> : <Icon.Download s={12} />} Estimado
                                    </button>
                                )}
                                {!isCheckout && <button className="btn btn-secondary btn-sm" onClick={() => handleDownloadInvoicePDF(selectedInvoice.public_id)} disabled={downloadingInvoiceId === selectedInvoice.public_id}>
                                    {downloadingInvoiceId === selectedInvoice.public_id ? <Icon.Loader s={12} /> : <Icon.Download s={12} />} PDF
                                </button>}
                                <button className="modal-close" onClick={closeDetailModal}><Icon.X s={14} /></button>
                            </div>
                        </div>
                        <div className="modal-body">
                            {isCheckout && selectedInvoice.preparation_readiness?.blockers?.length > 0 && (
                                <div className={s.cashNotice} role="status" style={{ marginBottom: "14px" }}>
                                    <Icon.AlertTriangle s={15} />
                                    <span>
                                        {selectedInvoice.preparation_readiness.blockers
                                            .map(blocker => blocker.message)
                                            .join(" ")}
                                    </span>
                                </div>
                            )}
                            <div className={s.infoGrid}>
                                <div><p className={s.infoLabel}>Mascota</p><p className={s.infoValue}>{selectedInvoice.pet_name}</p></div>
                                <div><p className={s.infoLabel}>Cliente</p><p className={s.infoValue}>{selectedInvoice.customer_name || selectedInvoice.owner_name}</p></div>
                                <div><p className={s.infoLabel}>Fecha</p><p className={s.infoValue}>{formatDate(selectedInvoice.created_at)}</p></div>
                            </div>

                            <p className={s.eyebrow}>Conceptos</p>
                            <div className="table-wrap"><table className="table">
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
                            </table></div>

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
                                    <p className={s.eyebrow} style={{ marginBottom: "8px" }}>
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
                                key={`${selectedInvoice.public_id}:${selectedInvoice.version || 0}`}
                                invoice={selectedInvoice}
                                onDispensed={handleDispensed}
                            />
                        </div>
                        <div className="modal-footer">
                            <div style={{ display: "flex", gap: "8px", width: "100%" }}>
                                {isCheckout && Number(selectedInvoice.total) > 0 && !selectedInvoice.operational_hold && (
                                    <button className="btn btn-primary btn-md" style={{ flex: 1, background: "var(--c-success-text)", borderColor: "var(--c-success-text)", color: "#fff" }} onClick={openPayModal} disabled={cashBlocked || checkoutActionBlocked("pay")} title={cashBlocked ? "Abre una caja para cobrar" : checkoutActionTitle("pay")}>
                                        Cobrar
                                    </button>
                                )}
                                {isCheckout && Number(selectedInvoice.total) > 0 && !selectedInvoice.operational_hold && selectedInvoice.origin === "consultation" && allowPostUnpaid && can("invoice.post_unpaid") && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={handlePostCheckout} disabled={checkoutActionBlocked("post_unpaid")} title={checkoutActionTitle("post_unpaid")}>Emitir pendiente</button>
                                )}
                                {isCheckout && Number(selectedInvoice.total) === 0 && !selectedInvoice.operational_hold && (
                                    <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleNoCharge} disabled={checkoutActionBlocked("complete_no_charge")} title={checkoutActionTitle("complete_no_charge")}>Completar sin cargo</button>
                                )}
                                {!isCheckout && selectedInvoice.status === "posted" && (
                                    <button className="btn btn-primary btn-md" style={{ flex: 1, background: "var(--c-success-text)", borderColor: "var(--c-success-text)", color: "#fff" }} onClick={openPayModal} disabled={cashBlocked} title={cashBlocked ? "Abre una caja para cobrar" : undefined}>Registrar Pago</button>
                                )}
                                {selectedInvoice.status === "paid" && can("billing.refund") && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={() => setShowRefundModal(true)}>Devolver</button>
                                )}
                                {!isCheckout && selectedInvoice.status === "posted" && can("invoice.replace") && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={() => openReplacementModal("replacement")}>Corregir emisión</button>
                                )}
                                {!isCheckout && selectedInvoice.status === "posted" && can("invoice.void_terminal") && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={() => openReplacementModal("terminal")}>Anular</button>
                                )}
                                {isCheckout && selectedInvoice.kind === "replacement" && can("invoice.replace_waive") && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={handleWaiveReplacement} disabled={checkoutActionBlocked("waive_replacement")} title={checkoutActionTitle("waive_replacement")}>Condonar</button>
                                )}
                                {isCheckout && !selectedInvoice.operational_hold && can("checkout.dispute.open") && Number(selectedInvoice.total) > 0 && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={handleOpenDispute} disabled={disputeBusy || checkoutActionBlocked("open_dispute")} title={checkoutActionTitle("open_dispute")}>Registrar disputa</button>
                                )}
                                {isCheckout && selectedInvoice.operational_hold === "dispute" && can("checkout.dispute.resolve") && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={handleAcceptDispute} disabled={disputeBusy}>Resolver: aceptado</button>
                                )}
                                {isCheckout && selectedInvoice.kind === "replacement" && can("invoice.replace_adjust") && !selectedInvoice.operational_hold && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={handleAdjustReplacement} disabled={checkoutActionBlocked("adjust_replacement")} title={checkoutActionTitle("adjust_replacement")}>Ajustar exposición</button>
                                )}
                                {isCheckout && selectedInvoice.kind === "replacement" && can("invoice.replace_manage") && !selectedInvoice.operational_hold && (
                                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={handleTakeReplacement}>Asignarme</button>
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
                                        {isCheckout ? "Cobrar preparación" : "Registrar pago"}
                                    </h3>
                                    <button className="modal-close" onClick={() => setShowPayModal(false)} disabled={paying}><Icon.X s={14} /></button>
                                </div>
                                <div className="modal-body">
                                    <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", marginBottom: "8px" }}>
                                        Método{payLines.length > 1 ? "s" : ""} de pago
                                    </label>
                                    <PaymentLinesEditor
                                        total={payTarget}
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
                                        disabled={paying || !paymentLinesValid(payLines, payTarget, true)}
                                    >
                                        {paying ? <Icon.Loader s={14} /> : "Registrar Pago"}
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}

                    {showReplacementModal && (
                        <div className="modal-overlay" style={{ zIndex: 1001 }}>
                            <div className="modal" style={{ maxWidth: "520px" }}>
                                <div className="modal-header">
                                    <h3 style={{ fontSize: "15px", fontWeight: 600 }}>
                                        {replacementMode === "terminal" ? "Anular factura" : "Corregir factura emitida"}
                                    </h3>
                                    <button className="modal-close" onClick={() => setShowReplacementModal(false)} disabled={replacing}><Icon.X s={14} /></button>
                                </div>
                                <div className="modal-body">
                                    <p style={{ margin: "0 0 14px", color: "var(--c-text-3)", fontSize: "13px" }}>
                                        {replacementMode === "terminal"
                                            ? "La obligación terminará sin reemplazo. Todos los productos entregados deben haber regresado o haberse descartado."
                                            : "La factura original quedará anulada y se abrirá una preparación vinculada. Indica qué ocurrió físicamente con cada producto."}
                                    </p>
                                    {replacementMode === "terminal" ? (
                                        <>
                                            <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>Resultado terminal</label>
                                            <select className="select-input" value={terminalReasonCode} onChange={event => setTerminalReasonCode(event.target.value)}>
                                                <option value="full_return">Devolución total</option>
                                                <option value="duplicate">Documento duplicado</option>
                                                <option value="invalid_obligation">Obligación inválida</option>
                                                <option value="authorized_waiver">Condonación autorizada</option>
                                                <option value="legal_cancellation">Cancelación legal</option>
                                            </select>
                                            <label style={{ display: "block", fontSize: "12px", fontWeight: 600, margin: "12px 0 6px" }}>Justificación</label>
                                            <textarea className="input" value={terminalReasonNotes} onChange={event => setTerminalReasonNotes(event.target.value)} maxLength={500} rows={3} />
                                        </>
                                    ) : (
                                        <>
                                            <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>Motivo de corrección</label>
                                            <input className="input" value={replacementReason} onChange={event => setReplacementReason(event.target.value)} maxLength={100} />
                                        </>
                                    )}
                                    {selectedInvoice.items.filter(item => item.has_stock_allocation).map(item => {
                                        const row = replacementDispositions.find(value => value.invoice_item === item.id);
                                        return (
                                            <div key={item.id} style={{ marginTop: "14px" }}>
                                                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>{item.description}</label>
                                                <select
                                                    className="select-input"
                                                    value={row?.outcome || "goods_retained"}
                                                    onChange={event => setReplacementDispositions(current => current.map(value => (
                                                        value.invoice_item === item.id ? { ...value, outcome: event.target.value } : value
                                                    )))}
                                                >
                                                    {replacementMode !== "terminal" && <option value="goods_retained">El cliente conserva el producto</option>}
                                                    <option value="returned_restocked">Devuelto y reintegrado a stock</option>
                                                    <option value="returned_discarded">Devuelto y descartado</option>
                                                </select>
                                            </div>
                                        );
                                    })}
                                </div>
                                <div className="modal-footer">
                                    <button className="btn btn-secondary btn-sm" onClick={() => setShowReplacementModal(false)} disabled={replacing}>Cancelar</button>
                                    <button className="btn btn-primary btn-sm" onClick={submitReplacement} disabled={replacing || (replacementMode === "terminal" ? !terminalReasonNotes.trim() : !replacementReason.trim())}>
                                        {replacing ? <Icon.Loader s={12} /> : (replacementMode === "terminal" ? "Anular definitivamente" : "Anular y preparar corrección")}
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

        </div>
    );
};

export default Billing;
