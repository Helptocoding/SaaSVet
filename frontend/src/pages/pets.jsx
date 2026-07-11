import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams, useLocation } from "react-router-dom";
import { getPets, getPet, getPetStats, createPet, updatePet, deletePet } from "../api/pets";
import { useConfirm } from "../components/useConfirm";
import { toast } from "sonner";
import { getMedicalRecords } from "../api/medicalRecords";
import { getVaccines } from "../api/vaccines";
import { getAppointments } from "../api/appointments";
import { getStatusBreakdown } from "../api/statusBreakdown";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import Pagination from "../components/Pagination";
import EmptyState from "../components/EmptyState";
import { DayPicker } from 'react-day-picker';
import { es } from 'react-day-picker/locale';
import 'react-day-picker/style.css';
import '../styles/day-picker.css';
import handleFormError from "../utils/handleFormError";
import { apiError } from "../utils/apiError";
import { toList } from "../utils/toList";
import { isCanino, isFelino, getAgeGroup } from "../utils/petFilters";

// ─── Constants ────────────────────────────────────────────────────────────────
const SEX_LABELS = { male: "Macho", female: "Hembra", unknown: "Desconocido" };

// Especie puede quedar "pendiente" ('') en alta manual / importación: la mascota
// SÍ tiene especie, solo no se capturó. Ver modules/patients.md.
const speciesLabel = (s) => (s && s.trim() ? s : "Pendiente");

const EMPTY_FORM = {
    name: "", species: "", breed: "", birth_date: "",
    sex: "unknown", color: "",
    owner: { name: "", phone: "" },
};

// ─── Age display (solo Mascotas) ────────────────────────────────────────────────
const calcAge = (bd) => {
    if (!bd) return null;
    const ms = Date.now() - new Date(bd).getTime();
    const y = Math.floor(ms / (365.25 * 24 * 3600 * 1000));
    const m = Math.floor(ms / (30.44 * 24 * 3600 * 1000));
    if (y >= 1) return `${y} año${y !== 1 ? "s" : ""}`;
    if (m >= 1) return `${m} mes${m !== 1 ? "es" : ""}`;
    return "< 1 mes";
};

// ─── Week range ───────────────────────────────────────────────────────────────
const getWeekRange = () => {
    const now = new Date();
    const start = new Date(now);
    start.setDate(now.getDate() - now.getDay());
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    end.setHours(23, 59, 59, 999);
    return { start, end };
};

// ─── Species Icon helper ──────────────────────────────────────────────────────
const SpeciesIcon = ({ pet, size = 20, color }) => {
    if (isCanino(pet)) return <Icon.Bone s={size} c={color} />;
    if (isFelino(pet)) return <Icon.Cat s={size} c={color} />;
    return <Icon.Paw s={size} c={color} />;
};

const speciesAccent = (pet) => isCanino(pet)
    ? { bg: "#dbeafe", icon: "#3b82f6", border: "#bfdbfe", text: "#1d4ed8" }
    : isFelino(pet)
    ? { bg: "#fce7f3", icon: "#ec4899", border: "#fbcfe8", text: "#be185d" }
    : { bg: "var(--c-primary-light)", icon: "var(--c-primary-dark)", border: "var(--sage-400)", text: "var(--c-primary-dark)" };

