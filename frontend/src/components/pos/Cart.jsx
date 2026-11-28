import { Fragment, useEffect, useState } from "react";
import { Icon } from "../icons";
import { getProductLots } from "../../api/inventory";
import { formatMoney } from "../../utils/money";
import s from "./pos.module.css";

/* Selector de lote (FEFO) para un ítem de producto con tracks_lots.
   Carga los lotes elegibles del producto y auto-selecciona el primero (FEFO). */
const LotSelect = ({ item, updateRx, disabled }) => {
    const [lots, setLots] = useState([]);
    useEffect(() => {
        if (!item.productPublicId) return undefined;
        let active = true;
        (async () => {
            try {
                const data = await getProductLots(item.productPublicId, { with_stock: "true" });
                const list = (Array.isArray(data) ? data : data?.results || [])
                    .filter(l => l.effective_status === "active");
                if (!active) return;
                setLots(list);
                if (!item.lot) updateRx(item.key, { lot: list[0] || null });
            } catch {
                /* noop */
            }
        })();
        return () => { active = false; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [item.productPublicId]);

    return (
        <select
            className="input"
            style={{ flex: 1, maxWidth: 340 }}
            value={item.lot?.id ?? ""}
            disabled={disabled}
            onChange={e => updateRx(item.key, { lot: lots.find(l => String(l.id) === e.target.value) || null })}
        >
            {lots.length === 0 && <option value="">Sin lotes disponibles</option>}
            {lots.map(l => (
                <option key={l.id} value={l.id}>
                    {l.lot_number}{l.expiry_date ? ` · vence ${l.expiry_date}` : ""} · {Math.round(Number(l.quantity_on_hand))} disp.
                </option>
            ))}
        </select>
    );
};

/* ── Cart — tabla de la venta en curso ──
   Cantidad editable inline; productos Rx despliegan la atestación de receta
   externa (ADR p26: el backend exige rx_attested + prescriber_name en
   direct_sale). Solo estado de UI — totales e impuestos los calcula el
   backend al cobrar. */
const Cart = ({ items, updateQuantity, updateRx, removeItem, disabled }) => (
    <div className="table-wrap">
        <table className="table">
            <thead>
                <tr>
                    <th>Concepto</th>
                    <th style={{ width: "80px", textAlign: "center" }}>Cant.</th>
                    <th style={{ width: "100px", textAlign: "right" }}>P. unit sin IVA</th>
                    <th style={{ width: "110px", textAlign: "right" }}>Subtotal sin IVA</th>
                    <th style={{ width: "44px" }}></th>
                </tr>
            </thead>
            <tbody>
                {items.length === 0 ? (
                    <tr>
                        <td colSpan="5" style={{ textAlign: "center", padding: "32px", color: "var(--c-text-3)" }}>
                            Escanea o busca un producto para comenzar.
                        </td>
                    </tr>
                ) : items.map(item => (
                    <Fragment key={item.key}>
                        <tr>
                            <td style={{ fontWeight: 500 }}>
                                {item.type === "service" && <Icon.Stethoscope s={12} c="var(--c-text-3)" />}{" "}
                                {item.name}
                                {item.requiresRx && (
                                    <span className="badge badge-warning" style={{ marginLeft: "6px" }}>Rx</span>
                                )}
                            </td>
                            <td style={{ textAlign: "center" }}>
                                <input
                                    type="number"
                                    className={`input ${s.qtyInput}`}
                                    min="1"
                                    step="1"
                                    value={item.quantity}
                                    disabled={disabled}
                                    onChange={e => updateQuantity(item.key, e.target.value)}
                                />
                            </td>
                            <td style={{ textAlign: "right" }}>{formatMoney(item.unitPrice)}</td>
                            <td style={{ textAlign: "right", fontWeight: 600 }}>
                                {formatMoney((Number(item.quantity) || 0) * item.unitPrice)}
                            </td>
                            <td style={{ textAlign: "right" }}>
                                <button
                                    className="btn btn-ghost btn-xs"
                                    onClick={() => removeItem(item.key)}
                                    disabled={disabled}
                                >
                                    <Icon.Trash s={13} />
                                </button>
                            </td>
                        </tr>
                        {item.type === "product" && item.tracksLots && (
                            <tr>
                                <td colSpan="5" className={s.rxCell}>
                                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                        <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--c-text-3)", whiteSpace: "nowrap" }}>
                                            Lote (FEFO)
                                        </span>
                                        <LotSelect item={item} updateRx={updateRx} disabled={disabled} />
                                    </div>
                                </td>
                            </tr>
                        )}
                        {item.requiresRx && (
                            <tr>
                                <td colSpan="5" className={s.rxCell}>
                                    <label className={s.rxLabel}>
                                        <input
                                            type="checkbox"
                                            checked={item.rxAttested}
                                            disabled={disabled}
                                            onChange={e => updateRx(item.key, { rxAttested: e.target.checked })}
                                        />
                                        El cliente presentó receta médica válida
                                    </label>
                                    {item.rxAttested && (
                                        <div className={s.rxFields}>
                                            <input
                                                type="text" className="input" style={{ flex: 2 }}
                                                placeholder="Médico que emitió la receta"
                                                value={item.prescriberName}
                                                disabled={disabled}
                                                onChange={e => updateRx(item.key, { prescriberName: e.target.value })}
                                            />
                                            <input
                                                type="text" className="input" style={{ flex: 1 }}
                                                placeholder="Folio (opcional)"
                                                value={item.prescriptionFolio}
                                                disabled={disabled}
                                                onChange={e => updateRx(item.key, { prescriptionFolio: e.target.value })}
                                            />
                                        </div>
                                    )}
                                </td>
                            </tr>
                        )}
                    </Fragment>
                ))}
            </tbody>
        </table>
    </div>
);

export default Cart;
