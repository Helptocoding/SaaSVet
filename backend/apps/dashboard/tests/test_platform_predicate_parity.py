"""`IsAdminSaaS` y `IsPlatformOperator` deciden lo mismo.

Origen (auditoría run-1, unidad comodín): `analytics_health` es la única
lectura cross-tenant del SaaS — acepta `?org=<id>` y, sin ese parámetro,
consulta todas las organizaciones a la vez. Estaba protegida por un predicado
LOCAL que comprobaba solo `role == 'ADMIN_SAAS'`, mientras la frontera de
plataforma exigía además `is_superuser` e `is_staff`. Esa divergencia no era
explotable por API (ninguna ruta escribe `User.role`), pero hacía que el
aislamiento dependiera de una propiedad del código en vez de del permiso.

Hay dos clases a propósito: `apps.dashboard` NO importa
`apps.platform.permissions`, porque `platform` es la frontera cross-tenant y
un dominio de lectura no debe depender de ella. El coste de esa decisión es la
duplicación, y este gate es lo que la paga: recorre la tabla de verdad
completa y falla si las dos clases vuelven a divergir.

Importar `platform` AQUÍ es legítimo: un test no es código de producción y no
crea acoplamiento en tiempo de ejecución.
"""
from itertools import product

from django.test import SimpleTestCase

from apps.dashboard.views import IsAdminSaaS
from apps.platform.permissions import IsPlatformOperator


class _FakeUser:
    def __init__(self, authenticated, superuser, staff, role):
        self.is_authenticated = authenticated
        self.is_superuser = superuser
        self.is_staff = staff
        self.role = role
        self.pk = 1
        self.username = 'parity'


class _FakeRequest:
    def __init__(self, user):
        self.user = user
        self.path = '/api/internal/analytics-health/'
        self.method = 'GET'


class PlatformPredicateParityTests(SimpleTestCase):
    """Sin DB: ambos predicados solo leen atributos del usuario."""

    TRUTH_TABLE = list(product(
        [True, False],                      # authenticated
        [True, False],                      # is_superuser
        [True, False],                      # is_staff
        ['ADMIN_SAAS', 'ADMIN', 'VET', ''],  # role
    ))

    def test_both_predicates_agree_on_every_combination(self):
        local, canonical = IsAdminSaaS(), IsPlatformOperator()
        for authenticated, superuser, staff, role in self.TRUTH_TABLE:
            user = _FakeUser(authenticated, superuser, staff, role)
            request = _FakeRequest(user)
            with self.subTest(auth=authenticated, su=superuser, staff=staff, role=role):
                self.assertEqual(
                    bool(local.has_permission(request, None)),
                    bool(canonical.has_permission(request, None)),
                    'IsAdminSaaS divergió de IsPlatformOperator: una de las dos '
                    'cambió sin la otra, y la que protege la lectura cross-tenant '
                    'es la local.',
                )

    def test_only_the_full_operator_passes(self):
        """Ancla del contrato: la conjunción de las tres condiciones."""
        local = IsAdminSaaS()
        granted = [
            (a, su, st, r) for (a, su, st, r) in self.TRUTH_TABLE
            if local.has_permission(_FakeRequest(_FakeUser(a, su, st, r)), None)
        ]
        self.assertEqual(granted, [(True, True, True, 'ADMIN_SAAS')])

    def test_role_alone_is_refused(self):
        """La regresión concreta que esto cubre."""
        request = _FakeRequest(_FakeUser(True, False, False, 'ADMIN_SAAS'))
        self.assertFalse(IsAdminSaaS().has_permission(request, None))

    def test_anonymous_user_without_the_attributes_does_not_raise(self):
        """Un AnonymousUser no tiene is_superuser/role: debe cerrar, no estallar."""
        class _Anon:
            is_authenticated = False

        self.assertFalse(IsAdminSaaS().has_permission(_FakeRequest(_Anon()), None))
