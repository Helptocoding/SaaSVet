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

    # Vacunas (É0-PR1 — fix del gap RBAC). Las views declaran
    # resource_name="vaccinerecord" desde Día 6/ADR p18, pero el catálogo
    # nunca tuvo estos códigos → VET/ASSISTANT con UserRole en DB recibían
    # RBAC_DENIED en /api/vaccines/ (solo ADMIN pasaba vía *.*).
    # Sin "vaccinerecord.destroy": DELETE está bloqueado en la view
    # (NOM-007/046, registro legal — ADR p16).
    "vaccinerecord.list",
    "vaccinerecord.retrieve",
    "vaccinerecord.create",
    "vaccinerecord.update",

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

    # Importador CSV/Excel (migración de clínicas). v1: solo ADMIN (vía *.*).
    # No se agregan a VET/ASSISTANT — migración de datos = operación sensible.
    "import.list",
    "import.retrieve",
    "import.create",
    "import.commit",

    # Bandeja del agente conversacional (É-F0 PR-6, decisión Q13 de la spec).
    # La bandeja expone transcripts (PII conversacional) → permisos propios,
    # no colgados de appointment.*. claim cubre también cerrar/liberar
    # (gestión de estado de la conversación); config = kill switch + horario
    # + FAQ (solo ADMIN vía *.*).
    "agentinbox.view",
    "agentinbox.claim",
    "agentinbox.send",
    "agentinbox.config",
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
        "vaccinerecord.list", "vaccinerecord.retrieve",
        "vaccinerecord.create", "vaccinerecord.update",
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
        # Bandeja del agente: el VET puede VER conversaciones (contexto
        # clínico), no operarlas — la recepción es de ASSISTANT/ADMIN (Q13).
        "agentinbox.view",
    ],

    # Asistente / Recepcionista
    "ASSISTANT": [
        "appointment.list", "appointment.retrieve", "appointment.create",
        "appointment.update", "appointment.destroy",
        "medicalrecord.list", "medicalrecord.retrieve",
        "medicalrecord.vitals.list", "medicalrecord.summary.retrieve",
        "vaccinerecord.list", "vaccinerecord.retrieve",
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
        # Bandeja del agente (Q13): la recepcionista atiende WhatsApp —
        # ver, reclamar/cerrar y responder. config (kill switch) es ADMIN.
        "agentinbox.view", "agentinbox.claim", "agentinbox.send",
    ],

    # Agente virtual — service account del subsistema conversacional
    # (ADR p51). Menor privilegio POR FASE: F1 = solo las lecturas que
    # respaldan sus tools (spec congelada: whatsapp-agent-functional-spec
    # §9). F2 añadirá appointment.create/update editando esta lista (el
    # seed propaga en el siguiente deploy). PROHIBIDO acercarlo a
    # invoice/billing/cash/medicalrecord/prescription/staff/import.
    "AGENT": [
        "appointment.list", "appointment.retrieve",
        # É-F2: escritura de agenda (crear/confirmar/cancelar/reagendar). NO
        # gana appointment.destroy (el agente cancela vía /status/, que deja
        # lineage de auditoría; el DELETE es de staff). Sigue SIN billing,
        # medicalrecord, prescription, cash, staff, import.
        "appointment.create", "appointment.update",
        "patient.list", "patient.retrieve",
        # É-F2: alta de cliente+mascota vía create-with-patient (INT-21).
        "patient.create",
        "owner.list", "owner.retrieve", "owner.create",
        "vaccinerecord.list", "vaccinerecord.retrieve",
        "service.list", "service.retrieve",
        "inventory.list", "inventory.retrieve",
    ],
}
