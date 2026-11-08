import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Icon } from "./icons";
import { apiError } from "../utils/apiError";
import { newOperationUuid } from "../utils/idempotency";
import { adjustPresentationStock, receiveStock } from "../api/inventory";
import s from "../pages/inventory.module.css";

const emptyLot = () => ({ lot_number: "", expiry_date: "", quantity: 1 });

const fmt = (n) => Math.round(parseFloat(n ?? 0) || 0);

const ICON_COLOR = { medication: "#3b82f6", food: "#0d9488", accessory: "#7c3aed", other: "#94a3b8" };
const CATEGORY_ICON = { medication: Icon.Pill, food: Icon.ShoppingBag, accessory: Icon.Package, other: Icon.Box };
const ICO_CLS = { medication: s.icoMed, food: s.icoFood, accessory: s.icoAcc, other: s.icoOther };

const CategoryIcon = ({ category, size = 18 }) => {
    const c = ICON_COLOR[category] || ICON_COLOR.other;
    const IconComp = CATEGORY_ICON[category] || CATEGORY_ICON.other;
    return <IconComp s={size} c={c} />;
};

/**
 * Entrada rápida de stock (recepción de mercancía).
 *
 * Capa UX sobre el ajuste existente: resuelve a una presentación específica
 * (barras / código interno / nombre) y suma vía adjustPresentationStock, que
 * aplica el conversion_factor del formato recibido (multi-presentación correcto).
 * NO crea productos ni modifica datos del producto.
 */
