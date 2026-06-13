"""
core/permissions_codes.py — Fuente única de verdad de permisos RBAC
====================================================================

REGLAS:
  - Este archivo es la única fuente de verdad para permisos.
  - Formato: "resource.action"
  - PERMISSIONS define los permisos estáticos por rol.
  - El seed valida que PERMISSION_CODES == set de todos los permisos en PERMISSIONS.
  - Nunca modificar PERMISSIONS sin actualizar PERMISSION_CODES primero.
  - Wildcard global es "*.*", no "*".
"""

# ---------------------------------------------------------------------------
# Catálogo de permisos válidos
# ---------------------------------------------------------------------------
PERMISSION_CODES = [
    # Citas
    "appointment.list",
    "appointment.retrieve",
    "appointment.create",
    # Granular permiso para walk-ins (creacion de citas en modo walk-in)
    "appointment.create_walkin",
    "appointment.update",
    "appointment.destroy",

    # Historial clínico
    "medicalrecord.list",
    "medicalrecord.retrieve",
    "medicalrecord.create",
    "medicalrecord.update",
    "medicalrecord.close",
    "medicalrecord.vitals.create",
    "medicalrecord.vitals.list",
    "medicalrecord.summary.retrieve",

    # Facturas
    "invoice.list",
    "invoice.retrieve",
    "invoice.create",
    "invoice.destroy",
    "invoice.confirm",
    "invoice.pay",
    "invoice.cancel",
    # Dispensar producto con receta en venta directa (ADR p26 — boundary alto-trust)
    "billing.rx_dispense",
    # Emitir nota de crédito / devolución (ADR p29 — alto-trust; solo ADMIN por default)
    "billing.refund",

    # Servicios (catálogo de facturación — Configuración)
    "service.list",
    "service.retrieve",
    "service.create",
    "service.update",
    "service.destroy",

    # Pacientes (mascotas)
    "patient.list",
    "patient.retrieve",
    "patient.create",
    "patient.update",
    "patient.destroy",

    # Propietarios
    "owner.list",
    "owner.retrieve",
    "owner.create",
    "owner.update",
    "owner.destroy",

    # Inventario
    "inventory.list",
    "inventory.retrieve",
    "inventory.create",
    "inventory.update",

    # Recetas
    "prescription.list",
    "prescription.retrieve",
    "prescription.create",
    "prescription.destroy",

    # Equipo (gestión de usuarios internos)
    "staff.list",
    "staff.create",
    "staff.destroy",
    # ADR p21: admin reset de password de staff. Solo ADMIN de la org.
    "staff.reset_password",

    # Organización
    "organization.list",
    "organization.retrieve",
    "organization.update",
    "organization.create",

    # Dashboard
    "dashboard.view",
    "dashboard.financial.view",
    "dashboard.summary",

    # Caja — turno / cierre Z (ADR p28)
    "cashsession.list",
    "cashsession.retrieve",
    "cashsession.open",
    "cashsession.close",
    # Caja — movimientos manuales: entrada / retiro / gasto (ADR p39)
    "cashmovement.list",
    "cashmovement.create",
]

# ---------------------------------------------------------------------------
# Permisos estáticos por rol (fallback cuando no hay roles en DB)
# ---------------------------------------------------------------------------
PERMISSIONS = {
    # Superadmin de plataforma
    "ADMIN_SAAS": ["*.*"],

    # Administrador de clínica
    "ADMIN": ["*.*"],

    # Veterinario
    "VET": [
        "appointment.list", "appointment.retrieve", "appointment.create",
        "appointment.update", "appointment.destroy",
        # walk-in granular
        "appointment.create_walkin",
        "medicalrecord.list", "medicalrecord.retrieve", "medicalrecord.create",
        "medicalrecord.update", "medicalrecord.close",
        "medicalrecord.vitals.create", "medicalrecord.vitals.list",
        "medicalrecord.summary.retrieve",
        "prescription.list", "prescription.retrieve", "prescription.create",
        "prescription.destroy",
        "patient.list", "patient.retrieve", "patient.create",
        "patient.update", "patient.destroy",
        "owner.list", "owner.retrieve", "owner.create",
        "owner.update", "owner.destroy",
        "inventory.list", "inventory.retrieve",
        "invoice.list", "invoice.retrieve", "invoice.create",
        "invoice.destroy", "invoice.confirm", "invoice.pay", "invoice.cancel",
        "billing.rx_dispense",
        "service.list", "service.retrieve",
        "staff.list",
        "dashboard.view",
        "dashboard.summary",
        # Caja (ADR p28)
        "cashsession.list", "cashsession.retrieve",
        "cashsession.open", "cashsession.close",
        # Movimientos manuales de caja (ADR p39)
        "cashmovement.list", "cashmovement.create",
    ],

    # Asistente / Recepcionista
    "ASSISTANT": [
        "appointment.list", "appointment.retrieve", "appointment.create",
        "appointment.update", "appointment.destroy",
        "medicalrecord.list", "medicalrecord.retrieve",
        "medicalrecord.vitals.list", "medicalrecord.summary.retrieve",
        "prescription.list", "prescription.retrieve",
        "patient.list", "patient.retrieve", "patient.create",
        "patient.update", "patient.destroy",
        "owner.list", "owner.retrieve", "owner.create",
        "owner.update", "owner.destroy",
        "inventory.list", "inventory.retrieve",
        "invoice.list", "invoice.retrieve", "invoice.create",
        "invoice.destroy", "invoice.confirm", "invoice.pay", "invoice.cancel",
        "service.list", "service.retrieve",
        "staff.list",
        "dashboard.view",
        "dashboard.summary",
        # Caja (ADR p28)
        "cashsession.list", "cashsession.retrieve",
        "cashsession.open", "cashsession.close",
        # Movimientos manuales de caja (ADR p39)
        "cashmovement.list", "cashmovement.create",
    ],
}
