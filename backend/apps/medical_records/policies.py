import logging

from apps.core.models import UserRole
from apps.core.permissions import _is_allowed, _get_cached_permissions
from apps.core.permissions_codes import PERMISSIONS


policy_logger = logging.getLogger("medical_records.events")


def _role_names(user) -> set[str]:
    if hasattr(user, "_cached_role_names"):
        return user._cached_role_names

    roles = set(
        UserRole.objects.filter(user=user).values_list("role__name", flat=True)
    )
    user._cached_role_names = roles
    return roles


def _permission_codes(user):
    return _get_cached_permissions(user)


def _has_required_permission(user, required: str) -> bool:
    db_perms = _permission_codes(user)
    if db_perms is not None:
        return _is_allowed(required, list(db_perms))
    return _is_allowed(required, PERMISSIONS.get(user.role, []))


def can_modify_medical_record_charges(user, medical_record) -> bool:
    if not _has_required_permission(user, "medicalrecord.update"):
        return False

    if medical_record.organization_id != user.organization_id:
        return False

    if medical_record.status == medical_record.Status.CLOSED:
        return False

    role_names = _role_names(user)
    if "ADMIN_SAAS" in role_names or "ADMIN" in role_names:
        return True

    if "VET" in role_names and medical_record.veterinarian_id == user.id:
        return True

    return False


def can_close_medical_record(user, medical_record) -> bool:
    if not _has_required_permission(user, "medicalrecord.close"):
        return False

    if medical_record.organization_id != user.organization_id:
        return False

    # Una consulta ya cerrada no se vuelve a finalizar. close_medical_record es
    # idempotente en la view, pero este flag refleja "acción disponible": sin el
    # guard el botón "Finalizar" del Timeline persiste tras cerrar.
    if medical_record.status == medical_record.Status.CLOSED:
        return False

    role_names = _role_names(user)
    if "ADMIN_SAAS" in role_names or "ADMIN" in role_names:
        return True

    if "VET" in role_names and medical_record.veterinarian_id == user.id:
        return True

    return False


def assert_can_modify_medical_record(user, medical_record, request=None) -> None:
    """
    Gate clínico para datos no-facturación (signos vitales, etc.).
    Separado de assert_can_modify_charges que es específico para billing.
    """
    from rest_framework.exceptions import PermissionDenied

    if medical_record.organization_id != user.organization_id:
        if request:
            log_ownership_denied(user=user, medical_record=medical_record, request=request)
        raise PermissionDenied("No puedes modificar consultas fuera de tu organización")

    if medical_record.status == medical_record.Status.CLOSED:
        if request:
            log_closed_denied(user=user, medical_record=medical_record, request=request)
        raise PermissionDenied("La consulta está cerrada")


# Campos que un hijo de una consulta CERRADA sigue admitiendo. Solo la
# anotación: es la vía de anulación que documentan VaccineRecordDetailView
# ("para anular un registro creado por error, usar PATCH") y
# PrescriptionDetailView ("para anular, PATCH notes"). Todo lo demás —el
# paciente, quién lo hizo, la fecha, la consulta a la que pertenece— queda
# congelado al cerrar.
POST_CLOSE_EDITABLE_FIELDS = frozenset({'notes'})


