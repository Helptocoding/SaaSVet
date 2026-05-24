import api from "./client";

/**
 * Self-service password change.
 *
 * Backend: POST /api/users/change-password/
 * Returns: { detail, request_id, duration_ms, access, refresh }
 *
 * The caller MUST replace the stored access + refresh tokens via the
 * central auth manager (useAuth().login). Writing to localStorage from
 * form components is a smell — drift between callers leads to stale
 * tokens and silent re-login bugs.
 */
export const changePassword = async ({ current_password, new_password, confirm_password }) => {
    const requestId =
        typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : Math.random().toString(36).slice(2);
    const res = await api.post(
        "users/change-password/",
        { current_password, new_password, confirm_password },
        { headers: { "X-Request-ID": requestId } },
    );
    return res.data;
};
