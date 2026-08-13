"""
test_vet_lock_race.py — bloqueador conocido de F0 (ADR p57).

`PATCH` de detalle, `/status/` y `DELETE` resolvían la cita con
`get_object()`/`resolve_public_id()` ANTES de abrir el `atomic()` que
escribe. Si una reasignación de veterinario de la MISMA cita confirmaba en
esa ventana, `lock_veterinarians` bloqueaba el veterinario VIEJO: la
escritura que seguía quedaba SIN serializar contra el veterinario REAL — el
hueco por el que se cuela el deadlock (40P01) que `lock_veterinarians` existe
para prevenir.

La ventana real (entre la lectura pre-atomic de la vista y el lock) es
demasiado ancha para depender de timing de hilos en un test — pero también
demasiado indeterminista para reproducirla de forma confiable así. Estas
pruebas van directo al mecanismo:

  1. Nivel de servicio: fuerza la carrera exacta (peek → reasignación
     concurrente confirmada → lock) inyectando la escritura competidora en el
     punto exacto donde el peek deja de ser válido, y comprueba que
     `lock_appointment_and_veterinarians` la detecta (`VeterinarianLockRace`)
     en vez de bloquear en silencio el veterinario equivocado.
  2. Nivel de vista: la MISMA inyección, pero a través de los tres endpoints
     reales (`PATCH` detalle, `/status/`, `DELETE`) — confirma que el
     reintento (`retry_on_vet_lock_race`) hace la corrección transparente
     para el llamador: nunca un 500, y el resultado queda serializado contra
     el veterinario REAL (no el viejo).

PostgreSQL, como el resto de la suite de INV-D/INV-A: el mecanismo bajo
prueba es `select_for_update()` + una restricción de exclusión reales.
"""
import threading
from datetime import timedelta
from unittest import mock

from django.test import TransactionTestCase
from django.db import connections, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITransactionTestCase

from apps.appointments.models import Appointment, AppointmentStatusChange
from apps.appointments import services as appt_services
from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _slot(days=3, hour=10):
    day = (timezone.now() + timedelta(days=days)).date()
    return day.isoformat(), f"{hour:02d}:00", f"{hour:02d}:30"


def _seed(name, suffix):
    org = Organization.objects.create(name=name, timezone="UTC")
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    role, _ = Role.objects.get_or_create(
        name="ADMIN", organization=org, defaults={"is_system_role": True})
    role.permissions.set([wildcard])

    admin = User.objects.create_user(
        username=f"race_admin_{suffix}", password="p", organization=org, role="ADMIN")
    UserRole.objects.get_or_create(user=admin, role=role)
    vet1 = User.objects.create_user(
        username=f"race_vet1_{suffix}", password="p", organization=org, role="VET")
    UserRole.objects.get_or_create(user=vet1, role=role)
    vet2 = User.objects.create_user(
        username=f"race_vet2_{suffix}", password="p", organization=org, role="VET")
    UserRole.objects.get_or_create(user=vet2, role=role)

    owner = Owner.objects.create(organization=org, name="Ana", phone="5511110099")
    pet = Pet.objects.create(
        organization=org, owner=owner, name="Luna",
        species="perro", birth_date="2021-01-01")
    return org, admin, vet1, vet2, pet


def _reassign_directly(appointment_pk, new_vet_id):
    """Reasigna el veterinario de la cita en una conexión y transacción
    INDEPENDIENTES, con COMMIT real antes de retornar — simula el commit
    concurrente que corre entre el peek y el lock de la petición bajo prueba.

    Tiene que ser una conexión de verdad, no un `transaction.atomic()`
    anidado en la conexión del caller: eso sería solo un SAVEPOINT, y un
    rollback del caller (p.ej. porque la prueba espera que
    `VeterinarianLockRace` propague) se llevaría la "reasignación" con él —
    dejando de probar lo que dice probar. Mismo patrón de
    `test_no_overlap.py`/`test_preconditions.py`: hilo propio, conexión
    propia, `connections.close_all()` al terminar.
    """
    outcome = {}

    def _run():
        try:
            Appointment.objects.filter(pk=appointment_pk).update(veterinarian_id=new_vet_id)
        except BaseException as exc:  # noqa: BLE001 — reportar, nunca tragar
            outcome['error'] = exc
        finally:
            connections.close_all()

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        raise RuntimeError('_reassign_directly: el hilo no terminó en 10s.')
    if 'error' in outcome:
        # Un hilo Python que muere en silencio (excepción no capturada) solo
        # imprime a stderr — el hilo principal seguiría creyendo que la
        # reasignación ocurrió. Re-lanzar aquí es lo que convierte «la
        # carrera no se armó como se esperaba» en un fallo de test legible,
        # en vez de un falso negativo silencioso.
        raise outcome['error']