const StockEntryModal = ({ products, onClose, onSaved, onCreateNew, onReceptionIssue }) => {
    const [query, setQuery] = useState("");
    const [match, setMatch] = useState(null);        // { product, presentation|null, lockedFormat }
    const [presId, setPresId] = useState("");         // presentación elegida (multi)
    const [qty, setQty] = useState(1);
    const [nameResults, setNameResults] = useState([]);
    const [notFound, setNotFound] = useState(false);
    const [saving, setSaving] = useState(false);
    // Recepción por lotes (B1) — solo si el producto tiene tracks_lots.
    const [lots, setLots] = useState([emptyLot()]);
    const [supplierName, setSupplierName] = useState("");

    const searchRef = useRef(null);
    const qtyRef = useRef(null);
    // Reintentar la misma captura conserva su identidad; cambiarla es otra recepción.
    const receptionAttempt = useRef(null);

    useEffect(() => { searchRef.current?.focus(); }, []);

    const focusSearch = () => requestAnimationFrame(() => searchRef.current?.focus());
    const focusQty = () => requestAnimationFrame(() => qtyRef.current?.focus());

    const resetToSearch = (clearQuery = true) => {
        if (clearQuery) setQuery("");
        setMatch(null); setPresId(""); setQty(1);
        setNameResults([]); setNotFound(false);
        setLots([emptyLot()]); setSupplierName("");
        focusSearch();
    };

    const addLot = () => setLots(ls => [...ls, emptyLot()]);
    const updateLot = (i, patch) => setLots(ls => ls.map((l, idx) => idx === i ? { ...l, ...patch } : l));
    const removeLot = (i) => setLots(ls => ls.length > 1 ? ls.filter((_, idx) => idx !== i) : ls);

    const selectProduct = (product, locked) => {
        const press = product.presentations || [];
        setNameResults([]); setNotFound(false); setQty(1);
        if (press.length === 0) { setNotFound(true); return; }
        if (press.length === 1) {
            setMatch({ product, presentation: press[0], lockedFormat: locked });
            setPresId(press[0].public_id);
            focusQty();
        } else {
            // Varias presentaciones → obligar selección, sin default (evita entradas incorrectas).
            setMatch({ product, presentation: null, lockedFormat: false });
            setPresId("");
        }
    };

    const runLookup = (raw) => {
        // Leer del DOM (raw) para lectores físicos: el scanner teclea + Enter en
        // milisegundos y el último setQuery aún no commitea cuando dispara Enter.
        const q = (typeof raw === "string" ? raw : query).trim();
        if (!q) return;
        if (q !== query) setQuery(q);
        setNotFound(false); setNameResults([]);

        // 1. Código de barras (presentación, exacto) → formato bloqueado.
        for (const p of products) {
            const pres = (p.presentations || []).find(pr => pr.barcode && pr.barcode === q);
            if (pres) {
                setMatch({ product: p, presentation: pres, lockedFormat: true });
                setPresId(pres.public_id);
                setQty(1);
                focusQty();
                return;
            }
        }
        // 2. Código interno (producto, exacto case-insensitive).
        const ql = q.toLowerCase();
        const byCode = products.find(p => (p.internal_code || "").toLowerCase() === ql);
        if (byCode) { selectProduct(byCode, false); return; }

        // 3. Nombre (contiene).
        const byName = products.filter(p => p.name.toLowerCase().includes(ql));
        if (byName.length === 1) { selectProduct(byName[0], false); return; }
        if (byName.length > 1) { setNameResults(byName); return; }

        setNotFound(true);
    };

    const onPickFormat = (publicId) => {
        setPresId(publicId);
        const pres = (match?.product?.presentations || []).find(p => p.public_id === publicId) || null;
        setMatch(m => (m ? { ...m, presentation: pres } : m));
        if (pres) focusQty();
    };

    const currentPres = match?.presentation
        || (match?.product?.presentations || []).find(p => p.public_id === presId)
        || null;

    const tracksLots = !!match?.product?.tracks_lots;

    // Al elegir un producto con control de lotes, reiniciar el editor de lotes.
    useEffect(() => {
        if (tracksLots) { setLots([emptyLot()]); setSupplierName(""); }
        // eslint-disable-next-line react-hooks/set-state-in-effect
    }, [match?.product?.public_id, tracksLots]);

    const handleConfirm = async () => {
        if (!currentPres) { toast.error("Selecciona la presentación recibida."); return; }

        if (tracksLots) {
            const clean = lots.map(l => ({ ...l, lot_number: (l.lot_number || "").trim() }));
            if (clean.some(l => !l.lot_number)) { toast.error("Cada lote necesita su número."); return; }
            if (clean.some(l => !(Number(l.quantity) > 0))) { toast.error("La cantidad de cada lote debe ser mayor a 0."); return; }
            const payload = {
                supplier_name: supplierName.trim(),
                lots: clean.map(l => ({
                    lot_number: l.lot_number,
                    expiry_date: l.expiry_date || null,
                    quantity: Number(l.quantity),
                })),
            };
            const fingerprint = JSON.stringify([currentPres.public_id, payload]);
            if (receptionAttempt.current?.fingerprint !== fingerprint) {
                receptionAttempt.current = { fingerprint, operationId: newOperationUuid() };
            }
            setSaving(true);
            try {
                await receiveStock(currentPres.public_id, payload, receptionAttempt.current.operationId);
                receptionAttempt.current = null;
                toast.success(`Recepción registrada · ${match.product.name}`);
                await onSaved?.();
                resetToSearch(true);
            } catch (err) {
                toast.error(apiError(err, "No se pudo confirmar la recepción"));
                await onReceptionIssue?.(err);
            } finally {
                setSaving(false);
            }
            return;
        }

        const n = Number(qty);
        if (!(n > 0)) { toast.error("La cantidad debe ser mayor a 0"); return; }
        setSaving(true);
        try {
            await adjustPresentationStock(currentPres.public_id, {
                movement_type: "in",
                quantity: n,
                reason: "Entrada de mercancía",
            });
            toast.success(`+${fmt(n)} ${currentPres.name} · ${match.product.name}`);
            await onSaved?.();
            resetToSearch(true); // limpiar y reenfocar para el siguiente escaneo
        } catch (err) {
            toast.error(apiError(err, "No se pudo registrar la entrada"));
        } finally {
            setSaving(false);
        }
    };

    // ── Preview (ambas unidades) ──────────────────────────────
    const stockBase = currentPres ? (parseFloat(match.product.stock_quantity ?? 0) || 0) : 0;
    const cf = currentPres ? (parseFloat(currentPres.conversion_factor ?? 1) || 1) : 1;
    const baseUnitLabel = currentPres ? (currentPres.base_unit_display || currentPres.base_unit || "ud.") : "";
    const lotsTotal = lots.reduce((a, l) => a + (Number(l.quantity) || 0), 0);
    const addedBase = (tracksLots ? lotsTotal : (Number(qty) || 0)) * cf;
    const newBase = stockBase + addedBase;
    const multiPres = (match?.product?.presentations?.length || 0) > 1;

    return (
        <div className="modal-overlay">
            <div className="modal modal-sm">
                <div className="modal-header">
                    <div>
                        <h3>Entrada de stock</h3>
                        <p style={{ fontSize: "12.5px", color: "var(--c-text-2)", marginTop: "2px" }}>
                            Escanea o busca para sumar mercancía recibida
                        </p>
                    </div>
                    <button className="modal-close" onClick={onClose}><Icon.X s={16} /></button>
                </div>

                <div className="modal-body">
                    {/* Buscador */}
                    <div className={s.seSearch}>
                        <Icon.Search s={15} c="var(--c-text-3)" />
                        <input
                            ref={searchRef}
                            type="text"
                            className={s.seSearchInput}
                            placeholder="Escanea código de barras o escribe código interno"
                            value={query}
                            onChange={e => { setQuery(e.target.value); if (notFound) setNotFound(false); }}
                            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); runLookup(e.target.value); } }}
                        />
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => runLookup()}>
                            Buscar
                        </button>
                    </div>

                    {/* Varias coincidencias por nombre → elegir */}
                    {nameResults.length > 0 && (
                        <div className={s.seNameList}>
                            {nameResults.slice(0, 8).map(p => (
                                <button
                                    key={p.public_id}
                                    type="button"
                                    className={s.seNameItem}
                                    onClick={() => selectProduct(p, false)}
                                >
                                    <span className={`${s.prodIco} ${ICO_CLS[p.category] || s.icoOther}`}>
                                        <CategoryIcon category={p.category} size={16} />
                                    </span>
                                    <span style={{ minWidth: 0 }}>
                                        <span className={s.seNameItemName}>{p.name}</span>
                                        {p.internal_code && <span className={s.seNameItemCode}>{p.internal_code}</span>}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}

                    {/* No encontrado */}
                    {notFound && (
                        <div className={s.seNotFound}>
                            <Icon.AlertCircle s={18} c="var(--c-danger-text)" />
                            <p style={{ margin: 0, fontWeight: 600 }}>No encontramos este producto</p>
                            <div className={s.seNotFoundActions}>
                                <button type="button" className="btn btn-secondary btn-sm" onClick={() => resetToSearch(true)}>
                                    Buscar manualmente
                                </button>
                                <button type="button" className="btn btn-primary btn-sm" onClick={() => { onClose?.(); onCreateNew?.(); }}>
                                    Crear producto nuevo
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Tarjeta de coincidencia */}
                    {match && (
                        <div className={s.seCard}>
                            <div className={s.seCardHead}>
                                <span className={`${s.prodIco} ${ICO_CLS[match.product.category] || s.icoOther}`}>
                                    <CategoryIcon category={match.product.category} />
                                </span>
                                <div style={{ minWidth: 0 }}>
                                    <div className={s.summaryProdName}>{match.product.name}</div>
                                    {match.product.internal_code && (
                                        <div className={s.prodDesc}>{match.product.internal_code}</div>
                                    )}
                                </div>
                            </div>

                            {/* Formato: selector (multi sin barras) | fijo */}
                            {multiPres && !match.lockedFormat ? (
                                <div className="form-group" style={{ marginBottom: 12 }}>
                                    <label className="form-label">PRESENTACIÓN RECIBIDA *</label>
                                    <select className="input" value={presId} onChange={e => onPickFormat(e.target.value)}>
                                        <option value="">Selecciona el formato…</option>
                                        {match.product.presentations.map(p => {
                                            const pcf = parseFloat(p.conversion_factor ?? 1) || 1;
                                            const unit = p.base_unit_display || p.base_unit || "";
                                            return (
                                                <option key={p.public_id} value={p.public_id}>
                                                    {p.name}{pcf > 1 ? ` (${fmt(pcf)} ${unit})` : ""}
                                                </option>
                                            );
                                        })}
                                    </select>
                                </div>
                            ) : currentPres && (
                                <div className={s.seFormatFixed}>
                                    Presentación: <strong>{currentPres.name}</strong>
                                    {cf > 1 && <span className={s.prodDesc}> · {fmt(cf)} {baseUnitLabel} c/u</span>}
                                </div>
                            )}

                            {currentPres && (
                                <>
                                    {/* Stock actual → nuevo (ambas unidades) */}
                                    <div className={s.seStockRow}>
                                        <div>
                                            <div className={s.seStockLbl}>Stock actual</div>
                                            <div className={s.seStockVal}>{fmt(stockBase)} <span>{baseUnitLabel}</span></div>
                                            {cf > 1 && <div className={s.seStockEquiv}>≈ {fmt(stockBase / cf)} {currentPres.name}</div>}
                                        </div>
                                        <div className={s.seArrow}>→</div>
                                        <div style={{ textAlign: "right" }}>
                                            <div className={s.seStockLbl}>Nuevo stock</div>
                                            <div className={`${s.seStockVal} ${s.seStockValNew}`}>{fmt(newBase)} <span>{baseUnitLabel}</span></div>
                                            {cf > 1 && <div className={s.seStockEquiv}>≈ {fmt(newBase / cf)} {currentPres.name}</div>}
                                        </div>
                                    </div>

                                    {/* Lote-trackeado: recepción multi-lote. Si no, stepper simple. */}
                                    {tracksLots ? (
                                        <>
                                            <div className="form-group" style={{ marginBottom: 10 }}>
                                                <label className="form-label">PROVEEDOR (OPCIONAL)</label>
                                                <input
                                                    className="input"
                                                    placeholder="Ej: Distribuidora X"
                                                    value={supplierName}
                                                    onChange={e => setSupplierName(e.target.value)}
                                                />
                                            </div>
                                            <div className="form-group" style={{ marginBottom: 0 }}>
                                                <label className="form-label">
                                                    LOTES RECIBIDOS ({currentPres.name.toUpperCase()}) *
                                                </label>
                                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 62px 30px", gap: 6, fontSize: 10.5, fontWeight: 600, color: "var(--c-text-3)", textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 3 }}>
                                                    <span>Lote</span>
                                                    <span>Caduca</span>
                                                    <span style={{ textAlign: "center" }}>Cant.</span>
                                                    <span />
                                                </div>
                                                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                                    {lots.map((l, i) => (
                                                        <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 62px 30px", gap: 6, alignItems: "center" }}>
                                                            <input
                                                                className="input" placeholder="A123"
                                                                value={l.lot_number}
                                                                onChange={e => updateLot(i, { lot_number: e.target.value })}
                                                            />
                                                            <input
                                                                className="input" type="date"
                                                                value={l.expiry_date}
                                                                onChange={e => updateLot(i, { expiry_date: e.target.value })}
                                                            />
                                                            <input
                                                                className="input" type="number" min="1" step="1"
                                                                style={{ textAlign: "center", fontWeight: 700 }}
                                                                value={l.quantity}
                                                                onChange={e => updateLot(i, { quantity: e.target.value })}
                                                            />
                                                            <button
                                                                type="button" className="btn btn-ghost btn-sm"
                                                                style={{ padding: 0 }}
                                                                disabled={lots.length === 1}
                                                                onClick={() => removeLot(i)}
                                                                title="Quitar lote"
                                                            >
                                                                <Icon.Trash s={14} />
                                                            </button>
                                                        </div>
                                                    ))}
                                                </div>
                                                <button type="button" className="btn btn-secondary btn-sm" style={{ marginTop: 8 }} onClick={addLot}>
                                                    <Icon.Plus s={13} /> Agregar lote
                                                </button>
                                                <p className={s.prodDesc} style={{ marginTop: 8, maxWidth: "none" }}>
                                                    Total: {fmt(lotsTotal)} {currentPres.name}
                                                    {cf > 1 ? ` = ${fmt(addedBase)} ${baseUnitLabel}` : ""}
                                                </p>
                                            </div>
                                        </>
                                    ) : (
                                        <div className="form-group" style={{ marginBottom: 0 }}>
                                            <label className="form-label">
                                                CANTIDAD RECIBIDA ({currentPres.name.toUpperCase()}) *
                                            </label>
                                            <div className={s.seStepper}>
                                                <button
                                                    type="button" className="btn btn-secondary btn-md"
                                                    style={{ width: 38, padding: 0, fontSize: 20, fontWeight: 400, flexShrink: 0 }}
                                                    onClick={() => setQty(q => Math.max(1, (Number(q) || 1) - 1))}
                                                >−</button>
                                                <input
                                                    ref={qtyRef}
                                                    type="number" min="1" step="1" className="input"
                                                    style={{ textAlign: "center", fontWeight: 700, fontSize: 16 }}
                                                    value={qty}
                                                    onChange={e => setQty(e.target.value)}
                                                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); handleConfirm(); } }}
                                                />
                                                <button
                                                    type="button" className="btn btn-secondary btn-md"
                                                    style={{ width: 38, padding: 0, fontSize: 20, fontWeight: 400, flexShrink: 0 }}
                                                    onClick={() => setQty(q => (Number(q) || 0) + 1)}
                                                >+</button>
                                            </div>
                                            {cf > 1 && Number(qty) > 0 && (
                                                <p className={s.prodDesc} style={{ marginTop: 6, maxWidth: "none" }}>
                                                    {fmt(qty)} {currentPres.name} = {fmt(addedBase)} {baseUnitLabel}
                                                </p>
                                            )}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    )}
                </div>

                <div className="modal-footer">
                    {match && currentPres ? (
                        <>
                            <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleConfirm} disabled={saving}>
                                {saving ? "Registrando..." : (tracksLots ? "Registrar recepción" : "Confirmar entrada")}
                            </button>
                            <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={() => resetToSearch(true)}>
                                Otro producto
                            </button>
                        </>
                    ) : (
                        <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={onClose}>
                            Cerrar
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default StockEntryModal;
