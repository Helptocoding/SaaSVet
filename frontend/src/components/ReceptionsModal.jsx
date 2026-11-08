import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Icon } from "./icons";
import { useConfirm } from "./useConfirm";
import { useAuth } from "../auth/authContext";
import { apiError } from "../utils/apiError";
import { formatDateTime, orgTz } from "../utils/datetime";
import {
    completeReception, discardReception, getReception, getReceptions, getUnattributedReceptionEntries,
} from "../api/inventory";
import s from "../pages/inventory.module.css";

const FILTERS = [
    { value: "", label: "Todas" },
    { value: "pending", label: "Sin resolver" },
    { value: "confirmed", label: "Confirmadas" },
    { value: "discarded", label: "Descartadas" },
    { value: "unattributed", label: "Entradas sin identidad" },
];
const STATUS_LABEL = { pending: "Sin confirmar", confirmed: "Confirmada", discarded: "Descartada" };
const STATUS_BADGE = { pending: "badge-warning", confirmed: "badge-success", discarded: "badge-default" };
const DISCARD_REASONS = [
    { value: "not_received", label: "La mercancía no se recibió" },
    { value: "already_registered", label: "Ya se registró por otra vía" },
    { value: "entered_in_error", label: "Captura equivocada" },
];
const discardReasonLabel = (value) => DISCARD_REASONS.find(reason => reason.value === value)?.label || "Sin motivo";

const cursorOf = (next) => (next ? new URL(next, window.location.origin).searchParams.get("cursor") : null);

const qty = (value) => {
    const number = parseFloat(value);
    return Number.isFinite(number) ? number.toLocaleString("es-MX", { maximumFractionDigits: 4 }) : "—";
};

const lineSummary = (operation) => {
    const lines = operation.requested_lines;
    if (!lines) {
        const lots = (operation.legacy_lots || []).map(lot => lot.lot_number).join(", ");
        return lots ? `Lotes ${lots} · sin cantidades registradas` : "Sin captura conservada";
    }
    const text = lines.map(line => `Lote ${line.lot_number} × ${qty(line.quantity)}`).join(" · ");
    const hidden = operation.lines_total - lines.length;
    return hidden > 0 ? `${text} · y ${hidden} más` : text;
};

const StatusSummary = ({ operation, tz }) => {
    const resolved = operation.resolved_at ? formatDateTime(operation.resolved_at, tz) : "";
    if (operation.status === "pending" && operation.evidence_level === "unavailable") {
        return <p className={s.recStatus}>Esta operación no conserva lo capturado y no puede completarse. Verifica físicamente la mercancía y descártala; si llegó, registra una recepción nueva.</p>;
    }
    if (operation.status === "pending") {
        return (
            <p className={s.recStatus}>
                Según el servidor, esta operación todavía no ha sumado stock. Si otra pestaña o petición
                sigue en curso, completar o descartar espera a que termine y nunca suma dos veces.
            </p>
        );
    }
    if (operation.status === "discarded") {
        return <p className={s.recStatus}>Descartada por {operation.resolved_by_name || "otra persona"} el {resolved}: {discardReasonLabel(operation.discard_reason)}. No sumó stock.{operation.discard_note ? ` Nota: ${operation.discard_note}` : ""}</p>;
    }
    if (operation.evidence_level === "ledger") {
        return <p className={s.recStatus}>Esta recepción ya sumó stock el {formatDateTime(operation.applied_lines[0]?.created_at || operation.resolved_at, tz)}. No hace falta repetirla.</p>;
    }
    return (
        <p className={s.recStatus}>
            Consta como confirmada por un recibo anterior a este control. Ese recibo no conserva cantidades
            por línea: compara con tu remisión y con el libro de movimientos. No hace falta repetirla.
        </p>
    );
};

