export const compareMessages = (left, right) => {
    const byTime = new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
    if (byTime !== 0) return byTime;
    if (typeof left.id === "number" && typeof right.id === "number") return left.id - right.id;
    return String(left.id).localeCompare(String(right.id));
};

export const mergeThreadMessages = (existing, incoming) => [...new Map(
    [...existing, ...incoming].map((message) => [String(message.id), message])
).values()].sort(compareMessages);
