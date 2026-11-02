"""Ratchet del inventario del Django admin (auditoría run-1, pendiente
`infra/caddy/django-admin-exposed-without-ip-allowlist-or-login-throttle`).

Por qué este gate y no el que el plan de remediación proponía primero:

El criterio inicial era «todo ModelAdmin sobre un modelo con tenant debe tener
un `get_queryset` restringido por organización». **Es incorrecto.** El admin es
la herramienta del operador de plataforma (`ADMIN_SAAS`), y ver todas las
clínicas es precisamente su función. Imponer ahí el filtro de organización
rompería el caso de uso legítimo.

Lo que sí hay que vigilar es el **radio de impacto**: una sesión de superusuario
en el admin rodea `for_organization`, del que depende TODO el aislamiento entre
clínicas (no hay row-level security en PostgreSQL — ADR p23 sigue diferido). Y
el login del admin es una vista Django plana, así que ningún throttle del
proyecto lo cubre: el límite de 5/15min protege `/api/token/`, no ese
formulario. La mitigación vive en `infra/Caddyfile`
(`DJANGO_ADMIN_ALLOWED_IPS`, fail-closed) y en el slug secreto.

Siendo así, cada modelo que se registra en el admin **amplía** lo que una sola
sesión comprometida alcanza. Este test no lo prohíbe: lo hace **consciente**.
Mismo patrón de baseline revisado que `test_tenant_scoping_audit.py`.

Si añades un registro, añádelo abajo y pregúntate si de verdad hace falta
administrarlo por ahí. Si lo quitas, quítalo de la lista.
"""
from django.contrib import admin
from django.test import SimpleTestCase

# Inventario revisado el 2026-10-28. Formato: "app_label.ModelName".
BASELINE_REGISTERED = {
    # Catálogo y documentos financieros. Con tenant: alcanzables cross-clínica
    # por un superusuario, aceptado para soporte de plataforma.
    'billing.Service',
    'billing.Invoice',
    # Inventario. Con tenant.
    'inventory.Product',
    'inventory.Presentation',
    'inventory.StockMovement',
    'inventory.MedicalRecordProduct',
    # Recetas. Con tenant y contenido clínico.
    'prescriptions.Prescription',
    # Operaciones del agente conversacional. Inspección de solo lectura.
    'agent.ConversationOperation',
    # Documentos legales: globales de plataforma por diseño, no son datos de
    # tenant. Su aceptación sí es por usuario.
    'legal.LegalDocument',
    'legal.LegalAcceptance',
    # El tenant mismo y las cuentas.
    'organizations.Organization',
    'users.User',
    # Infraestructura de Django/terceros, no dominio del proyecto.
    'auth.Group',
    'token_blacklist.OutstandingToken',
    'token_blacklist.BlacklistedToken',
}


def _registered_labels():
    return {
        f'{model._meta.app_label}.{model.__name__}'
        for model in admin.site._registry
    }


class AdminRegistrationAuditTests(SimpleTestCase):

    def test_no_unreviewed_admin_registration(self):
        current = _registered_labels()
        added = current - BASELINE_REGISTERED
        self.assertFalse(
            added,
            "Modelos registrados en el Django admin sin revisar:\n"
            + '\n'.join(f'  - {label}' for label in sorted(added))
            + "\n\nCada registro amplía lo que alcanza UNA sesión de "
              "superusuario comprometida, y el admin rodea for_organization "
              "(no hay RLS). Si el registro es necesario, añádelo a "
              "BASELINE_REGISTERED en este archivo indicando por qué.",
        )

    def test_baseline_has_no_stale_entries(self):
        """Obliga a mantener la lista: una entrada que ya no se registra debe
        salir, o el baseline deja de describir la realidad y pierde valor."""
        current = _registered_labels()
        stale = BASELINE_REGISTERED - current
        self.assertFalse(
            stale,
            "Entradas de BASELINE_REGISTERED que ya no están registradas:\n"
            + '\n'.join(f'  - {label}' for label in sorted(stale))
            + "\n\nQuítalas del baseline.",
        )
