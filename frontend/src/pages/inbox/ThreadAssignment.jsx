import { useEffect, useRef, useState } from "react";
import { getAssignableUsers } from "../../api/inbox";
import { apiError } from "../../utils/apiError";
import styles from "./inbox.module.css";

export default function ThreadAssignment({ disabled, onAssign }) {
    const [open, setOpen] = useState(false);
    const [users, setUsers] = useState([]);
    const [selected, setSelected] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [attempt, setAttempt] = useState(0);
    const [submitting, setSubmitting] = useState(false);
    const pendingRef = useRef(false);
    const mountedRef = useRef(true);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    useEffect(() => {
        if (!open) return;
        const controller = new AbortController();
        getAssignableUsers({ signal: controller.signal }).then((data) => {
            if (!controller.signal.aborted) setUsers(data);
        }).catch((err) => {
            if (!controller.signal.aborted) setError(apiError(err, "No se pudo cargar el equipo"));
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [open, attempt]);

    const prepareLoad = () => {
        setLoading(true);
        setError("");
        setSelected("");
    };

    const submit = async (event) => {
        event.preventDefault();
        if (disabled || !selected || pendingRef.current) return;
        pendingRef.current = true;
        setSubmitting(true);
        try {
            const assigned = await onAssign(selected);
            if (assigned && mountedRef.current) setOpen(false);
        } finally {
            pendingRef.current = false;
            if (mountedRef.current) setSubmitting(false);
        }
    };

    return <div className={styles.assignment}>
        <button type="button" className="btn btn-secondary btn-xs" disabled={disabled || submitting}
            aria-expanded={open} onClick={() => { if (!open) prepareLoad(); setOpen(!open); }}>
            Asignar a…
        </button>
        {open && <form className={styles.assignmentForm} onSubmit={submit} aria-label="Asignar conversación">
            {loading ? <span role="status">Cargando equipo…</span> : error ? <>
                <span role="alert">{error}</span>
                <button type="button" className="btn btn-secondary btn-xs"
                    onClick={() => { prepareLoad(); setAttempt(attempt + 1); }}>Reintentar equipo</button>
            </> : users.length === 0 ? <span>No hay personas disponibles para responder.</span> : <>
                <label>Persona asignada
                    <select value={selected} disabled={disabled || submitting}
                        onChange={(event) => setSelected(event.target.value)}>
                        <option value="">Selecciona una persona</option>
                        {users.map((user) => <option key={user.public_id} value={user.public_id}>
                            {user.name}
                        </option>)}
                    </select>
                </label>
                <button type="submit" className="btn btn-primary btn-xs"
                    disabled={disabled || submitting || !selected}>
                    {submitting ? "Asignando…" : "Asignar"}
                </button>
            </>}
            <button type="button" className="btn btn-secondary btn-xs" disabled={submitting}
                onClick={() => setOpen(false)}>Cancelar asignación</button>
        </form>}
    </div>;
}
