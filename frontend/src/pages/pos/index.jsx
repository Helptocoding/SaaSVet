import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import { apiError } from "../../utils/apiError";
import { newIdempotencyKey } from "../../utils/idempotency";
import { buildPaymentLines } from "../../utils/payments";
import {
    abandonCheckout, addCheckoutItem, createDirectSaleCheckout,
    getCheckout, payCheckout,
} from "../../api/billing";
import { getOwners } from "../../api/pets";
import { getOrgSettings } from "../../api/organizations";
import { Icon } from "../../components/icons";
import CajaBar from "../../components/CajaBar";
import ProductSearch from "../../components/pos/ProductSearch";
import Cart from "../../components/pos/Cart";
import CustomerSelector from "../../components/pos/CustomerSelector";
import PaymentPanel from "../../components/pos/PaymentPanel";
import usePOSCart from "../../hooks/usePOSCart";
import s from "./pos.module.css";

const toList = (d) => (Array.isArray(d) ? d : d?.results || []);

/* ── POS — venta directa de mostrador ──
   Checkout en dos pasos, server-driven (sin matemática financiera en React):
   1. "Cobrar" persiste un Checkout (owner + items) y
      lee del backend subtotal/IVA/total exactos.
   2. El panel pasa a modo pago: PaymentLinesEditor (mismo flujo que Registrar
      Pago de Cobros) + post/pay atómico con X-Idempotency-Key.
   "Volver al carrito" abandona el Checkout sin emitir una Invoice. */
