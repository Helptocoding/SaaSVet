import { Fragment } from "react";
import { Icon } from "../icons";
import s from "./pos.module.css";

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
                    <th style={{ width: "100px", textAlign: "right" }}>P. unit</th>
                    <th style={{ width: "110px", textAlign: "right" }}>Subtotal</th>
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
                            <td style={{ textAlign: "right" }}>${item.unitPrice.toFixed(2)}</td>
                            <td style={{ textAlign: "right", fontWeight: 600 }}>
                                ${((Number(item.quantity) || 0) * item.unitPrice).toFixed(2)}
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
