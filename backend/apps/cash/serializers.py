from rest_framework import serializers

from .models import CashMovement, CashSession


class CashSessionSerializer(serializers.ModelSerializer):
    """
    Solo lectura. Expone únicamente `public_id` (ADR p24 — modelo público nuevo
    no expone `id`+`public_id`). Los actores se exponen por nombre, no por PK de
    User (sin leak de PKs internos).
    """
    opened_by_name = serializers.SerializerMethodField()
    closed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CashSession
        fields = [
            'public_id', 'status',
            'opening_float',
            'opened_at', 'opened_by_name',
            'closed_at', 'closed_by_name',
            'expected_cash', 'counted_cash', 'difference',
            'closed_snapshot', 'report_schema_version',
            'notes', 'created_at',
        ]
        read_only_fields = fields

    def _full_name(self, user):
        if not user:
            return ''
        return f"{user.first_name} {user.last_name}".strip() or user.username

    def get_opened_by_name(self, obj):
        return self._full_name(obj.opened_by)

    def get_closed_by_name(self, obj):
        return self._full_name(obj.closed_by)


class CashMovementSerializer(serializers.ModelSerializer):
    """
    Solo lectura (ADR p39): la escritura pasa por el view → service
    (register_cash_movement); append-only, sin PATCH/DELETE.
    """
    actor_name = serializers.SerializerMethodField()
    movement_type_display = serializers.CharField(
        source='get_movement_type_display', read_only=True,
    )

    class Meta:
        model = CashMovement
        fields = [
            'public_id', 'movement_type', 'movement_type_display',
            'amount', 'reason', 'occurred_at', 'actor_name',
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if not obj.actor:
            return ''
        return f"{obj.actor.first_name} {obj.actor.last_name}".strip() or obj.actor.username
