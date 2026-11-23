import { useCallback, useEffect, useState } from "react";
import { Icon } from "../components/icons";
import CajaBar from "../components/CajaBar";
import { useAuth } from "../auth/authContext";
import { listSessions } from "../api/cash";
import Skeleton from "react-loading-skeleton";
import TableSkeleton from "../components/TableSkeleton";

const money = (v) => (v == null || v === "") ? "—" : `$${Number(v).toFixed(2)}`;
const fmtDate = (d) => d ? new Date(d).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" }) : "—";
const STATUS_LABELS = { open: "Abierta", closed: "Cerrada", force_closed: "Cierre admin" };
const STATUS_COLOR = {
    open: "var(--c-success-text)",
    closed: "var(--c-text-3)",
    force_closed: "var(--c-danger-text)",
};

const diffColor = (d) => {
    const n = Number(d);
    if (Number.isNaN(n) || n === 0) return "var(--c-text)";
    return n < 0 ? "var(--c-danger-text)" : "var(--c-info-text)";
};

const Cash = () => {
    const { initializing } = useAuth();
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [detail, setDetail] = useState(null);

    const load = useCallback(async () => {
        try {
            const data = await listSessions();
            setSessions(Array.isArray(data) ? data : data?.results || []);
        } catch {
            // silencioso — el usuario ve lista vacía
        } finally {
            setLoading(false);
        }
    }, []);

    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount idiomático
    useEffect(() => { load(); }, [load]);

    return (
        // Mismo contenedor, título y tabla que las demás páginas (plan UX F2.6/F2.8).
        <div>
            <div className="page-header">
                <h1 className="page-title">Caja</h1>
            </div>

            <CajaBar onChange={load} showManageLink={false} />

            <p style={{ fontSize: "11px", fontWeight: 600, color: "var(--c-text-3)", margin: "20px 0 8px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Historial de turnos
            </p>

            {(initializing || loading) ? (
                <CashHistorySkeleton />
            ) : sessions.length === 0 ? (
                <div className="empty-state"><p className="empty-state-title">No hay turnos registrados</p></div>
            ) : (
                <div className="table-wrap">
                <table className="table">
                    <thead>
                        <tr>
                            <th>Apertura</th>
                            <th>Abrió</th>
                            <th>Estado</th>
                            <th style={{ textAlign: "right" }}>Esperado</th>
                            <th style={{ textAlign: "right" }}>Contado</th>
                            <th style={{ textAlign: "right" }}>Diferencia</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {sessions.map(s => (
                            <tr key={s.public_id}>
                                <td style={{ color: "var(--c-text-3)" }}>{fmtDate(s.opened_at)}</td>
                                <td>{s.opened_by_name || "—"}</td>
                                <td>
                                    <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                                        <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: STATUS_COLOR[s.status] }} />
                                        {STATUS_LABELS[s.status] || s.status}
                                    </span>
                                </td>
                                <td style={{ textAlign: "right" }}>{money(s.expected_cash)}</td>
                                <td style={{ textAlign: "right" }}>{money(s.counted_cash)}</td>
                                <td style={{ textAlign: "right", color: diffColor(s.difference), fontWeight: 500 }}>{money(s.difference)}</td>
                                <td style={{ textAlign: "right" }}>
                                    <button className="btn btn-ghost btn-xs" onClick={() => setDetail(s)} disabled={s.status === "open"}>
                                        Ver corte
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </div>
            )}

            {/* Detalle Z (snapshot congelado) */}
            {detail && (
                <div className="modal-overlay" onClick={() => setDetail(null)}>
                    <div className="modal" style={{ maxWidth: "420px" }} onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3 style={{ fontSize: "16px", fontWeight: 600, color: "var(--c-text)" }}>Corte de caja</h3>
                            <button className="modal-close" onClick={() => setDetail(null)}><Icon.X s={14} /></button>
                        </div>
                        <div className="modal-body">
                            <ZReport session={detail} />
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary btn-sm" onClick={() => setDetail(null)}>Cerrar</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

// Historial de turnos cargando: mismas columnas que la tabla real.
const CASH_SKELETON_COLUMNS = [
    { label: "Apertura", width: 130 },
    { label: "Abrió", width: 90 },
    { label: "Estado", width: 70 },
    { label: "Esperado", width: 64, align: "right" },
    { label: "Contado", width: 64, align: "right" },
    { label: "Diferencia", width: 56, align: "right" },
    { label: "", align: "right", cell: () => <Skeleton width={62} height={22} borderRadius="var(--r-md)" /> },
];

const CashHistorySkeleton = () => (
    <div role="status" aria-label="Cargando historial de turnos">
        <TableSkeleton
            rows={5}
            columns={CASH_SKELETON_COLUMNS}
        />
    </div>
);

const Row = ({ label, value, strong, color }) => (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
        <span style={{ color: "var(--c-text-3)" }}>{label}</span>
        <span style={{ color: color || "var(--c-text)", fontWeight: strong ? 600 : 400 }}>{value}</span>
    </div>
);

const ZReport = ({ session }) => {
    const snap = session.closed_snapshot || {};
    const byMethod = snap.totals_by_method || {};
    const METHOD_LABELS = { cash: "Efectivo", card: "Tarjeta", transfer: "Transferencia", other: "Otro" };
    return (
        <div>
            <Row label="Apertura" value={fmtDate(session.opened_at)} />
            <Row label="Cierre" value={fmtDate(session.closed_at)} />
            <Row label="Cerró" value={session.closed_by_name || "—"} />
            <div style={{ height: "1px", background: "var(--c-subtle)", margin: "8px 0" }} />
            <Row label="Fondo de apertura" value={money(session.opening_float)} />
            {Object.keys(byMethod).length > 0 && (
                <>
                    <p style={{ fontSize: "11px", color: "var(--c-text-3)", margin: "8px 0 2px", textTransform: "uppercase" }}>Cobrado por método</p>
                    {Object.entries(byMethod).map(([m, v]) => (
                        <Row key={m} label={METHOD_LABELS[m] || m} value={money(v)} />
                    ))}
                </>
            )}
            {/* Movimientos manuales (snapshot v3, ADR p39) — Z's viejos no los traen */}
            {(Number(snap.manual_in) > 0 || Number(snap.manual_out) > 0) && (
                <>
                    <div style={{ height: "1px", background: "var(--c-subtle)", margin: "8px 0" }} />
                    {Number(snap.manual_in) > 0 && <Row label="Entradas manuales" value={`+${money(snap.manual_in)}`} />}
                    {Number(snap.manual_out) > 0 && <Row label="Salidas manuales (retiros/gastos)" value={`−${money(snap.manual_out)}`} />}
                </>
            )}
            <div style={{ height: "1px", background: "var(--c-subtle)", margin: "8px 0" }} />
            <Row label="Efectivo esperado" value={money(session.expected_cash)} strong />
            <Row label="Efectivo contado" value={money(session.counted_cash)} />
            <Row label="Diferencia" value={money(session.difference)} strong color={diffColor(session.difference)} />
            <Row label="Operaciones" value={snap.operations ?? "—"} />
        </div>
    );
};

export default Cash;
