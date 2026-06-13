import { useNavigate } from "react-router-dom";

// Backend envía stock/min_stock como string decimal (e.g. "2.0000"). Mostrar
// limpio: "2", "2.5". El stock es product-level en unidades base (ADR p31).
const fmtQty = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  return n.toLocaleString("es-MX", { maximumFractionDigits: 2 });
};

function StockRow({ alert, isCritical }) {
  return (
    <li className={`dsp-item${isCritical ? " dsp-item-critical" : ""}`}>
      <span className={`dsp-sev ${isCritical ? "dsp-sev-critical" : "dsp-sev-warning"}`} />
      <div className="dsp-item-body">
        <span className="dsp-item-name">{alert.product_name}</span>
        <span className="dsp-item-meta">
          {fmtQty(alert.stock)} {alert.unit || "u"} · mín {fmtQty(alert.min_stock)}
        </span>
      </div>
      <span className={`badge ${isCritical ? "badge-danger" : "badge-warning"}`}>
        {isCritical ? "Agotado" : "Bajo"}
      </span>
    </li>
  );
}

export default function StockAlerts({ alerts }) {
  const navigate = useNavigate();

  if (!alerts || alerts.length === 0) {
    return (
      <div className="dsp">
        <div className="dsp-head">
          <h3 className="dsp-title">Stock crítico</h3>
        </div>
        <p className="dsp-empty">Sin alertas de stock.</p>
      </div>
    );
  }

  const critical = alerts.filter((a) => a.severity === "critical");
  const warning  = alerts.filter((a) => a.severity !== "critical");

  return (
    <div className="dsp">
      <div className="dsp-head">
        <h3 className="dsp-title">Stock crítico</h3>
        {critical.length > 0 && (
          <span className="badge badge-danger">{critical.length}</span>
        )}
      </div>

      <ul className="dsp-list">
        {critical.slice(0, 3).map((a, i) => (
          <StockRow key={`c-${i}`} alert={a} isCritical />
        ))}
        {warning.slice(0, 2).map((a, i) => (
          <StockRow key={`w-${i}`} alert={a} isCritical={false} />
        ))}
      </ul>

      {alerts.length > 5 && (
        <p className="dsp-overflow">+{alerts.length - 5} más</p>
      )}

      <button className="btn btn-ghost btn-xs dsp-action" onClick={() => navigate("/inventory")}>
        Ver inventario →
      </button>
    </div>
  );
}
