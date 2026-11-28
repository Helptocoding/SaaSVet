"""
P1-8 — seed_demo_clinic

Crea (o reconstruye/elimina) un tenant demo realista DENTRO del SaaS real, como
una Organization normal marcada con `is_demo=True`. Sirve para mostrar el producto
y para que testers exploren flujos reales sin pantallas vacías.

Principios:
  - Idempotente: re-correr no duplica (catálogo/personas por get_or_create con
    clave determinística; las operaciones transaccionales solo se construyen si
    aún no existen).
  - Respeta invariantes: reusa los servicios autoritativos
    (provision_organization, apply_stock_movement, billing.services) en vez de
    escribir stock/anchors/payments a mano. La ÚNICA escritura directa permitida
    es el backdating de fechas (created_at/anchors/occurred_at) para que el
    dashboard tenga histórico — documentado e inofensivo (mantiene la
    consistencia status↔anchor que exigen los CHECK).
  - Seguro en producción: --reset y --delete SOLO afectan organizations con
    is_demo=True; abortan si hay 0 o >1 demo; exigen --yes.

Uso:
    python manage.py seed_demo_clinic
    python manage.py seed_demo_clinic --reset --yes
    python manage.py seed_demo_clinic --delete --yes
    python manage.py seed_demo_clinic --actor-username <admin_saas>

Tras el seed, correr `build_daily_metrics` para poblar el histórico de analytics.
"""
import logging
import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from time import monotonic
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.organizations.models import Organization, OrganizationSettings
from apps.patients.models import Owner, Pet
from apps.appointments.models import Appointment, AppointmentStatusChange
from apps.medical_records.models import (
    MedicalRecord, MedicalRecordService, VitalSigns, VaccineRecord,
)
from apps.inventory.models import (
    Product, Presentation, StockMovement, MedicalRecordProduct,
)
from apps.inventory.services import apply_stock_movement
from apps.billing.models import (
    Service, Checkout, Invoice, InvoiceItem, Payment,
)
from apps.billing.checkout_services import (
    add_checkout_item, create_direct_sale_checkout,
    get_or_create_primary_checkout_for_medical_record, post_checkout,
    record_clinical_charge_delta,
)
from apps.cash.models import CashSession, CashMovement
from apps.core.models import Permission, Role
from apps.core.permissions_codes import role_grants
from apps.platform.deletion_guards import demo_purge_authorized
from apps.platform.services.provision_organization import provision_organization

from ._demo_data import (
    DEMO_ORG_NAME, DEMO_TIMEZONE, DEMO_TAX_RATE, DEMO_PASSWORD, DEMO_USERS,
    DEMO_ORG_CONTACT,
    DEMO_SERVICES, DEMO_PRODUCTS, OWNER_NAMES, PET_NAMES, BREEDS,
    SPECIES_WEIGHTS, CONSULTATION_TEMPLATES,
)

User = get_user_model()

logger = logging.getLogger('apps.core.demo_reset')

# Productos seguros para venta directa (stock holgado — nunca los deliberadamente
# bajos, que existen solo para poblar "stock crítico").
SALE_PRODUCT_NAMES = [
    "Alimento perro adulto 15kg", "Alimento gato adulto 3kg", "Lata alimento húmedo",
    "Shampoo medicado", "Collar antipulgas", "Juguete mordedera", "Arena sanitaria 5kg",
    "Antiparasitario interno", "Antipulgas pipeta",
]


