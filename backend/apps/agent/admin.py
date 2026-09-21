"""Operational B7A inspection without sensitive definitions or editable authority."""
from django.contrib import admin
from django.utils.timesince import timesince
from .models import ConversationOperation


@admin.register(ConversationOperation)
class ConversationOperationAdmin(admin.ModelAdmin):
    list_display = ('operation_kind', 'proposal_stage', 'consent_state', 'execution_stage', 'created_at', 'age',
                    'expires_at', 'replaces_id', 'binding_revision', 'identity_revision', 'ownership_epoch')
    list_filter = ('operation_kind', 'consent_state', 'execution_state')
    fields = readonly_fields = ('operation_key', 'operation_kind', 'consent_state',
        'execution_state', 'created_at', 'updated_at', 'age', 'expires_at', 'replaces_id', 'binding_revision',
        'identity_revision', 'ownership_epoch', 'invalidation_reason', 'proposal_stage',
        'proposal_message_id', 'authorization_message_id', 'consent_decided_at',
        'execution_stage', 'result_code', 'executed_at')

    @admin.display(description='Ejecución / reconciliación')
    def execution_stage(self, obj):
        from .operation_execution import execution_stage
        return execution_stage(obj)

    @admin.display(description='Propuesta / emisión')
    def proposal_stage(self, obj):
        from .operation_proposals import proposal_stage
        return proposal_stage(obj)

    @admin.display(description='Age')
    def age(self, obj):
        return timesince(obj.created_at)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization_id=request.user.organization_id)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
