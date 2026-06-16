"""
Escalabilidad del listado de Mascotas (GET /api/pets/).

Tras importar una clínica con miles de mascotas, /pets descargaba TODO + N+1 de
owner + filtrado client-side. Estos tests blindan el rediseño:

- Paginación **opt-in** vía ?page (vista Mascotas) — sin ?page se conserva el
  contrato legacy de array plano que consumen los dropdowns SearchSelect y las
  listas client-side (.then(ps => ps.map(...))).
- Filtros server-side: search (nombre/especie/raza/expediente/dueño/teléfono),
  species, sex, age.
- Sin N+1: select_related('owner') → el nº de queries NO escala con las filas.
- Aislamiento multi-tenant (cross-org nunca aparece).
- Endpoint agregado /pets/stats/ (conteos de toda la clínica).
"""
from datetime import date, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(name=name, organization=org, defaults={"is_system_role": True})
        role.permissions.set([wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map])
        roles[name] = role
    return roles


def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="pass", organization=org, role=role_name)
    roles = _seed_roles(org)
    UserRole.objects.get_or_create(user=u, role=roles[role_name])
    return u


def _make_pet(org, owner, name, species="canino", sex="unknown", birth_date=None):
    return Pet.objects.create(
        organization=org, owner=owner, name=name, species=species,
        sex=sex, birth_date=birth_date,
    )


