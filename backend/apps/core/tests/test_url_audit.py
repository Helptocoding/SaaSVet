"""
test_url_audit.py — Guard introspectivo Día 6

Bloquea reintroducir <int:pk> en URLs de modelos públicos.
Bloquea filtros de query param de modelos públicos que usen filter(<modelo>_id=raw).

Modelos públicos (PublicIdMixin): Pet, Owner, Appointment, MedicalRecord,
Invoice, Prescription, Product, Presentation, Service.

Fase 5: agregar VaccineRecord, User, Organization.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[4]
URLS_GLOB = list((REPO_ROOT / 'backend' / 'apps').rglob('urls.py'))

# URLs con <int:pk> permitidas (legacy intencional o child interno).
# Día 6 hardening: cada allow es un regex anclado al CONTEXTO específico,
# no substring suelto. Sin esto, `'services/<int:pk>'` admitía silenciosamente
# una regresión hipotética en `billing/services/<int:pk>` (Service es modelo
# público, debe ser <str:pk>).
ALLOWED_INT_PATTERNS = (
    # OrganizationLegacyView — Sunset RFC 8594 (ADR-15 / p16)
    re.compile(r'organizations/<int:pk>'),
    # MedicalRecordService (child interno bajo MR UUID parent)
    re.compile(r'medical-records/<str:[A-Za-z_][A-Za-z0-9_]*>/services/<int:pk>'),
    # PrescriptionItem (child interno bajo Prescription UUID parent)
    re.compile(r'prescriptions/<str:[A-Za-z_][A-Za-z0-9_]*>/items/<int:pk>'),
    # channels.Message (WA-RETRY-01) NO va aquí: un patrón suelto aceptaría la
    # ruta en cualquier archivo y con cualquier handler. Su excepción vive en
    # INTERNAL_MESSAGE_RETRY_ROUTE, atada a agent/urls.py y a views.retry_message.
)


# Message has no PublicIdMixin: its integer ID is an internal child beneath
# an organization-scoped public Conversation. This exact handler validates
# organization, conversation, account/contact scope and retry authorization.
INTERNAL_MESSAGE_RETRY_ROUTE = re.compile(
    r"\s*path\('conversations/<str:pk>/messages/<int:message_id>/retry/', "
    r"views\.retry_message,\s*"
)


def is_allowed_int_route(url_file, line):
    if any(pattern.search(line) for pattern in ALLOWED_INT_PATTERNS):
        return True
    return (
        url_file == REPO_ROOT / 'backend' / 'apps' / 'agent' / 'urls.py'
        and INTERNAL_MESSAGE_RETRY_ROUTE.fullmatch(line) is not None
    )


class IntPkInPublicUrlsTest(SimpleTestCase):
    """
    Test introspectivo: scan apps/*/urls.py + config/urls.py por <int:pk>
    en endpoints de modelos públicos.
    """

    def test_no_int_pk_in_public_urls(self):
        """
        Fase 0/1 BLOCKER: cero <int:pk> en endpoints de modelos públicos.
        """
        violations = []
        files = URLS_GLOB + [REPO_ROOT / 'backend' / 'config' / 'urls.py']

        for url_file in files:
            content = url_file.read_text(encoding='utf-8')
            for lineno, line in enumerate(content.splitlines(), 1):
                if '<int:' not in line:
                    continue
                if is_allowed_int_route(url_file, line):
                    continue
                if line.strip().startswith('#'):
                    continue
                violations.append(f"{url_file.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

        if violations:
            msg = (
                "URLs con <int:pk> en modelos públicos detectadas. "
                "Cambiar a <str:pk> + PublicIdLookupMixin/resolve_public_id:\n"
                + "\n".join(violations)
            )
            self.fail(msg)

    def test_internal_message_retry_exception_requires_exact_context(self):
        from apps.channels.models import Message

        self.assertNotIn('public_id', {field.name for field in Message._meta.get_fields()})
        path = REPO_ROOT / 'backend' / 'apps' / 'agent' / 'urls.py'
        line = (
            "    path('conversations/<str:pk>/messages/<int:message_id>/retry/', "
            "views.retry_message,"
        )
        self.assertTrue(is_allowed_int_route(path, line))
        cases = (
            (REPO_ROOT / 'backend' / 'apps' / 'billing' / 'urls.py', line),
            (path, line.replace('views.retry_message', 'views.other_handler')),
            (path, line.replace('messages/', 'appointments/')),
            (path, line.replace('conversations/', 'billing/conversations/')),
            (path, line.replace('<str:pk>', '<int:pk>')),
            (path, "path('appointments/<int:pk>/', views.retry_message,"),
        )
        for url_file, candidate in cases:
            with self.subTest(file=str(url_file), line=candidate):
                self.assertFalse(is_allowed_int_route(url_file, candidate))


class QueryParamPublicModelFilterTest(SimpleTestCase):
    """
    Test introspectivo: detecta filter(<modelo>_id=raw) sobre modelos públicos
    que debe pasar por resolve_public_id().

    Modelos públicos sensibles a query param: pet, owner, appointment,
    medical_record, invoice, prescription, product, presentation, service.
    """

    PUBLIC_MODEL_NAMES = (
        'pet', 'owner', 'appointment', 'medical_record',
        'invoice', 'prescription', 'product', 'presentation', 'service',
    )

    def test_no_raw_id_filter_on_public_models_in_query_params(self):
        """
        Fase 3 BLOCKER: detecta filter(<modelo>_id=<raw_var>) en views.

        Permite filter(<modelo>=<instancia>) — patrón correcto post-resolve.
        """
        violations = []
        views_glob = list((REPO_ROOT / 'backend' / 'apps').rglob('views.py'))

        # Patrón: .filter(<modelo>_id=<algo no acabado en _obj>)
        pattern = re.compile(
            r'\.filter\(\s*(' + '|'.join(self.PUBLIC_MODEL_NAMES) + r')_id\s*=\s*(\w+)'
        )

        for view_file in views_glob:
            content = view_file.read_text(encoding='utf-8')
            for lineno, line in enumerate(content.splitlines(), 1):
                match = pattern.search(line)
                if not match:
                    continue
                # Acepta foo_id=instance.pk o foo_id=organization.id (no es query param)
                var = match.group(2)
                if var in ('pk', 'id'):
                    continue
                # Acepta self-references / construcciones internas
                if 'request.user' in line:
                    continue
                violations.append(
                    f"{view_file.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                )

        # Fase 3 cerrada (Día 6): guard activo. Cualquier regresión bloquea CI.
        # Si necesitas filter(<modelo>_id=<var>) por motivo legítimo, refactor
        # a `resolve_public_id(Model.objects.for_organization(org), value)`
        # antes de `.filter(<modelo>=instance)` — NUNCA bypasses tenant.
        if violations:
            msg = (
                "filter(<modelo_publico>_id=raw_var) detectado — riesgo de "
                "tenant leak. Migrar a resolve_public_id() antes de filter():\n"
                + "\n".join(violations)
            )
            self.fail(msg)
