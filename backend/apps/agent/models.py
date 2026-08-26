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
from django.db import models
from django.utils import timezone

from apps.core.models import OrganizationalModel, PublicIdMixin


class ContactIdentity(PublicIdMixin, OrganizationalModel):
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

    Fase 1 no tiene árbitro todavía (llega en Fase 3): `verdict` guarda el
    `decision` de hoy tal cual (string libre, ~20 valores en `planner.py`);
    `because` SÍ es el enum cerrado y ortogonal desde este primer commit
    (regla de gobernanza §0.6: un presupuesto añadido después no se añade
    nunca) — se deriva con un mapeo grueso y deliberadamente conservador en
    `planner._infer_because`. Fase 3 sustituye el mapeo por el veredicto real
    del árbitro; el enum de `because` no debería necesitar romperse para eso.
    """

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
    verdict = models.CharField(max_length=40)
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
