import { describe, expect, it } from "vitest";

import {
    DEFAULT_ORG_TIMEZONE,
    clockTimeOrg,
    dayLabelOrg,
    fmtTimeOrg,
    groupMessagesByDay,
    orgTz,
    relativeTimeOrg,
} from "./datetime";

describe("datetime org-aware", () => {
    it("resuelve la TZ del usuario y cae defensivamente a México", () => {
        expect(orgTz({ organization_timezone: "America/Tijuana" })).toBe("America/Tijuana");
        expect(orgTz({ organization_timezone: "Not/A_Timezone" })).toBe(DEFAULT_ORG_TIMEZONE);
        expect(orgTz(null)).toBe(DEFAULT_ORG_TIMEZONE);
    });

    it("calcula Ayer en la frontera UTC que cruza medianoche local", () => {
        const now = new Date("2026-08-23T08:30:00Z"); // 01:30 del 23 en Tijuana
        expect(dayLabelOrg("2026-08-23T06:30:00Z", "America/Tijuana", now))
            .toBe("Ayer"); // 23:30 del 22 en Tijuana
    });

    it("mantiene Hoy y la hora correcta durante el salto DST", () => {
        const now = new Date("2026-03-08T18:00:00Z");
        const beforeSpringForward = "2026-03-08T09:30:00Z"; // 01:30 PST
        const afterSpringForward = "2026-03-08T10:30:00Z"; // 03:30 PDT

        expect(dayLabelOrg(beforeSpringForward, "America/Tijuana", now)).toBe("Hoy");
        expect(dayLabelOrg(afterSpringForward, "America/Tijuana", now)).toBe("Hoy");
        expect(fmtTimeOrg(beforeSpringForward, "America/Tijuana", now)).toMatch(/01:30/);
        expect(fmtTimeOrg(afterSpringForward, "America/Tijuana", now)).toMatch(/03:30/);
    });

    it("clockTimeOrg siempre conserva hora:minuto aunque el mensaje sea histórico", () => {
        expect(clockTimeOrg("2026-08-22T18:45:00Z", "America/Tijuana"))
            .toMatch(/11:45/);
    });

    it("produce etiquetas es-MX, tiempo relativo y fallback ante TZ inválida", () => {
        const now = new Date("2026-08-23T18:00:00Z");
        expect(dayLabelOrg("2026-08-12T18:00:00Z", DEFAULT_ORG_TIMEZONE, now)).toBe("12 ago");
        expect(relativeTimeOrg("2026-08-23T17:55:00Z", DEFAULT_ORG_TIMEZONE, now))
            .toBe("hace 5 min");
        expect(dayLabelOrg("2026-08-23T17:00:00Z", "Not/A_Timezone", now))
            .toBe(dayLabelOrg("2026-08-23T17:00:00Z", DEFAULT_ORG_TIMEZONE, now));
    });
});

describe("groupMessagesByDay", () => {
    const now = new Date("2026-08-23T18:00:00Z");

    it("devuelve vacío sin mensajes", () => {
        expect(groupMessagesByDay([], "America/Tijuana", now)).toEqual([]);
    });

    it("agrupa una frontera de medianoche y únicamente los tres días presentes", () => {
        const messages = [
            { id: "m1", created_at: "2026-08-21T06:30:00Z" }, // 20 ago, 23:30
            { id: "m2", created_at: "2026-08-21T07:30:00Z" }, // 21 ago, 00:30
            { id: "m3", created_at: "2026-08-21T18:00:00Z" }, // 21 ago, 11:00
            { id: "m4", created_at: "2026-08-23T07:30:00Z" }, // 23 ago, 00:30
        ];

        const groups = groupMessagesByDay(messages, "America/Tijuana", now);

        expect(groups.map(({ key }) => key)).toEqual([
            "2026-08-20",
            "2026-08-21",
            "2026-08-23",
        ]);
        expect(groups.map(({ messages: dayMessages }) => dayMessages.map(({ id }) => id)))
            .toEqual([["m1"], ["m2", "m3"], ["m4"]]);
    });

    it("no divide un mismo día durante DST", () => {
        const messages = [
            { id: "before", created_at: "2026-03-08T09:30:00Z" },
            { id: "after", created_at: "2026-03-08T10:30:00Z" },
        ];
        const groups = groupMessagesByDay(
            messages,
            "America/Tijuana",
            new Date("2026-03-08T18:00:00Z")
        );
        expect(groups).toHaveLength(1);
        expect(groups[0].messages).toHaveLength(2);
    });
});
