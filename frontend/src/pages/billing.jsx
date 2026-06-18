import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useConfirm } from "../components/useConfirm";
import { apiError } from "../utils/apiError";
import {
    getInvoices, getInvoice, confirmInvoice, payInvoice, directPayInvoice,
    downloadInvoicePDF, refundInvoice, reverseCreditNote,
    dispensePrescription,
} from "../api/billing";
import { extractFilename, triggerDownload } from "../utils/downloadBlob";
import { getOrgSettings } from "../api/organizations";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import { toast } from "sonner";
import PaymentLinesEditor from "../components/PaymentLinesEditor";
import { buildPaymentLines, paymentLinesValid } from "../utils/payments";
import { newIdempotencyKey } from "../utils/idempotency";
import { toList } from "../utils/toList";
import DateRangePicker from "../components/DateRangePicker";
import CajaBar from "../components/CajaBar";
import SortHeader from "../components/SortHeader";
import Pagination from "../components/Pagination";
import s from "./billing.module.css";

const FILTER_KEYS = ["status", "invoice_type", "created_from", "created_to", "paid_from", "paid_to"];
const STATUS_LABELS = { draft: "Borrador", confirmed: "Confirmada", paid: "Pagada", cancelled: "Cancelada" };
const TYPE_LABELS = { consultation: "Consulta", direct_sale: "Venta directa" };

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
        suggestions.map(s => {
            const presentations = s.presentations || [];
            // Cantidades de receta en unidades base del producto (ADR p31).
            const remainingBase = Number(s.remaining_quantity ?? s.suggested_quantity) || 0;
            const firstCf = Number(presentations[0]?.conversion_factor) || 1;
            const firstMax = Math.floor(remainingBase / firstCf);
            return {
                key: s.prescription_item_id,
                productName: s.product_name,
                dose: s.dose,
                baseUnit: s.base_unit || "",
                prescribed: Number(s.prescribed_quantity ?? s.suggested_quantity) || 0,
                dispensed: Number(s.dispensed_quantity) || 0,
                remainingBase,
                presentations,
                // Por defecto seleccionado solo si hay presentación vendible y cupo.
                selected: presentations.length > 0 && firstMax > 0,
                presentationId: presentations[0]?.id ? String(presentations[0].id) : "",
                quantity: firstMax > 0 ? "1" : "0",
            };
        })
    );
    const [submitting, setSubmitting] = useState(false);
    const setRow = (key, patch) => setRows(prev => prev.map(r => r.key === key ? { ...r, ...patch } : r));

    // Tope clínico (espejo del backend): máximo en unidades de la presentación
    // elegida = restante recetado (unidades base) / conversion_factor.
    const maxQtyFor = (r, presentationId = r.presentationId) => {
        const p = r.presentations.find(x => String(x.id) === String(presentationId));
        if (!p) return 0;
        const cfRaw = Number(p.conversion_factor);
        const cf = cfRaw > 0 ? cfRaw : 1;   // fail-safe ante cf corrupto (NaN/0/negativo)
        return Math.floor(r.remainingBase / cf);
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
                        <th style={{ width: "70px" }}>Cant.</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(r => {
                        const noPres = r.presentations.length === 0;
                        const exhausted = r.remainingBase <= 0;
                        const max = maxQtyFor(r);
                        const over = r.selected && Number(r.quantity) > max;
                        const unitLabel = r.baseUnit ? ` ${r.baseUnit.toLowerCase()}` : "";
                        return (
                            <tr key={r.key} style={{ opacity: r.selected ? 1 : 0.45 }}>
                                <td>
                                    <input
                                        type="checkbox" checked={r.selected}
                                        disabled={submitting || noPres || exhausted}
                                        onChange={e => setRow(r.key, { selected: e.target.checked })}
                                    />
                                </td>
                                <td>
                                    <div>{r.productName}</div>
                                    {r.dose && <div style={{ fontSize: "11px", color: "var(--c-text-3)" }}>{r.dose}</div>}
                                    <div style={{ fontSize: "11px", color: exhausted ? "var(--c-success-text)" : "var(--c-text-3)" }}>
                                        {exhausted
                                            ? "Dispensado por completo"
                                            : `Recetado ${r.prescribed}${unitLabel}${r.dispensed > 0 ? ` · en cobro ${r.dispensed}` : ""} · restante ${r.remainingBase}`}
                                    </div>
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
                                                    // Clamp al nuevo máximo del formato elegido.
                                                    quantity: String(Math.min(Math.max(Number(r.quantity) || 1, 1), Math.max(nextMax, 0))),
                                                });
                                            }}
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
                                        style={{ width: "60px", height: "30px", textAlign: "right", borderColor: over ? "var(--c-danger-text)" : undefined }}
                                        min="1" max={max} step="1"
                                        value={r.quantity} disabled={!r.selected || submitting || noPres || exhausted}
                                        onChange={e => setRow(r.key, { quantity: e.target.value })}
                                    />
                                    {!noPres && !exhausted && (
                                        <div style={{ fontSize: "10px", textAlign: "right", marginTop: "2px", color: over ? "var(--c-danger-text)" : "var(--c-text-4)" }}>
                                            máx {max}
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
    const { token, initializing, can } = useAuth();
    const confirm = useConfirm();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const [loading, setLoading] = useState(true);
    const requestIdRef = useRef(0);

    const [invoices, setInvoices] = useState([]);

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

    // Caja (ADR p28): turno actual + si la org exige caja abierta para cobrar.
    const [cashSession, setCashSession] = useState(undefined); // undefined=cargando | null=cerrada | obj=abierta
    const [requireCash, setRequireCash] = useState(false);

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

    // Caja: la sesión llega vía CajaBar (onSession) — sin GET duplicado.
    // Aquí solo se carga el flag de la org. Silencioso: si falla, no bloquea.
    const loadCashSettings = async () => {
        const settings = await getOrgSettings().catch(() => null);
        setRequireCash(!!settings?.require_open_cash_session);
    };

    const loadAll = async () => {
        setLoading(requestIdRef.current === 0);
        try {
            await loadInvoices(filters);
            loadCashSettings();
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
        if (invoiceParam && token && !loading) {
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
            const filename = extractFilename(contentDisposition, "cobro.pdf");
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
        const paymentLines = buildPaymentLines(
            payLines, direct ? selectedInvoice.total : selectedInvoice.remaining_balance
        );
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

    const hasActiveFilters = FILTER_KEYS.some(k => filters[k]);

    return (
        <div className={s.billingContainer}>
            <div className="page-header">
                <h1 className="page-title">Cobros</h1>
                {/* Chip de caja (Fase 3): estado + abrir/cerrar sin fila completa.
                    onSession alimenta cashBlocked — único GET de sesión de la página. */}
                <CajaBar variant="compact" onSession={setCashSession} />
            </div>

            {cashBlocked && (
                <div className="form-alert form-alert-warning" style={{ alignItems: "center" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <Icon.AlertTriangle s={16} />
                        <span><strong>No hay una caja abierta.</strong> Debes abrir una caja para registrar pagos — usa "Abrir caja" aquí arriba.</span>
                    </span>
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
                                        <button className={s.actionBtn} onClick={() => openInvoiceDetail(inv)}><Icon.Eye s={14} /></button>
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
                                <div><p className={s.infoLabel}>Mascota</p><p className={s.infoValue}>{selectedInvoice.pet_name}</p></div>
                                <div><p className={s.infoLabel}>Cliente</p><p className={s.infoValue}>{selectedInvoice.owner_name}</p></div>
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

        </div>
    );
};

export default Billing;
