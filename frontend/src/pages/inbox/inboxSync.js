// A corrupt/incomplete delta must never erase a loaded page or advance its cursor.
export class InvalidInboxDelta extends Error {}
export const threadKey = (row) => `${row.contact_public_id}:${row.channel_account_public_id}`;
const object = (value) => value && typeof value === "object" && !Array.isArray(value);
const invalid = () => { throw new InvalidInboxDelta("Respuesta incremental incompleta"); };

export function mergeListPacket(previous, data) {
    if (data?.mode !== "delta") {
        if (data?.mode === "full" && !Array.isArray(data.results)) invalid();
        return data;
    }
    if (!previous || !Array.isArray(previous.results) || !data.sync_cursor
            || !Array.isArray(data.upserts) || !Array.isArray(data.removals)) invalid();
    const rows = new Map(previous.results.map((row) => [threadKey(row), row]));
    const upserts = new Set();
    for (const row of data.upserts) {
        if (!object(row) || !row.contact_public_id || !row.channel_account_public_id) invalid();
        const key = threadKey(row);
        if (upserts.has(key) || data.removals.includes(key)) invalid();
        if (!rows.has(key) && !Array.isArray(data.order)) invalid();
        upserts.add(key); rows.set(key, row);
    }
    for (const key of data.removals) {
        if (typeof key !== "string") invalid();
        rows.delete(key);
    }
    const order = data.order ?? [...rows.keys()];
    if (!Array.isArray(order) || new Set(order).size !== rows.size
            || order.length !== rows.size || order.some((key) => !rows.has(key))) invalid();
    return { ...data, results: order.map((key) => rows.get(key)) };
}

export function mergeTranscriptPacket(previous, data) {
    if (data?.mode !== "delta") {
        if (data?.mode === "full" && !Array.isArray(data.messages)) invalid();
        return data;
    }
    if (!previous || !data.sync_cursor || !Array.isArray(data.messages)
            || !Array.isArray(data.removals) || !object(data.metadata)) invalid();
    const ids = new Set();
    for (const row of data.messages) {
        if (!object(row) || !Number.isSafeInteger(row.id) || ids.has(row.id)
                || data.removals.includes(row.id)) invalid();
        ids.add(row.id);
    }
    if (data.removals.some((id) => !Number.isSafeInteger(id))) invalid();
    if (data.range_ids !== undefined && (!Array.isArray(data.range_ids)
        || new Set(data.range_ids).size !== data.range_ids.length
        || data.range_ids.some((id) => !Number.isSafeInteger(id))
        || data.messages.some((row) => !data.range_ids.includes(row.id)))) invalid();
    for (const key of ["contact_public_id", "channel_account_public_id"]) {
        if (previous[key] && data.metadata[key] && previous[key] !== data.metadata[key]) invalid();
    }
    return { ...previous, ...data.metadata, mode: "delta", sync_cursor: data.sync_cursor,
        messages: data.messages, removals: data.removals, range_ids: data.range_ids,
        next_before: undefined, reset_range: false };
}

export async function fetchSynced(fetchPage, cursor, merge) {
    try {
        return merge(await fetchPage(cursor || null));
    } catch (error) {
        if (!cursor || (error.response?.data?.code !== "invalid_sync_cursor"
                && !(error instanceof InvalidInboxDelta))) throw error;
        return merge(await fetchPage(null));
    }
}
