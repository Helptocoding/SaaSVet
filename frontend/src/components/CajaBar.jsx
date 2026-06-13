import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Icon } from "./icons";
import { apiError } from "../utils/apiError";
import { useAuth } from "../auth/authContext";
import { getCurrentSession, openSession, closeSession, registerCashMovement } from "../api/cash";

const money = (v) => `$${Number(v || 0).toFixed(2)}`;

// ADR p39: movimientos manuales del cajón. El signo lo da el tipo.
const MOVEMENT_TYPES = [
    { value: "deposit", label: "(+) Entrada", hint: "Efectivo que entra al cajón (ej. fondo extra)" },
    { value: "withdrawal", label: "(−) Retiro", hint: "Efectivo que sale (ej. depósito a banco)" },
    { value: "expense", label: "(−) Gasto", hint: "Pago en efectivo desde el cajón" },
];

/**
 * Banner operativo de caja (ADR p28). Estado del turno + abrir/cerrar rápido +
 * acceso a /cash.
 *
 * `variant`:
 *  - "full" (default): fila completa — header de /cash.
 *  - "compact": chip de estado + acción — vive en el page-header de /billing
 *    (Fase 3 Cobros: la fila completa duplicaba la alerta de caja requerida).
 *
 * `onChange` se invoca tras abrir/cerrar para que el padre refresque (ej. lista
 * de sesiones en /cash). `onSession(session|null)` notifica cada cambio de
 * sesión conocido (carga inicial incluida) — permite al padre consumir el
 * estado sin duplicar el GET de sesión actual. `showManageLink` muestra el
 * enlace a /cash.
 */