const POS = () => {
    const { initializing, can } = useAuth();
    const confirm = useConfirm();
    const navigate = useNavigate();
    const cart = usePOSCart();
    const searchRef = useRef(null);

    const [customer, setCustomer] = useState({ owner: null, pet: null });
    const [genericOwner, setGenericOwner] = useState(null);

    // mode "cart" → editando venta | "paying" → Checkout creado, capturando pago.
    const [mode, setMode] = useState("cart");
    const [invoice, setInvoice] = useState(null);
    const [payLines, setPayLines] = useState([{ method: "cash", amount: "" }]);
    const [idemKey, setIdemKey] = useState(null);
    const [processing, setProcessing] = useState(false);

    // Caja (ADR p28): sesión vía CajaBar (onSession) + flag de la org.
    const [cashSession, setCashSession] = useState(undefined);
    const [requireCash, setRequireCash] = useState(false);

    useEffect(() => {
        getOwners({ is_generic: "true" })
            .then(d => setGenericOwner(toList(d)[0] || null))
            .catch(() => {});
        getOrgSettings()
            .then(settings => setRequireCash(!!settings?.require_open_cash_session))
            .catch(() => {});
    }, []);

    // El Checkout POS es servidor-persistente: navegar o refrescar no lo
    // abandona. Puede reanudarse desde la bandeja de Cobros.

    const cashBlocked = requireCash && cashSession === null;
    const paying = mode === "paying";

    const validateCart = () => {
        if (cart.items.length === 0) {
            toast.error("Agrega al menos un ítem.");
            return false;
        }
        if (cart.items.some(i => !(parseInt(i.quantity, 10) >= 1))) {
            toast.error("Revisa las cantidades: deben ser de al menos 1.");
            return false;
        }
        const rxIncomplete = cart.items.find(i => i.requiresRx && (!i.rxAttested || !i.prescriberName.trim()));
        if (rxIncomplete) {
            toast.error(`${rxIncomplete.name} requiere receta: confirma que el cliente la presentó e indica el médico.`);
            return false;
        }
        const missingLot = cart.items.find(i => i.type === "product" && i.tracksLots && !i.lot?.id);
        if (missingLot) {
            toast.error(`${missingLot.name}: selecciona un lote disponible.`);
            return false;
        }
        if (!customer.owner && !genericOwner) {
            toast.error("No se encontró el cliente genérico. Verifica la configuración.");
            return false;
        }
        return true;
    };

    // Paso 1: crea el Checkout y pasa a modo pago con totales del backend.
    const handleRingUp = async () => {
        if (!validateCart()) return;
        setProcessing(true);
        let created = null;
        try {
            const ownerId = customer.owner ? customer.owner.public_id : genericOwner.public_id;
            const payload = { owner: ownerId };
            if (customer.pet) payload.pet = customer.pet.public_id;
            created = await createDirectSaleCheckout(payload);
            for (const item of cart.items) {
                let body;
                if (item.type === "product") {
                    body = { presentation: item.id, quantity: String(parseInt(item.quantity, 10)) };
                    if (item.tracksLots && item.lot?.id) {
                        body.lot = item.lot.id;
                    }
                    if (item.requiresRx) {
                        // ADR p26: atestación de receta externa.
                        body.rx_attested = true;
                        body.prescriber_name = item.prescriberName.trim();
                        body.prescription_folio = item.prescriptionFolio.trim();
                    }
                } else {
                    body = { service: item.id, quantity: String(parseInt(item.quantity, 10)) };
                }
                await addCheckoutItem(created.public_id, body);
            }
            const detail = await getCheckout(created.public_id);
            setInvoice(detail);
            setPayLines([{ method: "cash", amount: Number(detail.total) > 0 ? Number(detail.total).toFixed(2) : "" }]);
            setIdemKey(newIdempotencyKey());
            setMode("paying");
        } catch (err) {
            toast.error(apiError(err, "No se pudo preparar el cobro."));
            // No dejar una preparación POS a medias.
            if (created) {
                abandonCheckout(created.public_id, {
                    reason: "pos_prepare_error",
                    idempotencyKey: newIdempotencyKey(),
                }).catch(() => {});
            }
        } finally {
            setProcessing(false);
        }
    };

    const resetSale = () => {
        cart.clear();
        setCustomer({ owner: null, pet: null });
        setInvoice(null);
        setPayLines([{ method: "cash", amount: "" }]);
        setIdemKey(null);
        setMode("cart");
        searchRef.current?.focus();
    };

    // Paso 2: post/pay atómico (total exacto; el sobrepago en
    // efectivo es cambio para el cliente y NO se registra — se capea al total).
    const handleConfirmCharge = async () => {
        const paymentLines = buildPaymentLines(payLines, invoice.total);
        setProcessing(true);
        // sonner v2: toast.promise NO resuelve a la data — await la promesa real.
        const call = payCheckout(invoice.public_id, {
            paymentLines,
            expectedVersion: invoice.version,
            idempotencyKey: idemKey,
        });
        toast.promise(call, {
            loading: "Cobrando...",
            success: "Venta cobrada",
            error: (err) => apiError(err, "Error al procesar el cobro. Intenta de nuevo."),
        });
        try {
            await call;
            resetSale();
        } catch {
            // toast.promise ya mostró el error; el Checkout y la idemKey se
            // conservan para reintentar sin doble cobro.
        } finally {
            setProcessing(false);
        }
    };

    // Volver a editar descarta el Checkout persistido y conserva el carrito local.
    const handleBackToCart = async () => {
        setProcessing(true);
        try {
            await abandonCheckout(invoice.public_id, {
                reason: "pos_back_to_cart",
                expectedVersion: invoice.version,
                idempotencyKey: newIdempotencyKey(),
            });
            setInvoice(null);
            setMode("cart");
            searchRef.current?.focus();
        } catch (err) {
            toast.error(apiError(err, "No se pudo volver al carrito."));
        } finally {
            setProcessing(false);
        }
    };

    const handleClearCart = async () => {
        const ok = await confirm({
            message: "¿Descartar la venta en curso? Los ítems no se guardarán.",
            confirmText: "Descartar",
            dangerMode: true,
        });
        if (!ok) return;
        resetSale();
    };

    if (initializing) {
        return <div style={{ display: "flex", justifyContent: "center", padding: "100px", color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</div>;
    }

    if (!can("invoice.create")) {
        return (
            <div className="empty-state">
                <p className="empty-state-title">No tienes permiso para registrar cobros.</p>
            </div>
        );
    }

    return (
        <div>
            <div className="page-header">
                <h1 className="page-title">Punto de Venta</h1>
                <div style={{ display: "flex", alignItems: "center", gap: "12px", marginLeft: "auto" }}>
                    {/* Plan UX D7: la acción secundaria antes; «Abrir caja» (la que
                        desbloquea cobrar) queda al final, dentro de CajaBar. */}
                    <button className="btn btn-secondary btn-sm" onClick={() => navigate("/billing")}>
                        Ver cobros
                    </button>
                    <CajaBar variant="compact" onSession={setCashSession} />
                </div>
            </div>

            {cashBlocked && (
                <div className="form-alert form-alert-warning" style={{ alignItems: "center" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <Icon.AlertTriangle s={16} />
                        <span><strong>No hay una caja abierta.</strong> Debes abrir una caja para cobrar — usa "Abrir caja" aquí arriba.</span>
                    </span>
                </div>
            )}

            <div className={s.posGrid}>
                <div className={s.leftCol}>
                    <ProductSearch
                        ref={searchRef}
                        onAddProduct={cart.addProduct}
                        onAddService={cart.addService}
                        disabled={paying || processing}
                    />
                    <Cart
                        items={cart.items}
                        updateQuantity={cart.updateQuantity}
                        updateRx={cart.updateRx}
                        removeItem={cart.removeItem}
                        disabled={paying || processing}
                    />
                    {cart.items.length > 0 && (
                        <div className={s.cartFooter}>
                            <span>{cart.items.length} concepto{cart.items.length !== 1 ? "s" : ""}</span>
                            {!paying && (
                                <button className="btn btn-ghost btn-xs" onClick={handleClearCart} disabled={processing}>
                                    Descartar venta
                                </button>
                            )}
                        </div>
                    )}
                </div>

                <div className={s.rightCol}>
                    <div className="card">
                        <CustomerSelector
                            customer={customer}
                            setCustomer={setCustomer}
                            disabled={paying || processing}
                        />
                    </div>
                    <PaymentPanel
                        mode={mode}
                        subtotal={cart.subtotal}
                        invoice={invoice}
                        lines={payLines}
                        setLines={setPayLines}
                        processing={processing}
                        cashBlocked={cashBlocked}
                        canRingUp={cart.items.length > 0 && (!!customer.owner || !!genericOwner)}
                        onRingUp={handleRingUp}
                        onConfirmCharge={handleConfirmCharge}
                        onBackToCart={handleBackToCart}
                    />
                </div>
            </div>
        </div>
    );
};

export default POS;