// ─── Birth Date Picker ────────────────────────────────────────────────────────
function BirthDatePicker({ value, onChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const today = new Date();

    const selected = value ? new Date(`${value}T12:00:00`) : undefined;
    const [month, setMonth] = useState(selected || today);

    useEffect(() => {
        const handleClickOutside = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleSelect = (date) => {
        if (!date) return;
        const str = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        onChange(str);
        setOpen(false);
    };

    const displayValue = selected
        ? selected.toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' })
        : '';

    const years = Array.from({ length: today.getFullYear() - 1949 }, (_, i) => today.getFullYear() - i);
    const monthNames = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

    const selectStyle = {
        background: "var(--c-subtle)", border: "1px solid var(--c-border)",
        borderRadius: "var(--r-md)", padding: "4px 8px",
        fontSize: "12px", fontFamily: "inherit", fontWeight: 600, color: "var(--c-text)",
        cursor: "pointer", outline: "none",
    };

    const navBtnStyle = {
        background: "none", border: "1px solid var(--c-border)",
        borderRadius: "var(--r-md)", padding: "4px 8px",
        cursor: "pointer", color: "var(--c-text-3)",
        fontSize: "13px", lineHeight: 1,
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "color 0.15s, background 0.15s",
    };

    return (
        <div ref={ref} style={{ position: 'relative' }}>
            <input
                className="input"
                readOnly
                value={displayValue}
                placeholder="Selecciona una fecha"
                onClick={() => setOpen(o => !o)}
                style={{ cursor: 'pointer' }}
            />
            {open && (
                <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 200 }}>
                    <div style={{
                        background: "var(--c-surface)", borderRadius: "var(--r-lg)",
                        border: "1px solid var(--c-border)", boxShadow: "var(--shadow-md)",
                        padding: "12px",
                    }}>
                        <div style={{ display: "flex", gap: "6px", alignItems: "center", marginBottom: "10px" }}>
                            <button
                                onClick={() => {
                                    const d = new Date(month);
                                    d.setMonth(d.getMonth() - 1);
                                    setMonth(d);
                                }}
                                style={navBtnStyle}
                                onMouseEnter={e => { e.currentTarget.style.color = "var(--c-text)"; e.currentTarget.style.background = "var(--c-hover)"; }}
                                onMouseLeave={e => { e.currentTarget.style.color = "var(--c-text-3)"; e.currentTarget.style.background = "none"; }}
                            >
                                ‹
                            </button>
                            <select
                                value={month.getMonth()}
                                onChange={e => setMonth(new Date(month.getFullYear(), Number(e.target.value)))}
                                style={{ ...selectStyle, flex: 1 }}
                            >
                                {monthNames.map((m, i) => (
                                    <option key={i} value={i}>{m}</option>
                                ))}
                            </select>
                            <select
                                value={month.getFullYear()}
                                onChange={e => setMonth(new Date(Number(e.target.value), month.getMonth()))}
                                style={{ ...selectStyle, width: 80 }}
                            >
                                {years.map(y => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                            <button
                                onClick={() => {
                                    const d = new Date(month);
                                    d.setMonth(d.getMonth() + 1);
                                    if (d <= today) setMonth(d);
                                }}
                                style={navBtnStyle}
                                onMouseEnter={e => { e.currentTarget.style.color = "var(--c-text)"; e.currentTarget.style.background = "var(--c-hover)"; }}
                                onMouseLeave={e => { e.currentTarget.style.color = "var(--c-text-3)"; e.currentTarget.style.background = "none"; }}
                            >
                                ›
                            </button>
                        </div>
                        <DayPicker
                            mode="single"
                            selected={selected}
                            onSelect={handleSelect}
                            disabled={{ after: today }}
                            month={month}
                            onMonthChange={setMonth}
                            locale={es}
                            components={{ Caption: () => null, Nav: () => null }}
                        />
                    </div>
                </div>
            )}
        </div>
    );
}

// ─── Pet Form Modal ───────────────────────────────────────────────────────────
const SPECIES_OPTIONS = [
    { value: "canino",  label: "Canino" },
    { value: "felino",  label: "Felino" },
    { value: "equino",  label: "Equino" },
    { value: "ave",     label: "Ave" },
    { value: "reptil",  label: "Reptil" },
    { value: "exótico", label: "Exótico" },
    { value: "otro",    label: "Otro" },
];
const COLOR_OPTIONS = [
    "Negro", "Blanco", "Café", "Gris", "Naranja", "Amarillo",
    "Atigrado", "Bicolor", "Tricolor", "Multicolor", "Otro",
];

const PetModal = ({ form, setForm, editing, onSubmit, onClose, formErrors }) => (
    <div className="modal-overlay">
        <div className="modal modal-md">
            <div className="modal-header">
                <h3>{editing ? "Editar Mascota" : "Nueva Mascota"}</h3>
                <button className="modal-close" onClick={onClose}><Icon.X s={16} /></button>
            </div>
            <div className="modal-body">
                <form onSubmit={onSubmit}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px" }}>
                        <div className="form-group" style={{ gridColumn: "1 / -1" }}>
                            <label className="form-label">NOMBRE *</label>
                            <input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Ej: Max" />
                        </div>
                    </div>
                    <p style={{ fontSize: "11.5px", color: "var(--c-text-3)", margin: "2px 0 12px" }}>
                        Lo demás es opcional — puedes completarlo después.
                    </p>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px" }}>
                        <div className="form-group">
                            <label className="form-label">ESPECIE</label>
                            <select className="select-input" value={form.species} onChange={e => setForm({ ...form, species: e.target.value })}>
                                <option value="">Pendiente</option>
                                {SPECIES_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">RAZA</label>
                            <input className="input" value={form.breed} onChange={e => setForm({ ...form, breed: e.target.value })} placeholder="Ej: Labrador" />
                        </div>
                        <div className="form-group">
                            <label className="form-label">FECHA DE NACIMIENTO</label>
                            <BirthDatePicker
                                value={form.birth_date}
                                onChange={(dateStr) => setForm({ ...form, birth_date: dateStr })}
                            />
                            {formErrors?.birth_date && (
                                <p style={{ color: "var(--c-danger-text)", fontSize: "11.5px", marginTop: "4px" }}>
                                    {Array.isArray(formErrors.birth_date) ? formErrors.birth_date[0] : formErrors.birth_date}
                                </p>
                            )}
                        </div>
                        <div className="form-group">
                            <label className="form-label">SEXO</label>
                            <select className="select-input" value={form.sex} onChange={e => setForm({ ...form, sex: e.target.value })}>
                                <option value="unknown">Desconocido</option>
                                <option value="male">Macho</option>
                                <option value="female">Hembra</option>
                            </select>
                        </div>
                        <div className="form-group" style={{ gridColumn: "1 / -1" }}>
                            <label className="form-label">COLOR</label>
                            <select className="select-input" value={form.color} onChange={e => setForm({ ...form, color: e.target.value })}>
                                <option value="">Sin especificar</option>
                                {COLOR_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
                            </select>
                        </div>
                    </div>
                    <hr className="divider" />
                    <p style={{ fontSize: "12.5px", fontWeight: "600", color: "var(--c-text-2)", marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Cliente
                    </p>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px" }}>
                        <div className="form-group">
                            <label className="form-label">NOMBRE *</label>
                            <input className="input" value={form.owner.name} onChange={e => setForm({ ...form, owner: { ...form.owner, name: e.target.value } })} placeholder="Nombre del cliente" />
                        </div>
                        <div className="form-group">
                            <label className="form-label">TELÉFONO *</label>
                            <input
                                className="input"
                                value={form.owner.phone}
                                onChange={e => setForm({ ...form, owner: { ...form.owner, phone: e.target.value.replace(/\D/g, '').slice(0, 10) } })}
                                placeholder="10 dígitos"
                                maxLength={10}
                                inputMode="numeric"
                            />
                        </div>
                    </div>
                </form>
            </div>
            <div className="modal-footer">
                <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={onSubmit}>
                    {editing ? "Guardar cambios" : "Registrar mascota"}
                </button>
                <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={onClose}>Cancelar</button>
            </div>
        </div>
    </div>
);

// ─── Pet Card ─────────────────────────────────────────────────────────────────
const PetCard = ({ pet, onSelect, onEdit, onDelete }) => {
    const age = calcAge(pet.birth_date);
    const ageGroup = getAgeGroup(pet.birth_date);
    const accent = speciesAccent(pet);

    const ageBadgeClass = ageGroup === "senior" ? "badge-warning"
        : ageGroup === "cachorro" ? "badge-info"
        : "badge-default";

    return (
        <div
            className="card card-hover"
            style={{ cursor: "pointer", padding: "18px 20px" }}
            onClick={onSelect}
        >
            {/* Header */}
            <div style={{ display: "flex", alignItems: "flex-start", gap: "12px", marginBottom: "14px" }}>
                <div style={{
                    width: "44px", height: "44px", borderRadius: "12px", flexShrink: 0,
                    background: accent.bg, border: `1px solid ${accent.border}`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                    <SpeciesIcon pet={pet} size={22} color={accent.icon} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h3 style={{ fontSize: "15px", fontWeight: "700", marginBottom: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {pet.name}
                    </h3>
                    <p style={{ fontSize: "12.5px", color: "var(--c-text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {speciesLabel(pet.species)}{pet.breed ? ` · ${pet.breed}` : ""}
                    </p>
                </div>
                {ageGroup && (
                    <span className={`badge ${ageBadgeClass}`} style={{ flexShrink: 0 }}>
                        {ageGroup.charAt(0).toUpperCase() + ageGroup.slice(1)}
                    </span>
                )}
            </div>

            {/* Data grid */}
            <div style={{ borderTop: "1px solid var(--c-subtle)", marginBottom: "14px", paddingTop: "12px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div>
                    <p style={{ fontSize: "11px", color: "var(--c-text-3)", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>Edad</p>
                    <p style={{ fontSize: "13.5px", color: "var(--c-text)", fontWeight: "500" }}>{age || "—"}</p>
                </div>
                <div>
                    <p style={{ fontSize: "11px", color: "var(--c-text-3)", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>Sexo</p>
                    <p style={{ fontSize: "13.5px", color: "var(--c-text)", fontWeight: "500" }}>
                        {pet.sex && pet.sex !== "unknown" ? SEX_LABELS[pet.sex] : "—"}
                    </p>
                </div>
                {pet.color && (
                    <div style={{ gridColumn: "1 / -1" }}>
                        <p style={{ fontSize: "11px", color: "var(--c-text-3)", fontWeight: "700", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>Color</p>
                        <p style={{ fontSize: "13.5px", color: "var(--c-text)", fontWeight: "500" }}>{pet.color}</p>
                    </div>
                )}
            </div>

            {/* Owner */}
            <div style={{
                display: "flex", alignItems: "center", gap: "8px",
                padding: "8px 10px", borderRadius: "var(--r-md)",
                background: "var(--c-subtle)", marginBottom: "12px",
            }}>
                <Icon.User s={14} c="var(--c-text-3)" />
                <div style={{ minWidth: 0 }}>
                    <p style={{ fontSize: "12.5px", fontWeight: "500", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {pet.owner?.name || "Sin cliente"}
                    </p>
                    {pet.owner?.phone && (
                        <p style={{ fontSize: "11.5px", color: "var(--c-text-3)" }}>{pet.owner.phone}</p>
                    )}
                </div>
            </div>

            {/* Actions */}
            <div style={{ display: "flex", gap: "6px" }} onClick={e => e.stopPropagation()}>
                <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={() => onEdit(pet)}>
                    <Icon.Edit s={13} /> Editar
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => onDelete(pet.public_id)}>
                    <Icon.Trash s={13} />
                </button>
            </div>
        </div>
    );
};

// ─── Quick Profile Panel ──────────────────────────────────────────────────────
const QuickPanel = ({ pet, records, appointments, loading, onClose, onEdit, navigate }) => {
    // Historial de vacunación real (VaccineRecord), no derivado de texto de consultas.
    // El hook debe correr siempre (antes de cualquier early return) para no violar
    // las reglas de hooks; se guarda contra pet nulo dentro del effect.
    const [vaccines, setVaccines] = useState([]);
    useEffect(() => {
        if (!pet?.public_id) { setVaccines([]); return; }
        let active = true;
        (async () => {
            try {
                const data = await getVaccines({ pet: pet.public_id });
                if (active) setVaccines(toList(data));
            } catch {
                /* informativo: silencioso */
            }
        })();
        return () => { active = false; };
    }, [pet?.public_id]);

    if (!pet) return null;

    const accent = speciesAccent(pet);
    const age = calcAge(pet.birth_date);
    const ageGroup = getAgeGroup(pet.birth_date);

    // Sort records by date desc
    const sortedRecords = [...records].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    // VaccineRecord ya viene ordenado por -application_date desde el backend.
    const lastVaccine = vaccines[0] || null;

    // Upcoming scheduled appointments
    const now = new Date();
    const upcoming = appointments
        .filter(a => a.status === "scheduled" && new Date(a.date) >= now)
        .sort((a, b) => new Date(a.date) - new Date(b.date))
        .slice(0, 2);

    // Fechas date-only ("YYYY-MM-DD", p.ej. VaccineRecord.application_date) se
    // parsean como local para no desfasar un día en tz negativa (MX = UTC-6).
    const fmtDate = (ds) => {
        if (!ds) return "";
        const d = /^\d{4}-\d{2}-\d{2}$/.test(ds) ? new Date(`${ds}T00:00:00`) : new Date(ds);
        return d.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });
    };
    const fmtWeekday = (ds) => new Date(ds).toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });

    return (
        <>
            {/* Backdrop */}
            <div
                onClick={onClose}
                style={{
                    position: "fixed", inset: 0,
                    background: "rgba(15,23,42,0.28)",
                    zIndex: 900,
                    animation: "fadeIn 0.15s ease",
                }}
            />

            {/* Panel */}
            <div style={{
                position: "fixed", top: 0, right: 0, bottom: 0,
                width: "390px", maxWidth: "100vw",
                background: "var(--c-surface)",
                borderLeft: "1px solid var(--c-border)",
                zIndex: 910,
                display: "flex", flexDirection: "column",
                boxShadow: "-8px 0 40px rgba(0,0,0,0.10)",
                animation: "slideInRight 0.22s ease",
            }}>

                {/* Header */}
                <div style={{
                    padding: "20px 22px 16px",
                    borderBottom: "1px solid var(--c-border)",
                    display: "flex", alignItems: "flex-start", gap: "14px",
                    flexShrink: 0,
                }}>
                    <div style={{
                        width: "52px", height: "52px", borderRadius: "14px", flexShrink: 0,
                        background: accent.bg, border: `1px solid ${accent.border}`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                        <SpeciesIcon pet={pet} size={26} color={accent.icon} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <h3 style={{ fontSize: "17px", fontWeight: "700", marginBottom: "3px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {pet.name}
                        </h3>
                        <p style={{ fontSize: "12.5px", color: "var(--c-text-2)", marginBottom: "7px" }}>
                            {speciesLabel(pet.species)}{pet.breed ? ` · ${pet.breed}` : ""}
                        </p>
                        <div style={{ display: "flex", gap: "5px", flexWrap: "wrap" }}>
                            {age && <span className="badge badge-default">{age}</span>}
                            {pet.sex && pet.sex !== "unknown" && (
                                <span className="badge badge-default">{SEX_LABELS[pet.sex]}</span>
                            )}
                            {ageGroup && (
                                <span className={`badge ${ageGroup === "senior" ? "badge-warning" : ageGroup === "cachorro" ? "badge-info" : "badge-default"}`}>
                                    {ageGroup.charAt(0).toUpperCase() + ageGroup.slice(1)}
                                </span>
                            )}
                        </div>
                    </div>
                    <button
                        className="btn btn-ghost"
                        style={{ padding: "6px", flexShrink: 0 }}
                        onClick={onClose}
                    >
                        <Icon.X s={15} />
                    </button>
                </div>

                {/* Body */}
                <div style={{ flex: 1, overflowY: "auto", padding: "20px 22px" }}>
                    {loading ? (
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "120px" }}>
                            <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando datos...</p>
                        </div>
                    ) : (
                        <>
                            {/* Cliente */}
                            <section style={{ marginBottom: "22px" }}>
                                <p style={sectionTitle}>Cliente</p>
                                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                    <div style={{
                                        width: "36px", height: "36px", borderRadius: "50%", flexShrink: 0,
                                        background: "var(--c-subtle)", border: "1px solid var(--c-border)",
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                    }}>
                                        <Icon.User s={16} c="var(--c-text-2)" />
                                    </div>
                                    <div>
                                        <p style={{ fontWeight: "600", fontSize: "13.5px" }}>{pet.owner?.name || "—"}</p>
                                        {pet.owner?.phone && (
                                            <p style={{ fontSize: "12px", color: "var(--c-text-2)", display: "flex", alignItems: "center", gap: "4px", marginTop: "2px" }}>
                                                <Icon.Phone s={12} c="var(--c-text-3)" />
                                                {pet.owner.phone}
                                            </p>
                                        )}
                                    </div>
                                </div>
                            </section>

                            {/* Datos físicos */}
                            {(pet.color || pet.birth_date) && (
                                <section style={{ marginBottom: "22px" }}>
                                    <p style={sectionTitle}>Datos físicos</p>
                                    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                        {pet.birth_date && (
                                            <div className="info-row" style={{ marginBottom: 0 }}>
                                                <span className="info-row-label">Fecha nac.</span>
                                                <span className="info-row-value">
                                                    {new Date(pet.birth_date).toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" })}
                                                </span>
                                            </div>
                                        )}
                                        {pet.color && (
                                            <div className="info-row" style={{ marginBottom: 0 }}>
                                                <span className="info-row-label">Color</span>
                                                <span className="info-row-value">{pet.color}</span>
                                            </div>
                                        )}
                                    </div>
                                </section>
                            )}

                            {/* Próximas citas */}
                            {upcoming.length > 0 && (
                                <section style={{ marginBottom: "22px" }}>
                                    <p style={sectionTitle}>Próximas citas</p>
                                    <div style={{ display: "flex", flexDirection: "column", gap: "7px" }}>
                                        {upcoming.map(appt => (
                                            <div key={appt.id} style={{
                                                display: "flex", alignItems: "flex-start", gap: "10px",
                                                padding: "10px 12px", borderRadius: "var(--r-md)",
                                                background: "var(--c-info-bg)", border: "1px solid var(--c-info-border)",
                                            }}>
                                                <Icon.Calendar s={14} c="var(--c-info-text)" />
                                                <div>
                                                    <p style={{ fontWeight: "600", fontSize: "12.5px", color: "var(--c-info-text)" }}>
                                                        {fmtWeekday(appt.date)}
                                                    </p>
                                                    <p style={{ fontSize: "11.5px", color: "var(--c-text-2)", marginTop: "1px" }}>
                                                        {appt.start_time?.slice(0, 5)}{appt.veterinarian_name ? ` · Dr. ${appt.veterinarian_name}` : ""}
                                                        {appt.reason ? ` · ${appt.reason}` : ""}
                                                    </p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </section>
                            )}

                            {/* Historial reciente */}
                            <section style={{ marginBottom: "22px" }}>
                                <p style={sectionTitle}>Historial reciente</p>
                                {sortedRecords.length === 0 ? (
                                    <p style={{ fontSize: "12.5px", color: "var(--c-text-3)", fontStyle: "italic" }}>Sin consultas registradas</p>
                                ) : (
                                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                        {sortedRecords.slice(0, 3).map(rec => (
                                            <div key={rec.id} style={{
                                                padding: "10px 12px", borderRadius: "var(--r-md)",
                                                border: "1px solid var(--c-border)", background: "var(--c-subtle)",
                                            }}>
                                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                                                    <span style={{ fontSize: "11.5px", fontWeight: "600", color: "var(--c-text-2)" }}>
                                                        {fmtDate(rec.created_at)}
                                                    </span>
                                                    {rec.veterinarian_name && (
                                                        <span style={{ fontSize: "11px", color: "var(--c-text-3)" }}>Dr. {rec.veterinarian_name}</span>
                                                    )}
                                                </div>
                                                <p style={{ fontSize: "12.5px", color: "var(--c-text)", lineHeight: "1.45" }}>
                                                    {rec.diagnosis?.length > 75 ? rec.diagnosis.slice(0, 75) + "…" : rec.diagnosis}
                                                </p>
                                                {rec.weight && (
                                                    <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>{rec.weight} kg</p>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </section>

                            {/* Estado de vacunas */}
                            <section style={{ marginBottom: "4px" }}>
                                <p style={sectionTitle}>Estado de vacunas</p>
                                {lastVaccine ? (
                                    <div style={{
                                        display: "flex", alignItems: "center", gap: "10px",
                                        padding: "10px 12px", borderRadius: "var(--r-md)",
                                        background: "var(--c-success-bg)", border: "1px solid var(--c-success-border)",
                                    }}>
                                        <Icon.Syringe s={14} c="var(--c-success-text)" />
                                        <div>
                                            <p style={{ fontSize: "12.5px", fontWeight: "600", color: "var(--c-success-text)" }}>{lastVaccine.vaccine_name}</p>
                                            <p style={{ fontSize: "11.5px", color: "var(--c-success-text)", opacity: 0.85, marginTop: "1px" }}>
                                                {fmtDate(lastVaccine.application_date)}
                                                {lastVaccine.applied_by_name ? ` · ${lastVaccine.applied_by_name}` : ""}
                                            </p>
                                        </div>
                                    </div>
                                ) : sortedRecords.length === 0 ? (
                                    <p style={{ fontSize: "12.5px", color: "var(--c-text-3)", fontStyle: "italic" }}>Sin historial clínico registrado</p>
                                ) : (
                                    <div style={{
                                        display: "flex", alignItems: "center", gap: "10px",
                                        padding: "10px 12px", borderRadius: "var(--r-md)",
                                        background: "var(--c-warning-bg)", border: "1px solid var(--c-warning-border)",
                                    }}>
                                        <Icon.AlertTriangle s={14} c="var(--c-warning-text)" />
                                        <p style={{ fontSize: "12.5px", color: "var(--c-warning-text)" }}>
                                            Sin registros de vacunación en el historial
                                        </p>
                                    </div>
                                )}
                            </section>
                        </>
                    )}
                </div>

                {/* Footer */}
                <div style={{
                    padding: "14px 22px", borderTop: "1px solid var(--c-border)",
                    display: "flex", gap: "8px", flexShrink: 0,
                }}>
                    <button
                        className="btn btn-primary btn-md"
                        style={{ flex: 1 }}
                        onClick={() => { onClose(); navigate(`/pets/${pet.public_id}`); }}
                    >
                        Ver ficha completa
                        <Icon.ChevronRight s={14} />
                    </button>
                    <button
                        className="btn btn-secondary btn-md"
                        onClick={() => { onClose(); onEdit(pet); }}
                    >
                        <Icon.Edit s={14} />
                        Editar
                    </button>
                </div>
            </div>
        </>
    );
};

// Shared section title style
const sectionTitle = {
    fontSize: "11px", fontWeight: "700", color: "var(--c-text-3)",
    textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "10px",
};

// ─── Main Component ───────────────────────────────────────────────────────────
const Pets = () => {
    const { token, initializing, can, user } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const confirm = useConfirm();

    // ─── Lista server-driven (paginación + filtros server-side) ───
    const [pets, setPets] = useState([]);        // solo la página actual
    const [count, setCount] = useState(0);       // total filtrado (backend)
    const [loading, setLoading] = useState(true);   // carga inicial
    const [fetching, setFetching] = useState(false); // cambio de página/filtro
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(25);
    const [reloadKey, setReloadKey] = useState(0);  // fuerza refetch tras mutación

    // Stats de TODA la clínica (no de la página) — alimentan los stat-cards.
    const [stats, setStats] = useState({ total: 0, caninos: 0, felinos: 0 });
    const [weekApptCount, setWeekApptCount] = useState(0);

    // View
    const [view, setView] = useState("cards");

    // Filtros (todos server-side)
    const [search, setSearch] = useState("");
    const [debouncedSearch, setDebouncedSearch] = useState("");
    const [filterSpecies, setFilterSpecies] = useState("all");
    const [filterSex, setFilterSex] = useState("all");
    const [filterAge, setFilterAge] = useState("all");

    // Form modal
    const [showModal, setShowModal] = useState(false);
    const [editing, setEditing] = useState(null);
    const [form, setForm] = useState(EMPTY_FORM);
    const [formErrors, setFormErrors] = useState({});

    // Quick panel
    const [selectedPet, setSelectedPet] = useState(null);
    const [panelRecords, setPanelRecords] = useState([]);
    const [panelAppts, setPanelAppts] = useState([]);
    const [panelLoading, setPanelLoading] = useState(false);

    const hasActiveFilters = search || filterSpecies !== "all" || filterSex !== "all" || filterAge !== "all";

    // Cambiar un filtro siempre vuelve a la página 1 (un solo render).
    const setFilter = (setter, value) => { setter(value); setPage(1); };

    // Debounce de la búsqueda remota (350ms) → resetea a la página 1.
    useEffect(() => {
        const t = setTimeout(() => {
            setDebouncedSearch(search.trim());
            setPage(1);
        }, 350);
        return () => clearTimeout(t);
    }, [search]);

    // Fetch de la página actual ante cualquier cambio de página/tamaño/filtro.
    useEffect(() => {
        if (!token) return;
        let cancelled = false;
        const params = { page, page_size: pageSize };
        if (debouncedSearch) params.search = debouncedSearch;
        if (filterSpecies !== "all") params.species = filterSpecies;
        if (filterSex !== "all") params.sex = filterSex;
        if (filterAge !== "all") params.age = filterAge;

        // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount idiomático
        setFetching(true);
        getPets(params)
            .then(data => {
                if (cancelled) return;
                setPets(toList(data));
                setCount(typeof data?.count === "number" ? data.count : toList(data).length);
            })
            .catch(err => { if (!cancelled) toast.error(apiError(err, "No se pudieron cargar las mascotas")); })
            .finally(() => { if (!cancelled) { setLoading(false); setFetching(false); } });
        return () => { cancelled = true; };
    }, [token, page, pageSize, debouncedSearch, filterSpecies, filterSex, filterAge, reloadKey]);

    const loadStats = () => {
        // Falla suave: si /stats/ no responde, los cards muestran 0 (no bloquea la lista).
        getPetStats().then(setStats).catch(() => {});
    };
    useEffect(() => { if (token) loadStats(); }, [token]);

    // Citas de la semana (solo conteo) vía status-breakdown — sin traer filas.
    useEffect(() => {
        if (!token) return;
        const { start, end } = getWeekRange();
        getStatusBreakdown({ from: start, to: end })
            .then(d => {
                const totals = d?.totals || {};
                setWeekApptCount(Object.values(totals).reduce((a, b) => a + (b || 0), 0));
            })
            .catch(() => setWeekApptCount(0));
    }, [token]);

    // Refetch de la página actual + stats tras crear/editar/eliminar.
    const reload = () => { setReloadKey(k => k + 1); loadStats(); };

    // Rango "Mostrando X–Y de N".
    const fromRow = count === 0 ? 0 : (page - 1) * pageSize + 1;
    const toRow = Math.min(page * pageSize, count);

    // ─── Panel ────────────────────────────────────────────────
    const openPanel = async (pet) => {
        setSelectedPet(pet);
        setPanelLoading(true);
        setPanelRecords([]);
        setPanelAppts([]);
        try {
            const [records, appts] = await Promise.all([
                getMedicalRecords(token, { pet: pet.public_id }),
                getAppointments(token, { pet: pet.public_id }).catch(() => []),
            ]);
            setPanelRecords(Array.isArray(records) ? records : (records.results || []));
            setPanelAppts(Array.isArray(appts) ? appts : (appts.results || []));
        } catch (err) {
            console.error(apiError(err));
        } finally {
            setPanelLoading(false);
        }
    };

    const closePanel = () => {
        setSelectedPet(null);
        setPanelRecords([]);
        setPanelAppts([]);
    };

    // ─── CRUD ─────────────────────────────────────────────────
    const handleSubmit = async (e) => {
        e.preventDefault();
        setFormErrors({});
        const nameRe = /^[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ' -]+$/;
        if (!form.name.trim()) { toast.error("El nombre es obligatorio"); return; }
        if (!nameRe.test(form.name.trim())) { toast.error("El nombre solo puede contener letras, números, espacios, acentos y guiones"); return; }
        // Especie y fecha de nacimiento son OPCIONALES (datos mínimos): solo se
        // valida la fecha cuando el usuario la captura. Ver modules/patients.md.
        if (form.birth_date && new Date(form.birth_date) > new Date()) { toast.error("La fecha de nacimiento no puede ser en el futuro"); return; }
        if (!form.owner.name.trim()) { toast.error("El nombre del cliente es obligatorio"); return; }
        if (!nameRe.test(form.owner.name.trim())) { toast.error("El nombre del cliente solo puede contener letras, espacios y acentos"); return; }
        if (!form.owner.phone || form.owner.phone.length !== 10) { toast.error("El teléfono debe tener exactamente 10 dígitos"); return; }
        const payload = { ...form, birth_date: form.birth_date || null };
        try {
            const p = editing ? updatePet(token, editing.public_id, payload) : createPet(token, payload);
            await p;
            toast.success('Mascota guardada correctamente');
            setForm(EMPTY_FORM);
            setEditing(null);
            setFormErrors({});
            setShowModal(false);
            // Flujo de onboarding: si se llegó desde el FirstRunAssistant, volver al
            // dashboard automáticamente (sin intervención) y disparar la celebración.
            if (!editing && location.state?.fromOnboarding) {
                navigate("/", { state: { onboardingStep: "has_patients" } });
                return;
            }
            reload();
        } catch (err) {
            handleFormError(err, setFormErrors);
        }
    };

    const handleEdit = (pet) => {
        setEditing(pet);
        setForm({
            name: pet.name,
            species: pet.species,
            breed: pet.breed || "",
            birth_date: pet.birth_date || "",
            sex: pet.sex || "unknown",
            color: pet.color || "",
            owner: { name: pet.owner?.name || "", phone: pet.owner?.phone || "" },
        });
        setShowModal(true);
    };

    // Deep-link de "Completar datos" desde la ficha (?edit=<public_id>): abre el
    // modal de edición de esa mascota (puede no estar en la página actual → se
    // pide por public_id). Se limpia el param para no reabrir al refrescar.
    useEffect(() => {
        const editId = searchParams.get("edit");
        if (!token || !editId) return;
        getPet(editId).then(handleEdit).catch(() => {});
        const next = new URLSearchParams(searchParams);
        next.delete("edit");
        setSearchParams(next, { replace: true });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, searchParams]);

    const handleDelete = async (id) => {
        const ok = await confirm({
            title: "Eliminar mascota",
            message: "Se eliminará la mascota y todo su historial clínico. Esta acción no se puede deshacer.",
            confirmText: "Eliminar",
            dangerMode: true,
        });
        if (!ok) return;
        try {
            await toast.promise(deletePet(token, id), {
                loading: 'Eliminando...',
                success: 'Mascota eliminada',
                error: 'Error al eliminar la mascota'
            });
            if (selectedPet?.public_id === id) closePanel();
            reload();
        } catch {
            // Manejado por toast
        }
    };

    const handleClose = () => {
        setShowModal(false);
        setEditing(null);
        setForm(EMPTY_FORM);
        setFormErrors({});
    };

    if (initializing || loading) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
                <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</p>
            </div>
        );
    }

    return (
        <div>
            {/* Page header */}
            <div className="page-header">
                <div>
                    <h1 className="page-title">Mascotas</h1>
                    <p className="page-subtitle">{stats.total} registrada{stats.total !== 1 ? "s" : ""}</p>
                </div>
                <button
                    className="btn btn-primary btn-md"
                    onClick={() => { setEditing(null); setForm(EMPTY_FORM); ; setShowModal(true); }}
                >
                    + Nueva Mascota
                </button>
            </div>

            {/* Metrics */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "14px", marginBottom: "24px" }}>
                {/* Total */}
                <div className="stat-card" style={{ borderTop: "3px solid var(--c-primary)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                        <p className="stat-label">Total mascotas</p>
                        <div style={iconBox("var(--c-primary-light)")}>
                            <Icon.Paw s={16} c="var(--c-primary-dark)" />
                        </div>
                    </div>
                    <p className="stat-value" style={{ color: "var(--c-primary-dark)" }}>{stats.total}</p>
                    <p className="stat-sub">registradas en la clínica</p>
                </div>

                {/* Caninos */}
                <div className="stat-card" style={{ borderTop: "3px solid #3b82f6" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                        <p className="stat-label">Caninos</p>
                        <div style={iconBox("#dbeafe")}>
                            <Icon.Dog s={16} c="#3b82f6" />
                        </div>
                    </div>
                    <p className="stat-value" style={{ color: "#1d4ed8" }}>{stats.caninos}</p>
                    <p className="stat-sub">
                        {stats.total > 0 ? Math.round(stats.caninos / stats.total * 100) : 0}% del total
                    </p>
                </div>

                {/* Felinos */}
                <div className="stat-card" style={{ borderTop: "3px solid #ec4899" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                        <p className="stat-label">Felinos</p>
                        <div style={iconBox("#fce7f3")}>
                            <Icon.Cat s={16} c="#ec4899" />
                        </div>
                    </div>
                    <p className="stat-value" style={{ color: "#be185d" }}>{stats.felinos}</p>
                    <p className="stat-sub">
                        {stats.total > 0 ? Math.round(stats.felinos / stats.total * 100) : 0}% del total
                    </p>
                </div>

                {/* Citas esta semana */}
                <div className="stat-card" style={{ borderTop: "3px solid var(--c-warning-text)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                        <p className="stat-label">Citas esta semana</p>
                        <div style={iconBox("var(--c-warning-bg)")}>
                            <Icon.Calendar s={16} c="var(--c-warning-text)" />
                        </div>
                    </div>
                    <p className="stat-value" style={{ color: "var(--c-warning-text)" }}>{weekApptCount}</p>
                    <p className="stat-sub">
                        cita{weekApptCount !== 1 ? "s" : ""} en la semana
                    </p>
                </div>
            </div>

            {/* Filter bar */}
            <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap", marginBottom: "16px" }}>
                {/* Search */}
                <div className="searchBar" style={{ flex: "1 1 220px", maxWidth: "300px" }}>
                    <Icon.Search s={14} c="var(--c-text-3)" />
                    <input
                        type="text"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Nombre, raza, especie, cliente..."
                    />
                </div>

                {/* Species chips */}
                <div style={{ display: "flex", gap: "3px", background: "var(--c-subtle)", padding: "3px", borderRadius: "var(--r-md)", border: "1px solid var(--c-border)" }}>
                    {[
                        { key: "all", label: "Todos" },
                        { key: "caninos", label: "Caninos", icon: <Icon.Dog s={13} /> },
                        { key: "felinos", label: "Felinos", icon: <Icon.Cat s={13} /> },
                    ].map(({ key, label, icon }) => (
                        <button
                            key={key}
                            onClick={() => setFilter(setFilterSpecies, key)}
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

                {/* Sex select */}
                <select
                    className="select-input"
                    value={filterSex}
                    onChange={e => setFilter(setFilterSex, e.target.value)}
                    style={{ width: "auto", height: "36px", fontSize: "13px" }}
                >
                    <option value="all">Todos los sexos</option>
                    <option value="male">Macho</option>
                    <option value="female">Hembra</option>
                    <option value="unknown">Sin especificar</option>
                </select>

                {/* Age select */}
                <select
                    className="select-input"
                    value={filterAge}
                    onChange={e => setFilter(setFilterAge, e.target.value)}
                    style={{ width: "auto", height: "36px", fontSize: "13px" }}
                >
                    <option value="all">Todas las edades</option>
                    <option value="cachorro">Cachorro (&lt;1 año)</option>
                    <option value="joven">Joven (1–3 años)</option>
                    <option value="adulto">Adulto (3–8 años)</option>
                    <option value="senior">Senior (&gt;8 años)</option>
                </select>

                {/* Clear */}
                {hasActiveFilters && (
                    <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => { setSearch(""); setFilterSpecies("all"); setFilterSex("all"); setFilterAge("all"); setPage(1); }}
                    >
                        <Icon.X s={12} />
                        Limpiar
                    </button>
                )}

                <div style={{ flex: 1 }} />

                {/* View toggle */}
                <div style={{ display: "flex", gap: "3px", background: "var(--c-subtle)", padding: "3px", borderRadius: "var(--r-md)", border: "1px solid var(--c-border)" }}>
                    {[{ key: "cards", I: Icon.Grid }, { key: "table", I: Icon.Rows }].map(({ key, I }) => (
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

            {/* Results count + page size */}
            {count > 0 && (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", marginBottom: "12px" }}>
                    <p style={{ fontSize: "12.5px", color: "var(--c-text-3)" }}>
                        Mostrando {fromRow}–{toRow} de {count} mascota{count !== 1 ? "s" : ""}
                        {hasActiveFilters && " (filtradas)"}
                    </p>
                    <label style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "12.5px", color: "var(--c-text-3)" }}>
                        Por página
                        <select
                            className="select-input"
                            value={pageSize}
                            onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
                            style={{ width: "auto", height: "32px", fontSize: "13px" }}
                        >
                            <option value={25}>25</option>
                            <option value={50}>50</option>
                            <option value={100}>100</option>
                        </select>
                    </label>
                </div>
            )}

            {/* Empty state */}
            {pets.length === 0 && !fetching && (
                hasActiveFilters ? (
                    <EmptyState
                        title="No se encontraron mascotas con esos filtros"
                        body="Prueba con otro término de búsqueda o limpia los filtros."
                    />
                ) : (
                    <EmptyState
                        icon={Icon.PawPrint}
                        title="Todavía no tienes pacientes"
                        body="Agrega tus pacientes manualmente o importa tu archivo anterior."
                        actions={[
                            can("import.create") && !user?.is_demo
                                ? { label: "Importar Excel", onClick: () => navigate("/imports"), variant: "secondary" }
                                : null,
                            can("patient.create")
                                ? { label: "Agregar paciente", onClick: () => { setEditing(null); setForm(EMPTY_FORM); setShowModal(true); }, variant: "primary" }
                                : null,
                        ]}
                    />
                )
            )}

            {/* Cards view */}
            {view === "cards" && pets.length > 0 && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(272px, 1fr))", gap: "14px" }}>
                    {pets.map(pet => (
                        <PetCard
                            key={pet.public_id}
                            pet={pet}
                            onSelect={() => openPanel(pet)}
                            onEdit={handleEdit}
                            onDelete={handleDelete}
                        />
                    ))}
                </div>
            )}

            {/* Table view */}
            {view === "table" && pets.length > 0 && (
                <div className="table-wrap">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Mascota</th>
                                <th>Especie / Raza</th>
                                <th>Cliente</th>
                                <th>Edad · Sexo</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {pets.map((pet) => {
                                const accent = speciesAccent(pet);
                                return (
                                    <tr key={pet.public_id} style={{ cursor: "pointer" }} onClick={() => openPanel(pet)}>
                                        <td>
                                            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                                <div style={{
                                                    width: "34px", height: "34px", borderRadius: "8px", flexShrink: 0,
                                                    background: accent.bg, border: `1px solid ${accent.border}`,
                                                    display: "flex", alignItems: "center", justifyContent: "center",
                                                }}>
                                                    <SpeciesIcon pet={pet} size={17} color={accent.icon} />
                                                </div>
                                                <div>
                                                    <span style={{ fontWeight: "600" }}>{pet.name}</span>
                                                    {pet.color && <span style={{ display: "block", fontSize: "12px", color: "var(--c-text-3)" }}>{pet.color}</span>}
                                                </div>
                                            </div>
                                        </td>
                                        <td>
                                            {speciesLabel(pet.species)}
                                            {pet.breed && <span style={{ color: "var(--c-text-3)" }}> · {pet.breed}</span>}
                                        </td>
                                        <td>
                                            <span>{pet.owner?.name || "—"}</span>
                                            {pet.owner?.phone && <span style={{ display: "block", fontSize: "12px", color: "var(--c-text-3)" }}>{pet.owner.phone}</span>}
                                        </td>
                                        <td style={{ color: "var(--c-text-2)" }}>
                                            {calcAge(pet.birth_date) || "—"}
                                            {pet.sex && pet.sex !== "unknown" && (
                                                <span style={{ color: "var(--c-text-3)" }}> · {SEX_LABELS[pet.sex]}</span>
                                            )}
                                        </td>
                                        <td onClick={e => e.stopPropagation()}>
                                            <div style={{ display: "flex", gap: "6px" }}>
                                                <button className="btn btn-secondary btn-sm" onClick={() => handleEdit(pet)}>
                                                    <Icon.Edit s={13} /> Editar
                                                </button>
                                                <button className="btn btn-danger btn-sm" onClick={() => handleDelete(pet.public_id)}>
                                                    <Icon.Trash s={13} />
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                    <div className="table-footer">
                        Mostrando {fromRow}–{toRow} de {count} mascota{count !== 1 ? "s" : ""}
                    </div>
                </div>
            )}

            {/* Paginación (server-side) — se auto-oculta si todo cabe en una página */}
            {pets.length > 0 && (
                <Pagination page={page} count={count} pageSize={pageSize} onPage={setPage} fetching={fetching} />
            )}

            {/* Quick profile panel */}
            {selectedPet && (
                <QuickPanel
                    pet={selectedPet}
                    records={panelRecords}
                    appointments={panelAppts}
                    loading={panelLoading}
                    onClose={closePanel}
                    onEdit={handleEdit}
                    navigate={navigate}
                />
            )}

            {/* Form modal */}
            {showModal && (
                <PetModal
                    form={form}
                    setForm={setForm}
                    editing={editing}
                    onSubmit={handleSubmit}
                    onClose={handleClose}
                    formErrors={formErrors}
                />
            )}
        </div>
    );
};

// Small icon box helper
const iconBox = (bg) => ({
    width: "32px", height: "32px", borderRadius: "8px",
    background: bg, display: "flex", alignItems: "center", justifyContent: "center",
    flexShrink: 0,
});

export default Pets;
