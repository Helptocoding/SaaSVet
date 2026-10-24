import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../auth/authContext";
import useMediaUrl, { acquireMediaUrl } from "./useMediaUrl";
import styles from "./inbox.module.css";

const mediaSize = (size) => Number.isFinite(size)
    ? (size >= 1024 * 1024 ? (size / (1024 * 1024)).toFixed(1) + " MB" : Math.ceil(size / 1024) + " KB") : "";
const typeLabels = { image: "Imagen", sticker: "Sticker", audio: "Audio", video: "Video", document: "Documento" };

export default function MediaBubble({ media, kind, caption = "" }) {
    const { user } = useAuth();
    const scope = JSON.stringify([user?.public_id || user?.id, user?.organization]);
    const frameRef = useRef(null), thumbnailRef = useRef(null), dialogRef = useRef(null);
    const downloadRef = useRef(null), downloadTimerRef = useRef(null);
    const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
    const [requested, setRequested] = useState(false);
    const [lightbox, setLightbox] = useState(false);
    const [documentState, setDocumentState] = useState({ loading: false, error: null });
    const [clock, setClock] = useState(() => Date.now());
    const expires = Date.parse(media.expires_at);
    const expired = media.status === "expired" || (Number.isFinite(expires) && clock >= expires);
    const ready = media.status === "ready" && !expired;
    const image = kind === "image" || kind === "sticker";
    const autoImage = image && (!media.file_size || media.file_size <= 5 * 1024 * 1024);
    const { url, error, loading, retry } = useMediaUrl(media.public_id, {
        scope, enabled: ready && kind !== "document" && ((autoImage && visible) || requested),
    });
    const failure = documentState.error || error;
    const unavailable = expired || failure?.response?.status === 410;
    const label = typeLabels[kind] || "Archivo";
    const weight = mediaSize(media.file_size);
    const name = media.filename || label;
    const ratio = media.width > 0 && media.height > 0 ? String(media.width) + "/" + String(media.height) : "4/3";

    useEffect(() => {
        if (typeof IntersectionObserver === "undefined") return;
        const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { rootMargin: "200px" });
        observer.observe(frameRef.current);
        return () => observer.disconnect();
    }, []);
    useEffect(() => {
        if (!ready || !Number.isFinite(expires)) return;
        const remaining = expires - Date.now();
        const timer = setTimeout(() => setClock(Date.now()), Math.max(1, Math.min(remaining + 1, 2147483647)));
        return () => clearTimeout(timer);
    }, [ready, expires, clock]);
    useEffect(() => {
        const handleRef = downloadRef, timerRef = downloadTimerRef;
        return () => { clearTimeout(timerRef.current); handleRef.current?.release(); handleRef.current = null; };
    }, [scope, media.public_id, ready]);

    const downloadDocument = async () => {
        if (!ready || documentState.loading) return;
        const handle = acquireMediaUrl(media.public_id, scope);
        downloadRef.current?.release();
        downloadRef.current = handle;
        setDocumentState({ loading: true, error: null });
        try {
            const blobUrl = await handle.promise;
            if (downloadRef.current !== handle) return;
            const anchor = document.createElement("a");
            anchor.href = blobUrl;
            anchor.download = name;
            anchor.click();
            downloadTimerRef.current = setTimeout(() => {
                handle.release();
                if (downloadRef.current === handle) {
                    downloadRef.current = null;
                    setDocumentState({ loading: false, error: null });
                }
            }, 1000);
        } catch (reason) {
            handle.release();
            if (downloadRef.current === handle && reason.name !== "AbortError") {
                downloadRef.current = null;
                setDocumentState({ loading: false, error: reason });
            }
        }
    };
    const closeLightbox = () => {
        dialogRef.current?.close();
        setLightbox(false);
        thumbnailRef.current?.focus();
    };
    let content;
    if (unavailable) {
        content = <span role="status">Archivo expirado</span>;
    } else if (media.status === "failed") {
        content = <span role="status">Archivo no disponible (falló la recepción)</span>;
    } else if (!ready) {
        content = <span role="status">Recibiendo archivo…</span>;
    } else if (failure) {
        content = <><span role="alert">No se pudo cargar el archivo</span>
            <button type="button" className={styles.mediaButton} onClick={kind === "document" ? downloadDocument : retry}>Reintentar archivo</button></>;
    } else if (loading || documentState.loading) {
        content = <span role="status" aria-busy="true">Cargando archivo…</span>;
    } else if (kind === "document") {
        content = <><strong className={styles.mediaFilename}>{name}</strong><span>{weight}</span>
            <button type="button" className={styles.mediaButton} onClick={downloadDocument}>Descargar documento</button></>;
    } else if (url && image) {
        content = <button type="button" ref={thumbnailRef} className={styles.mediaThumbnail} aria-label="Ampliar imagen"
            onClick={() => { setRequested(true); setLightbox(true); }}><img src={url} loading="lazy" alt={caption || name} /></button>;
    } else if (url && kind === "audio") {
        content = <audio controls preload="metadata" src={url} aria-label="Audio recibido" />;
    } else if (url && kind === "video") {
        content = <video controls preload="metadata" src={url} aria-label="Video recibido" />;
    } else {
        content = <button type="button" className={styles.mediaButton} onClick={() => setRequested(true)}>
            {"Cargar " + label.toLowerCase() + (weight ? " · " + weight : "")}</button>;
    }
    return (
        <div ref={frameRef} className={styles.mediaCard} aria-label={label + " recibido"}>
            <div className={image || kind === "video" ? styles.mediaFrame : styles.mediaContent}
                style={image || kind === "video" ? { aspectRatio: ratio } : undefined}>{content}</div>
            {lightbox && ready && url && image && <dialog className={styles.mediaLightbox}
                aria-label="Imagen ampliada" ref={(node) => { dialogRef.current = node; if (node && !node.open) node.showModal(); }}
                onCancel={(event) => { event.preventDefault(); closeLightbox(); }}
                onClick={(event) => { if (event.target === event.currentTarget) closeLightbox(); }}>
                <button type="button" className={styles.mediaButton} onClick={closeLightbox}>Cerrar imagen</button>
                <img src={url} alt={caption || name} />
            </dialog>}
        </div>
    );
}
