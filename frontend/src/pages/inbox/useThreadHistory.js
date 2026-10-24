import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { getThreadMessages } from "../../api/inbox";
import { apiError } from "../../utils/apiError";
import { compareMessages, mergeThreadMessages } from "./threadMessages";

const EMPTY_OLDER_LOAD = { loading: false, error: "" };
const EMPTY_MESSAGES = [];
const AUTO_HISTORY_LIMIT = 500;
const numericMessageId = (message) => Number.isSafeInteger(Number(message.id)) ? Number(message.id) : 0;
const messageKey = (message) => message.client_message_id
    ? `client:${message.client_message_id}` : `id:${message.id}`;

export default function useThreadHistory(viewportRef, { optimisticMessages = EMPTY_MESSAGES, sessionId = null, layoutKey = null } = {}) {
    const [messages, setMessages] = useState([]);
    const [nextBefore, setNextBefore] = useState(null);
    const [olderLoad, setOlderLoad] = useState(EMPTY_OLDER_LOAD);
    const [newBelow, setNewBelow] = useState(0);
    const [jumpLoad, setJumpLoad] = useState({ loading: false, error: "", targetId: null });
    const [highlightedId, setHighlightedId] = useState(null);
    const [jumpRevision, setJumpRevision] = useState(0);
    const messagesRef = useRef([]);
    const cursorRef = useRef(null);
    const initializedRef = useRef(false);
    const loadingOlderRef = useRef(false);
    const olderErrorRef = useRef(false);
    const revisionRef = useRef(0);
    const controllerRef = useRef(null);
    const scrollSnapshotRef = useRef(null);
    const readingInitializedRef = useRef(false);
    const initialMaxIdRef = useRef(0);
    const seenIdsRef = useRef(new Set());
    const seenClientIdsRef = useRef(new Set());
    const newKeysRef = useRef(new Set());
    const mountedRef = useRef(true);
    const removedIdsRef = useRef(new Set());
    const syncFloorRef = useRef(null);
    const jumpControllerRef = useRef(null);
    const jumpSequenceRef = useRef(0);
    const jumpScrollRef = useRef(null);
    const highlightTimerRef = useRef(null);
    const jumpPinRef = useRef(null);

    const transcriptMessages = useMemo(() => {
        if (!sessionId) return messages;
        const clientIds = new Set(messages.map((message) => message.client_message_id).filter(Boolean));
        return [...messages, ...optimisticMessages.filter((message) => (
            message.sessionId === sessionId && !clientIds.has(message.client_message_id)
        ))].sort(compareMessages);
    }, [messages, optimisticMessages, sessionId]);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            revisionRef.current += 1;
            controllerRef.current?.abort();
            jumpControllerRef.current?.abort();
            clearTimeout(highlightTimerRef.current);
        };
    }, []);

    const captureScroll = useCallback(({ prepend = false } = {}) => {
        const area = viewportRef.current;
        if (!area || !Number.isFinite(area.scrollHeight)) return;
        const pending = scrollSnapshotRef.current;
        if (pending?.area === area) {
            pending.prepend ||= prepend;
            return;
        }
        const bounds = area.getBoundingClientRect?.();
        const anchor = bounds && [...(area.querySelectorAll?.("[data-message-id]") || [])].find((node) => {
            const rect = node.getBoundingClientRect();
            return rect.height > 0 && rect.bottom > bounds.top && rect.top < bounds.bottom;
        });
        scrollSnapshotRef.current = {
            area, top: area.scrollTop, height: area.scrollHeight, prepend,
            atBottom: area.scrollTop + area.clientHeight >= area.scrollHeight - 80,
            anchorId: anchor?.getAttribute("data-message-id"),
            anchorOffset: anchor ? anchor.getBoundingClientRect().top - bounds.top : null,
        };
    }, [viewportRef]);

    const updateMessages = useCallback((updater, options) => {
        captureScroll(options);
        const next = updater(messagesRef.current);
        messagesRef.current = next;
        setMessages(next);
    }, [captureScroll]);

    const resetHistory = useCallback(() => {
        revisionRef.current += 1;
        controllerRef.current?.abort();
        controllerRef.current = null;
        initializedRef.current = false;
        loadingOlderRef.current = false;
        olderErrorRef.current = false;
        cursorRef.current = null;
        messagesRef.current = [];
        scrollSnapshotRef.current = null;
        readingInitializedRef.current = false;
        initialMaxIdRef.current = 0;
        removedIdsRef.current.clear();
        syncFloorRef.current = null;
        jumpControllerRef.current?.abort();
        jumpControllerRef.current = null;
        jumpSequenceRef.current += 1;
        jumpScrollRef.current = null;
        jumpPinRef.current = null;
        clearTimeout(highlightTimerRef.current);
        setJumpLoad({ loading: false, error: "", targetId: null });
        setHighlightedId(null);
        seenIdsRef.current.clear();
        seenClientIdsRef.current.clear();
        newKeysRef.current.clear();
        setMessages([]);
        setNextBefore(null);
        setOlderLoad(EMPTY_OLDER_LOAD);
        setNewBelow(0);
    }, []);

    const getSyncFloor = useCallback(() => syncFloorRef.current ?? messagesRef.current.find(
        (message) => Number.isSafeInteger(message.id))?.id ?? null, []);

    const extendFloor = useCallback((data) => {
        const oldest = messagesRef.current[0];
        const pageOldest = data?.messages?.[0];
        // A page filling the gap after around must not move the floor forward
        // and let a later delta erase the older page already being read.
        if (data?.sync_floor && pageOldest && (!oldest || compareMessages(pageOldest, oldest) <= 0)) {
            syncFloorRef.current = data.sync_floor;
        }
    }, []);

    const isJumping = useCallback(() => jumpControllerRef.current !== null, []);

    const receiveLatest = useCallback((incoming, cursor, { removals = [], replace = false, rangeIds, syncFloor } = {}) => {
        if (syncFloor) extendFloor({ messages: incoming, sync_floor: syncFloor });
        for (const id of removals) removedIdsRef.current.add(String(id));
        for (const message of incoming) removedIdsRef.current.delete(String(message.id));
        const visible = rangeIds ? new Set(rangeIds.map(String)) : null;
        updateMessages((previous) => mergeThreadMessages(replace ? [] : previous.filter(
            (message) => !removedIdsRef.current.has(String(message.id))
                && (!visible || visible.has(String(message.id))
                    || (message.is_hidden && message.id === jumpPinRef.current))), incoming));
        if (!initializedRef.current) {
            initializedRef.current = true;
            cursorRef.current = cursor ?? null;
            setNextBefore(cursorRef.current);
        }
    }, [updateMessages, extendFloor]);

    const loadOlder = useCallback(async (target, { manual = false } = {}) => {
        const cursor = cursorRef.current;
        if (!target || !mountedRef.current || loadingOlderRef.current || cursor === null) return;
        if (!manual && jumpPinRef.current !== null) return;
        if (!manual && (document.hidden || olderErrorRef.current || messagesRef.current.length >= AUTO_HISTORY_LIMIT)) return;
        const revision = revisionRef.current;
        const controller = new AbortController();
        controllerRef.current = controller;
        const isCurrent = () => mountedRef.current && !controller.signal.aborted && revision === revisionRef.current;
        loadingOlderRef.current = true;
        olderErrorRef.current = false;
        setOlderLoad({ loading: true, error: "" });
        try {
            const data = await getThreadMessages(target.contact, target.account,
                { before: cursor }, { signal: controller.signal });
            if (!isCurrent()) return;
            extendFloor(data);
            const incoming = (data?.messages || []).filter((message) => !removedIdsRef.current.has(String(message.id)));
            updateMessages((previous) => mergeThreadMessages(incoming, previous), { prepend: true });
            const next = data?.next_before ?? null;
            cursorRef.current = data?.messages?.length === 0 || String(next) === String(cursor) ? null : next;
            setNextBefore(cursorRef.current);
            setOlderLoad(EMPTY_OLDER_LOAD);
        } catch (error) {
            if (!isCurrent()) return;
            olderErrorRef.current = true;
            setOlderLoad({ loading: false,
                error: apiError(error, "No se pudieron cargar los mensajes anteriores") });
        } finally {
            if (isCurrent()) {
                loadingOlderRef.current = false;
                controllerRef.current = null;
            }
        }
    }, [updateMessages, extendFloor]);

    const jumpToMessage = useCallback(async (target, id) => {
        if (!target || !mountedRef.current || !Number.isSafeInteger(id) || id <= 0) return;
        if (jumpControllerRef.current?.targetId === id) return;
        jumpControllerRef.current?.abort();
        jumpControllerRef.current = null;
        const sequence = ++jumpSequenceRef.current;
        const revision = revisionRef.current;
        clearTimeout(highlightTimerRef.current);
        jumpPinRef.current = null;
        setHighlightedId(null);
        const queueScroll = () => {
            scrollSnapshotRef.current = null;
            jumpScrollRef.current = id;
            jumpPinRef.current = id;
            setHighlightedId(id);
            setJumpRevision((value) => value + 1);
            setJumpLoad({ loading: false, error: "", targetId: null });
        };
        if (messagesRef.current.some((message) => message.id === id)) {
            queueScroll();
            return;
        }
        const controller = new AbortController();
        controller.targetId = id;
        jumpControllerRef.current = controller;
        const isCurrent = () => mountedRef.current && !controller.signal.aborted
            && revision === revisionRef.current && sequence === jumpSequenceRef.current;
        setJumpLoad({ loading: true, error: "", targetId: id });
        try {
            const data = await getThreadMessages(target.contact, target.account,
                { around: id }, { signal: controller.signal });
            if (!isCurrent()) return;
            if (!Array.isArray(data?.messages) || !data.messages.some((message) => message.id === id)
                || removedIdsRef.current.has(String(id))
                || (data.contact_public_id && data.contact_public_id !== target.contact)
                || (data.channel_account_public_id && data.channel_account_public_id !== target.account)) {
                throw new Error("Original unavailable");
            }
            extendFloor(data);
            const incoming = data.messages.filter((message) => !removedIdsRef.current.has(String(message.id)));
            for (const message of incoming) {
                seenIdsRef.current.add(String(message.id));
                if (message.client_message_id) seenClientIdsRef.current.add(message.client_message_id);
            }
            // Existing rows may have newer delivery updates from a concurrent poll.
            // Keep the before chain: an around window can leave a gap in history.
            updateMessages((previous) => mergeThreadMessages(incoming, previous), { prepend: true });
            queueScroll();
        } catch (error) {
            if (!isCurrent()) return;
            setJumpLoad({ loading: false, targetId: id, error: error?.response?.status === 404
                || error?.message === "Original unavailable" ? "El mensaje original ya no está disponible."
                : "No se pudo cargar el mensaje original. Vuelve a pulsar la cita para reintentar." });
        } finally {
            if (jumpControllerRef.current === controller) jumpControllerRef.current = null;
        }
    }, [extendFloor, updateMessages]);

    const trackScroll = useCallback((area) => {
        if (jumpPinRef.current !== null) return;
        if (area.scrollTop + area.clientHeight >= area.scrollHeight - 80) {
            newKeysRef.current.clear();
            setNewBelow(0);
        }
    }, []);

    const goToEnd = useCallback(() => {
        const area = viewportRef.current;
        if (!area) return;
        jumpControllerRef.current?.abort();
        jumpControllerRef.current = null;
        jumpSequenceRef.current += 1;
        jumpScrollRef.current = null;
        jumpPinRef.current = null;
        clearTimeout(highlightTimerRef.current);
        setHighlightedId(null);
        setJumpLoad({ loading: false, error: "", targetId: null });
        area.scrollTo({ top: area.scrollHeight, behavior: newKeysRef.current.size > 0 ? "smooth" : "auto" });
        area.focus({ preventScroll: true });
        newKeysRef.current.clear();
        setNewBelow(0);
    }, [viewportRef]);

    // Único efecto de scroll: monta al fondo, sigue llegadas si estaba al fondo,
    // y conserva el ancla de lectura incluso si poll y scrollback se agrupan.
    useLayoutEffect(() => {
        const area = viewportRef.current;
        const snapshot = scrollSnapshotRef.current;
        scrollSnapshotRef.current = null;
        if (!area || !Number.isFinite(area.scrollHeight)) return;
        const first = !readingInitializedRef.current;
        if (first) {
            initialMaxIdRef.current = transcriptMessages.reduce((max, message) => Math.max(max, numericMessageId(message)), 0);
            readingInitializedRef.current = true;
        }
        for (const message of transcriptMessages) {
            if (message.client_message_id && newKeysRef.current.delete(`id:${message.id}`)) {
                newKeysRef.current.add(messageKey(message));
            }
        }
        const visibleKeys = new Set(transcriptMessages.map(messageKey));
        newKeysRef.current = new Set([...newKeysRef.current].filter((key) => visibleKeys.has(key)));
        for (const message of transcriptMessages) {
            const seen = seenIdsRef.current.has(String(message.id))
                || (message.client_message_id && seenClientIdsRef.current.has(message.client_message_id));
            if (!first && !seen && (numericMessageId(message) > initialMaxIdRef.current
                || (message.client_message_id && numericMessageId(message) === 0))) {
                newKeysRef.current.add(messageKey(message));
            }
            seenIdsRef.current.add(String(message.id));
            if (message.client_message_id) seenClientIdsRef.current.add(message.client_message_id);
        }
        const jumpId = jumpScrollRef.current;
        jumpScrollRef.current = null;
        const jumpNode = jumpId !== null && [...(area.querySelectorAll?.("[data-server-message-id]") || [])]
            .find((node) => node.getAttribute("data-server-message-id") === String(jumpId));
        if (jumpId !== null) {
            highlightTimerRef.current = setTimeout(() => {
                if (!mountedRef.current) return;
                jumpPinRef.current = null;
                setHighlightedId(null);
            }, 2000);
        }
        if (jumpNode) {
            const top = area.scrollTop + jumpNode.getBoundingClientRect().top
                - area.getBoundingClientRect().top - (area.clientHeight - jumpNode.getBoundingClientRect().height) / 2;
            area.scrollTo({ top: Math.max(0, top), behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? "auto" : "smooth" });
            jumpNode.focus({ preventScroll: true });
        } else if (first || (!jumpPinRef.current && snapshot?.area === area && snapshot.atBottom)) {
            area.scrollTop = area.scrollHeight;
            newKeysRef.current.clear();
        } else if (snapshot?.area === area) {
            const anchor = snapshot.anchorId && [...(area.querySelectorAll?.("[data-message-id]") || [])]
                .find((node) => node.getAttribute("data-message-id") === snapshot.anchorId);
            if (anchor) {
                const offset = anchor.getBoundingClientRect().top - area.getBoundingClientRect().top;
                area.scrollTop += offset - snapshot.anchorOffset;
            } else {
                area.scrollTop = snapshot.top + (snapshot.prepend ? area.scrollHeight - snapshot.height : 0);
            }
        }
        setNewBelow(newKeysRef.current.size);
    }, [transcriptMessages, viewportRef, layoutKey, jumpRevision]);

    return { messages, transcriptMessages, nextBefore, olderLoad, newBelow, jumpLoad, highlightedId,
        captureScroll, trackScroll, goToEnd, receiveLatest, updateMessages, resetHistory, loadOlder, getSyncFloor,
        jumpToMessage, isJumping };
}
