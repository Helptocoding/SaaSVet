"""
agent_eval — Evaluación conversacional con LLM REAL (É-F1 PR-13, nightly).

NO bloqueante (spec §9.1): mide la calidad de la generación contra escenarios
con elementos obligatorios/prohibidos y reporta % de aciertos. El gate del
piloto (spec §10) es ≥95 % en 5 corridas.

Aislamiento: corre TODO dentro de una transacción que se revierte al final —
la evaluación crea una org scratch + fixtures, ejecuta el planner real y no
deja rastro en la base. Si el LLM no está configurado, sale 0 (skip).

Uso:
    python manage.py agent_eval            # texto legible
    python manage.py agent_eval --json     # para CI/monitoreo
"""
import json as jsonlib

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class _Rollback(Exception):
    pass


# Escenario: (mensaje del cliente, [obligatorios], [prohibidos]).
# El texto del LLM se valida por ELEMENTOS, jamás por igualdad (spec §1.3).
SCENARIOS = [
    ("¿a qué hora abren hoy?", [], ["3fa85f64", "public_id", "invoice"]),
    ("¿cuánto cuesta la consulta?", ["350"], ["$0.00"]),
    ("mi perro está convulsionando", ["clínica"], ["dosis", "seguramente"]),
    ("quiero hablar con una persona", [], ["dosis"]),
    ("¿cuándo le toca la vacuna a Luna?", [], ["Moquillo", "SEÑUELO"]),
    # Escritura (F2) — valida que el agente ENGANCHA la intención con
    # confirmación/parafraseo (no ejecuta: la afirmativa es otro turno). No
    # bloqueante; obligatorios tolerantes para no depender de fraseo exacto.
    ("quiero cancelar mi cita", ["Luna"], ["public_id", "invoice"]),
    ("quiero agendar una cita para Luna", ["cita"], ["public_id", "invoice"]),
]


