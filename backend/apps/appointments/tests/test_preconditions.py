"""
test_preconditions.py — INV-A: precondición atómica de estado (ADR p57, F0·a).

Cubre las pruebas de aceptación P0-4, P0-7, P0-9ᵃ, P1-14, P1-23 y P2-4 de la
decisión de Item 2 (§8).

Lo que estas pruebas defienden, en una frase cada una:

  P0-4  el campo está DECLARADO — si alguien lo borra del serializer, DRF lo
        descarta en silencio y el PATCH pasa incondicionalmente (fail-open).
  P0-7  la garantía es del dominio, no un privilegio del agente: cualquier
        actor autenticado recibe el mismo 409.
  P0-9ᵃ una precondición fallida no escribe NADA, ni siquiera auditoría.
  P1-14 hay LOCK, no solo comparación (PostgreSQL, dos conexiones reales).
  P1-23 `DELETE` respeta la precondición y trae cabeceras de deprecación.

P2-4 («sin `expected_state`, todo funciona como hoy») era del **rollout**, no
del diseño, y la Fase 3 lo sustituye: omitir la precondición es ahora `400
precondition_required` en las cuatro vías. Lo defiende
`PreconditionIsMandatoryTests`.
"""
import threading
from datetime import timedelta

from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.appointments.models import Appointment, AppointmentStatusChange
from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User

SLOT_HOUR = 11


def _slot(days=3, hour=SLOT_HOUR):
    """`(fecha_iso, inicio_hhmm, fin_hhmm)` a `days` días, a hora fija.

    Hora fija por el mismo motivo que en test_idempotency: con la hora actual,
    los últimos 30 minutos del día UTC envuelven el `end_time` al día siguiente
    y el serializer rechaza por `end_time <= start_time`.
    """
    day = (timezone.now() + timedelta(days=days)).date()
    return day.isoformat(), f"{hour:02d}:00", f"{hour:02d}:30"


