import { formatMoney } from "../utils/money";
import styles from "./PriceLabel.module.css";

/**
 * Precio para el personal (ADR p70 D4): el precio capturado se rotula «sin IVA»
 * y, si el backend entregó el precio con IVA, se muestra al lado.
 *
 * Presentacional: no calcula impuestos. `withTax` llega del backend
 * (`price_with_tax` / `sale_price_with_tax`); si falta, solo se ve el base.
 */
export default function PriceLabel({ base, withTax = null, className = "" }) {
    const hasTax = withTax !== null && withTax !== undefined && withTax !== "";
    return (
        <span className={`${styles.price} ${className}`}>
            <span className={styles.base}>{formatMoney(base)}</span>
            <span className={styles.note}>sin IVA</span>
            {hasTax && (
                <>
                    <span className={styles.sep} aria-hidden="true">·</span>
                    <span className={styles.withTax}>{formatMoney(withTax)}</span>
                    <span className={styles.note}>con IVA</span>
                </>
            )}
        </span>
    );
}
