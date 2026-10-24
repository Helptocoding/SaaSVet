import { describe, expect, it } from "vitest";
import { phoneHref, tokenizeMessageUrls } from "./messageText";

describe("WA-CPY-01 — texto y URLs", () => {
    it("conserva texto vacío, saltos y espacios sin enlaces", () => {
        expect(tokenizeMessageUrls("")).toEqual([]);
        expect(tokenizeMessageUrls("  Hola\nAna  ")).toEqual([{ text: "  Hola\nAna  " }]);
    });

    it("reconoce HTTP/HTTPS, queries y varios enlaces sin perder texto", () => {
        const text = "Ver HTTPS://example.org/a?x=1&y=2 y http://example.com/b#info\nGracias.";
        const parts = tokenizeMessageUrls(text);
        expect(parts.filter((part) => part.href).map((part) => part.href)).toEqual([
            "https://example.org/a?x=1&y=2", "http://example.com/b#info",
        ]);
        expect(parts.map((part) => part.text).join("")).toBe(text);
    });

    it("separa puntuación de la prosa y conserva paréntesis propios de la URL", () => {
        const text = "(https://example.org/wiki/Gato_(animal)). [https://example.com/cita], ¡https://example.org/hora!";
        const parts = tokenizeMessageUrls(text);
        expect(parts.filter((part) => part.href).map((part) => part.text)).toEqual([
            "https://example.org/wiki/Gato_(animal)", "https://example.com/cita", "https://example.org/hora",
        ]);
        expect(parts.map((part) => part.text).join("")).toBe(text);
    });

    it("deja esquemas peligrosos, URLs inválidas y HTML como texto", () => {
        const text = '<img src=x onerror=alert(1)> javascript:alert(1) data:text/html,test ftp://host/a https:// http://[invalid]';
        expect(tokenizeMessageUrls(text)).toEqual([{ text }]);
    });

    it("no incorpora comillas ni etiquetas en un enlace y conserva todo el cuerpo", () => {
        const text = '<a href="https://example.org/x">texto</a> https://example.org/y" onclick=alert(1)';
        const parts = tokenizeMessageUrls(text);
        expect(parts.filter((part) => part.href).map((part) => part.href)).toEqual([
            "https://example.org/x", "https://example.org/y",
        ]);
        expect(parts.map((part) => part.text).join("")).toBe(text);
    });

    it("normaliza sólo caracteres de formato de teléfono", () => {
        expect(phoneHref("+52 (55) 1234-5678")).toBe("tel:+525512345678");
        expect(phoneHref("525512345678")).toBe("tel:525512345678");
        expect(phoneHref("")).toBeUndefined();
        expect(phoneHref("javascript:alert(1)")).toBeUndefined();
        expect(phoneHref("+52;ext=123")).toBeUndefined();
    });
});
