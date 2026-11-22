import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { provisionOrganization } from "../../api/platform";
import { useAuth } from "../../auth/authContext";
import { Icon } from "../../components/icons";
import handleFormError from "../../utils/handleFormError";

const EMPTY_FORM = {
    name: "",
    timezone: "America/Mexico_City",
    tax_rate: "0.1600",
    admin_username: "",
    admin_email: "",
    admin_password: "",
    admin_first_name: "",
    admin_last_name: "",
};

const TIMEZONE_OPTIONS = [
    "America/Mexico_City",
    "America/Cancun",
    "America/Tijuana",
    "America/Monterrey",
    "America/Hermosillo",
    "America/Chihuahua",
    "America/Mazatlan",
];

const TAX_PRESETS = [
    { value: "0.0000", label: "Sin IVA (0%)" },
    { value: "0.0800", label: "IVA 8% (frontera)" },
    { value: "0.1600", label: "IVA 16% (general)" },
];

const CreateOrganization = () => {
    const { user, initializing } = useAuth();
    const navigate = useNavigate();

    const [form, setForm] = useState(EMPTY_FORM);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [result, setResult] = useState(null);

    if (initializing) return null;

    // Gate — only ADMIN_SAAS may access this page.
    if (!user || user.role !== "ADMIN_SAAS") {
        return <Navigate to="/" replace />;
    }

    const handleChange = (field) => (e) => {
        setForm({ ...form, [field]: e.target.value });
        if (errors[field]) {
            setErrors({ ...errors, [field]: undefined });
        }
    };

    const clientSideValidate = () => {
        const errs = {};
        if (!form.name.trim()) errs.name = "Nombre requerido.";
        if (!form.admin_username.trim()) errs.admin_username = "Usuario requerido.";
        if (!form.admin_email.trim()) errs.admin_email = "Correo electrónico requerido.";
        else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.admin_email))
            errs.admin_email = "Correo electrónico inválido.";
        if (!form.admin_first_name.trim()) errs.admin_first_name = "Nombre requerido.";
        if (!form.admin_last_name.trim()) errs.admin_last_name = "Apellido requerido.";
        if (!form.admin_password || form.admin_password.length < 12)
            errs.admin_password = "Mínimo 12 caracteres.";
        else if (/^\d+$/.test(form.admin_password))
            errs.admin_password = "No puede ser solo numérico.";
        const taxNum = parseFloat(form.tax_rate);
        if (Number.isNaN(taxNum) || taxNum < 0 || taxNum > 1)
            errs.tax_rate = "tax_rate entre 0 y 1.";
        return errs;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const clientErrs = clientSideValidate();
        if (Object.keys(clientErrs).length > 0) {
            setErrors(clientErrs);
            toast.error("Revisa los campos marcados.");
            return;
        }

        setErrors({});
        setSaving(true);
        try {
            const data = await provisionOrganization(form);
            setResult({
                ...data,
                admin_password_shown_once: form.admin_password,
            });
            toast.success(`Clínica "${data.organization.name}" creada.`);
            setForm(EMPTY_FORM);
        } catch (err) {
            const status = err?.response?.status;
            if (status === 403) {
                toast.error("Solo operadores de plataforma pueden crear clínicas.");
            } else if (status === 429) {
                toast.error("Límite de 20 clínicas por hora alcanzado. Espera un momento.");
            } else {
                handleFormError(err, setErrors);
            }
        } finally {
            setSaving(false);
        }
    };

    const fieldError = (field) => errors?.[field];

    const inputClass = (field) =>
        fieldError(field) ? "input input-error" : "input";

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">Crear clínica</h1>
                    <p className="page-subtitle">
                        Provisión de un nuevo tenant + administrador inicial. Acceso restringido a ADMIN_SAAS.
                    </p>
                </div>
                <button
                    className="btn btn-ghost btn-md"
                    onClick={() => navigate("/")}
                    type="button"
                >
                    Volver al dashboard
                </button>
            </div>

            {result && <SuccessCard result={result} onCreateAnother={() => setResult(null)} />}

            {!result && (
                <form onSubmit={handleSubmit} style={{ maxWidth: "720px" }}>
                    <Section title="Organización" subtitle="Datos de la clínica nueva.">
                        <Field label="Nombre de la clínica" required error={fieldError("name")}>
                            <input
                                className={inputClass("name")}
                                placeholder="Clínica San Lázaro"
                                value={form.name}
                                onChange={handleChange("name")}
                                autoFocus
                            />
                        </Field>

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 14px" }}>
                            <Field label="Zona horaria" error={fieldError("timezone")}>
                                <select
                                    className={inputClass("timezone")}
                                    value={form.timezone}
                                    onChange={handleChange("timezone")}
                                >
                                    {TIMEZONE_OPTIONS.map((tz) => (
                                        <option key={tz} value={tz}>{tz}</option>
                                    ))}
                                </select>
                            </Field>

                            <Field label="IVA aplicado" error={fieldError("tax_rate")}>
                                <select
                                    className={inputClass("tax_rate")}
                                    value={form.tax_rate}
                                    onChange={handleChange("tax_rate")}
                                >
                                    {TAX_PRESETS.map((p) => (
                                        <option key={p.value} value={p.value}>{p.label}</option>
                                    ))}
                                </select>
                            </Field>
                        </div>
                    </Section>

                    <Section title="Administrador inicial" subtitle="Cuenta ADMIN de la clínica que estás creando.">
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 14px" }}>
                            <Field label="Nombre" required error={fieldError("admin_first_name")}>
                                <input
                                    className={inputClass("admin_first_name")}
                                    placeholder="Mariana"
                                    value={form.admin_first_name}
                                    onChange={handleChange("admin_first_name")}
                                />
                            </Field>

                            <Field label="Apellido" required error={fieldError("admin_last_name")}>
                                <input
                                    className={inputClass("admin_last_name")}
                                    placeholder="Reyes"
                                    value={form.admin_last_name}
                                    onChange={handleChange("admin_last_name")}
                                />
                            </Field>
                        </div>

                        <Field label="Usuario" required error={fieldError("admin_username")}>
                            <input
                                className={inputClass("admin_username")}
                                placeholder="sanlazaro_admin"
                                value={form.admin_username}
                                onChange={handleChange("admin_username")}
                            />
                        </Field>

                        <Field label="Correo electrónico" required error={fieldError("admin_email")}>
                            <input
                                type="email"
                                className={inputClass("admin_email")}
                                placeholder="admin@sanlazaro.mx"
                                value={form.admin_email}
                                onChange={handleChange("admin_email")}
                            />
                        </Field>

                        <Field
                            label="Contraseña temporal"
                            required
                            error={fieldError("admin_password")}
                            hint="Mínimo 12 caracteres. Se mostrará una vez tras crear — anótala antes de cerrar la página."
                        >
                            <input
                                type="text"
                                className={inputClass("admin_password")}
                                placeholder="TempPass-Strong-2026!"
                                value={form.admin_password}
                                onChange={handleChange("admin_password")}
                                autoComplete="off"
                                spellCheck="false"
                            />
                        </Field>
                    </Section>

                    <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
                        <button
                            type="submit"
                            className="btn btn-primary btn-md"
                            disabled={saving}
                        >
                            {saving ? "Creando..." : "Crear clínica + administrador"}
                        </button>
                    </div>
                </form>
            )}
        </div>
    );
};

