import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

// Carrito del POS (venta directa). Solo estado de UI: stock real, totales con
// IVA y tope de receta los valida el backend al cobrar. El guard de stock aquí
// es pre-check visual (mismo criterio que el flujo legacy de venta directa).
const itemKey = (type, id) => `${type}-${id}`;

export default function usePOSCart() {
    const [items, setItemsState] = useState([]);
    // Espejo en ref: los handlers del scanner pueden disparar varias veces
    // antes del re-render; leer el ref evita closures stale sin meter side
    // effects (toasts) dentro de un updater funcional.
    const itemsRef = useRef(items);
    const setItems = useCallback((next) => {
        itemsRef.current = next;
        setItemsState(next);
    }, []);

    const addProduct = useCallback((pres, qty = 1) => {
        const prev = itemsRef.current;
        const key = itemKey("product", pres.id);
        const existing = prev.find(i => i.key === key);
        const nextQty = (Number(existing?.quantity) || 0) + qty;
        if (Number(pres.stock) < nextQty) {
            toast.error(`Stock insuficiente de ${pres.product_name} (${pres.stock} disponible).`);
            return false;
        }
        if (existing) {
            setItems(prev.map(i => i.key === key ? { ...i, quantity: String(nextQty) } : i));
        } else {
            setItems([...prev, {
                key,
                type: "product",
                id: pres.id,
                name: `${pres.product_name} — ${pres.name}`,
                quantity: String(qty),
                unitPrice: Number(pres.sale_price),
                stock: Number(pres.stock),
                requiresRx: !!pres.requires_prescription,
                rxAttested: false,
                prescriberName: "",
                prescriptionFolio: "",
            }]);
        }
        return true;
    }, [setItems]);

    const addService = useCallback((svc, qty = 1) => {
        const prev = itemsRef.current;
        const key = itemKey("service", svc.id);
        const existing = prev.find(i => i.key === key);
        if (existing) {
            setItems(prev.map(i => i.key === key
                ? { ...i, quantity: String((Number(i.quantity) || 0) + qty) }
                : i
            ));
        } else {
            setItems([...prev, {
                key,
                type: "service",
                id: svc.id,
                name: svc.name,
                quantity: String(qty),
                unitPrice: Number(svc.base_price),
                requiresRx: false,
            }]);
        }
        return true;
    }, [setItems]);

    // Mantiene el string del input (permite "" mientras se edita); clampa al
    // stock visible para productos. La cantidad final se normaliza al cobrar.
    const updateQuantity = useCallback((key, value) => {
        const prev = itemsRef.current;
        const item = prev.find(i => i.key === key);
        if (!item) return;
        let next = value;
        const parsed = parseInt(value, 10);
        if (item.type === "product" && Number.isFinite(parsed) && parsed > item.stock) {
            toast.error(`Stock insuficiente (${item.stock} disponible).`);
            next = String(item.stock);
        }
        setItems(prev.map(i => i.key === key ? { ...i, quantity: next } : i));
    }, [setItems]);

    const updateRx = useCallback((key, patch) => {
        setItems(itemsRef.current.map(i => i.key === key ? { ...i, ...patch } : i));
    }, [setItems]);

    const removeItem = useCallback((key) => {
        setItems(itemsRef.current.filter(i => i.key !== key));
    }, [setItems]);

    const clear = useCallback(() => setItems([]), [setItems]);

    const subtotal = items.reduce(
        (sum, i) => sum + (Number(i.quantity) || 0) * i.unitPrice, 0
    );

    return { items, addProduct, addService, updateQuantity, updateRx, removeItem, clear, subtotal };
}
