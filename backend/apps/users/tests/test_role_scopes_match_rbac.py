"""Fase 1 Equipo: las descripciones de rol de la interfaz dicen la verdad.

``frontend/src/features/staff/roleScopes.json`` explica a la clínica qué permite
cada rol al dar de alta o editar a un integrante. Junto a cada texto declara los
permisos que lo respaldan (``grants``) y los que el texto niega (``lacks``). Esta
prueba los contrasta con la lista real de cada rol (``PERMISSIONS``, ADR p63):
si un rol pierde un permiso que su texto promete, o gana uno que su texto niega,
falla y hay que corregir el texto.
"""
import json
from pathlib import Path

from django.test import SimpleTestCase

from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS

REPO_ROOT = Path(__file__).resolve().parents[4]
ROLE_SCOPES = REPO_ROOT / 'frontend' / 'src' / 'features' / 'staff' / 'roleScopes.json'
CLINIC_ROLES = {'ADMIN', 'VET', 'ASSISTANT'}


class RoleScopesMatchRbacTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scopes = json.loads(ROLE_SCOPES.read_text(encoding='utf-8'))

    def test_covers_exactly_the_clinic_roles(self):
        self.assertEqual(set(self.scopes), CLINIC_ROLES)

    def test_every_text_is_present(self):
        for role, scope in self.scopes.items():
            for key in ('label', 'short', 'summary'):
                with self.subTest(role=role, key=key):
                    self.assertTrue(scope.get(key, '').strip())

    def test_declared_codes_exist(self):
        for role, scope in self.scopes.items():
            for code in scope['grants'] + scope['lacks']:
                with self.subTest(role=role, code=code):
                    self.assertIn(code, PERMISSION_CODES)

    def test_what_the_text_promises_the_role_has(self):
        for role, scope in self.scopes.items():
            for code in scope['grants']:
                with self.subTest(role=role, code=code):
                    self.assertIn(code, PERMISSIONS[role])

    def test_what_the_text_denies_the_role_lacks(self):
        for role, scope in self.scopes.items():
            for code in scope['lacks']:
                with self.subTest(role=role, code=code):
                    self.assertNotIn(code, PERMISSIONS[role])