const Section = ({ title, subtitle, children }) => (
    <div style={{ marginBottom: "20px" }}>
        <h3 style={{ fontSize: "14px", fontWeight: "600", color: "var(--c-text-1)", marginBottom: "2px" }}>
            {title}
        </h3>
        {subtitle && (
            <p style={{ fontSize: "12px", color: "var(--c-text-3)", marginBottom: "12px" }}>
                {subtitle}
            </p>
        )}
        <div>{children}</div>
    </div>
);

const Field = ({ label, required, error, hint, children }) => (
    <div className="form-group">
        <label className="form-label">
            {label.toUpperCase()} {required && <span style={{ color: "var(--c-danger)" }}>*</span>}
        </label>
        {children}
        {hint && !error && (
            <div style={{ fontSize: "11px", color: "var(--c-text-3)", marginTop: "4px" }}>
                {hint}
            </div>
        )}
        {error && (
            <div style={{ fontSize: "11px", color: "var(--c-danger)", marginTop: "4px" }}>
                {error}
            </div>
        )}
    </div>
);

const SuccessCard = ({ result, onCreateAnother }) => {
    const [copied, setCopied] = useState(false);

    const credentialsText =
        `Clínica: ${result.organization.name}\n` +
        `Login: ${result.admin.username}\n` +
        `Correo electrónico: ${result.admin.email}\n` +
        `Contraseña temporal: ${result.admin_password_shown_once}\n` +
        `\n` +
        `Organization public_id: ${result.organization.public_id}\n` +
        `Admin public_id: ${result.admin.public_id}`;

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(credentialsText);
            setCopied(true);
            toast.success("Credenciales copiadas al portapapeles.");
            setTimeout(() => setCopied(false), 2500);
        } catch {
            toast.error("No se pudo copiar. Selecciona y copia manualmente.");
        }
    };

    return (
        <div style={{
            border: "1px solid rgba(26,68,52,0.35)",
            background: "rgba(26,68,52,0.06)",
            borderRadius: "10px",
            padding: "16px 20px",
            marginBottom: "20px",
            maxWidth: "720px",
        }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
                <Icon.CheckCircle s={20} c="var(--c-primary)" />
                <h3 style={{ fontSize: "16px", fontWeight: "600", color: "var(--c-text-1)", margin: 0 }}>
                    Clínica creada exitosamente
                </h3>
            </div>

            <div style={{
                background: "rgba(251,191,36,0.10)",
                border: "1px solid rgba(251,191,36,0.30)",
                borderRadius: "6px",
                padding: "10px 12px",
                marginBottom: "14px",
                fontSize: "12.5px",
                color: "#fbbf24",
            }}>
                <strong>⚠ Anota o copia la contraseña ahora.</strong> Por seguridad no se vuelve a mostrar.
                Envíasela al administrador de la clínica por canal seguro (no Slack/WhatsApp/SMS).
            </div>

            <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "8px 14px", margin: 0 }}>
                <Row label="Clínica" value={result.organization.name} />
                <Row label="Login" value={result.admin.username} mono />
                <Row label="Correo electrónico" value={result.admin.email} mono />
                <Row label="Contraseña" value={result.admin_password_shown_once} mono highlight />
                <Row label="Org public_id" value={result.organization.public_id} mono small />
                <Row label="Admin public_id" value={result.admin.public_id} mono small />
                <Row label="Request ID" value={result.request_id} mono small />
                <Row label="Duración" value={`${result.duration_ms} ms`} small />
            </dl>

            <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
                <button
                    type="button"
                    className="btn btn-secondary btn-md"
                    onClick={handleCopy}
                >
                    {copied ? "Copiado ✓" : "Copiar credenciales"}
                </button>
                <button
                    type="button"
                    className="btn btn-primary btn-md"
                    onClick={onCreateAnother}
                >
                    Crear otra clínica
                </button>
            </div>
        </div>
    );
};

const Row = ({ label, value, mono, small, highlight }) => (
    <>
        <dt style={{ fontSize: "11.5px", color: "var(--c-text-3)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: "500" }}>
            {label}
        </dt>
        <dd style={{
            margin: 0,
            fontSize: small ? "11.5px" : "13px",
            color: highlight ? "#fbbf24" : "var(--c-text-1)",
            fontFamily: mono ? "var(--font-mono)" : "inherit",
            wordBreak: "break-all",
            fontWeight: highlight ? "600" : "400",
        }}>
            {value}
        </dd>
    </>
);

export default CreateOrganization;
