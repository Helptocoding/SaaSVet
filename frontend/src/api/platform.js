import api from "./client";

export const provisionOrganization = async (data) => {
    const requestId =
        typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : Math.random().toString(36).slice(2);
    const res = await api.post("platform/organizations/", data, {
        headers: { "X-Request-ID": requestId },
    });
    return res.data;
};