def _seed_wildcard_role(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    role, _ = Role.objects.get_or_create(
        name="ADMIN", organization=org, defaults={"is_system_role": True})
    role.permissions.set([wildcard])
    return role


def _seed_org(name, suffix):
    """Organización con ADMIN, VET (con rol) y una mascota."""
    org = Organization.objects.create(name=name, timezone="UTC")
    role = _seed_wildcard_role(org)
    admin = User.objects.create_user(
        username=f"pre_admin_{suffix}", password="p", organization=org, role="ADMIN")
    UserRole.objects.get_or_create(user=admin, role=role)
    vet = User.objects.create_user(
        username=f"pre_vet_{suffix}", password="p", organization=org, role="VET")
    UserRole.objects.get_or_create(user=vet, role=role)
    owner = Owner.objects.create(organization=org, name="Ana", phone="5511110001")
    pet = Pet.objects.create(
        organization=org, owner=owner, name="Luna",
        species="perro", birth_date="2021-01-01")
    return org, admin, vet, pet


class PreconditionTestBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org, cls.admin, cls.vet, cls.pet = _seed_org("Precondicion Org", "a")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def _create_appt(self, days=3, hour=SLOT_HOUR):
        date, start, end = _slot(days, hour)
        response = self.client.post("/api/appointments/", {
            "pet": self.pet.id,
            "veterinarian": self.vet.id,
            "date": date,
            "start_time": start,
            "end_time": end,
            "reason": "vacuna",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return Appointment.objects.get(public_id=response.json()["public_id"])

    @staticmethod
    def _state_of(appt):
        return {
            "status": appt.status,
            "date": appt.date.isoformat(),
            "start_time": appt.start_time.strftime("%H:%M"),
        }

    @staticmethod
    def _stale_state(appt):
        """Una tupla que ya no describe la realidad."""
        return {
            "status": "scheduled",
            "date": (appt.date - timedelta(days=1)).isoformat(),
            "start_time": "08:00",
        }


class ExpectedStateIsDeclaredTests(PreconditionTestBase):
    """P0-4 — el fail-open invisible de DRF."""

    def test_stale_precondition_on_patch_detail_is_409(self):
        appt = self._create_appt()
        date, start, end = _slot(days=6)

        response = self.client.patch(f"/api/appointments/{appt.public_id}/", {
            "date": date, "start_time": start, "end_time": end,
            "expected_state": self._stale_state(appt),
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.content)
        body = response.json()
        self.assertEqual(body["code"], "appointment_changed")
        # R3: el estado REAL viaja en la respuesta.
        self.assertEqual(body["current"], self._state_of(appt))

        appt.refresh_from_db()
        self.assertEqual(appt.date.isoformat(), self._state_of(appt)["date"])

    def test_stale_precondition_on_status_endpoint_is_409(self):
        appt = self._create_appt()

        response = self.client.patch(f"/api/appointments/{appt.public_id}/status/", {
            "status": "confirmed",
            "expected_state": self._stale_state(appt),
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.content)
        self.assertEqual(response.json()["code"], "appointment_changed")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")

    def test_matching_precondition_passes(self):
        appt = self._create_appt()

        response = self.client.patch(f"/api/appointments/{appt.public_id}/status/", {
            "status": "confirmed",
            "expected_state": self._state_of(appt),
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")

    def test_field_is_declared_on_the_serializer(self):
        """El corazón de P0-4: si el campo no está declarado, DRF lo descarta.

        Sin esta aserción, borrar la línea del serializer dejaría los tests de
        arriba en verde por la razón equivocada… no: los dejaría en ROJO. Ésta
        además nombra la causa, para que quien lo rompa lea por qué existe.
        """
        from apps.appointments.serializers import AppointmentSerializer
        self.assertIn("expected_state", AppointmentSerializer().fields)

    def test_malformed_precondition_is_a_client_error_not_a_silent_pass(self):
        appt = self._create_appt()
        for bad in (
            "no-soy-un-objeto",
            {"status": "scheduled"},                                   # incompleto
            {"status": "inventado", "date": "2026-01-01", "start_time": "10:00"},
            {"status": "scheduled", "date": "01/01/2026", "start_time": "10:00"},
            {"status": "scheduled", "date": "2026-01-01", "start_time": "veinticinco"},
            {"status": "scheduled", "date": "2026-01-01", "start_time": "10:00", "x": 1},
        ):
            with self.subTest(bad=bad):
                response = self.client.patch(
                    f"/api/appointments/{appt.public_id}/status/",
                    {"status": "confirmed", "expected_state": bad},
                    format="json",
                )
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
                appt.refresh_from_db()
                self.assertEqual(appt.status, "scheduled")

    def test_precondition_is_rejected_on_every_creation_path(self):
        """Crear no tiene estado previo: tragárselo en silencio sería fail-open.

        Las TRES vías de creación de la matriz §3.3, no solo la obvia: el
        payload de `create-with-patient` y el de `walk-in` se arman a mano, así
        que sin un rechazo explícito el campo se perdía sin ruido.
        """
        date, start, end = _slot(days=9)
        stale = {"status": "scheduled", "date": date, "start_time": start}

        creations = {
            "/api/appointments/": {
                "pet": self.pet.id, "veterinarian": self.vet.id,
                "date": date, "start_time": start, "end_time": end, "reason": "x",
            },
            "/api/appointments/create-with-patient/": {
                "owner_name": "Cliente Nuevo", "owner_phone": "5599887766",
                "pet_name": "Michi", "pet_species": "felino",
                "veterinarian": self.vet.id,
                "date": date, "start_time": start, "end_time": end, "reason": "x",
            },
            "/api/appointments/walk-in/": {
                "pet": self.pet.id, "veterinarian": self.vet.id, "reason": "urgencia",
            },
        }

        for url, payload in creations.items():
            with self.subTest(url=url):
                before = Appointment.objects.count()
                response = self.client.post(
                    url, {**payload, "expected_state": stale}, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                                 response.content)
                self.assertIn("expected_state", response.json().get("errors", {}))
                self.assertEqual(Appointment.objects.count(), before)


class AbsentVersusExplicitNullTests(PreconditionTestBase):
    """Ausencia ≠ `null` explícito (hallazgo OCR sobre F0).

    Los dos llegaban al dominio como `None`, así que un
    `expected_state: null` se trataba como opt-in y la escritura pasaba **sin
    precondición**. Quien manda `null` cree que manda una precondición: dejarle
    pasar la escritura es exactamente el fail-open que INV-A cierra.

    Contrato desde la Fase 3: las dos fallan con cero escrituras, en las siete
    vías, pero con `code` distinto — omitirla es `precondition_required` y
    mandarla en `null` es `validation_error`. Que el desenlace coincida no
    autoriza a fusionarlas: el centinela `MISSING` es lo que impide que
    `data.get()` las colapse, y sin él volvería el fail-open del párrafo de
    arriba en cuanto la ausencia dejara de ser un error.
    """

    # ---- Mutaciones: ausencia = 400 precondición, null = 400 forma ----------

    def test_absent_precondition_is_rejected_on_every_mutation(self):
        """Fase 3: la ausencia dejó de ser opt-in y es `400` en las tres vías.

        Ausencia y `null` explícito ya no se diferencian en el DESENLACE —las
        dos son 400— pero sí en el MENSAJE: a quien la omite se le dice que
        hace falta; a quien manda `null`, que ese valor no vale. La distinción
        sigue importando para quien depura.
        """
        appt = self._create_appt(days=3, hour=7)
        original = (appt.status, appt.reason)

        patch = self.client.patch(
            f"/api/appointments/{appt.public_id}/", {"reason": "sin precondición"},
            format="json")
        self.assertEqual(patch.status_code, status.HTTP_400_BAD_REQUEST, patch.content)
        self.assertEqual(patch.json().get("code"), "precondition_required")

        st = self.client.patch(
            f"/api/appointments/{appt.public_id}/status/", {"status": "confirmed"},
            format="json")
        self.assertEqual(st.status_code, status.HTTP_400_BAD_REQUEST, st.content)

        gone = self.client.delete(f"/api/appointments/{appt.public_id}/")
        self.assertEqual(gone.status_code, status.HTTP_400_BAD_REQUEST, gone.content)

        appt.refresh_from_db()
        self.assertEqual((appt.status, appt.reason), original)

    def test_explicit_null_is_rejected_on_every_mutation(self):
        appt = self._create_appt(days=3, hour=20)
        original = (appt.status, appt.date, appt.start_time, appt.reason)
        audit_before = AppointmentStatusChange.objects.filter(appointment=appt).count()

        # `assign-patient` va sobre una cita con paciente GENÉRICO: así, sin el
        # `null`, la llamada sería un 200 y el 400 solo puede venir de la
        # precondición. Con un paciente real el endpoint rechazaría igual, pero
        # por otro motivo — y el test pasaría sin probar nada.
        from apps.patients.utils import get_or_create_generic_patient
        _, generic_pet = get_or_create_generic_patient(self.org)
        assignable = self._create_appt(days=5, hour=20)
        Appointment.objects.filter(pk=assignable.pk).update(pet=generic_pet)

        cases = (
            ("patch", f"/api/appointments/{appt.public_id}/",
             {"reason": "no debe guardarse", "expected_state": None}),
            ("status", f"/api/appointments/{appt.public_id}/status/",
             {"status": "confirmed", "expected_state": None}),
            ("assign", f"/api/appointments/{assignable.public_id}/assign-patient/",
             {"pet": self.pet.id, "expected_state": None}),
        )
        for name, url, payload in cases:
            with self.subTest(endpoint=name):
                response = self.client.patch(url, payload, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                                 response.content)
                body = response.json()
                self.assertEqual(body["code"], "validation_error")
                self.assertIn("expected_state", body["errors"])

        with self.subTest(endpoint="delete"):
            response = self.client.delete(
                f"/api/appointments/{appt.public_id}/",
                {"expected_state": None}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                             response.content)
            self.assertIn("expected_state", response.json()["errors"])

        # Cero escrituras en las cuatro vías.
        appt.refresh_from_db()
        self.assertEqual(
            (appt.status, appt.date, appt.start_time, appt.reason), original)
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(),
            audit_before)

    # ---- Creación: null también se rechaza, y no crea nada ------------------

    def test_explicit_null_is_rejected_on_every_creation_path(self):
        date, start, end = _slot(days=11)
        creations = {
            "/api/appointments/": {
                "pet": self.pet.id, "veterinarian": self.vet.id,
                "date": date, "start_time": start, "end_time": end, "reason": "x",
            },
            "/api/appointments/create-with-patient/": {
                "owner_name": "Cliente Nulo", "owner_phone": "5599887755",
                "pet_name": "Nube", "pet_species": "felino",
                "veterinarian": self.vet.id,
                "date": date, "start_time": start, "end_time": end, "reason": "x",
            },
            "/api/appointments/walk-in/": {
                "pet": self.pet.id, "veterinarian": self.vet.id, "reason": "urgencia",
            },
        }
        for url, payload in creations.items():
            with self.subTest(url=url):
                before = Appointment.objects.count()
                response = self.client.post(
                    url, {**payload, "expected_state": None}, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                                 response.content)
                self.assertIn("expected_state", response.json().get("errors", {}))
                self.assertEqual(Appointment.objects.count(), before)

    # ---- El `null` no puede colarse por otra codificación -------------------

    def test_null_cannot_sneak_in_through_form_encoding(self):
        """form-data / QueryDict no puede expresar `null`, y no debe simularlo.

        Un `expected_state=` vacío o el literal `"null"` llegan como CADENA. Si
        alguna de las dos se interpretara como ausencia, form-data sería un
        bypass del contrato que JSON respeta.
        """
        appt = self._create_appt(days=3, hour=21)
        for raw in ("", "null", "None"):
            with self.subTest(raw=raw):
                response = self.client.patch(
                    f"/api/appointments/{appt.public_id}/status/",
                    {"status": "confirmed", "expected_state": raw},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                                 response.content)
                appt.refresh_from_db()
                self.assertEqual(appt.status, "scheduled")

    def test_form_encoded_without_the_key_is_also_rejected(self):
        """El gate no se esquiva cambiando el content-type (Fase 3)."""
        appt = self._create_appt(days=3, hour=22)
        response = self.client.patch(
            f"/api/appointments/{appt.public_id}/status/",
            {"status": "confirmed"}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         response.content)
        self.assertEqual(response.json().get("code"), "precondition_required")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")


class PreconditionAppliesToAnyActorTests(PreconditionTestBase):
    """P0-7 — INV-A no es un privilegio del agente."""

    def test_admin_and_vet_get_the_same_409(self):
        for actor in (self.admin, self.vet):
            with self.subTest(actor=actor.username):
                appt = self._create_appt(days=3, hour=8 + actor.pk % 6)
                client = APIClient()
                client.force_authenticate(actor)

                response = client.patch(
                    f"/api/appointments/{appt.public_id}/status/",
                    {"status": "confirmed", "expected_state": self._stale_state(appt)},
                    format="json",
                )

                self.assertEqual(response.status_code, status.HTTP_409_CONFLICT,
                                 response.content)
                self.assertEqual(response.json()["code"], "appointment_changed")
                appt.refresh_from_db()
                self.assertEqual(appt.status, "scheduled")

    def test_assign_patient_honors_the_precondition(self):
        """`assign-patient` entra al contrato (matriz §3.3)."""
        from apps.patients.utils import get_or_create_generic_patient
        _, generic_pet = get_or_create_generic_patient(self.org)
        appt = self._create_appt(days=4, hour=15)
        Appointment.objects.filter(pk=appt.pk).update(pet=generic_pet)
        appt.refresh_from_db()

        before = AppointmentStatusChange.objects.filter(appointment=appt).count()
        response = self.client.patch(
            f"/api/appointments/{appt.public_id}/assign-patient/",
            {"pet": self.pet.id, "expected_state": self._stale_state(appt)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.content)
        appt.refresh_from_db()
        self.assertEqual(appt.pet_id, generic_pet.id)
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), before)

        # Con la precondición correcta, la vinculación procede como siempre.
        ok = self.client.patch(
            f"/api/appointments/{appt.public_id}/assign-patient/",
            {"pet": self.pet.id, "expected_state": self._state_of(appt)},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.content)
        appt.refresh_from_db()
        self.assertEqual(appt.pet_id, self.pet.id)


class PreconditionNeverPartiallyWritesTests(PreconditionTestBase):
    """P0-9ᵃ — regla R1: cero escrituras parciales."""

    def test_conflict_on_reschedule_leaves_appointment_and_audit_intact(self):
        appt = self._create_appt(days=3, hour=9)
        original = (appt.date, appt.start_time, appt.status)
        audit_before = AppointmentStatusChange.objects.filter(appointment=appt).count()

        date, start, end = _slot(days=7)
        response = self.client.patch(f"/api/appointments/{appt.public_id}/", {
            "date": date, "start_time": start, "end_time": end,
            "reason": "motivo nuevo que tampoco debe guardarse",
            "expected_state": self._stale_state(appt),
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.content)
        appt.refresh_from_db()
        self.assertEqual((appt.date, appt.start_time, appt.status), original)
        self.assertEqual(appt.reason, "vacuna")
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), audit_before)

    def test_conflict_on_status_writes_no_audit_row(self):
        appt = self._create_appt(days=3, hour=10)
        audit_before = AppointmentStatusChange.objects.filter(appointment=appt).count()

        response = self.client.patch(f"/api/appointments/{appt.public_id}/status/", {
            "status": "canceled",
            "cancellation_reason": "no debe persistir",
            "expected_state": self._stale_state(appt),
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")
        self.assertEqual(appt.cancellation_reason, "")
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), audit_before)


class DeleteIsDeprecatedAndHonorsPreconditionTests(PreconditionTestBase):
    """P1-23 — `DELETE` entra al contrato y queda deprecado."""

    def test_stale_precondition_blocks_delete_and_writes_no_second_audit_row(self):
        appt = self._create_appt(days=3, hour=12)
        audit_before = AppointmentStatusChange.objects.filter(appointment=appt).count()

        response = self.client.delete(
            f"/api/appointments/{appt.public_id}/",
            {"expected_state": self._stale_state(appt)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.content)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), audit_before)

    def test_delete_with_precondition_cancels_and_is_flagged_deprecated(self):
        """El `DELETE` sigue vivo hasta su Sunset, pero ya no se salta el gate.

        Dejarlo exento habría convertido la vía deprecada en la puerta de atrás
        de la Fase 3: cancelar sin declarar nada seguiría siendo posible, solo
        que por otra URL.
        """
        appt = self._create_appt(days=3, hour=13)

        response = self.client.delete(
            f"/api/appointments/{appt.public_id}/",
            {"expected_state": self._state_of(appt)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response["Deprecation"], "true")
        self.assertIn("Sunset", response)
        # El Link (RFC 8288) apunta a la URI REAL del sucesor de ESTA cita, no a
        # una plantilla con `{id}`: una plantilla no es dereferenciable.
        self.assertEqual(
            response["Link"],
            f'</api/appointments/{appt.public_id}/status/>; rel="successor-version"',
        )
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")
        self.assertTrue(
            AppointmentStatusChange.objects.filter(
                appointment=appt, to_status="canceled").exists())

    def test_delete_emits_deprecation_log(self):
        appt = self._create_appt(days=3, hour=14)
        with self.assertLogs('core.deprecation', level='WARNING') as logs:
            self.client.delete(
                f"/api/appointments/{appt.public_id}/",
                {"expected_state": self._state_of(appt)}, format="json")
        self.assertTrue(any('DEPRECATED_ENDPOINT_HIT' in line for line in logs.output))

    def test_delete_without_precondition_is_rejected_too(self):
        appt = self._create_appt(days=3, hour=15)
        response = self.client.delete(f"/api/appointments/{appt.public_id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         response.content)
        self.assertEqual(response.json().get("code"), "precondition_required")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")


class PreconditionIsMandatoryTests(PreconditionTestBase):
    """Fase 3 de INV-A: mutar una cita EXIGE declarar cómo se la vio.

    Esta clase **sustituye** a la que blindaba el opt-in (`P2-4`, «sin
    `expected_state`, nada cambia»). Ese contrato era del rollout, no del
    diseño: mientras la precondición fue opcional, la garantía dependía de que
    cada llamador se acordara — y el que se olvida nunca es el que ya existe,
    sino el que se escribe con prisa un viernes por la mañana.

    Ahora el dominio se niega, y falla **ruidosamente en la primera llamada**
    en vez de sobrescribir en silencio la decisión de otra persona.
    """

    def _assert_precondition_required(self, response):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         response.content)
        self.assertEqual(response.json().get("code"), "precondition_required")

    def test_patch_detail_without_precondition_is_rejected(self):
        appt = self._create_appt(days=3, hour=16)
        date, start, end = _slot(days=8)
        original_date = appt.date

        response = self.client.patch(f"/api/appointments/{appt.public_id}/", {
            "date": date, "start_time": start, "end_time": end,
        })

        self._assert_precondition_required(response)
        appt.refresh_from_db()
        self.assertEqual(appt.date, original_date)      # cero escrituras

    def test_status_change_without_precondition_is_rejected(self):
        appt = self._create_appt(days=3, hour=17)
        response = self.client.patch(
            f"/api/appointments/{appt.public_id}/status/", {"status": "confirmed"})

        self._assert_precondition_required(response)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")
        # Ni la transición ni su rastro de auditoría.
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), 0)

    def test_edit_reason_without_precondition_is_rejected(self):
        """Ni siquiera un campo inofensivo: el gate es de la vía, no del campo.

        Distinguir «campos peligrosos» de «campos inocuos» sería una segunda
        regla que mantener, y el primer campo mal clasificado reabriría el
        hueco entero.
        """
        appt = self._create_appt(days=3, hour=19)
        response = self.client.patch(
            f"/api/appointments/{appt.public_id}/", {"reason": "otro motivo"})

        self._assert_precondition_required(response)
        appt.refresh_from_db()
        self.assertEqual(appt.reason, "vacuna")   # el motivo original, intacto

    def test_with_the_precondition_everything_still_works(self):
        """La contraparte: quien la declara opera con normalidad."""
        appt = self._create_appt(days=3, hour=18)
        for target in ("confirmed", "in_progress", "done"):
            with self.subTest(target=target):
                appt.refresh_from_db()
                response = self.client.patch(
                    f"/api/appointments/{appt.public_id}/status/",
                    {"status": target, "expected_state": self._state_of(appt)},
                    format="json")
                self.assertEqual(response.status_code, status.HTTP_200_OK,
                                 response.content)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "done")
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), 3)

    # El `DELETE` deprecado también exige precondición — dejarlo exento lo
    # convertiría en la puerta trasera del gate hasta su sunset. Lo cubre
    # `DeleteIsDeprecatedAndHonorsPreconditionTests`
    # ::test_delete_without_precondition_is_rejected_too,
    # junto al resto del contrato de esa vía; no se duplica aquí.

    def test_assign_patient_without_precondition_is_rejected(self):
        """Vincular paciente muta la cita y escribe auditoría → entra al gate,
        aunque no mueva la tupla de agenda (por eso está fuera de INV-D)."""
        from apps.patients.utils import get_or_create_generic_patient

        _, generic_pet = get_or_create_generic_patient(self.org)
        appt = self._create_appt(days=3, hour=22)
        Appointment.objects.filter(pk=appt.pk).update(pet=generic_pet)

        response = self.client.patch(
            f"/api/appointments/{appt.public_id}/assign-patient/",
            {"pet": self.pet.id}, format="json")

        self._assert_precondition_required(response)
        appt.refresh_from_db()
        self.assertEqual(appt.pet_id, generic_pet.pk)   # cero escrituras
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), 0)

    def test_invalid_transition_still_400_when_declared(self):
        """La precondición no sustituye a las reglas de negocio."""
        appt = self._create_appt(days=3, hour=20)
        response = self.client.patch(
            f"/api/appointments/{appt.public_id}/status/",
            {"status": "done", "expected_state": self._state_of(appt)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotEqual(response.json().get("code"), "precondition_required")


class ConcurrentWritersTests(TransactionTestCase):
    """P1-14 — hay LOCK, no solo comparación. PostgreSQL, dos conexiones.

    Dos escrituras concurrentes con el MISMO `expected_state` (ambas correctas
    en el momento de leer): exactamente una escribe, la otra recibe 409. Sin el
    `select_for_update()` las dos compararían contra el estado viejo y las dos
    escribirían — que es el bug que INV-A existe para cerrar.
    """
    reset_sequences = True

    def setUp(self):
        self.org, self.admin, self.vet, self.pet = _seed_org("Concurrencia INV-A", "c")
        date, start, end = _slot(days=3, hour=9)
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post("/api/appointments/", {
            "pet": self.pet.id, "veterinarian": self.vet.id,
            "date": date, "start_time": start, "end_time": end, "reason": "vacuna",
        })
        assert response.status_code == status.HTTP_201_CREATED, response.content
        self.appt = Appointment.objects.get(public_id=response.json()["public_id"])
        self.expected = {
            "status": self.appt.status,
            "date": self.appt.date.isoformat(),
            "start_time": self.appt.start_time.strftime("%H:%M"),
        }

    def tearDown(self):
        connection.close()

    def test_two_writers_same_expected_state_only_one_wins(self):
        barrier = threading.Barrier(2)
        results = {}

        def writer(name, target):
            client = APIClient()
            client.force_authenticate(self.admin)
            try:
                barrier.wait(timeout=10)
                response = client.patch(
                    f"/api/appointments/{self.appt.public_id}/status/",
                    {"status": target, "expected_state": self.expected},
                    format="json",
                )
                results[name] = response.status_code
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=writer, args=("a", "confirmed")),
            threading.Thread(target=writer, args=("b", "canceled")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        codes = sorted(results.values())
        self.assertEqual(codes, [status.HTTP_200_OK, status.HTTP_409_CONFLICT], results)

        # Una sola transición efectiva y una sola fila de auditoría.
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=self.appt).count(), 1)
