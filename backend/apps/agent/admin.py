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
        'execution_stage', 'result_code', 'executed_at', 'execution_gate', 'appointment_effect')

    @admin.display(description='Execution gate')
    def execution_gate(self, obj):
        from .operation_execution import REGISTRY, _gate
        entry = REGISTRY.get(obj.operation_kind)
        return _gate(obj, entry) or 'OPEN (guard required)' if entry else 'CLOSED'

    @admin.display(description='Appointment / reconciliación')
    def appointment_effect(self, obj):
        if obj.operation_kind != 'CREATE_APPOINTMENT':
            return 'No adapter'
        from .appointment_execution import CreateAppointmentAdapter
        result = CreateAppointmentAdapter().reconcile(obj, None)
        return {'ABSENT': 'None', 'SUCCEEDED': 'Linked / reconciled',
                'UNCERTAIN': 'Linked / evidence mismatch; inspection required'}.get(result.status, 'UNCERTAIN')

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
