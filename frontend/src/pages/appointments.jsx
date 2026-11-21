import { useEffect, useState, useRef, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useConfirm } from "../components/useConfirm";
import { isAppointmentChanged, appointmentChangedCurrent } from "../utils/apiError";
import { statusLabel, statusBadgeClass } from "../utils/appointmentStatus";
import { toast } from "sonner";
import {
    getAppointments, createAppointment,
    updateAppointment, updateAppointmentStatus, walkInAppointment,
    getAppointmentHistory, assignPatient, createAppointmentWithPatient,
} from "../api/appointments";
import { getOrgSettings } from "../api/organizations";
import { getStaff } from "../api/staff";
import EntitySearch from "../components/EntitySearch";
import { searchPets } from "../api/lookups";
import { renderPetOption, petOptionLabel } from "../components/lookupOptions";
import QuickPatientForm from "../components/QuickPatientForm";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import ViewModeButtonGroup from "../components/ViewModeButtonGroup";
import EmptyState from "../components/EmptyState";
import SpotlightTour from "../components/SpotlightTour";
import StatusBadge from "../components/StatusBadge";
import { useAgendaTour } from "../features/appointments/tour/useAgendaTour";
import { AGENDA_TOUR_KEY } from "../features/appointments/tour/agendaSteps";
import AppointmentsSkeleton from "../features/appointments/AppointmentsSkeleton";
import Skeleton from "react-loading-skeleton";
import api from "../api/client";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";

import { apiError } from "../utils/apiError";
import handleFormError from "../utils/handleFormError";

// ── Constants ──────────────────────────────────────────────────────────────────
const DAYS_ES  = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
const MONTHS_S = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
const MONTHS_F = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
const HOURS    = Array.from({ length: 13 }, (_, i) => i + 7); // 7 – 19

const PAL_KEYS = ["teal","amber","blue","purple","rose","slate"];
const PAL = {
    teal:   { bg:"#E1F5EE", text:"#085041", border:"#1D9E75" },
    amber:  { bg:"#FAEEDA", text:"#633806", border:"#BA7517" },
    blue:   { bg:"#E6F1FB", text:"#0C447C", border:"#378ADD" },
    purple: { bg:"#F0EDFB", text:"#3B1F79", border:"#7C5CBF" },
    rose:   { bg:"#FCE8EF", text:"#7B1535", border:"#D43B6A" },
    slate:  { bg:"#F1F4F8", text:"#2E3A4E", border:"#7A8FA6" },
};


const APPOINTMENT_CATEGORIES = [
    ["general_consultation", "Consulta general"],
    ["preventive_vaccination", "Vacunación / preventiva"],
    ["surgery_procedure", "Cirugía o procedimiento"],
    ["grooming", "Estética"],
    ["follow_up", "Seguimiento"],
    ["emergency", "Urgencia"],
    ["other", "Otro"],
];
const categoryLabel = (value) => APPOINTMENT_CATEGORIES.find(([id]) => id === value)?.[1] || "Consulta general";

// ── Utils ──────────────────────────────────────────────────────────────────────
const pad = n => String(n).padStart(2,"0");

function getWeekStart(base, offset = 0) {
    const d = new Date(base);
    d.setDate(d.getDate() - d.getDay() + offset * 7);
    d.setHours(0, 0, 0, 0);
    return d;
}

function isSameDay(a, b) {
    return a.getFullYear() === b.getFullYear() &&
           a.getMonth()    === b.getMonth()    &&
           a.getDate()     === b.getDate();
}

function weekTitle(ws) {
    const we = new Date(ws); we.setDate(we.getDate() + 6);
    if (ws.getMonth() === we.getMonth())
        return `${ws.getDate()} – ${we.getDate()} de ${MONTHS_F[ws.getMonth()]} ${ws.getFullYear()}`;
    return `${ws.getDate()} ${MONTHS_S[ws.getMonth()]} – ${we.getDate()} ${MONTHS_S[we.getMonth()]} ${ws.getFullYear()}`;
}

function toDateStr(d) {
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
}

// ── Shared style atoms ─────────────────────────────────────────────────────────
const lblStyle = {
    display:"block", fontSize:"12px", fontWeight:"500",
    color:"var(--c-text-2)", marginBottom:"4px",
};

const miniNavBtn = {
    background:"none", border:"none", cursor:"pointer",
    color:"var(--c-text-2)", fontSize:"16px", padding:"2px 6px",
};

const calNavBtn = {
    background:"none", border:"1px solid var(--c-border)", borderRadius:"var(--r-md)",
    padding:"5px 10px", cursor:"pointer", color:"var(--c-text-2)",
    fontSize:"14px", boxShadow:"var(--shadow-xs)",
};

