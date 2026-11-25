// Piezas de Equipo que usan la página y la ficha del integrante.
import { useState } from "react";
import { toast } from "sonner";
import { STAFF_ROLE_ORDER, roleLabel, roleSummary } from "./roles";
import { fullName } from "./staffForm";
import styles from "./StaffParts.module.css";

export function FieldError({ id, message }) {
    return message ? <p id={id} className={styles.fieldError}>{message}</p> : null;
}

const initials = (member) => {
    const first = (member?.first_name || member?.username || "?").trim().charAt(0);
    const last = (member?.last_name || "").trim().charAt(0);
    return `${first}${last}`.toUpperCase();
};

/** Iniciales sobre un círculo; decorativo (el nombre va al lado). */
export function MemberAvatar({ member, size = "md" }) {
    return (
        <span className={`${styles.avatar} ${size === "lg" ? styles.avatarLg : ""}`} aria-hidden="true">
            {initials(member)}
        </span>
    );
}

// Credenciales que se muestran una sola vez: la inicial del alta (no vence) y la
// temporal de restablecer, reenviar invitación o reactivar (24 h).
export function CredentialsModal({ result, onClose }) {
    const [copied, setCopied] = useState(false);
    const created = result.kind === "created";
    const title = created ? "Integrante creado" : "Contraseña temporal generada";
    const seconds = result.expires_in_seconds;
    const hours = seconds ? Math.round(seconds / 3600) : null;
    const validity = hours != null
        ? `${hours} ${hours === 1 ? "hora" : "horas"} para iniciar sesión`
        : "Hasta su primer ingreso";

    const copy = async () => {
        const lines = [
            `Usuario: ${result.target.username}`,
            ...(result.target.email ? [`Correo: ${result.target.email}`] : []),
            `Contraseña temporal: ${result.temp_password}`,
            `Válida: ${validity}`,
            "Importante: debe cambiar la contraseña al iniciar sesión.",
        ];
        try {
            await navigator.clipboard.writeText(lines.join("\n"));
            setCopied(true);
            toast.success("Credenciales copiadas.");
            setTimeout(() => setCopied(false), 2500);
        } catch {
            toast.error("No se pudo copiar. Selecciona y copia manualmente.");
        }
    };

    return (
        <div className="modal-overlay">
            <div className="modal modal-sm" role="dialog" aria-modal="true" aria-label={title}>
                <div className="modal-header">
                    <h3>{title}</h3>
                </div>
                <div className="modal-body">
                    {created && (
                        <p className={styles.credentialsIntro}>
                            Entrégale estos datos a {fullName(result.target)} para su primer ingreso.
                        </p>
                    )}
                    <div className={styles.tempWarning}>
                        <strong>⚠ Anota o copia ahora.</strong> Esta contraseña no se vuelve a mostrar. Si la pierdes, deberás restablecerla de nuevo.
                    </div>
                    <dl className={styles.credentials}>
                        <dt>Usuario</dt>
                        <dd className={styles.credentialMono}>{result.target.username}</dd>
                        {result.target.email && (
                            <>
                                <dt>Correo</dt>
                                <dd className={styles.credentialMono}>{result.target.email}</dd>
                            </>
                        )}
                        <dt>Contraseña</dt>
                        <dd className={styles.tempPassword}>{result.temp_password}</dd>
                        <dt>Válida</dt>
                        <dd>{validity}</dd>
                    </dl>
                    <p className={styles.tempNote}>
                        Entra con su correo o su usuario. Deberá cambiar esta contraseña al iniciar sesión. Entrégala en persona o por un canal privado.
                    </p>
                    <div className={styles.modalActions}>
                        <button type="button" className="btn btn-secondary btn-md" onClick={copy}>
                            {copied ? "Copiado ✓" : "Copiar credenciales"}
                        </button>
                        <button type="button" className="btn btn-primary btn-md" onClick={onClose}>
                            Listo
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

// Elección del rol (alta y ficha), con lo que permite cada uno.
export function RolePicker({ value, onChange, name = "create-role", disabled = false }) {
    return (
        <fieldset className={styles.roleOptions} disabled={disabled}>
            <legend className="form-label">ROL *</legend>
            {STAFF_ROLE_ORDER.map((role) => (
                <label key={role} className={`${styles.roleOption}${value === role ? ` ${styles.roleOptionSelected}` : ""}`}>
                    <input
                        type="radio"
                        name={name}
                        value={role}
                        checked={value === role}
                        onChange={() => onChange(role)}
                    />
                    <span>
                        <span className={styles.roleName}>{roleLabel(role)}</span>
                        <span className={styles.roleDescription}>{roleSummary(role)}</span>
                    </span>
                </label>
            ))}
        </fieldset>
    );
}

// ADR p66: solo en ADMIN se elige si atiende pacientes (VET siempre, ASSISTANT nunca).
export function AttendsField({ id, checked, onChange, disabled = false }) {
    return (
        <label className={styles.attendsField} htmlFor={id}>
            <input
                id={id}
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(e) => onChange(e.target.checked)}
            />
            <span>
                <span className={styles.roleName}>Atiende pacientes</span>
                <span className={styles.roleDescription}>
                    Aparece como veterinario en la agenda y puede recibir citas. Requiere cédula profesional.
                </span>
            </span>
        </label>
    );
}
