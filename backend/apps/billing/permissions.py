"""
billing/permissions.py — Permisos de facturación

Delega al sistema RBAC central (HybridPermission via make_permission).
Regla 3: acciones custom SIEMPRE definen required_permission.
"""
from apps.core.permissions import make_permission

# Clases listas para usar en @permission_classes
CanPayInvoice = make_permission("invoice.pay")