const LinesTable = ({ caption, head, rows }) => (
    <div className={s.recSection}>
        <h4>{caption}</h4>
        <table className={s.recTable}>
            <thead><tr>{head.map(label => <th key={label}>{label}</th>)}</tr></thead>
            <tbody>{rows.map(row => <tr key={row[0]}>{row.slice(1).map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}</tbody>
        </table>
    </div>
);

const OperationEvidence = ({ operation, tz }) => {
    const applied = operation.applied_lines || [];
    const ledger = operation.ledger_since_intent;
    const balance = operation.current_balance;
    return (
        <>
            {operation.requested_lines && (
                <LinesTable
                    caption={`Lo capturado en ${operation.presentation_name}${operation.supplier_name ? ` · ${operation.supplier_name}` : ""}`}
                    head={["Lote", "Caducidad", "Cantidad"]}
                    rows={operation.requested_lines.map((line, index) => [index, line.lot_number, line.expiry_date || "—", qty(line.quantity)])}
                />
            )}
            {applied.length > 0 && (
                <LinesTable
                    caption="Lo que el libro de movimientos registró para esta operación"
                    head={["Lote", "Presentación", `Unidad base (${operation.base_unit || "ud."})`]}
                    rows={applied.map(line => [line.movement_id, line.lot_number, qty(line.quantity_presentation), qty(line.quantity_base)])}
                />
            )}
            {operation.legacy_lots && (
                <div className={s.recSection}>
                    <h4>Lotes del recibo</h4>
                    <p>{operation.legacy_lots.map(lot => lot.lot_number).join(", ") || "Sin lotes"}</p>
                </div>
            )}
            {ledger && (
                ledger.entries.length > 0 ? (
                    <LinesTable
                        caption={`Otras entradas de este producto desde esta captura${ledger.truncated ? " (las más recientes)" : ""}`}
                        head={["Fecha", "Lote", "Cantidad base", "Usuario"]}
                        rows={ledger.entries.map(entry => [entry.id, formatDateTime(entry.created_at, tz), entry.lot_number || "—", qty(entry.quantity), entry.actor_name || "—"])}
                    />
                ) : (
                    <div className={s.recSection}>
                        <h4>Otras entradas de este producto desde esta captura</h4>
                        <p>Ninguna hasta ahora.</p>
                    </div>
                )
            )}
            {balance && (
                <div className={s.recSection}>
                    <h4>Saldo actual (informativo)</h4>
                    <p>
                        {qty(balance.product_stock_quantity)} {balance.base_unit || "ud."} en el producto
                        {balance.lots.length > 0 ? ` · ${balance.lots.map(lot => `lote ${lot.lot_number}: ${qty(lot.quantity_on_hand)}`).join(" · ")}` : ""}.
                    </p>
                    <p className={s.recHint}>Acumula otras entradas y salidas: no es la cantidad de esta operación.</p>
                </div>
            )}
        </>
    );
};

const UnattributedList = ({ rows, tz }) => (
    <div className={s.recReview}>
        <p>
            Estas entradas sí están en el libro de movimientos, pero se registraron sin identidad de operación
            (antes de este control o por una llamada directa). El sistema no puede decir a qué intento corresponden.
        </p>
        <ol>
            <li>Compara producto, lote, cantidad, fecha y usuario con tu remisión.</li>
            <li>Si tu entrega aparece aquí, ya sumó stock: no hay nada que repetir ni que corregir.</li>
            <li>Si no aparece, usa «Registrar una recepción nueva».</li>
        </ol>
        {rows.length === 0 && <p className={s.recHint}>No hay entradas sin identidad en esta vista.</p>}
        {rows.length > 0 && (
            <LinesTable
                caption="Entradas sin identidad"
                head={["Fecha", "Producto", "Lote", "Cantidad", "Usuario"]}
                rows={rows.map(entry => [entry.id, formatDateTime(entry.created_at, tz), `${entry.product_name} · ${entry.presentation_name}`, entry.lot_number || "—", `${qty(entry.quantity)} ${entry.quantity_unit === "base" ? "base" : "presentación"}`, entry.actor_name || "—"])}
            />
        )}
    </div>
);

/**
 * Recepciones según el servidor. No lee nada del navegador: sirve también tras perder
 * toda la sesión. Nunca elige por el usuario: aunque haya una sola candidata, resolverla
 * exige seleccionarla y confirmar.
 */
const ReceptionsModal = ({ products = [], initialFilter = "", onClose, onChanged, onNewReception }) => {
    const { user } = useAuth();
    const confirm = useConfirm();
    const tz = orgTz(user);

    const [query, setQuery] = useState({ filter: initialFilter, scope: "own", product: "", tick: 0 });
    const [rows, setRows] = useState([]);
    const [next, setNext] = useState(null);
    const [canSupervise, setCanSupervise] = useState(false);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [listError, setListError] = useState("");
    const [selectedId, setSelectedId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailError, setDetailError] = useState("");
    const [acting, setActing] = useState(false);
    const [discardReason, setDiscardReason] = useState("");
    const [discardNote, setDiscardNote] = useState("");
    const detailRequest = useRef(0);
    const listRevision = useRef(0);

    const isUnattributed = query.filter === "unattributed";
    const fetchPage = ({ filter, scope, product }, cursor) => {
        const params = { scope, ...(cursor ? { cursor } : {}) };
        if (filter === "unattributed") return getUnattributedReceptionEntries(params);
        return getReceptions({ ...params, ...(filter ? { status: filter } : {}), ...(product ? { product } : {}) });
    };

    useEffect(() => {
        let cancelled = false;
        fetchPage(query)
            .then(data => {
                if (cancelled) return;
                setRows(data.results || []);
                setNext(data.next || null);
                if (data.can_supervise !== undefined) setCanSupervise(data.can_supervise);
                setListError("");
            })
            .catch(err => { if (!cancelled) { setRows([]); setNext(null); setListError(apiError(err, "No se pudo consultar el servidor.")); } })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [query]);

    const clearSelection = () => {
        detailRequest.current += 1;
        setSelectedId(null); setDetail(null); setDetailError("");
        setDiscardReason(""); setDiscardNote("");
    };

    const changeQuery = (patch) => {
        listRevision.current += 1;
        setLoading(true);
        clearSelection();
        setQuery(current => ({ ...current, ...patch }));
    };

    const reloadList = () => {
        listRevision.current += 1;
        setLoading(true);
        setQuery(current => ({ ...current, tick: current.tick + 1 }));
    };

    const loadMore = async () => {
        const revision = listRevision.current;
        setLoadingMore(true);
        try {
            const data = await fetchPage(query, cursorOf(next));
            if (revision !== listRevision.current) return;
            setRows(current => [...current, ...(data.results || [])]);
            setNext(data.next || null);
        } catch (err) {
            toast.error(apiError(err, "No se pudieron cargar más recepciones."));
        } finally {
            setLoadingMore(false);
        }
    };

    const loadDetail = async (operationId) => {
        const request = ++detailRequest.current;
        setSelectedId(operationId); setDetail(null); setDetailError("");
        setDiscardReason(""); setDiscardNote("");
        try {
            const data = await getReception(operationId);
            if (request === detailRequest.current) setDetail(data);
        } catch (err) {
            if (request === detailRequest.current) setDetailError(apiError(err, "No se pudo consultar esta recepción."));
        }
    };

    const afterAction = (operation) => {
        setDetail(operation);
        reloadList();
        onChanged?.(operation.operation_id);
    };

    const afterConflict = async (err, fallback) => {
        toast.error(apiError(err, fallback));
        // Otra persona o petición pudo decidir antes: se muestra lo que el servidor sabe ahora.
        await loadDetail(detail.operation_id);
        reloadList();
        onChanged?.(detail.operation_id);
    };

    const handleComplete = async () => {
        const ok = await confirm({
            message: `Se sumará al stock exactamente lo capturado en esta operación de ${detail.product_name}. Comprueba antes que esa mercancía no se haya registrado por otra vía.`,
            confirmText: "Completar recepción",
            dangerMode: false,
        });
        if (!ok) return;
        setActing(true);
        try {
            afterAction(await completeReception(detail.operation_id));
            toast.success("Recepción completada.");
        } catch (err) {
            await afterConflict(err, "No se pudo completar la recepción.");
        } finally {
            setActing(false);
        }
    };

    const handleDiscard = async () => {
        if (!discardReason) { toast.error("Indica por qué se descarta."); return; }
        const ok = await confirm({
            message: "La operación quedará cerrada sin sumar stock y no podrá completarse después. El registro se conserva.",
            confirmText: "Descartar operación",
            dangerMode: true,
        });
        if (!ok) return;
        setActing(true);
        try {
            afterAction(await discardReception(detail.operation_id, { reason: discardReason, note: discardNote.trim() }));
            toast.success("Operación descartada. No sumó stock.");
        } catch (err) {
            await afterConflict(err, "No se pudo descartar la operación.");
        } finally {
            setActing(false);
        }
    };

    const actions = detail?.allowed_actions || [];

    return (
        <div className="modal-overlay">
            <div className={`modal ${s.recModal}`} role="dialog" aria-label="Recepciones">
                <div className="modal-header">
                    <div>
                        <h3>Recepciones</h3>
                        <p className={s.recSubtitle}>Lo que el servidor registró de cada recepción, aunque este navegador no recuerde nada.</p>
                    </div>
                    <button className="modal-close" onClick={onClose} aria-label="Cerrar"><Icon.X s={16} /></button>
                </div>

                <div className="modal-body">
                    <div className={s.recFilters}>
                        <div className="segmented-control" role="group" aria-label="Estado">
                            {FILTERS.map(option => (
                                <button key={option.value} type="button" aria-pressed={query.filter === option.value} onClick={() => changeQuery({ filter: option.value })}>
                                    {option.label}
                                </button>
                            ))}
                        </div>
                        {canSupervise && (
                            <div className="segmented-control" role="group" aria-label="Alcance">
                                <button type="button" aria-pressed={query.scope === "own"} onClick={() => changeQuery({ scope: "own" })}>Mías</button>
                                <button type="button" aria-pressed={query.scope === "organization"} onClick={() => changeQuery({ scope: "organization" })}>Toda la clínica</button>
                            </div>
                        )}
                        {!isUnattributed && (
                            <select className={s.recSelect} aria-label="Producto" value={query.product} onChange={e => changeQuery({ product: e.target.value })}>
                                <option value="">Todos los productos</option>
                                {products.filter(product => product.tracks_lots).map(product => (
                                    <option key={product.public_id} value={product.public_id}>{product.name}</option>
                                ))}
                            </select>
                        )}
                    </div>

                    {listError && <div className={s.recError} role="alert">{listError} <button type="button" className="btn btn-secondary btn-sm" onClick={reloadList}>Reintentar</button></div>}

                    {isUnattributed ? (
                        <>
                            {loading ? <p className={s.recHint}>Consultando el servidor…</p> : !listError && <UnattributedList rows={rows} tz={tz} />}
                            {!loading && next && (
                                <button type="button" className="btn btn-secondary btn-sm" disabled={loadingMore} onClick={loadMore}>
                                    {loadingMore ? "Cargando…" : "Cargar más"}
                                </button>
                            )}
                        </>
                    ) : (
                        <div className={s.recLayout}>
                            <div className={s.recList}>
                                {loading && <p className={s.recHint}>Consultando el servidor…</p>}
                                {!loading && !listError && rows.length === 0 && (
                                    <p className={s.recHint}>
                                        No hay operaciones en esta vista.
                                        {!query.filter && !query.product && " Lo que no aparece aquí no sumó stock como operación; si crees que tu entrega entró de otra forma, revisa «Entradas sin identidad»."}
                                    </p>
                                )}
                                {!loading && rows.map(operation => (
                                    <button
                                        key={operation.operation_id}
                                        type="button"
                                        className={`${s.recRow} ${selectedId === operation.operation_id ? s.recRowOn : ""}`}
                                        aria-pressed={selectedId === operation.operation_id}
                                        onClick={() => loadDetail(operation.operation_id)}
                                    >
                                        <span className={s.recRowTop}>
                                            <strong>{operation.product_name}</strong>
                                            <span className={`badge ${STATUS_BADGE[operation.status]}`}>{STATUS_LABEL[operation.status]}</span>
                                        </span>
                                        <span>{lineSummary(operation)}</span>
                                        <span className={s.recHint}>{formatDateTime(operation.created_at, tz)} · {operation.is_own ? "Tú" : operation.actor_name}</span>
                                    </button>
                                ))}
                                {!loading && next && (
                                    <button type="button" className="btn btn-secondary btn-sm" disabled={loadingMore} onClick={loadMore}>
                                        {loadingMore ? "Cargando…" : "Cargar más"}
                                    </button>
                                )}
                            </div>

                            <div className={s.recDetail}>
                                {!selectedId && <p className={s.recHint}>Selecciona una operación para ver lo que el servidor acredita. Dos recepciones con el mismo lote y cantidad pueden ser legítimas: compáralas con tu remisión.</p>}
                                {selectedId && !detail && !detailError && <p className={s.recHint}>Consultando…</p>}
                                {detailError && <div className={s.recError} role="alert">{detailError}</div>}
                                {detail && (
                                    <>
                                        <div className={s.recRowTop}>
                                            <strong>{detail.product_name} · {detail.presentation_name}</strong>
                                            <span className={`badge ${STATUS_BADGE[detail.status]}`}>{STATUS_LABEL[detail.status]}</span>
                                        </div>
                                        <p className={s.recHint}>Capturada el {formatDateTime(detail.created_at, tz)} por {detail.is_own ? "ti" : detail.actor_name}.</p>
                                        <StatusSummary operation={detail} tz={tz} />
                                        <OperationEvidence operation={detail} tz={tz} />

                                        {actions.includes("complete") && (
                                            <div className={s.recActions}>
                                                <button type="button" className="btn btn-primary btn-sm" disabled={acting} onClick={handleComplete}>
                                                    {acting ? "Procesando…" : "Completar esta recepción"}
                                                </button>
                                            </div>
                                        )}
                                        {detail.status === "pending" && !detail.is_own && (
                                            <p className={s.recHint}>Solo {detail.actor_name} puede completarla. Puedes cerrarla si esa mercancía no va a registrarse por esta operación.</p>
                                        )}
                                        {actions.includes("discard") && (
                                            <div className={s.recActions}>
                                                <select className={s.recSelect} aria-label="Motivo para descartar" value={discardReason} disabled={acting} onChange={e => setDiscardReason(e.target.value)}>
                                                    <option value="">Motivo para descartar…</option>
                                                    {DISCARD_REASONS.map(reason => <option key={reason.value} value={reason.value}>{reason.label}</option>)}
                                                </select>
                                                <input className={s.recNote} aria-label="Nota" placeholder="Nota (opcional)" maxLength={255} value={discardNote} disabled={acting} onChange={e => setDiscardNote(e.target.value)} />
                                                <button type="button" className="btn btn-secondary btn-sm" disabled={acting} onClick={handleDiscard}>Descartar esta operación</button>
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                <div className="modal-footer">
                    <span className={`${s.recHint} ${s.recFooterHint}`}>Una recepción nueva es una entrada distinta: suma stock aunque coincida en lote y cantidad con otra.</span>
                    <button type="button" className="btn btn-secondary btn-md" onClick={onNewReception}>Registrar una recepción nueva</button>
                    <button type="button" className="btn btn-primary btn-md" onClick={onClose}>Cerrar</button>
                </div>
            </div>
        </div>
    );
};

export default ReceptionsModal;
