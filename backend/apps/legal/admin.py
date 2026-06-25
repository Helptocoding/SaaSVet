from django.contrib import admin

from .models import LegalAcceptance, LegalDocument


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    """Catálogo de versiones. Promover is_current = sync manual con la landing."""
    list_display = ('doc_type', 'version', 'effective_date', 'is_current', 'landing_url')
    list_filter = ('doc_type', 'is_current')
    search_fields = ('version', 'landing_url')


@admin.register(LegalAcceptance)
class LegalAcceptanceAdmin(admin.ModelAdmin):
    """Append-only: solo lectura desde el admin (la corrección es otra aceptación)."""
    list_display = ('user', 'document', 'accepted_at', 'organization')
    list_filter = ('document__doc_type',)
    search_fields = ('user__username',)
    readonly_fields = ('user', 'document', 'accepted_at', 'ip', 'user_agent', 'organization')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
