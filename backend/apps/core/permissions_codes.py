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
    "invoice.pay",
    "invoice.post_unpaid",
    "invoice.replace_waive",
    "invoice.replace",
    "invoice.replace_adjust",
    "invoice.replace_manage",
    "invoice.void_terminal",
    "billing.clinical_charge.reprice",
    "checkout.prescription_decide",
    "checkout.estimate.issue",
    "checkout.dispute.open",
    "checkout.dispute.resolve",
    "collection.resolve",
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
    "organization.retrieve",
    "organization.update",

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

    # Centro de notificaciones (Rev.5: lectura por capacidad).
    "notification.list",
    "notification.retrieve",
    "notification.seen",
    # Bandeja del agente conversacional (É-F0 PR-6, decisión Q13 de la spec).
    # La bandeja expone transcripts (PII conversacional) → permisos propios,
    # no colgados de appointment.*. claim cubre también cerrar/liberar
    # (gestión de estado de la conversación); config = kill switch + horario
    # + FAQ (solo ADMIN vía *.*).
    "agentinbox.view",
    "agentinbox.claim",
    "agentinbox.send",
    "agentinbox.config",
    # FLUJO-C (ADR p57, F4): verificar la identidad de un contacto y autorizar
    # su vínculo con un expediente EXISTENTE. Código propio, no `config`:
    # verificar identidad es una función de mostrador, no de administración del
    # canal — delegarla en una recepcionista de confianza no debe entregarle
    # también el kill switch del agente. Y simetría con `reset_contact_identity`
    # (desvincular, ADMIN): vincular es la operación inversa y no puede ser
    # menos exigente. Solo ADMIN de entrada.
    "agentinbox.identity_verify",
]

# ---------------------------------------------------------------------------
# Política de cada código frente al comodín "*.*" (auditoría run-1, H-1)
# ---------------------------------------------------------------------------
# Todo código del catálogo debe estar en exactamente un grupo; un test falla si
# aparece uno sin clasificar, así que añadir un código obliga a decidir si el ADMIN
# de clínica debe recibirlo por el comodín.
#
#   ADMIN_WILDCARD_ORDINARY: operación ordinaria de la clínica.
#   ADMIN_WILDCARD_SENSITIVE: el ADMIN los recibe por contrato, pero mueven dinero,
#     acceso o identidad. Es una lista revisada, no una restricción en ejecución.
#   WILDCARD_EXCLUDED: el comodín NO los concede (`_is_allowed`): exigen asignación
#     explícita al rol. Es donde va un código exclusivo de plataforma. Un superuser
#     sigue pasando, porque no se evalúa por comodín. Hoy vacío: ningún código actual
#     es exclusivo de plataforma, ya que esas vistas usan `IsPlatformOperator`.
ADMIN_WILDCARD_ORDINARY = frozenset({
    "appointment.list", "appointment.retrieve", "appointment.create",
    "appointment.create_walkin", "appointment.update", "appointment.destroy",
    "medicalrecord.list", "medicalrecord.retrieve", "medicalrecord.create",
    "medicalrecord.update", "medicalrecord.close", "medicalrecord.vitals.create",
    "medicalrecord.vitals.list", "medicalrecord.summary.retrieve",
    "vaccinerecord.list", "vaccinerecord.retrieve", "vaccinerecord.create",
    "vaccinerecord.update",
    "invoice.list", "invoice.retrieve", "invoice.create", "invoice.pay",
    "checkout.prescription_decide", "checkout.estimate.issue", "checkout.dispute.open",
    "billing.rx_dispense",
    "service.list", "service.retrieve", "service.create", "service.update", "service.destroy",
    "patient.list", "patient.retrieve", "patient.create", "patient.update", "patient.destroy",
    "owner.list", "owner.retrieve", "owner.create", "owner.update", "owner.destroy",
    "inventory.list", "inventory.retrieve", "inventory.create", "inventory.update",
    "prescription.list", "prescription.retrieve", "prescription.create", "prescription.destroy",
    "staff.list", "organization.retrieve",
    "dashboard.view", "dashboard.summary",
    "cashsession.list", "cashsession.retrieve", "cashsession.open", "cashsession.close",
    "cashmovement.list", "cashmovement.create",
    "import.list", "import.retrieve", "import.create",
    "notification.list", "notification.retrieve", "notification.seen",
    "agentinbox.view", "agentinbox.claim", "agentinbox.send",
})
ADMIN_WILDCARD_SENSITIVE = frozenset({
    "invoice.destroy", "invoice.post_unpaid", "invoice.replace", "invoice.replace_adjust",
    "invoice.replace_manage", "invoice.replace_waive", "invoice.void_terminal",
    "billing.clinical_charge.reprice", "billing.refund",
    "checkout.dispute.resolve", "collection.resolve",
    "staff.create", "staff.destroy", "staff.reset_password",
    "organization.update", "import.commit", "dashboard.financial.view",
    "agentinbox.config", "agentinbox.identity_verify",
})
WILDCARD_EXCLUDED = frozenset()

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
        "invoice.list", "invoice.retrieve", "invoice.create", "checkout.dispute.open",
        "billing.rx_dispense",
        "service.list", "service.retrieve",
        "staff.list",
        "dashboard.view",
        "dashboard.summary",
        "notification.list", "notification.retrieve", "notification.seen",
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
        "invoice.list", "invoice.retrieve", "invoice.create", "invoice.pay",
        "checkout.prescription_decide", "checkout.estimate.issue", "checkout.dispute.open",
        "service.list", "service.retrieve",
        "staff.list",
        "dashboard.view",
        "dashboard.summary",
        "notification.list", "notification.retrieve", "notification.seen",
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
