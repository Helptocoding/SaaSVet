import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    claimConversation,
    closeConversation,
    getAgentSettings,
    getConversationMessages,
    getConversations,
    releaseConversation,
    sendInboxMessage,
    updateAgentSettings,
} from "../../api/inbox";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import EmptyState from "../../components/EmptyState";
import { Icon } from "../../components/icons";
import { apiError } from "../../utils/apiError";
import { toList } from "../../utils/toList";
import styles from "./inbox.module.css";

// Bandeja WhatsApp (É-F0 PR-7). Polling (patrón useDashboardSummary): la
// lista cada 20s, el transcript seleccionado cada 10s. En F0 todas las
// conversaciones las atiende un humano; el agente solo auto-saluda.

const LIST_POLL_MS = 20000;
const THREAD_POLL_MS = 10000;

const STATE_LABEL = {
    active: "Abierta",
    handoff_pending: "Esperando",
    human_active: "Atendida",
    closed: "Cerrada",
};
const STATE_BADGE = {
    active: "badge-info",
    handoff_pending: "badge-warning",
    human_active: "badge-purple",
    closed: "badge-default",
};

const FILTERS = [
    { value: "", label: "Abiertas" },
    { value: "human_active", label: "Atendidas" },
    { value: "closed", label: "Cerradas" },
];

const fmtTime = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    const sameDay = d.toDateString() === new Date().toDateString();
    return sameDay
        ? d.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleDateString("es-MX", { day: "2-digit", month: "short" });
};

const contactLabel = (conv) =>
    conv.owner_name || conv.contact_display_name || conv.contact_phone || "Sin nombre";

const AUTHOR_LABEL = {
    client: null,
    agent: "Asistente",
    system: "Automático",
};

