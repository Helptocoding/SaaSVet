import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../../components/icons";
import { toast } from "sonner";
import { apiError } from "../../utils/apiError";
import { useAuth } from "../../auth/authContext";
import {
  createMedicalRecord,
  updateMedicalRecord,
  closeMedicalRecord,
  getMedicalRecord,
} from "../../api/medicalRecords";
import { createVitals, getSummary } from "../../api/vitals";
import {
  addMedicalRecordProduct,
  removeMedicalRecordProduct,
  getMedicalRecordProducts,
} from "../../api/inventory";
import { getServices } from "../../api/billing";
import { createPrescription, updatePrescription } from "../../api/prescriptions";
import {
  getMedicalRecordServices,
  addMedicalRecordService,
  removeMedicalRecordService,
} from "../../api/medicalRecords";
import SearchSelect from "../../components/SearchSelect";
import styles from "./stepperV2.module.css";

const CONSULTATION_TYPES = [
  { value: "general", label: "General", desc: "Chequeo, control", icon: <Icon.Paw s={20} /> },
  { value: "vaccine", label: "Vacuna", desc: "Inmunización", icon: <Icon.Syringe s={20} /> },
  { value: "surgery", label: "Cirugía", desc: "Proc. quirúrgico", icon: <Icon.Activity s={20} /> },
  { value: "emergency", label: "Urgencia", desc: "Atención inmediata", icon: <Icon.AlertTriangle s={20} /> },
];

const STEPS = [
  { id: 1, label: "Paciente y diagnóstico" },
  { id: 2, label: "Tratamiento y receta" },
  { id: 3, label: "Insumos y cargos" },
];

const FIELD_TO_STEP = {
  consultation_type: 1,
  diagnosis: 1,
  notes: 1,
  treatment: 2,
  weight: 2,
  products: 3,
  services: 3,
  prescription: 2,
};

const normalizeVitals = (draft) => ({
  weight: toNumberOrNull(draft.weight),
  temperature: toNumberOrNull(draft.temperature),
  heart_rate: toNumberOrNull(draft.heart_rate),
  respiratory_rate: toNumberOrNull(draft.respiratory_rate),
});

const toNumberOrNull = (v) => {
  if (v === "" || v == null) return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
};