class LockAppointmentAndVeterinariansServiceTests(TransactionTestCase):
    """Nivel de servicio — fuerza la carrera exacta contra el helper."""

    def setUp(self):
        self.org, self.admin, self.vet1, self.vet2, self.pet = _seed(
            "VetLockRace Service", "svc")
        date, start, end = _slot(days=3, hour=9)
        self.appt = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet1,
            date=date, start_time=start, end_time=end,
            start_datetime=timezone.now() + timedelta(days=3),
            end_datetime=timezone.now() + timedelta(days=3, minutes=30),
            reason="consulta", status="scheduled",
        )

    def test_race_between_peek_and_lock_is_detected_not_silently_wrong(self):
        """El peek ve vet1; ANTES de que `lock_veterinarians` corra, otra
        transacción reasigna a vet2 y confirma. El helper debe levantar
        `VeterinarianLockRace` — nunca bloquear vet1 en silencio y proceder
        como si el veterinario real siguiera siendo vet1."""
        real_lock_veterinarians = appt_services.lock_veterinarians

        def _racing_lock_veterinarians(organization_id, *veterinarian_ids):
            # En el momento en que el helper va a bloquear lo que el peek
            # encontró (vet1), la reasignación concurrente YA confirmó.
            _reassign_directly(self.appt.pk, self.vet2.pk)
            return real_lock_veterinarians(organization_id, *veterinarian_ids)

        with mock.patch.object(
            appt_services, 'lock_veterinarians', side_effect=_racing_lock_veterinarians,
        ):
            with self.assertRaises(appt_services.VeterinarianLockRace):
                with transaction.atomic():
                    appt_services.lock_appointment_and_veterinarians(
                        self.appt, self.org.pk,
                    )

        # La reasignación concurrente sí quedó (era una escritura legítima,
        # ya confirmada, de otro actor).
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.veterinarian_id, self.vet2.pk)

    def test_retry_recovers_and_locks_the_real_veterinarian(self):
        """`retry_on_vet_lock_race`: el primer intento pierde la carrera: el
        SEGUNDO peek ya ve vet2 (la reasignación ya confirmó) y no hay
        carrera que perder — converge sin necesitar ayuda externa."""
        real_lock_veterinarians = appt_services.lock_veterinarians
        call_count = {"n": 0}

        def _race_once_then_stop(organization_id, *veterinarian_ids):
            call_count["n"] += 1
            if call_count["n"] == 1:
                _reassign_directly(self.appt.pk, self.vet2.pk)
            return real_lock_veterinarians(organization_id, *veterinarian_ids)

        def _do():
            with transaction.atomic():
                return appt_services.lock_appointment_and_veterinarians(
                    self.appt, self.org.pk,
                )

        with mock.patch.object(
            appt_services, 'lock_veterinarians', side_effect=_race_once_then_stop,
        ):
            locked = appt_services.retry_on_vet_lock_race(_do)

        self.assertEqual(locked.veterinarian_id, self.vet2.pk)
        # Un intento perdido + un intento ganador.
        self.assertEqual(call_count["n"], 2)

    def test_persistent_race_is_not_silently_swallowed(self):
        """Si la carrera se repite en TODOS los intentos permitidos, se deja
        propagar — nunca se disfraza de resultado de negocio ni se reintenta
        para siempre (mismo criterio que un deadlock 40P01 persistente)."""
        real_lock_veterinarians = appt_services.lock_veterinarians
        toggle = {"vet": self.vet1.pk}  # valor real inicial (seed de setUp)

        def _always_race(organization_id, *veterinarian_ids):
            # Cada vez que se va a bloquear, la reasignación YA corrió hacia
            # el OTRO veterinario del que el peek de ESTE intento acaba de
            # ver — así el mismatch se repite en cada intento. `toggle["vet"]`
            # rastrea el valor REAL vigente (empieza en vet1, el seed
            # inicial): reasignar siempre al opuesto de eso garantiza que
            # diverja del peek que se acaba de hacer.
            other = self.vet2.pk if toggle["vet"] == self.vet1.pk else self.vet1.pk
            _reassign_directly(self.appt.pk, other)
            toggle["vet"] = other
            return real_lock_veterinarians(organization_id, *veterinarian_ids)

        def _do():
            with transaction.atomic():
                return appt_services.lock_appointment_and_veterinarians(
                    self.appt, self.org.pk,
                )

        with mock.patch.object(
            appt_services, 'lock_veterinarians', side_effect=_always_race,
        ):
            with self.assertRaises(appt_services.VeterinarianLockRace):
                appt_services.retry_on_vet_lock_race(_do)


