import { useState } from "react";
import { getImportConflicts } from "../../api/imports";
import { apiError } from "../../utils/apiError";
import ConflictCard from "./ConflictCard";
import s from "./imports.module.css";

// Una sola página en memoria; los cursores quedan ligados a la versión del job.
// `cfg` es la configuración de la entidad: las tarjetas son las mismas que en la muestra.
export default function ConflictPages({ publicId, report, highTotal, uncertainTotal, cfg }) {
    const [page, setPage] = useState(null);
    const [cursors, setCursors] = useState([null]);
    const [index, setIndex] = useState(0);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    if (!publicId || !report || !report.total) return null;

    const load = async (cursor, target, history) => {
        if (busy) return;
        setBusy(true);
        setError("");
        try {
            const response = await getImportConflicts(publicId, {
                version: report.version, ...(cursor ? { cursor } : {}),
            });
            setPage(response);
            setIndex(target);
            setCursors(history);
        } catch (err) {
            setError(apiError(err, "No se pudo cargar el detalle. Actualiza la vista e inténtalo de nuevo."));
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className={s.omittedReasonBlock} aria-label="Detalle de conflictos">
            <h3 className={s.omittedReasonTitle}>Detalle completo de conflictos</h3>
            <p>Coincidencias altas: {highTotal} · Por revisar: {uncertainTotal}</p>
            {!page && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => load(null, 0, [null])}>Ver detalle</button>}
            {error && <p role="alert">{error}</p>}
            {page && <>
                <p className={s.previewShowing}>Mostrando {page.results.length} de {page.total} · Página {index + 1}</p>
                {!page.complete && <p role="status">El reporte histórico está incompleto: hay {page.available} detalles conservados.</p>}
                {['high', 'uncertain'].map(level => {
                    const entries = page.results.filter(item => level === 'high' ? item.match_confidence === 'high' : item.match_confidence !== 'high');
                    return entries.length > 0 && <div key={level}>
                        <h4>{level === 'high' ? 'Coincidencias altas' : 'Por revisar'}</h4>
                        {entries.map((item, i) => <ConflictCard key={`${item.row}-${i}`} conflict={item} cfg={cfg} />)}
                    </div>;
                })}
                <button type="button" className="btn btn-secondary btn-sm" disabled={busy || index === 0} onClick={() => load(cursors[index - 1], index - 1, cursors)}>Anterior</button>{' '}
                <button type="button" className="btn btn-secondary btn-sm" disabled={busy || !page.next_cursor} onClick={() => load(page.next_cursor, index + 1, [...cursors.slice(0, index + 1), page.next_cursor])}>Siguiente</button>
            </>}
        </section>
    );
}
