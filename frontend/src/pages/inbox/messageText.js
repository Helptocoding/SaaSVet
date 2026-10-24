// Plain text stays plain text. Only validated HTTP(S) tokens become links.
export const tokenizeMessageUrls = (text) => {
    const parts = [];
    let cursor = 0;
    for (const match of text.matchAll(/\bhttps?:\/\/[^\s<>"'`]+/gi)) {
        let candidate = match[0].replace(/[.,;:!?]+$/, "");
        // Keep balanced parentheses in paths; leave prose punctuation outside.
        const pairs = { ")": "(", "]": "[", "}": "{" };
        while (pairs[candidate.at(-1)]) {
            const close = candidate.at(-1);
            const open = pairs[close];
            if (candidate.split(close).length <= candidate.split(open).length) break;
            candidate = candidate.slice(0, -1).replace(/[.,;:!?]+$/, "");
        }
        let url;
        try {
            url = new URL(candidate);
        } catch {
            continue;
        }
        if (!url.hostname || !["http:", "https:"].includes(url.protocol)) continue;
        if (match.index > cursor) parts.push({ text: text.slice(cursor, match.index) });
        parts.push({ text: candidate, href: url.href });
        cursor = match.index + candidate.length;
    }
    if (cursor < text.length) parts.push({ text: text.slice(cursor) });
    return parts;
};

export const phoneHref = (phone) => {
    const number = phone.replace(/[\s()-]/g, "");
    return /^\+?\d+$/.test(number) ? `tel:${number}` : undefined;
};
