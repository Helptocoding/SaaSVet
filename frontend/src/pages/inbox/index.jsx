import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import {
    assignConversation,
    authorizeIdentityLink,
    claimConversation,
    closeConversation,
    getAgentSettings,
    getThreadMessages,
    getThreads,
    getInboxMetrics,
    getWhatsappToken,
    releaseConversation,
    resetContactIdentity,
    sendInboxMessage,
    setWhatsappToken,
    unlinkFamily,
    updateAgentSettings,
    verifyContactIdentity,
} from "../../api/inbox";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import EmptyState from "../../components/EmptyState";
import { Icon } from "../../components/icons";
import { apiError } from "../../utils/apiError";
import { clockTimeOrg, fmtTimeOrg, groupMessagesByDay, orgTz } from "../../utils/datetime";
import { newIdempotencyKey } from "../../utils/idempotency";
import { toList } from "../../utils/toList";
import DeliveryTicks from "./DeliveryTicks";
import FailedMessageRetry from "./FailedMessageRetry";
import SessionWindowNotice from "./SessionWindowNotice";
import ThreadContextPanel from "./ThreadContextPanel";
import ThreadAssignment from "./ThreadAssignment";
import { getSessionWindow } from "./sessionWindow";
import { groupConsecutiveMessages } from "./messageGroups";
import MessageBody from "./MessageBody";
import ReplyQuote from "./ReplyQuote";
import MediaBubble from "./MediaBubble";
import { phoneHref } from "./messageText";
import useInboxTitle from "./useInboxTitle";
import usePollingWhenVisible from "../../hooks/usePollingWhenVisible";
import ContactVerificationBadge from "./ContactVerificationBadge";
import ThreadViewport from "./ThreadViewport";
import useThreadHistory from "./useThreadHistory";
import useThreadRead from "./useThreadRead";
import { compareMessages } from "./threadMessages";
import { fetchSynced, mergeListPacket, mergeTranscriptPacket } from "./inboxSync";
import { InboxConnectionBanner, InboxLoadError, InboxLoading } from "./InboxLoadState";
import styles from "./inbox.module.css";

// Bandeja WhatsApp (É-F0 PR-7). Polling (patrón useDashboardSummary): la
// lista cada 20s, el transcript seleccionado cada 10s. En F0 todas las
// conversaciones las atiende un humano; el agente solo auto-saluda.

const LIST_POLL_MS = 20000;
const THREAD_POLL_MS = 10000;
const INBOX_CLOCK_TICK_MS = 60000;
const MAX_PENDING_SEND_ATTEMPTS = 20;
const COMPOSER_MAX_LENGTH = 4000;
const COMPOSER_MAX_HEIGHT = 120;
const EMPTY_LOAD_STATE = { loading: false, error: "", failures: 0 };

const uniqueThreads = (rows) => [...new Map(rows.map((row) => [
    JSON.stringify([row.contact_public_id, row.channel_account_public_id]), row,
])).values()];

const nextThreadOffset = (data, offset) => (
    data?.has_more === true && Number.isSafeInteger(data.next_offset) && data.next_offset > offset
        ? data.next_offset : null
);

const removePendingAttempt = (registry, sessionId, clientMessageId) => {
    const sessionAttempts = registry.get(sessionId);
    if (!sessionAttempts) return;
    sessionAttempts.delete(clientMessageId);
    if (sessionAttempts.size === 0) registry.delete(sessionId);
};

const registerPendingAttempt = (registry, attempt) => {
    let sessionAttempts = registry.get(attempt.sessionId);
    if (!sessionAttempts) {
        sessionAttempts = new Map();
        registry.set(attempt.sessionId, sessionAttempts);
    }
    sessionAttempts.set(attempt.clientMessageId, attempt);

    let total = [...registry.values()].reduce((sum, attempts) => sum + attempts.size, 0);
    while (total > MAX_PENDING_SEND_ATTEMPTS) {
        let oldestAttempt = null;
        for (const attempts of registry.values()) {
            for (const candidate of attempts.values()) {
                if (!oldestAttempt || candidate.sequence < oldestAttempt.sequence) {
                    oldestAttempt = candidate;
                }
            }
        }
        if (!oldestAttempt) break;
        removePendingAttempt(
            registry,
            oldestAttempt.sessionId,
            oldestAttempt.clientMessageId
        );
        total -= 1;
    }
};

const mergeServerMessage = (messages, serverMessage) => {
    const serverId = serverMessage?.id;
    const clientMessageId = serverMessage?.client_message_id;
    return [...messages.filter((message) => (
        message.id !== serverId
        && (!clientMessageId || message.client_message_id !== clientMessageId)
    )), serverMessage].sort(compareMessages);
};

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

// El HILO no tiene estado —lo tiene su sesión vigente—, así que el filtro es
// otro: o hay algo abierto, o el hilo está archivado.
const FILTERS = [
    { value: "", label: "Activas" },
    { value: "archived", label: "Archivadas" },
];

const contactLabel = (conv) =>
    conv.owner_name || conv.contact_display_name || conv.contact_phone || "Sin nombre";

const threadPreview = (row) => row.last_message_preview || ({
    image: "📷 Foto", audio: "🎤 Nota de voz", video: "🎬 Video", sticker: "Sticker",
    document: "📄 " + (row.last_message_filename || "Documento"),
}[row.last_message_type]) || "—";

const AUTHOR_LABEL = {
    client: null,
    agent: "Asistente",
    system: "Automático",
};

// Tile de métricas de negocio del piloto F2 (spec §8): read-only, últimos 30d.
const MetricsBar = ({ metrics }) => {
    if (!metrics) return null;
    const pct = Math.round((metrics.tasa_conversion || 0) * 100);
    const cards = [
        { value: metrics.conversaciones_iniciadas, label: "Conversaciones" },
        { value: metrics.con_intencion_agendar, label: "Con intención" },
        { value: metrics.citas_creadas, label: "Citas creadas" },
        { value: `${pct}%`, label: "Conversión" },
        { value: metrics.citas_abandonadas, label: "Abandonadas" },
        { value: metrics.cancelaciones, label: "Cancelaciones" },
        { value: metrics.handoffs?.total ?? 0, label: "A un humano" },
    ];
    return (
        <div className={styles.metricsBar}>
            {cards.map((c) => (
                <div key={c.label} className={styles.metricCard}>
                    <div className={styles.metricValue}>{c.value}</div>
                    <div className={styles.metricLabel}>{c.label}</div>
                </div>
            ))}
        </div>
    );
};

/** Tipos de evidencia — espejo del enum del backend (ADR p57 §5.5.3).
 *
 * Ninguna opción se basa en el número que escribe: ese ya se sabe que coincide
 * —es lo que creó el caso— y usarlo como prueba sería circular. `callback` es
 * llamar al teléfono DEL EXPEDIENTE, que es otra cosa.
 */
const EVIDENCE_KINDS = [
    { value: "in_person_id", label: "Identificación en mostrador" },
    { value: "known_record", label: "Datos del expediente que solo el titular sabe" },
    { value: "callback", label: "Llamada al teléfono del expediente" },
    { value: "other", label: "Otra (detállala en la nota)" },
];

/** Caso de identidad abierto: qué pidió el cliente y las dos acciones.
 *
 * Presentacional: no conoce RBAC ni llama a la API. El caller le pasa
 * `canVerify` ya resuelto y los handlers — mismo patrón que `EmptyState`.
 */