// ── MiniCalendar ───────────────────────────────────────────────────────────────
function MiniCalendar({ today, selectedDate, onSelect }) {
    const [view, setView] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
    const firstDow     = view.getDay();
    const daysInMonth  = new Date(view.getFullYear(), view.getMonth()+1, 0).getDate();
    const cells = [];
    for (let i = 0; i < firstDow; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);

    return (
        <div>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:"10px"}}>
                <button style={miniNavBtn}
                    onClick={()=>setView(v=>new Date(v.getFullYear(),v.getMonth()-1,1))}>‹</button>
                <span style={{fontSize:"13px",fontWeight:"500",color:"var(--c-text)"}}>
                    {MONTHS_F[view.getMonth()]} {view.getFullYear()}
                </span>
                <button style={miniNavBtn}
                    onClick={()=>setView(v=>new Date(v.getFullYear(),v.getMonth()+1,1))}>›</button>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(7,1fr)",gap:"1px"}}>
                {DAYS_ES.map(d => (
                    <div key={d} style={{fontSize:"10px",color:"var(--c-text-3)",textAlign:"center",
                        paddingBottom:"4px",textTransform:"uppercase",fontWeight:"600"}}>
                        {d[0]}
                    </div>
                ))}
                {cells.map((d, i) => {
                    if (!d) return <div key={`e${i}`} />;
                    const date    = new Date(view.getFullYear(), view.getMonth(), d);
                    const isToday = isSameDay(date, today);
                    const isSel   = selectedDate && isSameDay(date, selectedDate);
                    return (
                        <div key={d} onClick={()=>onSelect(date)} style={{
                            fontSize:"12px", textAlign:"center", padding:"5px 2px",
                            borderRadius:"50%", cursor:"pointer",
                            background: isToday?"var(--c-primary)": isSel?"var(--c-primary-light)":"transparent",
                            color:      isToday?"#fff": isSel?"var(--c-primary-dark)":"var(--c-text-2)",
                            fontWeight: (isToday||isSel)?"600":"400",
                        }}>
                            {d}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// ── localTodayStr ──────────────────────────────────────────────────────────────
function localTodayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

// ── Detail Modal ───────────────────────────────────────────────────────────────
function DetailModal({ appt, petName, vetName, petId, onClose, onStatusChange, onAttendNow, onEdit, onNewFromAppt, navigate, canEdit, showHistory, onRefresh }) {
    const confirm = useConfirm();
    const [history,          setHistory]          = useState([]);
    const [historyOpen,      setHistoryOpen]      = useState(false);
    const [loadingHist,      setLoadingHist]      = useState(false);
    const [assigningPatient, setAssigningPatient] = useState(false);
    const [newPetItem,       setNewPetItem]       = useState(null);
    const [savingAssign,     setSavingAssign]     = useState(false);
    const [attending,        setAttending]        = useState(false);

    const canReschedule = appt.status === "canceled" && appt.date >= localTodayStr();
    const showNewAppt   = (appt.status === "canceled" && appt.date < localTodayStr()) || appt.status === "no_show";

    const toggleHistory = async () => {
        if (!historyOpen && history.length === 0) {
            setLoadingHist(true);
            try {
                const data = await getAppointmentHistory(appt.public_id);
                setHistory(data);
            } catch {
                // silenciar — historial no crítico
            } finally {
                setLoadingHist(false);
            }
        }
        setHistoryOpen(prev => !prev);
    };

    const handleAssign = async () => {
        if (!newPetItem) { toast.error("Selecciona una mascota"); return; }
        setSavingAssign(true);
        try {
            const updated = await assignPatient(appt.public_id, newPetItem.id, appt);
            onRefresh(updated);
            setAssigningPatient(false);
            setNewPetItem(null);
            toast.success("Paciente vinculado correctamente");
        } catch (err) {
            toast.error(apiError(err, "Error al vincular paciente"));
        } finally {
            setSavingAssign(false);
        }
    };

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal modal-md" onClick={e=>e.stopPropagation()}>
                <div className="modal-header">
                    <div>
                        <h3 style={{marginBottom:"5px"}}>{petName || "—"}</h3>
                        <StatusBadge status={appt.status} />
                    </div>
                    <button className="modal-close" onClick={onClose}>×</button>
                </div>
                <div className="modal-body" data-tour="agenda-detail">
                    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"10px"}}>
                        {[
                            ["Veterinario", vetName || appt.veterinarian_name || "—"],
                            ["Fecha", new Date(appt.date+"T00:00:00").toLocaleDateString("es-ES",{weekday:"short",day:"numeric",month:"long",year:"numeric"})],
                            ["Horario", `${appt.start_time?.slice(0,5)} – ${appt.end_time?.slice(0,5)}`],
                            ["Motivo", appt.reason],
                            ["Categoría", categoryLabel(appt.category)],
                        ].map(([k,v])=>(
                            <div key={k} style={{background:"var(--c-subtle)",borderRadius:"var(--r-md)",padding:"9px 11px"}}>
                                <div style={{fontSize:"11px",color:"var(--c-text-3)",fontWeight:"600",
                                    textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:"3px"}}>{k}</div>
                                <div style={{fontSize:"13px",fontWeight:"500",color:"var(--c-text)"}}>{v}</div>
                            </div>
                        ))}
                    </div>
                    {appt.notes && (
                        <div style={{marginTop:"12px",padding:"10px 12px",background:"var(--c-subtle)",
                            borderRadius:"var(--r-md)",fontSize:"13px",color:"var(--c-text-2)"}}>
                            {appt.notes}
                        </div>
                    )}
                    {appt.cancellation_reason && (
                        <div style={{marginTop:"8px",padding:"8px 12px",background:"#fef2f2",
                            borderRadius:"var(--r-md)",fontSize:"12px",color:"#991b1b",borderLeft:"3px solid #f87171"}}>
                            <strong>Motivo cancelación:</strong> {appt.cancellation_reason}
                        </div>
                    )}

                    {/* Banner: paciente genérico — vincular a real */}
                    {appt.pet_is_generic && canEdit && (
                        <div style={{
                            marginTop:"12px", padding:"12px 14px",
                            background:"#fffbeb", border:"1px solid #fbbf24",
                            borderRadius:"var(--r-md)",
                        }}>
                            <p style={{fontSize:"12.5px",fontWeight:"600",color:"#92400e",marginBottom:"8px"}}>
                                Atención sin mascota registrada — vincular mascota
                            </p>
                            {appt.status === 'done' ? (
                                <p style={{fontSize:"12px",color:"#b45309"}}>
                                    La consulta ya fue completada. El paciente no puede reasignarse.
                                </p>
                            ) : assigningPatient ? (
                                <div>
                                    <EntitySearch
                                        value={newPetItem}
                                        onChange={item => setNewPetItem(item)}
                                        fetchPage={({ query, page }) => searchPets({ query, page })}
                                        renderItem={renderPetOption}
                                        getOptionLabel={petOptionLabel}
                                        placeholder="Buscar mascota..."
                                    />
                                    <div style={{display:"flex",gap:"6px",marginTop:"8px"}}>
                                        <button className="btn btn-primary btn-sm"
                                            disabled={!newPetItem || savingAssign}
                                            onClick={handleAssign}>
                                            {savingAssign ? "Guardando..." : "Vincular"}
                                        </button>
                                        <button className="btn btn-secondary btn-sm"
                                            onClick={() => { setAssigningPatient(false); setNewPetItem(null); }}>
                                            Cancelar
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <button className="btn btn-secondary btn-sm"
                                    onClick={() => setAssigningPatient(true)}>
                                    Vincular paciente
                                </button>
                            )}
                        </div>
                    )}

                    {/* Historial de estados — solo si el toggle está activo */}
                    {showHistory && (
                        <div style={{marginTop:"12px"}}>
                            <button
                                type="button"
                                onClick={toggleHistory}
                                style={{
                                    display:"flex",alignItems:"center",gap:"6px",
                                    background:"none",border:"none",cursor:"pointer",
                                    fontSize:"12px",fontWeight:"600",color:"var(--c-text-2)",padding:"0",
                                }}
                            >
                                <span style={{fontSize:"10px"}}>{historyOpen ? "▼" : "▶"}</span>
                                Historial de estados
                            </button>
                            {historyOpen && (
                                <div style={{marginTop:"8px",borderLeft:"2px solid var(--c-border)",paddingLeft:"12px"}}>
                                    {loadingHist ? (
                                        <div role="status" aria-label="Cargando historial de estados">
                                            {[0, 1, 2].map(i => (
                                                <div key={i} aria-hidden="true" style={{marginBottom:"8px"}}>
                                                    <Skeleton width={150} height={16} borderRadius="var(--r-full)" />
                                                    <Skeleton width={120} height={10} />
                                                </div>
                                            ))}
                                        </div>
                                    ) : history.length === 0 ? (
                                        <p style={{fontSize:"12px",color:"var(--c-text-3)"}}>Sin cambios registrados.</p>
                                    ) : history.map(h => (
                                        <div key={h.id} style={{marginBottom:"8px"}}>
                                            <div style={{display:"flex",alignItems:"center",gap:"6px",fontSize:"12.5px"}}>
                                                <span className={`badge ${statusBadgeClass(h.from_status)}`} style={{fontSize:"10px"}}>
                                                    {h.from_status_display || h.from_status}
                                                </span>
                                                <span style={{color:"var(--c-text-3)"}}>→</span>
                                                <span className={`badge ${statusBadgeClass(h.to_status)}`} style={{fontSize:"10px"}}>
                                                    {h.to_status_display || h.to_status}
                                                </span>
                                            </div>
                                            <p style={{fontSize:"11px",color:"var(--c-text-3)",marginTop:"2px"}}>
                                                {h.changed_by_name || "—"} · {h.created_at ? new Date(h.created_at).toLocaleString("es-MX",{dateStyle:"short",timeStyle:"short"}) : ""}
                                            </p>
                                            {h.reason && (
                                                <p style={{fontSize:"11px",color:"var(--c-text-3)",fontStyle:"italic"}}>{h.reason}</p>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
                <div className="modal-footer modal-footer-stacked">

                    {/* scheduled / confirmed → Atender ahora */}
                    {(appt.status === "scheduled" || appt.status === "confirmed") && canEdit && (
                        <>
                            <button
                                className="btn btn-attention btn-lg"
                                data-tour="agenda-attend"
                                style={{ width: "100%" }}
                                disabled={attending}
                                onClick={async () => {
                                    setAttending(true);
                                    try { await onAttendNow?.(appt); } finally { setAttending(false); }
                                }}>
                                ▶ Atender ahora
                            </button>
                            {appt.status === "scheduled" && (
                                <div style={{ display: "flex", gap: "6px", width: "100%" }}>
                                    <button className="btn btn-info btn-md" style={{ flex: 1 }}
                                        onClick={() => onEdit(appt)}>Editar</button>
                                    <button className="btn btn-purple btn-md" style={{ flex: 1 }}
                                        onClick={() => onStatusChange(appt.public_id, "confirmed", appt)}>Confirmar</button>
                                </div>
                            )}
                            <div style={{ display: "flex", gap: "6px", width: "100%" }}>
                                <button className="btn btn-secondary btn-md" style={{ flex: 1 }}
                                    onClick={async () => {
                                        if (await confirm({ message: "¿Marcar como no presentado?", confirmText: "No se presentó" }))
                                            onStatusChange(appt.public_id, "no_show", appt);
                                    }}>No se presentó</button>
                                <button className="btn btn-danger btn-md" style={{ flex: 1 }}
                                    onClick={async () => {
                                        if (await confirm({ message: "¿Cancelar esta cita?", confirmText: "Cancelar cita", dangerMode: true }))
                                            onStatusChange(appt.public_id, "canceled", appt);
                                    }}>Cancelar</button>
                            </div>
                        </>
                    )}

                    {/* in_progress → continuar / completar / cancelar */}
                    {appt.status === "in_progress" && canEdit && (
                        <>
                            <button
                                className="btn btn-attention btn-lg"
                                style={{ width: "100%" }}
                                disabled={attending}
                                onClick={async () => {
                                    setAttending(true);
                                    try { await onAttendNow?.(appt); } finally { setAttending(false); }
                                }}>
                                Continuar consulta
                            </button>
                            <div style={{display:"flex",gap:"6px",width:"100%"}}>
                                <button className="btn btn-success btn-md" style={{flex:2}}
                                    onClick={async ()=>{
                                        const ok = await confirm({
                                            title: "Finalizar atención",
                                            message: "La cita se marcará como completada. Después podrás crear o abrir la consulta médica y continuar con el flujo clínico y de cobro.",
                                            confirmText: "Completar consulta",
                                        });
                                        if (ok) onStatusChange(appt.public_id, "done", appt);
                                    }}>Completar consulta</button>
                                <button className="btn btn-danger btn-md" style={{flex:1}}
                                    onClick={async ()=>{
                                        if(await confirm({ message:"¿Cancelar esta consulta en progreso?", confirmText:"Cancelar", dangerMode:true }))
                                            onStatusChange(appt.public_id, "canceled", appt);
                                    }}>Cancelar</button>
                            </div>
                        </>
                    )}

                    {/* done → medical record / invoice */}
                    {appt.status === "done" && (
                        <>
                            {appt.medical_record_public_ids?.length > 0 ? (
                                <button className="btn btn-purple btn-md" style={{width:"100%"}}
                                    onClick={()=>{onClose(); navigate(`/medical-records?record=${appt.medical_record_public_ids[0]}`); }}>
                                    Ver Consulta
                                </button>
                            ) : canEdit && (
                                <button className="btn btn-purple btn-md" style={{width:"100%"}}
                                    onClick={()=>{onClose(); navigate(`/medical-records?pet=${petId}&appointment=${appt.public_id}`); }}>
                                    + Crear Consulta Médica
                                </button>
                            )}
                            {appt.invoice_id && (
                                <button className="btn btn-success btn-md"
                                    style={{width:"100%"}}
                                    onClick={()=>{onClose(); navigate("/billing"); }}>
                                    Ver Factura
                                </button>
                            )}
                        </>
                    )}

                    {/* canceled → reschedule (if date still valid) or new appt */}
                    {canReschedule && canEdit && (
                        <button className="btn btn-info btn-md" style={{width:"100%"}}
                            onClick={()=>onStatusChange(appt.public_id, "scheduled", appt)}>Reprogramar</button>
                    )}
                    {showNewAppt && canEdit && (
                        <button className="btn btn-info btn-md" style={{width:"100%"}}
                            onClick={()=>{ onClose(); onNewFromAppt(appt); }}>
                            + Crear nueva cita
                        </button>
                    )}

                    <button className="btn btn-secondary btn-md" style={{width:"100%"}} onClick={onClose}>
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Edit Modal ─────────────────────────────────────────────────────────────────
function EditModal({ appt, staff, user, onClose, onSave }) {
    const [form, setForm] = useState({
        veterinarian: String(appt.veterinarian || ""),
        date:         appt.date || "",
        start_time:   appt.start_time?.slice(0,5) || "09:00",
        end_time:     appt.end_time?.slice(0,5)   || "10:00",
        reason:       appt.reason || "",
        category:     appt.category || "general_consultation",
        notes:        appt.notes  || "",
    });
    const [saving, setSaving] = useState(false);

    async function handleSave() {
        if (saving) return;
        if (!form.veterinarian) { toast.error("Selecciona un veterinario"); return; }
        if (!form.date)         { toast.error("La fecha es obligatoria"); return; }
        if (!form.reason.trim()) { toast.error("El motivo es obligatorio"); return; }
        setSaving(true);
        try {
            await toast.promise(onSave(form), {
                loading: 'Guardando cambios...',
                success: 'Cita actualizada',
                error: (err) => apiError(err, "Error al guardar")
            });
        } catch {
            // el error ya lo muestra toast.promise
        } finally { setSaving(false); }
    }

    const petName = appt.pet_name || "—";

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal modal-md" onClick={e=>e.stopPropagation()}>
                <div className="modal-header">
                    <h3>Editar Cita</h3>
                    <button className="modal-close" onClick={onClose}>×</button>
                </div>
                <div className="modal-body">
                    <div className="form-group">
                        <label className="form-label" htmlFor="edit-appt-pet">MASCOTA</label>
                        <input id="edit-appt-pet" name="edit-appt-pet" value={petName} readOnly className="input" />
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="edit-appt-vet">VETERINARIO *</label>
                        <select id="edit-appt-vet" name="edit-appt-vet" className="select-input" value={form.veterinarian}
                            onChange={e=>setForm({...form,veterinarian:e.target.value})}
                            disabled={user?.role==="VET"}>
                            <option value="">Seleccionar</option>
                            {staff.map(s=>(
                                <option key={s.id} value={s.id}>{s.first_name} {s.last_name}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="edit-appt-date">FECHA *</label>
                        <input id="edit-appt-date" name="edit-appt-date" type="date" className="input" value={form.date}
                            min={localTodayStr()}
                            onChange={e=>setForm({...form,date:e.target.value})}/>
                    </div>
                    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"14px"}}>
                        <div className="form-group">
                            <label className="form-label" htmlFor="edit-appt-start">HORA INICIO *</label>
                            <input id="edit-appt-start" name="edit-appt-start" type="time" className="input" value={form.start_time}
                                onChange={e=>setForm({...form,start_time:e.target.value})}/>
                        </div>
                        <div className="form-group">
                            <label className="form-label" htmlFor="edit-appt-end">HORA FIN *</label>
                            <input id="edit-appt-end" name="edit-appt-end" type="time" className="input" value={form.end_time}
                                onChange={e=>setForm({...form,end_time:e.target.value})}/>
                        </div>
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="edit-appt-reason">MOTIVO *</label>
                        <input id="edit-appt-reason" name="edit-appt-reason" type="text" className="input" value={form.reason}
                            onChange={e=>setForm({...form,reason:e.target.value})}
                            placeholder="Ej: Vacunación, Revisión general"/>
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="edit-appt-category">CATEGORÍA *</label>
                        <select id="edit-appt-category" name="edit-appt-category" className="select-input" value={form.category}
                            onChange={e=>setForm({...form,category:e.target.value})}>
                            {APPOINTMENT_CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="edit-appt-notes">NOTAS</label>
                        <textarea id="edit-appt-notes" name="edit-appt-notes" className="textarea-input" style={{minHeight:"60px"}} value={form.notes}
                            onChange={e=>setForm({...form,notes:e.target.value})}
                            placeholder="Notas adicionales..."/>
                    </div>
                </div>
                <div className="modal-footer">
                    <button className="btn btn-primary btn-md" style={{flex:1}}
                        onClick={handleSave} disabled={saving}>
                        {saving ? "Guardando..." : "Guardar cambios"}
                    </button>
                    <button className="btn btn-secondary btn-md" style={{flex:1}} onClick={onClose}>
                        Cancelar
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Sidebar Form (new appointment) ─────────────────────────────────────────────
const EMPTY_QUICK = { ownerName: '', ownerPhone: '', petName: '', species: '', sex: 'unknown', birthDate: '' };

function SidebarForm({ slot, onSave, onSaveWithPatient, onClear, staff, user, formRef }) {
    const [petItem,          setPetItem]          = useState(null);
    const [vetId,            setVetId]            = useState(user?.role==="VET" ? String(user.id) : "");
    const [reason,           setReason]           = useState("");
    const [category,         setCategory]         = useState("general_consultation");
    const [notes,            setNotes]            = useState("");
    const [hour,             setHour]             = useState(slot?.hour ?? 9);
    const [saving,           setSaving]           = useState(false);
    const [showQuickPatient, setShowQuickPatient] = useState(false);
    const [quickPatient,     setQuickPatient]     = useState(EMPTY_QUICK);
    const warnedPastRef = useRef(false);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- precarga la hora del horario elegido; el usuario puede cambiarla
        if (slot?.hour !== undefined) setHour(slot.hour);
    }, [slot?.hour]);

    useEffect(() => {
        if (!slot) { warnedPastRef.current = false; return; }
        const isPast = toDateStr(slot.date) < localTodayStr();
        if (isPast && !warnedPastRef.current) {
            warnedPastRef.current = true;
            toast.error("No puedes crear una cita pasada. Revisa la fecha o cambia el estado a 'Completada'.");
        }
        if (!isPast) warnedPastRef.current = false;
    }, [slot]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- preselecciona al veterinario cuando llega la sesión
        if (user?.role === "VET") setVetId(String(user.id));
    }, [user]);

    async function handleSave() {
        if (saving) return;
        if (!petItem && !showQuickPatient) { toast.error("Selecciona una mascota"); return; }
        if (!vetId)         { toast.error("Selecciona un veterinario"); return; }
        if (!reason.trim()) { toast.error("Ingresa el motivo de la consulta"); return; }
        if (!slot)          { toast.error("Selecciona un horario en el calendario"); return; }

        if (showQuickPatient) {
            if (!quickPatient.ownerName.trim())            { toast.error("Nombre del cliente requerido"); return; }
            if (!/^\d{10}$/.test(quickPatient.ownerPhone)) { toast.error("Teléfono del cliente: 10 dígitos"); return; }
            if (!quickPatient.petName.trim())              { toast.error("Nombre de la mascota requerido"); return; }
            // Especie OPCIONAL (datos mínimos): '' => "pendiente". Ver modules/patients.md.

            setSaving(true);
            try {
                await toast.promise(onSaveWithPatient({
                    owner_name:     quickPatient.ownerName.trim(),
                    owner_phone:    quickPatient.ownerPhone,
                    pet_name:       quickPatient.petName.trim(),
                    pet_species:    quickPatient.species,
                    pet_sex:        quickPatient.sex,
                    pet_birth_date: quickPatient.birthDate || null,
                    veterinarian:   parseInt(vetId),
                    date:           toDateStr(slot.date),
                    start_time:     `${pad(hour)}:00`,
                    end_time:       hour < 20 ? `${pad(hour)}:30` : '20:00',
                    reason:         reason.trim(),
                    category,
                    notes,
                }), {
                    loading: 'Guardando cita...',
                    success: 'Cita creada exitosamente',
                    error: (err) => apiError(err, "Error al crear la cita"),
                });
                setPetItem(null); setReason(""); setCategory("general_consultation"); setNotes("");
                setShowQuickPatient(false); setQuickPatient(EMPTY_QUICK);
                if (user?.role !== "VET") setVetId("");
            } catch {
                // el error ya lo muestra toast.promise
            } finally {
                setSaving(false);
            }
        } else {
            setSaving(true);
            try {
                await toast.promise(onSave({
                    petId: petItem.id, vetId,
                    reason: reason.trim(), category, notes,
                    start_time: `${pad(hour)}:00`,
                    end_time:   hour < 20 ? `${pad(hour)}:30` : `20:00`,
                }), {
                    loading: 'Guardando cita...',
                    success: 'Cita creada exitosamente',
                    error: (err) => apiError(err, "Error al crear la cita"),
                });
                setPetItem(null); setReason(""); setCategory("general_consultation"); setNotes("");
                if (user?.role !== "VET") setVetId("");
            } catch {
                // el error ya lo muestra toast.promise
            } finally {
                setSaving(false);
            }
        }
    }

    return (
        <div ref={formRef}>
            <p style={{fontSize:"11px",fontWeight:"700",color:"var(--c-text-3)",
                textTransform:"uppercase",letterSpacing:"0.07em",marginBottom:"14px"}}>
                Nueva cita
            </p>

            {slot ? (
                <div style={{
                    background:"var(--c-primary-light)",color:"var(--c-primary-dark)",
                    borderRadius:"var(--r-md)",padding:"7px 10px",fontSize:"12px",fontWeight:"500",
                    marginBottom:"12px",display:"flex",justifyContent:"space-between",alignItems:"center",
                    border:"1px solid var(--sage-400)",
                }}>
                    <span>{slot.label}</span>
                    <button onClick={onClear} style={{background:"none",border:"none",
                        color:"var(--c-primary-dark)",cursor:"pointer",fontSize:"16px",lineHeight:1,padding:"0 2px"}}>
                        ×
                    </button>
                </div>
            ) : (
                <div style={{
                    background:"var(--c-subtle)",color:"var(--c-text-3)",borderRadius:"var(--r-md)",
                    padding:"7px 10px",fontSize:"12px",marginBottom:"12px",border:"1px solid var(--c-border)",
                }}>
                    Haz clic en una celda del calendario
                </div>
            )}

            <div style={{marginBottom:"10px"}}>
                <label style={lblStyle}>Mascota</label>
                {!showQuickPatient ? (
                    <>
                        <EntitySearch
                            id="new-appt-pet"
                            name="new-appt-pet"
                            value={petItem}
                            onChange={item => setPetItem(item)}
                            fetchPage={({ query, page }) => searchPets({ query, page })}
                            renderItem={renderPetOption}
                            getOptionLabel={petOptionLabel}
                            placeholder="Buscar mascota..."
                            disabled={saving}
                        />
                        <button
                            type="button"
                            data-tour="agenda-quickadd"
                            onClick={() => setShowQuickPatient(true)}
                            disabled={saving}
                            style={{
                                background:"none",border:"none",cursor:"pointer",padding:"4px 0 0",
                                fontSize:"11px",color:"var(--c-text-3)",display:"block",
                            }}
                        >
                            No encuentro la mascota →
                        </button>
                    </>
                ) : (
                    <QuickPatientForm
                        value={quickPatient}
                        onChange={setQuickPatient}
                        onCancel={() => { setShowQuickPatient(false); setQuickPatient(EMPTY_QUICK); }}
                        disabled={saving}
                    />
                )}
            </div>

            <div style={{marginBottom:"10px"}}>
                <label style={lblStyle} htmlFor="new-appt-vet">Veterinario</label>
                <select id="new-appt-vet" name="new-appt-vet" className="select-input" value={vetId}
                    onChange={e=>setVetId(e.target.value)}
                    disabled={user?.role==="VET"} style={{fontSize:"13px"}}>
                    <option value="">Seleccionar veterinario</option>
                    {staff.map(s=>(
                        <option key={s.id} value={s.id}>{s.first_name} {s.last_name}</option>
                    ))}
                </select>
            </div>

            <div style={{marginBottom:"10px"}}>
                <label style={lblStyle} htmlFor="new-appt-reason">Motivo</label>
                <input id="new-appt-reason" name="new-appt-reason" className="input" value={reason} onChange={e=>setReason(e.target.value)}
                    placeholder="Ej: Vacunación, Revisión general" style={{fontSize:"13px"}}/>
            </div>

            <div style={{marginBottom:"10px"}}>
                <label style={lblStyle} htmlFor="new-appt-category">Categoría</label>
                <select id="new-appt-category" name="new-appt-category" className="select-input" value={category}
                    onChange={e=>setCategory(e.target.value)} disabled={saving} style={{fontSize:"13px"}}>
                    {APPOINTMENT_CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
            </div>

            <fieldset style={{marginBottom:"10px", border:"none", padding:0, marginInline:0}}>
                <legend style={lblStyle}>Hora</legend>
                <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:"4px"}}>
                    {HOURS.map(h=>(
                        <button key={h} type="button" onClick={()=>setHour(h)} style={{
                            padding:"5px 2px",
                            border:`1px solid ${hour===h?"var(--c-primary)":"var(--c-border)"}`,
                            borderRadius:"var(--r-sm)", fontSize:"11px", cursor:"pointer",
                            background:  hour===h?"var(--c-primary)":"var(--c-subtle)",
                            color:       hour===h?"#fff":"var(--c-text-2)",
                            fontFamily:  "inherit", fontWeight: hour===h?"600":"400",
                            transition:  "all var(--t)",
                        }}>
                            {h}:00
                        </button>
                    ))}
                </div>
            </fieldset>

            <div style={{marginBottom:"10px"}}>
                <label style={lblStyle} htmlFor="new-appt-notes">Notas (opcional)</label>
                <textarea id="new-appt-notes" name="new-appt-notes" className="textarea-input" value={notes} onChange={e=>setNotes(e.target.value)}
                    placeholder="Notas adicionales..." style={{minHeight:"50px",fontSize:"13px"}}/>
            </div>

            <button className="btn btn-primary btn-md" style={{width:"100%"}}
                onClick={handleSave} disabled={saving}>
                {saving ? "Guardando..." : "Guardar cita"}
            </button>
        </div>
    );
}

// ── WalkIn Modal ───────────────────────────────────────────────────────────────
function WalkInModal({ staff, user, onClose, onSave, allowAnonymousWalkIn }) {
    const [petItem, setPetItem] = useState(null);
    const [vetId,  setVetId]  = useState(user?.role === "VET" ? String(user.id) : "");
    const [reason, setReason] = useState("");
    const [category, setCategory] = useState("general_consultation");
    const [notes,  setNotes]  = useState("");
    const [saving, setSaving] = useState(false);
    const [formErrors, setFormErrors] = useState({});

    async function handleSave() {
        setFormErrors({});
        if (!petItem && !allowAnonymousWalkIn) { toast.error("Selecciona una mascota"); return; }
        if (!vetId)         { toast.error("Selecciona un veterinario"); return; }
        if (!reason.trim()) { toast.error("El motivo es obligatorio"); return; }
        setSaving(true);
        try {
            const payload = {
                veterinarian: parseInt(vetId),
                reason: reason.trim(),
                category,
                notes,
            };
            if (petItem) payload.pet = petItem.id;

            await onSave(payload);
            toast.success('Atención sin cita registrada — consulta en progreso');
        } catch (err) {
            handleFormError(err, setFormErrors);
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal modal-md" onClick={e=>e.stopPropagation()}>
                <div className="modal-header">
                    <div>
                        <h3 style={{marginBottom:"4px"}}>Atención sin cita</h3>
                        <p style={{fontSize:"12px",color:"var(--c-text-3)",margin:0}}>
                            Consulta inmediata — la cita se crea en estado "En consulta"
                        </p>
                    </div>
                    <button className="modal-close" onClick={onClose}>×</button>
                </div>
                <div className="modal-body">
                    <div className="form-group">
                        <label className="form-label" htmlFor="walkin-pet">MASCOTA {allowAnonymousWalkIn ? "(opcional)" : "*"}</label>
                        <EntitySearch
                            id="walkin-pet"
                            name="walkin-pet"
                            value={petItem}
                            onChange={item => setPetItem(item)}
                            fetchPage={({ query, page }) => searchPets({ query, page })}
                            renderItem={renderPetOption}
                            getOptionLabel={petOptionLabel}
                            placeholder="Buscar mascota..."
                        />
                        {allowAnonymousWalkIn && (
                            <p style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "5px" }}>
                                Si lo dejas vacío, se registrará como paciente anónimo.
                            </p>
                        )}
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="walkin-vet">VETERINARIO *</label>
                        <select id="walkin-vet" name="walkin-vet" className={`select-input${formErrors.veterinarian ? " input-error" : ""}`} value={vetId}
                            onChange={e=>setVetId(e.target.value)}
                            disabled={user?.role === "VET"}>
                            <option value="">Seleccionar veterinario</option>
                            {staff.map(s=>(
                                <option key={s.id} value={s.id}>{s.first_name} {s.last_name}</option>
                            ))}
                        </select>
                        {formErrors.veterinarian && (
                            <p style={{ color: "var(--c-danger-text)", fontSize: "11.5px", marginTop: "4px" }}>
                                {formErrors.veterinarian}
                            </p>
                        )}
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="walkin-reason">MOTIVO *</label>
                        <input id="walkin-reason" name="walkin-reason" className={`input${formErrors.reason ? " input-error" : ""}`} value={reason} onChange={e=>setReason(e.target.value)}
                            placeholder="Ej: Revisión de urgencia, Vacunación"/>
                        {formErrors.reason && (
                            <p style={{ color: "var(--c-danger-text)", fontSize: "11.5px", marginTop: "4px" }}>
                                {formErrors.reason}
                            </p>
                        )}
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="walkin-category">CATEGORÍA *</label>
                        <select id="walkin-category" name="walkin-category" className="select-input" value={category}
                            onChange={e=>setCategory(e.target.value)}>
                            {APPOINTMENT_CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                    </div>
                    <div className="form-group">
                        <label className="form-label" htmlFor="walkin-notes">NOTAS</label>
                        <textarea id="walkin-notes" name="walkin-notes" className="textarea-input" style={{minHeight:"56px"}} value={notes}
                            onChange={e=>setNotes(e.target.value)} placeholder="Observaciones adicionales..."/>
                    </div>
                </div>
                <div className="modal-footer">
                    <button className="btn btn-primary btn-md" style={{flex:1}}
                        onClick={handleSave} disabled={saving}>
                        {saving ? "Registrando..." : "Iniciar consulta"}
                    </button>
                    <button className="btn btn-secondary btn-md" style={{flex:1}} onClick={onClose}>
                        Cancelar
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Event manager view ───────────────────────────────────────────────────────
const EVENT_VIEWS = { day: "timeGridDay", week: "timeGridWeek", month: "dayGridMonth" };
const STATUS_FILTERS = [["", "Todas"], ["scheduled", "Programadas"], ["confirmed", "Confirmadas"], ["in_progress", "En consulta"], ["done", "Completadas"], ["walk_in", "Sin cita"]];
const eventTime = (date) => `${pad(date.getHours())}:${pad(date.getMinutes())}:00`;
const isPastCalendarDate = (date, today) => {
    const candidate = new Date(date);
    candidate.setHours(0, 0, 0, 0);
    return candidate < today;
};

function calendarRangeLabel(view) {
    const current = view.currentStart;
    if (view.type === "dayGridMonth") return `${MONTHS_F[current.getMonth()]} ${current.getFullYear()}`;
    if (view.type === "timeGridDay") return current.toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    return weekTitle(current);
}

const CATEGORY_PALETTE = {
    general_consultation: PAL.teal,
    preventive_vaccination: PAL.amber,
    surgery_procedure: PAL.rose,
    grooming: PAL.purple,
    follow_up: PAL.blue,
    emergency: { bg: "#FEECE7", text: "#A3321B", border: "#E45C3A" },
    other: PAL.slate,
};

function CalendarControls({ search, onSearchChange, staff, filterVetId, onVetChange, categoryFilter, onCategoryChange, statusFilter, onStatusChange }) {
    return (
        <div className="agenda-controls" data-tour="agenda-filters" aria-label="Filtros de agenda">
            <input className="agenda-search" value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder="Buscar citas…" aria-label="Buscar citas" />
            <select className="agenda-control-select" value={filterVetId} onChange={(event) => onVetChange(event.target.value)} aria-label="Filtrar por veterinario">
                <option value="">Todos los veterinarios</option>
                {staff.map((member) => <option key={member.id} value={member.id}>{member.first_name} {member.last_name}</option>)}
            </select>
            <select className="agenda-control-select" value={statusFilter} onChange={(event) => onStatusChange(event.target.value)} aria-label="Filtrar por estado">
                {STATUS_FILTERS.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
            </select>
            <select className="agenda-control-select agenda-category-select" value={categoryFilter} onChange={(event) => onCategoryChange(event.target.value)} aria-label="Filtrar por categoría">
                <option value="">Todas las categorías</option>
                {APPOINTMENT_CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <span className="agenda-past-note" data-tour="agenda-past-dates" role="note">No se permiten fechas pasadas</span>
        </div>
    );
}

function AppointmentCreateModal({ slot, onClose, onSave, onSaveWithPatient, staff, user, formRef }) {
    return (
        <div className="modal-overlay appointment-create-modal" data-tour="agenda-create-modal" onClick={onClose}>
            <div className="modal modal-lg" onClick={(event) => event.stopPropagation()}>
                <div className="modal-header">
                    <div>
                        <h3>Nueva cita</h3>
                        <p style={{ color: "var(--c-primary-dark)", fontSize: "13px", margin: "4px 0 0" }}>{slot?.label || "Selecciona fecha y horario"}</p>
                    </div>
                    <button className="modal-close" onClick={onClose}>×</button>
                </div>
                <div className="modal-body">
                    <SidebarForm slot={slot} onSave={onSave} onSaveWithPatient={onSaveWithPatient} onClear={onClose} staff={staff} user={user} formRef={formRef} />
                </div>
            </div>
        </div>
    );
}

function DayPlanner({ selectedDate, appointments, today, canCreate, onSelectSlot, onViewAppointment, onNavigate, calendarView, onChangeView }) {
    const dateKey = toDateStr(selectedDate);
    const dayAppointments = appointments.filter((appointment) => appointment.date === dateKey).sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)));
    const pendingCount = dayAppointments.filter((appointment) => ["scheduled", "confirmed"].includes(appointment.status)).length;
    const completedCount = dayAppointments.filter((appointment) => appointment.status === "done").length;
    const isPast = isPastCalendarDate(selectedDate, today);

    return <section className="day-planner" aria-label="Agenda del día">
        <header className="day-planner-toolbar">
            <div><div className="week-planner-kicker">Agenda del día</div><div className="week-planner-range">{selectedDate.toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</div></div>
            <div className="week-planner-actions"><div className="week-planner-nav"><button type="button" onClick={() => onNavigate("prev")} aria-label="Día anterior">‹</button><button type="button" onClick={() => onNavigate("today")}>Hoy</button><button type="button" onClick={() => onNavigate("next")} aria-label="Día siguiente">›</button></div><ViewModeButtonGroup className="week-planner-switcher" value={calendarView} onChange={onChangeView} /></div>
        </header>
        <div className="day-planner-stats"><div><span>Citas hoy</span><strong>{dayAppointments.length}</strong></div><div><span>Pendientes</span><strong>{pendingCount}</strong></div><div><span>Atendidas</span><strong>{completedCount}</strong></div></div>
        <div className="day-planner-list">{dayAppointments.length === 0 ? <div className="day-planner-empty"><strong>{isPast ? "No hubo citas este día" : "No hay citas programadas"}</strong>{!isPast && canCreate && <button type="button" onClick={() => onSelectSlot(selectedDate, 9)}>Crear primera cita</button>}</div> : dayAppointments.map((appointment) => { const palette = CATEGORY_PALETTE[appointment.category] || PAL.teal; return <button key={appointment.id} type="button" className="day-appointment-row" style={{ "--appointment-accent": palette.border }} onClick={() => onViewAppointment(appointment)}><time>{String(appointment.start_time).slice(0, 5)}</time><span className="day-appointment-pet"><strong>{appointment.pet_name || "Paciente"}</strong><small>{appointment.owner_name || "Sin propietario"}</small></span><span className="day-appointment-reason">{categoryLabel(appointment.category)}</span><StatusBadge status={appointment.status} /></button>; })}</div>
    </section>;
}

function AppointmentList({ appointments, onViewAppointment }) {
    const [page, setPage] = useState(1);
    const perPage = 10;
    const sorted = useMemo(() => [...appointments].sort((a, b) => `${a.date}${a.start_time}`.localeCompare(`${b.date}${b.start_time}`)), [appointments]);
    const pageCount = Math.max(1, Math.ceil(sorted.length / perPage));
    const currentPage = Math.min(page, pageCount);
    const pageItems = sorted.slice((currentPage - 1) * perPage, currentPage * perPage);
    const groups = pageItems.reduce((result, appointment) => {
        (result[appointment.date] ||= []).push(appointment);
        return result;
    }, {});
    const [prevAppointments, setPrevAppointments] = useState(appointments);
    if (prevAppointments !== appointments) { setPrevAppointments(appointments); setPage(1); }

    return <section className="appointment-list-view" data-tour="agenda-list" aria-label="Lista de citas">
        {pageItems.length === 0 ? <div className="appointment-list-empty">No hay citas que coincidan con los filtros.</div> : Object.entries(groups).map(([date, items]) => <div key={date} className="appointment-date-group"><h3>{new Date(`${date}T00:00:00`).toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</h3><div className="appointment-date-items">{items.map((appointment) => { const palette = CATEGORY_PALETTE[appointment.category] || PAL.teal; return <button key={appointment.id} type="button" className="appointment-list-card" style={{ "--appointment-accent": palette.border }} onClick={() => onViewAppointment(appointment)}><time>{String(appointment.start_time).slice(0, 5)} - {String(appointment.end_time).slice(0, 5)}</time><span className="appointment-list-main"><strong>{appointment.pet_name || "Paciente"}</strong><small>{appointment.reason || categoryLabel(appointment.category)}</small></span><span className="appointment-list-tags"><em>{categoryLabel(appointment.category)}</em><em>{appointment.owner_name || "Sin propietario"}</em></span><StatusBadge status={appointment.status} /></button>; })}</div></div>)}
        {pageCount > 1 && <nav className="appointment-pagination" aria-label="Paginación de citas"><button type="button" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={currentPage === 1}>Anterior</button>{Array.from({ length: pageCount }, (_, index) => <button key={index + 1} type="button" className={currentPage === index + 1 ? "is-active" : ""} onClick={() => setPage(index + 1)}>{index + 1}</button>)}<button type="button" onClick={() => setPage((value) => Math.min(pageCount, value + 1))} disabled={currentPage === pageCount}>Siguiente</button></nav>}
    </section>;
}

function EventManagerAppointments() {
    const { token, initializing, user, can } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const formRef = useRef(null);
    const calendarRef = useRef(null);
    const today = useMemo(() => { const date = new Date(); date.setHours(0, 0, 0, 0); return date; }, []);
    const [appointments, setAppointments] = useState([]);
    const [staff, setStaff] = useState([]);
    const [loading, setLoading] = useState(true);
    const [calendarView, setCalendarView] = useState("month");
    const [calendarTitle, setCalendarTitle] = useState(`${MONTHS_F[today.getMonth()]} ${today.getFullYear()}`);
    const [weekOffset, setWeekOffset] = useState(0);
    const [dayAnchor, setDayAnchor] = useState(today);
    const [selectedSlot, setSelectedSlot] = useState(null);
    const [viewAppt, setViewAppt] = useState(null);
    const [editingAppt, setEditingAppt] = useState(null);
    const [walkInOpen, setWalkInOpen] = useState(false);
    const [filterVetId, setFilterVetId] = useState("");
    const [statusFilter, setStatusFilter] = useState("");
    const [categoryFilter, setCategoryFilter] = useState("");
    const [search, setSearch] = useState("");
    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [orgSettings, setOrgSettings] = useState(null);
    const [tourDemoAppt, setTourDemoAppt] = useState(null);
    const tourActions = useMemo(() => ({
        setWeekOffset,
        setSelectedSlot,
        setViewAppt,
        setTourDemoAppt,
        setCalendarView,
        goToToday: () => calendarRef.current?.getApi().today(),
        openCreateModal: (slot) => { setSelectedSlot(slot); setCreateModalOpen(true); },
        closeCreateModal: () => setCreateModalOpen(false),
    }), []);
    const tour = useAgendaTour(tourActions);
    const tourStartedRef = useRef(false);
    const canCreate = user?.role !== "ASSISTANT";
    const canEdit = user?.role === "ADMIN" || user?.role === "VET";

    const loadAll = async () => {
        try {
            const [staffData, apptData] = await Promise.all([getStaff(), getAppointments(token)]);
            setStaff(staffData.filter((member) => member.role === "VET" || member.role === "ADMIN"));
            setAppointments(Array.isArray(apptData) ? apptData : (apptData.results || []));
        } catch (err) { console.error(apiError(err)); } finally { setLoading(false); }
    };
    const loadAppointments = async () => {
        try { const data = await getAppointments(token); setAppointments(Array.isArray(data) ? data : (data.results || [])); }
        catch (err) { console.error(apiError(err)); }
    };
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga inicial desde la API al montar
    useEffect(() => { if (token) { loadAll(); getOrgSettings().then(setOrgSettings).catch(() => {}); } }, [token]);
    useEffect(() => { const appointmentId = searchParams.get("appointment"); if (appointmentId && token) api.get(`appointments/${appointmentId}/`).then((response) => setViewAppt(response.data)).catch(() => {}); }, [searchParams, token]);
    useEffect(() => { if (weekOffset) calendarRef.current?.getApi().gotoDate(getWeekStart(today, weekOffset)); }, [today, weekOffset]);
    useEffect(() => {
        if (!loading && calendarView !== "list") calendarRef.current?.getApi().changeView(EVENT_VIEWS[calendarView]);
    }, [calendarView, loading]);
    useEffect(() => {
        const calendar = calendarRef.current?.getApi();
        if (!calendar) return;
        calendar.setOption("selectAllow", (selection) => !isPastCalendarDate(selection.start, today));
        calendar.setOption("eventAllow", (dropInfo, draggedEvent) => canEdit && !isPastCalendarDate(dropInfo.start, today) && ["scheduled", "confirmed"].includes(draggedEvent.extendedProps.appointment.status));
        calendar.setOption("fixedWeekCount", false);
        calendar.setOption("dayMaxEvents", 2);
    }, [calendarView, canEdit, today]);
    const startTour = tour.start;
    useEffect(() => { if (tourStartedRef.current || !canCreate) return; let seen = true; try { seen = localStorage.getItem(AGENDA_TOUR_KEY) === "true"; } catch { /* localStorage no disponible: se asume visto */ } if (!seen) { tourStartedRef.current = true; startTour(); } }, [canCreate, startTour]);

    const vetPalette = useMemo(() => new Map(staff.map((member, index) => [member.id, PAL[PAL_KEYS[index % PAL_KEYS.length]]])), [staff]);
    const getVetName = (id) => { const member = staff.find((item) => item.id === id); return member ? `${member.first_name} ${member.last_name}` : null; };
    const visibleAppointments = useMemo(() => {
        const normalizedSearch = search.trim().toLocaleLowerCase("es-MX");
        const source = tourDemoAppt ? [...appointments, tourDemoAppt] : appointments;
        return source.filter((appointment) => {
            if (filterVetId && String(appointment.veterinarian) !== filterVetId) return false;
            if (statusFilter === "walk_in" && !appointment.walk_in) return false;
            if (statusFilter && statusFilter !== "walk_in" && appointment.status !== statusFilter) return false;
            if (categoryFilter && appointment.category !== categoryFilter) return false;
            if (!normalizedSearch) return true;
            return [appointment.pet_name, appointment.owner_name, appointment.reason, categoryLabel(appointment.category), appointment.veterinarian_name || getVetName(appointment.veterinarian)].filter(Boolean).join(" ").toLocaleLowerCase("es-MX").includes(normalizedSearch);
        });
    }, [appointments, categoryFilter, filterVetId, getVetName, search, statusFilter, tourDemoAppt]);
    const calendarEvents = useMemo(() => visibleAppointments.map((appointment) => {
        const palette = CATEGORY_PALETTE[appointment.category] || PAL.teal;
        return { id: String(appointment.id), title: `${appointment.pet_name || "Paciente"} · ${categoryLabel(appointment.category)}`, start: `${appointment.date}T${appointment.start_time}`, end: `${appointment.date}T${appointment.end_time}`, backgroundColor: "#ffffff", borderColor: palette.border, textColor: palette.text, classNames: ["appointment-event", `appointment-status-${appointment.status}`], extendedProps: { appointment } };
    }), [vetPalette, visibleAppointments]);
    const todayCount = appointments.filter((appointment) => isSameDay(new Date(`${appointment.date}T00:00:00`), today)).length;
    const currentWeekStart = getWeekStart(today); const currentWeekEnd = new Date(currentWeekStart); currentWeekEnd.setDate(currentWeekEnd.getDate() + 6);
    const weekCount = appointments.filter((appointment) => { const date = new Date(`${appointment.date}T00:00:00`); return date >= currentWeekStart && date <= currentWeekEnd; }).length;
    const selectSlot = (date, hour = 9) => {
        if (!canCreate) return;
        if (isPastCalendarDate(date, today)) {
            toast.error("No puedes agendar citas en fechas pasadas.");
            return;
        }
        const label = `${DAYS_ES[date.getDay()]} ${date.getDate()} ${MONTHS_S[date.getMonth()]} · ${pad(hour)}:${pad(date.getMinutes())} hs`;
        setSelectedSlot({ date, hour, label });
        setCreateModalOpen(true);
    };
    const handleCalendarSelect = (selection) => { selectSlot(selection.start, selection.allDay ? 9 : selection.start.getHours()); selection.view.calendar.unselect(); };
    const handleFormSave = async ({ petId, vetId, reason, category, notes, start_time, end_time }) => {
        if (!selectedSlot || isPastCalendarDate(selectedSlot.date, today)) {
            toast.error("No puedes agendar citas en fechas pasadas.");
            setCreateModalOpen(false);
            return;
        }
        await createAppointment(token, { pet: petId, veterinarian: vetId, date: toDateStr(selectedSlot.date), start_time, end_time, reason, category, notes, status: "scheduled" });
        window.dispatchEvent(new Event("dashboard:refresh")); setSelectedSlot(null); setCreateModalOpen(false); loadAppointments();
    };
    const handleSaveWithPatient = async (data) => {
        if (!selectedSlot || isPastCalendarDate(selectedSlot.date, today)) {
            toast.error("No puedes agendar citas en fechas pasadas.");
            setCreateModalOpen(false);
            return;
        }
        await createAppointmentWithPatient(data); window.dispatchEvent(new Event("dashboard:refresh")); setSelectedSlot(null); setCreateModalOpen(false); loadAppointments();
    };
    const conflictMessage = (err) => { const current = appointmentChangedCurrent(err); const label = current?.status ? statusLabel(current.status) : ""; const when = current?.date && current?.start_time ? ` (${current.date} ${String(current.start_time).slice(0, 5)})` : ""; return label ? `Esta cita cambió mientras la tenías abierta: ahora está "${label}"${when}. Se recargó la agenda.` : "Esta cita cambió mientras la tenías abierta. Se recargó la agenda."; };
    const handleStatusChange = async (id, status, expected = null) => {
        const messages = { confirmed: "Cita confirmada", in_progress: "Consulta iniciada", done: "Consulta completada", canceled: "Cita cancelada", no_show: "Marcada como no presentado", scheduled: "Cita reprogramada" };
        try { const updated = await updateAppointmentStatus(token, id, status, expected); window.dispatchEvent(new Event("dashboard:refresh")); setAppointments((previous) => previous.map((item) => item.id === updated.id ? updated : item)); setViewAppt(updated); toast.success(messages[status] || "Estado actualizado"); return updated; }
        catch (err) { if (isAppointmentChanged(err)) { toast.error(conflictMessage(err)); await loadAppointments(); } else toast.error(apiError(err, "Error al cambiar estado")); return null; }
    };
    const handleAttendNow = async (appointment) => {
        let current = appointment;
        if (current.status !== "in_progress") { try { current = (await api.get(`appointments/${current.public_id}/`)).data; } catch { toast.error("No se pudo verificar el estado de la cita"); return; } }
        if (current.status !== "in_progress") { if (current.status !== "scheduled" && current.status !== "confirmed") { toast.error("Esta cita ya no está disponible para atender"); return; } try { await updateAppointmentStatus(token, current.public_id, "in_progress", current); window.dispatchEvent(new Event("dashboard:refresh")); loadAppointments(); } catch { toast.info("Hubo un problema menor al abrir la cita, pero puedes continuar normalmente."); } }
        setViewAppt(null); const recordId = current.medical_record_public_ids?.[0]; const query = recordId ? `record=${recordId}` : `pet=${current.pet_public_id}&appointment=${current.public_id}`; navigate(`/medical-records?${query}`, recordId ? undefined : { state: { appointmentId: current.id } });
    };
    const handleWalkIn = async (data) => { await walkInAppointment(token, data); window.dispatchEvent(new Event("dashboard:refresh")); setWalkInOpen(false); loadAppointments(); };
    const handleEditSave = async (form) => {
        if (isPastCalendarDate(`${form.date}T00:00:00`, today)) {
            toast.error("No puedes reprogramar una cita a una fecha pasada.");
            return;
        }
        await updateAppointment(token, editingAppt.public_id, { pet: editingAppt.pet, veterinarian: parseInt(form.veterinarian, 10), date: form.date, start_time: form.start_time, end_time: form.end_time, reason: form.reason, category: form.category, notes: form.notes, status: editingAppt.status }, editingAppt); window.dispatchEvent(new Event("dashboard:refresh")); setEditingAppt(null); loadAppointments();
    };
    const saveCalendarMutation = async (info) => {
        const appointment = info.oldEvent.extendedProps.appointment; const start = info.event.start; const end = info.event.end || new Date(start.getTime() + 30 * 60 * 1000);
        try { const updated = await updateAppointment(token, appointment.public_id, { pet: appointment.pet, veterinarian: appointment.veterinarian, date: toDateStr(start), start_time: eventTime(start), end_time: eventTime(end), reason: appointment.reason, category: appointment.category || "general_consultation", notes: appointment.notes, status: appointment.status }, appointment); setAppointments((previous) => previous.map((item) => item.id === updated.id ? updated : item)); window.dispatchEvent(new Event("dashboard:refresh")); toast.success("Cita reprogramada"); }
        catch (err) { info.revert(); if (isAppointmentChanged(err)) { toast.error(conflictMessage(err)); loadAppointments(); } else toast.error(apiError(err, "No se pudo reprogramar la cita")); }
    };
    const changeView = (nextView) => { setCalendarView(nextView); if (nextView !== "list") calendarRef.current?.getApi().changeView(EVENT_VIEWS[nextView]); };
    const navigateDay = (direction) => {
        setDayAnchor((current) => {
            const next = direction === "today" ? new Date(today) : new Date(current);
            if (direction === "prev") next.setDate(next.getDate() - 1);
            if (direction === "next") next.setDate(next.getDate() + 1);
            calendarRef.current?.getApi().gotoDate(next);
            return next;
        });
    };
    const navigateCalendar = (method) => calendarRef.current?.getApi()[method]();
    if (initializing || loading) return <AppointmentsSkeleton />;

    return <div className={`appointments-event-manager${canCreate ? " can-create" : ""} view-${calendarView}`}>
        <style>{`
            .appointments-event-manager { --agenda-mist:#f3f8f5; } .agenda-shell { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--r-xl); box-shadow:var(--shadow-sm); overflow:hidden; } .agenda-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:16px 20px; border-bottom:1px solid var(--c-border); } .agenda-view-switcher,.agenda-filters,.agenda-staff { display:flex; flex-wrap:wrap; gap:6px; } .agenda-view-button,.agenda-filter,.agenda-staff-button { border:1px solid var(--c-border); border-radius:999px; background:var(--c-surface); color:var(--c-text-2); cursor:pointer; font-size:12px; font-weight:650; padding:6px 11px; transition:all .16s ease; } .agenda-view-button:hover,.agenda-filter:hover,.agenda-staff-button:hover { border-color:var(--c-primary); color:var(--c-primary-dark); } .agenda-view-button.is-active,.agenda-filter.is-active { color:#fff; background:var(--c-primary); border-color:var(--c-primary); } .agenda-search { width:100%; border:1px solid var(--c-border); background:var(--c-subtle); border-radius:var(--r-md); color:var(--c-text); font:inherit; font-size:13px; padding:9px 11px; } .agenda-search:focus { outline:2px solid rgba(29,158,117,.2); border-color:var(--c-primary); } .agenda-grid { display:grid; grid-template-columns:minmax(0,1fr) 286px; gap:16px; align-items:start; } .agenda-sidebar { display:flex; flex-direction:column; gap:14px; } .agenda-sidebar-card { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--r-xl); padding:18px; box-shadow:var(--shadow-sm); } .agenda-section-label { color:var(--c-text-3); font-size:10px; font-weight:750; letter-spacing:.1em; margin:0 0 9px; text-transform:uppercase; } .agenda-calendar .fc { font-size:12px; } .agenda-calendar .fc-theme-standard td,.agenda-calendar .fc-theme-standard th { border-color:var(--c-border); } .agenda-calendar .fc-col-header-cell { background:var(--agenda-mist); padding:5px 0; text-transform:uppercase; font-size:10px; letter-spacing:.07em; } .agenda-calendar .fc-timegrid-slot { height:3.8em; } .agenda-calendar .fc-event { border-radius:7px; border-width:0 0 0 3px; box-shadow:0 1px 2px rgba(17,47,38,.16); cursor:pointer; padding:2px 4px; } .agenda-calendar .fc-event-title { font-weight:700; white-space:normal; line-height:1.2; } .agenda-calendar .fc-highlight { background:rgba(29,158,117,.14); } .agenda-calendar .fc-day-today { background:rgba(29,158,117,.045) !important; } .agenda-list { display:grid; gap:8px; padding:12px; } .agenda-list-item { background:var(--c-surface); border:1px solid var(--c-border); border-left:4px solid var(--c-primary); border-radius:var(--r-lg); cursor:pointer; display:grid; gap:4px; padding:12px 14px; text-align:left; } .agenda-list-item:hover { background:var(--agenda-mist); border-color:var(--c-primary); } .agenda-list-meta { color:var(--c-text-3); font-size:12px; } .agenda-stats { background:var(--c-primary-light); border:1px solid var(--sage-400); border-radius:var(--r-xl); display:grid; gap:12px; grid-template-columns:1fr 1fr; padding:14px 18px; } @media (max-width:980px) { .agenda-grid { grid-template-columns:1fr; } .agenda-sidebar { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); } .agenda-sidebar > :last-child { grid-column:span 2; } } @media (max-width:640px) { .agenda-toolbar,.page-header { align-items:flex-start; flex-direction:column; } .agenda-sidebar { display:flex; } .agenda-calendar .fc-timegrid-slot { height:3.2em; } }
        `}</style>
        <style>{`
            .appointments-event-manager .agenda-grid { display:block; }
            .appointments-event-manager .agenda-sidebar { display:none; }
            .appointments-event-manager { --monday-teal:#087f83; --monday-teal-soft:#e7f5f3; --calendar-line:#e7ebef; }
            .appointments-event-manager .page-header { align-items:center; margin-bottom:12px; }
            .appointments-event-manager .page-title { font-size:26px; letter-spacing:-.035em; }
            .appointments-event-manager .page-subtitle { display:none; }
            .appointments-event-manager .agenda-controls { align-items:center; background:#fff; border:1px solid var(--calendar-line); border-bottom:0; border-radius:8px 8px 0 0; display:flex; flex-wrap:wrap; gap:8px; margin-bottom:-1px; padding:10px 14px; position:relative; z-index:1; }
            .appointments-event-manager .agenda-shell { border-color:var(--calendar-line); border-radius:0 0 8px 8px; box-shadow:none; }
            .appointments-event-manager .agenda-toolbar { min-height:56px; padding:9px 14px; }
            .appointments-event-manager .agenda-search { background:#fff; border-color:#d9e0e5; border-radius:6px; font-size:13px; padding:8px 10px; width:250px; }
            .appointments-event-manager .agenda-control-select { background:#fff; border:1px solid #d9e0e5; border-radius:6px; color:var(--c-text); font:inherit; font-size:12.5px; min-height:35px; padding:0 28px 0 9px; }
            .appointments-event-manager .agenda-category-select { max-width:180px; }
            .appointments-event-manager .agenda-past-note { color:#74818a; font-size:11.5px; margin-left:auto; white-space:nowrap; }
            .appointments-event-manager .agenda-view-switcher { background:#f4f6f7; border:1px solid #e1e6e8; border-radius:7px; gap:0; overflow:hidden; padding:2px; }
            .appointments-event-manager .agenda-view-button { border:0; border-radius:5px; font-size:12px; padding:6px 10px; }
            .appointments-event-manager .agenda-view-button.is-active { background:#fff; box-shadow:0 1px 2px rgba(22,42,49,.14); color:var(--monday-teal); }
            .appointments-event-manager .agenda-calendar .fc { font-size:12px; }
            .appointments-event-manager .agenda-calendar .fc-scrollgrid { border:0; }
            .appointments-event-manager .agenda-calendar .fc-theme-standard td,.appointments-event-manager .agenda-calendar .fc-theme-standard th { border-color:var(--calendar-line); }
            .appointments-event-manager .agenda-calendar .fc-col-header-cell { background:#fafbfc; color:#63717b; font-size:10px; font-weight:750; letter-spacing:.07em; padding:8px 0; }
            .appointments-event-manager .agenda-calendar .fc-daygrid-day-frame { min-height:106px; position:relative; transition:background .15s ease, box-shadow .15s ease; }
            .appointments-event-manager .agenda-calendar .fc-daygrid-day-number { color:#27343d; font-size:12px; font-weight:700; padding:8px 9px; }
            .appointments-event-manager .agenda-calendar .fc-day-today { background:rgba(8,127,131,.035) !important; }
            .appointments-event-manager .agenda-calendar .fc-day-today .fc-daygrid-day-number { color:var(--monday-teal); }
            .appointments-event-manager .agenda-calendar .fc-event { background:#fff !important; border-radius:4px; border-width:0 0 0 3px; box-shadow:0 1px 2px rgba(28,44,52,.09); font-size:11.5px; margin:1px 3px; padding:3px 5px; }
            .appointments-event-manager .agenda-calendar .fc-event:hover { box-shadow:0 3px 8px rgba(28,44,52,.16); transform:translateY(-1px); }
            .appointments-event-manager .agenda-calendar .fc-event-title { font-weight:650; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .appointments-event-manager .agenda-calendar .fc-daygrid-more-link { color:var(--monday-teal); font-size:11px; font-weight:700; }
            .appointments-event-manager .agenda-calendar .fc-timegrid-slot { height:2.75em; }
            .appointments-event-manager .agenda-calendar .fc-day-past,.appointments-event-manager .agenda-calendar .fc-day-disabled { background:#fff; opacity:1; }
            .appointments-event-manager .agenda-calendar .fc-day-past .fc-daygrid-day-frame,.appointments-event-manager .agenda-calendar .fc-day-disabled .fc-daygrid-day-frame { background:transparent; cursor:not-allowed; }
            .appointments-event-manager .agenda-calendar .fc-day-past .fc-daygrid-day-number,.appointments-event-manager .agenda-calendar .fc-day-disabled .fc-daygrid-day-number { color:#27343d; font-weight:700; opacity:1; }
            .appointments-event-manager .agenda-calendar .fc-day-past:hover .fc-daygrid-day-frame,.appointments-event-manager .agenda-calendar .fc-day-disabled:hover .fc-daygrid-day-frame { background:#f1efed; box-shadow:inset 0 0 0 1px #d8ceca; }
            .appointments-event-manager.can-create .agenda-calendar .fc-daygrid-day:not(.fc-day-past):not(.fc-day-disabled) .fc-daygrid-day-frame { cursor:pointer; }
            .appointments-event-manager.can-create .agenda-calendar .fc-daygrid-day:not(.fc-day-past):not(.fc-day-disabled) .fc-daygrid-day-frame:hover { background:#f3faf9; box-shadow:inset 0 0 0 1px #9bcfcd; }
            .appointments-event-manager.view-month .agenda-calendar .fc-daygrid-body table { border-collapse:separate; border-spacing:3px; }
            .appointments-event-manager.view-month .agenda-calendar .fc-daygrid-day { background:#fff; border:1px solid #e6ece9 !important; border-radius:8px; box-shadow:0 1px 2px rgba(24,46,39,.035); overflow:hidden; }
            .appointments-event-manager.view-month .agenda-calendar .fc-daygrid-day-frame { min-height:60px; }
            .appointments-event-manager.view-month .agenda-calendar .fc-daygrid-day-top { min-height:20px; }
            .appointments-event-manager.view-month .agenda-calendar .fc-daygrid-day-number { font-size:10px; padding:4px 6px; }
            .appointments-event-manager.view-month .agenda-calendar .fc-day-past { background:#fff; border-color:#e6ece9 !important; }
            .appointments-event-manager.view-month .agenda-calendar .fc-day-past .fc-daygrid-day-frame { background:transparent; }
            .appointments-event-manager.view-month .agenda-calendar .fc-day-today { box-shadow:inset 0 0 0 1px var(--monday-teal),0 2px 7px rgba(8,127,131,.12); }
            .appointments-event-manager.view-month .agenda-calendar .fc-event { border-radius:4px; box-shadow:0 1px 3px rgba(26,48,40,.11); font-size:10px; line-height:1.15; margin:1px 3px; padding:2px 4px; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-axis { background:#fafcfc; color:#52635e; font-size:11px; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-col { background:#fff; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-col.fc-day-past { background:#fff; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-col.fc-day-past .fc-timegrid-col-frame { background:transparent; cursor:not-allowed; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-col.fc-day-past:hover .fc-timegrid-col-frame { background:#f1efed; box-shadow:inset 0 0 0 1px #d8ceca; }
            .appointments-event-manager.view-week .agenda-calendar .fc-col-header-cell { background:#f8fbfa; padding:10px 0; }
            .appointments-event-manager.view-week .agenda-calendar .fc-col-header-cell-cushion { color:#435750; font-size:11px; font-weight:750; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-slot { height:2.2em; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-slot-minor { border-top-color:#edf2f0; border-top-style:dashed; }
            .appointments-event-manager.view-week .agenda-calendar .fc-timegrid-slot-lane { transition:background .14s ease; }
            .appointments-event-manager.can-create.view-week .agenda-calendar .fc-timegrid-col:not(.fc-day-past) .fc-timegrid-slot-lane { cursor:pointer; }
            .appointments-event-manager.can-create.view-week .agenda-calendar .fc-timegrid-col:not(.fc-day-past) .fc-timegrid-slot-lane:hover { background:rgba(8,127,131,.075); box-shadow:inset 0 0 0 1px rgba(8,127,131,.12); }
            .appointments-event-manager.can-create.view-week .agenda-calendar .fc-timegrid-slot-lane { cursor:pointer; }
            .appointments-event-manager.view-week .agenda-calendar .fc-day-past .fc-timegrid-slot-lane { cursor:not-allowed; }
            .appointments-event-manager.view-week .agenda-calendar .fc-event { border-radius:6px; box-shadow:0 3px 8px rgba(26,48,40,.14); padding:4px 6px; }
            .appointment-list-view { background:#fff; border:1px solid #e4eae7; border-radius:10px; padding:16px; }
            .appointment-date-group + .appointment-date-group { margin-top:20px; }
            .appointment-date-group h3 { color:#345149; font-size:12px; font-weight:760; margin:0 0 8px; text-transform:capitalize; }
            .appointment-date-items { display:grid; gap:7px; }
            .appointment-list-card { align-items:center; background:#fff; border:1px solid #e4eae7; border-left:4px solid var(--appointment-accent); border-radius:7px; color:#294139; cursor:pointer; display:grid; gap:14px; grid-template-columns:112px minmax(160px,1fr) minmax(180px,1fr) auto; min-height:62px; padding:8px 12px; text-align:left; }
            .appointment-list-card:hover { background:#f5fbf9; border-color:#aed8d0; box-shadow:0 3px 8px rgba(26,48,40,.08); }
            .appointment-list-card time { color:#526961; font-size:11px; font-weight:750; }
            .appointment-list-main { display:grid; gap:3px; }
            .appointment-list-main strong { font-size:13px; }
            .appointment-list-main small { color:#71807a; font-size:11px; }
            .appointment-list-tags { display:flex; flex-wrap:wrap; gap:5px; }
            .appointment-list-tags em { background:#f0f5f3; border-radius:999px; color:#547068; font-size:10px; font-style:normal; padding:4px 7px; }
            .appointment-list-empty { color:#71807a; padding:40px 12px; text-align:center; }
            .appointment-pagination { align-items:center; display:flex; gap:5px; justify-content:flex-end; margin-top:18px; }
            .appointment-pagination button { background:#fff; border:1px solid #dfe7e3; border-radius:5px; color:#466057; cursor:pointer; font:inherit; font-size:12px; min-height:31px; padding:0 9px; }
            .appointment-pagination button:hover:not(:disabled),.appointment-pagination button.is-active { background:var(--monday-teal); border-color:var(--monday-teal); color:#fff; }
            .appointment-pagination button:disabled { cursor:not-allowed; opacity:.45; }
            .agenda-global-view-switcher { display:none; }
            .appointments-event-manager.view-list .agenda-global-view-switcher { display:flex; justify-content:flex-end; margin:0 0 10px; }
            .appointments-event-manager.view-day .agenda-grid,.appointments-event-manager.view-list .agenda-grid { display:none; }
            .week-planner { background:#f8faf9; border:1px solid #e5e9e8; border-radius:10px; overflow:hidden; }
            .week-planner-toolbar { align-items:center; background:#fff; border-bottom:1px solid #e5e9e8; display:flex; justify-content:space-between; padding:13px 16px; }
            .week-planner-kicker { color:#72817d; font-size:10px; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }
            .week-planner-range { color:#20332f; font-size:18px; font-weight:760; letter-spacing:-.025em; margin-top:2px; }
            .week-planner-actions,.week-planner-nav { align-items:center; display:flex; gap:8px; }
            .week-planner-nav { gap:4px; }
            .week-planner-nav button { background:#fff; border:1px solid #dfe6e4; border-radius:6px; color:#38504a; cursor:pointer; font:inherit; font-size:12px; min-height:31px; min-width:31px; padding:0 9px; }
            .week-planner-nav button:hover { border-color:#85c5bc; color:var(--monday-teal); }
            .week-planner-scroll { overflow-x:auto; overflow-y:hidden; padding:9px 12px; }
            .week-planner-layout { display:grid; grid-template-columns:42px minmax(980px,1fr); min-width:1022px; }
            .week-time-ruler { position:relative; }
            .week-time-ruler span { color:#89938f; font-size:10px; position:absolute; right:9px; transform:translateY(-50%); }
            .week-day-grid { display:grid; gap:9px; grid-template-columns:repeat(7,minmax(0,1fr)); }
            .week-day-card { background:#fff; border:1px solid #e4e9e7; border-radius:9px; box-shadow:0 2px 6px rgba(22,43,37,.045); min-width:0; overflow:hidden; }
            .week-day-card.is-past { background:#f2f3f2; border-color:#e2e5e3; }
            .week-day-card-header { align-items:center; background:#fbfcfb; border-bottom:1px solid #e9eeec; display:flex; flex-direction:column; min-height:62px; padding:8px 8px 7px; text-align:center; }
            .week-day-card.is-past .week-day-card-header { background:#ecefed; }
            .week-day-card-header span { color:#63716c; font-size:10px; font-weight:760; letter-spacing:.07em; text-transform:uppercase; }
            .week-day-card-header strong { color:#283a35; font-size:20px; font-weight:740; letter-spacing:-.035em; line-height:1; margin:4px 0 3px; }
            .week-day-card-header small { color:#79857f; font-size:10px; }
            .week-day-card.is-today .week-day-card-header { background:#f2fbf9; box-shadow:inset 0 -3px 0 var(--monday-teal); }
            .week-day-card.is-today .week-day-card-header span,.week-day-card.is-today .week-day-card-header strong { color:var(--monday-teal); }
            .week-day-schedule { height:245px; position:relative; }
            .week-day-card:not(.is-past) .week-day-schedule { cursor:pointer; }
            .week-day-card:not(.is-past) .week-day-schedule:hover { background:rgba(244,250,248,.76); }
            .week-day-schedule > i { border-top:1px dashed #dfe7e4; display:block; left:10px; position:absolute; right:10px; }
            .week-day-card.is-past .week-day-schedule > i { border-color:#d9dfdc; }
            .week-appointment { background:#fff; border:1px solid #e2e8e5; border-left:3px solid var(--appointment-accent); border-radius:6px; box-shadow:0 2px 5px rgba(20,43,35,.1); color:#284039; cursor:pointer; display:grid; gap:0; left:8px; overflow:hidden; padding:4px 6px; position:absolute; right:8px; text-align:left; z-index:2; }
            .week-appointment:hover { box-shadow:0 5px 12px rgba(20,43,35,.17); transform:translateY(-1px); }
            .week-appointment b { font-size:9px; font-weight:760; }
            .week-appointment span { font-size:11px; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .week-appointment small { display:none; }
            .week-day-add { background:transparent; border:0; bottom:10px; color:var(--monday-teal); cursor:pointer; font-size:25px; font-weight:300; line-height:1; opacity:0; padding:3px 8px; position:absolute; right:7px; transition:opacity .15s ease, transform .15s ease; }
            .week-day-card:not(.is-past):hover .week-day-add,.week-day-card:not(.is-past):focus-within .week-day-add { opacity:1; transform:translateY(-2px); }
            .week-day-add:hover { color:#045c60; }
            .day-planner { background:#fff; border:1px solid #e5e9e8; border-radius:10px; overflow:hidden; }
            .day-planner-toolbar { align-items:center; border-bottom:1px solid #e8edeb; display:flex; justify-content:space-between; padding:13px 16px; }
            .day-planner-stats { background:#f8faf9; border-bottom:1px solid #e8edeb; display:grid; grid-template-columns:repeat(3,1fr); }
            .day-planner-stats > div { align-items:center; border-right:1px solid #e8edeb; display:flex; gap:10px; min-height:60px; padding:0 18px; }
            .day-planner-stats > div:last-child { border-right:0; }
            .day-planner-stats span { color:#72817c; font-size:12px; }
            .day-planner-stats strong { color:#173f3a; font-size:22px; letter-spacing:-.04em; }
            .day-planner-list { display:grid; gap:7px; padding:12px; }
            .day-appointment-row { align-items:center; background:#fff; border:1px solid #e5ebe8; border-left:4px solid var(--appointment-accent); border-radius:7px; color:#273c36; cursor:pointer; display:grid; gap:14px; grid-template-columns:62px minmax(160px,1.4fr) minmax(130px,1fr) auto; min-height:58px; padding:7px 12px; text-align:left; }
            .day-appointment-row:hover { background:#f6fbfa; border-color:#b9dad4; }
            .day-appointment-row time { background:#f1f5f3; border-radius:5px; color:#35514a; font-size:12px; font-weight:760; padding:6px 7px; text-align:center; }
            .day-appointment-pet { display:grid; gap:2px; }
            .day-appointment-pet strong { font-size:13px; }
            .day-appointment-pet small,.day-appointment-reason { color:#71807a; font-size:11px; }
            .day-planner-empty { align-items:center; color:#63736d; display:flex; flex-direction:column; gap:9px; min-height:230px; justify-content:center; }
            .day-planner-empty button { background:var(--monday-teal); border:0; border-radius:6px; color:#fff; cursor:pointer; font:inherit; font-size:12px; padding:8px 11px; }
            .appointment-create-modal .modal { max-width:720px; }
            .appointment-create-modal .modal-body { padding:22px 28px 26px; }
            .appointment-create-modal .modal-body > div > p:first-child { display:none; }
            .appointment-create-modal .modal-body .btn-primary { margin-top:8px; }
            @media (max-width:760px) { .week-planner-toolbar,.day-planner-toolbar { align-items:flex-start; flex-direction:column; gap:10px; } .week-planner-actions { justify-content:space-between; width:100%; } .day-appointment-row { gap:8px; grid-template-columns:54px 1fr auto; } .day-appointment-reason { display:none; } }
            @media (max-width:640px) { .appointments-event-manager .agenda-toolbar,.appointments-event-manager .agenda-controls { padding-left:14px; padding-right:14px; } .appointments-event-manager .agenda-search { width:100%; } .appointments-event-manager .agenda-control-select { flex:1; min-width:0; } .appointments-event-manager .agenda-past-note { margin-left:0; } }
        `}</style>
        <div className="page-header"><div><h1 className="page-title">Citas</h1><p className="page-subtitle">Agenda clínica · {visibleAppointments.length} citas visibles</p></div><div style={{ display:"flex", alignItems:"center", gap:"8px", flexWrap:"wrap" }}><button className="btn btn-secondary btn-md" onClick={tour.start}><Icon.Help s={15} /> Cómo funciona</button>{canCreate && <button className="btn btn-primary btn-md" onClick={() => selectSlot(today, 9)}><Icon.Plus s={15} /> Nueva cita</button>}{canEdit && <button className="btn btn-secondary btn-md" data-tour="agenda-walkin" onClick={() => setWalkInOpen(true)}>Atención sin cita</button>}</div></div>
        {appointments.length === 0 && <div className="card" style={{ marginBottom:"16px" }}><EmptyState compact icon={Icon.CalendarClock} title="Tu agenda está vacía" body="Selecciona un horario para agendar tu primera cita, o registra un paciente sin cita previa." actions={[can("appointment.create_walkin") ? { label:"Registrar atención sin cita", onClick:() => setWalkInOpen(true), variant:"primary" } : null]} /></div>}
        <CalendarControls search={search} onSearchChange={setSearch} staff={staff} filterVetId={filterVetId} onVetChange={setFilterVetId} categoryFilter={categoryFilter} onCategoryChange={setCategoryFilter} statusFilter={statusFilter} onStatusChange={setStatusFilter} />
        <div className="agenda-global-view-switcher"><ViewModeButtonGroup value={calendarView} onChange={changeView} /></div>
        {calendarView === "day" && <DayPlanner selectedDate={dayAnchor} appointments={visibleAppointments} today={today} canCreate={canCreate} onSelectSlot={selectSlot} onViewAppointment={setViewAppt} onNavigate={navigateDay} calendarView={calendarView} onChangeView={changeView} />}
        {calendarView === "list" && <AppointmentList key={`${search}|${filterVetId}|${statusFilter}|${categoryFilter}`} appointments={visibleAppointments} onViewAppointment={setViewAppt} />}
        <div className="agenda-grid"><div className="agenda-shell" data-tour="agenda-calendar"><div className="agenda-toolbar"><div><div style={{ color:"var(--c-text)", fontSize:"16px", fontWeight:750 }}>{calendarView === "list" ? "Lista de citas" : calendarTitle}</div>{calendarView !== "list" && <div style={{ display:"flex", gap:"6px", marginTop:"8px" }}><button style={calNavBtn} onClick={() => navigateCalendar("prev")}>‹</button><button style={{ ...calNavBtn, fontSize:"12px" }} onClick={() => navigateCalendar("today")}>Hoy</button><button style={calNavBtn} onClick={() => navigateCalendar("next")}>›</button></div>}</div><ViewModeButtonGroup value={calendarView} onChange={changeView} dataTour="agenda-view-switcher" /></div>{calendarView === "list" ? <div className="agenda-list">{visibleAppointments.length === 0 ? <p style={{ color:"var(--c-text-3)", padding:"18px", textAlign:"center" }}>No hay citas que coincidan con los filtros.</p> : [...visibleAppointments].sort((a,b) => `${a.date}${a.start_time}`.localeCompare(`${b.date}${b.start_time}`)).map((appointment) => { const palette = vetPalette.get(appointment.veterinarian) || PAL.teal; return <button key={appointment.id} className="agenda-list-item" style={{ borderLeftColor:palette.border }} onClick={() => setViewAppt(appointment)}><strong>{appointment.pet_name || "Paciente"} · {appointment.reason || "Cita"}</strong><span className="agenda-list-meta">{appointment.date} · {String(appointment.start_time).slice(0,5)} · {appointment.owner_name || "Sin propietario"}</span><StatusBadge status={appointment.status} /></button>; })}</div> : <div className="agenda-calendar"><FullCalendar ref={calendarRef} plugins={[dayGridPlugin,timeGridPlugin,interactionPlugin]} initialView={EVENT_VIEWS.week} initialDate={today} headerToolbar={false} allDaySlot={false} slotMinTime="07:00:00" slotMaxTime="20:00:00" slotDuration="00:30:00" nowIndicator height="auto" weekends events={calendarEvents} selectable={canCreate} selectMirror editable={canEdit} eventStartEditable={canEdit} eventDurationEditable={canEdit} dateClick={(info) => selectSlot(info.date, info.allDay ? 9 : info.date.getHours())} select={handleCalendarSelect} eventClick={(info) => setViewAppt(info.event.extendedProps.appointment)} eventDrop={saveCalendarMutation} eventResize={saveCalendarMutation} eventAllow={(dropInfo, draggedEvent) => canEdit && ["scheduled","confirmed"].includes(draggedEvent.extendedProps.appointment.status)} eventDidMount={(info) => { if (info.event.extendedProps.appointment.public_id === "__demo__") info.el.dataset.tour = "agenda-appt-demo"; }} datesSet={(info) => setCalendarTitle(calendarRangeLabel(info.view))} /></div>}</div>
        <aside className="agenda-sidebar"><div className="agenda-sidebar-card"><input className="agenda-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar mascota, cliente o motivo…" aria-label="Buscar citas" /><div style={{ borderTop:"1px solid var(--c-border)", marginTop:"14px", paddingTop:"14px" }}><p className="agenda-section-label">Estado</p><div className="agenda-filters">{STATUS_FILTERS.map(([value,label]) => <button key={value || "all"} className={`agenda-filter${statusFilter === value ? " is-active" : ""}`} onClick={() => setStatusFilter(value)}>{label}</button>)}</div></div><div style={{ borderTop:"1px solid var(--c-border)", marginTop:"14px", paddingTop:"14px" }}><p className="agenda-section-label">Veterinarios</p><div className="agenda-staff"><button className={`agenda-staff-button${filterVetId === "" ? " is-active" : ""}`} onClick={() => setFilterVetId("")}>Todos</button>{staff.map((member) => { const palette = vetPalette.get(member.id) || PAL.teal; const active = filterVetId === String(member.id); return <button key={member.id} className="agenda-staff-button" onClick={() => setFilterVetId((current) => current === String(member.id) ? "" : String(member.id))} style={{ background:active ? palette.border : palette.bg, borderColor:palette.border, color:active ? "#fff" : palette.text }}>{member.first_name} {member.last_name}</button>; })}</div></div></div><div className="agenda-sidebar-card"><MiniCalendar today={today} selectedDate={selectedSlot?.date} onSelect={(date) => { setWeekOffset(0); calendarRef.current?.getApi().gotoDate(date); }} /></div><div className="agenda-sidebar-card" data-tour="agenda-form">{canCreate ? <SidebarForm slot={selectedSlot} onSave={handleFormSave} onSaveWithPatient={handleSaveWithPatient} onClear={() => setSelectedSlot(null)} staff={staff} user={user} formRef={formRef} /> : <p style={{ color:"var(--c-text-3)", fontSize:"12.5px", fontStyle:"italic", textAlign:"center" }}>Modo lectura — sin permiso para crear citas</p>}</div><div className="agenda-stats">{[["Hoy",todayCount],["Esta semana",weekCount]].map(([label,count]) => <div key={label}><div style={{ color:"var(--c-primary-dark)", fontSize:"11px" }}>{label}</div><div style={{ color:"var(--c-primary-dark)", fontSize:"26px", fontWeight:750, lineHeight:1.15 }}>{count}</div><div style={{ color:"var(--c-primary-dark)", fontSize:"11px", opacity:.7 }}>cita{count !== 1 ? "s" : ""}</div></div>)}</div></aside></div>
        {viewAppt && <DetailModal appt={viewAppt} petName={viewAppt.pet_name || "—"} vetName={getVetName(viewAppt.veterinarian) || viewAppt.veterinarian_name} petId={viewAppt.pet_public_id} onClose={() => setViewAppt(null)} onStatusChange={handleStatusChange} onAttendNow={handleAttendNow} onEdit={(appointment) => { setEditingAppt(appointment); setViewAppt(null); }} onNewFromAppt={(appointment) => { setViewAppt(null); selectSlot(new Date(`${appointment.date}T${appointment.start_time}`), parseInt(appointment.start_time,10)); }} navigate={navigate} canEdit={canEdit} showHistory={!!orgSettings?.show_status_change_history} onRefresh={(updated) => { setAppointments((previous) => previous.map((item) => item.id === updated.id ? updated : item)); setViewAppt(updated); }} />}
        {createModalOpen && <AppointmentCreateModal slot={selectedSlot} onClose={() => { setCreateModalOpen(false); setSelectedSlot(null); }} onSave={handleFormSave} onSaveWithPatient={handleSaveWithPatient} staff={staff} user={user} formRef={formRef} />}
        {editingAppt && <EditModal appt={editingAppt} staff={staff} user={user} onClose={() => setEditingAppt(null)} onSave={handleEditSave} />}{walkInOpen && <WalkInModal staff={staff} user={user} allowAnonymousWalkIn={!!orgSettings?.allow_anonymous_walkin} onClose={() => setWalkInOpen(false)} onSave={handleWalkIn} />}{tour.active && <SpotlightTour steps={tour.steps} stepIdx={tour.stepIdx} onNext={tour.next} onPrev={tour.prev} onSkip={tour.skip} onFinish={tour.finish} />}
    </div>;
}

export default EventManagerAppointments;
