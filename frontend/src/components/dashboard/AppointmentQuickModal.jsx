import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../../auth/authContext";
import { createMedicalRecord } from "../../api/medicalRecords";
import { updateAppointmentStatus } from "../../api/appointments";
import { useConfirm } from "../useConfirm";
import { Icon } from "../icons";
import StatusBadge from "../StatusBadge";
import Skeleton from "react-loading-skeleton";
import {
  apiError, appointmentChangedCurrent, isAppointmentChanged,
} from "../../utils/apiError";
import { statusLabel } from "../../utils/appointmentStatus";
import api from "../../api/client";

/** INV-A (ADR p57): un `409 appointment_changed` no es «no se pudo».
 *
 * Alguien movió la cita entre que se abrió el modal y se pulsó la acción. Se
 * dice QUÉ pasó —el modal se cierra y el dashboard se refresca solo— y **no se
 * reintenta**: reintentar sin precondición es sobrescribir la decisión ajena.
 */
const conflictOr = (err, fallback) => {
  if (!isAppointmentChanged(err)) return apiError(err, fallback);
  const current = appointmentChangedCurrent(err);
  const label = current?.status ? statusLabel(current.status) : "";
  return label
    ? `Esta cita cambió mientras la mirabas: ahora está "${label}". Vuelve a abrirla para decidir.`
    : "Esta cita cambió mientras la mirabas. Vuelve a abrirla para decidir.";
};

