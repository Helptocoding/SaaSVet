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
from django.core.exceptions import ValidationError
from django.db import models, transaction
from uuid import uuid4
from django.utils import timezone

from apps.core.models import OrganizationalModel, PublicIdMixin
from .operation_model_contract import OperationManager
from .capabilities import OPERATIONS
from . import arbiter


class InboxReadState(OrganizationalModel):
    """Lectura propia del staff por hilo, independiente del episodio (ADR p60 D-3)."""

    track_updated_at = True

    user = models.ForeignKey('users.User', on_delete=models.PROTECT, related_name='+')
    contact = models.ForeignKey('agent.ContactIdentity', on_delete=models.PROTECT, related_name='+')
    channel_account = models.ForeignKey(
        'channels.ChannelAccount', on_delete=models.PROTECT, related_name='+',
    )
    last_read_message = models.ForeignKey(
        'channels.Message', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'user', 'contact', 'channel_account'],
                name='inbox_read_state_unique_thread',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'user', 'updated_at'], name='inbox_read_user_updated_idx'),
        ]

    def clean(self):
        super().clean()
        if not self.organization_id:
            return
        errors = {}
        for name in ('user', 'contact', 'channel_account', 'last_read_message'):
            related = getattr(self, name) if getattr(self, name + '_id') else None
            if related and related.organization_id != self.organization_id:
                errors[name] = 'Debe pertenecer a la misma organización.'
        if self.last_read_message_id:
            message = self.last_read_message
            if (message.contact_id != self.contact_id
                    or message.channel_account_id != self.channel_account_id
                    or message.direction != 'in'):
                errors['last_read_message'] = 'Debe ser un entrante del mismo hilo.'
        if errors:
            raise ValidationError(errors)


class ContactIdentity(PublicIdMixin, OrganizationalModel):
    """Quién habla por el canal, por organización — con nivel de confianza.

    La verificación sube por reto ("el cliente aporta, el sistema verifica",
    regla G4 de la spec): nunca se enumeran datos para que el contacto los
    confirme. `phone_normalized` = últimos 10 dígitos del wa_id (decisión
    Q5, México-only; el dominio NO migra a E.164).
    """

    track_updated_at = True
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

    # B7A: permission generation, independent of matter and worker ownership.
    authorization_revision = models.PositiveBigIntegerField(default=0, editable=False)
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
    # Levantado por `reset_contact_identity` (soporte/QA): impide CUALQUIER
    # auto-enlace posterior a un Owner existente por coincidencia de teléfono
    # — no solo `_rematch_owner` (mensaje entrante normal), también el alta
    # de cliente nuevo (`tools.commit_register_new_client_and_pet`, que
    # puede terminar reutilizando ese mismo Owner vía `get_or_create` en
    # `create-with-patient`). Si no, el reset se deshacía solo por cualquiera
    # de las dos rutas. Se baja ÚNICAMENTE al alcanzar `confirmed_in_chat`/
    # `staff_verified` por una vía confiable (identity._promote, y
    # link_self_registered/link_family, ambas solo alcanzables ya con el
    # guard correspondiente superado — ver sus docstrings): nunca por el
    # mero hecho de volver a escribir.
    auto_rematch_blocked = models.BooleanField(default=False)
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

    def save(self, *args, **kwargs):
        from .operation_identity import save_identity
        return save_identity(self, super().save, args, kwargs)


