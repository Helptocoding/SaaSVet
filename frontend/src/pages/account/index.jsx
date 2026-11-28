import { useAuth } from "../../auth/authContext";
import ChangePasswordForm from "../../components/ChangePasswordForm";
import { roleLabel } from "../../features/staff/roles";
import MfaSettings from "../config/MfaSettings";
import SettingsPanel from "../config/SettingsPanel";
import { IdentityHeader, SettingRow } from "../config/parts";
import styles from "../config/config.module.css";

const PLATFORM_ROLE = "ADMIN_SAAS";

const fullName = (user) =>
    [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.username || "";

/**
 * Mi cuenta (ADR p70 D8, plan F1.2): lo personal de quien entra, para todo
 * usuario autenticado. Datos de solo lectura (los edita quien gestiona el
 * equipo), contraseña y verificación en dos pasos. Antes vivía dentro de
 * Configuración, adonde no todos pueden entrar.
 */
const Account = () => {
    const { user } = useAuth();
    const role = user?.role === PLATFORM_ROLE ? "Operador de la plataforma" : roleLabel(user?.role);

    return (
        <div className={styles.page}>
            <header className="page-header">
                <div>
                    <h1 className="page-title">Mi cuenta</h1>
                    <p className="page-subtitle">Tus datos de acceso, tu contraseña y la verificación en dos pasos</p>
                </div>
            </header>

            <SettingsPanel
                title="Tus datos"
                description="Si algo no es correcto, pídele el cambio a quien administra el equipo de tu clínica."
            >
                <IdentityHeader name={fullName(user)} meta={[role, user?.organization_name].filter(Boolean)} />
                <SettingRow label="Usuario">
                    <p className={styles.readonlyValue}>{user?.username || "—"}</p>
                </SettingRow>
                <SettingRow label="Correo electrónico">
                    <p className={styles.readonlyValue}>{user?.email || "Sin capturar"}</p>
                </SettingRow>
            </SettingsPanel>

            <SettingsPanel title="Contraseña" description="Actualiza tu contraseña de acceso al sistema.">
                {user?.is_demo ? (
                    <p className={styles.readonlyValue}>En la demo la contraseña no se cambia.</p>
                ) : (
                    <ChangePasswordForm />
                )}
            </SettingsPanel>

            {/* ADR p68: solo aparece si la cuenta puede usarla (ADMIN, fuera de la demo). */}
            <MfaSettings />
        </div>
    );
};

export default Account;