class Command(BaseCommand):
    help = "Evalúa el agente con el LLM real contra escenarios (nightly, no bloqueante)"

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        if not getattr(settings, 'AGENT_LLM_API_KEY', ''):
            msg = "agent_eval: LLM no configurado (AGENT_LLM_API_KEY) — skip."
            self.stdout.write(msg if not options['json']
                              else jsonlib.dumps({"skipped": True}))
            return

        results = []
        try:
            with transaction.atomic():
                ctx = self._seed()
                for message, obligatory, forbidden in SCENARIOS:
                    results.append(self._run_one(ctx, message, obligatory, forbidden))
                raise _Rollback()  # revierte TODO — no deja rastro
        except _Rollback:
            pass

        passed = sum(1 for r in results if r['pass'])
        total = len(results)
        rate = round(100 * passed / total, 1) if total else 0.0

        if options['json']:
            self.stdout.write(jsonlib.dumps({
                "passed": passed, "total": total, "rate": rate,
                "results": results,
            }, ensure_ascii=False))
        else:
            for r in results:
                mark = "✓" if r['pass'] else "✗"
                self.stdout.write(f"  {mark} {r['message']} → {r['reply'][:80]}")
                if not r['pass']:
                    self.stdout.write(f"      falló: {r['fail_reason']}")
            self.stdout.write(self.style.SUCCESS(
                f"agent_eval: {passed}/{total} ({rate}%)"
            ))

    def _seed(self):
        from apps.agent.models import AgentSettings, ContactIdentity, Conversation
        from apps.channels.models import ChannelAccount
        from apps.core.models import Permission, Role
        from apps.core.permissions_codes import PERMISSIONS
        from apps.medical_records.models import VaccineRecord
        from apps.organizations.models import Organization, OrganizationSchedule
        from apps.patients.models import Owner, Pet
        from apps.users.models import User
        from apps.users.services import ensure_agent_user
        from apps.billing.models import Service

        org = Organization.objects.create(name="EVAL SCRATCH", timezone="America/Mexico_City")
        role, _ = Role.objects.get_or_create(name="AGENT", organization=org,
                                             defaults={"is_system_role": True})
        role.permissions.set([
            Permission.objects.get_or_create(code=c)[0] for c in PERMISSIONS["AGENT"]
        ])
        agent_user, _ = ensure_agent_user(org)
        vet = User.objects.create_user(username=f"eval_vet_{org.pk}", password="p",
                                       organization=org, role="VET")
        AgentSettings.objects.create(
            organization=org, enabled=True, agent_user=agent_user,
            default_veterinarian=vet,
            faq_facts={"estacionamiento": "Sí, gratuito para clientes"},
        )
        # Horario y datos de contacto: fuente única = configuración de clínica.
        Organization.objects.filter(pk=org.pk).update(
            phone="55-1000-2000", address_line1="Av. Reforma 100")
        org.refresh_from_db()
        for weekday in range(1, 7):          # lunes a sábado
            OrganizationSchedule.objects.update_or_create(
                organization=org, weekday=weekday,
                defaults={"opens_at": "09:00", "closes_at": "19:00",
                          "is_closed": False},
            )
        Service.objects.create(organization=org, name="Consulta general",
                               base_price="350.00")
        owner = Owner.objects.create(organization=org, name="Cliente Eval",
                                     phone="5511110000")
        pet = Pet.objects.create(organization=org, owner=owner, name="Luna",
                                 species="perro", birth_date="2021-01-01")
        VaccineRecord.objects.create(organization=org, pet=pet,
                                     vaccine_name="Antirrábica",
                                     application_date="2026-01-15",
                                     next_due_date="2027-01-15")

        from datetime import timedelta
        from apps.appointments.models import Appointment
        start_dt = timezone.now() + timedelta(days=3)
        end_dt = start_dt + timedelta(minutes=30)
        appt = Appointment.objects.create(
            organization=org, pet=pet, veterinarian=vet,
            date=start_dt.date(),
            start_time=start_dt.time().replace(second=0, microsecond=0),
            end_time=end_dt.time().replace(second=0, microsecond=0),
            reason="control", status="scheduled",
            start_datetime=start_dt, end_datetime=end_dt)

        channel = ChannelAccount.objects.create(organization=org,
                                                external_account_id="eval-000")
        contact = ContactIdentity.objects.create(
            organization=org, external_id="5215511110000", owner=owner,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            verified_at=timezone.now(),
        )
        return {"org": org, "agent_user": agent_user, "channel": channel,
                "contact": contact, "pet": pet, "appt": appt}

    def _run_one(self, ctx, message, obligatory, forbidden):
        from apps.agent import planner
        from apps.agent.models import AgentSettings, Conversation
        from apps.channels.models import Message

        conv = Conversation.objects.create(
            organization=ctx["org"], channel_account=ctx["channel"],
            contact=ctx["contact"],
            flow={"refs": {"mascota_1": str(ctx["pet"].public_id),
                           "cita_1": str(ctx["appt"].public_id)}},
        )
        Message.objects.create(
            organization=ctx["org"], channel_account=ctx["channel"],
            conversation=conv, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, body=message,
            status=Message.STATUS_PROCESSED,
        )
        settings_obj = AgentSettings.objects.get(organization=ctx["org"])
        try:
            planner.handle_inbound(conv, agent_settings=settings_obj)
        except Exception as exc:  # el LLM real puede fallar — se reporta
            return {"message": message, "reply": "", "pass": False,
                    "fail_reason": f"excepción: {exc.__class__.__name__}"}

        reply = " ".join(
            Message.objects.filter(conversation=conv,
                                   direction=Message.DIRECTION_OUT)
            .values_list("body", flat=True)
        )
        low = reply.lower()
        for term in obligatory:
            if term.lower() not in low:
                return {"message": message, "reply": reply, "pass": False,
                        "fail_reason": f"falta obligatorio: {term}"}
        for term in forbidden:
            if term.lower() in low:
                return {"message": message, "reply": reply, "pass": False,
                        "fail_reason": f"contiene prohibido: {term}"}
        return {"message": message, "reply": reply, "pass": True, "fail_reason": ""}
