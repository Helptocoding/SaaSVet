import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { changePassword } from "../api/users";
import { useAuth } from "../auth/authContext";
import handleFormError from "../utils/handleFormError";


const EMPTY_FORM = {
    current_password: "",
    new_password: "",
    confirm_password: "",
};

const MIN_PASSWORD_LENGTH = 8;

/**
 * Self-service password change form.
 *
 * On success, replaces the stored access + refresh tokens via the
 * central `useAuth().login(access, refresh)` — do NOT write directly
 * to localStorage. The server has blacklisted every previous refresh
 * token; using the central manager ensures the in-flight session
 * picks up the new pair atomically.
 */
const ChangePasswordForm = () => {
    const { login, refreshUser, user } = useAuth();
    const navigate = useNavigate();
    const [form, setForm] = useState(EMPTY_FORM);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);

    const handleChange = (field) => (e) => {
        setForm((prev) => ({ ...prev, [field]: e.target.value }));
        if (errors[field]) {
            setErrors((prev) => ({ ...prev, [field]: undefined }));
        }
    };

    const clientValidate = () => {
        const errs = {};
        if (!form.current_password) errs.current_password = "Requerido.";
        if (!form.new_password) errs.new_password = "Requerido.";
        else if (form.new_password.length < MIN_PASSWORD_LENGTH)
            errs.new_password = `Mínimo ${MIN_PASSWORD_LENGTH} caracteres.`;
        if (form.confirm_password !== form.new_password)
            errs.confirm_password = "Las contraseñas no coinciden.";
        if (form.current_password && form.new_password &&
            form.current_password === form.new_password) {
            errs.new_password = "Debe ser distinta a la actual.";
        }
        return errs;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const clientErrs = clientValidate();
        if (Object.keys(clientErrs).length > 0) {
            setErrors(clientErrs);
            return;
        }

        // Capturar ANTES del submit: si esta era la contraseña temporal obligatoria,
        // al terminar hay que llevar al usuario al dashboard (sin re-login).
        const wasForced = !!user?.must_change_password;

        setErrors({});
        setSaving(true);
        try {
            const data = await changePassword(form);
            // Reemplazo de tokens via central manager — NO localStorage directo.
            login(data.access, data.refresh);
            // El backend limpió must_change_password, pero el user en React state
            // todavía lo tiene en true (login solo intercambia tokens). Re-leer /me/
            // sincroniza el flag → el MustChangePasswordGate deja de rebotar.
            const fresh = await refreshUser();
            toast.success("Contraseña actualizada.");
            setForm(EMPTY_FORM);
            // Flujo obligatorio: Login → cambio → Dashboard → Onboarding, sin re-login.
            // Solo navegar si el flag ya se limpió (evita loop contra el gate).
            if (wasForced && fresh && !fresh.must_change_password) {
                navigate("/", { replace: true });
            }
        } catch (err) {
            const statusCode = err?.response?.status;
            if (statusCode === 429) {
                toast.error("Demasiados intentos. Espera antes de reintentar.");
            } else if (statusCode === 401) {
                toast.error("Tu sesión expiró. Inicia sesión de nuevo.");
            } else {
                handleFormError(err, setErrors);
            }
        } finally {
            setSaving(false);
        }
    };

    const fieldError = (field) => errors?.[field];

    return (
        <form onSubmit={handleSubmit} style={{ maxWidth: "440px" }}>
            <PasswordField
                label="Contraseña actual"
                value={form.current_password}
                onChange={handleChange("current_password")}
                error={fieldError("current_password")}
                autoComplete="current-password"
            />
            <PasswordField
                label="Nueva contraseña"
                value={form.new_password}
                onChange={handleChange("new_password")}
                error={fieldError("new_password")}
                hint={`Mínimo ${MIN_PASSWORD_LENGTH} caracteres. Evita contraseñas comunes o numéricas.`}
                autoComplete="new-password"
            />
            <PasswordField
                label="Confirmar nueva contraseña"
                value={form.confirm_password}
                onChange={handleChange("confirm_password")}
                error={fieldError("confirm_password")}
                autoComplete="new-password"
            />

            <button
                type="submit"
                className="btn btn-primary btn-md"
                disabled={saving}
                style={{ marginTop: "8px" }}
            >
                {saving ? "Actualizando..." : "Cambiar contraseña"}
            </button>

            <p style={{ fontSize: "11.5px", color: "var(--c-text-3)", marginTop: "14px" }}>
                Al cambiar tu contraseña, se invalidan todas tus sesiones
                anteriores en otros dispositivos. Tu sesión actual continúa.
            </p>
        </form>
    );
};

const PasswordField = ({ label, value, onChange, error, hint, autoComplete }) => {
    const [show, setShow] = useState(false);
    return (
        <div className="form-group">
            <label className="form-label">{label.toUpperCase()}</label>
            <div style={{ position: "relative" }}>
                <input
                    type={show ? "text" : "password"}
                    className={error ? "input input-error" : "input"}
                    value={value}
                    onChange={onChange}
                    autoComplete={autoComplete}
                    style={{ paddingRight: "56px" }}
                />
                <button
                    type="button"
                    onClick={() => setShow((s) => !s)}
                    style={{
                        position: "absolute",
                        right: "8px",
                        top: "50%",
                        transform: "translateY(-50%)",
                        background: "transparent",
                        border: "none",
                        color: "var(--c-text-3)",
                        fontSize: "11px",
                        cursor: "pointer",
                        padding: "4px 6px",
                        fontFamily: "inherit",
                    }}
                >
                    {show ? "Ocultar" : "Mostrar"}
                </button>
            </div>
            {hint && !error && (
                <div style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>
                    {hint}
                </div>
            )}
            {error && (
                <div style={{ fontSize: "11px", color: "var(--c-danger-text)", marginTop: "4px" }}>
                    {error}
                </div>
            )}
        </div>
    );
};

export default ChangePasswordForm;