class ViewLevelRaceRecoveryTests(APITransactionTestCase):
    """Nivel de vista — la MISMA inyección, a través de los tres endpoints.

    `APITransactionTestCase`, no `APITestCase`: el racer necesita una
    conexión de verdad que vea (y comprometa) sus propios cambios de forma
    independiente. `APITestCase` envuelve la prueba entera en una transacción
    que nunca se confirma — una segunda conexión no vería ni la cita creada
    por `self.client.post(...)`.

    No es una prueba de concurrencia real (timing de hilos): fuerza la
    carrera exacta que la ventana pre-atomic dejaba pasar, y comprueba que el
    reintento automático la absorbe. Nunca un 500; el estado final queda
    serializado contra el veterinario REAL.
    """

    def setUp(self):
        self.org, self.admin, self.vet1, self.vet2, self.pet = _seed(
            "VetLockRace View", "view")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _create_appt(self, vet, days=3, hour=9):
        date, start, end = _slot(days, hour)
        response = self.client.post("/api/appointments/", {
            "pet": self.pet.id, "veterinarian": vet.id,
            "date": date, "start_time": start, "end_time": end, "reason": "consulta",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return Appointment.objects.get(public_id=response.json()["public_id"])

    def _precondition(self, appt):
        """INV-A: la precondición es obligatoria en las tres vías (Fase 3).

        Se construye desde la cita tal como la vio el llamador. La carrera que
        estas pruebas inyectan reasigna el **veterinario**, que NO forma parte
        de la tupla (`status`, `date`, `start_time`): la precondición sigue
        siendo válida y la escritura procede. Es el comportamiento buscado —
        INV-A protege la decisión de agenda del usuario, no la asignación
        interna de recursos, que es justo lo que INV-D serializa aparte.
        """
        return {"expected_state": {
            "status": appt.status,
            "date": appt.date.isoformat(),
            "start_time": appt.start_time.strftime("%H:%M"),
        }}

    def _race_once(self, appt_pk, new_vet_id):
        """Parchea `lock_veterinarians` para que, la PRIMERA vez que se
        invoque dentro de la request bajo prueba, otra transacción reasigne
        la cita y confirme antes de que el lock proceda. Devuelve el
        contextmanager del patch (usar como `with`)."""
        real = appt_services.lock_veterinarians
        state = {"raced": False}

        def _side_effect(organization_id, *veterinarian_ids):
            if not state["raced"]:
                state["raced"] = True
                _reassign_directly(appt_pk, new_vet_id)
            return real(organization_id, *veterinarian_ids)

        return mock.patch.object(appt_services, 'lock_veterinarians', side_effect=_side_effect)

    def test_patch_detail_survives_the_race_and_serializes_against_the_real_vet(self):
        """Reasignación de vet1→vet2 confirmada ENTRE el peek y el lock del
        PATCH (que solo edita `reason`, no toca `veterinarian`). Sin la
        corrección, el lock habría caído sobre vet1 (stale) — con ella, el
        reintento converge y el PATCH queda correctamente serializado contra
        vet2 (el real). Nunca un 500; el estado final refleja vet2."""
        appt = self._create_appt(self.vet1, hour=10)

        with self._race_once(appt.pk, self.vet2.pk):
            response = self.client.patch(
                f"/api/appointments/{appt.public_id}/",
                {"reason": "motivo actualizado", **self._precondition(appt)},
                format="json",
            )

        self.assertNotEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR,
                             response.content)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        appt.refresh_from_db()
        self.assertEqual(appt.veterinarian_id, self.vet2.pk)
        self.assertEqual(appt.reason, "motivo actualizado")

    def test_the_race_helper_cannot_fabricate_an_overlap_inv_d_forbids(self):
        """`_reassign_directly` escribe crudo (sin `lock_veterinarians`), pero
        sigue siendo una escritura real bajo la restricción de exclusión: si
        el destino ya está ocupado, INV-D la rechaza igual que a cualquier
        otro escritor. Ancla que el harness de estas pruebas no puede montar
        un escenario que el propio dominio prohíbe — si esto pasara a
        silenciarse, las pruebas de arriba dejarían de probar una carrera
        real sin que nadie lo notara."""
        appt = self._create_appt(self.vet1, hour=11)
        self._create_appt(self.vet2, hour=11)  # ocupa vet2 en ese hueco

        with self.assertRaises(appt_services.NO_OVERLAP_EXCEPTIONS):
            _reassign_directly(appt.pk, self.vet2.pk)

    def test_status_endpoint_survives_the_race(self):
        appt = self._create_appt(self.vet1, hour=11)

        with self._race_once(appt.pk, self.vet2.pk):
            response = self.client.patch(
                f"/api/appointments/{appt.public_id}/status/",
                {"status": "confirmed", **self._precondition(appt)},
                format="json",
            )

        self.assertNotEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR,
                             response.content)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")
        self.assertEqual(appt.veterinarian_id, self.vet2.pk)
        # Una sola fila de auditoría: el reintento no duplicó la transición.
        self.assertEqual(
            AppointmentStatusChange.objects.filter(appointment=appt).count(), 1)

    def test_delete_survives_the_race(self):
        appt = self._create_appt(self.vet1, hour=12)

        with self._race_once(appt.pk, self.vet2.pk):
            response = self.client.delete(
                f"/api/appointments/{appt.public_id}/",
                self._precondition(appt), format="json",
            )

        self.assertNotEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR,
                             response.content)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")
        self.assertEqual(appt.veterinarian_id, self.vet2.pk)
        self.assertEqual(
            AppointmentStatusChange.objects.filter(
                appointment=appt, to_status="canceled").count(), 1)
