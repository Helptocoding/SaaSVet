"""
agent/models.py — Núcleo conversacional (É-F0).

En F0 viven: identidad de contacto, conversación (FSM persistida) y
configuración por organización. `ToolExecution`, `LLMCall` y `HumanHandoff`
llegan en É-F1 (no crear stubs — YAGNI, plan v1.1).

Principios (contrato: docs/whatsapp-agent-implementation-plan.md §8):
- El dominio es la memoria de largo plazo del negocio: aquí NUNCA se copia
  estado de negocio (citas/vacunas se leen en vivo); solo referencias por
  public_id y estado conversacional.
- FSM persistida en DB (4 estados; `pending_action` y bloqueo son datos
  derivados, NO estados) — jamás inferida del contexto del LLM.
- `ContactIdentity` NO es un User: jamás se le emiten tokens (ADR p51
  separa actor-agente de identidad-de-contacto).
"""
from django.db import models
from django.utils import timezone

from apps.core.models import OrganizationalModel, PublicIdMixin


class ContactIdentity(OrganizationalModel):
    """Quién habla por el canal, por organización — con nivel de confianza.

    La verificación sube por reto ("el cliente aporta, el sistema verifica",
    regla G4 de la spec): nunca se enumeran datos para que el contacto los
    confirme. `phone_normalized` = últimos 10 dígitos del wa_id (decisión
    Q5, México-only; el dominio NO migra a E.164).
    """

    VERIFICATION_UNKNOWN = 'unknown'
    VERIFICATION_PHONE_MATCH = 'phone_match'
    VERIFICATION_CONFIRMED = 'confirmed_in_chat'
    VERIFICATION_STAFF = 'staff_verified'
    VERIFICATION_CHOICES = (
        (VERIFICATION_UNKNOWN, 'Sin verificar'),
        (VERIFICATION_PHONE_MATCH, 'Teléfono coincide'),
        (VERIFICATION_CONFIRMED, 'Confirmado en chat'),
        (VERIFICATION_STAFF, 'Verificado por staff'),
    )

    channel_type = models.CharField(max_length=20, default='whatsapp')
    # wa_id del remitente (E.164 sin '+', tal como lo entrega el proveedor).
    external_id = models.CharField(max_length=32)
    phone_normalized = models.CharField(max_length=10, blank=True, default='')
    # PROTECT: si el Owner tiene identidades de contacto, primero se
    # desvinculan (consistente con la política de borrado ADR p16).
    owner = models.ForeignKey(
        'patients.Owner', on_delete=models.PROTECT,
        null=True, blank=True, related_name='contact_identities',
    )
    verification_level = models.CharField(
        max_length=20, choices=VERIFICATION_CHOICES,
        default=VERIFICATION_UNKNOWN,
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    # Nombre de perfil de WhatsApp — dato NO confiable (lo escribe el
    # cliente); solo display de bandeja, jamás para verificación.
    display_name = models.CharField(max_length=128, blank=True, default='')
    is_blocked = models.BooleanField(default=False)
    # ≥2 owners con el mismo teléfono en la org (D1): el sistema nunca
    # "elige" — intenciones personales escalan a humano (E-05).
    is_ambiguous = models.BooleanField(default=False)
    # UX-01: aviso de privacidad just-in-time, una sola vez por contacto.
    privacy_notice_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'channel_type', 'external_id'],
                name='contactidentity_unique_per_org_channel',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'phone_normalized']),
        ]

    def __str__(self):
        return f"ContactIdentity<{self.channel_type} {self.external_id} {self.verification_level}>"


class Conversation(PublicIdMixin, OrganizationalModel):
    """Hilo conversacional con FSM persistida (spec §7, v1.1: 4 estados).

    La organización queda fijada al crear (derivada del ChannelAccount
    receptor) y es INMUTABLE — ninguna tool ni el LLM la re-deciden (R1).
    `flow` es scratchpad del flujo activo (slots, refs, pending_action) con
    la misma filosofía que MedicalRecord.consultation_draft (ADR p50):
    NUNCA fuente de verdad de negocio.
    """

    STATE_ACTIVE = 'active'
    STATE_HANDOFF_PENDING = 'handoff_pending'
    STATE_HUMAN_ACTIVE = 'human_active'
    STATE_CLOSED = 'closed'
    STATE_CHOICES = (
        (STATE_ACTIVE, 'Activa'),
        (STATE_HANDOFF_PENDING, 'Esperando humano'),
        (STATE_HUMAN_ACTIVE, 'Atendida por humano'),
        (STATE_CLOSED, 'Cerrada'),
    )

    channel_account = models.ForeignKey(
        'channels.ChannelAccount', on_delete=models.PROTECT,
        related_name='conversations',
    )
    contact = models.ForeignKey(
        ContactIdentity, on_delete=models.PROTECT, related_name='conversations',
    )
    state = models.CharField(
        max_length=20, choices=STATE_CHOICES, default=STATE_ACTIVE,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    # Ventana de 24 h de WhatsApp: fuera de ella solo plantillas (F3). La
    # valida el Sender, no el LLM.
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    # Bandeja F0: claim exclusivo simple (HumanHandoff formal llega en É-F1).
    claimed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    # Estado del flujo activo (F1): slots, tabla de refs, pending_action.
    # Whitelist de keys + tope de tamaño se enforcen en É-F1 (patrón ADR p50).
    flow = models.JSONField(default=dict, blank=True)
    # Resumen rodante (F1) — compresión conversacional, jamás datos clínicos.
    summary = models.TextField(blank=True, default='')

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'state', '-last_activity_at']),
            models.Index(fields=['contact', '-created_at']),
        ]

    def __str__(self):
        return f"Conversation<{self.public_id} {self.state}>"


class AgentSettings(models.Model):
    """Configuración del subsistema por organización (espejo del patrón
    OrganizationSettings). v1.1 §7-C7: solo 4 campos en F0 — cada knob se
    añade cuando exista quien lo gire (scheduling_mode llega en F2).
    """

    organization = models.OneToOneField(
        'organizations.Organization', on_delete=models.CASCADE,
        related_name='agent_settings',
    )
    # Kill switch operativo (Q15/R10: la demo queda en False; ninguna
    # conversación se procesa con esto apagado — solo plantilla T0-DISABLED).
    enabled = models.BooleanField(default=False)
    # Actor RBAC del subsistema (ADR p51). SET_NULL: si el user se pierde,
    # ensure_agent_users lo repara; PROTECT bloquearía esa reparación.
    agent_user = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    # Horario de atención (los datos públicos de la clínica NO existen en
    # organizations — gap D2 del plan; viven aquí hasta promoverse).
    # Schema del JSON se define con las plantillas tier-0 (PR-5).
    business_hours = models.JSONField(default=dict, blank=True)
    # Hechos de FAQ (dirección, estacionamiento…) para INT-10/T5.
    faq_facts = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"AgentSettings — {self.organization.name} ({'ON' if self.enabled else 'OFF'})"
