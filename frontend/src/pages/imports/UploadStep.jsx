import { useRef, useState } from "react";
import { toast } from "sonner";
import { Icon } from "../../components/icons";
import s from "./imports.module.css";

// Extensiones aceptadas en v1 (CSV + XLSX, Ajuste #2 del sprint).
const ACCEPTED = [".csv", ".xlsx"];
// Tope de tamaño (igual al backend parsers.MAX_FILE_BYTES). Pre-check en cliente
// para feedback inmediato; el backend sigue siendo la fuente de verdad.
const MAX_BYTES = 5 * 1024 * 1024;

const hasAcceptedExt = (name = "") =>
    ACCEPTED.some(ext => name.toLowerCase().endsWith(ext));

const formatSize = (bytes) => {
    if (!bytes) return "";
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(0)} KB`;
    return `${(kb / 1024).toFixed(1)} MB`;
};

/* Paso 1 — Subir archivo.
   `entity_type` está fijo a 'owner_pet' en v1 (no hay selector). El padre
   (index.jsx) es dueño de la llamada de red (uploadImport) para centralizar
   el manejo de errores; aquí solo se elige el archivo y se valida la extensión. */
const UploadStep = ({ onUpload, uploading }) => {
    const inputRef = useRef(null);
    const [file, setFile] = useState(null);
    const [dragOver, setDragOver] = useState(false);

    const pickFile = (candidate) => {
        if (!candidate) return;
        if (!hasAcceptedExt(candidate.name)) {
            toast.error("Formato no válido. Sube un archivo .csv o .xlsx.");
            return;
        }
        if (candidate.size > MAX_BYTES) {
            toast.error(`El archivo pesa demasiado (${formatSize(candidate.size)}). El máximo es 5 MB.`);
            return;
        }
        setFile(candidate);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setDragOver(false);
        if (uploading) return;
        pickFile(e.dataTransfer.files?.[0]);
    };

    const handleSubmit = () => {
        if (!file) { toast.error("Selecciona un archivo primero."); return; }
        onUpload(file);
    };

    return (
        <div className="card">
            <div style={{ marginBottom: 18 }}>
                <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 3 }}>Sube tu archivo de clientes y mascotas</p>
                <p style={{ fontSize: 12.5, color: "var(--c-text-2)" }}>
                    Acepta Excel (.xlsx) o CSV (.csv). La primera fila debe contener los
                    encabezados de cada columna. En el siguiente paso eliges qué columna
                    corresponde a cada dato.
                </p>
            </div>

            <div
                className={`${s.dropZone} ${dragOver ? s.dropZoneOver : ""}`}
                onClick={() => !uploading && inputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); if (!uploading) setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !uploading) inputRef.current?.click(); }}
                aria-label="Seleccionar archivo para importar"
            >
                <Icon.Upload s={30} c="var(--c-text-3)" />
                <p className={s.dropTitle}>Arrastra tu archivo aquí o haz clic para buscar</p>
                <p className={s.dropHint}>Formatos: .xlsx · .csv — máximo 5 MB</p>

                <input
                    ref={inputRef}
                    type="file"
                    accept=".csv,.xlsx"
                    style={{ display: "none" }}
                    onChange={(e) => pickFile(e.target.files?.[0])}
                    disabled={uploading}
                />
            </div>

            {file && (
                <div className={s.fileChip}>
                    <Icon.FileText s={18} c="var(--c-primary)" />
                    <div style={{ textAlign: "left" }}>
                        <div className={s.fileName}>{file.name}</div>
                        <div className={s.fileMeta}>{formatSize(file.size)}</div>
                    </div>
                </div>
            )}

            <div className={s.actions}>
                <span style={{ fontSize: 12, color: "var(--c-text-3)" }}>
                    Importarás <strong>clientes y sus mascotas</strong>.
                </span>
                <div className={s.actionsRight}>
                    <button
                        className="btn btn-primary btn-md"
                        onClick={handleSubmit}
                        disabled={uploading || !file}
                    >
                        {uploading ? "Subiendo..." : "Subir y continuar"}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default UploadStep;
