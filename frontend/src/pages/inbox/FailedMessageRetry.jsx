import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { retryInboxMessage } from "../../api/inbox";
import { apiError } from "../../utils/apiError";
import { phoneHref } from "./messageText";
import styles from "./inbox.module.css";

const windowFailure = (reason) => /ventana|session_window_closed|meta_131047|window_closed/i.test(reason || "");

export default function FailedMessageRetry({ message, sessionId, canSend, phone, onRetried }) {
    const [busy, setBusy] = useState(false);
    const [windowClosed, setWindowClosed] = useState(false);
    const controllerRef = useRef(null);
    useEffect(() => () => controllerRef.current?.abort(), []);

    if (message.direction !== "out" || message.status !== "failed") return null;
    const closed = windowClosed || windowFailure(message.failure_reason);
    const canRetry = canSend && sessionId && message.conversation_public_id === sessionId
        && !message.acceptance_known && !message.provider_accepted_at
        && !message.delivered_at && !message.read_at && !message.uncertain_at;
    const retry = async () => {
        if (controllerRef.current) return;
        const controller = new AbortController();
        controllerRef.current = controller;
        setBusy(true);
        try {
            const result = await retryInboxMessage(sessionId, message.id,
                message.client_message_id, { signal: controller.signal });
            if (controller.signal.aborted) return;
            if (result?.id !== message.id) throw new Error("El reintento no confirmó el mensaje original.");
            setWindowClosed(false);
            onRetried(result);
        } catch (error) {
            if (controller.signal.aborted) return;
            if (error?.response?.data?.code === "window_closed") setWindowClosed(true);
            else toast.error(apiError(error, "No se pudo reintentar el mensaje"));
        } finally {
            if (!controller.signal.aborted) setBusy(false);
            controllerRef.current = null;
        }
    };
    return <>
        {closed && <span className={styles.retryWindowHint}>
            Ventana de WhatsApp cerrada{phone ? <> — llámala al {phoneHref(phone)
                ? <a href={phoneHref(phone)}>{phone}</a> : phone}</> : " — contacta por teléfono"}
        </span>}
        {canRetry && <button type="button" className={styles.retrySend} disabled={busy}
            onClick={retry}>{busy ? "Reintentando…" : "Reintentar"}</button>}
    </>;
}
