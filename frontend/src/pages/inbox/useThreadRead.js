import { useCallback, useEffect, useRef } from "react";
import { markThreadRead } from "../../api/inbox";

const id = (value) => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : 0;
const attention = () => document.visibilityState === "visible" && document.hasFocus();
const sameThread = (a, b) => a && b && a.contact === b.contact && a.account === b.account;

export default function useThreadRead({ onDivider, onMarked }) {
    const state = useRef(null);
    const callbacks = useRef({ onDivider, onMarked });
    useEffect(() => { callbacks.current = { onDivider, onMarked }; }, [onDivider, onMarked]);

    const publish = useCallback((value) => {
        const current = state.current;
        if (!current || current.boundary === value) return;
        current.boundary = value;
        callbacks.current.onDivider(value);
    }, []);
    const cancel = useCallback(() => {
        const current = state.current;
        if (!current) return;
        clearTimeout(current.timer);
        current.timer = null;
        current.controller?.abort();
        current.controller = null;
    }, []);
    const schedule = useCallback(function scheduleRead() {
        const current = state.current;
        if (!current?.ready || current.failed || current.timer !== null || current.controller
            || !attention() || current.unread <= 0 || current.latest <= current.marker) return;
        current.timer = setTimeout(async () => {
            current.timer = null;
            if (state.current !== current || !attention()) return;
            const candidate = current.latest;
            const controller = new AbortController();
            current.controller = controller;
            const isCurrent = () => state.current === current && !controller.signal.aborted;
            try {
                const data = await markThreadRead(current.target.contact, current.target.account,
                    candidate, { signal: controller.signal });
                if (!isCurrent()) return;
                if (id(data?.last_read_message_id) < candidate
                    || !Number.isSafeInteger(data?.unread_count) || data.unread_count < 0) {
                    throw new Error("Lectura sin confirmación del marcador");
                }
                current.marker = Math.max(current.marker, id(data.last_read_message_id));
                current.unread = Math.max(data.unread_count, current.latest > current.marker ? 1 : 0);
                if (current.boundary <= current.marker) publish(null);
                callbacks.current.onMarked(current.target, data);
            } catch {
                // No se muestra ni registra el error HTTP: el siguiente poll reintenta.
                if (isCurrent()) current.failed = true;
            } finally {
                if (isCurrent()) {
                    current.controller = null;
                    scheduleRead();
                }
            }
        }, 1500);
    }, [publish]);

    const resetRead = useCallback((target) => {
        cancel();
        state.current = { target, marker: 0, latest: 0, boundary: undefined,
            unread: 0, ready: false, failed: false, timer: null, controller: null };
        publish(null);
    }, [cancel, publish]);

    const receiveReadState = useCallback((target, data) => {
        const current = state.current;
        if (!sameThread(current?.target, target) || !Number.isSafeInteger(data?.unread_count)) return;
        const marker = id(data.last_read_message_id);
        if (marker < current.marker) return; // GET iniciado antes de nuestro POST confirmado.
        const latest = id(data.latest_visible_inbound_id);
        if (latest !== current.latest) {
            clearTimeout(current.timer);
            current.timer = null;
        }
        current.marker = marker;
        current.latest = latest;
        current.unread = data.unread_count;
        current.ready = Boolean(data.conversation);
        current.failed = false;
        const first = id(data.first_unread_message_id);
        publish(current.ready && current.unread > 0 && first > marker ? first : null);
        schedule();
    }, [publish, schedule]);

    useEffect(() => {
        const syncAttention = () => attention() ? schedule() : cancel();
        document.addEventListener("visibilitychange", syncAttention);
        window.addEventListener("focus", syncAttention);
        window.addEventListener("blur", cancel);
        return () => {
            cancel();
            state.current = null;
            document.removeEventListener("visibilitychange", syncAttention);
            window.removeEventListener("focus", syncAttention);
            window.removeEventListener("blur", cancel);
        };
    }, [cancel, schedule]);
    return { resetRead, receiveReadState };
}