export default function AppointmentQuickModal({ publicId, onClose }) {
  const navigate = useNavigate();
  const { token } = useAuth();
  const confirm = useConfirm();
  const [appt, setAppt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [attending, setAttending] = useState(false);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    api
      .get(`appointments/${publicId}/`)
      .then((r) => setAppt(r.data))
      .catch(() => toast.error("No se pudo cargar la cita"))
      .finally(() => setLoading(false));
  }, [publicId]);

  const handleAttendNow = async () => {
    if (!appt) return;
    setAttending(true);

    if (appt.status === "done" || appt.status === "canceled" || appt.status === "no_show") {
      toast.error("Esta cita ya no está disponible para atender");
      setAttending(false);
      return;
    }

    if (appt.status === "in_progress") {
      const petId = appt.pet_public_id;
      const recId =
        appt.medical_record_public_ids?.length > 0
          ? appt.medical_record_public_ids[0]
          : null;
      onClose();
      const qs = recId
        ? `record=${recId}`
        : `pet=${petId}&appointment=${appt.public_id}`;
      navigate(`/medical-records?${qs}`);
      setAttending(false);
      return;
    }

    try {
      const record = await createMedicalRecord(token, {
        pet: appt.pet,
        appointment: appt.id,
        consultation_type: "general",
      });
      try {
        await updateAppointmentStatus(token, appt.public_id, "in_progress", appt);
        window.dispatchEvent(new Event("dashboard:refresh"));
      } catch {
        toast.info("Hubo un problema menor al abrir la cita, pero puedes continuar normalmente.");
      }
      onClose();
      navigate(
        `/medical-records?pet=${appt.pet_public_id}&appointment=${appt.public_id}&record=${record.public_id}`
      );
    } catch (err) {
      toast.error(apiError(err, "No se pudo iniciar la consulta. ¿Reintentar?"));
    } finally {
      setAttending(false);
    }
  };

  const handleViewDetails = () => {
    onClose();
    navigate(`/appointments?appointment=${publicId}`);
  };

  const handleNoShow = async () => {
    if (!appt) return;
    const ok = await confirm({
      message: `¿Marcar la cita de ${appt.pet_name || "este paciente"} como "No se presentó"?`,
      confirmText: "No asistió",
      dangerMode: true,
    });
    if (!ok) return;
    setUpdating(true);
    try {
      await updateAppointmentStatus(token, appt.public_id, "no_show", appt);
      window.dispatchEvent(new Event("dashboard:refresh"));
      toast.success("Cita marcada como no asistió");
      onClose();
    } catch (err) {
      toast.error(conflictOr(err, "No se pudo actualizar la cita"));
      if (isAppointmentChanged(err)) {
        window.dispatchEvent(new Event("dashboard:refresh"));
        onClose();
      }
    } finally {
      setUpdating(false);
    }
  };

  const handleReschedule = () => {
    onClose();
    navigate(`/appointments?appointment=${publicId}`);
  };

  const handleConfirm = async () => {
    if (!appt) return;
    setUpdating(true);
    try {
      await updateAppointmentStatus(token, appt.public_id, "confirmed", appt);
      window.dispatchEvent(new Event("dashboard:refresh"));
      toast.success("Cita confirmada");
      onClose();
    } catch (err) {
      toast.error(conflictOr(err, "No se pudo confirmar la cita"));
      if (isAppointmentChanged(err)) {
        window.dispatchEvent(new Event("dashboard:refresh"));
        onClose();
      }
    } finally {
      setUpdating(false);
    }
  };

  const handleCancel = async () => {
    if (!appt) return;
    const ok = await confirm({
      message: `¿Cancelar la cita de ${appt.pet_name || "este paciente"}?`,
      confirmText: "Cancelar cita",
      dangerMode: true,
    });
    if (!ok) return;
    setUpdating(true);
    try {
      await updateAppointmentStatus(token, appt.public_id, "canceled", appt);
      window.dispatchEvent(new Event("dashboard:refresh"));
      toast.success("Cita cancelada");
      onClose();
    } catch (err) {
      toast.error(conflictOr(err, "No se pudo cancelar la cita"));
      if (isAppointmentChanged(err)) {
        window.dispatchEvent(new Event("dashboard:refresh"));
        onClose();
      }
    } finally {
      setUpdating(false);
    }
  };

  const handleViewRecord = () => {
    onClose();
    const recId =
      appt.medical_record_public_ids?.length > 0
        ? appt.medical_record_public_ids[0]
        : null;
    navigate(
      recId
        ? `/medical-records?record=${recId}`
        : `/medical-records?pet=${appt.pet_public_id}`
    );
  };

  if (loading) {
    // Misma caja que el detalle: encabezado (mascota + estado), datos y acciones.
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal modal-sm" onClick={(e) => e.stopPropagation()} role="status" aria-label="Cargando cita">
          <div className="modal-header" aria-hidden="true">
            <div>
              <Skeleton width={140} height={16} />
              <Skeleton width={84} height={20} borderRadius="var(--r-full)" />
            </div>
          </div>
          <div className="modal-body" aria-hidden="true">
            <Skeleton count={4} height={13} className="dash-skel-row" />
            <Skeleton count={2} height={36} borderRadius="var(--r-lg)" className="dash-skel-row" />
          </div>
        </div>
      </div>
    );
  }

  if (!appt) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal modal-sm" onClick={(e) => e.stopPropagation()} style={{ padding: "24px" }}>
          <p style={{ color: "var(--c-text-3)", fontSize: "13px", textAlign: "center" }}>Cita no encontrada.</p>
          <button className="btn btn-secondary btn-md" style={{ marginTop: "12px", width: "100%" }} onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    );
  }

  const isActive = appt.status === "scheduled" || appt.status === "confirmed";
  const isInProgress = appt.status === "in_progress";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 style={{ marginBottom: "4px", fontSize: "16px" }}>
              <Icon.Paw s={14} /> {appt.pet_name || "Paciente"}
            </h3>
            <StatusBadge status={appt.status} />
          </div>
          <button className="modal-close" onClick={onClose}>
            <Icon.X s={14} />
          </button>
        </div>

        <div className="modal-body">
          <div
            style={{
              display: "grid",
              gap: "8px",
              marginBottom: isInProgress ? "12px" : "0",
            }}
          >
            {[
              ["Cliente", appt.owner_name || "—"],
              ["Hora", appt.start_time?.slice(0, 5) || "—"],
              ["Motivo", appt.reason || "—"],
              ["Veterinario", appt.veterinarian_name || "—"],
            ].map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  fontSize: "12.5px",
                  padding: "6px 0",
                  borderBottom: "1px solid var(--c-subtle)",
                }}
              >
                <span style={{ color: "var(--c-text-3)", fontWeight: 600 }}>{k}</span>
                <span style={{ color: "var(--c-text)", fontWeight: 500 }}>{v}</span>
              </div>
            ))}
          </div>

          {isInProgress && (
            <div
              style={{
                padding: "10px 12px",
                background: "#fffbeb",
                border: "1px solid #fbbf24",
                borderRadius: "var(--r-md)",
                fontSize: "12.5px",
                color: "#92400e",
                marginBottom: "12px",
                textAlign: "center",
              }}
            >
              Esta consulta ya fue iniciada por {appt.veterinarian_name || "otro veterinario"}.
            </div>
          )}
        </div>

        <div className="modal-footer" style={{ flexDirection: "column", gap: "8px" }}>
          {isInProgress && (
            <button
              className="btn btn-primary btn-lg"
              style={{ width: "100%", fontWeight: 700, fontSize: "14px" }}
              disabled={attending}
              onClick={handleAttendNow}
            >
              Continuar consulta
            </button>
          )}

          {isActive && (
            <>
              <button
                className="btn btn-primary btn-lg"
                style={{
                  width: "100%",
                  background: "#f59e0b",
                  borderColor: "#f59e0b",
                  color: "#fff",
                  fontWeight: 700,
                  fontSize: "14px",
                }}
                disabled={attending}
                onClick={handleAttendNow}
              >
                ▶ Atender ahora
              </button>

              {appt.status === "scheduled" && (
                <button
                  className="btn btn-secondary btn-md"
                  style={{ width: "100%" }}
                  disabled={updating || attending}
                  onClick={handleConfirm}
                >
                  Confirmar cita
                </button>
              )}

              <div style={{ display: "flex", gap: "8px", width: "100%" }}>
                <button
                  className="btn btn-secondary btn-md"
                  style={{ flex: 1 }}
                  disabled={updating || attending}
                  onClick={handleNoShow}
                >
                  No asistió
                </button>
                <button
                  className="btn btn-secondary btn-md"
                  style={{ flex: 1 }}
                  disabled={updating || attending}
                  onClick={handleReschedule}
                >
                  Reprogramar
                </button>
              </div>

              <button
                className="btn btn-ghost btn-md"
                style={{ width: "100%", color: "var(--c-danger-text)" }}
                disabled={updating || attending}
                onClick={handleCancel}
              >
                Cancelar cita
              </button>
            </>
          )}

          {appt.status === "done" && (
            <button
              className="btn btn-primary btn-lg"
              style={{ width: "100%", fontWeight: 700, fontSize: "14px" }}
              onClick={handleViewRecord}
            >
              Ver expediente
            </button>
          )}

          <button
            className="btn btn-ghost btn-md"
            style={{ width: "100%" }}
            onClick={handleViewDetails}
          >
            Ver más detalles
          </button>
        </div>
      </div>
    </div>
  );
}