class Command(BaseCommand):
    help = "Crea/reconstruye/elimina el tenant demo (is_demo=True). P1-8."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Borra los datos de la org demo y la reconstruye (guard is_demo).")
        parser.add_argument("--delete", action="store_true",
                            help="Elimina por completo la org demo, incluidos usuarios (guard is_demo).")
        parser.add_argument("--yes", action="store_true",
                            help="Confirma operaciones destructivas (--reset/--delete).")
        parser.add_argument("--actor-username", default=None,
                            help="Username del superusuario que provisiona la org (default: primer superuser).")

    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        self.rnd = random.Random(1808)
        self.tz = ZoneInfo(DEMO_TIMEZONE)
        self.now = timezone.now()
        # INV-D (ADR p57): huecos ACTIVOS ya reservados, por veterinario. El
        # demo siembra decenas de citas al azar para un único VET; antes una
        # colisión era solo un dato feo, ahora es un IntegrityError que tumba el
        # seed — y con él, el reset automático del tenant demo (ADR p49).
        self._busy_slots = {}

        if opts["delete"]:
            self._delete_demo(opts["yes"])
            return
        if opts["reset"]:
            self._reset_demo(opts["yes"])
            return

        org = self._ensure_org(opts["actor_username"])
        self._ensure_org_contact(org)
        users = self._ensure_users(org)
        self._accept_legal_for_demo_users(users)
        self._restrict_demo_import(org)
        self._ensure_catalog(org)
        self._ensure_people(org)

        if not Appointment.all_objects.filter(organization=org).exists():
            self._build_operations(org, users)
        else:
            self.stdout.write("Operaciones ya existen — se omite (idempotente). "
                              "Usa --reset --yes para reconstruir.")

        self._report(org)

    # ------------------------------------------------------------------ #
    # Guards / resolución de la org demo
    # ------------------------------------------------------------------ #
    def _demo_org_or_abort(self):
        demos = Organization.objects.filter(is_demo=True)
        n = demos.count()
        if n == 0:
            raise CommandError("No existe ninguna organización demo (is_demo=True).")
        if n > 1:
            raise CommandError(
                f"Hay {n} organizaciones con is_demo=True — abortando por seguridad. "
                "Resuelve manualmente cuál es la demo."
            )
        return demos.first()

    def _ensure_org(self, actor_username):
        existing = Organization.objects.filter(is_demo=True)
        if existing.count() > 1:
            raise CommandError("Hay >1 organización demo — abortando.")
        if existing.exists():
            org = existing.first()
            self.stdout.write(f"Org demo existente: «{org.name}» (id={org.pk}).")
            return org

        actor = None
        if actor_username:
            actor = User.objects.filter(username=actor_username).first()
            if actor is None:
                raise CommandError(f"No existe el usuario --actor-username={actor_username}.")
        if actor is None:
            actor = User.objects.filter(is_superuser=True).order_by("pk").first()
        if actor is None:
            raise CommandError(
                "No hay superusuario para provisionar la org. Crea uno con "
                "`createsuperuser` o pasa --actor-username."
            )

        admin = DEMO_USERS[0]
        result = provision_organization(
            actor=actor,
            validated_data={
                "name": DEMO_ORG_NAME,
                "timezone": DEMO_TIMEZONE,
                "tax_rate": Decimal(DEMO_TAX_RATE),
                "admin_username": admin["username"],
                "admin_email": admin["email"],
                "admin_password": DEMO_PASSWORD,
                "admin_first_name": admin["first_name"],
                "admin_last_name": admin["last_name"],
            },
            # Demo de login compartido: el admin demo NO debe quedar gateado por
            # MustChangePasswordGate (rompería el login con la contraseña común).
            require_password_change=False,
        )
        org = result.organization
        org.is_demo = True
        org.save()
        self.stdout.write(self.style.SUCCESS(
            f"Org demo creada: «{org.name}» (id={org.pk}), admin={result.admin.username}."
        ))
        return org

    def _ensure_org_contact(self, org):
        """Datos de contacto de la clínica demo — idempotente y no destructivo.

        Solo rellena los campos VACÍOS: si alguien capturó un dato real en la
        demo, el seed no lo pisa. Sobrevive al reset porque el purge (ADR p49)
        borra el subgrafo operativo, no la fila `Organization`.

        Por qué existe: sin `phone`, el hito `has_clinic_contact` del endpoint de
        activación es False → la demo arranca con el overlay de onboarding encima.
        """
        changed = []
        for field, value in DEMO_ORG_CONTACT.items():
            if (getattr(org, field, '') or '').strip():
                continue
            setattr(org, field, value)
            changed.append(field)
        if changed:
            org.save(update_fields=changed)
            self.stdout.write(f"Contacto demo sembrado: {', '.join(changed)}.")

    def _ensure_users(self, org):
        for u in DEMO_USERS:
            if User.objects.filter(username=u["username"]).exists():
                continue
            if u["role"] == "ADMIN":
                continue  # lo crea provision_organization
            User.objects.create_user(
                username=u["username"],
                email=u["email"],
                password=DEMO_PASSWORD,
                first_name=u["first_name"],
                last_name=u["last_name"],
                role=u["role"],
                organization=org,
                is_active=True,
            )
            self.stdout.write(f"  usuario creado: {u['username']} ({u['role']})")
        # M01 (orden 7): la demo cierra consultas y emite recetas, y quien firma
        # necesita cédula. Solo rellena la vacía: no pisa una capturada a mano.
        for u in DEMO_USERS:
            if u.get("license_number"):
                User.objects.filter(username=u["username"], license_number="").update(
                    license_number=u["license_number"])
        return {
            "admin": User.objects.get(username=DEMO_USERS[0]["username"]),
            "vet": User.objects.get(username=DEMO_USERS[1]["username"]),
            "recepcion": User.objects.get(username=DEMO_USERS[2]["username"]),
        }

    def _accept_legal_for_demo_users(self, users):
        """
        Pre-acepta los documentos legales vigentes para los usuarios demo, de
        modo que el LegalAcceptanceGate (ADR p46) NO rompa el login compartido
        del demo (espejo de la decisión require_password_change=False para el
        admin demo). No-op si aún no hay documentos `is_current`. Idempotente.
        """
        from apps.legal.services import current_required_documents, record_acceptances
        for u in users.values():
            docs = list(current_required_documents(u))
            if docs:
                record_acceptances(user=u, documents=docs, user_agent='seed_demo_clinic')

    def _restrict_demo_import(self, org):
        """
        Deshabilita la importación de datos para los usuarios demo.

        Import = operación sensible (alta masiva de clientes/mascotas). En el demo
        privado los testers no deben poder migrar datos. `role_grants` es la misma
        fuente que usa `seed_permissions`, así que un release no revierte esta resta.

        Efecto (ambos lados, ver apps/core/permissions.py):
          - backend HybridPermission usa los perms de DB → 403 en `import.*`.
          - /api/me build_permissions_list no incluye `import.*` → sin CTA en frontend.

        Scoped a la org demo (los roles son por organización). Idempotente.
        """
        for role_name in ("ADMIN", "VET", "ASSISTANT"):
            role = Role.objects.filter(
                organization=org, name=role_name, is_system_role=True
            ).first()
            if role:
                role.permissions.set([
                    Permission.objects.get_or_create(code=code)[0]
                    for code in role_grants(role_name, is_demo=True)
                ])

    # ------------------------------------------------------------------ #
    # Catálogo: servicios + productos + stock inicial
    # ------------------------------------------------------------------ #
    def _ensure_catalog(self, org):
        for s in DEMO_SERVICES:
            Service.objects.get_or_create(
                organization=org, name=s["name"],
                defaults={"base_price": Decimal(s["base_price"])},
            )

        for idx, p in enumerate(DEMO_PRODUCTS):
            code = f"DEMO-P-{idx:03d}"
            product, created = Product.objects.get_or_create(
                organization=org, internal_code=code,
                defaults={
                    "name": p["name"],
                    "category": p["category"],
                    "requires_prescription": p["requires_prescription"],
                    "base_unit": p["base_unit"],
                    "min_stock": Decimal(p["min_stock_base"]),
                },
            )
            pres_def = p["presentation"]
            pres, _ = Presentation.objects.get_or_create(
                product=product, name=pres_def["name"],
                defaults={
                    "organization": org,
                    "base_unit": p["base_unit"],
                    "sale_price": Decimal(pres_def["sale_price"]),
                    "conversion_factor": Decimal(pres_def["conversion_factor"]),
                    "quantity": Decimal(pres_def["conversion_factor"]),
                    "stock": Decimal("0"),
                    "min_stock": Decimal("0"),
                },
            )
            # Existencia inicial solo en el primer alta (idempotente: no re-aplica
            # ni duplica StockMovement en re-runs). 'adjustment' fija el absoluto.
            if created:
                with transaction.atomic():
                    apply_stock_movement(
                        presentation=pres,
                        quantity=Decimal(p["initial_stock_base"]),
                        movement_type="adjustment",
                        organization=org,
                        reason="Existencia inicial (demo)",
                    )

    # ------------------------------------------------------------------ #
    # Personas: owners + pets
    # ------------------------------------------------------------------ #
    def _ensure_people(self, org):
        for idx, name in enumerate(OWNER_NAMES):
            legacy = f"DEMO-OWN-{idx:03d}"
            phone = f"55{1000000 + idx * 13:08d}"[:10]
            Owner.objects.get_or_create(
                organization=org, legacy_id=legacy,
                defaults={"name": name, "phone": phone},
            )

        owners = list(
            Owner.objects.filter(organization=org, is_generic=False).order_by("legacy_id")
        )
        for idx in range(65):
            legacy = f"DEMO-PET-{idx:03d}"
            species = SPECIES_WEIGHTS[idx % len(SPECIES_WEIGHTS)]
            breed = self.rnd.choice(BREEDS[species])
            owner = owners[idx % len(owners)]
            age_days = self.rnd.randint(120, 4500)
            birth = (self.now - timedelta(days=age_days)).date()
            sex = self.rnd.choice(["male", "female", "unknown"])
            Pet.objects.get_or_create(
                organization=org, legacy_id=legacy,
                defaults={
                    "name": PET_NAMES[idx % len(PET_NAMES)],
                    "species": species,
                    "breed": breed,
                    "birth_date": birth,
                    "sex": sex,
                    "owner": owner,
                },
            )

    # ------------------------------------------------------------------ #
    # Operaciones: caja, citas, consultas, ventas (flujos reales)
    # ------------------------------------------------------------------ #
    def _build_operations(self, org, users):
        vet = users["vet"]
        recepcion = users["recepcion"]
        pets = list(Pet.objects.filter(organization=org, is_generic=False).order_by("legacy_id"))
        owners = list(Owner.objects.filter(organization=org, is_generic=False).order_by("legacy_id"))
        services = {s.name: s for s in Service.objects.filter(organization=org)}
        products = {
            pr.name: pr for pr in
            Product.objects.filter(organization=org).prefetch_related("presentations")
        }

        # Caja abierta de HOY para CADA usuario que cobra. `pay_invoice` resuelve
        # la sesión por `opened_by=actor` (ADR p28/p39), así que con
        # `require_open_cash_session=True` —encendido en la demo— un actor sin
        # turno propio revienta el cobro. Abajo se cobra con recepción (lo de hoy)
        # y con el veterinario (lo histórico): ambos necesitan turno.
        #
        # NO reducir a una sola sesión compartida: el turno es por usuario (el
        # cierre Z reconcilia el cajón de UNA persona). Sin la del veterinario, el
        # reset fallaba en el primer cobro histórico y hacía ROLLBACK completo —
        # la demo llevaba ~24 días sin resetearse.
        cash_session = CashSession.objects.create(
            organization=org, opened_by=recepcion, opened_at=self.now,
            opening_float=Decimal("500.00"), status="open",
        )
        CashSession.objects.create(
            organization=org, opened_by=vet, opened_at=self.now,
            opening_float=Decimal("500.00"), status="open",
        )
        org_settings, _ = OrganizationSettings.objects.get_or_create(organization=org)
        org_settings.allow_post_unpaid = True
        org_settings.save(update_fields=['allow_post_unpaid'])

        # --- 45 consultas cerradas (con cita 'done') -----------------------
        sample = self.rnd.sample(pets, min(45, len(pets)))
        for i, pet in enumerate(sample):
            tmpl = CONSULTATION_TEMPLATES[i % len(CONSULTATION_TEMPLATES)]
            is_today = i < 5
            days_ago = 0 if is_today else self.rnd.randint(1, 60)
            when = self.now - timedelta(days=days_ago, hours=self.rnd.randint(0, 6))
            actor = recepcion if is_today else vet

            appt = self._make_appointment(org, pet, vet, when, "done", tmpl["reason"])
            checkout, mr = self._build_consultation(org, pet, vet, appt, tmpl, when, close=True)

            # Outcome futuro: mayoría pagadas y algunas deudas emitidas.
            outcome = self.rnd.choices(
                ["paid", "posted"], weights=[85, 15], k=1
            )[0]
            invoice = None
            if outcome == "paid":
                method = self.rnd.choices(
                    ["cash", "card", "transfer"], weights=[60, 30, 10], k=1
                )[0]
                invoice = post_checkout(
                    checkout, actor, payment_method=method,
                    expected_version=checkout.version,
                    idempotency_key=f'demo-consultation-pay-{mr.pk}',
                )
            elif outcome == "posted":
                invoice = post_checkout(
                    checkout, actor, expected_version=checkout.version,
                    idempotency_key=f'demo-consultation-post-{mr.pk}',
                    due_at=self.now + timedelta(days=30),
                    credit_reason='demo_authorized_credit',
                    obligation_evidence={
                        'basis': 'customer_acknowledgement',
                        'accepting_party': pet.owner.name,
                        'channel': 'in_person',
                    },
                )

            self._backdate_invoice(invoice, when)
            self._backdate_mr(mr, when)

        # --- 5 consultas ABIERTAS (backlog clínico) ------------------------
        # Las 2 primeras se anclan a "ahora" (hoy, hace 5–40 min) → el tag
        # "Ahora/En consulta" del dashboard coincide con el reloj a cualquier hora
        # (cada reset las regenera). Las otras 3 quedan abiertas de días previos
        # → pueblan "Pendientes clínicos" sin salir como "Ahora".
        open_pets = self.rnd.sample(pets, 5)
        now_local = self.now.astimezone(self.tz)
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        for i, pet in enumerate(open_pets):
            tmpl = CONSULTATION_TEMPLATES[i % len(CONSULTATION_TEMPLATES)]
            if i < 2:
                # Las dos se separan 45 min (INV-D: 30 min de slot por cita del
                # mismo VET). Siguen siendo de HOY y en `in_progress`, así que
                # el dashboard las sigue mostrando como "En consulta".
                start_local = now_local - timedelta(
                    minutes=self.rnd.randint(5, 40) + i * 45)
                if start_local < day_start + timedelta(minutes=1):
                    start_local = day_start + timedelta(minutes=1)  # mantener HOY
                when = start_local
                appt = self._make_appointment(
                    org, pet, vet, when, "in_progress", tmpl["reason"],
                    start_override=start_local,
                )
            else:
                when = self.now - timedelta(days=self.rnd.randint(1, 3))
                appt = self._make_appointment(org, pet, vet, when, "in_progress", tmpl["reason"])
            # Algunas sin diagnóstico → grupo "sin diagnóstico" del dashboard.
            no_dx = (i % 2 == 0)
            _, mr = self._build_consultation(
                org, pet, vet, appt, tmpl, when, close=False, no_diagnosis=no_dx
            )
            self._backdate_mr(mr, when)

        # --- 15 ventas directas (POS) --------------------------------------
        for i in range(15):
            is_today = i < 3
            days_ago = 0 if is_today else self.rnd.randint(1, 45)
            when = self.now - timedelta(days=days_ago, hours=self.rnd.randint(0, 6))
            actor = recepcion if is_today else vet
            owner = self.rnd.choice(owners)
            checkout = create_direct_sale_checkout(
                organization=org, customer=owner, pet=None, user=actor,
            )
            n_items = self.rnd.randint(1, 2)
            chosen = self.rnd.sample(SALE_PRODUCT_NAMES, n_items)
            for pname in chosen:
                prod = products[pname]
                pres = prod.presentations.first()
                qty = Decimal(self.rnd.randint(1, 2))
                add_checkout_item(
                    checkout, actor, presentation=pres, quantity=qty,
                )
            checkout.refresh_from_db()
            method = self.rnd.choices(
                ["cash", "card", "transfer"], weights=[55, 35, 10], k=1
            )[0]
            invoice = post_checkout(
                checkout, actor, payment_method=method,
                expected_version=checkout.version,
                idempotency_key=f'demo-direct-sale-{i}',
            )
            self._backdate_invoice(invoice, when)

        # --- Citas futuras + perdidas (sin consulta) -----------------------
        future_pets = self.rnd.sample(pets, 20)
        for i, pet in enumerate(future_pets):
            when = self.now + timedelta(days=self.rnd.randint(1, 30), hours=self.rnd.randint(0, 6))
            status = self.rnd.choices(["scheduled", "confirmed"], weights=[70, 30], k=1)[0]
            self._make_appointment(org, pet, vet, when, status, "Cita programada")

        past_pets = self.rnd.sample(pets, 10)
        for i, pet in enumerate(past_pets):
            when = self.now - timedelta(days=self.rnd.randint(1, 20), hours=self.rnd.randint(0, 6))
            status = self.rnd.choices(["canceled", "no_show"], weights=[60, 40], k=1)[0]
            appt = self._make_appointment(org, pet, vet, when, status, "Cita no atendida")

        # Movimiento de caja de ejemplo (retiro a banco) en el turno abierto.
        CashMovement.objects.create(
            organization=org, cash_session=cash_session, movement_type="withdrawal",
            amount=Decimal("1000.00"), reason="Retiro a banco (demo)",
            occurred_at=self.now, actor=recepcion,
        )

    # ------------------------------------------------------------------ #
    # Helpers de construcción
    # ------------------------------------------------------------------ #
    # INV-D: estados que ocupan el hueco del veterinario. `done`, `canceled` y
    # `no_show` quedan fuera del predicado de la restricción → no reservan nada.
    ACTIVE_STATUSES = ("scheduled", "confirmed", "in_progress")
    SLOT = timedelta(minutes=30)

    def _reserve_slot(self, vet_pk, start_dt, tries=64):
        """Primer hueco de 30 min libre desde `start_dt`, ya reservado.

        Avanza de media hora en media hora. `tries` acota la búsqueda: si una
        agenda demo llegara a estar tan llena que no cabe, es mejor fallar
        ruidosamente aquí que sembrar una colisión que rompa la migración de
        cualquier entorno donde se restaure este dump.
        """
        taken = self._busy_slots.setdefault(vet_pk, [])
        for _ in range(tries):
            end_dt = start_dt + self.SLOT
            if all(start_dt >= busy_end or end_dt <= busy_start
                   for busy_start, busy_end in taken):
                taken.append((start_dt, end_dt))
                return start_dt
            start_dt += self.SLOT
        raise CommandError(
            "seed_demo_clinic: no se encontró hueco libre para el veterinario "
            f"{vet_pk} (INV-D). Revisa el volumen de citas sembradas."
        )

    def _make_appointment(self, org, pet, vet, when, status, reason, start_override=None):
        # start_override (datetime tz-aware): ancla la cita a un instante exacto
        # (p.ej. "ahora" para las consultas en curso → el tag "Ahora" del dashboard
        # coincide con el reloj). Sin él: hora aleatoria de horario laboral 9–17.
        if start_override is not None:
            start_dt = start_override
        else:
            hour = 9 + (self.rnd.randint(0, 8))
            start_dt = datetime.combine(when.date(), time(hour, 0), tzinfo=self.tz)
        if status in self.ACTIVE_STATUSES:
            start_dt = self._reserve_slot(vet.pk, start_dt)
        end_dt = start_dt + self.SLOT
        # No cruzar medianoche: start_time/end_time son TimeField naive y hay un
        # CHECK end_time > start_time. Si +30min cae al día siguiente, clamp a 23:59.
        if end_dt.date() != start_dt.date():
            end_dt = start_dt.replace(hour=23, minute=59, second=0, microsecond=0)
        return Appointment.objects.create(
            organization=org, pet=pet, veterinarian=vet,
            date=start_dt.date(), start_time=start_dt.time(), end_time=end_dt.time(),
            start_datetime=start_dt, end_datetime=end_dt,
            timezone_at_creation=org.timezone,
            reason=reason, status=status,
        )

    def _build_consultation(self, org, pet, vet, appt, tmpl, when, *, close, no_diagnosis=False):
        """Crea MR + cargos (servicio + producto) + vitales (+ cierre). Atómico."""
        weight = Decimal(str(round(self.rnd.uniform(2.0, 38.0), 2)))
        with transaction.atomic():
            mr = MedicalRecord.objects.create(
                organization=org, pet=pet, veterinarian=vet, appointment=appt,
                consultation_type=tmpl["type"], status="open",
            )

            # Servicio (no toca stock)
            svc = Service.objects.get(organization=org, name=tmpl["service"])
            mrs = MedicalRecordService.objects.create(
                organization=org, medical_record=mr, service=svc, quantity=1,
            )
            record_clinical_charge_delta(
                mrs, delta=Decimal('1'), user=vet,
                mutation_key=f'demo-service-{mr.pk}-{mrs.pk}',
            )

            # Producto consumido (descuenta stock vía MedicalRecordProduct.save)
            if tmpl["product"]:
                prod = Product.objects.get(organization=org, name=tmpl["product"])
                pres = prod.presentations.first()
                locked = Presentation.objects.select_for_update().get(pk=pres.pk)
                mrp = MedicalRecordProduct(
                    medical_record=mr, presentation=pres,
                    quantity=Decimal("1"), cost_behavior="charge",
                )
                mrp.save(locked_presentation=locked)
                record_clinical_charge_delta(
                    mrp, delta=Decimal('1'), user=vet,
                    mutation_key=f'demo-product-{mr.pk}-{mrp.pk}',
                )

            # Vitales
            VitalSigns.objects.create(
                medical_record=mr, weight=weight,
                temperature=Decimal(str(round(self.rnd.uniform(37.5, 39.5), 1))),
                heart_rate=self.rnd.randint(70, 140),
                respiratory_rate=self.rnd.randint(15, 35),
                recorded_by=vet, recorded_at=when,
            )

            # Datos clínicos (el peso vive solo en VitalSigns, M03)
            mr.diagnosis = "" if no_diagnosis else tmpl["diagnosis"]
            mr.treatment = tmpl["treatment"]
            if close:
                mr.status = "closed"
                mr.closed_at = when
                mr.closed_at_source = "service"
                mr.closed_by = vet
            mr.save()

            # Registro de vacuna si aplica
            if tmpl.get("vaccine"):
                VaccineRecord.objects.create(
                    organization=org, pet=pet, vaccine_name=tmpl["vaccine"],
                    application_date=when.date(),
                    next_due_date=(when + timedelta(days=365)).date(),
                    applied_by=vet, medical_record=mr,
                )
            checkout = (
                get_or_create_primary_checkout_for_medical_record(mr, owner=vet)
                if close else None
            )
        return checkout, mr

    # ------------------------------------------------------------------ #
    # Backdating (única escritura directa permitida — fechas, seed-only)
    # ------------------------------------------------------------------ #
    def _backdate_invoice(self, invoice, when):
        invoice.refresh_from_db()
        fields = {"created_at": when}
        if invoice.posted_at:
            fields["posted_at"] = when
        if invoice.paid_at:
            fields["paid_at"] = when
        if invoice.due_at:
            fields["due_at"] = when + timedelta(days=30)
        Invoice.all_objects.filter(pk=invoice.pk).update(**fields)
        Payment.all_objects.filter(invoice=invoice).update(occurred_at=when)

    def _backdate_mr(self, mr, when):
        MedicalRecord.all_objects.filter(pk=mr.pk).update(created_at=when, closed_at=mr.closed_at)

    # ------------------------------------------------------------------ #
    # Reset / Delete (protegidos por is_demo)
    # ------------------------------------------------------------------ #
    def _reset_demo(self, yes):
        """
        ADR p49 — reset atómico del tenant demo: purge + rebuild en UNA sola
        transacción, bajo advisory lock (exclusión mutua) y ventana de
        mantenimiento (deflecta escrituras de visitantes con 503). Un crash a
        mitad → ROLLBACK total → demo en su último estado bueno (nunca a medio
        borrar). El advisory lock se libera solo al terminar la transacción.
        """
        org = self._demo_org_or_abort()
        if not yes:
            raise CommandError("--reset es destructivo: añade --yes para confirmar.")

        from django.core.cache import cache
        from apps.core.demo_reset import (
            DEMO_RESET_ADVISORY_KEY, DEMO_RESET_FLAG_KEY, DEMO_RESET_FLAG_TTL,
        )

        flag_set = False
        try:
            with transaction.atomic():
                # Exclusión mutua (ADR p49 §7): advisory lock xact-scoped, no
                # bloqueante. Si otro reset corre, salir limpio sin encolar.
                with connection.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", [DEMO_RESET_ADVISORY_KEY])
                    acquired = cur.fetchone()[0]
                if not acquired:
                    logger.warning("DEMO_RESET_SKIPPED_LOCKED", extra={
                        "event": "DEMO_RESET_SKIPPED_LOCKED", "org_id": org.pk,
                    })
                    self.stdout.write(self.style.WARNING(
                        "Otro reset en curso (advisory lock) — se omite."
                    ))
                    return

                # Ventana de mantenimiento (ADR p49 §9): durante el reset las
                # ESCRITURAS de la demo reciben 503 (DemoResetGate). Las lecturas
                # pasan (MVCC sirve un estado consistente). Flag limpiado en
                # finally; el TTL es la red de seguridad ante crash.
                cache.set(DEMO_RESET_FLAG_KEY, True, timeout=DEMO_RESET_FLAG_TTL)
                flag_set = True

                t0 = monotonic()
                self._purge(org, full=False)
                t1 = monotonic()

                self._ensure_org_contact(org)
                users = self._ensure_users(org)
                self._accept_legal_for_demo_users(users)
                self._restrict_demo_import(org)
                self._ensure_catalog(org)
                self._ensure_people(org)
                self._build_operations(org, users)
                t2 = monotonic()

                # Validación inline pre-commit (ADR p49 §11.1): si los conteos no
                # alcanzan el mínimo → raise → ROLLBACK (demo intacta).
                self._validate_rebuild(org)

                purge_ms = int((t1 - t0) * 1000)
                rebuild_ms = int((t2 - t1) * 1000)
                total_ms = int((t2 - t0) * 1000)
                logger.info("DEMO_RESET_COMPLETED", extra={
                    "event": "DEMO_RESET_COMPLETED", "org_id": org.pk,
                    "purge_ms": purge_ms, "rebuild_ms": rebuild_ms, "total_ms": total_ms,
                })
                self.stdout.write(self.style.SUCCESS(
                    f"Reset demo «{org.name}» OK — purge {purge_ms}ms · "
                    f"rebuild {rebuild_ms}ms · total {total_ms}ms."
                ))
        finally:
            if flag_set:
                cache.delete(DEMO_RESET_FLAG_KEY)

        self._report(org)

    def _delete_demo(self, yes):
        org = self._demo_org_or_abort()
        if not yes:
            raise CommandError("--delete es destructivo: añade --yes para confirmar.")
        name = org.name
        with transaction.atomic():
            self._purge(org, full=True)
        self.stdout.write(self.style.WARNING(f"Org demo «{name}» eliminada por completo."))

    @demo_purge_authorized
    def _purge(self, org, *, full):
        """Borra los datos de la org demo en orden FK-seguro. Guard: is_demo.

        El decorador abre la autorización de borrado físico para ESTA
        organización demo y solo durante esta llamada. Sin él, los guards de
        preservación de `apps.platform.deletion_guards` rechazan borrar Invoice,
        Prescription y los expedientes con evidencia — y el reset de la demo,
        cuyo propósito entero es borrarlos, dejaba de funcionar. La preservación
        sigue intacta para cualquier tenant real: la autorización se niega a
        abrirse para una organización que no sea demo.
        """
        if not org.is_demo:
            raise CommandError("Guard: la org objetivo NO tiene is_demo=True. Abortando.")

        f = {"organization": org}
        # El agregado Checkout/Invoice contiene PROTECT intencionales para que la
        # operación normal nunca destruya evidencia. El reset demo es la única
        # operación de borrado total autorizada; primero elimina hojas y rompe
        # solamente enlaces anulables internos del mismo subgrafo demo.
        from apps.billing.models import (
            CheckoutDispute, CheckoutEstimate, CheckoutEvent, CheckoutItem,
            CheckoutPrescriptionSelection, ClinicalChargeEntry,
            ClinicalChargeQuantityEvent, ClinicalChargeSnapshot, CollectionCase,
            CommandReceipt, CreditNote, CreditNoteItem,
            ExternalPrescriptionAttestation, InvoiceAuditLog,
            MedicalRecordBillingContext, ObligationEvidence,
            PrescriptionFulfillmentEvent, RefundPayment, RefundReversal,
            ReplacementWaiver, StockAllocation, StockDispositionEvent,
        )

        # Eventos financieros primero: protegen Invoice, CreditNote,
        # CommandReceipt y CashSession.
        RefundReversal.all_objects.filter(**f).delete()
        RefundPayment.all_objects.filter(**f).delete()
        Payment.all_objects.filter(**f).delete()

        # Proyecciones de inventario/Rx dependen de líneas de factura, notas de
        # crédito y allocations. Se eliminan de hoja a raíz.
        PrescriptionFulfillmentEvent.all_objects.filter(**f).delete()
        StockDispositionEvent.all_objects.filter(**f).delete()
        StockAllocation.all_objects.filter(**f).delete()

        # ADR p49 (P0): MetricAdjustment.source_invoice es PROTECT → DEBE borrarse
        # ANTES que Invoice, o el DELETE de Invoice lanza ProtectedError. Lo crea
        # billing.services.process_refund cuando un visitante devuelve un cobro.
        from apps.analytics.models import (
            DailyOrgMetrics, DashboardSnapshotAudit, MetricAdjustment,
        )
        MetricAdjustment.all_objects.filter(**f).delete()

        CreditNoteItem.all_objects.filter(**f).delete()
        CreditNote.all_objects.filter(**f).delete()

        ObligationEvidence.all_objects.filter(**f).delete()
        CollectionCase.all_objects.filter(**f).delete()
        CheckoutDispute.all_objects.filter(**f).delete()
        ReplacementWaiver.all_objects.filter(**f).delete()
        CheckoutEstimate.all_objects.filter(**f).delete()
        CheckoutEvent.all_objects.filter(**f).delete()
        CheckoutPrescriptionSelection.all_objects.filter(**f).delete()

        # Las correcciones de atestación, las facturas reemplazadas y los
        # ciclos de precio forman cadenas self-PROTECT. Al borrar todo el tenant
        # demo no existe un documento superviviente que deba conservarlas.
        ExternalPrescriptionAttestation.all_objects.filter(**f).update(
            supersedes_attestation=None,
        )
        InvoiceItem.all_objects.filter(**f).update(external_rx_attestation=None)
        CheckoutItem.all_objects.filter(**f).update(source_invoice_item=None)
        Invoice.all_objects.filter(**f).update(
            checkout=None, supersedes_invoice=None,
        )
        Checkout.all_objects.filter(**f).update(replaces_invoice=None)
        ClinicalChargeEntry.all_objects.filter(**f).update(supersedes_entry=None)

        ExternalPrescriptionAttestation.all_objects.filter(**f).delete()
        InvoiceAuditLog.objects.filter(invoice__organization=org).delete()
        CheckoutItem.all_objects.filter(**f).delete()
        Checkout.all_objects.filter(**f).delete()
        InvoiceItem.all_objects.filter(**f).delete()
        Invoice.all_objects.filter(**f).delete()

        ClinicalChargeSnapshot.all_objects.filter(**f).delete()
        ClinicalChargeQuantityEvent.all_objects.filter(**f).delete()
        ClinicalChargeEntry.all_objects.filter(**f).delete()
        MedicalRecordBillingContext.all_objects.filter(**f).delete()
        CommandReceipt.all_objects.filter(**f).delete()

        StockMovement.all_objects.filter(**f).delete()
        MedicalRecordProduct.all_objects.filter(**f).delete()  # QuerySet.delete → sin reversa de stock

        MedicalRecordService.all_objects.filter(**f).delete()
        VitalSigns.all_objects.filter(**f).delete()
        VaccineRecord.all_objects.filter(**f).delete()
        # Prescriptions (si un flujo manual creó alguna).
        try:
            from apps.prescriptions.models import Prescription, PrescriptionItem
            PrescriptionItem.all_objects.filter(**f).delete()
            Prescription.all_objects.filter(**f).delete()
        except Exception:
            pass
        MedicalRecord.all_objects.filter(**f).delete()

        AppointmentStatusChange.all_objects.filter(**f).delete()
        Appointment.all_objects.filter(**f).delete()

        CashMovement.all_objects.filter(**f).delete()
        CashSession.all_objects.filter(**f).delete()

        # ADR p49: limpieza de analytics (evita snapshots fantasma de ciclos
        # previos) + jobs de importación. Tras esto no queda org-FK PROTECT
        # apuntando al subgrafo demo desde analytics/imports.
        DailyOrgMetrics.all_objects.filter(**f).delete()
        DashboardSnapshotAudit.all_objects.filter(**f).delete()
        from apps.imports.models import ImportJob
        ImportJob.all_objects.filter(**f).delete()

        Presentation.all_objects.filter(**f).delete()
        Product.all_objects.filter(**f).delete()
        Service.all_objects.filter(**f).delete()
        # ADR p70 D9: el historial de Configuración de la demo se reinicia con
        # ella. Es de solo inserción por modelo; el borrado por queryset es la
        # única vía, y solo aquí.
        from apps.organizations.models import OrganizationClosure, OrganizationConfigEvent
        OrganizationConfigEvent.objects.filter(**f).delete()
        # ADR p70 D6: los cierres de la demo también se reinician (PROTECT sobre
        # los usuarios: antes de borrarlos en el modo completo).
        OrganizationClosure.objects.filter(**f).delete()

        # Pets/Owners: en reset conservar los genéricos; en delete borrar todo.
        Pet.all_objects.filter(organization=org, is_generic=False).delete()
        Owner.all_objects.filter(organization=org, is_generic=False).delete()

        if full:
            Pet.all_objects.filter(organization=org).delete()
            Owner.all_objects.filter(organization=org).delete()
            # Usuarios (org PROTECT) → antes de la org. UserRole CASCADE por user.
            User.objects.filter(organization=org).delete()
            from apps.core.models import Role
            Role.objects.filter(organization=org).delete()
            from apps.organizations.models import OrganizationSettings
            OrganizationSettings.objects.filter(organization=org).delete()
            org.delete()

    # ------------------------------------------------------------------ #
    def _report(self, org):
        counts = {
            "owners": Owner.objects.filter(organization=org, is_generic=False).count(),
            "pets": Pet.objects.filter(organization=org, is_generic=False).count(),
            "services": Service.objects.filter(organization=org).count(),
            "products": Product.objects.filter(organization=org).count(),
            "appointments": Appointment.all_objects.filter(organization=org).count(),
            "medical_records": MedicalRecord.all_objects.filter(organization=org).count(),
            "checkouts": Checkout.all_objects.filter(organization=org).count(),
            "invoices": Invoice.all_objects.filter(organization=org).count(),
            "payments": Payment.all_objects.filter(organization=org).count(),
            "cash_sessions": CashSession.all_objects.filter(organization=org).count(),
        }
        self.stdout.write(self.style.SUCCESS(f"\nDemo lista — «{org.name}» (id={org.pk}):"))
        for k, v in counts.items():
            self.stdout.write(f"  {k:16} {v}")
        self.stdout.write(
            "\nUsuarios demo (password: %s):\n  %s" % (
                DEMO_PASSWORD, "\n  ".join(u["username"] for u in DEMO_USERS)
            )
        )
        self.stdout.write(self.style.WARNING(
            "\nSiguiente: correr `build_daily_metrics` para poblar analytics:\n"
            "  python manage.py build_daily_metrics"
        ))

    # ------------------------------------------------------------------ #
    # Validación inline post-rebuild (ADR p49 §11.1) — lower bounds.
    # ------------------------------------------------------------------ #
    def _validate_rebuild(self, org):
        """
        Confirma que el rebuild pobló la demo. Usa lower bounds (no igualdad
        exacta) para no ser frágil ante ajustes menores del dataset; el objetivo
        es detectar un rebuild catastróficamente parcial. Si algún conteo cae bajo
        el mínimo → raise (la transacción del reset hace ROLLBACK; demo intacta).
        """
        f = {"organization": org}
        checks = {
            "owners": (Owner.all_objects.filter(is_generic=False, **f).count(), 40),
            "pets": (Pet.all_objects.filter(is_generic=False, **f).count(), 60),
            "services": (Service.all_objects.filter(**f).count(), 8),
            "products": (Product.all_objects.filter(**f).count(), 15),
            "appointments": (Appointment.all_objects.filter(**f).count(), 70),
            "medical_records": (MedicalRecord.all_objects.filter(**f).count(), 45),
            "invoices": (Invoice.all_objects.filter(**f).count(), 55),
            "payments": (Payment.all_objects.filter(**f).count(), 40),
            "cash_sessions": (CashSession.all_objects.filter(**f).count(), 1),
        }
        failed = {
            k: {"got": got, "min": lo}
            for k, (got, lo) in checks.items() if got < lo
        }
        if failed:
            logger.error("DEMO_RESET_VALIDATION_FAILED", extra={
                "event": "DEMO_RESET_VALIDATION_FAILED", "org_id": org.pk, "failed": failed,
            })
            raise CommandError(
                f"Validación post-reset falló (conteos bajo el mínimo): {failed}"
            )
