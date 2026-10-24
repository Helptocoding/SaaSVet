import { phoneHref } from "./messageText";
import styles from "./inbox.module.css";

export default function SessionWindowNotice({ window, phone }) {
    if (["open", "inactive"].includes(window.state)) return null;
    const closed = window.state === "closed";
    const minutes = window.minutes;
    const remaining = minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min`
        : minutes > 0 ? `${minutes} min` : "menos de 1 min";
    return <div id="inbox-session-window" role="status"
        className={`${styles.sessionWindow} ${closed ? styles.sessionWindowClosed : ""}`}>
        {window.state === "closing" ? `Respondes dentro de la ventana de 24 h · cierra en ${remaining}`
            : closed ? <>Ventana de WhatsApp cerrada. Espera un nuevo mensaje del cliente
                {phoneHref(phone) ? <> o llama al <a href={phoneHref(phone)}>{phone}</a>.</> : " o contacta por teléfono."}</>
                : "No se pudo comprobar la ventana de WhatsApp. Actualiza la conversación para responder."}
    </div>;
}
