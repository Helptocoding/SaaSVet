import { describe, expect, it, vi } from "vitest";
import { fetchSynced, InvalidInboxDelta, mergeListPacket, mergeTranscriptPacket } from "./inboxSync";

const row = (contact, extra = {}) => ({ contact_public_id: contact, channel_account_public_id: "main", ...extra });
const list = { results: [row("ana"), row("beto")], sync_cursor: "old" };
const delta = (extra = {}) => ({ mode: "delta", sync_cursor: "new", upserts: [], removals: [], ...extra });

describe("WA-PERF-03 — merge y recuperación", () => {
    it("combina por hilo compuesto, retira explícitos y aplica orden del servidor", () => {
        const result = mergeListPacket(list, delta({ upserts: [row("ana", { unread_count: 2 }), row("cora")],
            removals: ["beto:main"], order: ["cora:main", "ana:main"] }));
        expect(result.results).toEqual([row("cora"), row("ana", { unread_count: 2 })]);
        expect(list.results).toHaveLength(2);
        expect(mergeListPacket(result, delta()).results).toEqual(result.results);
    });
    it("distingue dos cuentas del mismo contacto y no duplica un replay", () => {
        const packet = delta({ upserts: [{ ...row("ana"), channel_account_public_id: "second" }],
            order: ["ana:main", "beto:main", "ana:second"] });
        const first = mergeListPacket(list, packet);
        expect(mergeListPacket(first, packet).results).toHaveLength(3);
    });
    it.each([
        { sync_cursor: null }, { upserts: null }, { removals: {} }, { upserts: [{}] },
        { upserts: [row("cora")] }, { order: ["ana:main"] }, { order: ["ana:main", "ana:main"] },
        { order: ["ana:main", "foreign:main"] }, { upserts: [row("ana"), row("ana")] },
        { upserts: [row("ana")], removals: ["ana:main"] },
    ])("rechaza un delta incompleto sin perder la página (%j)", (extra) => {
        expect(() => mergeListPacket(list, delta(extra))).toThrow(InvalidInboxDelta);
        expect(list.results).toHaveLength(2);
    });
    it("conserva metadatos al recibir sólo ticks y aplica null al archivar", () => {
        const before = { conversation: { public_id: "a" }, owner_name: "Ana", unread_count: 2 };
        const packet = { mode: "delta", sync_cursor: "n", messages: [{ id: 7, status: "read" }], removals: [], metadata: {} };
        expect(mergeTranscriptPacket(before, packet)).toMatchObject({ ...before, messages: packet.messages });
        expect(mergeTranscriptPacket(before, { ...packet, metadata: { conversation: null, unread_count: 0 } }))
            .toMatchObject({ conversation: null, owner_name: "Ana", unread_count: 0 });
    });
    it.each([
        { metadata: null }, { messages: null }, { removals: null }, { messages: [{ id: "7" }] },
        { messages: [{ id: 7 }, { id: 7 }] }, { messages: [{ id: 7 }], removals: [7] },
    ])("rechaza un transcript inconsistente (%j)", (extra) => {
        expect(() => mergeTranscriptPacket({}, { mode: "delta", sync_cursor: "n", messages: [],
            removals: [], metadata: {}, ...extra })).toThrow(InvalidInboxDelta);
    });
    it("cursor inválido hace una sola recuperación completa", async () => {
        const fetch = vi.fn().mockRejectedValueOnce({ response: { data: { code: "invalid_sync_cursor" } } })
            .mockResolvedValueOnce({ mode: "full", results: [row("cora")], sync_cursor: "fresh" });
        expect((await fetchSynced(fetch, "old", (data) => mergeListPacket(list, data))).results).toEqual([row("cora")]);
        expect(fetch.mock.calls).toEqual([["old"], [null]]);
    });
    it("delta corrupto recupera full y los errores normales conservan su significado", async () => {
        const fetch = vi.fn().mockResolvedValueOnce(delta({ order: [] })).mockResolvedValueOnce({ results: [] });
        expect(await fetchSynced(fetch, "old", (data) => mergeListPacket(list, data))).toEqual({ results: [] });
        const forbidden = { response: { status: 403, data: { code: "forbidden" } } };
        const denied = vi.fn().mockRejectedValue(forbidden);
        await expect(fetchSynced(denied, "old", (data) => data)).rejects.toBe(forbidden);
        expect(denied).toHaveBeenCalledTimes(1);
    });
});
