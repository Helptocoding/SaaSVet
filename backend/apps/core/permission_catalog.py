"""Catálogo legible de permisos (ADR p69): cada código del RBAC con su área, su
grupo y su acción en español.

Fuente única para mostrar y editar permisos en Equipo: el frontend lo recibe de
``GET /api/staff/permission-catalog/`` y no tiene copia. Una prueba exige que
cubra exactamente ``PERMISSION_CODES``: un código nuevo sin nombre aquí rompe la
suite, en vez de aparecer en pantalla como ``invoice.replace_adjust``.

Áreas: Clínica, Operación y Administración. Las lecturas que necesita todo el
equipo (panel de inicio, directorio, datos de la clínica, catálogo de servicios)
van en Operación, para que «Administración» signifique de verdad administrar.
"""
from apps.core.permissions_codes import PERMISSION_CODES

AREAS = (
    ('clinical', 'Clínica'),
    ('operation', 'Operación'),
    ('administration', 'Administración'),
)

# grupo → (área, etiqueta). El orden es el de presentación.
GROUPS = {
    'medical_records': ('clinical', 'Consultas'),
    'prescriptions': ('clinical', 'Recetas'),
    'vaccines': ('clinical', 'Vacunas'),
    'appointments': ('operation', 'Citas'),
    'owners': ('operation', 'Clientes'),
    'patients': ('operation', 'Mascotas'),
    'billing': ('operation', 'Cobros'),
    'cash': ('operation', 'Caja'),
    'inventory': ('operation', 'Inventario'),
    'whatsapp': ('operation', 'WhatsApp'),
    'general': ('operation', 'General'),
    'team': ('administration', 'Equipo'),
    'clinic_settings': ('administration', 'Configuración'),
    'services': ('administration', 'Servicios y precios'),
    'imports': ('administration', 'Importar datos'),
    'reports': ('administration', 'Reportes'),
}

