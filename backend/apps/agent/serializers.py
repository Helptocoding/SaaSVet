"""
agent/serializers.py — Bandeja del agente (É-F0 PR-6).

Regla ADR p24 (guard `test_public_id_dual_exposure_audit`): serializers
NUEVOS de modelos públicos exponen SOLO `public_id`, jamás `id`+`public_id`.
`Message` es modelo interno (sin public_id) → expone su `id` entero para
keys de React, consistente con InvoiceItem/VitalSigns (ADR p18).
"""
import unicodedata

from rest_framework import serializers

from apps.channels.models import Message
from apps.core.validators import is_valid_mx_phone

from .models import AgentSettings, Conversation

# Claves que YA tienen campo propio en la configuración de clínica (ADR p53).
# Aceptarlas aquí recrearía la segunda fuente de verdad que se eliminó al
# retirar `business_hours`: el ADMIN edita esto en Configuración → Clínica y
# el agente lo lee de ahí (`clinic_context.clinic_facts`).
RESERVED_FACT_KEYS = {
    'horario', 'horarios', 'telefono', 'tel', 'whatsapp', 'correo', 'email',
    'direccion', 'domicilio', 'ubicacion', 'mapa', 'maps', 'google_maps',
    'sitio_web', 'web', 'pagina', 'indicaciones', 'como_llegar',
}


def _normalize_fact_key(key):
    text = unicodedata.normalize('NFD', str(key or '').lower().strip())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.replace(' ', '_')


class MessageSerializer(serializers.ModelSerializer):
    human_author_name = serializers.SerializerMethodField()
    client_message_id = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'direction', 'author_type', 'payload_type', 'body',
            'status', 'failure_reason', 'created_at', 'human_author_name',
            'client_message_id',
        ]

    def get_human_author_name(self, obj):
        if obj.human_author_id is None:
            return None
        return obj.human_author.get_full_name() or obj.human_author.username

    def get_client_message_id(self, obj):
        """Correlación pública del composer; nunca expone claves del bot."""
        if (
            obj.direction != Message.DIRECTION_OUT
            or obj.author_type != Message.AUTHOR_HUMAN
        ):
            return None
        return obj.idempotency_key or None


