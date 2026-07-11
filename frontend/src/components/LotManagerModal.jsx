import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Icon } from "./icons";
import { apiError } from "../utils/apiError";
import { useConfirm } from "./useConfirm";
import { getProductLots, discardLot, setLotStatus } from "../api/inventory";

/**
 * Gestión de lotes de un producto con tracks_lots (B2c): lista los lotes con su
 * estado efectivo (activo/vencido/consumido/cuarentena/retirado) y permite
 * descartar (merma) o cambiar el estado administrativo (cuarentena/retiro/reactivar).
 */
const STATUS_META = {
    active: { label: "Activo", cls: "badge-success" },
    expired: { label: "Vencido", cls: "badge-danger" },
    consumed: { label: "Agotado", cls: "badge-default" },
    quarantined: { label: "En cuarentena", cls: "badge-warning" },
    recalled: { label: "Retirado", cls: "badge-danger" },
};

const LotManagerModal = ({ product, onClose, onChanged }) => {
    const confirm = useConfirm();
    const [lots, setLots] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const data = await getProductLots(product.public_id);
            setLots(Array.isArray(data) ? data : data?.results || []);
        } catch (err) {
            toast.error(apiError(err, "No se pudieron cargar los lotes"));
        } finally {
            setLoading(false);
        }
    }, [product.public_id]);

    useEffect(() => { load(); }, [load]);

    const afterChange = async () => {
        await load();
        await onChanged?.();
    };

    const handleDiscard = async (lot) => {
        const ok = await confirm({
            message: `¿Descartar el saldo del lote ${lot.lot_number} (${Math.round(Number(lot.quantity_on_hand))} unidades)? Esto registra una merma y no se puede deshacer.`,
            confirmText: "Descartar",
            dangerMode: true,
        });
        if (!ok) return;
        setBusyId(lot.id);
        try {
            await discardLot(lot.public_id, { reason: "Descarte de lote" });
            toast.success("Lote descartado");
            await afterChange();
        } catch (err) {
            toast.error(apiError(err, "No se pudo descartar el lote"));
        } finally {
            setBusyId(null);
        }
    };

    const handleStatus = async (lot, status, verb) => {
        if (status === "recalled") {
            const ok = await confirm({
                message: `¿Marcar el lote ${lot.lot_number} como retirado del mercado? Se bloqueará su consumo conservando el saldo.`,
                confirmText: "Retirar",
                dangerMode: true,
            });
            if (!ok) return;
        }
        setBusyId(lot.id);
        try {
            await setLotStatus(lot.public_id, { status });
            toast.success(`Lote ${verb}`);
            await afterChange();
        } catch (err) {
            toast.error(apiError(err, "No se pudo cambiar el estado del lote"));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="modal-overlay">
            <div className="modal modal-md">
                <div className="modal-header">
                    <div>
                        <h3>Lotes · {product.name}</h3>
                        <p style={{ fontSize: "12.5px", color: "var(--c-text-2)", marginTop: "2px" }}>
                            Caducidad, existencias y estado por lote
                        </p>
                    </div>
                    <button className="modal-close" onClick={onClose}><Icon.X s={16} /></button>
                </div>

                <div className="modal-body">
                    {loading ? (
                        <p style={{ color: "var(--c-text-3)", fontSize: 13 }}>Cargando lotes…</p>
                    ) : lots.length === 0 ? (
                        <p style={{ color: "var(--c-text-3)", fontSize: 13 }}>
                            Este producto aún no tiene lotes. Regístralos con "Entrada de stock".
                        </p>
                    ) : (
                        <div className="table-wrap">
                            <table className="table">
                                <thead>
                                    <tr>
                                        <th>Lote</th>
                                        <th>Caduca</th>
                                        <th style={{ textAlign: "right" }}>Saldo</th>
                                        <th>Estado</th>
                                        <th style={{ textAlign: "right" }}>Acciones</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {lots.map((lot) => {
                                        const meta = STATUS_META[lot.effective_status] || STATUS_META.active;
                                        const busy = busyId === lot.id;
                                        const hasStock = Number(lot.quantity_on_hand) > 0;
                                        return (
                                            <tr key={lot.id}>
                                                <td style={{ fontWeight: 600 }}>{lot.lot_number}</td>
                                                <td>{lot.expiry_date || "—"}</td>
                                                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                                                    {Math.round(Number(lot.quantity_on_hand))}
                                                </td>
                                                <td><span className={`badge ${meta.cls}`}>{meta.label}</span></td>
                                                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                                                    {lot.status === "active" ? (
                                                        <>
                                                            <button className="btn btn-ghost btn-xs" disabled={busy}
                                                                onClick={() => handleStatus(lot, "quarantined", "en cuarentena")}>
                                                                Cuarentena
                                                            </button>
                                                            <button className="btn btn-ghost btn-xs" disabled={busy}
                                                                onClick={() => handleStatus(lot, "recalled", "retirado")}>
                                                                Retirar
                                                            </button>
                                                        </>
                                                    ) : (
                                                        <button className="btn btn-ghost btn-xs" disabled={busy}
                                                            onClick={() => handleStatus(lot, "active", "reactivado")}>
                                                            Reactivar
                                                        </button>
                                                    )}
                                                    {hasStock && (
                                                        <button className="btn btn-ghost btn-xs" disabled={busy}
                                                            title="Descartar (merma)"
                                                            onClick={() => handleDiscard(lot)}>
                                                            <Icon.Trash s={13} />
                                                        </button>
                                                    )}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                <div className="modal-footer">
                    <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={onClose}>
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    );
};

export default LotManagerModal;