# código → (grupo, acción)
PERMISSIONS = {
    'medicalrecord.list': ('medical_records', 'Ver consultas'),
    'medicalrecord.retrieve': ('medical_records', 'Ver el detalle de una consulta'),
    'medicalrecord.create': ('medical_records', 'Abrir consultas'),
    'medicalrecord.update': ('medical_records', 'Editar consultas'),
    'medicalrecord.close': ('medical_records', 'Cerrar y firmar consultas'),
    'medicalrecord.destroy': ('medical_records', 'Eliminar consultas'),
    'medicalrecord.vitals.create': ('medical_records', 'Registrar signos vitales'),
    'medicalrecord.vitals.list': ('medical_records', 'Ver signos vitales'),
    'medicalrecord.summary.retrieve': ('medical_records', 'Ver el resumen clínico'),
    'prescription.list': ('prescriptions', 'Ver recetas'),
    'prescription.retrieve': ('prescriptions', 'Ver el detalle de una receta'),
    'prescription.create': ('prescriptions', 'Emitir y firmar recetas'),
    'prescription.update': ('prescriptions', 'Editar recetas'),
    'prescription.destroy': ('prescriptions', 'Eliminar recetas'),
    'vaccinerecord.list': ('vaccines', 'Ver vacunas'),
    'vaccinerecord.retrieve': ('vaccines', 'Ver el detalle de una vacuna'),
    'vaccinerecord.create': ('vaccines', 'Registrar vacunas'),
    'vaccinerecord.update': ('vaccines', 'Editar vacunas'),
    'appointment.list': ('appointments', 'Ver la agenda'),
    'appointment.retrieve': ('appointments', 'Ver el detalle de una cita'),
    'appointment.create': ('appointments', 'Agendar citas'),
    'appointment.create_walkin': ('appointments', 'Registrar atenciones sin cita'),
    'appointment.update': ('appointments', 'Editar, mover y reasignar citas'),
    'appointment.destroy': ('appointments', 'Cancelar citas'),
    'owner.list': ('owners', 'Ver clientes'),
    'owner.retrieve': ('owners', 'Ver el detalle de un cliente'),
    'owner.create': ('owners', 'Dar de alta clientes'),
    'owner.update': ('owners', 'Editar clientes'),
    'owner.destroy': ('owners', 'Archivar clientes'),
    'patient.list': ('patients', 'Ver mascotas'),
    'patient.retrieve': ('patients', 'Ver la ficha de una mascota'),
    'patient.create': ('patients', 'Dar de alta mascotas'),
    'patient.update': ('patients', 'Editar mascotas'),
    'patient.destroy': ('patients', 'Archivar mascotas'),
    'invoice.list': ('billing', 'Ver cobros'),
    'invoice.retrieve': ('billing', 'Ver el detalle de un cobro'),
    'invoice.create': ('billing', 'Preparar cobros'),
    'invoice.destroy': ('billing', 'Eliminar cobros'),
    'invoice.pay': ('billing', 'Registrar pagos'),
    'invoice.post_unpaid': ('billing', 'Emitir cobros a crédito'),
    'invoice.replace': ('billing', 'Corregir cobros emitidos'),
    'invoice.replace_adjust': ('billing', 'Ajustar la corrección de un cobro'),
    'invoice.replace_manage': ('billing', 'Gestionar correcciones de cobros'),
    'invoice.replace_waive': ('billing', 'Condonar en una corrección'),
    'invoice.void_terminal': ('billing', 'Anular cobros'),
    'billing.clinical_charge.reprice': ('billing', 'Cambiar el precio de cargos clínicos'),
    'billing.rx_dispense': ('billing', 'Dispensar medicamentos con receta'),
    'billing.refund': ('billing', 'Hacer devoluciones'),
    'checkout.prescription_decide': ('billing', 'Decidir la receta en el cobro'),
    'checkout.estimate.issue': ('billing', 'Emitir presupuestos'),
    'checkout.dispute.open': ('billing', 'Abrir aclaraciones de cobro'),
    'checkout.dispute.resolve': ('billing', 'Resolver aclaraciones de cobro'),
    'collection.resolve': ('billing', 'Resolver cobranza'),
    'cashsession.list': ('cash', 'Ver turnos de caja'),
    'cashsession.retrieve': ('cash', 'Ver el detalle de un turno'),
    'cashsession.open': ('cash', 'Abrir caja'),
    'cashsession.close': ('cash', 'Cerrar caja'),
    'cashmovement.list': ('cash', 'Ver movimientos de caja'),
    'cashmovement.create': ('cash', 'Registrar entradas y salidas de caja'),
    'inventory.list': ('inventory', 'Ver inventario'),
    'inventory.retrieve': ('inventory', 'Ver el detalle de un producto'),
    'inventory.view': ('inventory', 'Ver existencias'),
    'inventory.create': ('inventory', 'Dar de alta productos y recibir mercancía'),
    'inventory.update': ('inventory', 'Editar productos y ajustar existencias'),
    'inventory.destroy': ('inventory', 'Eliminar productos'),
    'agentinbox.view': ('whatsapp', 'Ver conversaciones'),
    'agentinbox.claim': ('whatsapp', 'Tomar y asignar conversaciones'),
    'agentinbox.send': ('whatsapp', 'Responder a clientes'),
    'agentinbox.identity_verify': ('whatsapp', 'Verificar la identidad de un cliente'),
    'dashboard.view': ('general', 'Ver el panel de inicio'),
    'dashboard.summary': ('general', 'Ver los indicadores del día'),
    'notification.list': ('general', 'Ver notificaciones'),
    'notification.seen': ('general', 'Marcar notificaciones como vistas'),
    'staff.list': ('general', 'Ver el directorio del equipo'),
    'organization.list': ('general', 'Ver los datos de la clínica'),
    'organization.retrieve': ('general', 'Ver el detalle de la clínica'),
    'service.list': ('general', 'Ver el catálogo de servicios'),
    'service.retrieve': ('general', 'Ver el detalle de un servicio'),
    'staff.create': ('team', 'Dar de alta integrantes'),
    'staff.update': ('team', 'Editar datos de integrantes'),
    'staff.destroy': ('team', 'Desactivar integrantes'),
    'staff.reactivate': ('team', 'Reactivar integrantes'),
    'staff.reset_password': ('team', 'Restablecer contraseñas'),
    'staff.change_role': ('team', 'Cambiar roles'),
    'staff.manage_permissions': ('team', 'Conceder y quitar permisos'),
    'staff.manage_absences': ('team', 'Registrar ausencias'),
    'organization.update': ('clinic_settings', 'Editar la configuración de la clínica'),
    'agentinbox.config': ('clinic_settings', 'Configurar el asistente de WhatsApp'),
    'service.create': ('services', 'Crear servicios'),
    'service.update': ('services', 'Editar servicios y precios'),
    'service.destroy': ('services', 'Eliminar servicios'),
    'import.list': ('imports', 'Ver importaciones'),
    'import.retrieve': ('imports', 'Ver el detalle de una importación'),
    'import.create': ('imports', 'Subir archivos para importar'),
    'import.commit': ('imports', 'Confirmar importaciones'),
    'dashboard.financial.view': ('reports', 'Ver reportes financieros'),
}

# ADR p69 §5: con cualquiera de estos se llega a controlar cuentas ajenas. No se
# conceden a otro rol y no se quitan a un ADMIN; «administrador» sigue siendo
# exactamente el rol ADMIN (INV-J intacto).
ADMIN_RESERVED = frozenset({
    'staff.create', 'staff.update', 'staff.destroy', 'staff.reset_password',
    'staff.reactivate', 'staff.change_role', 'staff.manage_permissions',
})

# El permiso que decide la columna «Firma de recetas» (con cédula, ADR p64).
SIGNING_PERMISSION = 'prescription.create'

_AREA_ORDER = [key for key, _ in AREAS]
_GROUP_ORDER = list(GROUPS)


def permission_area(code):
    group = PERMISSIONS.get(code, (None,))[0]
    return GROUPS[group][0] if group else None


def area_codes(area):
    return frozenset(code for code in PERMISSIONS if permission_area(code) == area)


ADMINISTRATION_CODES = area_codes('administration')


def catalog_payload():
    """Áreas → grupos → permisos, en orden de presentación y con su etiqueta."""
    by_group = {key: [] for key in _GROUP_ORDER}
    for code in PERMISSION_CODES:
        group, label = PERMISSIONS[code]
        by_group[group].append({'code': code, 'label': label, 'reserved': code in ADMIN_RESERVED})
    areas = []
    for area_key, area_label in AREAS:
        groups = [
            {'key': key, 'label': GROUPS[key][1], 'permissions': by_group[key]}
            for key in _GROUP_ORDER if GROUPS[key][0] == area_key and by_group[key]
        ]
        areas.append({'key': area_key, 'label': area_label, 'groups': groups})
    return areas
