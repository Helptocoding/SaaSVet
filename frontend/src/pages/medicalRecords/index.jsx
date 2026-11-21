import { useEffect, useState, useMemo } from "react";
import { useSearchParams, useLocation } from "react-router-dom";
import { apiError } from "../../utils/apiError";
import { useConfirm } from "../../components/useConfirm";
import api from "../../api/client";
import {
  getMedicalRecords, getMedicalRecord,
  deleteMedicalRecord, closeMedicalRecord,
  downloadMedicalRecordPDF,
} from "../../api/medicalRecords";
import { createPrescription, downloadPrescriptionPDF } from "../../api/prescriptions";
import { extractFilename, triggerDownload } from "../../utils/downloadBlob";
import { getPet } from "../../api/pets";
import { getProducts } from "../../api/inventory";
import { updateAppointmentStatus } from "../../api/appointments";
import { useAuth } from "../../auth/authContext";
import { Icon } from "../../components/icons";
import { toast } from "sonner";
import PrescriptionForm from "../../components/prescriptions/PrescriptionForm";
import PetSidebar from "./PetSidebar";
import PatientHeader from "./PatientHeader";
import Timeline from "./Timeline";
import ConsultationForm from "./ConsultationForm";
import Pagination from "../../components/Pagination";
import SegmentedControl from "../../components/SegmentedControl";
import styles from "./medicalRecords.module.css";
import Layout from "../../components/Layout";
import Skeleton from "react-loading-skeleton";

// Área principal mientras llega el catálogo de productos: encabezado del paciente,
// filtros y tarjetas del historial. La barra de mascotas carga por su cuenta.
const RecordsMainSkeleton = () => (
  <main className={styles.mainContent} role="status" aria-label="Cargando historial clínico">
    <div className={styles.patientHeader} aria-hidden="true">
      <div className={styles.skelPatient}>
        <Skeleton circle width={56} height={56} />
        <div>
          <Skeleton width={180} height={22} />
          <Skeleton width={240} height={12} />
        </div>
      </div>
    </div>
    <div className={styles.filtersBar} aria-hidden="true">
      <Skeleton width={320} height={32} borderRadius="var(--r-lg)" />
      <Skeleton width={220} height={32} borderRadius="var(--r-lg)" />
    </div>
    <div className={styles.skelTimeline} aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} height={88} borderRadius="var(--r-lg)" />
      ))}
    </div>
  </main>
);

const TYPE_FILTERS = [
  { id: "all",      label: "Todos" },
  { id: "general",  label: "General" },
  { id: "vaccine",   label: "Vacuna" },
  { id: "surgery",  label: "Cirugía" },
  { id: "emergency", label: "Emergencia" },
];

const TYPE_FILTER_MAP = {
  general:  "general",
  vaccine:  "vaccine",
  surgery:  "surgery",
  emergency: "emergency",
};

const normalizeList = (data) => (Array.isArray(data) ? data : (data?.results || []));