class Conversation(PublicIdMixin, OrganizationalModel):
    """Hilo conversacional con FSM persistida (spec §7, v1.1: 4 estados).

    La organización queda fijada al crear (derivada del ChannelAccount
    receptor) y es INMUTABLE — ninguna tool ni el LLM la re-deciden (R1).
    `flow` es scratchpad del flujo activo (slots, refs, pending_action) con
    la misma filosofía que MedicalRecord.consultation_draft (ADR p50):
    NUNCA fuente de verdad de negocio.
    """

    track_updated_at = True
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
    # POR QUÉ se cerró (plan de continuidad, F2). Antes ningún cierre lo
    # registraba, así que «se cerró por inactividad» y «lo cerró recepción» eran
    # indistinguibles en los datos. `legacy_unknown` es el valor de las filas ya
    # cerradas: no se les inventa una razón.
    CLOSE_IDLE = 'idle'
    CLOSE_STAFF = 'staff'
    CLOSE_OPT_OUT = 'opt_out'
    CLOSE_IDENTITY_RESET = 'identity_reset'
    CLOSE_DUPLICATE = 'duplicate_session'
    CLOSE_LEGACY = 'legacy_unknown'
    CLOSE_REASON_CHOICES = (
        (CLOSE_IDLE, 'Inactividad'),
        (CLOSE_STAFF, 'Cerrada por recepción'),
        (CLOSE_OPT_OUT, 'Baja del cliente'),
        (CLOSE_IDENTITY_RESET, 'Reset de identidad'),
        (CLOSE_DUPLICATE, 'Sesión duplicada'),
        (CLOSE_LEGACY, 'Desconocida (fila previa al campo)'),
    )
    close_reason = models.CharField(
        max_length=20, choices=CLOSE_REASON_CHOICES, blank=True, default='',
    )
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
    # Qué tipo de relación declaró el contacto SIN expediente vinculado. No se
    # infiere por frases ni por matchers: el modelo lo decide semánticamente
    # mediante una tool tipada y el servidor lo usa solo como frontera de
    # capacidades (alta vs. identificación). ``''`` significa que todavía
    # falta preguntarlo; un contacto con ``owner`` ya tiene ruta existente por
    # un hecho de dominio y no necesita escribir este campo.
    INTAKE_UNRESOLVED = ''
    INTAKE_NEW_CLIENT = 'new_client'
    INTAKE_EXISTING_CLIENT = 'existing_client'
    INTAKE_CHOICES = (
        (INTAKE_UNRESOLVED, 'Pendiente de clasificar'),
        (INTAKE_NEW_CLIENT, 'Primera visita'),
        (INTAKE_EXISTING_CLIENT, 'Cliente existente'),
    )
    intake_path = models.CharField(
        max_length=20, choices=INTAKE_CHOICES, blank=True, default='',
    )
    # `summary` (resumen rodante) se RETIRÓ en F5 del plan de continuidad. Se
    # declaró en É-F1 y nunca se escribió ni se leyó: 20 filas en producción, 0
    # con contenido. La continuidad se resolvió por otro camino —el transcript se
    # lee por contacto (F2) y los hechos duraderos salen de tools (F4)—, así que
    # un resumen generado por el LLM habría sido una segunda fuente de verdad
    # (justo lo que prohíbe ADR p50) con su propia superficie de fuga.
    #
    # Si algún día hace falta comprimir, se diseña entonces: un campo muerto no
    # es una decisión aplazada, es una invitación a llenarlo sin pensarlo.
    # Presupuesto (spec §2.6): al alcanzar el tope global la conversación
    # degrada a plantilla + handoff (E-09). Solo lo incrementa el planner.
    total_llm_calls = models.PositiveIntegerField(default=0)
    # Proyección legacy del lease B3 para lectores/UI compatibles. Ningún
    # claim ni release nuevo usa este campo como autoridad: usa TurnWork.
    processing_until = models.DateTimeField(null=True, blank=True)
    # B3 authority generation. processing_until is only a compatibility projection.
    ownership_epoch = models.PositiveBigIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'state', '-last_activity_at']),
            models.Index(fields=['contact', '-created_at']),
        ]

    def __str__(self):
        return f"Conversation<{self.public_id} {self.state}>"


