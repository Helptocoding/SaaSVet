import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { sendSupportMessage } from "../api/support";
import { apiError } from "../utils/apiError";
import { Icon } from "./icons";
import s from "./FeedbackButton.module.css";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024; // 5MB — espejo del límite del backend

// «Reportar un problema». Vive en la barra superior junto a la campana (plan UX
// D3): antes era un botón flotante con «?» que tapaba la última columna de
// acciones de las tablas y prometía ayuda en vez de un reporte.
const FeedbackButton = () => {
    const [open, setOpen] = useState(false);
    const [message, setMessage] = useState("");
    const [image, setImage] = useState(null);
    const [sending, setSending] = useState(false);
    const fileInputRef = useRef(null);
    const titleId = useId();
    const messageId = useId();

    const close = () => { if (!sending) setOpen(false); };

    useEffect(() => {
        if (!open) return undefined;
        const onKey = (e) => { if (e.key === "Escape" && !sending) setOpen(false); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, sending]);

    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (file) {
            if (file.size > MAX_IMAGE_BYTES) {
                toast.error("La imagen es demasiado grande (máx. 5 MB)");
                return;
            }
            setImage(file);
        }
    };

    const handleSend = async () => {
        if (!message.trim()) {
            toast.error("Describe el problema.");
            return;
        }

        setSending(true);
        try {
            await sendSupportMessage({
                message: message,
                pageUrl: window.location.href,
                timestamp: new Date().toISOString(),
                image: image,
            });
            toast.success("Reporte enviado. ¡Gracias!");
            setOpen(false);
            setMessage("");
            setImage(null);
        } catch (err) {
            toast.error(apiError(err, "No se pudo enviar el reporte. Intenta más tarde."));
        } finally {
            setSending(false);
        }
    };

    return (
        <>
            <button
                type="button"
                className={s.trigger}
                onClick={() => setOpen(true)}
                aria-label="Reportar un problema"
                title="Reportar un problema"
            >
                <Icon.ReportProblem s={20} />
            </button>

            {/* Portal: la barra superior es sticky con desenfoque, y eso encierra
                un `position: fixed` dentro de ella (el modal salía cortado). */}
            {open && createPortal(
                <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && close()}>
                    <div className="modal modal-sm" role="dialog" aria-modal="true" aria-labelledby={titleId}>
                        <div className="modal-header">
                            <h3 id={titleId}>Reportar un problema</h3>
                            <button type="button" className="modal-close" onClick={close} disabled={sending} aria-label="Cerrar">
                                <Icon.X s={14} />
                            </button>
                        </div>
                        <div className="modal-body">
                            <p className={s.lead}>Describe qué pasó y, si ayuda, adjunta una captura.</p>
                            <p className={s.warning}>
                                <Icon.AlertTriangle s={14} />
                                <span>No incluyas datos de pacientes (nombres, historiales, cobros) en el texto ni en la captura.</span>
                            </p>

                            <div className="form-group">
                                <label className="form-label" htmlFor={messageId}>Qué pasó</label>
                                <textarea
                                    id={messageId}
                                    className="textarea-input"
                                    value={message}
                                    onChange={(e) => setMessage(e.target.value)}
                                    placeholder="Ej.: no aparece el botón de imprimir en Cobros"
                                    rows={4}
                                    disabled={sending}
                                />
                            </div>

                            <input
                                type="file"
                                accept="image/*"
                                onChange={handleFileChange}
                                ref={fileInputRef}
                                hidden
                            />
                            <button
                                type="button"
                                className={`btn btn-secondary btn-sm ${s.attach}`}
                                onClick={() => fileInputRef.current.click()}
                                disabled={sending}
                            >
                                <Icon.Paperclip s={14} />
                                {image ? `Captura adjunta: ${image.name}` : "Adjuntar captura de pantalla"}
                            </button>
                        </div>
                        <div className="modal-footer">
                            <button type="button" className="btn btn-secondary btn-md" onClick={close} disabled={sending}>
                                Cancelar
                            </button>
                            <button type="button" className="btn btn-primary btn-md" onClick={handleSend} disabled={sending}>
                                {sending ? "Enviando…" : "Enviar reporte"}
                            </button>
                        </div>
                    </div>
                </div>,
                document.body,
            )}
        </>
    );
};

export default FeedbackButton;
