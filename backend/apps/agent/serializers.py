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

    class Meta:
        model = Message
        fields = [
            'id', 'direction', 'author_type', 'payload_type', 'body',
            'status', 'failure_reason', 'created_at', 'human_author_name',
        ]

    def get_human_author_name(self, obj):
        if obj.human_author_id is None:
            return None
        return obj.human_author.get_full_name() or obj.human_author.username


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

    class Meta:
        model = Conversation
        fields = [
            'public_id', 'state', 'created_at', 'last_inbound_at',
            'last_activity_at', 'closed_at',
            'contact_display_name', 'contact_phone', 'contact_verification',
            'linked_via', 'owner_name', 'claimed_by_name',
            'last_message_preview', 'has_unanswered',
            'handoff_priority', 'handoff_reason',
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