const IdentityCaseBanner = ({
    identityCase, canVerify, acting, onVerify, onAuthorize,
}) => {
    const { kind, requested, candidate, last_verification: last } = identityCase;
    const approvedHere = last?.decision === "approved" && last?.applies_to_this_case;

    return (
        <div className={styles.identityCase}>
            <div>
                <strong>Verificación de identidad requerida</strong>
                <p className={styles.identityCaseBody}>
                    {kind === "owner_ambiguous"
                        ? "Este teléfono tiene varios expedientes. Hay que ordenarlos antes de vincular a nadie."
                        : `Este número ya pertenece a un cliente registrado${candidate ? ` (${candidate.name})` : ""}. El teléfono localiza, no autoriza: confirma quién es antes de vincular.`}
                </p>
                {requested && (
                    <p className={styles.identityCaseBody}>
                        Pidió: <strong>{requested.owner_name}</strong> · {requested.pet_name}
                        {requested.pet_species ? ` (${requested.pet_species})` : ""}
                        {requested.date ? ` · ${requested.date} ${requested.start_time}` : ""}
                    </p>
                )}
                {last && (
                    <p className={styles.identityCaseBody}>
                        Última verificación: <strong>{last.decision === "approved" ? "aprobada" : "rechazada"}</strong>
                        {" · "}{last.actor}
                        {!last.applies_to_this_case && " (de un caso anterior — no cuenta aquí)"}
                    </p>
                )}
            </div>
            {canVerify && (
                <div className={styles.chatActions}>
                    <button className="btn btn-secondary btn-xs"
                        disabled={acting || !candidate}
                        title={candidate
                            ? "Registra que comprobaste la identidad con evidencia externa al teléfono"
                            : "Con varios expedientes no hay candidato: hay que ordenarlos primero"}
                        onClick={onVerify}>
                        Registrar verificación
                    </button>
                    <button className="btn btn-primary btn-xs"
                        disabled={acting || !approvedHere || !candidate}
                        title={approvedHere
                            ? "Vincula este número al cliente verificado"
                            : "Primero registra una verificación aprobada de este caso"}
                        onClick={onAuthorize}>
                        Autorizar vínculo
                    </button>
                </div>
            )}
        </div>
    );
};

/* Por qué el caso llegó a una persona.
 *
 * `reason` clasifica y `detail` informa: el backend manda los dos porque
 * "baja confianza" no le dice nada a recepción y "se atascó pidiendo datos"
 * sí. El texto se compone aquí —no en la API— por la misma razón que
 * `APPT_STATUS_LABEL`: las etiquetas de UI son del frontend. Lo que sí viene
 * del dominio son los `label` de cada dato, que viven junto al dato en
 * `goals.py` para que no haya dos vocabularios.
 */
const HANDOFF_REASON = {
    explicit_request: "El cliente pidió hablar con una persona.",
    emergency: "Posible urgencia clínica.",
    safety_urgent: "Safety · Revisión urgente del equipo.",
    policy_block: "El asistente tiene prohibido resolver esto solo.",
    low_confidence: "El asistente no pudo avanzar.",
    tool_failure: "Falló una operación del sistema.",
    identity: "Hay que verificar la identidad antes de continuar.",
    budget_exhausted: "La conversación se alargó demasiado sin resolverse.",
};

const HANDOFF_DETAIL = {
    goal_stalled: "Pidió el mismo dato tres veces sin obtenerlo.",
    llm_error: "El servicio de IA no respondió.",
    commit_failed: "La operación falló justo al confirmarla.",
    owner_exists: "El teléfono ya pertenece a un cliente registrado.",
    owner_ambiguous: "El teléfono tiene varios expedientes.",
};

export const HandoffReasonBanner = ({ handoff }) => {
    const { reason, detail, goal } = handoff;
    const headline = HANDOFF_REASON[reason] || "El asistente pasó el caso al equipo.";
    const nuance = HANDOFF_DETAIL[detail];

    return (
        <div className={styles.handoffReason}>
            <strong>{headline}</strong>
            {handoff.state && <p className={styles.handoffReasonBody}>
                {handoff.state === "ACKNOWLEDGED" ? "Acuse explícito registrado" : "En bandeja · Pendiente de acuse"}
                {handoff.opened_at && <> · Creado: {new Date(handoff.opened_at).toLocaleString()}</>}
            </p>}
            {handoff.notification_status === "NOT_CONFIGURED" && <p className={styles.handoffReasonBody}>
                Sin canal secundario de aviso. Estar en bandeja no confirma atención.
            </p>}
            {handoff.open_cases?.length > 1 && <ul>
                {handoff.open_cases.map((entry) => <li key={entry.id}>
                    {HANDOFF_REASON[entry.reason] || entry.reason} · {entry.priority === "urgent" ? "Urgente" : "Normal"}
                    {" · "}{entry.state === "ACKNOWLEDGED" ? "Acuse registrado" : "Pendiente de acuse"}
                    {" · "}{new Date(entry.opened_at).toLocaleString()}
                </li>)}
            </ul>}
            {handoff.guidance_status && <p className={styles.handoffReasonBody}>
                Guía al cliente: {handoff.guidance_status === "uncertain" ? "envío incierto" :
                    handoff.guidance_status === "failed" ? "envío fallido" :
                    handoff.guidance_status === "discarded" ? "descartada sin envío" :
                    handoff.guidance_status === "read" ? "leída" :
                    handoff.guidance_status === "delivered" ? "entregada" :
                    handoff.guidance_status === "sent" ? "aceptada por proveedor" : "pendiente de entrega"}.
            </p>}
            {nuance && <p className={styles.handoffReasonBody}>{nuance}</p>}
            {goal?.promise && (
                <p className={styles.handoffReasonBody}>
                    Quería <strong>{goal.promise}</strong>.
                    {goal.captured.length > 0 && (
                        <> Ya tenía: {goal.captured.map((c) => `${c.label} (${c.value})`).join(" · ")}.</>
                    )}
                </p>
            )}
            {goal?.missing?.length > 0 && (
                <p className={styles.handoffReasonBody}>
                    Le faltaba: <strong>{goal.missing.map((m) => m.label).join(" · ")}</strong>.
                </p>
            )}
        </div>
    );
};

const DateDivider = ({ label }) => (
    <div className={styles.dateDivider} role="separator" aria-label={label}>
        <span>{label}</span>
    </div>
);

