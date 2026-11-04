from django.contrib import admin
from apps.core.admin import TenantAwareAdmin
from .models import Product, Presentation, StockMovement, MedicalRecordProduct


@admin.register(Product)
class ProductAdmin(TenantAwareAdmin):
    list_display = ['name', 'internal_code', 'category', 'requires_prescription', 'is_active', 'organization']
    list_filter = ['is_active', 'category', 'organization']
    search_fields = ['name', 'internal_code']


@admin.register(Presentation)
class PresentationAdmin(TenantAwareAdmin):
    list_display = ['product', 'name', 'base_unit', 'stock', 'min_stock', 'sale_price', 'organization']
    list_filter = ['base_unit', 'organization']
    search_fields = ['name', 'product__name']
    # quantity es el alias legacy; el admin edita solo el factor comercial.
    readonly_fields = ['product', 'quantity']

    def save_model(self, request, obj, form, change):
        if not change or 'conversion_factor' in form.changed_data:
            obj.quantity = obj.conversion_factor
        super().save_model(request, obj, form, change)


@admin.register(StockMovement)
class StockMovementAdmin(TenantAwareAdmin):
    list_display = ['presentation', 'movement_type', 'quantity', 'reason', 'created_by', 'created_at']
    list_filter = ['movement_type', 'organization']
    readonly_fields = ['created_at']


@admin.register(MedicalRecordProduct)
class MedicalRecordProductAdmin(TenantAwareAdmin):
    list_display = ['medical_record', 'presentation', 'quantity']
