import { useEffect, useRef, useState } from "react";
import { getThreadContext } from "../../api/inbox";
import { apiError } from "../../utils/apiError";
import { statusLabel } from "../../utils/appointmentStatus";
import { formatDate } from "../../utils/datetime";
import { phoneHref } from "./messageText";
import styles from "./inbox.module.css";

export default function ThreadContextPanel({ contactId, accountId, canOpenPet, onOpenPet }) {
    const [open, setOpen] = useState(false);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const controllerRef = useRef(null);
    useEffect(() => () => controllerRef.current?.abort(), []);
    const load = async () => {
        controllerRef.current?.abort();
        const controller = new AbortController();
        controllerRef.current = controller;
        setLoading(true); setError(""); setData(null);
        try {
            const result = await getThreadContext(contactId, accountId, { signal: controller.signal });
            if (!controller.signal.aborted) setData(result);
        } catch (err) {
            if (!controller.signal.aborted) setError(apiError(err, "No se pudo cargar el contexto del cliente"));
        } finally {
            if (!controller.signal.aborted) setLoading(false);
        }
    };
    const toggle = () => {
        if (open) {
            controllerRef.current?.abort();
            setOpen(false); setData(null); setError(""); setLoading(false);
        } else {
            setOpen(true);
            load();
        }
    };
    const appointment = data?.last_appointment;
    const href = phoneHref(data?.owner?.phone || "");
    return <section className={styles.contextPanel} aria-label="Contexto del cliente">
        <button type="button" className={styles.contextToggle} aria-expanded={open}
            aria-controls="inbox-client-context" onClick={toggle}>
            {open ? "Ocultar contexto del cliente" : "Ver contexto del cliente"}
            <span aria-hidden="true">{open ? "−" : "+"}</span>
        </button>
        {open && <div id="inbox-client-context" className={styles.contextBody}>
            {loading && <p role="status">Cargando contexto del cliente…</p>}
            {error && <div role="alert"><p>{error}</p>
                <button type="button" className="btn btn-secondary btn-xs" onClick={load}>Reintentar contexto</button>
            </div>}
            {data && !data.owner && <p>Este contacto aún no tiene un cliente vinculado.</p>}
            {data?.owner && <>
                <dl className={styles.contextOwner}>
                    <dt>Cliente</dt><dd>{data.owner.name}</dd>
                    <dt>Teléfono del cliente</dt><dd>{href ? <a href={href}>{data.owner.phone}</a>
                        : data.owner.phone || "Sin teléfono registrado"}</dd>
                </dl>
                <h3 className={styles.contextHeading}>Mascotas</h3>
                {data.pets.length === 0 ? <p>No tiene mascotas registradas.</p> : (
                    <ul className={styles.contextPets}>{data.pets.map((pet) => (
                        <li key={pet.public_id} className={styles.contextPet}>
                            <span><strong>{pet.name}</strong><span className={styles.contextSpecies}>
                                {pet.species || "Especie pendiente"}</span></span>
                            {canOpenPet && <button type="button" className="btn btn-secondary btn-xs"
                                aria-label={`Abrir expediente de ${pet.name}`}
                                onClick={() => onOpenPet(pet.public_id)}>Abrir expediente</button>}
                        </li>
                    ))}</ul>
                )}
                <p className={styles.contextLastAppointment}>Última cita: {appointment ? <>
                    <time dateTime={appointment.date}>{formatDate(`${appointment.date}T00:00:00Z`, "UTC", "es-MX")}</time>
                    {" · "}{statusLabel(appointment.status)}
                </> : "Sin citas anteriores"}</p>
            </>}
        </div>}
    </section>;
}
