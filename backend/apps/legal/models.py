"""
apps/legal — Documentos legales versionados + aceptación por usuario.

`LegalDocument`: catálogo **global** (NO tenant-scoped) de versiones de los
documentos legales de SaaslyVet (Términos, Aviso de Privacidad, Cookies). El
TEXTO vive en la landing (www.saaslyvet.com); aquí solo se versiona y se apunta
(`landing_url`). Una versión `is_current` por `doc_type`.

Sync manual con la landing (repos independientes, sin dependencia en runtime):
al publicar una versión nueva en la landing, un operador crea/promueve la fila
aquí (ver `management/commands/seed_legal_documents.py`). La **promoción a
`is_current`** es la decisión humana que dispara el re-consentimiento — solo se
hace ante cambios materiales (no por correcciones menores).

`LegalAcceptance` (append-only): registro de que un `User` aceptó una versión
concreta de un documento. Por-usuario, capturando la `organization` para
auditoría/tenant. Re-consentimiento: al promover una versión nueva a
`is_current`, la última aceptación del usuario queda desfasada → el
`LegalAcceptanceGate` vuelve a exigir aceptación de la versión vigente.
"""
from uuid import uuid4

from django.db import models

from apps.core.models import OrganizationalModel


class LegalDocument(models.Model):
    DOC_TERMS = 'terms'
    DOC_PRIVACY = 'privacy'
    DOC_COOKIES = 'cookies'
    DOC_TYPE_CHOICES = (
        (DOC_TERMS, 'Términos y Condiciones'),
        (DOC_PRIVACY, 'Aviso de Privacidad'),
        (DOC_COOKIES, 'Política de Cookies'),
    )

    public_id = models.UUIDField(default=uuid4, editable=False, unique=True, db_index=True)
    doc_type = models.CharField(max_length=16, choices=DOC_TYPE_CHOICES)
    # Espejo de la fecha "Última actualización" del documento en la landing
    # (ej. "2026-06-24"). Cadena libre para no acoplar a un formato.
    version = models.CharField(max_length=32)
    effective_date = models.DateField()
    landing_url = models.URLField()
    # Solo una versión vigente por tipo. Promover a is_current = decisión humana
    # que dispara el re-consentimiento (solo cambios materiales).
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        flag = ' (current)' if self.is_current else ''
        return f"{self.doc_type} v{self.version}{flag}"

    class Meta:
        ordering = ['doc_type', '-effective_date']
        constraints = [
            models.UniqueConstraint(
                fields=['doc_type', 'version'],
                name='legaldocument_unique_type_version',
            ),
            # A lo sumo una versión vigente por tipo (índice único parcial).
            models.UniqueConstraint(
                fields=['doc_type'],
                condition=models.Q(is_current=True),
                name='legaldocument_one_current_per_type',
            ),
        ]


class LegalAcceptance(OrganizationalModel):
    """
    Append-only: sin PATCH/DELETE (no se exponen). Una fila por
    (user, document-version). La organización se hereda del user.
    """
    user = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='legal_acceptances',
    )
    document = models.ForeignKey(
        LegalDocument, on_delete=models.PROTECT, related_name='acceptances',
    )
    # Momento real de la aceptación — server-side (now()), nunca del cliente.
    accepted_at = models.DateTimeField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)

    def save(self, *args, **kwargs):
        # Hereda organization del user — captura de tenant para auditoría.
        if self.user_id and not self.organization_id:
            self.organization_id = self.user.organization_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"LegalAcceptance u{self.user_id} → doc{self.document_id}"

    class Meta:
        ordering = ['-accepted_at', '-id']
        indexes = [
            models.Index(fields=['organization', 'user', 'document']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'document'],
                name='legalacceptance_unique_user_document',
            ),
        ]