class ConversationOperation(OrganizationalModel):
    """B7A exact immutable definition. PENDING is not consent or WRITE authority."""
    KINDS = tuple(spec.operation_kind for spec in OPERATIONS.values() if spec.operation_kind)
    CONSENT_STATES = ('PENDING', 'AUTHORIZED', 'REJECTED', 'EXPIRED', 'INVALIDATED')
    EXECUTION_STATES = ('NOT_STARTED', 'SUCCEEDED', 'FAILED', 'UNCERTAIN')
    operation_key = models.UUIDField(default=uuid4, unique=True, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='operations')
    contact = models.ForeignKey(ContactIdentity, on_delete=models.PROTECT, related_name='operations')
    source_turn = models.ForeignKey('TurnWork', on_delete=models.PROTECT, related_name='operations')
    source_message = models.ForeignKey('channels.Message', on_delete=models.PROTECT, related_name='+')
    stage_key = models.CharField(max_length=40, default='business_definition_v1', editable=False)
    goal = models.ForeignKey('ConversationGoal', null=True, blank=True, on_delete=models.PROTECT, related_name='operations')
    proposal_message = models.ForeignKey('channels.Message', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    operation_kind = models.CharField(max_length=32, choices=[(s, s) for s in KINDS])
    authorization_mode = models.CharField(max_length=32, choices=[(s, s) for s in
        ('EXPLICIT_CONFIRMATION', 'CONTEXTUAL_DECLARATION', 'STEP_UP')])
    parameters = models.JSONField(default=dict)
    parameters_digest = models.CharField(max_length=64, editable=False)
    parameters_schema_version = models.PositiveSmallIntegerField(default=1, editable=False)
    preconditions = models.JSONField(default=dict)
    permission_snapshot = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
    owner = models.ForeignKey('patients.Owner', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    pet = models.ForeignKey('patients.Pet', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    appointment = models.ForeignKey('appointments.Appointment', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    binding_revision = models.PositiveBigIntegerField()
    identity_revision = models.PositiveBigIntegerField()
    ownership_epoch = models.PositiveBigIntegerField()
    replaces = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='replacements')
    consent_state = models.CharField(max_length=12, default='PENDING', choices=[(s, s) for s in CONSENT_STATES])
    invalidation_reason = models.CharField(max_length=64, blank=True, default='')
    authorized_at = models.DateTimeField(null=True, blank=True)
    consent_decided_at = models.DateTimeField(null=True, blank=True)
    authorization_message = models.ForeignKey('channels.Message', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    authorization_channel = models.CharField(max_length=32, blank=True, default='')
    authorization_policy_version = models.PositiveSmallIntegerField(null=True, blank=True)
    execution_state = models.CharField(max_length=12, default='NOT_STARTED', choices=[(s, s) for s in EXECUTION_STATES])
    result = models.JSONField(default=dict, blank=True)
    result_code = models.CharField(max_length=64, blank=True, default='')
    executed_at = models.DateTimeField(null=True, blank=True)
    objects = OperationManager()
    all_objects = OperationManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['source_turn', 'stage_key'], name='operation_causal_stage_unique'),
            models.CheckConstraint(condition=~models.Q(consent_state__in=('AUTHORIZED', 'REJECTED')) |
                (models.Q(consent_decided_at__isnull=False) & models.Q(proposal_message__isnull=False)
                 & models.Q(authorization_message__isnull=False)
                 & (models.Q(authorization_policy_version=1) | models.Q(
                     authorization_policy_version=2, operation_kind='CONFIRM_ATTENDANCE',
                     authorization_mode='CONTEXTUAL_DECLARATION',
                     preconditions__contains={'schema': 3, 'attendance_contract': 1}))
                 & models.Q(authorization_policy_version__isnull=False)
                 & models.Q(authorization_channel='whatsapp')), name='operation_b7b_decision_evidence'),
            models.UniqueConstraint(fields=['goal'], condition=models.Q(consent_state='PENDING'), name='operation_one_pending_matter'),
            models.CheckConstraint(condition=~models.Q(pk=models.F('replaces_id')), name='operation_no_self_replace'),
            models.CheckConstraint(condition=models.Q(parameters_digest__regex=r'^[0-9a-f]{64}$'), name='operation_digest_sha256'),
            models.CheckConstraint(condition=models.Q(consent_state__in=('PENDING', 'AUTHORIZED', 'REJECTED', 'EXPIRED', 'INVALIDATED')), name='operation_consent_valid'),
            models.CheckConstraint(condition=models.Q(execution_state__in=('NOT_STARTED', 'SUCCEEDED', 'FAILED', 'UNCERTAIN')), name='operation_execution_valid'),
            models.CheckConstraint(condition=~models.Q(consent_state='AUTHORIZED') | (models.Q(authorized_at__isnull=False) & models.Q(authorization_message__isnull=False)), name='operation_authorized_evidence'),
            models.CheckConstraint(condition=models.Q(execution_state='NOT_STARTED') | models.Q(consent_state='AUTHORIZED'), name='operation_effect_needs_consent'),
        ]
        indexes = [models.Index(fields=['organization', 'conversation', 'consent_state'], name='operation_current_lookup')]

    def save(self, *args, **kwargs):
        from .operation_model_contract import validate_operation
        with transaction.atomic():
            validate_operation(self)  # Cannot bypass with save(validate=False).
            return super().save(*args, **kwargs)


class TurnWork(OrganizationalModel):
    """Durable local work; completion says nothing about business or delivery."""

    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    NON_TERMINAL = (PENDING, PROCESSING)
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT,
                                     related_name='turn_works')
    anchor_message = models.ForeignKey('channels.Message', on_delete=models.PROTECT,
                                       related_name='+')
    anchor_created_at = models.DateTimeField()
    cursor_message_id = models.PositiveBigIntegerField()
    cursor_created_at = models.DateTimeField()
    # Freeze the B1 interpretation clock too, without duplicating event bodies.
    context_at = models.DateTimeField()
    clinic_timezone = models.CharField(max_length=64)
    status = models.CharField(max_length=10, default=PENDING,
        choices=[(s, s) for s in ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')])
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome_code = models.CharField(max_length=64, blank=True, default='')
    ownership_epoch = models.PositiveBigIntegerField(default=0)

    # B9 operational admission survives finalize_turn rollback/restart.
    # Existing rows migrate as unknown (NULL), only new work defaults to zero.
    llm_calls_admitted = models.PositiveIntegerField(null=True, default=0)
    llm_output_tokens_reserved = models.PositiveIntegerField(null=True, default=0)
    llm_call_limit = models.PositiveIntegerField(default=30)
    llm_output_token_limit = models.PositiveIntegerField(default=18000)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(models.Q(llm_calls_admitted__isnull=True) |
                models.Q(llm_calls_admitted__lte=models.F('llm_call_limit'))),
                name='turnwork_llm_calls_limit'),
            models.CheckConstraint(condition=(models.Q(llm_output_tokens_reserved__isnull=True) |
                models.Q(llm_output_tokens_reserved__lte=models.F('llm_output_token_limit'))),
                name='turnwork_llm_tokens_limit'),

            models.UniqueConstraint(fields=['conversation', 'anchor_message'],
                                    name='turnwork_unique_anchor'),
            models.UniqueConstraint(fields=['conversation'],
                condition=models.Q(status__in=['PENDING', 'PROCESSING']),
                name='turnwork_one_nonterminal'),
            models.CheckConstraint(condition=(~models.Q(status='PROCESSING') |
                (models.Q(lease_token__isnull=False) &
                 models.Q(lease_expires_at__isnull=False) & models.Q(attempts__gt=0))),
                name='turnwork_processing_lease'),
            models.CheckConstraint(condition=(~models.Q(status='COMPLETED') |
                (models.Q(completed_at__isnull=False) & ~models.Q(outcome_code=''))),
                name='turnwork_completed_outcome'),
        ]
        indexes = [
            models.Index(fields=['status', 'next_attempt_at'], name='turnwork_poll_retry'),
            models.Index(fields=['status', 'lease_expires_at'], name='turnwork_poll_lease'),
        ]

    def clean(self):
        super().clean()
        if self.conversation_id and self.anchor_message_id:
            conv, anchor = self.conversation, self.anchor_message
            if (conv.organization_id != self.organization_id or
                    anchor.organization_id != self.organization_id or
                    anchor.conversation_id != conv.pk or anchor.direction != 'in'):
                raise ValidationError('TurnWork scope mismatch')


class TurnOperationAssessment(OrganizationalModel):
    """Decisión semántica y auditable sobre un turno posterior a un recibo.

    No contiene una copia del texto ni decide mediante matchers. Conserva los
    mensajes que formaron la ráfaga, el veredicto de dos roles de lenguaje y la
    operación tipada que el orquestador (no el planner) puede convertir en un
    objetivo. Un veredicto no operativo también se persiste: que una capacidad
    no se abrió es parte de la auditoría, no una ausencia silenciosa de datos.
    """

    VERDICT_CONVERSATIONAL = 'conversational'
    VERDICT_AUTHORIZED = 'authorized'
    VERDICT_AMBIGUOUS = 'ambiguous'
    VERDICT_REJECTED = 'rejected'
    VERDICT_UNAVAILABLE = 'unavailable'
    VERDICT_CHOICES = (
        (VERDICT_CONVERSATIONAL, 'Turno conversacional'),
        (VERDICT_AUTHORIZED, 'Operación autorizada'),
        (VERDICT_AMBIGUOUS, 'Operación ambigua'),
        (VERDICT_REJECTED, 'Operación rechazada'),
        (VERDICT_UNAVAILABLE, 'Verificador no disponible'),
    )

    OPERATION_NEW_APPOINTMENT = 'new_appointment'
    OPERATION_FIRST_VISIT = 'first_visit'
    OPERATION_NEW_PET_WITH_APPOINTMENT = 'new_pet_with_appointment'
    OPERATION_NEW_PET_ONLY = 'new_pet_only'
    OPERATION_CANCEL_APPOINTMENT = 'cancel_appointment'
    OPERATION_RESCHEDULE_APPOINTMENT = 'reschedule_appointment'
    OPERATION_CHOICES = (
        (OPERATION_NEW_APPOINTMENT, 'Nueva cita'),
        (OPERATION_FIRST_VISIT, 'Primera visita'),
        (OPERATION_NEW_PET_WITH_APPOINTMENT, 'Mascota nueva con cita'),
        (OPERATION_NEW_PET_ONLY, 'Mascota nueva sin cita'),
        (OPERATION_CANCEL_APPOINTMENT, 'Cancelar cita'),
        (OPERATION_RESCHEDULE_APPOINTMENT, 'Reagendar cita'),
    )

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT,
        related_name='turn_operation_assessments',
    )
    # Último mensaje de la ráfaga. Hace idempotente la decisión si el worker
    # retoma el mismo turno; la relación M2M de abajo conserva la evidencia
    # completa y ordenada.
    anchor_message = models.ForeignKey(
        'channels.Message', on_delete=models.PROTECT,
        related_name='+',
    )
    verdict = models.CharField(max_length=20, choices=VERDICT_CHOICES)
    operation = models.CharField(
        max_length=32, choices=OPERATION_CHOICES, blank=True, default='',
    )
    authorizer_model = models.CharField(max_length=64, blank=True, default='')
    verifier_model = models.CharField(max_length=64, blank=True, default='')
    authorizer_prompt_version = models.CharField(
        max_length=32, blank=True, default='')
    verifier_prompt_version = models.CharField(
        max_length=32, blank=True, default='')
    # Código estable, sin cuerpo del mensaje ni razonamiento libre del modelo.
    failure_code = models.CharField(max_length=48, blank=True, default='')
    source_messages = models.ManyToManyField(
        'channels.Message', through='TurnOperationAssessmentMessage',
        related_name='turn_operation_assessments',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['conversation', 'anchor_message'],
                name='turnoperationassessment_one_per_anchor',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'conversation', 'created_at']),
            models.Index(fields=['organization', 'verdict', 'created_at']),
        ]

    def __str__(self):
        return f"TurnOperationAssessment<{self.verdict} {self.operation}>"


