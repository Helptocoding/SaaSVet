import { Icon } from "../icons";
import PaymentLinesEditor from "../PaymentLinesEditor";
import { paymentLinesValid } from "../../utils/payments";
import s from "./pos.module.css";

/* ── PaymentPanel — total + pago del POS ──
   Dos modos:
   - "cart": muestra el subtotal estimado (el IVA lo calcula el backend) y el
     CTA "Cobrar" que crea un Checkout abierto con sus líneas.
   - "paying": muestra los totales autoritativos del Checkout y
     reusa PaymentLinesEditor (mismo flujo que Registrar Pago de Cobros:
     split, total exacto, cambio en efectivo no persistido). La factura nace
     emitida y pagada dentro del post/pay atómico. */
const PaymentPanel = ({
    mode, subtotal, invoice, lines, setLines,
    processing, cashBlocked, canRingUp,
    onRingUp, onConfirmCharge, onBackToCart,
}) => {
    const fmt = (v) => Number(v || 0).toFixed(2);
    const paying = mode === "paying" && invoice;
    const payBlockers = invoice?.actions?.pay?.blockers || [];
    const payBlocked = invoice?.actions?.pay?.allowed === false;
    const payBlockedTitle = payBlockers.map(blocker => blocker.message).join(" ") || undefined;

    return (
        <div className="card">
            {paying ? (
                <>
                    <div className={s.totalBlock}>
                        <span className={s.totalLabel}>Total a cobrar</span>
                        <span className={s.totalAmount}>${fmt(invoice.total)}</span>
                    </div>
                    <div className={s.totalsBreakdown}>
                        <div className={s.breakdownRow}><span>Subtotal</span><span>${fmt(invoice.subtotal)}</span></div>
                        <div className={s.breakdownRow}><span>IVA</span><span>${fmt(invoice.tax_amount)}</span></div>
                    </div>
                    <PaymentLinesEditor
                        total={Number(invoice.total)}
                        allowPartial={false}
                        allowChange={true}
                        lines={lines}
                        setLines={setLines}
                        disabled={processing}
                    />
                    {payBlockers.length > 0 && (
                        <p role="status" style={{ color: "var(--c-danger-text)", fontSize: "12px", margin: "8px 0" }}>
                            {payBlockedTitle}
                        </p>
                    )}
                    <button
                        className={`btn btn-primary btn-lg ${s.chargeBtn}`}
                        style={{ background: "var(--c-success-text)", borderColor: "var(--c-success-text)", color: "#fff" }}
                        onClick={onConfirmCharge}
                        disabled={processing || cashBlocked || payBlocked || !paymentLinesValid(lines, Number(invoice.total), false, true)}
                        title={cashBlocked ? "Abre una caja para cobrar" : payBlockedTitle}
                    >
                        {processing ? <Icon.Loader s={16} /> : `Confirmar cobro $${fmt(invoice.total)}`}
                    </button>
                    <button
                        className="btn btn-ghost btn-sm"
                        style={{ width: "100%", marginTop: "8px" }}
                        onClick={onBackToCart}
                        disabled={processing}
                    >
                        ← Volver al carrito
                    </button>
                </>
            ) : (
                <>
                    <div className={s.totalBlock}>
                        <span className={s.totalLabel}>Total estimado</span>
                        <span className={s.totalAmount}>${fmt(subtotal)}</span>
                        <span className={s.totalHint}>El IVA se calcula al cobrar, según la configuración de la clínica.</span>
                    </div>
                    <button
                        className={`btn btn-primary btn-lg ${s.chargeBtn}`}
                        onClick={onRingUp}
                        disabled={!canRingUp || processing || cashBlocked}
                        title={cashBlocked ? "Abre una caja para cobrar" : undefined}
                    >
                        {processing ? <Icon.Loader s={16} /> : "Cobrar"}
                    </button>
                </>
            )}
        </div>
    );
};

export default PaymentPanel;
