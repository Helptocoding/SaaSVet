"""
ensure_agent_users — Garantiza el service account AGENT por organización.

Idempotente (ADR p51): corre bien N veces. Usos previstos:
  - Provisioning del subsistema conversacional (É-F0).
  - Reparación tras un borrado/desactivación accidental por shell (recrea
    o reactiva; ver ``users.services.ensure_agent_user``).

Requiere que ``seed_permissions`` ya haya sembrado el Role AGENT (corre en
cada deploy vía release.sh); si falta, el service lo reporta con WARNING y
la cuenta queda sin UserRole hasta el siguiente seed.

Uso:
    python manage.py ensure_agent_users                    # todas las orgs
    python manage.py ensure_agent_users --org <public_id>  # una sola
"""
from django.core.management.base import BaseCommand, CommandError

from apps.organizations.models import Organization
from apps.users.services import ensure_agent_user


class Command(BaseCommand):
    help = "Garantiza el user AGENT (service account, ADR p51) por organización (idempotente)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--org',
            help='public_id de una organización específica (default: todas)',
        )

    def handle(self, *args, **options):
        orgs = Organization.objects.all()
        if options['org']:
            orgs = orgs.filter(public_id=options['org'])
            if not orgs.exists():
                raise CommandError(
                    f"Organización {options['org']} no encontrada"
                )

        counts = {'created': 0, 'repaired': 0, 'ok': 0}
        for org in orgs:
            user, status_ = ensure_agent_user(org)
            counts[status_] += 1
            self.stdout.write(f"  {org.name}: {status_} ({user.username})")

        self.stdout.write(self.style.SUCCESS(
            f"ensure_agent_users: {counts['created']} creados, "
            f"{counts['repaired']} reparados, {counts['ok']} sin cambios"
        ))
