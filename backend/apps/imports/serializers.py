from rest_framework import serializers

from .models import ImportJob
from .normalization import FIELD_CATALOG, suggest_mapping

_SAMPLE_LIMIT = 10


class ImportJobSerializer(serializers.ModelSerializer):
    """Lectura de un ImportJob. Las escrituras van por las acciones dedicadas
    (mapping/validate/commit), nunca por PATCH directo del modelo."""

    sample_rows = serializers.SerializerMethodField()
    row_count = serializers.SerializerMethodField()
    field_catalog = serializers.SerializerMethodField()
    suggested_mapping = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            'public_id', 'entity_type', 'status', 'original_filename',
            'source_columns', 'sample_rows', 'row_count',
            'mapping', 'suggested_mapping', 'field_catalog',
            'dedup_strategy', 'result', 'created_at',
        ]
        read_only_fields = fields

    def get_sample_rows(self, obj):
        return (obj.rows or [])[:_SAMPLE_LIMIT]

    def get_row_count(self, obj):
        return len(obj.rows or [])

    def get_field_catalog(self, obj):
        return FIELD_CATALOG.get(obj.entity_type, [])

    def get_suggested_mapping(self, obj):
        # Si ya hay mapping confirmado, devolverlo; si no, sugerir.
        if obj.mapping:
            return obj.mapping
        return suggest_mapping(obj.source_columns or [], obj.entity_type)


class ImportJobListSerializer(serializers.ModelSerializer):
    """Versión liviana para el listado (sin filas)."""
    row_count = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            'public_id', 'entity_type', 'status', 'original_filename',
            'row_count', 'dedup_strategy', 'result', 'created_at',
        ]
        read_only_fields = fields

    def get_row_count(self, obj):
        return len(obj.rows or [])