const Inbox = () => {
    const { can } = useAuth();
    const confirm = useConfirm();

    const [conversations, setConversations] = useState([]);
    const [loadingList, setLoadingList] = useState(true);
    const [filter, setFilter] = useState("");
    const [selectedId, setSelectedId] = useState(null);
    const [thread, setThread] = useState(null); // { conversation, messages }
    const [body, setBody] = useState("");
    const [sending, setSending] = useState(false);
    const [acting, setActing] = useState(false);
    const [agentSettings, setAgentSettings] = useState(null);
    const threadEndRef = useRef(null);

    const canSend = can?.("agentinbox.send");
    const canClaim = can?.("agentinbox.claim");
    const canConfig = can?.("agentinbox.config");

    const loadList = useCallback(async () => {
        try {
            const data = await getConversations(filter ? { state: filter } : {});
            setConversations(toList(data));
        } catch (err) {
            console.error(apiError(err));
        } finally {
            setLoadingList(false);
        }
    }, [filter]);

    const loadThread = useCallback(async (publicId) => {
        if (!publicId) return;
        try {
            const data = await getConversationMessages(publicId);
            setThread(data);
        } catch (err) {
            toast.error(apiError(err, "No se pudo cargar la conversación"));
        }
    }, []);

    // Lista: carga inicial + polling.
    useEffect(() => {
        setLoadingList(true);
        loadList();
        const t = setInterval(loadList, LIST_POLL_MS);
        return () => clearInterval(t);
    }, [loadList]);

    // Transcript del seleccionado: carga + polling.
    useEffect(() => {
        if (!selectedId) { setThread(null); return; }
        loadThread(selectedId);
        const t = setInterval(() => loadThread(selectedId), THREAD_POLL_MS);
        return () => clearInterval(t);
    }, [selectedId, loadThread]);

    // Kill switch: solo si puede configurarlo.
    useEffect(() => {
        if (!canConfig) return;
        getAgentSettings()
            .then(setAgentSettings)
            .catch((err) => console.error(apiError(err)));
    }, [canConfig]);

    useEffect(() => {
        threadEndRef.current?.scrollIntoView({ block: "end" });
    }, [thread?.messages?.length]);

    const refreshAll = async () => {
        await Promise.all([loadList(), selectedId ? loadThread(selectedId) : null]);
    };

    const handleSend = async () => {
        const text = body.trim();
        if (!text) { toast.error("Escribe un mensaje"); return; }
        setSending(true);
        try {
            await sendInboxMessage(selectedId, text);
            setBody("");
            await refreshAll();
        } catch (err) {
            toast.error(apiError(err, "No se pudo enviar"));
        } finally {
            setSending(false);
        }
    };

    const runAction = async (fn, successMsg) => {
        setActing(true);
        try {
            await fn(selectedId);
            if (successMsg) toast.success(successMsg);
            await refreshAll();
        } catch (err) {
            if (err?.response?.status === 409) {
                toast.error(apiError(err, "Otra persona ya la está atendiendo"));
                await refreshAll();
            } else {
                toast.error(apiError(err, "Error inesperado"));
            }
        } finally {
            setActing(false);
        }
    };

    const handleClose = async () => {
        const ok = await confirm({
            message: "¿Cerrar esta conversación? Si el cliente vuelve a escribir se abrirá una nueva.",
            confirmText: "Cerrar conversación",
        });
        if (!ok) return;
        await runAction(closeConversation, "Conversación cerrada");
    };

    const handleToggleAgent = async () => {
        const next = !agentSettings?.enabled;
        try {
            const data = await updateAgentSettings({ enabled: next });
            setAgentSettings(data);
            toast.success(next ? "Respuestas automáticas activadas" : "Respuestas automáticas desactivadas");
        } catch (err) {
            toast.error(apiError(err, "No se pudo actualizar"));
        }
    };

    const conv = thread?.conversation;
    const isClosed = conv?.state === "closed";

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1>WhatsApp</h1>
                    <p className="page-subtitle">
                        Conversaciones con clientes — responde, toma o cierra cada hilo.
                    </p>
                </div>
                {canConfig && agentSettings !== null && (
                    <button
                        className={agentSettings.enabled ? "btn btn-secondary" : "btn btn-primary"}
                        onClick={handleToggleAgent}
                    >
                        {agentSettings.enabled ? "Desactivar respuestas automáticas" : "Activar respuestas automáticas"}
                    </button>
                )}
            </div>

            <div className={styles.layout}>
                {/* -------- Lista -------- */}
                <div className={styles.listPane}>
                    <div className={styles.filterRow}>
                        {FILTERS.map((f) => (
                            <button
                                key={f.value}
                                className={filter === f.value ? "btn btn-primary btn-xs" : "btn btn-secondary btn-xs"}
                                onClick={() => setFilter(f.value)}
                            >
                                {f.label}
                            </button>
                        ))}
                    </div>
                    <div className={styles.listScroll}>
                        {loadingList ? (
                            <div className={styles.emptyPane}>Cargando…</div>
                        ) : conversations.length === 0 ? (
                            <EmptyState
                                compact
                                icon={Icon.MessageCircle}
                                title="Sin conversaciones"
                                body="Cuando un cliente escriba al WhatsApp de la clínica, aparecerá aquí."
                            />
                        ) : (
                            conversations.map((c) => (
                                <button
                                    key={c.public_id}
                                    className={
                                        c.public_id === selectedId
                                            ? `${styles.convItem} ${styles.convItemActive}`
                                            : styles.convItem
                                    }
                                    onClick={() => setSelectedId(c.public_id)}
                                >
                                    <div className={styles.convTop}>
                                        <span className={styles.convName}>
                                            {c.has_unanswered && <span className={styles.unansweredDot} />}
                                            {contactLabel(c)}
                                        </span>
                                        <span className={styles.convTime}>{fmtTime(c.last_activity_at)}</span>
                                    </div>
                                    <div className={styles.convTop}>
                                        <span className={styles.convPreview}>{c.last_message_preview || "—"}</span>
                                        <span className={`badge ${STATE_BADGE[c.state] || "badge-default"}`}>
                                            {STATE_LABEL[c.state] || c.state}
                                        </span>
                                    </div>
                                </button>
                            ))
                        )}
                    </div>
                </div>

                {/* -------- Transcript -------- */}
                <div className={styles.chatPane}>
                    {!conv ? (
                        <div className={styles.emptyPane}>
                            Selecciona una conversación para ver los mensajes.
                        </div>
                    ) : (
                        <>
                            <div className={styles.chatHeader}>
                                <div>
                                    <strong>{contactLabel(conv)}</strong>
                                    {conv.contact_phone && (
                                        <span style={{ color: "var(--c-text-muted, #64748b)", marginLeft: 8, fontSize: 12.5 }}>
                                            {conv.contact_phone}
                                        </span>
                                    )}
                                    <span className={`badge ${STATE_BADGE[conv.state]}`} style={{ marginLeft: 8 }}>
                                        {STATE_LABEL[conv.state]}
                                    </span>
                                    {conv.claimed_by_name && (
                                        <span style={{ color: "var(--c-text-muted, #64748b)", marginLeft: 8, fontSize: 12 }}>
                                            Atiende: {conv.claimed_by_name}
                                        </span>
                                    )}
                                </div>
                                {canClaim && !isClosed && (
                                    <div className={styles.chatActions}>
                                        {conv.state !== "human_active" && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting}
                                                onClick={() => runAction(claimConversation)}>
                                                Tomar
                                            </button>
                                        )}
                                        {conv.state === "human_active" && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting}
                                                onClick={() => runAction(releaseConversation, "Conversación liberada")}>
                                                Liberar
                                            </button>
                                        )}
                                        <button className="btn btn-secondary btn-xs" disabled={acting} onClick={handleClose}>
                                            Cerrar
                                        </button>
                                    </div>
                                )}
                            </div>

                            <div className={styles.thread}>
                                {(thread?.messages || []).map((m) => (
                                    <div
                                        key={m.id}
                                        className={
                                            m.direction === "in"
                                                ? `${styles.bubble} ${styles.bubbleIn}`
                                                : `${styles.bubble} ${styles.bubbleOut}`
                                        }
                                    >
                                        {m.body || <em>[{m.payload_type}]</em>}
                                        <div className={styles.bubbleMeta}>
                                            {m.direction === "out" && (
                                                <span>
                                                    {m.author_type === "human_staff"
                                                        ? (m.human_author_name || "Staff")
                                                        : (AUTHOR_LABEL[m.author_type] || "")}
                                                </span>
                                            )}
                                            <span>{fmtTime(m.created_at)}</span>
                                            {m.direction === "out" && m.status === "failed" && (
                                                <span className={styles.bubbleFailed} title={m.failure_reason}>
                                                    no entregado
                                                </span>
                                            )}
                                            {m.direction === "out" && m.status === "pending" && <span>enviando…</span>}
                                        </div>
                                    </div>
                                ))}
                                <div ref={threadEndRef} />
                            </div>

                            {canSend && !isClosed && (
                                <div className={styles.composer}>
                                    <textarea
                                        className={styles.composerInput}
                                        placeholder="Escribe una respuesta…"
                                        value={body}
                                        maxLength={4000}
                                        onChange={(e) => setBody(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === "Enter" && !e.shiftKey) {
                                                e.preventDefault();
                                                if (!sending) handleSend();
                                            }
                                        }}
                                    />
                                    <button className="btn btn-primary" disabled={sending} onClick={handleSend}>
                                        <Icon.Send s={15} c="currentColor" />
                                        {sending ? "Enviando…" : "Enviar"}
                                    </button>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default Inbox;
