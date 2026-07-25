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
    # Bloqueo duro (abuso/spam): sus mensajes ni se procesan.
    is_blocked = models.BooleanField(default=False)
    # Baja de mensajes PROACTIVOS (INT-04). Distinto de `is_blocked`: si el
    # cliente vuelve a escribir se le atiende normal — un "stop" en un mal día
    # no puede dejarlo inalcanzable para siempre.
    proactive_opt_out = models.BooleanField(default=False)
    # ≥2 owners con el mismo teléfono en la org (D1): el sistema nunca
    # "elige" — intenciones personales escalan a humano (E-05).
    is_ambiguous = models.BooleanField(default=False)
    # Procedencia del vínculo contacto→owner (É-F2). '' = sin vínculo /
    # phone_match implícito. Sirve para señalizar y REVOCAR en bandeja un
    # vínculo secundario (self_register hoy; family_challenge en PR-17b).
    LINKED_SELF_REGISTER = 'self_register'
    LINKED_FAMILY = 'family_challenge'
    LINKED_STAFF = 'staff'
    LINKED_VIA_CHOICES = (
        ('', 'Sin vínculo explícito'),
        (LINKED_SELF_REGISTER, 'Auto-registro'),
        (LINKED_FAMILY, 'Vínculo familiar'),
        (LINKED_STAFF, 'Vinculado por staff'),
    )
    linked_via = models.CharField(
        max_length=20, choices=LINKED_VIA_CHOICES, blank=True, default='')
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
    # Presupuesto (spec §2.6): al alcanzar el tope global la conversación
    # degrada a plantilla + handoff (E-09). Solo lo incrementa el planner.
    total_llm_calls = models.PositiveIntegerField(default=0)
    # Lease del turno en vuelo (É-F3 W0-7): mientras esté en el futuro, ningún
    # otro worker toma esta conversación. Serializa el turno SIN mantener una
    # transacción abierta durante la llamada al LLM.
    processing_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'state', '-last_activity_at']),
            models.Index(fields=['contact', '-created_at']),
        ]

    def __str__(self):
        return f"Conversation<{self.public_id} {self.state}>"


class ConversationGoal(OrganizationalModel):
    """Objetivo que persigue la conversación (É-F3 W2).

    Tabla propia y no un blob en `Conversation.flow` por dos razones: un JSON
    no se agrega (y esto tiene que servir para analytics: embudo por objetivo
    y por slot), y el ciclo de vida con estado explícito es exactamente el
    patrón de `HumanHandoff`.

    El sistema es dueño del checklist (`missing`), el modelo solo redacta la
    pregunta. `slots` guarda `{slot: {value, confidence}}` con el valor YA
    normalizado por el validador — nunca el texto crudo del cliente.
    """

    STATUS_ACTIVE = 'active'
    STATUS_PAUSED = 'paused'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_HANDOFF = 'handoff'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, 'En curso'),
        (STATUS_PAUSED, 'Pausado'),
        (STATUS_COMPLETED, 'Completado'),
        (STATUS_CANCELLED, 'Cancelado'),
        (STATUS_HANDOFF, 'Escalado a humano'),
    )
    OPEN_STATUSES = (STATUS_ACTIVE, STATUS_PAUSED)

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='goals',
    )
    name = models.CharField(max_length=40)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )
    slots = models.JSONField(default=dict, blank=True)
    missing = models.JSONField(default=list, blank=True)
    # Valores propuestos por debajo del umbral de confianza: se confirman con
    # el cliente, jamás se dan por buenos.
    low_confidence = models.JSONField(default=list, blank=True)
    # {slot: veces_preguntado} — anti-repetición.
    asked = models.JSONField(default=dict, blank=True)
    stall_turns = models.PositiveSmallIntegerField(default=0)
    last_progress_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=80, blank=True, default='')

    class Meta:
        constraints = [
            # Un solo objetivo abierto por conversación (patrón espejo de
            # `cashsession_one_open_per_user`).
            models.UniqueConstraint(
                fields=['conversation'],
                condition=models.Q(status__in=('active', 'paused')),
                name='conversationgoal_one_open_per_conversation',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'name', 'status']),
        ]

    def __str__(self):
        return f"ConversationGoal<{self.name} {self.status}>"


