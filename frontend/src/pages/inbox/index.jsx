import { useCallback, useEffect, useRef, useState } from "react";
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

// El HILO no tiene estado —lo tiene su sesión vigente—, así que el filtro es
// otro: o hay algo abierto, o el hilo está archivado.
const FILTERS = [
    { value: "", label: "Activas" },
    { value: "archived", label: "Archivadas" },
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

const Inbox = () => {
    const { can } = useAuth();
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
    const [sending, setSending] = useState(false);
    const [acting, setActing] = useState(false);
    const [agentSettings, setAgentSettings] = useState(null);
    const [metrics, setMetrics] = useState(null);
    const [tokenStatus, setTokenStatus] = useState(null);
    const [tokenInput, setTokenInput] = useState("");
    const [savingToken, setSavingToken] = useState(false);
    const threadEndRef = useRef(null);

    const canSend = can?.("agentinbox.send");
    const canClaim = can?.("agentinbox.claim");
    const canConfig = can?.("agentinbox.config");
    // Permiso PROPIO (ADR p57 §5.5.2): verificar identidad es una función de
    // mostrador, no de administración del canal — quien la tenga no recibe con
    // ella el kill switch del agente.
    const canVerifyIdentity = can?.("agentinbox.identity_verify");

    const loadList = useCallback(async ({ silent = true } = {}) => {
        if (!silent) setLoadingList(true);
        try {
            // `archived` en vez de `state`: el hilo no tiene estado propio — lo
            // tiene su sesión vigente, y si no hay ninguna está archivado.
            const data = await getThreads(filter === "archived" ? { archived: 1 } : {});
            setConversations(toList(data));
        } catch (err) {
            console.error(apiError(err));
        } finally {
            setLoadingList(false);
        }
    }, [filter]);

    const loadThread = useCallback(async (target) => {
        if (!target) return;
        try {
            const data = await getThreadMessages(target.contact, target.account);
            setThread(data);
        } catch (err) {
            toast.error(apiError(err, "No se pudo cargar la conversación"));
        }
    }, []);

    // Lista: carga inicial + polling.
    useEffect(() => {
        loadList({ silent: false });
        const t = setInterval(loadList, LIST_POLL_MS);
        return () => clearInterval(t);
    }, [loadList]);

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
    }, [thread?.messages?.length]);

    // La sesión contra la que se ACTÚA. `null` = hilo archivado: se lee, se
    // recorre, y no ofrece acciones — escribir sobre una sesión cerrada devuelve
    // 400, así que no se pinta el botón.
    const sessionId = thread?.conversation?.public_id || null;
    const isSelected = (row) => (
        selectedThread
        && row.contact_public_id === selectedThread.contact
        && row.channel_account_public_id === selectedThread.account
    );

    const refreshAll = async () => {
        await Promise.all([loadList(), selectedThread ? loadThread(selectedThread) : null]);
    };

    const handleSend = async () => {
        const text = body.trim();
        if (!text) { toast.error("Escribe un mensaje"); return; }
        setSending(true);
        try {
            await sendInboxMessage(sessionId, text);
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
                                    key={`${c.contact_public_id}:${c.channel_account_public_id}`}
                                    className={[
                                        styles.convItem,
                                        isSelected(c) ? styles.convItemActive : "",
                                        c.handoff_priority === "urgent" ? styles.convItemUrgent : "",
                                    ].filter(Boolean).join(" ")}
                                    onClick={() => {
                                        // Limpiar aquí y no en un efecto: es la
                                        // consecuencia de un clic, y hacerlo en
                                        // el efecto encadena renders.
                                        setThread(null);
                                        setSelectedThread({
                                            contact: c.contact_public_id,
                                            account: c.channel_account_public_id,
                                        });
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
                                                    {c.session_count}
                                                </span>
                                            )}
                                            {fmtTime(c.last_activity_at)}
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
                                <div>
                                    <strong>{contactLabel(thread)}</strong>
                                    {conv?.contact_phone && (
                                        <span style={{ color: "var(--c-text-muted, #64748b)", marginLeft: 8, fontSize: 12.5 }}>
                                            {conv.contact_phone}
                                        </span>
                                    )}
                                    {conv ? (
                                        <span className={`badge ${STATE_BADGE[conv.state]}`} style={{ marginLeft: 8 }}>
                                            {STATE_LABEL[conv.state]}
                                        </span>
                                    ) : (
                                        // Sin sesión vigente: se lee el historial,
                                        // no se responde. El hilo revive solo
                                        // cuando el cliente vuelve a escribir.
                                        <span className="badge badge-default" style={{ marginLeft: 8 }}
                                            title="Sin conversación abierta — se puede leer, no responder">
                                            Archivada
                                        </span>
                                    )}
                                    {conv?.linked_via === "family_challenge" && (
                                        <span className="badge badge-purple" style={{ marginLeft: 8 }}>
                                            Vínculo familiar
                                        </span>
                                    )}
                                    {conv?.claimed_by_name && (
                                        <span style={{ color: "var(--c-text-muted, #64748b)", marginLeft: 8, fontSize: 12 }}>
                                            Atiende: {conv.claimed_by_name}
                                        </span>
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

                            {canSend && sessionId && (
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
