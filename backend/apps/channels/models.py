"""
channels/models.py — Transporte de mensajería del subsistema agente (É-F0).

Dominio FRONTERA (plan v1.1, docs/whatsapp-agent-implementation-plan.md):
ningún módulo de dominio importa channels; channels solo conoce
organizations (tenancy), users (autor humano de salientes) y
agent.Conversation (string ref, para el hilo). El "cerebro" conversacional
vive en apps.agent.

Diseño v1.1 §7-C1/C4: UNA tabla Message para entrantes y salientes, y el
inbox ES la cola (sin tabla de cola aparte) — el worker toma conversaciones
con mensajes `direction='in', status='pending'` vía FOR UPDATE SKIP LOCKED;
el outbox son los `direction='out', status='pending'`.
"""
from django.db import models

from apps.core.models import OrganizationalModel


class ChannelAccount(OrganizationalModel):
    """Un número/canal de una clínica.

    El enrutamiento número→organización es EL control anti cross-tenant del
    subsistema (riesgo R1): `external_account_id` es unique GLOBAL y la
    organización de una conversación se fija UNA sola vez al crearla — jamás
    se re-deriva ni la decide el LLM.
    """

    CHANNEL_WHATSAPP = 'whatsapp'
    CHANNEL_CHOICES = (
        (CHANNEL_WHATSAPP, 'WhatsApp'),
    )

    STATUS_ACTIVE = 'active'
    STATUS_PAUSED = 'paused'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, 'Activo'),
        (STATUS_PAUSED, 'Pausado'),
    )

    channel_type = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, default=CHANNEL_WHATSAPP,
    )
    # phone_number_id del proveedor (Meta Cloud API). Unique GLOBAL: un
    # número pertenece a exactamente una organización, por constraint.
    external_account_id = models.CharField(max_length=64, unique=True)
    display_number = models.CharField(max_length=20, blank=True, default='')
    # NOMBRE de la variable de entorno que contiene el access token del
    # proveedor (fallback). El token puede vivir cifrado en DB (abajo) para
    # rotarlo desde la UI; si no hay token en DB, se usa esta env var.
    provider_credentials_ref = models.CharField(
        max_length=100, default='WHATSAPP_ACCESS_TOKEN',
    )
    # Access token CIFRADO en reposo (Fernet, ver channels/crypto.py). Permite
    # rotar el token temporal de Meta desde /inbox sin tocar .env.prod ni
    # reiniciar. Write-only por API (nunca se devuelve en claro). Vacío =
    # se usa el fallback de env (`provider_credentials_ref`).
    access_token_encrypted = models.TextField(blank=True, default='')
    # Últimos 4 chars del token (no sensible) — para mostrar "…1234" en la UI
    # sin descifrar.
    access_token_last4 = models.CharField(max_length=4, blank=True, default='')
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'status']),
        ]

    def __str__(self):
        return f"ChannelAccount<{self.channel_type} {self.display_number or self.external_account_id}>"

    def set_access_token(self, plaintext):
        """Cifra y guarda el token (o lo limpia). NO hace save()."""
        from .crypto import encrypt_secret
        plaintext = (plaintext or '').strip()
        self.access_token_encrypted = encrypt_secret(plaintext)
        self.access_token_last4 = plaintext[-4:] if plaintext else ''

    def get_access_token(self):
        """Token en claro desde DB (cifrado), o '' si no hay."""
        from .crypto import decrypt_secret
        return decrypt_secret(self.access_token_encrypted)

    @property
    def has_db_token(self):
        return bool(self.access_token_encrypted)