export default function CajaBar({ onChange, onSession, showManageLink = true, variant = "full" }) {
    const { can } = useAuth();
    const [session, setSession] = useState(undefined); // undefined=loading | null=cerrada | obj=abierta
    const [showOpen, setShowOpen] = useState(false);
    const [showClose, setShowClose] = useState(false);
    const [showMove, setShowMove] = useState(false);
    const [openingFloat, setOpeningFloat] = useState("0.00");
    const [countedCash, setCountedCash] = useState("");
    const [movement, setMovement] = useState({ type: "withdrawal", amount: "", reason: "" });
    const [busy, setBusy] = useState(false);

    const applySession = (value) => {
        setSession(value);
        if (value !== undefined) onSession?.(value);
    };

    const load = async () => {
        try {
            const data = await getCurrentSession();
            applySession(data && data.public_id ? data : null);
        } catch {
            applySession(null);
        }
    };
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount idiomático
    useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- solo al montar

    const canOpen = can("cashsession.open");
    const canClose = can("cashsession.close");
    const canMove = can("cashmovement.create");

    const doOpen = async () => {
        if (Number(openingFloat) < 0) { toast.error("El fondo no puede ser negativo."); return; }
        setBusy(true);
        try {
            const s = await openSession({ openingFloat });
            applySession(s);
            setShowOpen(false);
            setOpeningFloat("0.00");
            toast.success("Caja abierta");
            onChange?.();
        } catch (err) {
            toast.error(apiError(err, "No se pudo abrir la caja"));
        } finally { setBusy(false); }
    };

    const doClose = async () => {
        if (countedCash === "" || Number(countedCash) < 0) { toast.error("Ingresa el efectivo contado."); return; }
        setBusy(true);
        try {
            const s = await closeSession(session.public_id, { countedCash });
            setShowClose(false);
            setCountedCash("");
            applySession(null);
            const diff = Number(s.difference);
            if (diff === 0) toast.success("Caja cerrada — cuadrada");
            else toast.warning(`Caja cerrada — diferencia ${money(diff)} (esperado ${money(s.expected_cash)}, contado ${money(s.counted_cash)})`);
            onChange?.();
        } catch (err) {
            toast.error(apiError(err, "No se pudo cerrar la caja"));
        } finally { setBusy(false); }
    };

    const doMovement = async () => {
        if (!(Number(movement.amount) > 0)) { toast.error("Ingresa un monto mayor a 0."); return; }
        if (!movement.reason.trim()) { toast.error("Indica el motivo del movimiento."); return; }
        setBusy(true);
        try {
            await registerCashMovement({
                movementType: movement.type,
                amount: movement.amount,
                reason: movement.reason.trim(),
            });
            setShowMove(false);
            setMovement({ type: "withdrawal", amount: "", reason: "" });
            toast.success("Movimiento registrado — el corte Z lo incluye en el esperado");
            onChange?.();
        } catch (err) {
            toast.error(apiError(err, "No se pudo registrar el movimiento"));
        } finally { setBusy(false); }
    };

    if (session === undefined) return null; // loading silencioso

    const open = !!session;
    const compact = variant === "compact";

    return (
        <div style={compact
            ? { display: "inline-flex", alignItems: "center", gap: "8px" }
            : {
                display: "flex", alignItems: "center", gap: "12px",
                padding: "8px 14px", borderRadius: "8px", marginBottom: "12px",
                border: "1px solid var(--c-border)",
                background: open ? "var(--c-success-bg, rgba(16,185,129,0.06))" : "var(--c-subtle, rgba(0,0,0,0.03))",
            }}>
            {compact ? (
                <span
                    className={`badge ${open ? "badge-success" : "badge-default"}`}
                    title={open ? `Fondo ${money(session.opening_float)}${session.opened_by_name ? ` · ${session.opened_by_name}` : ""}` : "No hay turno de caja abierto"}
                >
                    ● Caja {open ? "abierta" : "cerrada"}
                </span>
            ) : (
                <>
                    <Icon.Wallet s={16} c={open ? "var(--c-success-text)" : "var(--c-text-3)"} />
                    <div style={{ flex: 1, fontSize: "13px" }}>
                        {open ? (
                            <span style={{ color: "var(--c-text)" }}>
                                <strong>Caja abierta</strong>
                                <span style={{ color: "var(--c-text-3)" }}> · fondo {money(session.opening_float)}{session.opened_by_name ? ` · ${session.opened_by_name}` : ""}</span>
                            </span>
                        ) : (
                            <span style={{ color: "var(--c-text-3)" }}>Caja cerrada</span>
                        )}
                    </div>
                </>
            )}

            {open && canMove && (
                <button className={`btn btn-secondary ${compact ? "btn-xs" : "btn-sm"}`} onClick={() => setShowMove(true)}>
                    Movimiento
                </button>
            )}
            {open && canClose && (
                <button className={`btn ${compact ? "btn-xs" : "btn-sm"}`} style={{ background: "var(--c-danger-text)", color: "#fff", borderColor: "var(--c-danger-text)" }} onClick={() => setShowClose(true)}>
                    {compact ? "Cerrar (Z)" : "Cerrar caja (Z)"}
                </button>
            )}
            {!open && canOpen && (
                <button className={`btn btn-primary ${compact ? "btn-xs" : "btn-sm"}`} onClick={() => setShowOpen(true)}>
                    Abrir caja
                </button>
            )}
            {showManageLink && (
                <Link to="/cash" className="btn btn-ghost btn-xs" style={{ textDecoration: "none" }}>
                    Administrar
                </Link>
            )}

            {/* Modal abrir */}
            {showOpen && (
                <div className="modal-overlay" onClick={() => !busy && setShowOpen(false)}>
                    <div className="modal" style={{ maxWidth: "340px" }} onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3 style={{ fontSize: "15px", fontWeight: 600, color: "var(--c-text)" }}>Abrir caja</h3>
                            <button className="modal-close" onClick={() => setShowOpen(false)} disabled={busy}><Icon.X s={14} /></button>
                        </div>
                        <div className="modal-body">
                            <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", marginBottom: "6px" }}>
                                Fondo de apertura (efectivo inicial)
                            </label>
                            <input type="number" className="input" min="0" step="0.01" autoFocus
                                value={openingFloat} onChange={e => setOpeningFloat(e.target.value)} disabled={busy} />
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary btn-sm" onClick={() => setShowOpen(false)} disabled={busy}>Cancelar</button>
                            <button className="btn btn-primary btn-sm" onClick={doOpen} disabled={busy}>
                                {busy ? <Icon.Loader s={14} /> : "Abrir"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Modal movimiento manual (ADR p39) */}
            {showMove && session && (
                <div className="modal-overlay" onClick={() => !busy && setShowMove(false)}>
                    <div className="modal" style={{ maxWidth: "360px" }} onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3 style={{ fontSize: "15px", fontWeight: 600, color: "var(--c-text)" }}>Movimiento de caja</h3>
                            <button className="modal-close" onClick={() => setShowMove(false)} disabled={busy}><Icon.X s={14} /></button>
                        </div>
                        <div className="modal-body">
                            <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", marginBottom: "6px" }}>
                                Tipo
                            </label>
                            <div style={{ display: "flex", gap: "6px", marginBottom: "4px" }}>
                                {MOVEMENT_TYPES.map(t => (
                                    <button
                                        key={t.value}
                                        className={`btn ${movement.type === t.value ? "btn-primary" : "btn-secondary"} btn-xs`}
                                        onClick={() => setMovement(prev => ({ ...prev, type: t.value }))}
                                        disabled={busy}
                                    >
                                        {t.label}
                                    </button>
                                ))}
                            </div>
                            <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginBottom: "10px" }}>
                                {MOVEMENT_TYPES.find(t => t.value === movement.type)?.hint}
                            </p>
                            <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", marginBottom: "6px" }}>
                                Monto
                            </label>
                            <input type="number" className="input" min="0.01" step="0.01" autoFocus placeholder="0.00"
                                value={movement.amount} disabled={busy}
                                onChange={e => setMovement(prev => ({ ...prev, amount: e.target.value }))} />
                            <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", margin: "10px 0 6px" }}>
                                Motivo
                            </label>
                            <input type="text" className="input" placeholder="Ej. Depósito a banco"
                                value={movement.reason} disabled={busy} maxLength={255}
                                onChange={e => setMovement(prev => ({ ...prev, reason: e.target.value }))} />
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary btn-sm" onClick={() => setShowMove(false)} disabled={busy}>Cancelar</button>
                            <button className="btn btn-primary btn-sm" onClick={doMovement} disabled={busy}>
                                {busy ? <Icon.Loader s={14} /> : "Registrar"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Modal cerrar */}
            {showClose && session && (
                <div className="modal-overlay" onClick={() => !busy && setShowClose(false)}>
                    <div className="modal" style={{ maxWidth: "360px" }} onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3 style={{ fontSize: "15px", fontWeight: 600, color: "var(--c-text)" }}>Cerrar caja — corte Z</h3>
                            <button className="modal-close" onClick={() => setShowClose(false)} disabled={busy}><Icon.X s={14} /></button>
                        </div>
                        <div className="modal-body">
                            <p style={{ fontSize: "12px", color: "var(--c-text-3)", marginBottom: "10px" }}>
                                Cuenta el efectivo en el cajón. El sistema calcula el esperado y la diferencia.
                            </p>
                            <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--c-text-3)", display: "block", marginBottom: "6px" }}>
                                Efectivo contado
                            </label>
                            <input type="number" className="input" min="0" step="0.01" autoFocus
                                value={countedCash} onChange={e => setCountedCash(e.target.value)} disabled={busy} placeholder="0.00" />
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary btn-sm" onClick={() => setShowClose(false)} disabled={busy}>Cancelar</button>
                            <button className="btn btn-sm" style={{ background: "var(--c-danger-text)", color: "#fff", borderColor: "var(--c-danger-text)" }} onClick={doClose} disabled={busy}>
                                {busy ? <Icon.Loader s={14} /> : "Cerrar y cortar"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
