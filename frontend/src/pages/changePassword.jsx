import ChangePasswordForm from "../components/ChangePasswordForm";
import { useAuth } from "../auth/authContext";


/**
 * Dedicated /change-password page.
 *
 * Forced-redirect target when ``must_change_password=true`` (the normal
 * self-change lives in /account, ADR p70 F1.2). The
 * ``MustChangePasswordGate`` permission on the backend lets only this
 * endpoint (and a tiny whitelist of auth/me routes) through while the
 * flag is set — so even a curl client cannot bypass the redirect.
 */
const ChangePassword = () => {
    const { user } = useAuth();
    const mustChange = user?.must_change_password;

    return (
        <div style={{ maxWidth: "560px" }}>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Cambiar contraseña</h1>
                    {mustChange ? (
                        <p className="page-subtitle" style={{ color: "var(--c-warning-text)" }}>
                            Debes cambiar tu contraseña temporal antes de continuar.
                        </p>
                    ) : (
                        <p className="page-subtitle">
                            Actualiza tu contraseña personal.
                        </p>
                    )}
                </div>
            </div>

            {mustChange && (
                <div
                    style={{
                        background: "rgba(251,191,36,0.10)",
                        border: "1px solid rgba(251,191,36,0.30)",
                        borderRadius: "6px",
                        padding: "12px 14px",
                        marginBottom: "20px",
                        fontSize: "12.5px",
                        color: "var(--c-warning-text)",
                    }}
                >
                    <strong>Tu contraseña actual es temporal.</strong> Fue
                    asignada por tu administrador. Cámbiala ahora para
                    desbloquear el resto de la aplicación. El acceso a las
                    demás secciones está limitado hasta que completes este
                    cambio.
                </div>
            )}

            <ChangePasswordForm />
        </div>
    );
};

export default ChangePassword;