class PetListPaginationTests(APITestCase):
    URL = "/api/pets/"

    @classmethod
    def setUpTestData(cls):
        # El post_save de Organization siembra 1 Owner + 1 Pet genéricos por org.
        cls.org_a = Organization.objects.create(name="Org PET A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Org PET B", timezone="UTC")
        cls.admin_a = _make_user("adm_pet_a", cls.org_a, "ADMIN")

        cls.owner_a = Owner.objects.create(name="Dueño A", phone="5550000001", organization=cls.org_a)
        for i in range(30):
            _make_pet(cls.org_a, cls.owner_a, f"PagPet {i:02d}", species="canino")

        # Ruido en org B — nunca debe aparecer ni contarse.
        cls.owner_b = Owner.objects.create(name="Dueño B", phone="5559999991", organization=cls.org_b)
        _make_pet(cls.org_b, cls.owner_b, "OtherOrgPet", species="felino")

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    # ── Contrato de paginación opt-in ──────────────────────────────────────
    def test_list_paginated_only_with_page_param(self):
        r = self.client.get(self.URL, {"page": 1})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("results", r.data)
        self.assertIn("count", r.data)
        # 30 reales + 1 genérica de la org.
        expected = Pet.objects.for_organization(self.org_a).count()
        self.assertEqual(r.data["count"], expected)
        self.assertEqual(len(r.data["results"]), 25)

    def test_list_without_page_returns_flat_array(self):
        # Contrato legacy: getPets() sin params → array plano (prescriptions,
        # medical records lo consumen como lista completa).
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsInstance(r.data, list)
        self.assertEqual(len(r.data), Pet.objects.for_organization(self.org_a).count())

    def test_second_page_no_overlap(self):
        p1 = self.client.get(self.URL, {"page": 1}).data["results"]
        p2 = self.client.get(self.URL, {"page": 2}).data["results"]
        ids1 = {row["public_id"] for row in p1}
        ids2 = {row["public_id"] for row in p2}
        self.assertEqual(ids1 & ids2, set())

    def test_page_size_override(self):
        r = self.client.get(self.URL, {"page": 1, "page_size": 50})
        self.assertEqual(len(r.data["results"]), Pet.objects.for_organization(self.org_a).count())

    # ── Contrato dropdown (?search sin ?page) ──────────────────────────────
    def test_search_without_page_is_flat_capped(self):
        r = self.client.get(self.URL, {"search": "PagPet"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsInstance(r.data, list)          # NO envelope
        self.assertLessEqual(len(r.data), 20)        # cap [:20]

    def test_search_with_page_is_paginated(self):
        r = self.client.get(self.URL, {"search": "PagPet", "page": 1})
        self.assertIn("results", r.data)
        self.assertEqual(r.data["count"], 30)        # las 30 reales coinciden

    # ── Filtros server-side ────────────────────────────────────────────────
    def test_search_matches_owner_name(self):
        _make_pet(self.org_a, Owner.objects.create(name="Mariana López", phone="5550000777", organization=self.org_a), "Firulais")
        r = self.client.get(self.URL, {"search": "Mariana", "page": 1})
        names = [row["name"] for row in r.data["results"]]
        self.assertIn("Firulais", names)

    def test_search_matches_owner_phone(self):
        r = self.client.get(self.URL, {"search": "5550000001", "page": 1})
        self.assertEqual(r.data["count"], 30)        # todos los pets del owner_a

    def test_filter_species_caninos(self):
        _make_pet(self.org_a, self.owner_a, "Michi", species="felino")
        r = self.client.get(self.URL, {"species": "caninos", "page": 1})
        self.assertEqual(r.data["count"], 30)        # el felino queda fuera
        for row in r.data["results"]:
            self.assertNotEqual(row["species"], "felino")

    def test_filter_species_matches_dirty_import_values(self):
        _make_pet(self.org_a, self.owner_a, "ImportPerro", species="Perro")
        r = self.client.get(self.URL, {"species": "caninos", "page": 1})
        names = [row["name"] for row in r.data["results"]]
        self.assertIn("ImportPerro", names)

    def test_filter_sex(self):
        _make_pet(self.org_a, self.owner_a, "Hembrita", species="canino", sex="female")
        r = self.client.get(self.URL, {"sex": "female", "page": 1})
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["name"], "Hembrita")

    def test_filter_age_cachorro_vs_senior(self):
        today = date.today()
        _make_pet(self.org_a, self.owner_a, "Cachorrito", birth_date=today - timedelta(days=120))
        _make_pet(self.org_a, self.owner_a, "Viejito", birth_date=today - timedelta(days=365 * 10))
        cach = self.client.get(self.URL, {"age": "cachorro", "page": 1}).data
        sen = self.client.get(self.URL, {"age": "senior", "page": 1}).data
        self.assertEqual([r["name"] for r in cach["results"]], ["Cachorrito"])
        self.assertEqual([r["name"] for r in sen["results"]], ["Viejito"])

    # ── N+1 ────────────────────────────────────────────────────────────────
    def test_no_n_plus_1_on_paginated_list(self):
        # El nº de queries NO debe escalar con el nº de filas servidas: una
        # página de 5 y una de 25 deben costar lo mismo (owner vía JOIN con
        # select_related, no 1 query por mascota). Warmup primero para excluir
        # el costo único de la 1ª request del test (savepoints/permisos).
        self.client.get(self.URL, {"page": 1, "page_size": 1})
        with CaptureQueriesContext(connection) as ctx5:
            self.client.get(self.URL, {"page": 1, "page_size": 5})
        with CaptureQueriesContext(connection) as ctx25:
            self.client.get(self.URL, {"page": 1, "page_size": 25})
        self.assertEqual(len(ctx5), len(ctx25))

    # ── Multi-tenant ───────────────────────────────────────────────────────
    def test_tenant_isolation(self):
        r = self.client.get(self.URL, {"page": 1, "page_size": 100})
        names = [row["name"] for row in r.data["results"]]
        self.assertNotIn("OtherOrgPet", names)
        self.assertEqual(r.data["count"], Pet.objects.for_organization(self.org_a).count())

    # ── Stats ──────────────────────────────────────────────────────────────
    def test_stats_counts_whole_clinic(self):
        _make_pet(self.org_a, self.owner_a, "Gatito", species="felino")
        r = self.client.get(self.URL + "stats/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["caninos"], 30)
        self.assertEqual(r.data["felinos"], 1)
        self.assertEqual(r.data["total"], Pet.objects.for_organization(self.org_a).count())

    def test_stats_tenant_scoped(self):
        r = self.client.get(self.URL + "stats/")
        # El felino de org B (1) jamás entra al conteo de org A.
        self.assertEqual(r.data["felinos"], 0)

    def test_stats_single_aggregate_query(self):
        self.client.get(self.URL + "stats/")     # warmup
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.URL + "stats/")
        pet_queries = [q for q in ctx.captured_queries if "patients_pet" in q["sql"].lower()]
        # UNA sola query toca la tabla de mascotas (agregado), nunca por fila.
        self.assertEqual(len(pet_queries), 1)