const Inbox = () => {
    const { can, user } = useAuth();
    const confirm = useConfirm();
    const navigate = useNavigate();

    const [conversations, setConversations] = useState([]);
    useInboxTitle(conversations);
    const [loadingList, setLoadingList] = useState(true);
    const [listLoad, setListLoad] = useState(EMPTY_LOAD_STATE);
    const [hasMoreThreads, setHasMoreThreads] = useState(false);
    const [loadingMoreThreads, setLoadingMoreThreads] = useState(false);
    const [moreThreadsError, setMoreThreadsError] = useState("");
    const [filter, setFilter] = useState("");
    const [attention, setAttention] = useState("");
    const [urgentOnly, setUrgentOnly] = useState(false);
    const [mineOnly, setMineOnly] = useState(false);
    const [searchText, setSearchText] = useState("");
    const [searchQuery, setSearchQuery] = useState("");
    const searchRef = useRef(null);
    // La selección es el HILO —la persona—, no el episodio: `{contact, account}`.
    // Las ACCIONES siguen apuntando a la sesión vigente (`thread.conversation`),
    // porque de ella cuelgan el claim, el hand-off y los compromisos.
    const [selectedThread, setSelectedThread] = useState(null);
    const [thread, setThread] = useState(null); // Metadatos de la sesión vigente.
    const [threadLoad, setThreadLoad] = useState(EMPTY_LOAD_STATE);
    const [body, setBody] = useState("");
    const [replyTarget, setReplyTarget] = useState(null);
    const [acting, setActing] = useState(false);
    const actionInFlightRef = useRef(false);
    const [agentSettings, setAgentSettings] = useState(null);
    const [metrics, setMetrics] = useState(null);
    const [tokenStatus, setTokenStatus] = useState(null);
    const [tokenInput, setTokenInput] = useState("");
    const [savingToken, setSavingToken] = useState(false);
    const [timeReference, setTimeReference] = useState(() => new Date());
    const [optimisticMessages, setOptimisticMessages] = useState([]);
    const [unreadTotal, setUnreadTotal] = useState(0);
    const [firstUnreadId, setFirstUnreadId] = useState(null);
    const threadViewportRef = useRef(null);
    const { transcriptMessages, nextBefore, olderLoad, newBelow, jumpLoad, highlightedId, captureScroll,
        trackScroll, goToEnd, receiveLatest, updateMessages, resetHistory, loadOlder, getSyncFloor,
        jumpToMessage, isJumping } = useThreadHistory(
        threadViewportRef, { optimisticMessages, sessionId: thread?.conversation?.public_id || null,
            layoutKey: firstUnreadId }
    );
    const composerRef = useRef(null);
    const threadLoadRequestRef = useRef(0);
    const listLoadRequestRef = useRef(0);
    const listControllerRef = useRef(null);
    const threadControllerRef = useRef(null);
    const listPagesRef = useRef(new Map());
    const threadSnapshotRef = useRef(null);
    const loadedListPagesRef = useRef(1);
    const nextListOffsetRef = useRef(null);
    const loadingMoreThreadsRef = useRef(false);
    const selectedThreadRef = useRef(null);
    const activeSessionIdRef = useRef(null);
    const selectionRevisionRef = useRef(0);
    const draftRevisionRef = useRef(0);
    const pendingSendAttemptsRef = useRef(new Map());
    const optimisticMessagesRef = useRef([]);
    const sendSequenceRef = useRef(0);
    const mountedRef = useRef(true);
    const sendAbortControllersRef = useRef(new Map());

    const canSend = can?.("agentinbox.send");
    const canClaim = can?.("agentinbox.claim");
    const canConfig = can?.("agentinbox.config");
    const timezone = orgTz(user);
    // Permiso PROPIO (ADR p57 §5.5.2): verificar identidad es una función de
    // mostrador, no de administración del canal — quien la tenga no recibe con
    // ella el kill switch del agente.
    const canVerifyIdentity = can?.("agentinbox.identity_verify");

    const resetList = useCallback(() => {
        listLoadRequestRef.current += 1;
        listControllerRef.current?.abort();
        listControllerRef.current = null;
        listPagesRef.current.clear();
        loadedListPagesRef.current = 1;
        nextListOffsetRef.current = null;
        loadingMoreThreadsRef.current = false;
        setHasMoreThreads(false);
        setLoadingMoreThreads(false);
        setMoreThreadsError("");
        setListLoad(EMPTY_LOAD_STATE);
        setLoadingList(true);
        setConversations([]);
    }, []);

    useEffect(() => {
        const trimmed = searchText.trim();
        const nextQuery = trimmed.length >= 2 ? trimmed : "";
        if (nextQuery === searchQuery) return;
        const timer = setTimeout(() => {
            resetList();
            setSearchQuery(nextQuery);
        }, 250);
        return () => clearTimeout(timer);
    }, [searchText, searchQuery, resetList]);

    useEffect(() => {
        const focusSearch = (event) => {
            if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.isComposing
                && event.key.toLowerCase() === "k") {
                event.preventDefault();
                searchRef.current?.focus();
                searchRef.current?.select();
            }
        };
        document.addEventListener("keydown", focusSearch);
        return () => document.removeEventListener("keydown", focusSearch);
    }, []);

    const clearSearch = () => {
        setSearchText("");
        if (searchQuery) {
            resetList();
            setSearchQuery("");
        }
        searchRef.current?.focus();
    };

    const loadList = useCallback(async ({ silent = true, append = false } = {}) => {
        if (!mountedRef.current || loadingMoreThreadsRef.current) return;
        if (listControllerRef.current) {
            if (!append) return;
            // An explicit page request supersedes a background refresh.
            listControllerRef.current.abort();
            listControllerRef.current = null;
        }
        if (append && nextListOffsetRef.current === null) return;
        const controller = new AbortController();
        listControllerRef.current = controller;
        const requestId = ++listLoadRequestRef.current;
        const isCurrent = () => mountedRef.current && !controller.signal.aborted && requestId === listLoadRequestRef.current;
        if (append) {
            loadingMoreThreadsRef.current = true;
            setLoadingMoreThreads(true);
            setMoreThreadsError("");
        }
        if (!silent) setLoadingList(true);
        try {
            // Apply each delta to its own offset page, then publish all pages
            // together. Moving between pages never removes a still-visible row.
            const nextPages = append ? new Map(listPagesRef.current) : new Map();
            const pagesToLoad = append ? 1 : loadedListPagesRef.current;
            let offset = append ? nextListOffsetRef.current : 0;
            let nextOffset = null;
            let pagesLoaded = 0;
            let totalUnread = null;
            const rows = [];
            for (let page = 0; page < pagesToLoad; page += 1) {
                if (!isCurrent() || (page > 0 && document.hidden)) return;
                const params = filter === "archived" ? { archived: 1 } : {};
                if (attention !== "") params.unanswered = Number(attention);
                if (urgentOnly) params.urgent = 1;
                if (mineOnly) params.claimed = "me";
                if (searchQuery) params.q = searchQuery;
                if (offset > 0) params.offset = offset;
                const previous = listPagesRef.current.get(offset);
                const data = await fetchSynced(
                    (since) => getThreads({ ...params, ...(since ? { since } : {}) }, { signal: controller.signal }),
                    previous?.sync_cursor, (packet) => mergeListPacket(previous, packet));
                if (!isCurrent()) return;
                nextPages.set(offset, data);
                if (Number.isSafeInteger(data?.unread_total)) totalUnread = data.unread_total;
                const pageRows = toList(data);
                rows.push(...pageRows);
                pagesLoaded += 1;
                nextOffset = pageRows.length > 0 ? nextThreadOffset(data, offset) : null;
                if (nextOffset === null) break;
                offset = nextOffset;
            }
            setConversations((previous) => uniqueThreads(append ? [...previous, ...rows] : rows));
            listPagesRef.current = nextPages;
            if (totalUnread !== null) setUnreadTotal(totalUnread);
            loadedListPagesRef.current = append ? loadedListPagesRef.current + pagesLoaded : pagesLoaded;
            nextListOffsetRef.current = nextOffset;
            setHasMoreThreads(nextOffset !== null);
            setMoreThreadsError("");
            setListLoad(EMPTY_LOAD_STATE);
        } catch (err) {
            if (!isCurrent()) return;
            if (append) {
                setMoreThreadsError(apiError(err, "No se pudieron cargar más conversaciones"));
                return;
            }
            setListLoad((previous) => ({
                loading: false,
                error: apiError(err, "No se pudo cargar la lista de conversaciones"),
                failures: previous.failures + 1,
            }));
        } finally {
            if (listControllerRef.current === controller) listControllerRef.current = null;
            if (isCurrent()) {
                setLoadingList(false);
                if (append) {
                    loadingMoreThreadsRef.current = false;
                    setLoadingMoreThreads(false);
                }
            }
        }
    }, [filter, attention, urgentOnly, mineOnly, searchQuery]);

    const onReadDivider = useCallback((id) => {
        captureScroll();
        setFirstUnreadId(id);
    }, [captureScroll]);
    const onMarkedRead = useCallback((target, data) => {
        // Descartar GETs que empezaron antes del acuse; refrescar las páginas cargadas.
        listLoadRequestRef.current += 1;
        threadLoadRequestRef.current += 1;
        listControllerRef.current?.abort();
        listControllerRef.current = null;
        threadControllerRef.current?.abort();
        threadControllerRef.current = null;
        loadingMoreThreadsRef.current = false;
        setLoadingMoreThreads(false);
        setLoadingList(false);
        setConversations((rows) => rows.map((row) => (
            row.contact_public_id === target.contact && row.channel_account_public_id === target.account
                ? { ...row, unread_count: data.unread_count } : row
        )));
        if (Number.isSafeInteger(data.unread_total)) setUnreadTotal(data.unread_total);
        loadList();
    }, [loadList]);
    const { resetRead, receiveReadState } = useThreadRead({
        onDivider: onReadDivider, onMarked: onMarkedRead,
    });

    const updateOptimisticMessages = useCallback((updater) => {
        if (!mountedRef.current) return;
        captureScroll();
        const next = updater(optimisticMessagesRef.current);
        optimisticMessagesRef.current = next;
        setOptimisticMessages(next);
    }, [captureScroll]);

    const loadThread = useCallback(async (target, { silent = true } = {}) => {
        if (!target || !mountedRef.current || threadControllerRef.current || isJumping()) return;
        const controller = new AbortController();
        threadControllerRef.current = controller;
        const requestId = ++threadLoadRequestRef.current;
        if (!silent) setThreadLoad((previous) => ({ ...previous, loading: true }));
        try {
            const previous = threadSnapshotRef.current;
            const floor = previous?.sync_cursor ? getSyncFloor() : null;
            const data = await fetchSynced(
                (since) => getThreadMessages(target.contact, target.account,
                    { ...(since ? { since } : {}), ...(floor !== null ? { floor } : {}) },
                    { signal: controller.signal }),
                previous?.sync_cursor, (packet) => mergeTranscriptPacket(previous, packet));
            if (!mountedRef.current) return;
            if (controller.signal.aborted) return;
            if (requestId !== threadLoadRequestRef.current) return;
            const current = selectedThreadRef.current;
            if (!current
                || current.contact !== target.contact
                || current.account !== target.account) return;
            const loadedSessionId = data?.conversation?.public_id || null;
            if (loadedSessionId !== activeSessionIdRef.current) setReplyTarget(null);
            activeSessionIdRef.current = loadedSessionId;
            const serverClientIds = new Set(
                (data?.messages || [])
                    .map((message) => message.client_message_id)
                    .filter(Boolean)
            );
            if (serverClientIds.size > 0) {
                for (const clientMessageId of serverClientIds) {
                    removePendingAttempt(
                        pendingSendAttemptsRef.current,
                        loadedSessionId,
                        clientMessageId
                    );
                }
                if (optimisticMessagesRef.current.some((message) => (
                    message.sessionId === loadedSessionId
                    && serverClientIds.has(message.client_message_id)
                ))) {
                    updateOptimisticMessages((messages) => messages.filter((message) => (
                        message.sessionId !== loadedSessionId
                        || !serverClientIds.has(message.client_message_id)
                    )));
                }
            }
            const { messages = [], next_before: cursor, removals = [], reset_range: replace = false,
                range_ids: rangeIds, sync_floor: syncFloor, ...metadata } = data;
            receiveLatest(messages, cursor, { removals, replace, rangeIds, syncFloor });
            receiveReadState(target, data);
            threadSnapshotRef.current = metadata;
            setThread(metadata);
            setThreadLoad(EMPTY_LOAD_STATE);
        } catch (err) {
            if (!mountedRef.current) return;
            if (controller.signal.aborted) return;
            if (requestId !== threadLoadRequestRef.current) return;
            const current = selectedThreadRef.current;
            if (!current
                || current.contact !== target.contact
                || current.account !== target.account) return;
            setThreadLoad((previous) => ({
                loading: false,
                error: apiError(err, "No se pudo cargar la conversación"),
                failures: previous.failures + 1,
            }));
        } finally {
            if (threadControllerRef.current === controller) threadControllerRef.current = null;
        }
    }, [updateOptimisticMessages, receiveLatest, receiveReadState, getSyncFloor, isJumping]);

    useEffect(() => {
        mountedRef.current = true;
        const controllers = sendAbortControllersRef.current;
        return () => {
            mountedRef.current = false;
            threadLoadRequestRef.current += 1;
            listLoadRequestRef.current += 1;
            listControllerRef.current?.abort();
            threadControllerRef.current?.abort();
            listControllerRef.current = null;
            threadControllerRef.current = null;
            for (const controller of controllers.values()) {
                controller.abort();
            }
            controllers.clear();
        };
    }, []);

    const pollList = useCallback(({ initial }) => {
        loadList({ silent: !initial });
    }, [loadList]);
    usePollingWhenVisible(pollList, LIST_POLL_MS);

    // Una única referencia temporal alimenta todo el render. Se renueva cada
    // minuto para que Hoy/Ayer cambie al cruzar medianoche sin dejar el Inbox
    // congelado si no llegan mensajes nuevos.
    const updateTimeReference = useCallback(() => setTimeReference(new Date()), []);
    usePollingWhenVisible(updateTimeReference, INBOX_CLOCK_TICK_MS);

    const pollThread = useCallback(({ initial }) => {
        loadThread(selectedThread, { silent: !initial });
    }, [selectedThread, loadThread]);
    usePollingWhenVisible(pollThread, THREAD_POLL_MS, Boolean(selectedThread));

    // Kill switch: solo si puede configurarlo.
    useEffect(() => {
        if (!canConfig) return;
        getAgentSettings()
            .then(setAgentSettings)
            .catch((err) => console.error(apiError(err)));
    }, [canConfig]);

    // Métricas de negocio (últimos 30d) — carga única, read-only.
    useEffect(() => {
        getInboxMetrics()
            .then(setMetrics)
            .catch((err) => console.error(apiError(err)));
    }, []);

    // Estado del token de WhatsApp (solo ADMIN).
    useEffect(() => {
        if (!canConfig) return;
        getWhatsappToken()
            .then(setTokenStatus)
            .catch((err) => console.error(apiError(err)));
    }, [canConfig]);

    const handleSaveToken = async () => {
        const t = tokenInput.trim();
        if (!t) { toast.error("Pega el token de WhatsApp"); return; }
        setSavingToken(true);
        try {
            const data = await setWhatsappToken(t);
            setTokenStatus(data);
            setTokenInput("");
            toast.success("Token de WhatsApp actualizado");
        } catch (err) {
            toast.error(apiError(err, "No se pudo guardar el token"));
        } finally {
            setSavingToken(false);
        }
    };

    // La sesión contra la que se ACTÚA. `null` = hilo archivado: se lee, se
    // recorre, y no ofrece acciones — escribir sobre una sesión cerrada devuelve
    // 400, así que no se pinta el botón.
    const sessionId = thread?.conversation?.public_id || null;
    const sessionWindow = getSessionWindow(thread?.conversation, timeReference.getTime());
    const windowCanSend = ["open", "closing"].includes(sessionWindow.state);
    const windowExpiresAt = sessionWindow.expiresAt;
    useEffect(() => {
        // Expire at the boundary even between minute ticks; never use a long
        // timeout for absent/malformed timestamps or archived conversations.
        const remaining = windowExpiresAt - Date.now() + 1;
        if (!sessionId || !windowCanSend || !Number.isFinite(remaining)) return;
        const timer = setTimeout(updateTimeReference, Math.max(1, Math.min(remaining, 2147483647)));
        return () => clearTimeout(timer);
    }, [sessionId, windowCanSend, windowExpiresAt, timeReference, updateTimeReference]);
    const retrySelectionRevision = selectionRevisionRef.current;
    const handleRetriedMessage = (serverMessage) => {
        if (!mountedRef.current || selectionRevisionRef.current !== retrySelectionRevision
                || activeSessionIdRef.current !== sessionId) return;
        threadLoadRequestRef.current += 1;
        // Un poll/acuse puede haber avanzado el mismo mensaje mientras llegaba
        // el POST: el acuse siempre gana a la proyección PENDING del reintento.
        updateMessages((messages) => messages.map((message) => (
            message.id === serverMessage.id && ["failed", "pending"].includes(message.status)
                ? serverMessage : message
        )));
    };
    useLayoutEffect(() => {
        const input = composerRef.current;
        if (!input) return;
        // Medir tras aplicar el texto permite crecer al pegar y encoger al
        // borrar, enviar o cambiar de hilo. scrollHeight no incluye el borde.
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight + 2, COMPOSER_MAX_HEIGHT)}px`;
    }, [body, sessionId, canSend]);

    const messageGroups = useMemo(
        () => groupMessagesByDay(transcriptMessages, timezone, timeReference)
            .map((day) => ({ ...day, bursts: groupConsecutiveMessages(day.messages) })),
        [transcriptMessages, timezone, timeReference]
    );
    const isSelected = (row) => (
        selectedThread
        && row.contact_public_id === selectedThread.contact
        && row.channel_account_public_id === selectedThread.account
    );

    const refreshAll = async () => {
        await Promise.all([loadList(), selectedThread ? loadThread(selectedThread) : null]);
    };

    const handleJumpToMessage = (id) => {
        // A recovery started before around must not replace the opened page.
        threadLoadRequestRef.current += 1;
        threadControllerRef.current?.abort();
        threadControllerRef.current = null;
        jumpToMessage(selectedThreadRef.current, id);
    };

    const selectReply = (message) => {
        if (!canSend || !sessionId || !windowCanSend || !Number.isSafeInteger(message.id) || message.id <= 0) return;
        captureScroll();
        setReplyTarget({
            id: message.id,
            author_type: message.author_type,
            human_author_name: message.human_author_name,
            authorLabel: message.direction === "in" ? contactLabel(thread)
                : (message.human_author_name || AUTHOR_LABEL[message.author_type] || "Staff"),
            excerpt: Array.from(message.body || "").slice(0, 80).join(""),
            payload_type: message.payload_type || "text",
            status: message.status,
        });
        composerRef.current?.focus({ preventScroll: true });
    };

    const cancelReply = () => {
        captureScroll();
        setReplyTarget(null);
        composerRef.current?.focus({ preventScroll: true });
    };

    const executeSendAttempt = async (attempt) => {
        const controller = new AbortController();
        sendAbortControllersRef.current.set(attempt.clientMessageId, controller);
        try {
            const serverMessage = await sendInboxMessage(
                attempt.sessionId,
                attempt.body,
                attempt.clientMessageId,
                { signal: controller.signal, ...(attempt.replyToId != null ? { replyToId: attempt.replyToId } : {}) }
            );
            if (!mountedRef.current || controller.signal.aborted) return;
            if (serverMessage?.client_message_id !== attempt.clientMessageId) {
                throw new Error("La respuesta no confirmó client_message_id");
            }

            removePendingAttempt(
                pendingSendAttemptsRef.current,
                attempt.sessionId,
                attempt.clientMessageId
            );

            const current = selectedThreadRef.current;
            const activeTarget = current && attempt.targetThread
                && current.contact === attempt.targetThread.contact
                && current.account === attempt.targetThread.account
                && activeSessionIdRef.current === attempt.sessionId;
            if (activeTarget) {
                updateOptimisticMessages((messages) => messages.filter(
                    (message) => message.client_message_id !== attempt.clientMessageId
                ));
                updateMessages((messages) => mergeServerMessage(messages, serverMessage));
            } else {
                // Confirmado, pero el hilo original no está activo. Mantener la
                // proyección real evita que desaparezca durante navegación o
                // lag de réplica; el próximo GET la absorberá por client id.
                updateOptimisticMessages((messages) => [
                    ...messages.filter(
                        (message) => message.client_message_id !== attempt.clientMessageId
                    ),
                    { ...serverMessage, sessionId: attempt.sessionId },
                ].slice(-MAX_PENDING_SEND_ATTEMPTS));
            }
            await loadList();
        } catch (err) {
            if (!mountedRef.current || controller.signal.aborted) return;
            const status = err?.response?.status;
            const nonRetryable = status >= 400 && status < 500;
            const message = apiError(err, "No se pudo enviar el mensaje");
            if (nonRetryable) {
                removePendingAttempt(
                    pendingSendAttemptsRef.current,
                    attempt.sessionId,
                    attempt.clientMessageId
                );
                updateOptimisticMessages((messages) => messages.filter(
                    (item) => item.client_message_id !== attempt.clientMessageId
                ));
            } else {
                updateOptimisticMessages((messages) => messages.map((item) => (
                    item.client_message_id === attempt.clientMessageId
                        ? { ...item, status: "failed-local", failure_reason: message }
                        : item
                )));
            }
            toast.error(message);
        } finally {
            if (sendAbortControllersRef.current.get(attempt.clientMessageId) === controller) {
                sendAbortControllersRef.current.delete(attempt.clientMessageId);
            }
        }
    };

    const handleSend = () => {
        // Recheck at the click/Enter, including a timer delayed by tab suspension.
        if (!canSend || !["open", "closing"].includes(getSessionWindow(thread?.conversation).state)) return;
        const text = body.trim();
        if (!text) { toast.error("Escribe un mensaje"); return; }
        const currentSessionId = sessionId;
        const targetThread = selectedThreadRef.current;
        const clientMessageId = newIdempotencyKey();
        const createdAt = new Date().toISOString();
        const attempt = {
            sessionId: currentSessionId,
            clientMessageId,
            body: text,
            replyToId: replyTarget?.id ?? null,
            targetThread,
            selectionRevision: selectionRevisionRef.current,
            sequence: ++sendSequenceRef.current,
        };
        registerPendingAttempt(pendingSendAttemptsRef.current, attempt);
        updateOptimisticMessages((messages) => [...messages, {
            id: `tmp:${clientMessageId}`,
            client_message_id: clientMessageId,
            sessionId: currentSessionId,
            body: text,
            reply_to: replyTarget ? {
                id: replyTarget.id, author_type: replyTarget.author_type,
                human_author_name: replyTarget.human_author_name,
                excerpt: replyTarget.excerpt, payload_type: replyTarget.payload_type,
                status: replyTarget.status,
            } : null,
            direction: "out",
            author_type: "human_staff",
            human_author_name: "Tú",
            payload_type: "text",
            status: "pending",
            failure_reason: "",
            created_at: createdAt,
        }].slice(-MAX_PENDING_SEND_ATTEMPTS));
        draftRevisionRef.current += 1;
        setBody("");
        setReplyTarget(null);
        executeSendAttempt(attempt);
    };

    const handleRetrySend = (clientMessageId) => {
        const sessionAttempts = pendingSendAttemptsRef.current.get(sessionId);
        const previous = sessionAttempts?.get(clientMessageId);
        if (!previous) return;
        const attempt = {
            ...previous,
            targetThread: selectedThreadRef.current,
            selectionRevision: selectionRevisionRef.current,
        };
        sessionAttempts.set(clientMessageId, attempt);
        updateOptimisticMessages((messages) => messages.map((message) => (
            message.client_message_id === clientMessageId
                ? { ...message, status: "pending", failure_reason: "" }
                : message
        )));
        executeSendAttempt(attempt);
    };

    const runAction = async (fn, successMsg) => {
        if (actionInFlightRef.current) return false;
        actionInFlightRef.current = true;
        const actionSession = sessionId;
        const revision = selectionRevisionRef.current;
        const stillCurrent = () => mountedRef.current && revision === selectionRevisionRef.current
            && actionSession === activeSessionIdRef.current;
        setActing(true);
        try {
            await fn(actionSession);
            if (!stillCurrent()) return false;
            if (successMsg) toast.success(successMsg);
            await refreshAll();
            return true;
        } catch (err) {
            if (!stillCurrent()) return false;
            if (err?.response?.status === 409) {
                toast.error(apiError(err, "Otra persona ya la está atendiendo"));
                await refreshAll();
            } else {
                toast.error(apiError(err, "Error inesperado"));
            }
            return false;
        } finally {
            actionInFlightRef.current = false;
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

    const handleUnlinkFamily = async () => {
        const ok = await confirm({
            message: "¿Revocar el vínculo familiar? Este número dejará de tener acceso a los datos del titular.",
            confirmText: "Revocar acceso",
            dangerMode: true,
        });
        if (!ok) return;
        await runAction(unlinkFamily, "Vínculo familiar revocado");
    };

    const handleResetIdentity = async () => {
        const owner = thread?.conversation?.owner_name;
        const ok = await confirm({
            message: owner
                ? `¿Resetear la identidad de este contacto? Deja de estar vinculado a ${owner} y esta conversación se cierra — el siguiente mensaje se tratará como contacto nuevo.`
                : "¿Resetear la identidad de este contacto? Esta conversación se cierra — el siguiente mensaje se tratará como contacto nuevo.",
            confirmText: "Resetear identidad",
            dangerMode: true,
        });
        if (!ok) return;
        await runAction(resetContactIdentity, "Identidad reseteada");
    };

    const handleVerifyIdentity = async () => {
        const ownerPublicId = thread?.identity_case?.candidate?.public_id;
        if (!ownerPublicId) {
            toast.error("No hay un cliente candidato para verificar. Ábrelo en Clientes y vuelve.");
            return;
        }
        const ok = await confirm({
            message:
                "Vas a registrar que comprobaste la identidad de esta persona con evidencia "
                + "EXTERNA al teléfono (identificación, datos del expediente o llamada al número "
                + "registrado). Registrar la verificación no vincula nada todavía.",
            confirmText: "Registrar verificación",
        });
        if (!ok) return;
        setActing(true);
        try {
            await verifyContactIdentity(sessionId, {
                owner_public_id: ownerPublicId,
                decision: "approved",
                evidence_kind: EVIDENCE_KINDS[0].value,
                evidence_note: "",
            });
            toast.success("Verificación registrada");
            await loadThread(selectedThread);
        } catch (err) {
            toast.error(apiError(err, "No se pudo registrar la verificación"));
        } finally {
            setActing(false);
        }
    };

    const handleAuthorizeIdentity = async () => {
        const ownerPublicId = thread?.identity_case?.candidate?.public_id;
        const ok = await confirm({
            message:
                "¿Vincular este número al cliente verificado? A partir de ahora podrá consultar y "
                + "gestionar sus citas por WhatsApp. Queda registrado quién lo autorizó.",
            confirmText: "Autorizar vínculo",
        });
        if (!ok) return;
        setActing(true);
        try {
            await authorizeIdentityLink(sessionId, ownerPublicId);
            toast.success("Contacto vinculado");
            await loadThread(selectedThread);
            await loadList();
        } catch (err) {
            toast.error(apiError(err, "No se pudo autorizar el vínculo"));
        } finally {
            setActing(false);
        }
    };

    const handleToggleAgent = async () => {
        const next = !agentSettings?.enabled;
        try {
            const data = await updateAgentSettings({ enabled: next });
            setAgentSettings(data);
            toast.success(next ? "Respuestas automáticas activadas" : "Respuestas automáticas desactivadas");
        } catch (err) {
            // El backend bloquea `enabled=true` sin teléfono de clínica (plantilla
            // de urgencia sin número al que llamar). El mensaje ya es accionable —
            // se acompaña del atajo para no dejar al ADMIN buscando dónde ir.
            const message = apiError(err, "No se pudo actualizar");
            toast.error(message, next ? {
                action: { label: "Ir a Configuración", onClick: () => navigate("/config/clinic") },
                duration: 8000,
            } : undefined);
        }
    };

    const conv = thread?.conversation;
    const agentProcessing = conv?.agent_processing === true;
    const turnHint = agentProcessing ? "Espera a que el asistente termine de responder." : undefined;
    const contactPhone = conv?.contact_phone || thread?.contact_phone
        || conversations.find(isSelected)?.contact_phone || "";
    const contactPhoneHref = phoneHref(contactPhone);
    const handleCopy = async (text, successMessage) => {
        try {
            await navigator.clipboard.writeText(text);
            toast.success(successMessage);
        } catch {
            toast.error("No se pudo copiar. Selecciona y copia el texto manualmente.");
        }
    };

    return (
        <div className={styles.page}>
            <div className={`page-header ${styles.pageHeader}`}>
                <div>
                    <h1 className="page-title">WhatsApp</h1>
                    <p className="page-subtitle">
                        Conversaciones con clientes — responde, toma o cierra cada hilo.
                    </p>
                </div>
                {canConfig && agentSettings !== null && (
                    <button
                        className={`${agentSettings.enabled ? "btn btn-secondary" : "btn btn-primary"} ${styles.agentToggle}`}
                        onClick={handleToggleAgent}
                    >
                        {agentSettings.enabled ? "Desactivar respuestas automáticas" : "Activar respuestas automáticas"}
                    </button>
                )}
            </div>

            {canConfig && (
                <div className={styles.tokenBar}>
                    <span className={styles.tokenLabel}>
                        Token de WhatsApp:{" "}
                        {tokenStatus?.configured
                            ? <strong>configurado ✓ …{tokenStatus.last4}</strong>
                            : <em>no configurado</em>}
                    </span>
                    <input
                        type="password"
                        className={styles.tokenInput}
                        placeholder="Pegar token nuevo de Meta"
                        value={tokenInput}
                        autoComplete="off"
                        onChange={(e) => setTokenInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !savingToken) handleSaveToken();
                        }}
                    />
                    <button className="btn btn-secondary btn-xs" disabled={savingToken}
                        onClick={handleSaveToken}>
                        {savingToken ? "Guardando…" : "Guardar token"}
                    </button>
                </div>
            )}

            <MetricsBar metrics={metrics} />

            <div className={styles.layout}>
                {/* -------- Lista -------- */}
                <div className={styles.listPane}>
                    <div className={styles.searchBox}>
                        <label htmlFor="inbox-contact-search">Buscar conversaciones</label>
                        <div className={styles.searchControl}>
                            <input id="inbox-contact-search" ref={searchRef} type="search"
                                value={searchText} placeholder="Nombre o teléfono"
                                aria-describedby="inbox-search-hint" aria-keyshortcuts="Control+k Meta+k"
                                onChange={(event) => setSearchText(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === "Escape") { event.preventDefault(); clearSearch(); }
                                }} />
                            {searchText && <button type="button" aria-label="Limpiar búsqueda"
                                onClick={clearSearch}>×</button>}
                        </div>
                        <span id="inbox-search-hint">Nombre, teléfono o cliente · mínimo 2 caracteres</span>
                    </div>
                    <div className={styles.filterRow}>
                        {FILTERS.map((f) => (
                            <button
                                key={f.value}
                                className={`${styles.filterTab} ${filter === f.value ? styles.filterTabActive : ""}`}
                                onClick={() => {
                                    if (filter === f.value) return;
                                    resetList();
                                    setFilter(f.value);
                                }}
                                aria-pressed={filter === f.value}
                                aria-label={f.label}
                                aria-describedby={f.value === "" ? "inbox-unread-total" : undefined}
                            >
                                {f.label}
                                {f.value === "" && (
                                    <span id="inbox-unread-total" className={styles.unreadCount}
                                        aria-label={`${unreadTotal} mensajes sin leer en conversaciones activas`}>
                                        {unreadTotal}
                                    </span>
                                )}
                            </button>
                        ))}
                    </div>
                    <div className={styles.segmentRow} role="group" aria-label="Filtros de conversaciones">
                        {[
                            { label: "Sin atender", active: attention === "1", toggle: () => setAttention(attention === "1" ? "" : "1") },
                            { label: "Esperando cliente", active: attention === "0", toggle: () => setAttention(attention === "0" ? "" : "0") },
                            { label: "Urgentes", active: urgentOnly, toggle: () => setUrgentOnly(!urgentOnly) },
                            { label: "Míos", active: mineOnly, toggle: () => setMineOnly(!mineOnly) },
                        ].map(({ label, active, toggle }) => (
                            <button key={label} type="button" aria-pressed={active}
                                className={`${styles.segmentChip} ${active ? styles.segmentChipActive : ""}`}
                                onClick={() => { resetList(); toggle(); }}>
                                {label}
                            </button>
                        ))}
                    </div>
                    <div className={styles.listScroll}>
                        {listLoad.failures >= 2 && (
                            <InboxConnectionBanner panel="Conversaciones" retrying={loadingList || loadingMoreThreads}
                                onRetry={() => loadList({ silent: false })} />
                        )}
                        {loadingList && conversations.length === 0 ? (
                            <InboxLoading label="Cargando conversaciones" />
                        ) : listLoad.error && conversations.length === 0 ? (
                            <InboxLoadError title="No se pudieron cargar las conversaciones" error={listLoad.error}
                                onRetry={listLoad.failures < 2 ? () => loadList({ silent: false }) : undefined} />
                        ) : conversations.length === 0 ? (
                            <EmptyState
                                compact
                                icon={Icon.MessageCircle}
                                title={searchQuery || attention !== "" || urgentOnly || mineOnly ? "Sin coincidencias" : "Sin conversaciones"}
                                body={searchQuery
                                    ? "Prueba otro nombre o teléfono, o desactiva un filtro para ampliar la búsqueda."
                                    : attention !== "" || urgentOnly || mineOnly
                                        ? "No hay conversaciones con estos filtros. Desactiva un filtro para ampliar la lista."
                                    : "Cuando un cliente escriba al WhatsApp de la clínica, aparecerá aquí."}
                            />
                        ) : (
                            conversations.map((c) => (
                                <button
                                    key={`${c.contact_public_id}:${c.channel_account_public_id}`}
                                    className={[
                                        styles.convItem,
                                        isSelected(c) ? styles.convItemActive : "",
                                        c.handoff_priority === "urgent" ? styles.convItemUrgent : "",
                                    ].filter(Boolean).join(" ")}
                                    onClick={() => {
                                        const target = {
                                            contact: c.contact_public_id,
                                            account: c.channel_account_public_id,
                                        };
                                        const current = selectedThreadRef.current;
                                        if (current
                                            && current.contact === target.contact
                                            && current.account === target.account) return;

                                        // El hilo, su transcript y su borrador
                                        // cambian juntos. Limpiar aquí evita que
                                        // el texto de una persona pueda enviarse
                                        // a otra; un efecto encadenaría renders.
                                        selectedThreadRef.current = target;
                                        threadControllerRef.current?.abort();
                                        threadControllerRef.current = null;
                                        threadSnapshotRef.current = null;
                                        activeSessionIdRef.current = null;
                                        selectionRevisionRef.current += 1;
                                        resetRead(target);
                                        resetHistory();
                                        draftRevisionRef.current += 1;
                                        setBody("");
                                        setReplyTarget(null);
                                        // Invalida cualquier GET del hilo anterior
                                        // que siga en vuelo y termine más tarde.
                                        threadLoadRequestRef.current += 1;
                                        setThread(null);
                                        setThreadLoad({ ...EMPTY_LOAD_STATE, loading: true });
                                        setSelectedThread(target);
                                    }}
                                >
                                    <div className={styles.convTop}>
                                        <div className={styles.convIdentity}>
                                            <span className={styles.convName}>
                                                {!Number.isSafeInteger(c.unread_count) && c.has_unanswered
                                                    && <span className={styles.unansweredDot} />}
                                                {contactLabel(c)}
                                            </span>
                                            {c.unread_count > 0 && (
                                                <span className={styles.unreadCount}
                                                    aria-label={`${c.unread_count} ${c.unread_count === 1 ? "mensaje sin leer" : "mensajes sin leer"}`}>
                                                    {c.unread_count}
                                                </span>
                                            )}
                                            <ContactVerificationBadge level={c.contact_verification} />
                                        </div>
                                        <span className={styles.convTime}>
                                            {c.session_count > 1 && (
                                                <span className={styles.sessionCount}
                                                    title={`${c.session_count} conversaciones con esta persona`}>
                                                    ×{c.session_count}
                                                </span>
                                            )}
                                            {fmtTimeOrg(c.last_activity_at, timezone, timeReference)}
                                        </span>
                                    </div>
                                    <div className={styles.convTop}>
                                        <span className={styles.convPreview}>{threadPreview(c)}</span>
                                        {c.handoff_priority === "urgent" ? (
                                            <span className="badge badge-danger">Urgente</span>
                                        ) : c.state ? (
                                            <span className={`badge ${STATE_BADGE[c.state] || "badge-default"}`}>
                                                {STATE_LABEL[c.state] || c.state}
                                            </span>
                                        ) : (
                                            <span className="badge badge-default">Archivada</span>
                                        )}
                                    </div>
                                    {c.handoff_priority === "urgent" ? (
                                        <div className={styles.urgentHint}>
                                            Posible emergencia — atiende de inmediato
                                        </div>
                                    ) : (c.handoff_reason && (
                                        // Por qué está esperando, sin tener que
                                        // abrirla. El detalle fino gana al código
                                        // grueso: "se atascó pidiendo datos" ubica,
                                        // "baja confianza" no.
                                        <div className={styles.handoffHint}>
                                            {HANDOFF_DETAIL[c.handoff_detail]
                                                || HANDOFF_REASON[c.handoff_reason]
                                                || "Esperando a una persona"}
                                        </div>
                                    ))}
                                </button>
                            ))
                        )}
                    </div>
                    {conversations.length > 0 && (
                        <div className={styles.listPagination}>
                            <span role="status">
                                {conversations.length} {conversations.length === 1 ? "conversación cargada." : "conversaciones cargadas."}
                                {hasMoreThreads && " Hay más conversaciones."}
                            </span>
                            {moreThreadsError && <span role="alert">{moreThreadsError}</span>}
                            {hasMoreThreads && (
                                <button className="btn btn-secondary btn-sm"
                                    disabled={loadingMoreThreads}
                                    onClick={() => loadList({ append: true })}>
                                    {loadingMoreThreads ? "Cargando más…" : moreThreadsError ? "Reintentar cargar más" : "Cargar más"}
                                </button>
                            )}
                        </div>
                    )}
                </div>

                {/* -------- Transcript -------- */}
                <div className={styles.chatPane}>
                    {threadLoad.failures >= 2 && (
                        <InboxConnectionBanner panel="Mensajes" retrying={threadLoad.loading}
                            onRetry={() => loadThread(selectedThread, { silent: false })} />
                    )}
                    {!thread && selectedThread && threadLoad.loading ? (
                        <InboxLoading label="Cargando mensajes" />
                    ) : !thread && threadLoad.error ? (
                        <InboxLoadError title="No se pudo cargar la conversación" error={threadLoad.error}
                            onRetry={threadLoad.failures < 2 ? () => loadThread(selectedThread, { silent: false }) : undefined} />
                    ) : !thread ? (
                        <div className={styles.emptyPane}>
                            Selecciona una conversación para ver los mensajes.
                        </div>
                    ) : (
                        <>
                            <div className={styles.chatHeader}>
                                <div className={styles.chatIdentity}>
                                    <div className={styles.chatIdentityLine}>
                                        <strong className={styles.chatName}>{contactLabel(thread)}</strong>
                                        <ContactVerificationBadge level={thread.contact_verification ?? conv?.contact_verification} />
                                        {agentProcessing && (
                                            <span className="badge badge-info" role="status">
                                                El asistente está respondiendo…
                                            </span>
                                        )}
                                        {conv ? (
                                            <span className={`badge ${STATE_BADGE[conv.state]}`}>
                                                {STATE_LABEL[conv.state]}
                                            </span>
                                        ) : (
                                            // Sin sesión vigente: se lee el historial,
                                            // no se responde. El hilo revive solo
                                            // cuando el cliente vuelve a escribir.
                                            <span className="badge badge-default"
                                                title="Sin conversación abierta — se puede leer, no responder">
                                                Archivada
                                            </span>
                                        )}
                                        {conv?.linked_via === "family_challenge" && (
                                            <span className="badge badge-purple">Vínculo familiar</span>
                                        )}
                                    </div>
                                    {(contactPhone || conv?.claimed_by_name) && (
                                        <div className={styles.chatMeta}>
                                            {contactPhone && (
                                                <>
                                                    {contactPhoneHref ? (
                                                        <a href={contactPhoneHref}>{contactPhone}</a>
                                                    ) : <span>{contactPhone}</span>}
                                                    <button type="button" className={styles.copyPhone}
                                                        onClick={() => handleCopy(contactPhone, "Teléfono copiado")}>
                                                        Copiar teléfono
                                                    </button>
                                                </>
                                            )}
                                            {conv?.claimed_by_name && <span>Atiende: {conv.claimed_by_name}</span>}
                                        </div>
                                    )}
                                </div>
                                {canClaim && sessionId && (
                                    <div className={styles.chatActions}>
                                        {conv?.state !== "closed" && <ThreadAssignment key={sessionId}
                                            disabled={acting || agentProcessing}
                                            onAssign={(userId) => runAction(
                                                (id) => assignConversation(id, userId), "Conversación asignada",
                                            )} />}
                                        {(conv?.state !== "human_active" || thread?.handoff?.state === "QUEUED") && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting || agentProcessing}
                                                title={turnHint}
                                                onClick={() => runAction(claimConversation)}>
                                                {conv?.state === "human_active" ? "Acusar recibo" : "Tomar y acusar recibo"}
                                            </button>
                                        )}
                                        {conv?.state === "human_active" && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting || agentProcessing}
                                                title={turnHint}
                                                onClick={() => runAction(releaseConversation, "Conversación liberada")}>
                                                Liberar
                                            </button>
                                        )}
                                        {conv?.linked_via === "family_challenge" && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting}
                                                onClick={handleUnlinkFamily}>
                                                Revocar vínculo
                                            </button>
                                        )}
                                        {canConfig && conv?.contact_verification && conv.contact_verification !== "unknown" && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting}
                                                onClick={handleResetIdentity}
                                                title="Desliga este número de cualquier cliente y cierra el hilo — útil para volver a probar el flujo de identidad">
                                                Resetear identidad
                                            </button>
                                        )}
                                        <button className="btn btn-secondary btn-xs" disabled={acting} onClick={handleClose}>
                                            Cerrar
                                        </button>
                                    </div>
                                )}
                            </div>

                            {thread?.identity_case && (
                                <IdentityCaseBanner
                                    identityCase={thread.identity_case}
                                    canVerify={canVerifyIdentity}
                                    acting={acting}
                                    onVerify={handleVerifyIdentity}
                                    onAuthorize={handleAuthorizeIdentity}
                                />
                            )}

                            {/* Los casos de identidad ya se explican arriba, con
                                sus acciones; este banner cubre el resto — que
                                hasta aquí llegaba sin ninguna explicación. */}
                            {thread?.handoff && (!thread?.identity_case || thread.handoff.priority === "urgent") && (
                                <HandoffReasonBanner handoff={thread.handoff} />
                            )}

                            {selectedThread && <ThreadContextPanel
                                key={JSON.stringify([selectedThread.contact, selectedThread.account,
                                    thread.owner_name, thread.contact_verification, conv?.linked_via])}
                                contactId={selectedThread.contact} accountId={selectedThread.account}
                                canOpenPet={Boolean(can?.("patient.retrieve"))}
                                onOpenPet={(publicId) => navigate(`/pets/${publicId}`)} />}

                            <ThreadViewport viewportRef={threadViewportRef} newBelow={newBelow}
                                onViewportScroll={trackScroll} onGoToEnd={goToEnd}
                                onReachStart={() => loadOlder(selectedThread)}>
                                {jumpLoad.loading && <p className={styles.jumpNotice} role="status">Buscando mensaje original…</p>}
                                {jumpLoad.error && <p className={styles.jumpNotice} role="alert">{jumpLoad.error}</p>}
                                <div className={styles.historyStatus}>
                                    {olderLoad.loading ? (
                                        <span role="status" aria-label="Cargando mensajes anteriores">Cargando anteriores…</span>
                                    ) : olderLoad.error ? (
                                        <>
                                            <span role="alert">{olderLoad.error}</span>
                                            <button type="button" className="btn btn-secondary btn-xs"
                                                onClick={() => loadOlder(selectedThread, { manual: true })}>
                                                Reintentar anteriores
                                            </button>
                                        </>
                                    ) : nextBefore !== null ? (
                                        <button type="button" className="btn btn-secondary btn-xs"
                                            onClick={() => loadOlder(selectedThread, { manual: true })}>
                                            Cargar anteriores
                                        </button>
                                    ) : (
                                        <span>Inicio del historial disponible</span>
                                    )}
                                </div>
                                {messageGroups.map((group) => (
                                    <Fragment key={group.key}>
                                        <DateDivider label={group.label} />
                                        {group.bursts.map((burst) => (
                                            <div
                                                key={burst.key}
                                                role="group"
                                                aria-label={`${burst.messages.length} ${burst.messages.length === 1 ? "mensaje" : "mensajes"} de ${burst.messages[0].direction === "in" ? contactLabel(thread) : (burst.messages[0].human_author_name || AUTHOR_LABEL[burst.messages[0].author_type] || "Staff")}`}
                                                className={`${styles.messageGroup} ${burst.messages[0].direction === "in" ? styles.messageGroupIn : styles.messageGroupOut}`}
                                            >
                                                {burst.messages.map((m) => (
                                                    <Fragment key={m.id}>
                                                        {Number(m.id) === firstUnreadId && (
                                                            <div role="separator" aria-label="Mensajes nuevos"
                                                                className={styles.unreadDivider}>Mensajes nuevos</div>
                                                        )}
                                                    <div
                                                        data-message-id={m.client_message_id || String(m.id)}
                                                        data-server-message-id={Number.isSafeInteger(m.id) ? m.id : undefined}
                                                        tabIndex={-1}
                                                        className={
                                                            (m.direction === "in"
                                                                ? `${styles.bubble} ${styles.bubbleIn}`
                                                                : `${styles.bubble} ${styles.bubbleOut}`)
                                                            + (m.id === highlightedId ? ` ${styles.messageHighlight}` : "")
                                                        }
                                                    >
                                                        <ReplyQuote reply={m.reply_to} contactName={contactLabel(thread)}
                                                            onJump={handleJumpToMessage}
                                                            busy={jumpLoad.loading && jumpLoad.targetId === m.reply_to?.id} />
                                                        {m.media && <MediaBubble key={m.media.public_id} media={m.media}
                                                            kind={m.payload_type} caption={m.body} />}
                                                        {m.body ? <MessageBody text={m.body} /> : (!m.media && <em>[{m.payload_type}]</em>)}
                                                        <div className={styles.bubbleMeta}>
                                                            {canSend && sessionId && (
                                                                <button type="button" className={styles.replyMessage}
                                                                    aria-label="Responder al mensaje" title="Responder"
                                                                    disabled={!windowCanSend || !Number.isSafeInteger(m.id) || m.id <= 0}
                                                                    onClick={() => selectReply(m)}>
                                                                    Responder
                                                                </button>
                                                            )}
                                                            {m.body && (
                                                                <button type="button" className={styles.copyMessage}
                                                                    aria-label="Copiar mensaje" title="Copiar mensaje"
                                                                    onClick={() => handleCopy(m.body, "Mensaje copiado")}>
                                                                    Copiar
                                                                </button>
                                                            )}
                                                            {m.direction === "out" && (
                                                                <span>
                                                                    {m.author_type === "human_staff"
                                                                        ? (m.human_author_name || "Staff")
                                                                        : (AUTHOR_LABEL[m.author_type] || "")}
                                                                </span>
                                                            )}
                                                            <span>{clockTimeOrg(m.created_at, timezone)}</span>
                                                            <DeliveryTicks
                                                                status={m.status}
                                                                direction={m.direction}
                                                                failure_reason={m.failure_reason}
                                                                acceptance_known={m.acceptance_known}
                                                            />
                                                            {m.status === "failed-local" && (
                                                                <button
                                                                    type="button"
                                                                    className={styles.retrySend}
                                                                    onClick={() => handleRetrySend(m.client_message_id)}
                                                                >
                                                                    Reintentar
                                                                </button>
                                                            )}
                                                            {m.direction === "out" && m.status === "failed" && (
                                                            <FailedMessageRetry message={m} sessionId={sessionId}
                                                                canSend={canSend} phone={thread.contact_phone}
                                                                onRetried={handleRetriedMessage} />
                                                            )}
                                                        </div>
                                                    </div>
                                                    </Fragment>
                                                ))}
                                            </div>
                                        ))}
                                    </Fragment>
                                ))}
                            </ThreadViewport>

                            {canSend && sessionId && (
                                <div className={styles.composer} onKeyDown={(event) => {
                                    if (event.key === "Escape" && replyTarget) {
                                        event.preventDefault();
                                        event.stopPropagation();
                                        cancelReply();
                                    }
                                }}>
                                    <SessionWindowNotice window={sessionWindow} phone={contactPhone} />
                                    {replyTarget && (
                                        <div className={styles.replyComposer} role="status" aria-label="Mensaje citado">
                                            <div className={styles.replyPreview} id="inbox-reply-preview">
                                                <strong>Respondiendo a {replyTarget.authorLabel}</strong>
                                                <span>{replyTarget.excerpt || `[${replyTarget.payload_type}]`}</span>
                                            </div>
                                            <button type="button" className={styles.cancelReply}
                                                aria-label="Cancelar respuesta citada" title="Cancelar (Escape)"
                                                onClick={cancelReply}>×</button>
                                        </div>
                                    )}
                                    <div className={styles.composerField}>
                                        <textarea
                                            ref={composerRef}
                                            className={styles.composerInput}
                                            rows={1}
                                            aria-label="Respuesta al cliente"
                                            aria-describedby={[
                                                sessionWindow.state !== "open" ? "inbox-session-window" : null,
                                                body.length > 3600 ? "inbox-composer-count" : null,
                                                replyTarget ? "inbox-reply-preview" : null,
                                            ].filter(Boolean).join(" ") || undefined}
                                            disabled={!windowCanSend}
                                            placeholder="Escribe una respuesta…"
                                            value={body}
                                            maxLength={COMPOSER_MAX_LENGTH}
                                            onChange={(e) => {
                                                draftRevisionRef.current += 1;
                                                setBody(e.target.value);
                                            }}
                                            onKeyDown={(e) => {
                                                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                                                    e.preventDefault();
                                                    handleSend();
                                                }
                                            }}
                                        />
                                        {body.length > 3600 && (
                                            <span
                                                id="inbox-composer-count"
                                                className={`${styles.composerCount} ${body.length >= 3800 ? styles.composerCountWarning : ""}`}
                                                aria-label={`${body.length} de ${COMPOSER_MAX_LENGTH} caracteres`}
                                            >
                                                {body.length}/{COMPOSER_MAX_LENGTH}
                                            </span>
                                        )}
                                    </div>
                                    <button className={`btn btn-primary ${styles.sendButton}`} disabled={!windowCanSend || !body.trim()} onClick={handleSend}>
                                        <Icon.Send s={15} c="currentColor" />
                                        Enviar
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
