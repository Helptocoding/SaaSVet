import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useSearchParams } from "react-router-dom";
import { useConfirm } from "../components/ConfirmDialog";
import { toast } from "sonner";
import { Icon } from "../components/icons";
import PrescriptionForm from "../components/prescriptions/PrescriptionForm";
import { useAuth } from "../auth/authContext";
import { getProducts } from "../api/inventory";
import { getMedicalRecords } from "../api/medicalRecords";
import { getPets } from "../api/pets";
import {
    createPrescription,
    deletePrescription,
    downloadPrescriptionPDF,
    getPrescription,
    getPrescriptions,
    updatePrescription,
} from "../api/prescriptions";
import { extractFilename, triggerDownload } from "../utils/downloadBlob";
import { isCanino, isFelino, getAgeGroup } from "../utils/petFilters";

const formatDate = (ds) =>
    new Date(ds).toLocaleDateString("es-ES", { year: "numeric", month: "long", day: "numeric" });

const MONTHS_SHORT = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

// ─── Detail Modal ──────────────────────────────────────────────────────────────
const DetailModal = ({ prescription: rx, downloadingId, onDownload, onClose }) => (
    <div className="modal-overlay">
        <div className="modal modal-md">
            <div className="modal-header">
                <div>
                    <h3 style={{ fontSize: "16px", fontWeight: "700" }}>
                        Receta de {rx.pet_name}
                    </h3>
                    <p style={{ fontSize: "12px", color: "var(--c-text-3)", marginTop: "3px" }}>
                        {formatDate(rx.created_at)}
                    </p>
                </div>
                <button className="modal-close" onClick={onClose}><Icon.X s={16} /></button>
            </div>

            <div className="modal-body" style={{ paddingTop: "16px" }}>
                {/* Meta */}
                <div style={{
                    display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                    gap: "12px", marginBottom: "20px",
                    padding: "12px 14px", background: "var(--c-subtle)",
                    borderRadius: "var(--r-md)", border: "1px solid var(--c-border)",
                }}>
                    {[
                        { label: "Mascota",      value: rx.pet_name },
                        { label: "Veterinario",  value: `Dr. ${rx.veterinarian_name}` },
                        { label: "Fecha",        value: formatDate(rx.created_at) },
                    ].map(({ label, value }) => (
                        <div key={label}>
                            <p style={{ fontSize: "10px", fontWeight: "700", color: "var(--c-text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>{label}</p>
                            <p style={{ fontSize: "13px", fontWeight: "600", color: "var(--c-text)" }}>{value}</p>
                        </div>
                    ))}
                </div>

                {/* Medicamentos */}
                <p style={{ fontSize: "11px", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--c-text-3)", marginBottom: "10px" }}>
                    Medicamentos recetados
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "16px" }}>
                    {rx.items.map((item, i) => (
                        <div key={i} style={{
                            padding: "12px 14px",
                            background: "var(--c-surface)", border: "1px solid var(--c-border)",
                            borderLeft: "3px solid var(--c-primary)",
                            borderRadius: "var(--r-md)",
                        }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "6px" }}>
                                <p style={{ fontSize: "13.5px", fontWeight: "700", color: "var(--c-text)" }}>
                                    {item.product_name}
                                </p>
                                <span className="badge badge-default">
                                    {item.quantity} {item.product_unit}
                                </span>
                            </div>
                            <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
                                {item.dose && (
                                    <span style={{ fontSize: "12px", color: "var(--c-text-2)" }}>
                                        <span style={{ color: "var(--c-text-3)" }}>Dosis: </span>{item.dose}
                                    </span>
                                )}
                                {item.duration && (
                                    <span style={{ fontSize: "12px", color: "var(--c-text-2)" }}>
                                        <span style={{ color: "var(--c-text-3)" }}>Duración: </span>{item.duration}
                                    </span>
                                )}
                                {item.instructions && (
                                    <span style={{ fontSize: "12px", color: "var(--c-text-3)", fontStyle: "italic" }}>{item.instructions}</span>
                                )}
                            </div>
                        </div>
                    ))}
                </div>

                {/* Notas */}
                {rx.notes && (
                    <div style={{
                        padding: "12px 14px", background: "var(--c-warning-bg)",
                        border: "1px solid var(--c-warning-border)", borderRadius: "var(--r-md)",
                        marginBottom: "4px",
                    }}>
                        <p style={{ fontSize: "10px", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--c-warning-text)", marginBottom: "4px" }}>Notas</p>
                        <p style={{ fontSize: "13px", color: "var(--c-warning-text)", lineHeight: "1.6" }}>{rx.notes}</p>
                    </div>
                )}
            </div>

            <div className="modal-footer">
                <button
                    className="btn btn-primary btn-md"
                    style={{ flex: 1 }}
                    onClick={() => onDownload(rx.public_id)}
                    disabled={downloadingId === rx.public_id}
                >
                    {downloadingId === rx.public_id
                        ? <><Icon.Loader s={14} /> Generando…</>
                        : <><Icon.Download s={14} /> Descargar PDF</>}
                </button>
                <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={onClose}>
                    Cerrar
                </button>
            </div>
        </div>
    </div>
);

// ─── Prescription Card ─────────────────────────────────────────────────────────
const PrescriptionCard = ({ rx, downloadingId, canCreate, onView, onDownload, onDelete }) => {
    const d = new Date(rx.created_at);
    return (
        <div className="card card-hover" style={{ padding: "0", overflow: "hidden" }}>
            {/* Header de la card */}
            <div style={{
                display: "flex", alignItems: "flex-start", gap: "14px",
                padding: "14px 16px 12px",
                background: "var(--c-subtle)", borderBottom: "1px solid var(--c-border)",
            }}>
                {/* Bloque de fecha */}
                <div style={{
                    width: "44px", flexShrink: 0, textAlign: "center",
                    background: "var(--c-surface)", border: "1px solid var(--c-border)",
                    borderRadius: "var(--r-md)", padding: "6px 0",
                }}>
                    <p style={{ fontSize: "18px", fontWeight: "700", color: "var(--c-text)", lineHeight: "1" }}>{d.getDate()}</p>
                    <p style={{ fontSize: "9px", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--c-text-3)", marginTop: "2px" }}>
                        {MONTHS_SHORT[d.getMonth()]}
                    </p>
                </div>

                {/* Info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ fontSize: "15px", fontWeight: "700", color: "var(--c-text)", marginBottom: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {rx.pet_name}
                    </p>
                    <p style={{ fontSize: "12px", color: "var(--c-text-3)" }}>
                        Dr. {rx.veterinarian_name}
                    </p>
                </div>

                {/* Badge medicamentos */}
                <span className="badge badge-success" style={{ flexShrink: 0 }}>
                    <Icon.Pill s={11} />
                    {rx.items.length} med{rx.items.length !== 1 ? "s" : ""}
                </span>
            </div>

            {/* Chips de medicamentos */}
            {rx.items.length > 0 && (
                <div style={{ padding: "10px 16px 12px", display: "flex", gap: "6px", flexWrap: "wrap" }}>
                    {rx.items.map((item, i) => (
                        <span key={i} style={{
                            fontSize: "11.5px", fontWeight: "500",
                            padding: "3px 9px", borderRadius: "var(--r-full)",
                            background: "var(--c-surface)", border: "1px solid var(--c-border)",
                            color: "var(--c-text-2)",
                        }}>
                            {item.product_name}
                            <span style={{ color: "var(--c-text-3)" }}> · {item.quantity} {item.product_unit}</span>
                        </span>
                    ))}
                </div>
            )}

            {/* Acciones */}
            <div style={{
                display: "flex", gap: "6px", padding: "10px 16px",
                borderTop: "1px solid var(--c-subtle)",
            }}>
                <button className="btn btn-secondary btn-sm" onClick={() => onView(rx)} style={{ flex: 1 }}>
                    <Icon.Eye s={13} /> Ver detalle
                </button>
                <button
                    className="btn btn-primary btn-sm"
                    onClick={() => onDownload(rx.public_id)}
                    disabled={downloadingId === rx.public_id}
                    style={{ flex: 1 }}
                >
                    {downloadingId === rx.public_id
                        ? <><Icon.Loader s={13} /> …</>
                        : <><Icon.Download s={13} /> PDF</>}
                </button>
                {canCreate && (
                    <button
                        className="btn btn-danger btn-sm"
                        onClick={() => onDelete(rx.public_id)}
                        title="Eliminar receta"
                    >
                        <Icon.Trash s={13} />
                    </button>
                )}
            </div>
        </div>
    );
};

// ─── Main Page ─────────────────────────────────────────────────────────────────
const Prescriptions = () => {
    const { token, user, initializing } = useAuth();
    const confirm = useConfirm();
    const [searchParams] = useSearchParams();

    const [prescriptions, setPrescriptions]           = useState([]);
    const [pets, setPets]                             = useState([]);
    const [products, setProducts]                     = useState([]);
    const [medicalRecordsForPet, setMedicalRecords]   = useState([]);
    const [loading, setLoading]                       = useState(true);

    const [showModal, setShowModal]           = useState(false);
    const [showDetail, setShowDetail]         = useState(false);
    const [editing, setEditing]               = useState(null);
    const [viewing, setViewing]               = useState(null);
    const [selectedPet, setSelectedPet]       = useState("");
    const [lockedFromParams, setLocked]       = useState(false);
    const [formSeed, setFormSeed]             = useState({ medical_record: "", pet: "", notes: "", items: [] });
    const [downloadingId, setDownloadingId]   = useState(null);
    const [search, setSearch]                 = useState("");
    const [view, setView]                     = useState("table");
    const [filterSpecies, setFilterSpecies]   = useState("all");
    const [filterSex, setFilterSex]           = useState("all");
    const [filterAge, setFilterAge]           = useState("all");

    const canCreate = user?.role !== "ASSISTANT";

    const loadPrescriptions = useCallback(async () => {
        try {
            const params = {};
            if (selectedPet) params.pet = selectedPet;
            const data = await getPrescriptions(params);
            setPrescriptions(data);
        } catch { /* silencioso */ }
    }, [selectedPet]);

    const loadMedicalRecordsForPet = useCallback(async (petId) => {
        if (!petId || !token) { setMedicalRecords([]); return; }
        try {
            const data = await getMedicalRecords(token, { pet: petId });
            setMedicalRecords(data.results || data);
        } catch { setMedicalRecords([]); }
    }, [token]);

    useEffect(() => {
        if (!token) return;
        (async () => {
            setLoading(true);
            try {
                const [petsData, prodsData] = await Promise.all([
                    getPets(),
                    getProducts({ active: "true" }),
                ]);
                setPets(Array.isArray(petsData) ? petsData : (petsData.results || []));
                setProducts(Array.isArray(prodsData) ? prodsData : (prodsData.results || []));
                await loadPrescriptions();
            } finally { setLoading(false); }
        })();
    }, [token, loadPrescriptions]);

    useEffect(() => {
        if (token) loadPrescriptions();
    }, [token, loadPrescriptions]);

    useEffect(() => {
        const mrParam = searchParams.get("medical_record");
        const petParam = searchParams.get("pet");
        if (mrParam && petParam && token) {
            setLocked(true);
            setEditing(null);
            setFormSeed({ medical_record: mrParam, pet: petParam, notes: "", items: [] });
            setShowModal(true);
        }
    }, [searchParams, token]);

    const closeModal = () => {
        setShowModal(false); setEditing(null);
        setLocked(false); setMedicalRecords([]);
        setFormSeed({ medical_record: "", pet: "", notes: "", items: [] });
    };

    const handleFormSubmit = async (payload) => {
        if (editing) {
            await updatePrescription(editing.public_id, payload);
            toast.success("Receta actualizada");
        } else {
            await createPrescription(payload);
            toast.success("Receta creada");
        }
        await loadPrescriptions();
        closeModal();
    };

    const handleView = async (rx) => {
        try {
            const data = await getPrescription(rx.public_id);
            setViewing(data); setShowDetail(true);
        } catch { toast.error("Error al cargar la receta"); }
    };

    const handleDelete = async (id) => {
        const ok = await confirm({
            title: "Eliminar receta",
            message: "¿Eliminar esta receta? El registro médico asociado no se verá afectado.",
            confirmText: "Eliminar", dangerMode: true,
        });
        if (!ok) return;
        try {
            await deletePrescription(id);
            toast.success("Receta eliminada");
            loadPrescriptions();
        } catch { toast.error("Error al eliminar la receta"); }
    };

    const handleDownloadPDF = async (publicId) => {
        setDownloadingId(publicId);
        try {
            const { blob, contentDisposition } = await downloadPrescriptionPDF(publicId);
            const filename = extractFilename(contentDisposition, "receta.pdf");
            triggerDownload(blob, filename);
        } catch { toast.error("Error al generar el PDF"); }
        finally { setDownloadingId(null); }
    };

    // Join receta -> mascota por pet_public_id para reutilizar filtros de Mascotas
    const petByPublicId = useMemo(() => {
        const m = {};
        pets.forEach(p => { m[p.public_id] = p; });
        return m;
    }, [pets]);

    const filtered = prescriptions.filter(rx => {
        const q = search.toLowerCase();
        const matchSearch = !q ||
            rx.pet_name?.toLowerCase().includes(q) ||
            rx.veterinarian_name?.toLowerCase().includes(q) ||
            rx.items?.some(i => i.product_name?.toLowerCase().includes(q));

        const pet = petByPublicId[rx.pet_public_id];
        const matchSpecies = filterSpecies === "all" ||
            (filterSpecies === "caninos" && pet && isCanino(pet)) ||
            (filterSpecies === "felinos" && pet && isFelino(pet));
        const matchSex = filterSex === "all" || (pet && pet.sex === filterSex);
        const matchAge = filterAge === "all" || (pet && getAgeGroup(pet.birth_date) === filterAge);

        return matchSearch && matchSpecies && matchSex && matchAge;
    });

    const hasActiveFilters = search || selectedPet || filterSpecies !== "all" || filterSex !== "all" || filterAge !== "all";

    if (initializing || loading) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
                <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando recetas…</p>
            </div>
        );
    }

    return (
        <div>
            {/* Page header */}
            <div className="page-header">
                <div>
                    <h1 className="page-title">Recetas médicas</h1>
                    <p className="page-subtitle">{prescriptions.length} receta{prescriptions.length !== 1 ? "s" : ""} registrada{prescriptions.length !== 1 ? "s" : ""}</p>
                </div>
            </div>

            {/* Banner informativo */}
            <div style={{
                display: "flex", alignItems: "center", gap: "10px",
                padding: "10px 14px", marginBottom: "20px",
                background: "var(--c-info-bg)", border: "1px solid var(--c-info-border)",
                borderRadius: "var(--r-md)", fontSize: "13px", color: "var(--c-info-text)",
            }}>
                <Icon.Info s={15} />
                Las recetas se crean desde el{" "}
                <Link to="/medical-records" style={{ color: "var(--c-primary)", fontWeight: "600", textDecoration: "underline" }}>
                    historial clínico
                </Link>
                {" "}de cada consulta. Aquí puedes consultarlas y descargar el PDF.
            </div>

            {/* Filtros */}
            <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "20px", flexWrap: "wrap" }}>
                <div style={{ position: "relative", flex: "1 1 220px", maxWidth: "280px" }}>
                    <div style={{ position: "absolute", left: "10px", top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }}>
                        <Icon.Search s={14} c="var(--c-text-3)" />
                    </div>
                    <input
                        type="text"
                        className="input"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Mascota, medicamento, vet…"
                        style={{ paddingLeft: "32px" }}
                    />
                </div>
                <select
                    className="select-input"
                    value={selectedPet}
                    onChange={e => setSelectedPet(e.target.value)}
                    style={{ width: "auto", height: "36px", fontSize: "13px" }}
                >
                    <option value="">Todas las mascotas</option>
                    {pets.map(p => <option key={p.public_id} value={p.public_id}>{p.name}</option>)}
                </select>

                {/* Especie (reutilizado de Mascotas) */}
                <div style={{ display: "flex", gap: "3px", background: "var(--c-subtle)", padding: "3px", borderRadius: "var(--r-md)", border: "1px solid var(--c-border)" }}>
                    {[
                        { key: "all", label: "Todos" },
                        { key: "caninos", label: "Caninos", icon: <Icon.Dog s={13} /> },
                        { key: "felinos", label: "Felinos", icon: <Icon.Cat s={13} /> },
                    ].map(({ key, label, icon }) => (
                        <button
                            key={key}
                            onClick={() => setFilterSpecies(key)}
                            style={{
                                display: "inline-flex", alignItems: "center", gap: "5px",
                                height: "28px", padding: "0 10px",
                                borderRadius: "var(--r-sm)", border: "none", cursor: "pointer",
                                fontSize: "12.5px", fontWeight: "600", fontFamily: "inherit",
                                background: filterSpecies === key ? "var(--c-surface)" : "transparent",
                                color: filterSpecies === key ? "var(--c-text)" : "var(--c-text-2)",
                                boxShadow: filterSpecies === key ? "var(--shadow-xs)" : "none",
                                transition: "all var(--t)",
                            }}
                        >
                            {icon}
                            {label}
                        </button>
                    ))}
                </div>

                {/* Sexo (reutilizado de Mascotas) */}
                <select
                    className="select-input"
                    value={filterSex}
                    onChange={e => setFilterSex(e.target.value)}
                    style={{ width: "auto", height: "36px", fontSize: "13px" }}
                >
                    <option value="all">Todos los sexos</option>
                    <option value="male">Macho</option>
                    <option value="female">Hembra</option>
                    <option value="unknown">Sin especificar</option>
                </select>

                {/* Edad (reutilizado de Mascotas) */}
                <select
                    className="select-input"
                    value={filterAge}
                    onChange={e => setFilterAge(e.target.value)}
                    style={{ width: "auto", height: "36px", fontSize: "13px" }}
                >
                    <option value="all">Todas las edades</option>
                    <option value="cachorro">Cachorro (&lt;1 año)</option>
                    <option value="joven">Joven (1–3 años)</option>
                    <option value="adulto">Adulto (3–8 años)</option>
                    <option value="senior">Senior (&gt;8 años)</option>
                </select>

                {hasActiveFilters && (
                    <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => { setSearch(""); setSelectedPet(""); setFilterSpecies("all"); setFilterSex("all"); setFilterAge("all"); }}
                    >
                        <Icon.X s={12} /> Limpiar
                    </button>
                )}
                <div style={{ flex: 1 }} />
                {filtered.length !== prescriptions.length && (
                    <p style={{ fontSize: "12px", color: "var(--c-text-3)" }}>
                        {filtered.length} de {prescriptions.length}
                    </p>
                )}

                {/* View toggle */}
                <div style={{ display: "flex", gap: "3px", background: "var(--c-subtle)", padding: "3px", borderRadius: "var(--r-md)", border: "1px solid var(--c-border)" }}>
                    {[{ key: "table", I: Icon.Rows }, { key: "cards", I: Icon.Grid }].map(({ key, I }) => (
                        <button
                            key={key}
                            onClick={() => setView(key)}
                            style={{
                                width: "30px", height: "28px",
                                display: "flex", alignItems: "center", justifyContent: "center",
                                borderRadius: "var(--r-sm)", border: "none", cursor: "pointer",
                                background: view === key ? "var(--c-surface)" : "transparent",
                                color: view === key ? "var(--c-text)" : "var(--c-text-3)",
                                boxShadow: view === key ? "var(--shadow-xs)" : "none",
                                transition: "all var(--t)",
                            }}
                        >
                            <I s={15} />
                        </button>
                    ))}
                </div>
            </div>

            {/* Lista */}
            {filtered.length === 0 ? (
                <div className="empty-state">
                    <p className="empty-state-title">
                        {prescriptions.length === 0
                            ? "Aún no hay recetas registradas"
                            : "Ninguna receta coincide con el filtro"}
                    </p>
                    {prescriptions.length === 0 && (
                        <p className="empty-state-sub">
                            Crea la primera receta desde el{" "}
                            <Link to="/medical-records" style={{ color: "var(--c-primary)" }}>historial clínico</Link>.
                        </p>
                    )}
                </div>
            ) : view === "cards" ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "14px" }}>
                    {filtered.map(rx => (
                        <PrescriptionCard
                            key={rx.id}
                            rx={rx}
                            downloadingId={downloadingId}
                            canCreate={canCreate}
                            onView={handleView}
                            onDownload={handleDownloadPDF}
                            onDelete={handleDelete}
                        />
                    ))}
                </div>
            ) : (
                <div className="table-wrap">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Fecha</th>
                                <th>Mascota</th>
                                <th>Veterinario</th>
                                <th>Medicamentos</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map((rx) => (
                                <tr key={rx.id} style={{ cursor: "pointer" }} onClick={() => handleView(rx)}>
                                    <td style={{ whiteSpace: "nowrap", color: "var(--c-text-2)" }}>
                                        {formatDate(rx.created_at)}
                                    </td>
                                    <td>
                                        <span style={{ fontWeight: "600" }}>{rx.pet_name}</span>
                                    </td>
                                    <td style={{ color: "var(--c-text-2)" }}>
                                        Dr. {rx.veterinarian_name}
                                    </td>
                                    <td>
                                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                                            <span className="badge badge-success" style={{ flexShrink: 0 }}>
                                                <Icon.Pill s={11} />
                                                {rx.items.length}
                                            </span>
                                            <span style={{ fontSize: "12.5px", color: "var(--c-text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "320px" }}>
                                                {rx.items.map(i => i.product_name).join(", ") || "—"}
                                            </span>
                                        </div>
                                    </td>
                                    <td onClick={e => e.stopPropagation()}>
                                        <div style={{ display: "flex", gap: "6px" }}>
                                            <button className="btn btn-secondary btn-sm" onClick={() => handleView(rx)}>
                                                <Icon.Eye s={13} /> Ver
                                            </button>
                                            <button
                                                className="btn btn-primary btn-sm"
                                                onClick={() => handleDownloadPDF(rx.public_id)}
                                                disabled={downloadingId === rx.public_id}
                                            >
                                                {downloadingId === rx.public_id
                                                    ? <><Icon.Loader s={13} /> …</>
                                                    : <><Icon.Download s={13} /> PDF</>}
                                            </button>
                                            {canCreate && (
                                                <button
                                                    className="btn btn-danger btn-sm"
                                                    onClick={() => handleDelete(rx.public_id)}
                                                    title="Eliminar receta"
                                                >
                                                    <Icon.Trash s={13} />
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    <div className="table-footer">
                        {filtered.length} receta{filtered.length !== 1 ? "s" : ""}
                        {filtered.length !== prescriptions.length && ` de ${prescriptions.length} total`}
                    </div>
                </div>
            )}

            {/* Modal detalle */}
            {showDetail && viewing && (
                <DetailModal
                    prescription={viewing}
                    downloadingId={downloadingId}
                    onDownload={handleDownloadPDF}
                    onClose={() => { setShowDetail(false); setViewing(null); }}
                />
            )}

            {/* Modal formulario */}
            {showModal && (
                <PrescriptionForm
                    title={editing ? "Editar Receta" : "Nueva Receta"}
                    initialValue={formSeed}
                    pets={pets}
                    products={products}
                    medicalRecordsForPet={medicalRecordsForPet}
                    lockedPet={lockedFromParams}
                    lockedMedicalRecord={lockedFromParams}
                    submitLabel={editing ? "Guardar" : "Crear Receta"}
                    onPetChange={loadMedicalRecordsForPet}
                    onSubmit={handleFormSubmit}
                    onCancel={closeModal}
                />
            )}
        </div>
    );
};

export default Prescriptions;
