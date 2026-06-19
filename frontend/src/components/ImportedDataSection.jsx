/* Muestra los datos históricos importados del sistema anterior de la clínica
   (Pet.extra_data / Owner.extra_data, Sprint import Fase D). SOLO LECTURA.
   Lenguaje de migración a propósito ("Datos importados del sistema anterior"),
   NO "Notas" ni "Información adicional", para que no se confunda con un campo
   editable: estos datos vienen de una migración y no se actualizan solos.
   Cada item = {label, value, source_column?, imported_at?}; aquí solo se muestra
   label + value. Oculto si no hay datos. */
const ImportedDataSection = ({ items }) => {
    if (!items || items.length === 0) return null;
    return (
        <div style={{ marginTop: "18px" }}>
            <p
                style={{
                    fontWeight: "600",
                    marginBottom: "4px",
                    fontSize: "12px",
                    color: "var(--c-text-2)",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                }}
            >
                <span>Datos importados del sistema anterior</span>
                <span aria-hidden="true">🔒</span>
            </p>
            <p
                style={{
                    fontSize: "12px",
                    color: "var(--c-text-3)",
                    marginBottom: "10px",
                    lineHeight: 1.5,
                }}
            >
                Estos datos vienen de una migración y no se actualizan automáticamente.
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
