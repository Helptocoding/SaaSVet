import { useState } from "react";
import { apiError } from "../../utils/apiError";
import { dispensePrescription, decidePrescriptionItem } from "../../api/billing";
import { Icon } from "../icons";
import { toast } from "sonner";
import { newIdempotencyKey } from "../../utils/idempotency";
import { authoritativePresentationMax } from "../../utils/prescriptionAvailability";
import DispenseLotSelect from "./DispenseLotSelect";
import s from "../../pages/billing.module.css";

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
                                        <div style={{ fontSize: "11px", textAlign: "right", marginTop: "2px", color: over ? "var(--c-danger-text)" : "var(--c-text-4)" }}>
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

export default PrescriptionDispensePanel;
