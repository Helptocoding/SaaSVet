import { useState } from "react";
import { loginRequest, loginMfaRequest, getMe } from "../auth/login";
import { useAuth } from "../auth/authContext";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { apiError } from "../utils/apiError";

/**
 * Mensaje del login según lo que realmente pasó. Antes todo lo que no era 401
 * decía «Error de conexión. Verifica tu internet», también un bloqueo por
 * demasiados intentos (429), una clínica desactivada o un error del servidor:
 * el mensaje mandaba a revisar algo que no tenía la culpa.
 */
export function loginErrorMessage(err) {
    const response = err?.response;
    // Sin respuesta: el servidor no contestó o el navegador bloqueó la petición
    // (red caída, backend apagado, origen no permitido por CORS).
    if (!response) {
        return "No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.";
    }
    const status = response.status;
    const code = response.data?.code;
    if (status === 401 && code === "mfa_code_invalid") {
        return "El código no es válido. Revisa que la hora del celular sea automática o usa un código de respaldo.";
    }
    if (status === 401 && code === "mfa_challenge_invalid") {
        return "La verificación expiró. Vuelve a escribir tu contraseña.";
    }
    if (status === 401) return "Usuario o contraseña incorrectos.";
    if (status === 403 && code === "temp_password_expired") {
        return "Tu contraseña temporal expiró. Pídele a tu administrador un nuevo reset.";
    }
    if (status === 403 && code === "organization_inactive") {
        return "Tu clínica está desactivada. Comunícate con soporte para reactivarla.";
    }
    if (status === 429) {
        return "Demasiados intentos de inicio de sesión. Por seguridad, espera unos minutos y vuelve a intentarlo.";
    }
    if (status >= 500) {
        return "El servidor tuvo un problema. Inténtalo de nuevo en unos minutos.";
    }
    return apiError(err, "No se pudo iniciar sesión. Inténtalo de nuevo.");
}

export function useLoginForm() {
    const { login, setUserData } = useAuth();
    const navigate = useNavigate();

    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [remember, setRemember] = useState(true);
    const [loading, setLoading] = useState(false);
    // ADR p68: con verificación en dos pasos, la contraseña devuelve un reto
    // (`mfaToken`) y el formulario pide el código antes de entrar.
    const [mfaToken, setMfaToken] = useState(null);
    const [mfaCode, setMfaCode] = useState("");

    const finishLogin = async (data) => {
        const userData = await getMe(data.access);
        login(data.access, data.refresh, remember);
        setUserData(userData);
        if (typeof data.recovery_codes_remaining === "number") {
            const left = data.recovery_codes_remaining;
            toast.warning(left <= 3
                ? `Usaste un código de respaldo; te quedan ${left}. Genera nuevos en Configuración → Cuenta.`
                : `Usaste un código de respaldo; te quedan ${left}.`);
        }
        // Backend tags response with must_change_password if a temp
        // password reset is in effect — the MustChangePasswordGate
        // component will redirect on next render. Sending the user
        // to /change-password explicitly avoids a flash of "/" first.
        if (data.must_change_password || userData?.must_change_password) {
            navigate("/change-password");
        } else {
            navigate("/");
        }
    };

    const cancelMfa = () => {
        setMfaToken(null);
        setMfaCode("");
    };

    const handleSubmit = async (e) => {
        if (e) e.preventDefault();
        setLoading(true);
        try {
            if (mfaToken) {
                await finishLogin(await loginMfaRequest(mfaToken, mfaCode.trim()));
                return;
            }
            const data = await loginRequest(username, password);
            if (data.mfa_required) {
                setMfaToken(data.mfa_token);
                setMfaCode("");
                return;
            }
            await finishLogin(data);
        } catch (err) {
            // Un reto vencido o agotado no se puede reintentar: vuelve a la contraseña.
            if (err?.response?.data?.code === "mfa_challenge_invalid") {
                cancelMfa();
                setPassword("");
            }
            toast.error(loginErrorMessage(err));
        } finally {
            setLoading(false);
        }
    };

    return {
        username,
        setUsername,
        password,
        setPassword,
        remember,
        setRemember,
        loading,
        handleSubmit,
        mfaRequired: Boolean(mfaToken),
        mfaCode,
        setMfaCode,
        cancelMfa,
    };
}
