// Verificación en dos pasos (ADR p68): opcional y solo para ADMIN. La clave se
// teclea en la app autenticadora (sin QR, decisión del PO); al activar se dan 10
// códigos de respaldo de un solo uso. Si se pierden el celular y los códigos,
// otro ADMIN o soporte restablece la contraseña, y eso quita el MFA.
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
    disableMfa, enableMfa, getMfaStatus, regenerateRecoveryCodes, startMfaSetup,
} from "../../api/mfa";
import { Icon } from "../../components/icons";
import { apiError } from "../../utils/apiError";
import handleFormError from "../../utils/handleFormError";
import { formatDate, orgTz } from "../../utils/datetime";
import { useAuth } from "../../auth/authContext";
import styles from "./config.module.css";

const copyText = async (text, okMessage) => {
    try {
        await navigator.clipboard.writeText(text);
        toast.success(okMessage);
    } catch {
        toast.error("No se pudo copiar; selecciona el texto y cópialo a mano.");
    }
};

function RecoveryCodes({ codes, onDone }) {
    return (
        <>
            <p className={styles.mfaText}>
                Guárdalos en un lugar seguro. Cada uno sirve <strong>una sola vez</strong> para entrar si
                no tienes el celular. No se volverán a mostrar.
            </p>
            <ul className={styles.mfaCodes} aria-label="Códigos de respaldo">
                {codes.map((code) => <li key={code}>{code}</li>)}
            </ul>
            <div className="modal-footer">
                <button type="button" className="btn btn-secondary btn-md" style={{ flex: 1 }}
                    onClick={() => copyText(codes.join("\n"), "Códigos copiados")}>
                    Copiar códigos
                </button>
                <button type="button" className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={onDone}>
                    Ya los guardé
                </button>
            </div>
        </>
    );
}

function FieldError({ message }) {
    return message ? <p className={styles.mfaError}>{message}</p> : null;
}

// Alta: contraseña → clave para la app → primer código → códigos de respaldo.
function EnableFlow({ onClose, onChanged }) {
    const [step, setStep] = useState("password");
    const [password, setPassword] = useState("");
    const [code, setCode] = useState("");
    const [setup, setSetup] = useState(null);
    const [codes, setCodes] = useState(null);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);

    const submitPassword = async (event) => {
        event.preventDefault();
        if (!password) { setErrors({ password: "Escribe tu contraseña" }); return; }
        setSaving(true);
        try {
            setSetup(await startMfaSetup(password));
            setErrors({});
            setStep("key");
        } catch (err) {
            handleFormError(err, setErrors);
        } finally {
            setSaving(false);
        }
    };

    const submitCode = async (event) => {
        event.preventDefault();
        if (!code.trim()) { setErrors({ code: "Escribe el código que muestra la app" }); return; }
        setSaving(true);
        try {
            const result = await enableMfa(code.trim());
            setCodes(result.recovery_codes);
            setStep("codes");
            toast.success("Verificación en dos pasos activada");
            onChanged(result);
        } catch (err) {
            handleFormError(err, setErrors);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="modal-body">
            {step === "password" && (
                <form onSubmit={submitPassword}>
                    <p className={styles.mfaText}>
                        Además de tu contraseña, al entrar te pediremos un código de 6 dígitos de una app
                        autenticadora en tu celular (Google Authenticator, Microsoft Authenticator u otra).
                    </p>
                    <div className="form-group">
                        <label className="form-label" htmlFor="mfa-password">CONFIRMA TU CONTRASEÑA</label>
                        <input id="mfa-password" type="password" className="input" value={password}
                            autoComplete="current-password" onChange={(e) => setPassword(e.target.value)}
                            disabled={saving} />
                        <FieldError message={errors.password} />
                    </div>
                    <button type="submit" className="btn btn-primary btn-md" disabled={saving}>
                        {saving ? "Comprobando..." : "Continuar"}
                    </button>
                </form>
            )}
            {step === "key" && setup && (
                <form onSubmit={submitCode}>
                    <ol className={styles.mfaSteps}>
                        <li>En tu app autenticadora elige <strong>Agregar cuenta → Introducir clave de configuración</strong>, tipo <strong>basada en tiempo</strong>.</li>
                        <li>
                            Escribe esta clave:
                            <span className={styles.mfaKey} data-testid="mfa-secret">{setup.secret}</span>
                            <button type="button" className="btn btn-ghost btn-sm"
                                onClick={() => copyText(setup.secret.replace(/\s/g, ""), "Clave copiada")}>
                                Copiar clave
                            </button>
                            {" "}<a href={setup.otpauth_uri} className={styles.mfaLink}>Abrir en la app (desde el celular)</a>
                        </li>
                        <li>Escribe el código de 6 dígitos que muestra la app.</li>
                    </ol>
                    <div className="form-group">
                        <label className="form-label" htmlFor="mfa-enable-code">CÓDIGO DE LA APP</label>
                        <input id="mfa-enable-code" className="input" inputMode="numeric" autoComplete="one-time-code"
                            value={code} onChange={(e) => setCode(e.target.value)} disabled={saving} />
                        <FieldError message={errors.code} />
                    </div>
                    <button type="submit" className="btn btn-primary btn-md" disabled={saving}>
                        {saving ? "Activando..." : "Activar"}
                    </button>
                </form>
            )}
            {step === "codes" && codes && <RecoveryCodes codes={codes} onDone={onClose} />}
        </div>
    );
}

