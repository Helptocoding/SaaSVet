/* Override opcional de lote; vacío conserva FEFO multi-lote del backend. */
const DispenseLotSelect = ({ row, setRow, disabled }) => {
    const presentation = row.presentations.find(
        item => String(item.id) === String(row.presentationId),
    );
    const lots = presentation?.lots || [];

    return (
        <select
            className="input" style={{ height: "30px" }}
            value={row.lot?.id ?? ""} disabled={disabled}
            onChange={e => setRow(row.key, { lot: lots.find(l => String(l.id) === e.target.value) || null })}
        >
            <option value="">FEFO automático</option>
            {lots.map(l => (
                <option key={l.id} value={l.id}>
                    {l.lot_number}{l.expiry_date ? ` · ${l.expiry_date}` : ""} · {l.available_quantity_base}
                </option>
            ))}
        </select>
    );
};

export default DispenseLotSelect;
