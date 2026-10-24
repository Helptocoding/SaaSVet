import { describe, expect, it } from "vitest";
import { groupConsecutiveMessages } from "./messageGroups";

const message = (id, seconds = 0, extra = {}) => ({
    id, direction: "in", body: "Mismo texto",
    created_at: new Date(Date.parse("2026-10-20T18:00:00Z") + seconds * 1000).toISOString(),
    ...extra,
});

describe("WA-GRP-01 — agrupación consecutiva", () => {
    it("conserva el vacío y una burbuja aislada", () => {
        expect(groupConsecutiveMessages([])).toEqual([]);
        const one = message(1);
        expect(groupConsecutiveMessages([one])).toEqual([{ key: 1, messages: [one] }]);
    });

    it("une intervalos menores de cinco minutos y corta en cinco minutos exactos", () => {
        const messages = [message(1), message(2, 299.999), message(3, 599.999)];
        expect(groupConsecutiveMessages(messages).map((g) => g.messages.map((m) => m.id)))
            .toEqual([[1, 2], [3]]);
    });

    it("corta cuando interviene otro remitente aunque vuelva el primero", () => {
        const messages = [message(1), message(2, 1, { direction: "out", author_type: "agent" }), message(3, 2)];
        expect(groupConsecutiveMessages(messages).map((g) => g.messages.length)).toEqual([1, 1, 1]);
    });

    it("distingue humanos homónimos por UUID y conserva el mismo autor aunque cambie el nombre", () => {
        const human = { direction: "out", author_type: "human_staff", human_author_name: "Ana", human_author_public_id: "staff-a" };
        const messages = [message(1, 0, human), message(2, 1, { ...human, human_author_name: "Ana Pérez" }),
            message(3, 2, { ...human, human_author_public_id: "staff-b" })];
        expect(groupConsecutiveMessages(messages).map((g) => g.messages.map((m) => m.id)))
            .toEqual([[1, 2], [3]]);
    });

    it("no atribuye identidad a humanos sin UUID, incluidos temporales optimistas", () => {
        const human = { direction: "out", author_type: "human_staff", human_author_name: "Tú" };
        expect(groupConsecutiveMessages([message("tmp:a", 0, human), message("tmp:b", 1, human)]))
            .toHaveLength(2);
    });

    it("mantiene separados agente y sistema", () => {
        const agent = { direction: "out", author_type: "agent" };
        const messages = [message(1, 0, agent), message(2, 1, agent),
            message(3, 2, { direction: "out", author_type: "system" })];
        expect(groupConsecutiveMessages(messages).map((g) => g.messages.length)).toEqual([2, 1]);
    });

    it("no agrupa autores desconocidos ni tiempos inválidos o invertidos", () => {
        const unknown = { direction: "out", author_type: "unknown" };
        expect(groupConsecutiveMessages([message(1, 0, unknown), message(2, 1, unknown)])).toHaveLength(2);
        expect(groupConsecutiveMessages([message(1, 1), message(2, 0)])).toHaveLength(2);
        expect(groupConsecutiveMessages([message(1), message(2, 1, { created_at: "invalid" })])).toHaveLength(2);
    });

    it("conserva cada mensaje, estado y referencia sin deduplicar texto ni mutar entradas", () => {
        const human = { direction: "out", author_type: "human_staff", human_author_public_id: "staff-a" };
        const messages = Object.freeze(["pending", "sent", "read", "uncertain", "failed-local"].map((status, i) =>
            Object.freeze(message(i + 1, i, { ...human, status }))));
        const groups = groupConsecutiveMessages(messages);
        expect(groups).toHaveLength(1);
        expect(groups[0].messages).toEqual(messages);
        groups[0].messages.forEach((m, i) => expect(m).toBe(messages[i]));
    });
});