// Desactivar o generar códigos nuevos: contraseña + código (de la app o de respaldo).
function ConfirmFlow({ mode, onClose, onChanged }) {
    const [password, setPassword] = useState("");
    const [code, setCode] = useState("");
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [codes, setCodes] = useState(null);

    const submit = async (event) => {
        event.preventDefault();
        const missing = {};
        if (!password) missing.password = "Escribe tu contraseña";
        if (!code.trim()) missing.code = "Escribe un código de la app o de respaldo";
        if (Object.keys(missing).length) { setErrors(missing); return; }
        setSaving(true);
        try {
            if (mode === "disable") {
                const status = await disableMfa({ password, code: code.trim() });
                toast.success("Verificación en dos pasos desactivada");
                onChanged(status);
                onClose();
            } else {
                const result = await regenerateRecoveryCodes({ password, code: code.trim() });
                setCodes(result.recovery_codes);
                onChanged(result);
            }
        } catch (err) {
            handleFormError(err, setErrors);
        } finally {
            setSaving(false);
        }
    };

    if (codes) {
        return <div className="modal-body"><RecoveryCodes codes={codes} onDone={onClose} /></div>;
    }
    return (
        <div className="modal-body">
            <form onSubmit={submit}>
                <p className={styles.mfaText}>
                    {mode === "disable"
                        ? "Al entrar solo te pediremos la contraseña."
                        : "Los códigos de respaldo anteriores dejarán de servir."}
                </p>
                <div className="form-group">
                    <label className="form-label" htmlFor="mfa-confirm-password">CONTRASEÑA</label>
                    <input id="mfa-confirm-password" type="password" className="input" value={password}
                        autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} disabled={saving} />
                    <FieldError message={errors.password} />
                </div>
                <div className="form-group">
                    <label className="form-label" htmlFor="mfa-confirm-code">CÓDIGO DE LA APP O DE RESPALDO</label>
                    <input id="mfa-confirm-code" className="input" autoComplete="one-time-code"
                        value={code} onChange={(e) => setCode(e.target.value)} disabled={saving} />
                    <FieldError message={errors.code} />
                </div>
                <button type="submit" className={`btn btn-md ${mode === "disable" ? "btn-danger" : "btn-primary"}`} disabled={saving}>
                    {saving ? "Guardando..." : mode === "disable" ? "Desactivar" : "Generar códigos nuevos"}
                </button>
            </form>
        </div>
    );
}

const TITLES = {
    enable: "Activar verificación en dos pasos",
    disable: "Desactivar verificación en dos pasos",
    codes: "Nuevos códigos de respaldo",
};

export default function MfaSettings() {
    const { user } = useAuth();
    const [status, setStatus] = useState(null);
    const [flow, setFlow] = useState(null);

    useEffect(() => {
        let alive = true;
        getMfaStatus()
            .then((data) => { if (alive) setStatus(data); })
            .catch((err) => console.error(apiError(err)));
        return () => { alive = false; };
    }, []);

    if (!status?.available) return null;

    const onChanged = (data) => setStatus((current) => ({ ...current, ...data }));
    const tz = orgTz(user);

    return (
        <>
            <div className={styles.accountRow}>
                <div className={styles.accountIcon}>
                    <Icon.Lock s={18} c="var(--c-primary)" />
                </div>
                <div className={styles.accountInfo}>
                    <p className={styles.accountLabel}>Verificación en dos pasos</p>
                    <p className={styles.accountDesc}>
                        {status.enabled
                            ? `Activa${status.enabled_at ? ` desde ${formatDate(status.enabled_at, tz, "es-MX")}` : ""} · ${status.recovery_codes_remaining} códigos de respaldo`
                            : "Pide un código de tu celular además de la contraseña."}
                    </p>
                </div>
                {status.enabled ? (
                    <div className={styles.mfaActions}>
                        <button className="btn btn-secondary btn-sm" onClick={() => setFlow("codes")}>Nuevos códigos</button>
                        <button className="btn btn-secondary btn-sm" onClick={() => setFlow("disable")}>Desactivar</button>
                    </div>
                ) : (
                    <button className="btn btn-secondary btn-sm" onClick={() => setFlow("enable")}>Activar</button>
                )}
            </div>
            {flow && (
                <div className="modal-overlay">
                    <div className="modal modal-sm" role="dialog" aria-label={TITLES[flow]}>
                        <div className="modal-header">
                            <h3>{TITLES[flow]}</h3>
                            <button className="modal-close" onClick={() => setFlow(null)} aria-label="Cerrar">
                                <Icon.X s={16} />
                            </button>
                        </div>
                        {flow === "enable"
                            ? <EnableFlow onClose={() => setFlow(null)} onChanged={onChanged} />
                            : <ConfirmFlow mode={flow === "disable" ? "disable" : "codes"} onClose={() => setFlow(null)} onChanged={onChanged} />}
                    </div>
                </div>
            )}
        </>
    );
}