def assert_post_close_edit_allowed(user, medical_record, changed_fields, request=None,
                                   allowed=POST_CLOSE_EDITABLE_FIELDS) -> None:
    """Congela la identidad clínica de un hijo cuando su consulta está cerrada.

    Existe porque la inmutabilidad post-cierre se aplicaba a mano, vista por
    vista, con `assert_can_modify_charges` (cargos) y
    `assert_can_modify_medical_record` (vitales) — y el registro vacunal y la
    receta nunca se conectaron a ninguna de las dos. Quedaban editables, tras
    cerrar el expediente y sin dejar rastro, el paciente al que pertenece una
    vacunación, quién la aplicó y en qué fecha (auditoría run-1, hallazgo
    medical_records/post-close-immutability-missing-on-vaccine-and-prescription-records).

    No bloquea la mutación entera a propósito: hacerlo eliminaría la única vía
    de corrección de un documento que ambas vistas describen como retenido
    legalmente (NOM-007/NOM-046, cinco años). La regla real es más estrecha y
    es la que se impone aquí: después del cierre se puede anotar, no reescribir.

    `medical_record=None` no restringe nada: un registro sin consulta asociada
    no hereda un cierre que no existe.
    """
    from rest_framework.exceptions import PermissionDenied

    if medical_record is None:
        return

    if medical_record.organization_id != user.organization_id:
        if request:
            log_ownership_denied(user=user, medical_record=medical_record, request=request)
        raise PermissionDenied("No puedes modificar consultas fuera de tu organización")

    if medical_record.status != medical_record.Status.CLOSED:
        return

    forbidden = sorted(set(changed_fields) - set(allowed))
    if not forbidden:
        return

    if request:
        log_closed_denied(user=user, medical_record=medical_record, request=request)
    raise PermissionDenied(
        "La consulta está cerrada: solo se puede editar la nota "
        f"({', '.join(sorted(allowed))}). Campos rechazados: {', '.join(forbidden)}."
    )


def assert_can_modify_charges(user, medical_record, request) -> None:
    """
    Lanza PermissionDenied si el usuario no puede modificar cargos del registro.
    Centralizado para usarse en ListCreate y Delete sin herencia común.
    """
    from rest_framework.exceptions import PermissionDenied

    if medical_record.organization_id != user.organization_id:
        log_ownership_denied(user=user, medical_record=medical_record, request=request)
        raise PermissionDenied("No puedes modificar consultas fuera de tu organización")

    if medical_record.status == medical_record.Status.CLOSED:
        log_closed_denied(user=user, medical_record=medical_record, request=request)
        raise PermissionDenied("La consulta está cerrada")

    if not can_modify_medical_record_charges(user, medical_record):
        log_ownership_denied(user=user, medical_record=medical_record, request=request)
        raise PermissionDenied("No puedes modificar esta consulta")


def medical_record_has_clinical_content(record) -> bool:
    """
    Predicate: True si el registro tiene cualquier evidencia clínica u operativa.
    Usado por destroy() y can_delete para garantizar consistencia frontend/backend.
    """
    if (record.diagnosis or "").strip():
        return True
    if (record.treatment or "").strip():
        return True
    if (record.notes or "").strip():
        return True
    if record.consultation_draft:
        return True
    from apps.prescriptions.models import Prescription
    from apps.billing.models import ClinicalChargeEntry, MedicalRecordBillingContext, Checkout
    from apps.inventory.models import StockMovement
    return any([
        record.products_used.exists(),
        record.vaccine_records.exists(),
        record.services_used.exists(),
        record.vital_signs.exists(),
        record.consultation_assessments.exists(),
        record.surgery_records.exists(),
        record.emergency_records.exists(),
        ClinicalChargeEntry.all_objects.filter(medical_record=record).exists(),
        MedicalRecordBillingContext.all_objects.filter(medical_record=record).exists(),
        StockMovement.all_objects.filter(medical_record=record).exists(),
        Checkout.all_objects.filter(medical_record=record).exists(),
        Prescription.objects.filter(medical_record=record).exists(),
    ])


def log_ownership_denied(*, user, medical_record, request) -> None:
    policy_logger.warning(
        "MEDICAL_RECORD_OWNERSHIP_DENIED",
        extra={
            "user_id": user.id,
            "organization_id": user.organization_id,
            "medical_record_id": medical_record.id,
            "veterinarian_id": medical_record.veterinarian_id,
            "endpoint": request.path,
            "method": request.method,
        },
    )


def log_closed_denied(*, user, medical_record, request) -> None:
    policy_logger.warning(
        "MEDICAL_RECORD_CLOSED_DENIED",
        extra={
            "user_id": user.id,
            "organization_id": user.organization_id,
            "medical_record_id": medical_record.id,
            "veterinarian_id": medical_record.veterinarian_id,
            "endpoint": request.path,
            "method": request.method,
        },
    )
