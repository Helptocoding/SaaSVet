import { AnimatePresence, motion } from "framer-motion";
import { Icon } from "../../components/icons";
import styles from "./medicalRecords.module.css";

const MONTHS = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

const truncate = (t, n) => (!t ? "" : t.length > n ? t.slice(0, n) + "…" : t);

const getVetName = (r) => {
  const v = r.veterinarian;
  if (!v) return null;
  return [v.first_name, v.last_name].filter(Boolean).join(" ") || v.username || null;
};

const TimelineCard = ({
  record, typeMeta, isExpanded, onToggle,
  onClose, onEdit, onDelete,
  onCreatePrescription, onDownloadPrescription,
  onDownloadRecordPdf, downloadingRecordPdfId,
  downloadingPrescriptionId, canCreate,
}) => {
  const d        = new Date(record.latest_vitals?.recorded_at || record.created_at);
  const dateStr  = `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  const vetName  = getVetName(record);
  const isClosed = record.status === "closed";
  const hasPrx   = !!record.prescription_summary?.id;
  const vitals   = record.latest_vitals;
  const canEdit  = record.can_modify_charges;
  const canClose = record.can_close;
  const canDel   = !!record.can_delete;

  // Valoración estructurada (protocolo General). exam = {sistema:{status,finding}}.
  const assess = record.consultation_assessment;
  const alteredExam = assess?.exam && typeof assess.exam === "object"
    ? Object.entries(assess.exam).filter(([, v]) => v && (v.status === "altered" || v.finding))
    : [];
  const hasAssessDetail = !!(assess && (assess.history || alteredExam.length || assess.differentials || assess.recheck_date));

  // Protocolos Cirugía / Urgencia (A3).
  const surgery = record.surgery_record;
  const emergency = record.emergency_record;

  const hasExpandable = !!(
    record.notes ||
    hasAssessDetail ||
    surgery ||
    emergency ||
    record.products_used?.length > 0 ||
    (hasPrx && record.prescription_summary?.items?.length > 0)
  );
  const canDownloadRecord = !!record.public_id;
  const hasActions = hasPrx || canDownloadRecord || (!hasPrx && !isClosed && canCreate) || canEdit || canClose || canDel;

  return (
    <article
        className={`card ${styles.txCard} ${isExpanded ? styles.txCardOpen : ""}`}
      style={{ "--tx-color": typeMeta.color, "--tx-soft": typeMeta.soft || "#f0f9f4" }}
    >
      {/* ── Header: tipo · fecha · vet | badges · chevron ── */}
      <div
        className={`${styles.txHead} ${hasExpandable ? styles.txHeadClickable : ""}`}
        onClick={() => hasExpandable && onToggle?.()}
      >
        <div className={styles.txHeadLeft}>
          <span
            className={styles.txTypePill}
            style={{ color: typeMeta.color, background: typeMeta.soft || "var(--c-subtle)" }}
          >
            {typeMeta.label}
          </span>
          <span className={styles.txDate}>{dateStr}</span>
          {vetName && <span className={styles.txVet}>· Dr. {vetName}</span>}
        </div>

        <div className={styles.txHeadRight}>
          <span className={isClosed ? styles.txBadgeClosed : styles.txBadgeOpen}>
            {isClosed ? "Cerrada" : "Abierta"}
          </span>
          {hasPrx && (
            <span className={styles.txBadgeGreen}>
              <Icon.Pill s={10} /> Receta
            </span>
          )}
          {record.invoice_status && (
            <span className={styles.txBadgeBlue}>
              <Icon.Receipt s={10} /> Cobro
            </span>
          )}
          {hasExpandable && (
            <button
              className={styles.txToggle}
              onClick={(e) => { e.stopPropagation(); onToggle?.(); }}
              title={isExpanded ? "Ocultar detalles" : "Ver notas y más"}
            >
              {isExpanded ? <Icon.ChevronUp s={14} /> : <Icon.ChevronDown s={14} />}
            </button>
          )}
        </div>
      </div>

      {/* ── Contenido principal: motivo · diagnóstico · tratamiento · vitales ── */}
      <div className={styles.txContent}>
        {assess?.chief_complaint && (
          <p className={styles.txMotivo}>
            <span className={styles.txMotivoLabel}>Motivo</span>
            {truncate(assess.chief_complaint, 120)}
          </p>
        )}
        <p className={styles.txDiagnosis}>
          {record.diagnosis
            ? truncate(record.diagnosis, 180)
            : <span className={styles.txNone}>Sin diagnóstico registrado</span>}
        </p>

        {record.treatment && (
          <p className={styles.txTreatment}>{truncate(record.treatment, 130)}</p>
        )}

        {surgery && (
          <p className={styles.txMotivo}>
            <span className={styles.txMotivoLabel}>Cirugía</span>
            {surgery.surgery_type_display}
            {surgery.procedure ? ` · ${truncate(surgery.procedure, 110)}` : ""}
          </p>
        )}
        {emergency && (
          <p className={styles.txMotivo}>
            <span className={styles.txMotivoLabel}>Urgencia</span>
            Triage {emergency.triage_level_display}
            {emergency.chief_complaint ? ` · ${truncate(emergency.chief_complaint, 90)}` : ""}
            {` · Egreso: ${emergency.discharge_status_display}`}
          </p>
        )}

        {vitals && (
          <div className={styles.txVitals}>
            {vitals.weight        != null && <span><Icon.ArrowUp s={10} /> {Number(vitals.weight).toFixed(1)} kg</span>}
            {vitals.temperature   != null && <span><Icon.Activity s={10} /> {Number(vitals.temperature).toFixed(1)} °C</span>}
            {vitals.heart_rate    != null && <span><Icon.Heart s={10} /> FC {vitals.heart_rate}</span>}
            {vitals.respiratory_rate != null && <span>FR {vitals.respiratory_rate}</span>}
          </div>
        )}
      </div>

      {/* ── Acciones — siempre visibles ── */}
      {hasActions && (
        <div className={styles.txFooter}>
          {hasPrx && (
            <button
              className="btn btn-secondary btn-sm btn-row-action"
              disabled={downloadingPrescriptionId === record.prescription_summary.public_id}
              onClick={(e) => { e.stopPropagation(); onDownloadPrescription?.(record.prescription_summary.public_id); }}
            >
              {downloadingPrescriptionId === record.prescription_summary.public_id
                ? <Icon.Loader s={13} /> : <Icon.Download s={13} />}
              Descargar receta
            </button>
          )}
          {canDownloadRecord && (
            <button
              className="btn btn-secondary btn-sm btn-row-action"
              disabled={downloadingRecordPdfId === record.public_id}
              onClick={(e) => { e.stopPropagation(); onDownloadRecordPdf?.(record.public_id); }}
            >
              {downloadingRecordPdfId === record.public_id
                ? <Icon.Loader s={13} /> : <Icon.Download s={13} />}
              Descargar PDF resumen
            </button>
          )}
          {!hasPrx && !isClosed && canCreate && (
            <button
              className="btn btn-secondary btn-sm btn-row-action"
              onClick={(e) => { e.stopPropagation(); onCreatePrescription?.(); }}
            >
              <Icon.Pill s={13} /> Nueva receta
            </button>
          )}
          {canEdit && (
            <button
              className="btn btn-secondary btn-sm btn-row-action"
              onClick={(e) => { e.stopPropagation(); onEdit?.(); }}
            >
              <Icon.Edit s={13} /> Editar
            </button>
          )}
          {canClose && (
            <button
              className="btn btn-secondary btn-sm btn-row-action"
              onClick={(e) => { e.stopPropagation(); onClose?.(); }}
            >
              <Icon.CheckCircle s={13} /> Finalizar
            </button>
          )}
          {canDel && (
            <button
              className="btn btn-danger btn-sm btn-row-action"
              onClick={(e) => { e.stopPropagation(); onDelete?.(); }}
            >
              <Icon.Trash s={13} /> Eliminar
            </button>
          )}
        </div>
      )}

      {/* ── Expand: notas · productos · receta (sin repetir diagnóstico) ── */}
      <AnimatePresence initial={false}>
        {isExpanded && hasExpandable && (
          <motion.div
            className={styles.txExpanded}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className={styles.txExpandedInner}>
              {record.notes && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Notas clínicas</p>
                  <p className={styles.txText}>{record.notes}</p>
                </div>
              )}
              {assess?.history && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Historia clínica</p>
                  <p className={styles.txText}>{assess.history}</p>
                </div>
              )}
              {alteredExam.length > 0 && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Exploración — hallazgos</p>
                  <div className={styles.txChips}>
                    {alteredExam.map(([sys, v], i) => (
                      <span key={i} className={styles.txChip}>
                        {sys.replace(/_/g, " ")}{v.finding ? `: ${v.finding}` : ""}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {assess?.differentials && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Diagnósticos diferenciales</p>
                  <p className={styles.txText}>{assess.differentials}</p>
                </div>
              )}
              {surgery && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Informe quirúrgico</p>
                  <div className={styles.txChips}>
                    <span className={styles.txChip}>{surgery.surgery_type_display}</span>
                    <span className={styles.txChip}>ASA {surgery.asa_class}{surgery.asa_emergency ? "E" : ""}</span>
                    <span className={styles.txChip}>{surgery.anesthesia_type_display}</span>
                    {surgery.wound_class_display && <span className={styles.txChip}>{surgery.wound_class_display}</span>}
                  </div>
                  {surgery.preop_diagnosis && <p className={styles.txText}><b>Dx prequirúrgico:</b> {surgery.preop_diagnosis}</p>}
                  {surgery.procedure && <p className={styles.txText}><b>Procedimiento:</b> {surgery.procedure}</p>}
                  {surgery.findings && <p className={styles.txText}><b>Hallazgos:</b> {surgery.findings}</p>}
                  {surgery.complications && <p className={styles.txText}><b>Complicaciones:</b> {surgery.complications}</p>}
                  {surgery.postop_instructions && <p className={styles.txText}><b>Postoperatorio:</b> {surgery.postop_instructions}</p>}
                  {surgery.suture_removal_date && <p className={styles.txText}><b>Retiro de puntos:</b> {surgery.suture_removal_date}</p>}
                </div>
              )}
              {emergency && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Informe de urgencia</p>
                  <div className={styles.txChips}>
                    <span className={styles.txChip}>Triage {emergency.triage_level_display}</span>
                    <span className={styles.txChip}>Egreso: {emergency.discharge_status_display}</span>
                  </div>
                  <p className={styles.txText}><b>ABC:</b> A {emergency.airway_status_display} · B {emergency.breathing_status_display} · C {emergency.circulation_status_display}</p>
                  {emergency.chief_complaint && <p className={styles.txText}><b>Problema:</b> {emergency.chief_complaint}</p>}
                  {emergency.stabilization_actions && <p className={styles.txText}><b>Acciones:</b> {emergency.stabilization_actions}</p>}
                  {emergency.response && <p className={styles.txText}><b>Respuesta:</b> {emergency.response}</p>}
                  {emergency.reassessment_date && <p className={styles.txText}><b>Revaloración:</b> {emergency.reassessment_date}</p>}
                </div>
              )}
              {record.products_used?.length > 0 && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Productos utilizados</p>
                  <div className={styles.txChips}>
                    {record.products_used.map((p, i) => (
                      <span key={i} className={styles.txChip}>
                        {p.product_name} · {p.quantity} {p.base_unit_display || ""}
                        <span className={`${styles.txChipBadge} ${p.cost_behavior === 'included' ? styles.txChipBadgeIncluido : styles.txChipBadgeCobrado}`}>
                          {p.cost_behavior === 'included' ? 'insumo' : 'cobrado'}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {hasPrx && record.prescription_summary.items?.length > 0 && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Medicamentos recetados</p>
                  <div className={styles.txPrxList}>
                    {record.prescription_summary.items.map((item, i) => (
                      <div key={i} className={styles.txPrxRow}>
                        <span className={styles.txPrxName}>{item.product_name}</span>
                        <div className={styles.txPrxMeta}>
                          {item.dose     && <span>{item.dose}</span>}
                          {item.duration && <span>{item.duration}</span>}
                          {item.quantity && <span>×{item.quantity}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {assess?.recheck_date && (
                <div className={styles.txSection}>
                  <p className={styles.txLabel}>Próxima revisión</p>
                  <p className={styles.txText}>{assess.recheck_date}</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </article>
  );
};

export default TimelineCard;
