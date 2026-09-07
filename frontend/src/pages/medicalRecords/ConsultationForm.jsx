import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useBlocker } from "react-router-dom";
import { toast } from "sonner";
import { Icon } from "../../components/icons";
import { apiError } from "../../utils/apiError";
import { useAuth } from "../../auth/authContext";
import { useConfirm } from "../../components/useConfirm";
import {
  createMedicalRecord,
  updateMedicalRecord,
  closeMedicalRecord,
  getMedicalRecord,
  getMedicalRecordServices,
  addMedicalRecordService,
  removeMedicalRecordService,
} from "../../api/medicalRecords";
import { createVitals, getSummary } from "../../api/vitals";
import { getVaccines } from "../../api/vaccines";
import { protocolFor } from "../../features/consultation/protocols/registry";
import {
  addMedicalRecordProduct,
  removeMedicalRecordProduct,
  getMedicalRecordProducts,
  getProductLots,
} from "../../api/inventory";
import { getServices } from "../../api/billing";
import { createPrescription, updatePrescription } from "../../api/prescriptions";
import ConsultationRail, { SaveIndicator } from "./ConsultationRail";
import EvaluationSection from "./EvaluationSection";
import TreatmentSection from "./TreatmentSection";
import ChargesSection from "./ChargesSection";
import styles from "./consultationForm.module.css";

const CONSULTATION_TYPES = [
  { value: "general", label: "General", desc: "Chequeo, control", icon: <Icon.Stethoscope s={20} /> },
  { value: "vaccine", label: "Vacuna", desc: "Inmunización", icon: <Icon.Syringe s={20} /> },
  { value: "surgery", label: "Cirugía", desc: "Proc. quirúrgico", icon: <Icon.Activity s={20} /> },
  { value: "emergency", label: "Urgencia", desc: "Atención inmediata", icon: <Icon.AlertTriangle s={20} /> },
];

// Campos de vitales — fuente única para chips del banner y modal de edición.
const VITAL_FIELDS = [
  { f: "weight", l: "Peso", u: "kg", icon: <Icon.ArrowUp s={10} /> },
  { f: "temperature", l: "Temp.", u: "°C", icon: <Icon.Activity s={10} /> },
  { f: "heart_rate", l: "FC", u: "lpm", icon: <Icon.Heart s={10} /> },
  { f: "respiratory_rate", l: "FR", u: "rpm", icon: <Icon.Activity s={10} /> },
];

// Mapea cada campo validable a la sección donde vive, para hacer scroll al
// error cuando la validación de cierre falla.
const FIELD_SECTION = {
  consultation_type: "eval",
  diagnosis: "eval",
  notes: "eval",
  treatment: "treat",
};

const toNumberOrNull = (v) => {
  if (v === "" || v == null) return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
};

const normalizeVitals = (d) => ({
  weight: toNumberOrNull(d.weight),
  temperature: toNumberOrNull(d.temperature),
  heart_rate: toNumberOrNull(d.heart_rate),
  respiratory_rate: toNumberOrNull(d.respiratory_rate),
});

// Espeja la validación autoritativa del backend en close_medical_record:
// diagnóstico siempre obligatorio; tratamiento obligatorio salvo en vacunas.
// NO se aplica al guardar borrador (un borrador puede estar incompleto).
const validateForClose = (d) => {
  const errors = {};
  // Diagnóstico obligatorio salvo Urgencia (presuntivo permitido). Delegación al
  // protocolo (diseño A3, espeja el backend).
  if (d.consultation_type !== "emergency" && !(d.diagnosis || "").trim()) {
    errors.diagnosis = ["El diagnóstico es obligatorio."];
  }
  // Tratamiento del MedicalRecord no obligatorio para protocolos que capturan su
  // plan en su propio registro: Vacuna, Cirugía (postop) y Urgencia (estabilización).
  const treatmentExempt =
    d.consultation_type === "vaccine" ||
    d.consultation_type === "surgery" ||
    d.consultation_type === "emergency";
  if (!treatmentExempt && !(d.treatment || "").trim()) {
    errors.treatment = ["El tratamiento es obligatorio."];
  }
  return errors;
};

let recipeKeySeq = 0;
const nextRecipeKey = () => `rx-${Date.now()}-${recipeKeySeq++}`;

