import { useState } from "react";
import { Navigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import { apiError } from "../../utils/apiError";
import {
    uploadImport, setMapping, validateImport, commitImport,
} from "../../api/imports";
import { getEntityConfig } from "./entityConfig";
import { Icon } from "../../components/icons";
import UploadStep from "./UploadStep";
import MappingStep from "./MappingStep";
import PreviewStep from "./PreviewStep";
import ResultStep from "./ResultStep";
import s from "./imports.module.css";

// Pasos del wizard. El padre es dueño del ImportJob (public_id), del paso actual
// y del objeto job; centraliza TODA la red y el manejo de errores (apiError /
// handleFormError). Los step components solo presentan e informan callbacks.
const STEPS = [
    { key: "upload", label: "Archivo" },
    { key: "mapping", label: "Columnas" },
    { key: "preview", label: "Vista previa" },
    { key: "result", label: "Resultado" },
];

const Stepper = ({ current }) => {
    const idx = STEPS.findIndex(st => st.key === current);
    return (
        <div className={s.stepper}>
            {STEPS.map((st, i) => {
                const state = i < idx ? "done" : i === idx ? "active" : "todo";
                const cls = state === "active" ? s.stepActive : state === "done" ? s.stepDone : "";
                return (
                    <div key={st.key} style={{ display: "flex", alignItems: "center" }}>
                        <span className={`${s.step} ${cls}`}>
                            <span className={s.stepNum}>
                                {state === "done" ? <Icon.Check s={13} c="var(--c-success-text)" /> : i + 1}
                            </span>
                            {st.label}
                        </span>
                        {i < STEPS.length - 1 && <span className={s.stepSep} />}
                    </div>
                );
            })}
        </div>
    );
};

const Imports = () => {
    const { can, initializing } = useAuth();
    const confirm = useConfirm();

    const [entityType, setEntityType] = useState("owner_pet");
    const config = getEntityConfig(entityType);
    const [step, setStep] = useState("upload");
    const [job, setJob] = useState(null);            // ImportJob completo (incluye public_id)
    const [uploading, setUploading] = useState(false);
    const [validating, setValidating] = useState(false);
    const [committing, setCommitting] = useState(false);

    if (initializing) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
                <p style={{ color: "var(--c-text-3)", fontSize: 13 }}>Cargando...</p>
            </div>
        );
    }

    // Gate de acceso a la página: solo quien puede crear importaciones.
    if (!can("import.create")) {
        return <Navigate to="/" replace />;
    }

    const canCommit = can("import.commit");

    // ── Paso 1 → 2: subir archivo ──
    const handleUpload = async (file) => {
        if (uploading) return;
        setUploading(true);
        try {
            const created = await uploadImport(file, entityType);
            setJob(created);
            setStep("mapping");
        } catch (err) {
            // Errores de parseo/tamaño/validación → toast (mismo patrón que el
            // resto del sistema). apiError extrae el `message` accionable; nunca
            // el `code` técnico (import_parse_error, etc.).
            toast.error(apiError(err, "No se pudo subir el archivo"));
        } finally {
            setUploading(false);
        }
    };

    // ── Paso 2 → 3: confirmar mapping + dry-run ──
    const handleMappingContinue = async (mapping) => {
        if (validating || !job) return;
        setValidating(true);
        try {
            const mapped = await setMapping(job.public_id, { mapping });
            setJob(mapped);
            const req = validateImport(job.public_id);
            toast.promise(req, {
                loading: "Validando archivo...",
                success: "Validación lista",
                error: (err) => apiError(err, "No se pudo validar el archivo"),
            });
            const validated = await req;   // await la promesa original (gotcha sonner v2)
            setJob(validated);
            setStep("preview");
        } catch (err) {
            toast.error(apiError(err, "No se pudo validar el archivo"));
        } finally {
            setValidating(false);
        }
    };

    // ── Paso 3 → 4: commit (escribe) ──
    const handleConfirm = async () => {
        if (committing || !job) return;
        const r = job.result || {};
        const createdTotal = Number(r[config.createdTotalKey] || 0);
        const skippedConflicts = Number(r.skipped_conflicts || 0);
        const noun = createdTotal === 1 ? config.nouns.primary : config.nouns.primaryPlural;
        const message = createdTotal > 0
            ? `Se importarán ${createdTotal} ${noun} a tu sistema.`
                + (skippedConflicts > 0 ? ` ${skippedConflicts} posible${skippedConflicts === 1 ? "" : "s"} duplicado${skippedConflicts === 1 ? "" : "s"} se omitirán.` : "")
                + " ¿Confirmar la importación?"
            : "No hay registros nuevos para importar. ¿Deseas continuar?";
        const ok = await confirm({
            message,
            confirmText: "Importar",
        });
        if (!ok) return;

        setCommitting(true);
        try {
            const req = commitImport(job.public_id);
            toast.promise(req, {
                loading: "Importando registros...",
                success: "Importación completada",
                error: (err) => apiError(err, "No se pudo completar la importación"),
            });
            const committed = await req;
            setJob(committed);
            setStep("result");
        } catch (err) {
            toast.error(apiError(err, "No se pudo completar la importación"));
        } finally {
            setCommitting(false);
        }
    };

    const reset = () => {
        setStep("upload");
        setJob(null);
    };

    return (
        <div>
            <div className="page-header">
                <div>
                    <h1 className="page-title">{config.pageTitle}</h1>
                    <p className="page-subtitle">
                        {config.pageSubtitle}
                    </p>
                </div>
            </div>

            <Stepper current={step} />

            {step === "upload" && (
                <>
                    <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
                        <button
                            type="button"
                            className={`btn btn-sm ${entityType === "owner_pet" ? "btn-primary" : "btn-secondary"}`}
                            onClick={() => setEntityType("owner_pet")}
                            disabled={uploading}
                        >
                            Clientes y mascotas
                        </button>
                        <button
                            type="button"
                            className={`btn btn-sm ${entityType === "inventory" ? "btn-primary" : "btn-secondary"}`}
                            onClick={() => setEntityType("inventory")}
                            disabled={uploading}
                        >
                            Productos / Inventario
                        </button>
                    </div>
                    <UploadStep onUpload={handleUpload} uploading={uploading} config={config} />
                </>
            )}

            {step === "mapping" && job && (
                <MappingStep
                    sourceColumns={job.source_columns}
                    sampleRows={job.sample_rows}
                    fieldCatalog={job.field_catalog}
                    initialMapping={
                        job.mapping && Object.keys(job.mapping).length > 0
                            ? job.mapping
                            : (job.suggested_mapping || {})
                    }
                    onContinue={handleMappingContinue}
                    onBack={reset}
                    busy={validating}
                />
            )}

            {step === "preview" && job && (
                <PreviewStep
                    result={job.result}
                    fieldCatalog={job.field_catalog}
                    entityType={entityType}
                    onBack={() => setStep("mapping")}
                    onConfirm={handleConfirm}
                    committing={committing}
                    canCommit={canCommit}
                />
            )}

            {step === "result" && job && (
                <ResultStep
                    result={job.result}
                    job={job}
                    fieldCatalog={job.field_catalog}
                    entityType={entityType}
                    onReset={reset}
                />
            )}
        </div>
    );
};

export default Imports;
