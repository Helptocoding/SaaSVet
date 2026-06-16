import EntitySearch from "../EntitySearch";
import { searchOwners, searchPets } from "../../api/lookups";
import {
    renderOwnerOption, ownerOptionLabel,
    renderPetOption, petOptionLabel,
} from "../lookupOptions";

/* ── CustomerSelector — cliente opcional de la venta (ADR p25) ──
   Sin cliente → owner genérico "Público General" (lo resuelve la página).
   Usa EntitySearch: cada opción muestra teléfono/expediente (cliente) o
   dueño·tel (mascota) para diferenciar homónimos, con "Ver más" sin tope
   invisible. El value es el objeto completo (owner trae id PK + public_id;
   pet trae id PK), consumido por la página para el cuerpo de la venta. */
const CustomerSelector = ({ customer, setCustomer, disabled }) => (
    <div>
        <label className="form-label">Cliente</label>
        <EntitySearch
            placeholder="Público General (buscar cliente…)"
            value={customer.owner}
            onChange={item => setCustomer({ owner: item, pet: null })}
            fetchPage={({ query, page }) => searchOwners({ query, page })}
            renderItem={renderOwnerOption}
            getOptionLabel={ownerOptionLabel}
            disabled={disabled}
        />
        {customer.owner && (
            <div style={{ marginTop: "8px" }}>
                <label className="form-label">Mascota (opcional)</label>
                <EntitySearch
                    placeholder="Buscar mascota del cliente…"
                    value={customer.pet}
                    onChange={item => setCustomer(prev => ({ ...prev, pet: item }))}
                    fetchPage={({ query, page }) => searchPets({ query, page, ownerPublicId: customer.owner.public_id })}
                    renderItem={renderPetOption}
                    getOptionLabel={petOptionLabel}
                    disabled={disabled}
                />
            </div>
        )}
    </div>
);

export default CustomerSelector;