export default function ConsultationForm({
  pet,
  products = [],
  productMap = {},
  onClose,
  onComplete,
  initialRecord = null,
  appointmentId = null,
}) {
  const { token } = useAuth();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const isEditing = Boolean(initialRecord && initialRecord.id);

  // initialRecord es estable durante la vida del componente: index.jsx remonta
  // ConsultationForm al abrir/cerrar consulta. Por eso lazy-init (sin effect de
  // sincronización → evita set-state-in-effect).
  const [recordRef, setRecordRef] = useState(() =>
    isEditing && initialRecord
      ? { publicId: initialRecord.public_id, id: initialRecord.id }
      : { publicId: null, id: null }
  );
  const [prescriptionId, setPrescriptionId] = useState(initialRecord?.prescription_id || null);
  const [initialUpdatedAt] = useState(
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

  const [prescriptionDraft, setPrescriptionDraft] = useState({
    items: (initialRecord?.prescription_summary?.items || []).map((it) => ({
      ...it,
      _localKey: nextRecipeKey(),
    })),
    notes: initialRecord?.prescription_summary?.notes || "",
  });
  const [recipeLine, setRecipeLine] = useState({ product: null, dose: "", duration: "", quantity: "1" });

  const [addedProducts, setAddedProducts] = useState([]);
  const [productLine, setProductLine] = useState({
    product: null,
    presentation: null,
    quantity: "1",
    cost_behavior: "charge",
    lot: null,
  });
  // Lotes elegibles del producto seleccionado (solo si tracks_lots) — B2a.
  const [productLots, setProductLots] = useState([]);

  const [availableServices, setAvailableServices] = useState([]);
  const [addedServices, setAddedServices] = useState([]);
  const [serviceLine, setServiceLine] = useState({ service: null, quantity: "1" });

  const [formErrors, setFormErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [saveState, setSaveState] = useState("idle"); // idle | saving | saved | error
  const [closed, setClosed] = useState(() => initialRecord?.status === "closed");
  const [completionInvoicePublicId, setCompletionInvoicePublicId] = useState(null);
  const [forceWeight, setForceWeight] = useState(false);
  const [dirtyFlag, setDirtyFlag] = useState(false);
  const [activeSection, setActiveSection] = useState("sec-eval");

  // Borrador de protocolos clínicos (scratchpad de UI). Se persiste como
  // MedicalRecord.consultation_draft por el mismo autosave; NO se limpia al
  // cambiar consultation_type (capturar vacuna → ir a General → volver a Vacuna
  // conserva lo capturado). Los VaccineRecord se materializan en el backend al
  // finalizar (apply_consultation_draft_on_close), no aquí.
  const [protocolDraft, setProtocolDraft] = useState(
    () => initialRecord?.consultation_draft || {}
  );
  const [vaccineHistory, setVaccineHistory] = useState([]);

  // Refs: anti-duplicado de saves, serialización de autosave, race del summary.
  const lastVitalsHash = useRef(null);
  const lastPrescriptionHash = useRef(null);
  const saveLockRef = useRef(false);
  const pendingSaveRef = useRef(false);
  const requestSeq = useRef(0);
  const [summary, setSummary] = useState(null);
  const [lastSavedAt, setLastSavedAt] = useState(null);

  const scrollRef = useRef(null);

  const updateDraft = useCallback((patch) => {
    setDraft((prev) => ({ ...prev, ...patch }));
    setDirtyFlag(true);
  }, []);

  const clearError = useCallback((field) => {
    setFormErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
  }, []);

  const fmtMXN = useMemo(() => {
    const f = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
    return (v) => f.format(Number(v) || 0);
  }, []);

  const fmtDate = useMemo(
    () => (ds) =>
      ds
        ? new Date(`${ds}T00:00:00`).toLocaleDateString("es-MX", {
            day: "numeric", month: "short", year: "numeric",
          })
        : "",
    []
  );

  // Protocolo clínico activo según el tipo de consulta (null si no aplica, p.ej.
  // general). El slice se siembra vía initDraft solo para render; se persiste al
  // primer edit del usuario.
  const proto = protocolFor(draft.consultation_type);
  const protoSlice = proto
    ? protocolDraft[draft.consultation_type] ?? proto.initDraft(initialRecord)
    : null;

  const updateProtocol = useCallback(
    (patch) => {
      if (!proto) return;
      const type = draft.consultation_type;
      setProtocolDraft((prev) => {
        const current = prev[type] ?? proto.initDraft(initialRecord);
        return { ...prev, [type]: { ...current, ...patch } };
      });
      setDirtyFlag(true);
    },
    [proto, draft.consultation_type, initialRecord]
  );

  // Historial de vacunas de la mascota (ayuda contextual no bloqueante).
  useEffect(() => {
    if (!pet?.public_id) return;
    let active = true;
    (async () => {
      try {
        const data = await getVaccines({ pet: pet.public_id });
        const list = Array.isArray(data) ? data : data?.results || [];
        if (active) setVaccineHistory(list);
      } catch {
        /* informativo: silencioso */
      }
    })();
    return () => {
      active = false;
    };
  }, [pet?.public_id]);

  // Totales en vivo desde el estado local (instantáneo). El backend sigue siendo
  // la fuente autoritativa de la factura; aquí solo damos feedback inmediato.
  const productsTotal = useMemo(
    () =>
      addedProducts
        .filter((p) => p.cost_behavior !== "included")
        .reduce((a, p) => a + Number(p.unit_price || 0) * Number(p.quantity || 0), 0),
    [addedProducts]
  );
  const servicesTotal = useMemo(
    () => addedServices.reduce((a, s) => a + Number(s.price || 0) * Number(s.quantity || 0), 0),
    [addedServices]
  );
  const grandTotal = productsTotal + servicesTotal;

  const refreshSummary = useCallback(async () => {
    if (!recordRef.publicId) return;
    const seq = ++requestSeq.current;
    try {
      const data = await getSummary(recordRef.publicId);
      if (seq === requestSeq.current) setSummary(data);
    } catch {
      // El resumen es informativo; silencioso.
    }
  }, [recordRef.publicId]);

  // Cargar líneas existentes + summary al tener publicId.
  useEffect(() => {
    if (!recordRef.publicId) return;
    (async () => {
      try {
        const data = await getMedicalRecordProducts(recordRef.publicId);
        const list = Array.isArray(data) ? data : data?.results || [];
        setAddedProducts(
          list.map((p) => ({
            id: p.id,
            product_name: p.product_name,
            presentation_name: p.presentation_name,
            quantity: p.quantity,
            unit_price: p.unit_price,
            cost_behavior: p.cost_behavior || "charge",
          }))
        );
      } catch {
        /* noop */
      }
      try {
        const data = await getMedicalRecordServices(recordRef.publicId);
        const list = Array.isArray(data) ? data : data?.results || [];
        setAddedServices(
          list.map((s) => ({
            id: s.id,
            service: s.service,
            name: s.service_name,
            quantity: s.quantity,
            price: s.unit_price,
          }))
        );
      } catch {
        /* noop */
      }
      refreshSummary();
    })();
  }, [recordRef.publicId, refreshSummary]);

  // Catálogo de servicios disponibles (una vez).
  useEffect(() => {
    (async () => {
      try {
        const data = await getServices({ active: "true" });
        setAvailableServices(Array.isArray(data) ? data : data?.results || []);
      } catch {
        /* noop */
      }
    })();
  }, []);

  // Lotes elegibles cuando se selecciona un producto con tracks_lots (B2a).
  // El backend ordena por caducidad (FEFO) → el primer elegible es el default.
  useEffect(() => {
    const prod = productLine.product ? productMap[productLine.product.id] : null;
    if (!prod?.tracks_lots || !prod?.public_id) {
      setProductLots([]);
      return undefined;
    }
    let active = true;
    (async () => {
      try {
        const data = await getProductLots(prod.public_id, { with_stock: "true" });
        const list = (Array.isArray(data) ? data : data?.results || [])
          .filter((l) => l.effective_status === "active");
        if (!active) return;
        setProductLots(list);
        setProductLine((pl) => (pl.lot ? pl : { ...pl, lot: list[0] || null }));
      } catch {
        if (active) setProductLots([]);
      }
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productLine.product, productMap]);

  const handleProductSearch = useCallback(
    async (q) => {
      const lower = q.trim().toLowerCase();
      const base = !lower
        ? products
        : products.filter(
            (p) =>
              p.name?.toLowerCase().includes(lower) ||
              (p.sku && p.sku.toLowerCase().includes(lower))
          );
      return base.slice(0, 8).map((p) => ({ id: p.id, label: p.name }));
    },
    [products]
  );

  const handleServiceSearch = useCallback(
    async (q) => {
      const lower = q.trim().toLowerCase();
      const base = !lower
        ? availableServices
        : availableServices.filter((s) => s.name?.toLowerCase().includes(lower));
      return base.slice(0, 8).map((s) => ({ id: s.id, label: s.name }));
    },
    [availableServices]
  );

  // Anti-stale antes de mutaciones críticas (mismo contrato que la versión previa).
  const checkNotStale = useCallback(async () => {
    if (!recordRef.publicId || !initialUpdatedAt) return true;
    try {
      const fresh = await getMedicalRecord(token, recordRef.publicId);
      if (fresh.status !== "open") {
        toast.error("La consulta ya no está abierta.");
        return false;
      }
      if (new Date(fresh.updated_at).getTime() !== initialUpdatedAt) {
        toast.warning("La consulta fue modificada por otro usuario. Recargando…");
        onClose?.(recordRef.id);
        return false;
      }
      return true;
    } catch {
      return true; // Degradado: si el check falla, continuar.
    }
  }, [recordRef.publicId, recordRef.id, initialUpdatedAt, token, onClose]);

  /**
   * Persiste el borrador: MedicalRecord (create-or-PATCH) + vitales + receta.
   * NUNCA cierra. NO valida diagnóstico/tratamiento (un borrador puede estar
   * incompleto; la validación vive en handleFinalize).
   *
   * Serializado vía saveLockRef para evitar doble-create por autosaves
   * concurrentes. `silent` = autosave (sin toasts); explícito = botón / finalize.
   * Devuelve true si el guardado completó (para los flujos explícitos).
   */
  const persistDraft = useCallback(
    async ({ silent = false } = {}) => {
      if (closed) return true;
      if (saveLockRef.current) {
        pendingSaveRef.current = true; // re-encolar tras el save en curso
        return false;
      }
      saveLockRef.current = true;
      if (!silent) setSaving(true);
      setSaveState("saving");

      let ok = true;
      try {
        let resultId = recordRef.id;
        let resultPublicId = recordRef.publicId;

        // 1) MedicalRecord: crear (lazy) o PATCH parcial.
        const mrPayload = {
          consultation_type: draft.consultation_type,
          diagnosis: draft.diagnosis,
          treatment: draft.treatment,
          notes: draft.notes,
          consultation_draft: protocolDraft,
        };
        if (!resultPublicId) {
          // Liga el MR a la cita cuando viene del flujo "Atender ahora"
          // (appointmentId = PK). Así al finalizar, close_medical_record →
          // complete_appointment_on_record_close pasa la cita a done. En
          // consultas manuales appointmentId es null y se omite el campo.
          const result = await createMedicalRecord(token, {
            pet: pet.id,
            ...(appointmentId ? { appointment: appointmentId } : {}),
            ...mrPayload,
          });
          resultId = result.id;
          resultPublicId = result.public_id;
          setRecordRef({ publicId: resultPublicId, id: resultId });
        } else {
          await updateMedicalRecord(token, resultPublicId, mrPayload);
        }

        // 2) Vitales: solo si cambiaron (hash). El cambio brusco de peso exige
        // confirmación (force_weight). En silencioso se auto-sana al siguiente
        // ciclo (forceWeight queda en true); en explícito se aborta para que el
        // usuario confirme reintentando.
        const vitalsPayload = normalizeVitals(draft);
        const hasVitals = VITAL_FIELDS.some((v) => draft[v.f] !== "" && draft[v.f] != null);
        const vitalsHash = JSON.stringify(vitalsPayload);
        if (hasVitals && vitalsHash !== lastVitalsHash.current) {
          try {
            await createVitals(resultPublicId, { ...vitalsPayload, force_weight: forceWeight });
            lastVitalsHash.current = vitalsHash;
            setForceWeight(false);
          } catch (err) {
            if (err?.response?.data?.meta?.force_weight_required) {
              setForceWeight(true);
              if (!silent) {
                toast.error('Cambio brusco de peso. Pulsa "Guardar borrador" de nuevo para confirmar.');
                ok = false;
              }
              // No fijar el hash: se reintenta en el próximo guardado.
            } else {
              throw err;
            }
          }
        }

        // 3) Receta: incluye un medicamento tipeado pero no agregado con "+",
        // para no perderlo. Solo persiste si cambió (hash).
        let rxItems = prescriptionDraft.items;
        if (recipeLine.product) {
          const selectedRx = productMap[recipeLine.product.id];
          if (selectedRx) {
            if (!recipeLine.dose?.trim()) {
              if (!silent) {
                toast.error("Indica la dosis del medicamento antes de guardar.");
                ok = false;
              }
            } else {
              rxItems = [
                ...prescriptionDraft.items,
                {
                  _localKey: nextRecipeKey(),
                  product: selectedRx.id,
                  product_id: selectedRx.id,
                  product_name: selectedRx.name,
                  quantity: recipeLine.quantity,
                  dose: recipeLine.dose,
                  duration: recipeLine.duration,
                },
              ];
              setPrescriptionDraft((prev) => ({ ...prev, items: rxItems }));
              setRecipeLine({ product: null, dose: "", duration: "", quantity: "1" });
            }
          }
        }

        const rxHash = JSON.stringify({
          items: rxItems.map((i) => `${i.product_id || i.product}-${i.quantity}-${i.dose}`),
          notes: prescriptionDraft.notes,
        });
        if (rxItems.length > 0 && rxHash !== lastPrescriptionHash.current) {
          const pPayload = {
            pet: pet.id,
            medical_record: resultId, // FK = PK entero (no public_id)
            notes: prescriptionDraft.notes,
            items: rxItems.map((it) => ({
              product: it.product_id || it.product,
              quantity: it.quantity,
              dose: it.dose,
              duration: it.duration,
            })),
          };
          if (prescriptionId) {
            await updatePrescription(prescriptionId, pPayload);
          } else {
            const pResult = await createPrescription(pPayload);
            setPrescriptionId(pResult.id);
          }
          lastPrescriptionHash.current = rxHash;
        }

        if (ok) {
          setDirtyFlag(false);
          setSaveState("saved");
          setLastSavedAt(Date.now());
        } else {
          setSaveState("idle");
        }
        return ok;
      } catch (err) {
        setSaveState("error");
        if (!silent) {
          const fieldErrors = err?.response?.data?.errors || {};
          const firstField = Object.keys(fieldErrors)[0];
          const firstMsg =
            firstField && Array.isArray(fieldErrors[firstField]) ? fieldErrors[firstField][0] : null;
          toast.error(typeof firstMsg === "string" ? firstMsg : apiError(err, "Error al guardar"));
          setFormErrors(fieldErrors);
        }
        return false;
      } finally {
        saveLockRef.current = false;
        if (!silent) setSaving(false);
        if (pendingSaveRef.current) {
          pendingSaveRef.current = false;
          // Reintenta el guardado encolado (silencioso) sin bloquear.
          persistDraft({ silent: true });
        }
      }
    },
    [
      closed,
      recordRef.id,
      recordRef.publicId,
      draft,
      forceWeight,
      prescriptionDraft,
      protocolDraft,
      recipeLine,
      productMap,
      prescriptionId,
      token,
      pet,
      appointmentId,
    ]
  );

  // Autosave debounced: persiste el borrador ~1s tras la última edición.
  useEffect(() => {
    if (closed || !dirtyFlag) return;
    const t = setTimeout(() => persistDraft({ silent: true }), 1000);
    return () => clearTimeout(t);
  }, [draft, prescriptionDraft, protocolDraft, dirtyFlag, closed, persistDraft]);

  // Secciones navegables del riel (dependen del protocolo activo).
  const sectionIds = useMemo(() => {
    const ids = ["sec-eval"];
    if (proto) ids.push(`sec-${draft.consultation_type}`);
    ids.push("sec-treat", "sec-charges");
    return ids;
  }, [proto, draft.consultation_type]);

  const chargesBadge =
    grandTotal > 0
      ? fmtMXN(grandTotal)
      : addedProducts.length + addedServices.length || null;

  const navItems = useMemo(() => {
    const items = [{ id: "sec-eval", label: "Evaluación" }];
    if (proto) items.push({ id: `sec-${draft.consultation_type}`, label: proto.label });
    items.push({ id: "sec-treat", label: "Tratamiento" });
    items.push({ id: "sec-charges", label: "Cobros", badge: chargesBadge });
    return items;
  }, [proto, draft.consultation_type, chargesBadge]);

  const scrollToId = useCallback((id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const scrollToField = useCallback(
    (field) => {
      const section = FIELD_SECTION[field];
      scrollToId(section === "treat" ? "sec-treat" : "sec-eval");
    },
    [scrollToId]
  );

  // Scroll-spy: marca la sección activa según lo visible en el scroll container.
  useEffect(() => {
    if (closed) return undefined;
    const root = scrollRef.current;
    if (!root) return undefined;
    const els = sectionIds
      .map((id) => document.getElementById(id))
      .filter(Boolean);
    if (!els.length) return undefined;
    const visible = new Set();
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) visible.add(e.target.id);
          else visible.delete(e.target.id);
        });
        const firstVisible = sectionIds.find((id) => visible.has(id));
        if (firstVisible) setActiveSection(firstVisible);
      },
      { root, rootMargin: "0px 0px -60% 0px", threshold: 0 }
    );
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [sectionIds, closed]);

  // Cierre de la consulta tras un guardado exitoso.
  const closeRecord = useCallback(async () => {
    const targetId = recordRef.publicId;
    if (!targetId || closed) return;
    const isOk = await checkNotStale();
    if (!isOk) return;
    setSaving(true);
    try {
      await closeMedicalRecord(token, targetId);
      setClosed(true);
      toast.success("Consulta finalizada exitosamente");
      onComplete?.(recordRef.id);
      try {
        const updated = await getMedicalRecord(token, targetId);
        if (updated.checkout_public_id) setCompletionInvoicePublicId(updated.checkout_public_id);
      } catch {
        /* la factura se puede ubicar luego en Cobros */
      }
      refreshSummary();
    } catch (err) {
      setClosed(false);
      toast.error(apiError(err, "Error al finalizar"));
    } finally {
      setSaving(false);
    }
  }, [recordRef.publicId, recordRef.id, closed, checkNotStale, token, onComplete, refreshSummary]);

  const handleSaveDraft = useCallback(async () => {
    const okSaved = await persistDraft({ silent: false });
    if (okSaved) toast.success("Borrador guardado");
  }, [persistDraft]);

  const handleFinalize = useCallback(async () => {
    const errors = {
      ...validateForClose(draft),
      ...(proto ? proto.validate(protoSlice) : {}),
    };
    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      const firstField = Object.keys(errors)[0];
      toast.error(errors[firstField][0]);
      scrollToField(firstField);
      return;
    }
    const saved = await persistDraft({ silent: false });
    if (!saved) return;
    await closeRecord();
  }, [draft, proto, protoSlice, persistDraft, closeRecord, scrollToField]);

  // ── Receta (medicamentos) ──
  const handleAddRecipe = useCallback(() => {
    if (!recipeLine.product) return;
    const selected = productMap[recipeLine.product.id];
    if (!selected) return;
    setPrescriptionDraft((prev) => ({
      ...prev,
      items: [
        ...prev.items,
        {
          _localKey: nextRecipeKey(),
          product: selected.id,
          product_id: selected.id,
          product_name: selected.name,
          quantity: recipeLine.quantity,
          dose: recipeLine.dose,
          duration: recipeLine.duration,
        },
      ],
    }));
    setRecipeLine({ product: null, dose: "", duration: "", quantity: "1" });
    setDirtyFlag(true);
  }, [recipeLine, productMap]);

  const handleRemoveRecipe = useCallback((index) => {
    setPrescriptionDraft((prev) => ({
      ...prev,
      items: prev.items.filter((_, i) => i !== index),
    }));
    setDirtyFlag(true);
  }, []);

  const handlePrescriptionNotesChange = useCallback((value) => {
    setPrescriptionDraft((prev) => ({ ...prev, notes: value }));
    setDirtyFlag(true);
  }, []);

  // ── Productos ──
  const handleAddProduct = useCallback(async () => {
    if (!recordRef.publicId) {
      toast.error("Guarda el borrador antes de registrar productos.");
      return;
    }
    if (!productLine.product) return;
    const selected = productMap[productLine.product.id];
    const chosen = productLine.presentation;
    if (!chosen?.id) {
      toast.error("Selecciona una forma de venta");
      return;
    }
    if (selected?.tracks_lots && !productLine.lot?.id) {
      toast.error("Selecciona el lote a consumir.");
      return;
    }
    try {
      const result = await addMedicalRecordProduct(recordRef.publicId, {
        presentation: chosen.id,
        quantity: productLine.quantity,
        cost_behavior: productLine.cost_behavior,
        ...(selected?.tracks_lots && productLine.lot?.id ? { lot: productLine.lot.id } : {}),
      });
      setAddedProducts((prev) => [
        ...prev,
        {
          id: result.id,
          product_name: selected?.name,
          presentation_name: chosen.name,
          quantity: result.quantity,
          unit_price: result.unit_price,
          cost_behavior: result.cost_behavior || productLine.cost_behavior,
          lot_number: result.lot_number,
        },
      ]);
      setProductLine({ product: null, presentation: null, quantity: "1", cost_behavior: "charge", lot: null });
      toast.success("Producto agregado");
      refreshSummary();
    } catch (err) {
      toast.error(apiError(err, "Error al agregar producto"));
    }
  }, [recordRef.publicId, productLine, productMap, refreshSummary]);

  const handleRemoveProduct = useCallback(
    async (entryId) => {
      const prev = addedProducts;
      setAddedProducts(prev.filter((p) => p.id !== entryId));
      try {
        await removeMedicalRecordProduct(recordRef.publicId, entryId);
        toast.success("Producto eliminado");
        refreshSummary();
      } catch (err) {
        setAddedProducts(prev); // rollback
        toast.error(apiError(err, "No se pudo eliminar el producto"));
      }
    },
    [addedProducts, recordRef.publicId, refreshSummary]
  );

  // ── Servicios ──
  const handleAddService = useCallback(async () => {
    if (!recordRef.publicId) {
      toast.error("Guarda el borrador antes de registrar servicios.");
      return;
    }
    if (!serviceLine.service) return;
    const selected = availableServices.find((s) => s.id === serviceLine.service?.id);
    if (!selected) return;
    if (addedServices.some((s) => s.service === selected.id)) {
      toast.error("Este servicio ya fue agregado");
      return;
    }
    try {
      const result = await addMedicalRecordService(recordRef.publicId, {
        service: selected.id,
        quantity: serviceLine.quantity,
      });
      setAddedServices((prev) => [
        ...prev,
        {
          id: result.id,
          service: selected.id,
          name: selected.name,
          quantity: result.quantity,
          price: selected.base_price,
        },
      ]);
      setServiceLine({ service: null, quantity: "1" });
      toast.success("Servicio agregado");
      refreshSummary();
    } catch (err) {
      toast.error(apiError(err, "Error al agregar servicio"));
    }
  }, [recordRef.publicId, serviceLine, availableServices, addedServices, refreshSummary]);

  const handleRemoveService = useCallback(
    async (entryId) => {
      const prev = addedServices;
      setAddedServices(prev.filter((s) => s.id !== entryId));
      try {
        await removeMedicalRecordService(recordRef.publicId, entryId);
        toast.success("Servicio eliminado");
        refreshSummary();
      } catch (err) {
        setAddedServices(prev); // rollback
        toast.error(apiError(err, "No se pudo eliminar el servicio"));
      }
    },
    [addedServices, recordRef.publicId, refreshSummary]
  );

  // Dirty = ediciones persistibles OR cualquier línea en progreso sin agregar.
  const isDirty =
    dirtyFlag || !!recipeLine.product || !!productLine.product || !!serviceLine.service;

  const confirmDiscard = useCallback(
    () =>
      confirm({
        title: "Salir sin guardar",
        message: "Se perderán los datos no guardados de la consulta. ¿Salir?",
        confirmText: "Salir",
        dangerMode: true,
      }),
    [confirm]
  );

  const requestClose = useCallback(async () => {
    if (!closed && isDirty) {
      const ok = await confirmDiscard();
      if (!ok) return;
    }
    onClose?.();
  }, [closed, isDirty, confirmDiscard, onClose]);

  // Bloqueo de navegación in-app mientras haya cambios sin guardar.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty && !closed && currentLocation.pathname !== nextLocation.pathname
  );

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    let active = true;
    (async () => {
      const ok = await confirmDiscard();
      if (!active) return;
      if (ok) blocker.proceed();
      else blocker.reset();
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blocker]);

  // Aviso del navegador al recargar/cerrar pestaña con cambios sin guardar.
  useEffect(() => {
    if (!isDirty || closed) return;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty, closed]);

  const title = closed ? "Consulta" : isEditing ? "Editar consulta" : "Nueva consulta";
  const doneTotal = summary?.totals?.total != null ? Number(summary.totals.total) : grandTotal;

  return (
    <div className={styles.page}>
      {/* ── Barra superior fija ── */}
      <div className={styles.topbar}>
        <div className={styles.topLeft}>
          <button className={styles.backBtn} onClick={requestClose} aria-label="Volver" type="button">
            <Icon.ChevronLeft s={18} />
          </button>
          <div className={styles.topHead}>
            <div className={styles.topTitle}>{pet?.name || title}</div>
            {closed ? (
              <span className={styles.topSync}>
                <span className={styles.topSyncDot} /> Consulta finalizada
              </span>
            ) : (
              <SaveIndicator saveState={saveState} lastSavedAt={lastSavedAt} dot />
            )}
          </div>
        </div>
        {!closed && (
          <div className={styles.topActions}>
            <button className="btn btn-ghost btn-md" onClick={requestClose} disabled={saving} type="button">
              Cancelar
            </button>
            <button className="btn btn-secondary btn-md" onClick={handleSaveDraft} disabled={saving} type="button">
              <Icon.Check s={15} /> Guardar borrador
            </button>
            <button className="btn btn-primary btn-md btn-arrow" onClick={handleFinalize} disabled={saving} type="button">
              Enviar a cobros <span className="btn-trailing-icon" aria-hidden="true"><Icon.ChevronRight s={15} /></span>
            </button>
          </div>
        )}
      </div>

      <div className={styles.scroll} ref={scrollRef}>
        <div className={styles.shell}>
          <div className={styles.grid}>
            <ConsultationRail
              pet={pet}
              draft={draft}
              vitalFields={VITAL_FIELDS}
              formErrors={formErrors}
              closed={closed}
              onVitalsChange={updateDraft}
              onClearError={clearError}
              navItems={navItems}
              activeSection={activeSection}
              onNavigate={scrollToId}
            />

            <div className={styles.content}>
              {closed ? (
                <div className={`fade-in ${styles.doneWrap}`}>
              <div className={styles.doneIcon}>
                <Icon.Check s={32} />
              </div>
              <h2 className={styles.doneTitle}>Consulta finalizada y enviada a Cobros</h2>
              {completionInvoicePublicId ? (
                <>
                  <p className={styles.doneText}>
                    Se generó un borrador de cobro por{" "}
                    <strong className={styles.mono}>{fmtMXN(doneTotal)}</strong>
                  </p>
                  <div className={styles.resumenCard}>
                    {addedProducts.map((p, i) => (
                      <div key={`cp-${i}`} className={styles.resumenRow}>
                        <span>
                          {p.product_name} — {p.quantity}x
                        </span>
                        {p.cost_behavior === "included" ? (
                          <span style={{ color: "var(--c-text-3)", fontSize: 11 }}>insumo</span>
                        ) : (
                          <span className={styles.mono}>
                            {fmtMXN(Number(p.unit_price) * Number(p.quantity))}
                          </span>
                        )}
                      </div>
                    ))}
                    {addedServices.map((s, i) => (
                      <div key={`cs-${i}`} className={styles.resumenRow}>
                        <span>
                          {s.name} — {s.quantity}x
                        </span>
                        <span className={styles.mono}>
                          {fmtMXN(Number(s.price) * Number(s.quantity))}
                        </span>
                      </div>
                    ))}
                    <div className={`${styles.resumenRow} ${styles.subtotalHighlight}`}>
                      <span>Total</span>
                      <span className={styles.mono}>{fmtMXN(doneTotal)}</span>
                    </div>
                  </div>
                  <div className={styles.doneActions}>
                    <button
                      className="btn btn-primary btn-md"
                      onClick={() => {
                        onClose?.();
                        navigate(`/billing?checkout=${completionInvoicePublicId}`);
                      }}
                    >
                      <Icon.Download s={14} /> Ir a Cobros
                    </button>
                    <button className="btn btn-secondary btn-md" onClick={() => onClose?.()}>
                      Cerrar
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p className={styles.doneText}>Se ha cerrado la consulta correctamente.</p>
                  <button className="btn btn-secondary btn-md" onClick={() => onClose?.()}>
                    Cerrar
                  </button>
                </>
              )}
            </div>
              ) : (
                <>
                  <div id="sec-eval" className={styles.anchor}>
                    <EvaluationSection
                      draft={draft}
                      consultationTypes={CONSULTATION_TYPES}
                      formErrors={formErrors}
                      onChange={updateDraft}
                      onClearError={clearError}
                      disabled={closed}
                    />
                  </div>

                  {proto && (
                    <div id={`sec-${draft.consultation_type}`} className={styles.anchor}>
                      <proto.Section
                        value={protoSlice}
                        onChange={updateProtocol}
                        history={vaccineHistory}
                        species={pet?.species}
                        disabled={closed}
                        fmtDate={fmtDate}
                        products={products}
                      />
                    </div>
                  )}

                  <div id="sec-treat" className={styles.anchor}>
                    <TreatmentSection
                      draft={draft}
                      formErrors={formErrors}
                      onChange={updateDraft}
                      onClearError={clearError}
                      disabled={closed}
                      prescriptionItems={prescriptionDraft.items}
                      prescriptionNotes={prescriptionDraft.notes}
                      recipeLine={recipeLine}
                      onRecipeLineChange={(patch) => setRecipeLine((prev) => ({ ...prev, ...patch }))}
                      onAddRecipe={handleAddRecipe}
                      onRemoveRecipe={handleRemoveRecipe}
                      onPrescriptionNotesChange={handlePrescriptionNotesChange}
                      onProductSearch={handleProductSearch}
                      productMap={productMap}
                    />
                  </div>

                  <div id="sec-charges" className={styles.anchor}>
                    <ChargesSection
                      recordReady={!!recordRef.publicId}
                      disabled={closed}
                      productMap={productMap}
                      fmtMXN={fmtMXN}
                      productLine={productLine}
                      productLots={productLots}
                      onProductLineChange={(patch) => setProductLine((prev) => ({ ...prev, ...patch }))}
                      onAddProduct={handleAddProduct}
                      addedProducts={addedProducts}
                      onRemoveProduct={handleRemoveProduct}
                      onProductSearch={handleProductSearch}
                      serviceLine={serviceLine}
                      onServiceLineChange={(patch) => setServiceLine((prev) => ({ ...prev, ...patch }))}
                      onAddService={handleAddService}
                      addedServices={addedServices}
                      onRemoveService={handleRemoveService}
                      onServiceSearch={handleServiceSearch}
                    />
                  </div>

                  {(addedProducts.length > 0 || addedServices.length > 0) && (
                    <div className={styles.resumen}>
                      <div className={styles.resumenBox}>
                        <div className={styles.resumenLine}>
                          <span>Productos</span>
                          <span className={styles.mono}>{fmtMXN(productsTotal)}</span>
                        </div>
                        <div className={styles.resumenLine}>
                          <span>Servicios</span>
                          <span className={styles.mono}>{fmtMXN(servicesTotal)}</span>
                        </div>
                        <div className={styles.resumenTotal}>
                          <b>Total a cobrar</b>
                          <span className={styles.resumenTotalVal}>{fmtMXN(grandTotal)}</span>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