export default function ConsultationStepperV2({
  pet,
  products = [],
  productMap = {},
  onClose,
  onComplete,
  initialRecord = null,
}) {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const isEditing = initialRecord && initialRecord.id;

  // Referencia centralizada para IDs (evita desincronización)
  const [recordRef, setRecordRef] = useState({ publicId: null, id: null });

  useEffect(() => {
    if (isEditing && initialRecord) {
      setRecordRef({
        publicId: initialRecord.public_id,
        id: initialRecord.id,
      });
    } else {
      setRecordRef({ publicId: null, id: null });
    }
  }, [initialRecord, isEditing]);

  const [step, setStep] = useState(1);
  const [prescriptionId, setPrescriptionId] = useState(initialRecord?.prescription_id || null);

  // Guardar updated_at inicial para anti-stale check
  const [initialUpdatedAt, setInitialUpdatedAt] = useState(
    isEditing && initialRecord?.updated_at
      ? new Date(initialRecord.updated_at).getTime()
      : null
  );

  const [draft, setDraft] = useState(() => {
    if (isEditing) {
      const v = initialRecord.latest_vitals || {};
      return {
        consultation_type: initialRecord.consultation_type || "general",
        diagnosis: initialRecord.diagnosis || "",
        treatment: initialRecord.treatment || "",
        notes: initialRecord.notes || "",
        weight: v.weight ?? initialRecord.weight ?? "",
        temperature: v.temperature != null ? String(v.temperature) : "",
        heart_rate: v.heart_rate != null ? String(v.heart_rate) : "",
        respiratory_rate: v.respiratory_rate != null ? String(v.respiratory_rate) : "",
      };
    }
    return {
      consultation_type: "general",
      diagnosis: "",
      treatment: "",
      notes: "",
      weight: "",
      temperature: "",
      heart_rate: "",
      respiratory_rate: "",
    };
  });

  // Prescription draft state
  const [prescriptionDraft, setPrescriptionDraft] = useState({
    items: initialRecord?.prescription_summary?.items || [],
    notes: initialRecord?.prescription_summary?.notes || "",
  });
  const [recipeLine, setRecipeLine] = useState({ product: null, dose: "", duration: "", quantity: "1" });

  // Hash para detectar cambios en vitales (evita duplicados)
  const lastVitalsHash = useRef(null);
  // Hash para detectar cambios en receta (evita saves innecesarios)
  const lastPrescriptionHash = useRef(null);

  const [addedProducts, setAddedProducts] = useState([]);
  const [productLine, setProductLine] = useState({ product: null, quantity: "1" });
  const [saving, setSaving] = useState(false);
  // Derivar de initialRecord: abrir una consulta ya cerrada no debe mostrar
  // el botón "Finalizar" ni inputs editables.
  const [closed, setClosed] = useState(() => initialRecord?.status === "closed");
  const [completionInvoicePublicId, setCompletionInvoicePublicId] = useState(null);
  const [forceWeight, setForceWeight] = useState(false);

  // Servicios de consulta
  const [availableServices, setAvailableServices] = useState([]);
  const [addedServices, setAddedServices] = useState([]);
  const [serviceLine, setServiceLine] = useState({ service: null, quantity: "1" });

  // Errores de validación inline
  const [formErrors, setFormErrors] = useState({});

  // Summary state con requestSeq para evitar race conditions
  const [summary, setSummary] = useState(null);
  const requestSeq = useRef(0);

  const refreshSummary = useCallback(async () => {
    if (!recordRef.publicId) return;
    const seq = ++requestSeq.current;
    try {
      const data = await getSummary(recordRef.publicId);
      if (seq === requestSeq.current) {
        setSummary(data);
      }
    } catch {
      // Silencioso - el resumen es informativo
    }
  }, [recordRef.publicId]);

  // Cargar productos y servicios existentes al montar
  useEffect(() => {
    if (recordRef.publicId) {
      const loadProducts = async () => {
        try {
          const data = await getMedicalRecordProducts(recordRef.publicId);
          const normalized = (Array.isArray(data) ? data : (data?.results || [])).map(p => ({
            id: p.id,
            product_name: p.product_name,
            presentation_name: p.presentation_name,
            quantity: p.quantity,
            unit_price: p.unit_price,
          }));
          setAddedProducts(normalized);
        } catch { }
      };
      const loadServices = async () => {
        try {
          const data = await getMedicalRecordServices(recordRef.publicId);
          const normalized = (Array.isArray(data) ? data : (data?.results || [])).map(s => ({
            id: s.id,
            service: s.service,
            name: s.service_name,
            quantity: s.quantity,
            price: s.unit_price,
          }));
          setAddedServices(normalized);
        } catch { }
      };
      loadProducts();
      loadServices();
      refreshSummary();
    }
  }, [recordRef.publicId]);

  // Cargar servicios disponibles al montar
  useEffect(() => {
    const loadServices = async () => {
      try {
        const data = await getServices({ active: "true" });
        setAvailableServices(Array.isArray(data) ? data : (data?.results || []));
      } catch { }
    };
    loadServices();
  }, []);

  // Search logic for SearchSelect
  const handleProductSearch = async (q) => {
    const lower = q.trim().toLowerCase();
    if (!lower) return products.slice(0, 8).map((p) => ({ id: p.id, label: p.name }));
    return products
      .filter(
        (p) =>
          p.name?.toLowerCase().includes(lower) ||
          (p.sku && p.sku.toLowerCase().includes(lower))
      )
      .slice(0, 8)
      .map((p) => ({ id: p.id, label: p.name }));
  };

  // Anti-stale check antes de mutaciones críticas
  const checkNotStale = async () => {
    if (!recordRef.publicId || !initialUpdatedAt) return true;
    try {
      const fresh = await getMedicalRecord(token, recordRef.publicId);
      if (fresh.status !== 'open') {
        toast.error('La consulta ya no está abierta.');
        return false;
      }
      const freshTs = new Date(fresh.updated_at).getTime();
      if (freshTs !== initialUpdatedAt) {
        toast.warning('La consulta fue modificada por otro usuario. Recargando...');
        onClose?.(recordRef.id);
        return false;
      }
      return true;
    } catch {
      return true; // Si falla el check, continuar (degradado)
    }
  };

  const handleSave = async (fromStep) => {
    setSaving(true);
    setFormErrors({}); // Limpiar errores previos
    try {
      // Anti-stale check antes de mutar
      const isOk = await checkNotStale();
      if (!isOk) return;

      let resultId = recordRef.id;
      let resultPublicId = recordRef.publicId;

      // 1. Save Medical Record
      if (!recordRef.publicId) {
        const result = await createMedicalRecord(token, {
          pet: pet.id,
          consultation_type: draft.consultation_type,
          diagnosis: draft.diagnosis,
          treatment: draft.treatment,
          notes: draft.notes,
        });
        resultId = result.id;
        resultPublicId = result.public_id;
        setRecordRef({ publicId: resultPublicId, id: resultId });
      } else {
        await updateMedicalRecord(token, recordRef.publicId, {
          consultation_type: draft.consultation_type,
          diagnosis: draft.diagnosis,
          treatment: draft.treatment,
          notes: draft.notes,
        });
      }

      // 2. Save Vitals solo si cambiaron (hash comparison)
      const vitalFields = ["weight", "temperature", "heart_rate", "respiratory_rate"];
      const vitalsPayload = normalizeVitals(draft);
      const hasVitals = vitalFields.some(f => draft[f] !== "" && draft[f] != null);
      const currentVitalsHash = JSON.stringify(vitalsPayload);

      if (hasVitals && currentVitalsHash !== lastVitalsHash.current) {
        try {
          await createVitals(resultPublicId, {
            ...vitalsPayload,
            force_weight: forceWeight,
          });
          lastVitalsHash.current = currentVitalsHash;
          setForceWeight(false); // Reset después de éxito
        } catch (err) {
          // Detectar force_weight_required por meta
          const requiresForceWeight = err?.response?.data?.meta?.force_weight_required;
          if (requiresForceWeight) {
            setForceWeight(true);
            toast.error('Cambio brusco de peso detectado. Presiona "Siguiente" para confirmar.');
            return; // No avanzar, permitir reintento
          }
          throw err; // Re-lanzar otros errores
        }
      }

      // 3. Handle Prescription solo si cambió (hash comparison)
      const currentPrescriptionHash = JSON.stringify({
        items: prescriptionDraft.items.map(i => `${i.product}-${i.quantity}-${i.dose}`),
        notes: prescriptionDraft.notes,
      });

      if (prescriptionDraft.items.length > 0 && currentPrescriptionHash !== lastPrescriptionHash.current) {
        const pPayload = {
          pet: pet.id,
          medical_record: resultId, // FK usa id entero
          notes: prescriptionDraft.notes,
          items: prescriptionDraft.items.map(it => ({
            product: it.product_id || it.product,
            quantity: it.quantity,
            dose: it.dose,
            duration: it.duration
          }))
        };
        if (prescriptionId) {
          await updatePrescription(prescriptionId, pPayload);
        } else {
          const pResult = await createPrescription(pPayload);
          setPrescriptionId(pResult.id);
        }
        lastPrescriptionHash.current = currentPrescriptionHash;
      }

      // Éxito: limpiar errores y avanzar
      setFormErrors({});
      if (fromStep < 3) {
        setStep(fromStep + 1);
      } else {
        handleFinalize(resultPublicId);
      }
    } catch (err) {
      // Capturar errores de validación por campo
      const fieldErrors = err?.response?.data?.errors || {};

      // Mostrar primer error en toast (solo si es string legible)
      const firstField = Object.keys(fieldErrors)[0];
      const firstMsg = firstField && Array.isArray(fieldErrors[firstField])
        ? fieldErrors[firstField][0]
        : null;

      if (typeof firstMsg === 'string') {
        toast.error(firstMsg);
      } else {
        toast.error(apiError(err, "Error al guardar"));
      }

      // Setear errores inline para el formulario
      setFormErrors(fieldErrors);

      // Navegar al paso con error (solo el primero detectado)
      const targetStep = firstField ? FIELD_TO_STEP[firstField] : null;
      if (targetStep && targetStep !== step) {
        setStep(targetStep);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleFinalize = async (id) => {
    const targetId = id || recordRef.publicId;
    if (!targetId || closed) return;

    // Anti-stale check final
    const isOk = await checkNotStale();
    if (!isOk) return;

    setSaving(true);
    try {
      await closeMedicalRecord(token, targetId);
      setClosed(true);
      toast.success("Consulta finalizada exitosamente");
      onComplete?.(recordRef.id);

      // Buscar factura vinculada
      try {
        const updated = await getMedicalRecord(token, targetId);
        if (updated.invoice_public_id) {
          setCompletionInvoicePublicId(updated.invoice_public_id);
        }
      } catch {
        // Silencioso — la factura se puede buscar después en billing
      }
    } catch (err) {
      setClosed(false);
      toast.error(apiError(err, "Error al finalizar"));
    } finally {
      setSaving(false);
    }
  };

  const handleAddRecipeItem = () => {
    if (!recipeLine.product) return;
    const selected = productMap[recipeLine.product.id];
    if (!selected) return;

    const newItem = {
      product: selected.id,
      product_id: selected.id,
      product_name: selected.name,
      quantity: recipeLine.quantity,
      dose: recipeLine.dose,
      duration: recipeLine.duration,
    };

    setPrescriptionDraft(prev => ({
      ...prev,
      items: [...prev.items, newItem]
    }));
    setRecipeLine({ product: null, dose: "", duration: "", quantity: "1" });
  };

  const handleRemoveRecipeItem = (index) => {
    setPrescriptionDraft(prev => ({
      ...prev,
      items: prev.items.filter((_, i) => i !== index)
    }));
  };

  const handleAddProduct = async () => {
    if (!productLine.product) return;
    const selected = productMap[productLine.product.id];
    if (!selected?.presentation?.id) {
      toast.error("Selecciona un producto con presentación");
      return;
    }
    try {
      const result = await addMedicalRecordProduct(recordRef.publicId, {
        presentation: selected.presentation.id,
        quantity: productLine.quantity,
      });
      setAddedProducts(prev => [...prev, {
        id: result.id,
        product_name: selected.name,
        presentation_name: selected.presentation.name,
        quantity: result.quantity,
        unit_price: result.unit_price,
      }]);
      setProductLine({ product: null, quantity: "1" });
      toast.success("Producto agregado");
      refreshSummary();
    } catch (err) {
      toast.error(apiError(err, "Error al agregar producto"));
    }
  };

  const handleRemoveProduct = async (productEntryId) => {
    const prev = [...addedProducts];
    setAddedProducts(prev.filter(p => p.id !== productEntryId));
    try {
      await removeMedicalRecordProduct(recordRef.publicId, productEntryId);
      toast.success("Producto eliminado");
      refreshSummary();
    } catch (err) {
      setAddedProducts(prev); // Rollback
      toast.error(apiError(err, "No se pudo eliminar el producto"));
    }
  };

  const handleAddService = async () => {
    if (!serviceLine.service) return;
    const selected = availableServices.find(s => s.id === serviceLine.service?.id);
    if (!selected) return;

    // Validar unicidad
    if (addedServices.some(s => s.service === selected.id)) {
      toast.error("Este servicio ya fue agregado");
      return;
    }

    try {
      const result = await addMedicalRecordService(recordRef.publicId, {
        service: selected.id,
        quantity: serviceLine.quantity,
      });
      setAddedServices(prev => [...prev, {
        id: result.id,
        service: selected.id,
        name: selected.name,
        quantity: result.quantity,
        price: selected.base_price,
      }]);
      setServiceLine({ service: null, quantity: "1" });
      toast.success("Servicio agregado");
      refreshSummary();
    } catch (err) {
      toast.error(apiError(err, "Error al agregar servicio"));
    }
  };

  const handleRemoveService = async (serviceEntryId) => {
    const prev = [...addedServices];
    setAddedServices(prev.filter(s => s.id !== serviceEntryId));
    try {
      await removeMedicalRecordService(recordRef.publicId, serviceEntryId);
      toast.success("Servicio eliminado");
      refreshSummary();
    } catch (err) {
      setAddedServices(prev); // Rollback
      toast.error(apiError(err, "No se pudo eliminar el servicio"));
    }
  };

  const handleServiceSearch = async (q) => {
    const lower = q.trim().toLowerCase();
    const filtered = !lower
      ? availableServices
      : availableServices.filter((s) => s.name?.toLowerCase().includes(lower));
    return filtered.slice(0, 8).map((s) => ({ id: s.id, label: s.name }));
  };

  // Totales desde summary (backend) en lugar de hardcodeo
  const totalBilling = useMemo(() => {
    if (summary?.totals) {
      return {
        subtotal: summary.totals.subtotal,
        tax: summary.totals.tax_amount,
        total: summary.totals.total,
        status: summary.totals.status,
      };
    }
    // Fallback a cálculo local si no hay summary
    const prodsTotal = addedProducts.reduce((sum, p) => sum + (Number(p.unit_price) * Number(p.quantity)), 0);
    const servicesTotal = addedServices.reduce((sum, s) => sum + (Number(s.price) * Number(s.quantity)), 0);
    const subtotal = prodsTotal + servicesTotal;
    return { subtotal, tax: 0, total: subtotal, status: 'draft' };
  }, [summary, addedProducts, addedServices]);

  const billingStatusLabel = totalBilling.total > 0
    ? (totalBilling.status === "draft" ? "Borrador" : "Pendiente de cobro")
    : "Sin cargos";

  return (
    <div className={styles.fullPageContainer}>
      <div className={styles.mainWorkArea}>
        <div className={styles.header}>
          <div className={styles.breadcrumbs}>
            <span>Historial Clínico</span> / <span>{isEditing ? "Editar consulta" : "Nueva consulta"}</span>
          </div>
          <div className={styles.titleGroup}>
            <div>
              <h1 className={styles.titleMain}>{isEditing ? "Editar consulta" : "Nueva consulta"}</h1>
              <div className={styles.subtitle}>
                {pet?.name || "—"} · {pet?.species || "—"}
              </div>
            </div>
            <div className={styles.headerActions}>
              <button className="btn btn-secondary btn-sm" onClick={() => onClose()}>
                Cerrar
              </button>
              {!closed && (
                <button className={`${styles.btnFinalizar} btn btn-sm`} onClick={() => handleSave(3)} disabled={saving}>
                  <Icon.Check s={14} /> Finalizar y enviar a Cobros
                </button>
              )}
            </div>
          </div>
        </div>

        <div className={styles.stepperBar}>
          <div className={styles.stepTabs}>
            {STEPS.map((s) => {
              const isActive    = step === s.id;
              const isCompleted = step > s.id;
              return (
                <div
                  key={s.id}
                  className={`${styles.stepTab} ${isActive ? styles.stepTabActive : ""} ${isCompleted ? styles.stepTabDone : ""}`}
                >
                  <div className={styles.stepTabNum}>
                    {isCompleted ? <Icon.Check s={12} /> : s.id}
                  </div>
                  <span className={styles.stepTabLabel}>{s.label}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className={styles.contentArea}>
          {step === 1 && (
            <div className="fade-in">
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Tipo de consulta</h2>
              </div>
              <div className={styles.typeGrid}>
                {CONSULTATION_TYPES.map(t => (
                  <div key={t.value}
                    className={`${styles.typeCard} ${draft.consultation_type === t.value ? styles.typeCardActive : ""}`}
                    onClick={() => setDraft(d => ({ ...d, consultation_type: t.value }))}
                  >
                    <div className={styles.typeIcon}>{t.icon}</div>
                    <div>
                      <div className={styles.typeName}>{t.label}</div>
                      <div className={styles.typeDesc}>{t.desc}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Motivo y diagnóstico</h2>
              </div>

              <div className={styles.formGroup}>
                <label className={styles.inputLabel}>Motivo de consulta</label>
                <textarea
                  className={`${styles.textarea} ${formErrors.notes ? styles.fieldError : ''}`}
                  rows={2}
                  placeholder="Tos seca persistente"
                  value={draft.notes}
                  onChange={e => {
                    setDraft(d => ({ ...d, notes: e.target.value }));
                    if (formErrors.notes) setFormErrors(prev => ({ ...prev, notes: undefined }));
                  }}
                />
                {formErrors.notes && (
                  <div className={styles.fieldErrorMessage}>{formErrors.notes[0]}</div>
                )}
              </div>

              <div className={styles.formGroup}>
                <label className={styles.inputLabel}>Diagnóstico clínico</label>
                <textarea
                  className={`${styles.textarea} ${formErrors.diagnosis ? styles.fieldError : ''}`}
                  rows={3}
                  placeholder="Bronquitis aguda"
                  value={draft.diagnosis}
                  onChange={e => {
                    setDraft(d => ({ ...d, diagnosis: e.target.value }));
                    if (formErrors.diagnosis) setFormErrors(prev => ({ ...prev, diagnosis: undefined }));
                  }}
                />
                {formErrors.diagnosis && (
                  <div className={styles.fieldErrorMessage}>{formErrors.diagnosis[0]}</div>
                )}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="fade-in">
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Tratamiento e Indicaciones</h2>
              </div>
              <div className={styles.formGroup}>
                <label className={styles.inputLabel}>Indicaciones generales (Tratamiento)</label>
                <textarea
                  className={`${styles.textarea} ${formErrors.treatment ? styles.fieldError : ''}`}
                  rows={4}
                  placeholder="Instrucciones detalladas del tratamiento..."
                  value={draft.treatment}
                  onChange={e => {
                    setDraft(d => ({ ...d, treatment: e.target.value }));
                    if (formErrors.treatment) setFormErrors(prev => ({ ...prev, treatment: undefined }));
                  }}
                />
                {formErrors.treatment && (
                  <div className={styles.fieldErrorMessage}>{formErrors.treatment[0]}</div>
                )}
              </div>

              <div className={styles.recipeSection}>
                <div className={styles.sectionHeader}>
                  <h2 className={styles.sectionTitle}>Medicamentos recetados</h2>
                  <span className="badge badge-info" style={{ flexShrink: 0 }}>No se cobra</span>
                </div>
                <p className={styles.helperText}>
                  Estos medicamentos NO se cobran ni descuentan stock. Solo representan la indicación médica. Recepción decidirá posteriormente cuáles desea comprar el cliente.
                </p>

                <div className={styles.recipeForm}>
                  <div className={styles.recipeFormGrid}>
                    <div>
                      <label className={styles.inputLabel}>Medicamento</label>
                      <SearchSelect
                        placeholder="Buscar..."
                        value={recipeLine.product}
                        onChange={item => setRecipeLine(prev => ({ ...prev, product: item }))}
                        onSearch={handleProductSearch}
                      />
                    </div>
                    <div>
                      <label className={styles.inputLabel}>Dosis</label>
                      <input className={`${styles.textarea} ${styles.miniInput}`} placeholder="50mg c/12h" value={recipeLine.dose} onChange={e => setRecipeLine(p => ({ ...p, dose: e.target.value }))} />
                    </div>
                    <div>
                      <label className={styles.inputLabel}>Duración</label>
                      <input className={`${styles.textarea} ${styles.miniInput}`} placeholder="7 días" value={recipeLine.duration} onChange={e => setRecipeLine(p => ({ ...p, duration: e.target.value }))} />
                    </div>
                    <div>
                      <label className={styles.inputLabel}>Cant.</label>
                      <input type="number" className={`${styles.textarea} ${styles.miniInput}`} value={recipeLine.quantity} onChange={e => setRecipeLine(p => ({ ...p, quantity: e.target.value }))} />
                    </div>
                    <button className="btn btn-primary btn-md" style={{ height: '38px' }} onClick={handleAddRecipeItem} disabled={!recipeLine.product}>
                      +
                    </button>
                  </div>
                </div>

                <div className={styles.recipeList}>
                  {prescriptionDraft.items.length === 0 ? (
                    <p className={styles.recipeEmpty}>No hay medicamentos en la receta</p>
                  ) : prescriptionDraft.items.map((item, idx) => (
                    <div key={idx} className={styles.recipeItem}>
                      <Icon.Pill s={16} className={styles.recipeIcon} />
                      <div className={styles.recipeName}>{item.product_name || productMap[item.product_id || item.product]?.name}</div>
                      <span className="badge badge-info" style={{ flexShrink: 0 }}>Recetado</span>
                      <div className={styles.recipeDetails}>{item.dose} · {item.duration} · {item.quantity} unidades</div>
                      <button className={`btn btn-ghost btn-xs ${styles.iconBtnDanger}`} onClick={() => handleRemoveRecipeItem(idx)}>
                        <Icon.Trash s={14} />
                      </button>
                    </div>
                  ))}
                </div>

                <div className={styles.formGroup} style={{ marginTop: '16px' }}>
                  <label className={styles.inputLabel}>Notas adicionales para la receta</label>
                  <textarea
                    className={styles.textarea}
                    rows={2}
                    placeholder="Observaciones de la receta..."
                    value={prescriptionDraft.notes}
                    onChange={e => setPrescriptionDraft(p => ({ ...p, notes: e.target.value }))}
                  />
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="fade-in">
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Insumos y servicios utilizados</h2>
                <span className="badge badge-warning" style={{ flexShrink: 0 }}>Se cobrará</span>
              </div>
              <p className={styles.helperText}>
                Todo lo agregado aquí se cobrará al cliente y descontará inventario. Utiliza esta sección únicamente para productos ya consumidos durante la atención.
              </p>

              <div className={styles.stepThreeLayout}>
                <div>
                  <div className={styles.addRow}>
                    <div className={styles.addRowSearch}>
                      <SearchSelect
                        placeholder="Buscar producto..."
                        value={productLine.product}
                        onChange={item => setProductLine(prev => ({ ...prev, product: item }))}
                        onSearch={handleProductSearch}
                      />
                    </div>
                    <div className={styles.addRowQty}>
                      <input
                        type="number"
                        className={`${styles.textarea} ${styles.miniInput}`}
                        value={productLine.quantity}
                        onChange={e => setProductLine(prev => ({ ...prev, quantity: e.target.value }))}
                        min="1"
                      />
                    </div>
                    <button
                      className="btn btn-primary btn-md"
                      onClick={handleAddProduct}
                      disabled={!productLine.product}
                    >
                      Agregar
                    </button>
                  </div>

                  <div className={styles.tableContainer}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th style={{ textAlign: 'left' }}>Producto</th>
                          <th>Cant.</th>
                          <th>P. Unit</th>
                          <th>Subtotal</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {addedProducts.length === 0 ? (
                          <tr>
                            <td colSpan="5" className={styles.tableEmpty}>
                              No hay insumos registrados en esta consulta.
                            </td>
                          </tr>
                        ) : addedProducts.map(p => (
                          <tr key={p.id}>
                            <td>
                              <div className={styles.cellName}>{p.product_name}</div>
                              <div className={styles.cellSub}>{p.presentation_name}</div>
                            </td>
                            <td style={{ textAlign: 'center' }}>{p.quantity}</td>
                            <td style={{ textAlign: 'center' }}>${Number(p.unit_price).toFixed(2)}</td>
                            <td style={{ textAlign: 'center' }}>${(Number(p.unit_price) * Number(p.quantity)).toFixed(2)}</td>
                            <td style={{ textAlign: 'right' }}>
                              <button
                                className={`btn btn-ghost btn-xs ${styles.iconBtnDanger}`}
                                onClick={() => handleRemoveProduct(p.id)}
                              >
                                <Icon.Trash s={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className={styles.sectionHeader} style={{ marginTop: '36px' }}>
                    <h2 className={styles.sectionTitle}>Servicios profesionales</h2>
                  </div>

                  <div className={styles.addRow}>
                    <div className={styles.addRowSearch}>
                      <SearchSelect
                        placeholder="Buscar servicio..."
                        value={serviceLine.service}
                        onChange={item => setServiceLine(prev => ({ ...prev, service: item }))}
                        onSearch={handleServiceSearch}
                      />
                    </div>
                    <div className={styles.addRowQty}>
                      <input
                        type="number"
                        className={`${styles.textarea} ${styles.miniInput}`}
                        value={serviceLine.quantity}
                        onChange={e => setServiceLine(prev => ({ ...prev, quantity: e.target.value }))}
                        min="1"
                      />
                    </div>
                    <button
                      className="btn btn-primary btn-md"
                      onClick={handleAddService}
                      disabled={!serviceLine.service}
                    >
                      Agregar
                    </button>
                  </div>

                  <div className={styles.tableContainer}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th style={{ textAlign: 'left' }}>Servicio</th>
                          <th>Cant.</th>
                          <th>P. Unit</th>
                          <th>Subtotal</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {addedServices.length === 0 ? (
                          <tr>
                            <td colSpan="5" className={styles.tableEmpty}>
                              No hay servicios registrados en esta consulta.
                            </td>
                          </tr>
                        ) : addedServices.map(s => (
                          <tr key={s.id}>
                            <td>
                              <div className={styles.cellName}>{s.name}</div>
                            </td>
                            <td style={{ textAlign: 'center' }}>{s.quantity}</td>
                            <td style={{ textAlign: 'center' }}>${Number(s.price).toFixed(2)}</td>
                            <td style={{ textAlign: 'center' }}>${(Number(s.price) * Number(s.quantity)).toFixed(2)}</td>
                            <td style={{ textAlign: 'right' }}>
                              <button
                                className={`btn btn-ghost btn-xs ${styles.iconBtnDanger}`}
                                onClick={() => handleRemoveService(s.id)}
                              >
                                <Icon.Trash s={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <aside className={styles.chargePanel}>
                  <div className={styles.chargePanelHeader}>
                    <h3 className={styles.chargePanelTitle}>Resumen de consulta</h3>
                    <span className="badge badge-info">{billingStatusLabel}</span>
                  </div>

                  {prescriptionDraft.items.length > 0 && (
                    <div>
                      <p className={styles.eyebrow} style={{ marginBottom: 6 }}>
                        Medicamentos recetados ({prescriptionDraft.items.length})
                      </p>
                      <div className={styles.chargeLines}>
                        {prescriptionDraft.items.map((item, idx) => (
                          <div key={`rx-sum-${idx}`} className={styles.resumenRow}>
                            <span>{item.product_name || productMap[item.product_id || item.product]?.name}</span>
                            <span className="badge badge-info">Recetado</span>
                          </div>
                        ))}
                      </div>
                      <p className={styles.chargePanelEmpty} style={{ margin: "4px 0 0" }}>
                        No generan cobro
                      </p>
                      <hr className="divider" style={{ margin: "12px 0" }} />
                    </div>
                  )}

                  <p className={styles.eyebrow} style={{ marginBottom: 6 }}>Cargos generados</p>
                  {addedProducts.length === 0 && addedServices.length === 0 ? (
                    <p className={styles.chargePanelEmpty}>Aún no hay cargos agregados</p>
                  ) : (
                    <>
                      <div className={styles.chargeLines}>
                        {addedProducts.map((p) => (
                          <div key={`prod-${p.id}`} className={styles.resumenRow}>
                            <span>{p.product_name} x{p.quantity}</span>
                            <span>${(Number(p.unit_price) * Number(p.quantity)).toFixed(2)}</span>
                          </div>
                        ))}
                        {addedServices.map((s) => (
                          <div key={`srv-${s.id}`} className={styles.resumenRow}>
                            <span>{s.name} x{s.quantity}</span>
                            <span>${(Number(s.price) * Number(s.quantity)).toFixed(2)}</span>
                          </div>
                        ))}
                      </div>

                      <div className={`${styles.resumenCard} ${styles.summaryBox}`}>
                        <div className={styles.resumenRow}>
                          <span>Subtotal</span>
                          <span>${Number(totalBilling.subtotal).toFixed(2)}</span>
                        </div>
                        <div className={styles.resumenRow}>
                          <span>Impuesto</span>
                          <span>${Number(totalBilling.tax).toFixed(2)}</span>
                        </div>
                        <div className={`${styles.resumenRow} ${styles.totalRow}`}>
                          <span>TOTAL</span>
                          <span>${Number(totalBilling.total).toFixed(2)}</span>
                        </div>
                      </div>
                    </>
                  )}

                  <p className={styles.helperText} style={{ marginBottom: 0 }}>
                    Al finalizar, estos cargos se enviarán a Cobros como borrador.
                  </p>
                </aside>
              </div>
            </div>
          )}

          {closed && (
            <div className={`fade-in ${styles.doneWrap}`}>
              <div className={styles.doneIcon}>
                <Icon.Check s={32} />
              </div>
              <h2 className={styles.doneTitle}>
                Consulta finalizada y enviada a Cobros
              </h2>
              {completionInvoicePublicId && summary?.totals ? (
                <>
                  <p className={styles.doneText}>
                    Se generó un borrador de cobro por{" "}
                    <strong>${Number(summary.totals.total).toFixed(2)}</strong>
                  </p>
                  <div className={styles.resumenCard} style={{ maxWidth: "380px", margin: "0 auto 24px", textAlign: "left" }}>
                    {addedProducts.map((p, i) => (
                      <div key={`cp-${i}`} className={styles.resumenRow}>
                        <span>{p.product_name} — {p.quantity}x</span>
                        <span>${(Number(p.unit_price) * Number(p.quantity)).toFixed(2)}</span>
                      </div>
                    ))}
                    {addedServices.map((s, i) => (
                      <div key={`cs-${i}`} className={styles.resumenRow}>
                        <span>{s.name} — {s.quantity}x</span>
                        <span>${(Number(s.price) * Number(s.quantity)).toFixed(2)}</span>
                      </div>
                    ))}
                    <div className={`${styles.resumenRow} ${styles.subtotalHighlight}`}>
                      <span>Total</span>
                      <span>${Number(summary.totals.total).toFixed(2)}</span>
                    </div>
                  </div>
                  <div className={styles.doneActions}>
                    <button
                      className={`${styles.btnFinalizar} btn btn-md`}
                      onClick={() => {
                        onClose?.();
                        navigate(`/billing?invoice=${completionInvoicePublicId}`);
                      }}>
                      <Icon.Download s={14} /> Ir a Cobros
                    </button>
                    <button className="btn btn-secondary btn-md" onClick={() => onClose?.()}>
                      Cerrar
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p className={styles.doneText}>
                    Se ha cerrado la consulta correctamente.
                  </p>
                  <button className="btn btn-secondary btn-md" onClick={() => onClose?.()}>
                    Cerrar
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <div className={styles.footer}>
          {closed ? (
            <div style={{ display: "flex", gap: "12px", width: "100%", justifyContent: "center" }}>
              <button className="btn btn-secondary btn-md" onClick={() => onClose?.()}>
                Cerrar
              </button>
            </div>
          ) : (
            <>
              <button className="btn btn-secondary btn-md" disabled={step === 1} onClick={() => setStep(s => s - 1)}>
                <Icon.ChevronLeft s={16} /> Anterior
              </button>
              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  className="btn btn-primary btn-md"
                  onClick={() => handleSave(step)}
                  disabled={saving}
                >
                  {step === 3 ? 'Finalizar y enviar a Cobros' : 'Siguiente'} <Icon.ChevronRight s={16} />
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <aside className={styles.rightSidebar}>
        <section className={styles.sidebarSection}>
          <div className={styles.patientCard}>
            <div className={styles.patientMainInfo}>
              <div className={styles.avatar}>{(pet?.name?.[0] || 'P').toUpperCase()}</div>
              <div>
                <div className={styles.eyebrow} style={{ marginBottom: '2px' }}>Paciente</div>
                <h4 className={styles.patientName}>{pet?.name || "—"}</h4>
                <div className={styles.patientMeta}>{pet?.species || "—"} · {pet?.breed || "—"}</div>
              </div>
            </div>
            <div className={styles.patientDetailGrid}>
              <div className={styles.detailItem}>
                <div className={styles.detailLabel}>Tutor</div>
                <div className={styles.detailVal}>{pet?.owner?.name || pet?.owner_name || "No asignado"}</div>
              </div>
              <div className={styles.detailItem}>
                <div className={styles.detailLabel}>Teléfono</div>
                <div className={styles.detailVal}>{pet?.owner?.phone || "—"}</div>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.sidebarSection}>
          <div className={styles.eyebrow}>Signos Vitales</div>
          <div className={styles.vitalsGrid}>
            {[
              { f: 'weight', l: 'Peso', u: 'kg', icon: <Icon.ArrowUp s={10} /> },
              { f: 'temperature', l: 'Temp.', u: '°C', icon: <Icon.Paw s={10} /> },
              { f: 'heart_rate', l: 'FC', u: 'bpm', icon: <Icon.Heart s={10} /> },
              { f: 'respiratory_rate', l: 'FR', u: 'rpm', icon: <Icon.Activity s={10} /> },
            ].map(v => (
              <div key={v.f} className={styles.vitalItem}>
                <div className={styles.vitalLabel}>{v.icon} {v.l}</div>
                <div className={styles.vitalWrap}>
                  <input
                    type="number"
                    className={`${styles.vitalValue} ${formErrors[v.f] ? styles.fieldError : ''}`}
                    value={draft[v.f]}
                    disabled={closed}
                    onChange={e => {
                      setDraft(d => ({ ...d, [v.f]: e.target.value }));
                      if (formErrors[v.f]) setFormErrors(prev => ({ ...prev, [v.f]: undefined }));
                    }}
                    placeholder="—"
                  />
                  <span className={styles.vitalUnit}>{v.u}</span>
                </div>
                {formErrors[v.f] && (
                  <div className={styles.fieldErrorMessage} style={{ fontSize: '10px', marginTop: '2px' }}>
                    {formErrors[v.f][0]}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className={styles.sidebarSection} style={{ marginTop: 'auto' }}>
          <div className={styles.eyebrow}>Resumen</div>
          <div className={styles.resumenCard}>
            <div className={styles.resumenRow}>
              <span>Tipo</span>
              <span className="badge badge-success" style={{ textTransform: 'capitalize' }}>{draft.consultation_type}</span>
            </div>
            <div className={styles.resumenRow}>
              <span>Productos</span>
              <span style={{ fontWeight: 600, color: 'var(--c-text)' }}>{addedProducts.length} ítems</span>
            </div>
            <div className={styles.resumenRow}>
              <span>Servicios</span>
              <span style={{ fontWeight: 600, color: 'var(--c-text)' }}>{addedServices.length}</span>
            </div>
            <div className={`${styles.resumenRow} ${styles.subtotalHighlight}`}>
              <span>Subtotal</span>
              <span>${totalBilling.total.toFixed(2)}</span>
            </div>
          </div>
        </section>
      </aside>
    </div>
  );
}
