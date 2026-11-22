import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { acceptLegal, getCurrentLegal } from "../api/legal";
import { getMe } from "../auth/login";
import { useAuth } from "../auth/authContext";
import { getItem } from "../auth/tokenStorage";
import { apiError } from "../utils/apiError";
import Skeleton from "react-loading-skeleton";

// Pantalla dedicada /aceptar-terminos (ADR p46, decisión 4). Bloquea ANTES del
// Layout/Dashboard. El backend es el gate autoritativo; esto es la UX de captura.
const DOC_LABEL = {
    terms: "los Términos y Condiciones",
    privacy: "el Aviso de Privacidad",
    cookies: "la Política de Cookies",
};

export default function AcceptLegal() {
    const { setUserData, logout } = useAuth();
    const navigate = useNavigate();

    const [docs, setDocs] = useState([]);
    const [checked, setChecked] = useState({});
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        getCurrentLegal()
            .then((data) => setDocs(data.documents || []))
            .catch((err) => toast.error(apiError(err, "No se pudieron cargar los documentos.")))
            .finally(() => setLoading(false));
    }, []);

    const allChecked = docs.length > 0 && docs.every((d) => checked[d.public_id]);

    const toggle = (id) => (e) => setChecked((prev) => ({ ...prev, [id]: e.target.checked }));

    const handleSubmit = async () => {
        if (!allChecked) {
            toast.error("Debes aceptar todos los documentos para continuar.");
            return;
        }
        setSaving(true);
        try {
            await acceptLegal(docs.map((d) => d.public_id));
            // Refrescar /me/ para limpiar legal_acceptance_required → el gate deja pasar.
            const token = getItem("access_token");
            const me = await getMe(token);
            setUserData(me);
            toast.success("¡Listo! Gracias por aceptar.");
            navigate("/", { replace: true });
        } catch (err) {
            toast.error(apiError(err, "No se pudo registrar la aceptación."));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div style={{
            minHeight: "100vh", display: "flex", alignItems: "center",
            justifyContent: "center", padding: "24px", background: "var(--c-bg)",
        }}>
            <div style={{
                width: "100%", maxWidth: "560px", background: "var(--c-surface)",
                border: "1px solid var(--c-border)", borderRadius: "12px", padding: "24px",
            }}>
                <h1 className="page-title" style={{ marginTop: 0 }}>Antes de continuar</h1>
                <p className="page-subtitle">
                    Para usar SaaslyVet necesitamos que leas y aceptes los siguientes documentos.
                    Se abren en una pestaña nueva.
                </p>

                {loading ? (
                    // Una fila por documento (casilla + texto), como la lista real.
                    <div role="status" aria-label="Cargando documentos" style={{ display: "flex", flexDirection: "column", gap: "12px", margin: "16px 0" }}>
                        {[0, 1].map((i) => (
                            <div key={i} aria-hidden="true" style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                                <Skeleton width={16} height={16} borderRadius="var(--r-sm)" />
                                <Skeleton width={i === 0 ? 300 : 260} height={14} />
                            </div>
                        ))}
                    </div>
                ) : docs.length === 0 ? (
                    <p>No hay documentos pendientes.</p>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "12px", margin: "16px 0" }}>
                        {docs.map((d) => (
                            <label key={d.public_id} style={{ display: "flex", gap: "10px", alignItems: "flex-start", fontSize: "14px" }}>
                                <input
                                    type="checkbox"
                                    checked={!!checked[d.public_id]}
                                    onChange={toggle(d.public_id)}
                                    disabled={saving}
                                    style={{ marginTop: "4px" }}
                                />
                                <span>
                                    He leído y acepto{" "}
                                    <a href={d.landing_url} target="_blank" rel="noopener noreferrer">
                                        {DOC_LABEL[d.doc_type] || d.doc_type}
                                    </a>{" "}
                                    (versión {d.version}).
                                </span>
                            </label>
                        ))}
                    </div>
                )}

                <div style={{ display: "flex", gap: "10px", marginTop: "20px" }}>
                    <button
                        className="btn btn-primary btn-md"
                        style={{ flex: 1 }}
                        onClick={handleSubmit}
                        disabled={saving || !allChecked}
                    >
                        {saving ? "Guardando…" : "Aceptar y continuar"}
                    </button>
                    <button
                        className="btn btn-ghost btn-md"
                        onClick={logout}
                        disabled={saving}
                    >
                        Cerrar sesión
                    </button>
                </div>
            </div>
        </div>
    );
}