class Message(OrganizationalModel):
    """Mensaje de canal — entrantes y salientes en una sola tabla (v1.1 §7-C1).

    Cola y outbox son filtros sobre `status` (§7-C4):
      - inbound:  pending → processed | discarded
      - outbound: pending → sent → delivered → read, o failed (con reintentos)

    Dedup de reintentos del proveedor: unique parcial por
    (channel_account, external_message_id) SOLO inbound — patrón espejo de
    Payment.idempotency_key (ADR p27). El wamid de WhatsApp es único y
    estable; en salientes el proveedor lo asigna al enviar (no participa
    del constraint).

    PII: el cuerpo vive SOLO aquí — nunca en logs ni Sentry (regla R15 del
    doc de arquitectura).
    """

    DIRECTION_IN = 'in'
    DIRECTION_OUT = 'out'
    DIRECTION_CHOICES = (
        (DIRECTION_IN, 'Entrante'),
        (DIRECTION_OUT, 'Saliente'),
    )

    AUTHOR_CLIENT = 'client'
    AUTHOR_AGENT = 'agent'
    AUTHOR_HUMAN = 'human_staff'
    AUTHOR_SYSTEM = 'system'
    AUTHOR_CHOICES = (
        (AUTHOR_CLIENT, 'Cliente'),
        (AUTHOR_AGENT, 'Agente'),
        (AUTHOR_HUMAN, 'Staff'),
        (AUTHOR_SYSTEM, 'Sistema'),
    )

    PAYLOAD_TEXT = 'text'
    PAYLOAD_CHOICES = (
        (PAYLOAD_TEXT, 'Texto'),
        ('audio', 'Audio'),
        ('image', 'Imagen'),
        ('document', 'Documento'),
        ('location', 'Ubicación'),
        ('sticker', 'Sticker'),
        ('button_reply', 'Respuesta de botón'),
        ('other', 'Otro'),
    )

    STATUS_PENDING = 'pending'
    STATUS_PROCESSED = 'processed'
    STATUS_DISCARDED = 'discarded'
    STATUS_SENT = 'sent'
    STATUS_DELIVERED = 'delivered'
    STATUS_READ = 'read'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        # inbound
        (STATUS_PENDING, 'Pendiente'),
        (STATUS_PROCESSED, 'Procesado'),
        (STATUS_DISCARDED, 'Descartado'),
        # outbound
        (STATUS_SENT, 'Enviado'),
        (STATUS_DELIVERED, 'Entregado'),
        (STATUS_READ, 'Leído'),
        (STATUS_FAILED, 'Fallido'),
    )

    channel_account = models.ForeignKey(
        ChannelAccount, on_delete=models.PROTECT, related_name='messages',
    )
    # String ref: evita import circular channels↔agent. Nullable solo para
    # payloads que no logran resolver conversación (media huérfana, errores
    # de parseo); el flujo normal la asigna al persistir (PR-4).
    conversation = models.ForeignKey(
        'agent.Conversation', on_delete=models.PROTECT,
        null=True, blank=True, related_name='messages',
    )
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    author_type = models.CharField(max_length=12, choices=AUTHOR_CHOICES)
    # Staff que respondió desde la bandeja (solo author_type='human_staff').
    human_author = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    payload_type = models.CharField(
        max_length=15, choices=PAYLOAD_CHOICES, default=PAYLOAD_TEXT,
    )
    body = models.TextField(blank=True, default='')
    # wamid (inbound: llega en el webhook; outbound: lo asigna el proveedor
    # al enviar). Nullable — el unique parcial exige not-null + direction in.
    external_message_id = models.CharField(
        max_length=128, null=True, blank=True,
    )
    # Metadata cruda del proveedor (sin media binaria). Solo diagnóstico.
    raw_metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )
    # Entrega de salientes (reintentos exponenciales del sender, PR-5).
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=200, blank=True, default='')
    # Drain-on-pickup (v1.1 §7-C9): el worker no toma mensajes con
    # available_at futuro — delay fijo barato en vez de debounce con timers.
    available_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            # Dedup de reintentos del webhook (R5): el mismo wamid entrante
            # solo puede existir una vez por canal.
            models.UniqueConstraint(
                fields=['channel_account', 'external_message_id'],
                condition=models.Q(direction='in')
                & models.Q(external_message_id__isnull=False),
                name='message_unique_inbound_wamid',
            ),
        ]
        indexes = [
            # Transcript de una conversación (bandeja).
            models.Index(fields=['organization', 'conversation', 'created_at']),
            # Cola del worker (inbox pendiente) y outbox del sender.
            models.Index(fields=['direction', 'status']),
        ]

    def __str__(self):
        return f"Message<{self.direction} {self.status} conv={self.conversation_id}>"