class ConversationListSerializer(serializers.ModelSerializer):
    contact_display_name = serializers.CharField(
        source='contact.display_name', read_only=True,
    )
    contact_phone = serializers.CharField(
        source='contact.phone_normalized', read_only=True,
    )
    contact_verification = serializers.CharField(
        source='contact.verification_level', read_only=True,
    )
    # Procedencia del vínculo contacto→cliente: 'family_challenge' marca un
    # vínculo familiar secundario (revocable en bandeja, PR-17b).
    linked_via = serializers.CharField(
        source='contact.linked_via', read_only=True,
    )
    # Nombre del Cliente registrado (si la identidad matcheó a un Owner) —
    # ayuda a recepción a reconocer a quién atiende.
    owner_name = serializers.SerializerMethodField()
    claimed_by_name = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()
    has_unanswered = serializers.SerializerMethodField()
    # Escalada abierta (É-F3 W0-4): sin esto la bandeja pintaba igual una
    # urgencia clínica y una duda de horarios.
    handoff_priority = serializers.SerializerMethodField()
    handoff_reason = serializers.SerializerMethodField()
    handoff_detail = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'public_id', 'state', 'created_at', 'last_inbound_at',
            'last_activity_at', 'closed_at',
            'contact_display_name', 'contact_phone', 'contact_verification',
            'linked_via', 'owner_name', 'claimed_by_name',
            'last_message_preview', 'has_unanswered',
            'handoff_priority', 'handoff_reason', 'handoff_detail',
        ]

    def _open_handoff(self, obj):
        prefetched = getattr(obj, 'open_handoffs', None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return obj.handoffs.filter(resolved_at__isnull=True).first()

    def get_handoff_priority(self, obj):
        handoff = self._open_handoff(obj)
        return handoff.priority if handoff else None

    def get_handoff_reason(self, obj):
        handoff = self._open_handoff(obj)
        return handoff.reason_code if handoff else None

    def get_handoff_detail(self, obj):
        """El motivo FINO (`goal_stalled`, `commit_failed`, `owner_exists`…).

        `reason_code` clasifica para la máquina; `reason_detail` es el que le
        dice algo a una persona. Publicar solo el primero dejaba a la bandeja
        eligiendo entre no mostrar nada o mostrar «baja confianza», que en
        recepción no significa nada.
        """
        handoff = self._open_handoff(obj)
        return handoff.reason_detail if handoff else None

    def get_owner_name(self, obj):
        if obj.contact.owner_id is None:
            return None
        return obj.contact.owner.name

    def get_claimed_by_name(self, obj):
        if obj.claimed_by_id is None:
            return None
        return obj.claimed_by.get_full_name() or obj.claimed_by.username

    def _last_message(self, obj):
        # Prefetched por la view como `latest_messages` (lista de ≤1).
        prefetched = getattr(obj, 'latest_messages', None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return obj.messages.order_by('-created_at', '-id').first()

    def get_last_message_preview(self, obj):
        message = self._last_message(obj)
        if message is None:
            return ''
        if message.payload_type != Message.PAYLOAD_TEXT and not message.body:
            return f"[{message.get_payload_type_display()}]"
        return message.body[:120]

    def get_has_unanswered(self, obj):
        message = self._last_message(obj)
        return bool(message and message.direction == Message.DIRECTION_IN)


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000, allow_blank=False)


class AgentSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentSettings
        fields = ['enabled', 'faq_facts']

    def validate_enabled(self, value):
        """No debe existir `enabled=True` + `Organization.phone` vacío/inválido.

        NO es UX, es seguridad. El agente atiende urgencias: la plantilla de
        urgencia (`clinic_context.clinic_phone`) le dice al cliente "acude de
        inmediato a la clínica" y, sin teléfono, sin número al que llamar. Ese
        estado no debe ser alcanzable — independientemente de si el ADMIN pasó
        por el onboarding nuevo o venía de antes.

        División de responsabilidades: el onboarding EDUCA (te lleva al dato al
        arrancar), este gate GARANTIZA (impide el estado peligroso). El HORARIO
        no entra: se siembra por defecto al crear la org, así que "tiene horario"
        siempre es verdadero y bloquear sobre eso no protegería de nada.
        """
        if not value:
            return value
        org = getattr(self.instance, 'organization', None)
        if org is None or not is_valid_mx_phone(getattr(org, 'phone', '')):
            raise serializers.ValidationError(
                "Antes de activar las respuestas automáticas, captura el teléfono "
                "de la clínica en Configuración → Clínica. El asistente lo necesita "
                "para decirle a un cliente a dónde llamar en una urgencia."
            )
        return value

    def validate_faq_facts(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Debe ser un objeto clave→texto.")
        if len(value) > 20:
            raise serializers.ValidationError("Máximo 20 datos de FAQ.")
        for key, text in value.items():
            if _normalize_fact_key(key) in RESERVED_FACT_KEYS:
                raise serializers.ValidationError(
                    f"'{key}' se configura en Configuración → Clínica, no aquí."
                )
            if not isinstance(text, str) or len(text) > 500:
                raise serializers.ValidationError(
                    f"{key}: cada dato es texto de máximo 500 caracteres."
                )
        return value


class ThreadSerializer(serializers.Serializer):
    """Una fila de la bandeja AGRUPADA: la persona, no el episodio.

    En producción un solo contacto acumuló 19 conversaciones y la bandeja las
    mostraba como 19 filas. La conversación sigue existiendo —de ella cuelgan
    métricas, claim, hand-off y compromisos— pero recepción ve una fila por
    `(contacto, cuenta)`.

    El estado, el claim y la escalada que se muestran son los de la **sesión
    vigente**. Si no hay ninguna abierta, la fila está ARCHIVADA: se ve, se lee,
    y no ofrece acciones de respuesta — escribir crea sesión por el camino
    normal, cuando el cliente vuelva a escribir.
    """
    contact_public_id = serializers.UUIDField()
    channel_account_public_id = serializers.UUIDField()
    contact_display_name = serializers.CharField()
    contact_phone = serializers.CharField()
    contact_verification = serializers.CharField()
    linked_via = serializers.CharField()
    owner_name = serializers.CharField(allow_null=True)
    # Sesión vigente (o `null` si el hilo está archivado).
    conversation_public_id = serializers.UUIDField(allow_null=True)
    state = serializers.CharField(allow_null=True)
    claimed_by_name = serializers.CharField(allow_null=True)
    handoff_priority = serializers.CharField(allow_null=True)
    handoff_reason = serializers.CharField(allow_null=True)
    handoff_detail = serializers.CharField(allow_null=True)
    # Hilo completo, no solo la sesión: es lo que hace útil la agrupación.
    last_activity_at = serializers.DateTimeField(allow_null=True)
    last_message_preview = serializers.CharField(allow_null=True)
    has_unanswered = serializers.BooleanField()
    session_count = serializers.IntegerField()


class SessionSerializer(serializers.ModelSerializer):
    """Un episodio dentro del hilo. Para recorrer el historial de la persona."""
    claimed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'public_id', 'state', 'created_at', 'closed_at', 'close_reason',
            'last_activity_at', 'claimed_by_name',
        ]

    def get_claimed_by_name(self, obj):
        if obj.claimed_by_id is None:
            return None
        return obj.claimed_by.get_full_name() or obj.claimed_by.username
