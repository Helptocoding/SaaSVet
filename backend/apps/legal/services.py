"""
Lógica de aceptación legal (consumida por el gate, las views y /me/).

Requisito por rol (decisión P0):
  - ADMIN (OWNER de la clínica): Términos + Aviso de Privacidad (representa la
    relación comercial → acepta el contrato del servicio y el aviso).
  - VET / ASSISTANT: Aviso de Privacidad (titular de su propia cuenta).
  - ADMIN_SAAS: ninguno (operador de plataforma; además el gate lo saltea por
    is_superuser).

Re-consentimiento: el gate compara contra `LegalDocument.is_current`. Promover
una versión nueva a is_current (decisión humana, solo cambios materiales) deja
desfasada la última aceptación → el gate vuelve a exigir.
"""
from django.utils import timezone

from .models import LegalAcceptance, LegalDocument


REQUIRED_DOC_TYPES_BY_ROLE = {
    'ADMIN': (LegalDocument.DOC_TERMS, LegalDocument.DOC_PRIVACY),
    'VET': (LegalDocument.DOC_PRIVACY,),
    'ASSISTANT': (LegalDocument.DOC_PRIVACY,),
}


def required_doc_types(user):
    """Tipos de documento que el rol del user debe aceptar (tupla, posible vacía)."""
    return REQUIRED_DOC_TYPES_BY_ROLE.get(getattr(user, 'role', None), ())


def current_required_documents(user):
    """`LegalDocument` is_current de los tipos requeridos por el rol del user."""
    types = required_doc_types(user)
    if not types:
        return LegalDocument.objects.none()
    return LegalDocument.objects.filter(is_current=True, doc_type__in=types)


def pending_documents(user):
    """Documentos vigentes requeridos que el user AÚN no aceptó (lista)."""
    required = list(current_required_documents(user))
    if not required:
        return []
    accepted_ids = set(
        LegalAcceptance.objects
        .filter(user=user, document__in=required)
        .values_list('document_id', flat=True)
    )
    return [d for d in required if d.id not in accepted_ids]


def legal_acceptance_required(user):
    """True si el user tiene ≥1 documento vigente requerido sin aceptar."""
    return len(pending_documents(user)) > 0


def record_acceptances(*, user, documents, ip='', user_agent=''):
    """
    Registra la aceptación de `documents` por `user`. Idempotente: la unique
    constraint (user, document) + get_or_create evitan duplicados (reintentos).
    `accepted_at`, ip y user_agent son server-side. Devuelve las filas creadas.
    """
    now = timezone.now()
    created = []
    for doc in documents:
        _, was_created = LegalAcceptance.objects.get_or_create(
            user=user,
            document=doc,
            defaults={
                'accepted_at': now,
                'ip': ip or None,
                'user_agent': (user_agent or '')[:400],
                'organization_id': user.organization_id,
            },
        )
        if was_created:
            created.append(doc)
    return created
