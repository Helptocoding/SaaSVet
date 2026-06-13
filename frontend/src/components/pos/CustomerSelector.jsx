import SearchSelect from "../SearchSelect";
import { getOwners, getPets } from "../../api/pets";

const toList = (d) => (Array.isArray(d) ? d : d?.results || []);

/* ── CustomerSelector — cliente opcional de la venta (ADR p25) ──
   Sin cliente → owner genérico "Público General" (lo resuelve la página).
   owner lleva public_id (para filtrar pets vía ?owner=) e id (PK, body). */
const CustomerSelector = ({ customer, setCustomer, disabled }) => {
    const handleOwnerSearch = async (q) => {
        const data = await getOwners({ search: q, is_generic: "false" })
            .then(toList)
            .catch(() => []);
        return data.slice(0, 8).map(o => ({
            id: o.id,
            public_id: o.public_id,
            label: o.phone ? `${o.name} — ${o.phone}` : o.name,
        }));
    };

    const handlePetSearch = async (q) => {
        if (!customer.owner) return [];
        const data = await getPets({ owner: customer.owner.public_id, search: q })
            .then(toList)
            .catch(() => []);
        return data
            .filter(p => !p.is_generic)
            .slice(0, 8)
            .map(p => ({ id: p.id, label: p.name }));
    };

    return (
        <div>
            <label className="form-label">Cliente</label>
            <SearchSelect
                placeholder="Público General (buscar cliente…)"
                value={customer.owner}
                onChange={item => setCustomer({ owner: item, pet: null })}
                onSearch={handleOwnerSearch}
                disabled={disabled}
            />
            {customer.owner && (
                <div style={{ marginTop: "8px" }}>
                    <label className="form-label">Mascota (opcional)</label>
                    <SearchSelect
                        placeholder="Buscar mascota del cliente…"
                        value={customer.pet}
                        onChange={item => setCustomer(prev => ({ ...prev, pet: item }))}
                        onSearch={handlePetSearch}
                        disabled={disabled}
                    />
                </div>
            )}
        </div>
    );
};

export default CustomerSelector;
