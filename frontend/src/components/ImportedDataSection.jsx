/* Muestra los datos históricos importados del sistema anterior de la clínica
   (Pet.extra_data / Owner.extra_data, Sprint import Fase D). SOLO LECTURA.
   Lenguaje de migración a propósito ("Información del sistema anterior"), NO
   "Notas" ni "Información adicional", para que no se confunda con un campo
   editable. Lista de {label, value}; oculto si no hay datos. */
const ImportedDataSection = ({ items }) => {
    if (!items || items.length === 0) return null;
    return (
        <div style={{ marginTop: "18px" }}>
            <p
                style={{
                    fontWeight: "600",
                    marginBottom: "10px",
                    fontSize: "12px",
                    color: "var(--c-text-2)",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                }}
            >
                Información del sistema anterior
            </p>
            {items.map((it, i) => (
                <div key={i} className="info-row">
                    <span className="info-row-label">{it.label}</span>
                    <span className="info-row-value">{it.value || "—"}</span>
                </div>
            ))}
        </div>
    );
};

export default ImportedDataSection;