class ToolExecution(OrganizationalModel):
    """Auditoría append-only de cada tool ejecutada (É-F1, ADR p51).

    Completa la cadena de trazabilidad SIN FKs desde el dominio hacia agent:
    fila de dominio (`created_by = user AGENT`) → `domain_object_public_id`
    (indexado) → esta fila → conversación → mensaje disparador → LLMCall.
    Dado cualquier objeto creado por el agente se reconstruye exactamente
    qué conversación, mensaje, tool y corrida de LLM lo produjeron.

    `args_redacted`/`result_summary_redacted`: proyecciones SIN PII cruda
    (los cuerpos viven solo en Message — regla R15). Append-only por
    convención (corrección = fila nueva, jamás editar).
    """

    DECISION_AUTO = 'auto'
    DECISION_CONFIRMED = 'confirmed'
    DECISION_DENIED = 'denied'
    DECISION_ESCALATED = 'escalated'
    DECISION_CHOICES = (
        (DECISION_AUTO, 'Automática'),
        (DECISION_CONFIRMED, 'Confirmada por el cliente'),
        (DECISION_DENIED, 'Denegada por policy'),
        (DECISION_ESCALATED, 'Escalada a humano'),
    )

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='tool_executions',
    )
    tool_name = models.CharField(max_length=64)
    args_redacted = models.JSONField(default=dict, blank=True)
    policy_tier = models.CharField(max_length=8, blank=True, default='')
    policy_decision = models.CharField(
        max_length=12, choices=DECISION_CHOICES, default=DECISION_AUTO,
    )
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    result_summary_redacted = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default='')
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    # Correlación con la observabilidad existente (X-Request-ID, P1-5 A1).
    request_id = models.CharField(max_length=64, blank=True, default='')
    # public_id del objeto de dominio creado/afectado (cita, etc.).
    domain_object_public_id = models.UUIDField(
        null=True, blank=True, db_index=True,
    )
    triggered_by_message = models.ForeignKey(
        'channels.Message', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'conversation', 'created_at']),
        ]

    def __str__(self):
        return f"ToolExecution<{self.tool_name} {self.policy_decision}>"


class LLMCall(OrganizationalModel):
    """Auditoría/costos append-only de cada llamada al LLM (É-F1, R11).

    Proveedor-agnóstico: `provider`/`model_id` son datos, no supuestos
    (el proveedor es elección del PO — feedback 2026-07-17). No guarda el
    prompt (PII + volumen): `prompt_version` identifica la plantilla en git.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='llm_calls',
    )
    provider = models.CharField(max_length=32, blank=True, default='')
    model_id = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=32, blank=True, default='')
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    # Estimado con AGENT_LLM_COST_PER_MTOK_* (env por proveedor); 0 = sin
    # pricing configurado. Contabilidad, no facturación.
    cost_estimate = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
    )
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    finish_reason = models.CharField(max_length=32, blank=True, default='')
    retry_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    error = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'created_at']),
        ]

    def __str__(self):
        return f"LLMCall<{self.model_id} in={self.input_tokens} out={self.output_tokens}>"


class HumanHandoff(OrganizationalModel):
    """Cola de escalado a humano (É-F1; matriz E-01..E-10 de la spec §7).

    En F0 la bandeja usaba claim-lite sobre Conversation; desde F1 cada
    escalado deja SU registro (métrica de tasa de handoff = gate F1).
    """

    REASON_EXPLICIT = 'explicit_request'
    REASON_EMERGENCY = 'emergency'
    REASON_POLICY = 'policy_block'
    REASON_LOW_CONFIDENCE = 'low_confidence'
    REASON_TOOL_FAILURE = 'tool_failure'
    REASON_IDENTITY = 'identity_ambiguous'
    REASON_BUDGET = 'budget_exhausted'
    REASON_CHOICES = (
        (REASON_EXPLICIT, 'Pidió humano'),
        (REASON_EMERGENCY, 'Urgencia'),
        (REASON_POLICY, 'Bloqueado por política'),
        (REASON_LOW_CONFIDENCE, 'Baja confianza'),
        (REASON_TOOL_FAILURE, 'Fallo de herramienta'),
        (REASON_IDENTITY, 'Identidad ambigua'),
        (REASON_BUDGET, 'Presupuesto agotado'),
    )

    PRIORITY_URGENT = 'urgent'
    PRIORITY_NORMAL = 'normal'
    PRIORITY_CHOICES = (
        (PRIORITY_URGENT, 'Urgente'),
        (PRIORITY_NORMAL, 'Normal'),
    )

    RESOLUTION_CHOICES = (
        ('handled', 'Atendido'),
        ('returned_to_agent', 'Devuelto al agente'),
        ('closed', 'Cerrado'),
    )

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='handoffs',
    )
    reason_code = models.CharField(max_length=20, choices=REASON_CHOICES)
    reason_detail = models.CharField(max_length=200, blank=True, default='')
    priority = models.CharField(
        max_length=8, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL,
    )
    claimed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(
        max_length=20, choices=RESOLUTION_CHOICES, blank=True, default='',
    )

    class Meta:
        indexes = [
            # Cola de pendientes por org (resolved_at IS NULL).
            models.Index(fields=['organization', 'resolved_at', 'priority']),
        ]

    def __str__(self):
        return f"HumanHandoff<{self.reason_code} {self.priority}>"


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

    # É-F2 (Q14): cómo elige veterinario el agente al ofrecer/crear citas.
    #   fixed_vet     → siempre default_veterinarian (predecible; default).
    #   any_available → el subsistema resuelve un vet con hueco.
    SCHEDULING_FIXED = 'fixed_vet'
    SCHEDULING_ANY = 'any_available'
    SCHEDULING_CHOICES = (
        (SCHEDULING_FIXED, 'Veterinario fijo'),
        (SCHEDULING_ANY, 'Cualquiera disponible'),
    )
    scheduling_mode = models.CharField(
        max_length=16, choices=SCHEDULING_CHOICES, default=SCHEDULING_FIXED,
    )
    default_veterinarian = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    # UX-08: nudge único de flujo abandonado (PR-18). Por-org, default on.
    nudge_enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"AgentSettings — {self.organization.name} ({'ON' if self.enabled else 'OFF'})"