const MedicalRecords = () => {
  const { token, initializing, user } = useAuth();
  const confirm = useConfirm();
  const [searchParams] = useSearchParams();
  const location = useLocation();

  const [records,          setRecords]          = useState([]);
  const [products,         setProducts]         = useState([]);
  const productMap = useMemo(() => {
    const map = {};
    products.forEach(p => { map[p.id] = p; });
    return map;
  }, [products]);
  const [loading,          setLoading]          = useState(true);
  const [totalCount,       setTotalCount]       = useState(0);
  const [page,             setPage]             = useState(1);
  const [totalPages,       setTotalPages]       = useState(1);

  const [selectedPet,      setSelectedPet]      = useState("");
  const [selectedPetObj,   setSelectedPetObj]   = useState(null);
  const [typeFilter,       setTypeFilter]       = useState("all");
  const [historySearch,    setHistorySearch]    = useState("");
  const [expandedId,       setExpandedId]       = useState(null);

  const [showStepper,      setShowStepper]      = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [editingRecord,    setEditingRecord]    = useState(null);
  // PK de la cita en el flujo "Atender ahora" — se pasa al stepper para que
  // el MedicalRecord nuevo quede ligado a la cita (null en consultas manuales).
  const [attendAppointmentId, setAttendAppointmentId] = useState(null);
  const [showPrescriptionModal,  setShowPrescriptionModal]  = useState(false);
  const [prescriptionTarget,     setPrescriptionTarget]     = useState(null);
  const [downloadingPrescriptionId, setDownloadingPrescriptionId] = useState(null);
  const [downloadingRecordPdfId,    setDownloadingRecordPdfId]    = useState(null);

  useEffect(() => { if (token) loadAllData(); }, [token]);
  useEffect(() => { if (token) loadRecords(); }, [selectedPet, page, token]);

  useEffect(() => {
    const petParam = searchParams.get("pet");
    const appointmentParam = searchParams.get("appointment");
    const recordParam = searchParams.get("record");
    if (petParam) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- aplica los parámetros de la URL (deep-link) al entrar
      setSelectedPet(petParam);
      // Deep-link: resolvemos el objeto de la mascota por public_id (ya no hay
      // lista completa en memoria de la que sacarlo).
      getPet(petParam).then(setSelectedPetObj).catch(() => {});
      if (appointmentParam) {
        // Flujo "Atender ahora": el stepper crea el MedicalRecord (lazy). Hay
        // que ligarlo a la cita para que, al finalizar, la cita pase a done
        // (complete_appointment_on_record_close). El PK de la cita llega por
        // router state (no por URL: el body FK usa PK entero, ADR p18). Sin
        // esto el MR se crea sin appointment y la cita queda en in_progress.
        setAttendAppointmentId(location.state?.appointmentId ?? null);
        setShowStepper(true);
        // Auto-sanación: si el appointment no está en in_progress, transicionarlo
        if (token) {
          api.get(`appointments/${appointmentParam}/`).then((r) => {
            if (r.data && r.data.status !== "in_progress" && r.data.status !== "done") {
              // INV-A: la cita recién leída viaja como precondición. Sin ella,
              // esta auto-sanación podía revivir una cita que alguien acababa
              // de cancelar en la ventana entre el GET y el PATCH. Si cambió,
              // el dominio devuelve 409 y aquí no se insiste: se sigue con la
              // consulta, que es lo que el usuario vino a hacer.
              updateAppointmentStatus(token, appointmentParam, "in_progress", r.data)
                .then(() => window.dispatchEvent(new Event("dashboard:refresh")))
                .catch(() => {});
            }
          }).catch(() => {});
        }
      }
    }
    if (recordParam && token) {
      getMedicalRecord(token, recordParam).then((r) => {
        if (r?.public_id) {
          setExpandedId(r.public_id);
          // Día 6 B1: pet_public_id viene del serializer del MR
          if (r.pet_public_id) {
            setSelectedPet(String(r.pet_public_id));
            getPet(r.pet_public_id).then(setSelectedPetObj).catch(() => {});
          }
        }
      }).catch(() => {});
    }
  }, [searchParams, token, location.state]);

  async function loadAllData() {
    // El sidebar busca mascotas server-side (ya NO se carga la lista completa, ni
    // todos los medical records para contar — eso no escalaba con clínicas
    // importadas de miles de pacientes). Aquí solo el catálogo de productos para
    // el stepper de consulta.
    try {
      const prodsData = await getProducts({ active: "true" });
      setProducts(normalizeList(prodsData));
    } catch { setProducts([]); }

    setLoading(false);
  }

  async function loadRecords() {
    try {
      const filters = { page };
      if (selectedPet) filters.pet = selectedPet;
      const data = await getMedicalRecords(token, filters);
      const list = data.results || data;
      setRecords(list);
      setTotalPages(data.total_pages || 1);
      setTotalCount(data.count ?? list.length);
    } catch { /* carga best-effort; no bloquea la UI */ }
  }

  const refreshAfterMutation = () => loadRecords();

  const filteredByType = useMemo(() => {
    if (typeFilter === "all") return records;
    return records.filter(r => {
      const mapped = TYPE_FILTER_MAP[r.consultation_type] || r.consultation_type;
      return mapped === typeFilter;
    });
  }, [records, typeFilter]);

  const visibleRecords = useMemo(() => {
    if (!historySearch.trim()) return filteredByType;
    const q = historySearch.toLowerCase();
    return filteredByType.filter(r =>
      (r.diagnosis || "").toLowerCase().includes(q) ||
      (r.treatment || "").toLowerCase().includes(q) ||
      (r.notes || "").toLowerCase().includes(q) ||
      (r.consultation_assessment?.chief_complaint || "").toLowerCase().includes(q) ||
      (r.veterinarian_name || "").toLowerCase().includes(q)
    );
  }, [filteredByType, historySearch]);

  const petInfo = selectedPetObj;

  const handleSelectPet = (pet) => {
    // El sidebar entrega el objeto completo de la mascota (de su búsqueda
    // server-side) → lo guardamos para el header/consulta sin un GET extra.
    setSelectedPet(String(pet.public_id));
    setSelectedPetObj(pet);
    setPage(1);
    setExpandedId(null);
  };

  const handleCloseRecord = async (record) => {
    const ok = await confirm({
      title: "Finalizar consulta",
      message: "La consulta quedará cerrada y no podrás modificar productos o servicios.",
      confirmText: "Finalizar",
      dangerMode: false,
    });
    if (!ok) return;

    try {
      const p = closeMedicalRecord(token, record.public_id).then(() => refreshAfterMutation());
      await toast.promise(p, {
        loading: 'Finalizando...',
        success: 'Consulta finalizada',
        error: (err) => apiError(err, "No se pudo finalizar la consulta")
      });
    } catch { /* el error ya lo muestra toast.promise */ }
  };

  const handleDelete = async (publicId) => {
    const ok = await confirm({
      title: "Eliminar consulta",
      message: "Se eliminará el registro clínico de esta consulta. Esta acción no se puede deshacer.",
      confirmText: "Eliminar",
      dangerMode: true,
    });
    if (!ok) return;
    try {
      const p = deleteMedicalRecord(token, publicId).then(() => loadRecords());
      await toast.promise(p, { loading: 'Eliminando...', success: 'Consulta eliminada', error: 'Error al eliminar' });
    } catch { /* el error ya lo muestra toast.promise */ }
  };

  const handleDownloadPrescription = async (prescriptionPublicId) => {
    setDownloadingPrescriptionId(prescriptionPublicId);
    try {
      const { blob, contentDisposition } = await downloadPrescriptionPDF(prescriptionPublicId);
      const filename = extractFilename(contentDisposition, "receta.pdf");
      triggerDownload(blob, filename);
    } catch (err) {
      toast.error(apiError(err, "No se pudo descargar la receta"));
    } finally {
      setDownloadingPrescriptionId(null);
    }
  };

  const handleDownloadRecordPdf = async (recordPublicId) => {
    setDownloadingRecordPdfId(recordPublicId);
    try {
      const { blob, contentDisposition } = await downloadMedicalRecordPDF(recordPublicId);
      const filename = extractFilename(contentDisposition, "consulta.pdf");
      triggerDownload(blob, filename);
    } catch (err) {
      toast.error(apiError(err, "No se pudo descargar el PDF de la consulta"));
    } finally {
      setDownloadingRecordPdfId(null);
    }
  };

  const openPrescriptionModal = (record) => {
    if (!record || record.prescription_id) return;
    if (record.status === "closed") {
      toast.error("No puedes crear una receta en una consulta cerrada");
      return;
    }
    setPrescriptionTarget(record);
    setShowPrescriptionModal(true);
  };

  const closePrescriptionModal = () => {
    setShowPrescriptionModal(false);
    setPrescriptionTarget(null);
  };

  const handlePrescriptionSubmit = async (payload) => {
    try {
      const p = createPrescription(payload).then(async () => {
        await loadRecords();
        closePrescriptionModal();
      });
      await toast.promise(p, { loading: 'Creando receta...', success: 'Receta creada', error: 'Error al crear receta' });
    } catch { /* el error ya lo muestra toast.promise */ }
  };

  const handleStepperComplete = async () => {
    setShowStepper(false);
    setEditingRecord(null);
    setAttendAppointmentId(null);
    await loadRecords();
    await loadAllData();
  };

  const handleStepperClose = async () => {
    setShowStepper(false);
    setEditingRecord(null);
    setAttendAppointmentId(null);
    await loadRecords();
    await loadAllData();
  };

  const handleOpenStepper = () => {
    if (!selectedPet) {
      toast.error("Selecciona una mascota primero");
      return;
    }
    setEditingRecord(null);
    setAttendAppointmentId(null);   // consulta manual: sin cita ligada
    setShowStepper(true);
    setSidebarCollapsed(true);
  };

  const canCreate = user?.role !== "ASSISTANT";

  // Modo consulta: el stepper se renderiza DENTRO de <Layout> (se conserva el navbar
  // de la app y su header). Se oculta solo el PetSidebar (barra secundaria) durante la
  // consulta para dar ancho a la captura clínica.
  const inConsult = showStepper && selectedPet;

  return (
      <Layout>
      <div className={`${styles.pageLayout} ${inConsult ? styles.pageLayoutConsult : ""}`}>
        {!inConsult && (
          <PetSidebar
            selectedPet={selectedPet}
            selectedPetObj={selectedPetObj}
            onSelectPet={handleSelectPet}
            collapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed(c => !c)}
          />
        )}

        {(initializing || loading) ? (
          // La consulta necesita el catálogo de productos: hasta tenerlo no se monta.
          <RecordsMainSkeleton />
        ) : inConsult ? (
          <ConsultationForm
            pet={petInfo}
            products={products}
            productMap={productMap}
            onClose={handleStepperClose}
            onComplete={handleStepperComplete}
            initialRecord={editingRecord}
            appointmentId={attendAppointmentId}
          />
        ) : (
            <main className={`${styles.mainContent} ${inConsult ? styles.mainContentConsult : ""}`}>
              {!selectedPet ? (
                <div className={styles.emptyCenter}>
                  <div className={styles.emptyIconWrap}>
                    <Icon.Paw size={40} />
                  </div>
                  <p className={styles.emptyTitle}>Selecciona una mascota</p>
                  <p className={styles.emptySub}>
                    Elige una mascota del panel izquierdo para ver su historial clínico completo.
                  </p>
                </div>
              ) : (
                <>
                  <div className={styles.patientHeader}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <PatientHeader
                        pet={petInfo}
                        latestVitals={records[0]?.latest_vitals || null}
                        noPadding={true}
                      />
                      {canCreate && (
                        <button className="btn btn-primary btn-md" style={{ background: '#1a4434' }} onClick={handleOpenStepper}>
                          + Nueva Consulta
                        </button>
                      )}
                    </div>
                  </div>

                  <div className={styles.filtersBar}>
                    <SegmentedControl
                      options={TYPE_FILTERS}
                      value={typeFilter}
                      onChange={setTypeFilter}
                      ariaLabel="Filtrar historial por tipo de consulta"
                    />
                    <div className={styles.historySearchWrap}>
                      <span className={styles.historySearchIcon}><Icon.Search /></span>
                      <input
                        type="search"
                        className={styles.historySearchInput}
                        placeholder="Buscar en esta página…"
                        value={historySearch}
                        onChange={e => setHistorySearch(e.target.value)}
                      />
                    </div>
                  </div>

                  <div className={styles.timeline}>
                    {visibleRecords.length === 0 ? (
                      <div className={styles.emptyCenter} style={{ minHeight: "240px" }}>
                        <div className={styles.emptyIconWrap}>
                          <Icon.Paw size={32} />
                        </div>
                        <p className={styles.emptyTitle} style={{ fontSize: "15px" }}>
                          {historySearch || typeFilter !== "all"
                            ? "No hay consultas con ese filtro"
                            : "Esta mascota no tiene historial clínico aún"}
                        </p>
                      </div>
                    ) : (
                      <Timeline
                        records={visibleRecords}
                        expandedId={expandedId}
                        onToggleExpand={setExpandedId}
                        onCloseRecord={handleCloseRecord}
                        onEdit={(record) => {
                          setEditingRecord(record);
                          setAttendAppointmentId(null);
                          setShowStepper(true);
                        }}
                        onDelete={handleDelete}
                        onCreatePrescription={openPrescriptionModal}
                        onDownloadPrescription={handleDownloadPrescription}
                        onDownloadRecordPdf={handleDownloadRecordPdf}
                        downloadingPrescriptionId={downloadingPrescriptionId}
                        downloadingRecordPdfId={downloadingRecordPdfId}
                        user={user}
                        canCreate={canCreate}
                      />
                    )}

                    <Pagination
                      page={page}
                      count={totalCount}
                      totalPages={totalPages}
                      onPage={setPage}
                    />
                  </div>
                </>
              )}
            </main>
        )}
      </div>

      {showPrescriptionModal && prescriptionTarget && (
        <PrescriptionForm
          title="Nueva Receta"
          initialValue={{ pet: prescriptionTarget.pet, medical_record: prescriptionTarget.id, notes: "", items: [] }}
          pets={selectedPetObj ? [selectedPetObj] : []}
          products={products}
          medicalRecordsForPet={[prescriptionTarget]}
          lockedPet={true}
          lockedMedicalRecord={true}
          submitLabel="Crear Receta"
          onSubmit={handlePrescriptionSubmit}
          onCancel={closePrescriptionModal}
        />
      )}
    </Layout>
  );
};

export default MedicalRecords;