class TurnOperationAssessmentMessage(OrganizationalModel):
    """Mensaje fuente de una evaluación, preservando su orden en la ráfaga."""

    assessment = models.ForeignKey(
        TurnOperationAssessment, on_delete=models.CASCADE,
        related_name='message_links',
    )
    message = models.ForeignKey('channels.Message', on_delete=models.PROTECT)
    ordinal = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['assessment', 'message'],
                name='turnoperationassessmentmessage_unique_message',
            ),
            models.UniqueConstraint(
                fields=['assessment', 'ordinal'],
                name='turnoperationassessmentmessage_unique_ordinal',
            ),
        ]
        ordering = ['ordinal']


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

    def save(self, *args, **kwargs):
        # B7A retirement shares the B6 transaction, including staged B3 saves.
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            stale = ConversationOperation.objects.for_organization(self.organization_id).filter(goal_id=self.pk)
            if self.status in self.FOREGROUND_STATUSES:
                stale = stale.exclude(binding_revision=self.binding_revision)
            count = stale.retire_pending('INVALIDATED', 'binding_or_matter_changed')
            if count:
                from .operations import observe
                transaction.on_commit(lambda: observe('operation_invalidated', count=count))
            return result

    # Ciclo de vida del COMPROMISO (ADR p55 §3). Un compromiso nunca
    # desaparece: siempre está en uno de estos estados.
    STATUS_ACTIVE = 'active'
    STATUS_DEVIATED = 'deviated'      # ex-`paused`: el agente atiende otra
                                      # cosa y VUELVE — exige `return_to`
    STATUS_SUSPENDED = 'suspended'    # otro compromiso tomó el frente; se
                                      # OFRECE de vuelta (suplantar ≠ abortar)
    STATUS_BLOCKED = 'blocked'        # el dominio NO PUEDE cumplirlo
    STATUS_COMPLETED = 'completed'
    STATUS_ABANDONED = 'abandoned'    # el cliente lo abandonó
    STATUS_HANDOFF = 'handoff'
    # DEPRECADO. `cancelled` conflacionaba «suplantado» y «abandonado» (el
    # hallazgo de §10.4 de la auditoría de rigidez). Se conserva SOLO para no
    # reetiquetar filas históricas con un significado que no tuvieron: no se
    # puede saber, fila por fila, cuál de los dos casos fue. No usar en código
    # nuevo — hoy se escribe `suspended` o `abandoned` según corresponda.
    STATUS_CANCELLED_DEPRECATED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, 'En curso'),
        (STATUS_DEVIATED, 'Desviado'),
        (STATUS_SUSPENDED, 'Suspendido'),
        (STATUS_BLOCKED, 'Bloqueado'),
        (STATUS_COMPLETED, 'Completado'),
        (STATUS_ABANDONED, 'Abandonado'),
        (STATUS_HANDOFF, 'Escalado a humano'),
        (STATUS_CANCELLED_DEPRECATED, 'Cancelado (deprecado)'),
    )
    # No terminales: el compromiso sigue vivo y puede retomarse.
    OPEN_STATUSES = (STATUS_ACTIVE, STATUS_DEVIATED, STATUS_SUSPENDED)
    # En el FRENTE de la conversación (como máximo uno — ver constraints).
    FOREGROUND_STATUSES = (STATUS_ACTIVE, STATUS_DEVIATED)

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='goals',
    )
    # El mensaje entrante que autorizó abrir este objetivo operativo. Los
    # objetivos anteriores a la frontera no tienen procedencia (NULL); los
    # que nacen después de un recibo de operación sí deben poder reconstruir
    # qué nueva petición del cliente los abrió. No es copy ni una inferencia
    # sobre frases: es la relación causal entre un turno y una capacidad.
    authorization_message = models.ForeignKey(
        'channels.Message', on_delete=models.PROTECT,
        null=True, blank=True, related_name='authorized_goals',
    )
    # Reemplaza gradualmente la procedencia de un solo mensaje por la decisión
    # auditable del turno completo. `authorization_message` se conserva para
    # compatibilidad histórica y como ancla rápida de consultas existentes.
    operation_assessment = models.ForeignKey(
        TurnOperationAssessment, on_delete=models.PROTECT,
        null=True, blank=True, related_name='authorized_goals',
    )
    name = models.CharField(max_length=40)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )
    slots = models.JSONField(default=dict, blank=True)
    # B6 semantic generation belongs to this matter, not to identity/ownership.
    binding_revision = models.PositiveBigIntegerField(default=0)
    bound_owner = models.ForeignKey(
        'patients.Owner', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+',
    )
    bound_pet = models.ForeignKey(
        'patients.Pet', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+',
    )
    bound_appointment = models.ForeignKey(
        'appointments.Appointment', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+',
    )
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

    # ── Coordenadas del ciclo de vida (ADR p55 §3) ──────────────────────────
    # DÓNDE se retoma un compromiso desviado. Una pausa sin dirección de
    # retorno no es una pausa: es una interrupción que se sobrevivió por
    # suerte — retomar obligaba a re-derivar la pregunta pendiente de la
    # ventana de contexto, que es justo lo que falla (R4).
    return_to = models.CharField(max_length=32, blank=True, default='')
    # QUÉ tomó el frente cuando este compromiso quedó suspendido, para poder
    # ofrecerlo de vuelta ("¿retomamos la cita de Luna?").
    supplanted_by = models.CharField(max_length=40, blank=True, default='')
    # POR QUÉ el dominio no puede cumplirlo (p.ej. `no_vet`). Solo con
    # `status=blocked`; es lo que permite decirlo una vez y dejar de pedir.
    blocked_reason = models.CharField(max_length=40, blank=True, default='')
    # Intentos FALLIDOS (una respuesta equivocada). Distinto de `stall_turns`,
    # que cuenta turnos SIN AVANCE: preguntar no falla, y desde É-F4 Fase 0
    # tampoco cuenta como fallo. Es el presupuesto de paciencia de los retos
    # de identidad (2 fallos reales → humano, E-06).
    attempts_failed = models.PositiveSmallIntegerField(default=0)
    # Estado de trabajo LOCAL del mecanismo (candidatos que sobreviven a un
    # factor, si ya se dio la repetición gratis, cuántas veces se re-preguntó
    # el tamiz). Nunca se agrega ni se reporta: lo agregable son las columnas.
    # Vive aquí y no en `Conversation.flow` porque el compromiso es la fuente
    # única de la interacción (R7) — un blob por fuera era justo el problema.
    working_state = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            # Como máximo un compromiso EN EL FRENTE por conversación (patrón
            # espejo de `cashsession_one_open_per_user`). Los suspendidos no
            # cuentan: la urgencia suplanta a la cita, y ambas coexisten.
            models.UniqueConstraint(
                fields=['conversation'],
                condition=models.Q(status__in=('active', 'deviated')),
                name='conversationgoal_one_open_per_conversation',
            ),
            # …y como máximo uno suspendido. Límite deliberado (mismo alcance
            # que el slot único de la Fase 1): no existe hoy un caso que
            # necesite apilar dos, y una pila sin caso es sobre-diseño.
            models.UniqueConstraint(
                fields=['conversation'],
                condition=models.Q(status='suspended'),
                name='commitment_one_suspended_per_conversation',
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
    # Diagnostic correlation only; B7A does not use attempts as authorization.
    operation = models.ForeignKey(ConversationOperation, null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='tool_executions')
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
    """Evidence per call; B9 inserts admission and records observation once.

    Proveedor-agnóstico: `provider`/`model_id` son datos, no supuestos
    (el proveedor es elección del PO — feedback 2026-07-17). No guarda el
    prompt (PII + volumen): `prompt_version` identifica la plantilla en git.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='llm_calls',
    )
    turn_work = models.ForeignKey(TurnWork, on_delete=models.PROTECT,
        null=True, blank=True, related_name='llm_calls')
    admission_id = models.UUIDField(null=True, blank=True, unique=True)
    admitted_at = models.DateTimeField(null=True, blank=True)
    recorded_at = models.DateTimeField(null=True, blank=True)
    admission_lease_token = models.UUIDField(null=True, blank=True)
    admission_epoch = models.PositiveBigIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=24, blank=True, default='', choices=[
        ('planner', 'planner'), ('operation_authorizer', 'operation_authorizer'),
        ('operation_verifier', 'operation_verifier')])
    reserved_output_tokens = models.PositiveIntegerField(null=True, blank=True)
    provider = models.CharField(max_length=32, blank=True, default='')
    model_id = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=32, blank=True, default='')
    input_tokens = models.PositiveIntegerField(null=True, blank=True, default=None)
    output_tokens = models.PositiveIntegerField(null=True, blank=True, default=None)
    # Legacy optional estimate; NULL means unknown. Not budget authority.
    cost_estimate = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True, default=None,
    )
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    finish_reason = models.CharField(max_length=32, blank=True, default='')
    retry_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    error = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(models.Q(admission_id__isnull=True) |
                (models.Q(turn_work__isnull=False, admitted_at__isnull=False,
                          admission_lease_token__isnull=False, admission_epoch__isnull=False,
                          reserved_output_tokens__isnull=False, reserved_output_tokens__gt=0) &
                 models.Q(purpose__in=['planner', 'operation_authorizer', 'operation_verifier']))),
                name='llmcall_admission_evidence'),
        ]
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

    track_updated_at = True
    REASON_EXPLICIT = 'explicit_request'
    REASON_EMERGENCY = 'emergency'
    REASON_SAFETY = 'safety_urgent'
    REASON_POLICY = 'policy_block'
    REASON_LOW_CONFIDENCE = 'low_confidence'
    REASON_TOOL_FAILURE = 'tool_failure'
    # 'identity_ambiguous' mintió en producción (conv 13: los 4 factores
    # eran correctos, nada fue "ambiguo" — el sistema los tiró él solo).
    # Fase 1 §1.5: 'identity' es el valor correcto para escalados NUEVOS;
    # 'identity_ambiguous' queda DEPRECADO — solo para no reescribir las
    # filas viejas (histórico append-only). No usar 'identity_ambiguous'
    # en código nuevo. Sunset documentado en docs/modules/agent.md.
    REASON_IDENTITY = 'identity'
    REASON_IDENTITY_AMBIGUOUS_DEPRECATED = 'identity_ambiguous'
    REASON_BUDGET = 'budget_exhausted'
    REASON_CHOICES = (
        (REASON_EXPLICIT, 'Pidió humano'),
        (REASON_EMERGENCY, 'Urgencia'),
        (REASON_SAFETY, 'Señal safety: revisión prioritaria'),
        (REASON_POLICY, 'Bloqueado por política'),
        (REASON_LOW_CONFIDENCE, 'Baja confianza'),
        (REASON_TOOL_FAILURE, 'Fallo de herramienta'),
        (REASON_IDENTITY, 'Identidad — verificación requerida o fallida'),
        (REASON_IDENTITY_AMBIGUOUS_DEPRECATED,
         'Identidad ambigua (deprecado — solo filas históricas)'),
        (REASON_BUDGET, 'Presupuesto agotado'),
    )

    PRIORITY_URGENT = 'urgent'
    PRIORITY_NORMAL = 'normal'
    PRIORITY_CHOICES = (
        (PRIORITY_URGENT, 'Urgente'),
        (PRIORITY_NORMAL, 'Normal'),
    )

    RESOLUTION_HANDLED = 'handled'
    RESOLUTION_RETURNED_TO_AGENT = 'returned_to_agent'
    RESOLUTION_CLOSED = 'closed'
    RESOLUTION_CHOICES = (
        (RESOLUTION_HANDLED, 'Atendido'),
        (RESOLUTION_RETURNED_TO_AGENT, 'Devuelto al agente'),
        (RESOLUTION_CLOSED, 'Cerrado'),
    )

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='handoffs',
    )
    reason_code = models.CharField(max_length=20, choices=REASON_CHOICES)
    reason_detail = models.CharField(max_length=200, blank=True, default='')
    # B5 evidence; NULL/empty legacy is unknown, never synthetic notification.
    source_message = models.ForeignKey('channels.Message', on_delete=models.PROTECT,
        null=True, blank=True, related_name='+')
    source_turn = models.ForeignKey('TurnWork', on_delete=models.PROTECT,
        null=True, blank=True, related_name='+')
    event_key = models.CharField(max_length=64, null=True, blank=True)
    safety_signals = models.JSONField(default=list, blank=True)
    notification_status = models.CharField(max_length=20, null=True, blank=True,
        choices=(('NOT_CONFIGURED', 'Sin canal secundario'),))
    acknowledged_by = models.ForeignKey('users.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+')
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    guidance_message = models.ForeignKey('channels.Message', on_delete=models.PROTECT,
        null=True, blank=True, related_name='+')
    guidance_epoch = models.PositiveBigIntegerField(null=True, blank=True)
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
        constraints = [models.UniqueConstraint(fields=['organization', 'event_key'],
            condition=models.Q(event_key__isnull=False), name='handoff_unique_event')]
        indexes = [
            # Cola de pendientes por org (resolved_at IS NULL).
            models.Index(fields=['organization', 'resolved_at', 'priority']),
        ]

    def __str__(self):
        return f"HumanHandoff<{self.reason_code} {self.priority}>"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.conversation_id and self.conversation.organization_id != self.organization_id:
            raise ValidationError('Handoff conversation outside organization')
        for name in ('source_message', 'source_turn', 'guidance_message'):
            row = getattr(self, name) if getattr(self, name + '_id') else None
            if row and (row.organization_id != self.organization_id or row.conversation_id != self.conversation_id):
                raise ValidationError('Handoff causal reference outside conversation')
        if self.acknowledged_by_id and self.acknowledged_by.organization_id != self.organization_id:
            raise ValidationError('Handoff acknowledgement outside organization')


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
    # Hechos de FAQ que NO tienen campo propio en la configuración de clínica
    # (estacionamiento, aviso de privacidad…). El horario y los datos de
    # contacto viven en `Organization`/`OrganizationSchedule` (ADR p53) y son
    # fuente única: el serializer rechaza aquí las claves que los dupliquen.
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


class TurnDecision(OrganizationalModel):
    """Rastro append-only de la decisión de cada turno (R12, É-F4 Fase 1).

    INVARIANTE: el runtime NUNCA lee esta tabla. Si algún día la lógica del
    turno la consulta, se vuelve una segunda fuente de verdad y viola R7
    (una interacción, una fuente de verdad). Append-only, como `Payment` /
    `VitalSigns` / `LLMCall`: la corrección es una fila nueva, jamás un UPDATE.

    Frontera oráculo/diagnóstico (docs/whatsapp-agent-f4-gobernanza-plan.md
    §1.5): `verdict`/`because`/`active_commitment`/`return_to`/
    `supplanted_by`/`facts_consumed`/`facts_produced` son el ORÁCULO — los
    tests SÍ pueden afirmar sobre estos campos, son deterministas dado el
    mismo estado de entrada. `planner_used`/`tools_called`/`duration_ms` son
    DIAGNÓSTICO — varían turno a turno con la latencia real; ningún test
    afirma sobre ellos (harían la suite intermitente y acabaría apagada).

    `verdict` es el veredicto del árbitro (`Verdict`, el conjunto cerrado de
    `arbiter.VERDICTS`, ADR p55 §2). Vacío significa que el árbitro lanzó una
    excepción y no hubo veredicto; eso solo ocurre fuera del trabajo durable
    B3, que relanza el fallo. La salida operativa del planner (`reply`,
    `silent`, `escalate`…) es diagnóstico y vive en `facts_produced['salida']`
    (orden 8, G07). Las filas anteriores a É-F5 Fase 4 conservan el texto libre
    de entonces: la tabla es append-only y no se reescriben.

    `because` es el enum cerrado y ortogonal desde É-F4 Fase 1 (regla de
    gobernanza §0.6: un presupuesto añadido después no se añade nunca); se
    deriva con un mapeo grueso y deliberadamente conservador en
    `planner._infer_because`.
    """

    class Verdict(models.TextChoices):
        """Los cinco veredictos del árbitro. Un sexto exige ADR (p55 A1)."""
        CONTINUE = arbiter.CONTINUE, 'Continuar'
        DEVIATE = arbiter.DEVIATE, 'Desviar'
        SUPPLANT = arbiter.SUPPLANT, 'Suplantar'
        ABORT = arbiter.ABORT, 'Abortar'
        ANSWER = arbiter.ANSWER, 'Responder'

    class Because(models.TextChoices):
        """POR QUÉ pasó — hechos, nunca coordenadas (G1: ortogonal a los
        nombres de compromiso/etapa; G2: cardinalidad ≤ 12)."""
        SAFEGUARD = 'safeguard', 'Cortacircuito de seguridad'
        HUMAN_REQUESTED = 'human_requested', 'Cliente pidió un humano'
        CLIENT_QUESTIONED = 'client_questioned', 'Cliente preguntó en vez de responder'
        CLIENT_CONFIRMED = 'client_confirmed', 'Cliente confirmó/afirmó'
        CLIENT_DEFERRED = 'client_deferred', 'Cliente aplazó sin decidir'
        CLIENT_ANSWERED = 'client_answered', 'Cliente aportó un dato'
        VERIFICATION_REQUIRED = 'verification_required', 'Requería verificar identidad'
        GOAL_STALLED = 'goal_stalled', 'Objetivo sin avance'
        BUDGET_EXCEEDED = 'budget_exceeded', 'Presupuesto agotado'
        SYSTEM_ERROR = 'system_error', 'Error de sistema/dominio'
        OUT_OF_SCOPE = 'out_of_scope', 'Fuera de alcance'
        PLANNER_HANDLED = 'planner_handled', 'Turno normal, sin condición especial'

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name='turn_decisions',
    )
    # ── ORÁCULO · determinista, testeable ────────────────────────────────
    verdict = models.CharField(max_length=40, choices=Verdict.choices, blank=True)
    because = models.CharField(max_length=24, choices=Because.choices)
    active_commitment = models.CharField(max_length=32, blank=True, default='')
    return_to = models.CharField(max_length=32, blank=True, default='')
    supplanted_by = models.CharField(max_length=32, blank=True, default='')
    # Solo enums/referencias — jamás el cuerpo del mensaje (cero PII, R15).
    facts_consumed = models.JSONField(default=dict, blank=True)
    facts_produced = models.JSONField(default=dict, blank=True)
    # ── DIAGNÓSTICO · variable, NUNCA se afirma en tests ─────────────────
    planner_used = models.BooleanField(default=False)
    tools_called = models.PositiveSmallIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    triggered_by_message = models.ForeignKey(
        'channels.Message', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'conversation', 'created_at']),
        ]

    def __str__(self):
        return f"TurnDecision<{self.verdict} because={self.because}>"


class ContactIdentityVerification(PublicIdMixin, OrganizationalModel):
    """Registro APPEND-ONLY del juicio humano sobre la identidad de un contacto.

    FLUJO-C (ADR p57 §5.5.3, F4). Es la unica vía por la que un contacto no
    verificado puede terminar operando sobre un `Owner` EXISTENTE, y toda ella
    pasa por una persona.

    Por que hace falta un modelo y no basta `ContactIdentity`: esa tabla guarda
    `verified_at` pero **no guarda quien verifico**, y no puede representar un
    **rechazo** — no existe un "nivel de verificacion negativo". El flujo
    aprobado exige quien, cuando y con que resultado.

    **El sistema no juzga la evidencia**: registra que una persona identificada
    afirmo haberla comprobado. `evidence_kind` es una etiqueta de auditoria, no
    un puntaje ni una validacion. Y la evidencia es **externa al telefono**: el
    numero ya se sabe que coincide —es lo que creo el caso—, asi que usarlo como
    prueba seria circular. Por eso ninguna opcion del enum se basa en el.

    Append-only como el resto de la auditoria del sistema: sin PATCH, sin
    DELETE. Una decision equivocada se corrige registrando otra, no borrando la
    anterior — la autorizacion lee **el ultimo** registro.
    """

    DECISION_APPROVED = 'approved'
    DECISION_REJECTED = 'rejected'
    DECISION_CHOICES = (
        (DECISION_APPROVED, 'Aprobada'),
        (DECISION_REJECTED, 'Rechazada'),
    )

    # Ninguna opcion basada en el telefono, a proposito (§5.5.3).
    EVIDENCE_IN_PERSON = 'in_person_id'
    EVIDENCE_KNOWN_RECORD = 'known_record'
    EVIDENCE_CALLBACK = 'callback'
    EVIDENCE_OTHER = 'other'
    EVIDENCE_CHOICES = (
        (EVIDENCE_IN_PERSON, 'Identificacion en mostrador'),
        (EVIDENCE_KNOWN_RECORD, 'Datos del expediente que solo el titular sabe'),
        (EVIDENCE_CALLBACK, 'Llamada al telefono del expediente'),
        (EVIDENCE_OTHER, 'Otra (detallar en la nota)'),
    )

    contact = models.ForeignKey(
        ContactIdentity, on_delete=models.PROTECT,
        related_name='identity_verifications',
    )
    owner_candidate = models.ForeignKey(
        'patients.Owner', on_delete=models.PROTECT, related_name='+',
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT,
        related_name='identity_verifications',
    )
    # Ata la aprobacion al CASO concreto (hallazgo W de la revision). Sin este
    # campo, "la aprobacion es del caso abierto" seria una intencion, no una
    # regla: una aprobacion de hace tres meses habilitaria una accion de hoy.
    handoff = models.ForeignKey(
        HumanHandoff, on_delete=models.PROTECT,
        related_name='identity_verifications',
    )
    decision = models.CharField(max_length=16, choices=DECISION_CHOICES)
    evidence_kind = models.CharField(max_length=24, choices=EVIDENCE_CHOICES)
    # Nota OPERATIVA ("coincide expediente 2214, vino a mostrador"), no un sitio
    # para numeros de documento. Los logs asociados llevan ids, nunca esto.
    evidence_note = models.CharField(max_length=280, blank=True, default='')
    actor = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='+',
    )

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'contact', 'owner_candidate']),
            models.Index(fields=['organization', 'handoff']),
        ]

    def clean(self):
        """El invariante de tenant se valida AQUI, no solo en la vista.

        Cuatro FKs no prueban que apunten al mismo caso. Una via futura que
        escriba el registro sin pasar por el endpoint no puede saltarselo, y un
        desajuste es un error de programacion —no un 400 de usuario—: falla
        ruidosamente y no persiste nada.
        """
        super().clean()
        if not self.organization_id:
            return
        mismatched = [
            name for name, obj in (
                ('contact', self.contact_id and self.contact),
                ('owner_candidate', self.owner_candidate_id and self.owner_candidate),
                ('conversation', self.conversation_id and self.conversation),
                ('handoff', self.handoff_id and self.handoff),
            )
            if obj and obj.organization_id != self.organization_id
        ]
        if mismatched:
            raise ValidationError(
                'Registro de verificacion con FKs de otra organizacion: '
                + ', '.join(mismatched)
            )

    def __str__(self):
        return f"ContactIdentityVerification<{self.decision} contact={self.contact_id}>"
