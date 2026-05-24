import { useState } from "react";
import { loginRequest, getMe } from "../auth/login";
import { useAuth } from "../auth/authContext";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

export function useLoginForm() {
    const { login, setUserData } = useAuth();
    const navigate = useNavigate();

    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [remember, setRemember] = useState(true);
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        if (e) e.preventDefault();
        setLoading(true);
        try {
            const data = await loginRequest(username, password);
            const userData = await getMe(data.access);
            login(data.access, data.refresh, remember);
            setUserData(userData);
            // Backend tags response with must_change_password if a temp
            // password reset is in effect — the MustChangePasswordGate
            // component will redirect on next render. Sending the user
            // to /change-password explicitly avoids a flash of "/" first.
            if (data.must_change_password || userData?.must_change_password) {
                navigate("/change-password");
            } else {
                navigate("/");
            }
        } catch (err) {
            const code = err.response?.status;
            const errCode = err.response?.data?.code;
            if (code === 401) {
                toast.error("Usuario o contraseña incorrectos.");
            } else if (code === 403 && errCode === "temp_password_expired") {
                toast.error("Tu contraseña temporal expiró. Pídele a tu administrador un nuevo reset.");
            } else {
                toast.error("Error de conexión. Verifica tu internet e intenta de nuevo.");
            }
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
        handleSubmit
    };
}
