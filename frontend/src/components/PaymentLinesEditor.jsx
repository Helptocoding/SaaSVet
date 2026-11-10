import { Icon } from "./icons";
import { PAYMENT_METHODS, paymentSummary } from "../utils/payments";

/* ── PaymentLinesEditor — pago único o split, total exacto (ADR p30 rev) ──
   Componente compartido: modal Registrar Pago (Cobros), devoluciones y POS.
   No duplicar editores de pago por módulo. */
const PaymentLinesEditor = ({ total, allowPartial, allowChange = false, lines, setLines, disabled }) => {
    const { sum, remaining, change } = paymentSummary(lines, total);
    const setLine = (i, patch) => setLines(prev => prev.map((l, idx) => idx === i ? { ...l, ...patch } : l));
    const addLine = () => setLines(prev => [...prev, { method: "card", amount: remaining > 0 ? remaining.toFixed(2) : "" }]);
    const removeLine = (i) => setLines(prev => prev.filter((_, idx) => idx !== i));
    return (
        <div>
            {lines.map((l, i) => (
                <div key={i} style={{ display: "flex", gap: "6px", marginBottom: "6px", alignItems: "center" }}>
                    <select
                        className="input" style={{ flex: 1, height: "34px" }}
                        aria-label={`Método de pago ${i + 1}`}
                        value={l.method} disabled={disabled}
                        onChange={e => setLine(i, { method: e.target.value })}
                    >
                        {PAYMENT_METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                    <input
                        type="number" className="input"
                        style={{ width: "110px", height: "34px", textAlign: "right" }}
                        aria-label={`Monto del método ${i + 1}`}
                        min="0" step="0.01" placeholder="0.00" value={l.amount} disabled={disabled}
                        onChange={e => setLine(i, { amount: e.target.value })}
                    />
                    <button
                        className="btn btn-ghost btn-xs" onClick={() => removeLine(i)}
                        aria-label={`Quitar método ${i + 1}`}
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
            {allowPartial && remaining > 0 && sum > 0 && (
                <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>
                    Pago parcial: la factura quedará confirmada con saldo pendiente.
                </p>
            )}
            {allowChange && remaining < 0 && (
                <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>
                    Se cobra el total ${Number(total).toFixed(2)}; el cambio ${change.toFixed(2)} no se registra.
                </p>
            )}
        </div>
    );
};

export default PaymentLinesEditor;
