import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import {
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
import styles from "./inbox.module.css";

// Bandeja WhatsApp (É-F0 PR-7). Polling (patrón useDashboardSummary): la
// lista cada 20s, el transcript seleccionado cada 10s. En F0 todas las
// conversaciones las atiende un humano; el agente solo auto-saluda.

const LIST_POLL_MS = 20000;
const THREAD_POLL_MS = 10000;
const INBOX_CLOCK_TICK_MS = 60000;
const MAX_PENDING_SEND_ATTEMPTS = 20;

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

const compareMessages = (left, right) => {
    const byTime = new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
    if (byTime !== 0) return byTime;
    return String(left.id).localeCompare(String(right.id));
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

const HandoffReasonBanner = ({ handoff }) => {
    const { reason, detail, goal } = handoff;
    const headline = HANDOFF_REASON[reason] || "El asistente pasó el caso al equipo.";
    const nuance = HANDOFF_DETAIL[detail];

    return (
        <div className={styles.handoffReason}>
            <strong>{headline}</strong>
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
    const [loadingList, setLoadingList] = useState(true);
    const [filter, setFilter] = useState("");
    // La selección es el HILO —la persona—, no el episodio: `{contact, account}`.
    // Las ACCIONES siguen apuntando a la sesión vigente (`thread.conversation`),
    // porque de ella cuelgan el claim, el hand-off y los compromisos.
    const [selectedThread, setSelectedThread] = useState(null);
    const [thread, setThread] = useState(null); // { conversation, messages, ... }
    const [body, setBody] = useState("");
    const [acting, setActing] = useState(false);
    const [agentSettings, setAgentSettings] = useState(null);
    const [metrics, setMetrics] = useState(null);
    const [tokenStatus, setTokenStatus] = useState(null);
    const [tokenInput, setTokenInput] = useState("");
    const [savingToken, setSavingToken] = useState(false);
    const [timeReference, setTimeReference] = useState(() => new Date());
    const [optimisticMessages, setOptimisticMessages] = useState([]);
    const threadEndRef = useRef(null);
    const threadLoadRequestRef = useRef(0);
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

    const loadList = useCallback(async ({ silent = true } = {}) => {
        if (!mountedRef.current) return;
        if (!silent) setLoadingList(true);
        try {
            // `archived` en vez de `state`: el hilo no tiene estado propio — lo
            // tiene su sesión vigente, y si no hay ninguna está archivado.
            const data = await getThreads(filter === "archived" ? { archived: 1 } : {});
            if (!mountedRef.current) return;
            setConversations(toList(data));
        } catch (err) {
            if (mountedRef.current) console.error(apiError(err));
        } finally {
            if (mountedRef.current) setLoadingList(false);
        }
    }, [filter]);

    const updateOptimisticMessages = useCallback((updater) => {
        if (!mountedRef.current) return;
        const next = updater(optimisticMessagesRef.current);
        optimisticMessagesRef.current = next;
        setOptimisticMessages(next);
    }, []);

    const loadThread = useCallback(async (target) => {
        if (!target) return;
        const requestId = ++threadLoadRequestRef.current;
        try {
            const data = await getThreadMessages(target.contact, target.account);
            if (!mountedRef.current) return;
            if (requestId !== threadLoadRequestRef.current) return;
            const current = selectedThreadRef.current;
            if (!current
                || current.contact !== target.contact
                || current.account !== target.account) return;
            const loadedSessionId = data?.conversation?.public_id || null;
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
            setThread(data);
        } catch (err) {
            if (!mountedRef.current) return;
            if (requestId !== threadLoadRequestRef.current) return;
            const current = selectedThreadRef.current;
            if (!current
                || current.contact !== target.contact
                || current.account !== target.account) return;
            toast.error(apiError(err, "No se pudo cargar la conversación"));
        }
    }, [updateOptimisticMessages]);

    useEffect(() => {
        mountedRef.current = true;
        const controllers = sendAbortControllersRef.current;
        return () => {
            mountedRef.current = false;
            threadLoadRequestRef.current += 1;
            for (const controller of controllers.values()) {
                controller.abort();
            }
            controllers.clear();
        };
    }, []);

    // Lista: carga inicial + polling.
    useEffect(() => {
        loadList({ silent: false });
        const t = setInterval(loadList, LIST_POLL_MS);
        return () => clearInterval(t);
    }, [loadList]);

    // Una única referencia temporal alimenta todo el render. Se renueva cada
    // minuto para que Hoy/Ayer cambie al cruzar medianoche sin dejar el Inbox
    // congelado si no llegan mensajes nuevos.
    useEffect(() => {
        const timer = setInterval(() => setTimeReference(new Date()), INBOX_CLOCK_TICK_MS);
        return () => clearInterval(timer);
    }, []);

    // Transcript del seleccionado: carga + polling.
    useEffect(() => {
        if (!selectedThread) return;
        loadThread(selectedThread);
        const t = setInterval(() => loadThread(selectedThread), THREAD_POLL_MS);
        return () => clearInterval(t);
    }, [selectedThread, loadThread]);

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

    useEffect(() => {
        threadEndRef.current?.scrollIntoView({ block: "end" });
    }, [thread?.messages?.length, optimisticMessages.length]);

    // La sesión contra la que se ACTÚA. `null` = hilo archivado: se lee, se
    // recorre, y no ofrece acciones — escribir sobre una sesión cerrada devuelve
    // 400, así que no se pinta el botón.
    const sessionId = thread?.conversation?.public_id || null;
    const transcriptMessages = useMemo(() => {
        const serverMessages = thread?.messages || [];
        if (!sessionId) return serverMessages;
        const serverClientIds = new Set(
            serverMessages.map((message) => message.client_message_id).filter(Boolean)
        );
        const localMessages = optimisticMessages.filter((message) => (
            message.sessionId === sessionId
            && !serverClientIds.has(message.client_message_id)
        ));
        return [...serverMessages, ...localMessages].sort(compareMessages);
    }, [thread?.messages, optimisticMessages, sessionId]);
    const messageGroups = useMemo(
        () => groupMessagesByDay(transcriptMessages, timezone, timeReference),
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

    const executeSendAttempt = async (attempt) => {
        const controller = new AbortController();
        sendAbortControllersRef.current.set(attempt.clientMessageId, controller);
        try {
            const serverMessage = await sendInboxMessage(
                attempt.sessionId,
                attempt.body,
                attempt.clientMessageId,
                { signal: controller.signal }
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
                setThread((currentThread) => (
                    currentThread?.conversation?.public_id === attempt.sessionId
                        ? {
                            ...currentThread,
                            messages: mergeServerMessage(
                                currentThread.messages || [],
                                serverMessage
                            ),
                        }
                        : currentThread
                ));
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
        setActing(true);
        try {
            await fn(sessionId);
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
                action: { label: "Ir a Configuración", onClick: () => navigate("/config") },
                duration: 8000,
            } : undefined);
        }
    };

    const conv = thread?.conversation;

    return (
        <div className={styles.page}>
            <div className={`page-header ${styles.pageHeader}`}>
                <div>
                    <h1>WhatsApp</h1>
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
                    <div className={styles.filterRow}>
                        {FILTERS.map((f) => (
                            <button
                                key={f.value}
                                className={`${styles.filterTab} ${filter === f.value ? styles.filterTabActive : ""}`}
                                onClick={() => setFilter(f.value)}
                                aria-pressed={filter === f.value}
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
                                        activeSessionIdRef.current = null;
                                        selectionRevisionRef.current += 1;
                                        draftRevisionRef.current += 1;
                                        setBody("");
                                        // Invalida cualquier GET del hilo anterior
                                        // que siga en vuelo y termine más tarde.
                                        threadLoadRequestRef.current += 1;
                                        setThread(null);
                                        setSelectedThread(target);
                                    }}
                                >
                                    <div className={styles.convTop}>
                                        <span className={styles.convName}>
                                            {c.has_unanswered && <span className={styles.unansweredDot} />}
                                            {contactLabel(c)}
                                        </span>
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
                                        <span className={styles.convPreview}>{c.last_message_preview || "—"}</span>
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
                </div>

                {/* -------- Transcript -------- */}
                <div className={styles.chatPane}>
                    {!thread ? (
                        <div className={styles.emptyPane}>
                            Selecciona una conversación para ver los mensajes.
                        </div>
                    ) : (
                        <>
                            <div className={styles.chatHeader}>
                                <div className={styles.chatIdentity}>
                                    <div className={styles.chatIdentityLine}>
                                        <strong className={styles.chatName}>{contactLabel(thread)}</strong>
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
                                    {(conv?.contact_phone || conv?.claimed_by_name) && (
                                        <div className={styles.chatMeta}>
                                            {[conv?.contact_phone, conv?.claimed_by_name ? `Atiende: ${conv.claimed_by_name}` : null]
                                                .filter(Boolean).join(" · ")}
                                        </div>
                                    )}
                                </div>
                                {canClaim && sessionId && (
                                    <div className={styles.chatActions}>
                                        {conv?.state !== "human_active" && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting}
                                                onClick={() => runAction(claimConversation)}>
                                                Tomar
                                            </button>
                                        )}
                                        {conv?.state === "human_active" && (
                                            <button className="btn btn-secondary btn-xs" disabled={acting}
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
                            {thread?.handoff && !thread?.identity_case && (
                                <HandoffReasonBanner handoff={thread.handoff} />
                            )}

                            <div className={styles.thread}>
                                {messageGroups.map((group) => (
                                    <Fragment key={group.key}>
                                        <DateDivider label={group.label} />
                                        {group.messages.map((m) => (
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
                                                </div>
                                            </div>
                                        ))}
                                    </Fragment>
                                ))}
                                <div ref={threadEndRef} />
                            </div>

                            {canSend && sessionId && (
                                <div className={styles.composer}>
                                    <textarea
                                        className={styles.composerInput}
                                        placeholder="Escribe una respuesta…"
                                        value={body}
                                        maxLength={4000}
                                        onChange={(e) => {
                                            draftRevisionRef.current += 1;
                                            setBody(e.target.value);
                                        }}
                                        onKeyDown={(e) => {
                                            if (e.key === "Enter" && !e.shiftKey) {
                                                e.preventDefault();
                                                handleSend();
                                            }
                                        }}
                                    />
                                    <button className={`btn btn-primary ${styles.sendButton}`} disabled={!body.trim()} onClick={handleSend}>
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
