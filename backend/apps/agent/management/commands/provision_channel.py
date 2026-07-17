"""
provision_channel — Alta del subsistema conversacional para una organización.

Idempotente. Orquesta las tres piezas del provisioning (É-F0 PR-3):
  1. User AGENT (service account, ADR p51) vía ensure_agent_user.
  2. AgentSettings (enabled=False — el kill switch arranca apagado; se
     enciende desde la bandeja cuando la clínica esté lista).
  3. ChannelAccount con el phone_number_id del proveedor.

Guard R1 (cross-tenant): si el phone_number_id ya pertenece a OTRA
organización, aborta con error — un número JAMÁS se reasigna por comando
(hacerlo re-enrutaría conversaciones de una clínica a otra). El desmonte
de un número es operación manual consciente, no un efecto colateral.

Uso:
    python manage.py provision_channel --org <public_id> \
        --phone-number-id <id de Meta> \
        [--display-number "+52155..."] \
        [--credentials-ref WHATSAPP_ACCESS_TOKEN]
"""
from django.core.management.base import BaseCommand, CommandError

from apps.agent.models import AgentSettings
from apps.channels.models import ChannelAccount
from apps.organizations.models import Organization
from apps.users.services import ensure_agent_user


class Command(BaseCommand):
    help = "Provisiona el canal WhatsApp de una organización (idempotente)"

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True, help='public_id de la organización')
        parser.add_argument(
            '--phone-number-id', required=True,
            help='external_account_id del proveedor (phone_number_id de Meta)',
        )
        parser.add_argument('--display-number', default='')
        parser.add_argument(
            '--credentials-ref', default='WHATSAPP_ACCESS_TOKEN',
            help='NOMBRE de la env var con el access token (el secreto vive en .env.prod)',
        )

    def handle(self, *args, **options):
        try:
            org = Organization.objects.get(public_id=options['org'])
        except Organization.DoesNotExist:
            raise CommandError(f"Organización {options['org']} no encontrada")

        # 1. Actor del subsistema (idempotente, auto-reparador).
        agent_user, user_status = ensure_agent_user(org)
        self.stdout.write(f"  agent user: {user_status} ({agent_user.username})")

        # 2. Settings (kill switch apagado por default).
        settings_obj, created = AgentSettings.objects.get_or_create(
            organization=org, defaults={'agent_user': agent_user},
        )
        if not created and settings_obj.agent_user_id is None:
            settings_obj.agent_user = agent_user
            settings_obj.save(update_fields=['agent_user'])
        self.stdout.write(
            f"  settings: {'created' if created else 'ok'} "
            f"(enabled={settings_obj.enabled})"
        )

        # 3. Canal — guard R1 antes de cualquier escritura.
        phone_number_id = options['phone_number_id']
        existing = ChannelAccount.all_objects.filter(
            external_account_id=phone_number_id,
        ).first()
        if existing is not None and existing.organization_id != org.pk:
            raise CommandError(
                f"phone_number_id {phone_number_id} ya pertenece a otra "
                f"organización (id={existing.organization_id}). Un número "
                "jamás se reasigna por comando (riesgo cross-tenant R1)."
            )

        if existing is None:
            channel = ChannelAccount(
                organization=org,
                external_account_id=phone_number_id,
                display_number=options['display_number'],
                provider_credentials_ref=options['credentials_ref'],
            )
            channel.save()
            self.stdout.write(f"  channel: created ({phone_number_id})")
        else:
            updates = []
            if options['display_number'] and existing.display_number != options['display_number']:
                existing.display_number = options['display_number']
                updates.append('display_number')
            if existing.provider_credentials_ref != options['credentials_ref']:
                existing.provider_credentials_ref = options['credentials_ref']
                updates.append('provider_credentials_ref')
            if not existing.is_active:
                existing.is_active = True
                updates.append('is_active')
            if updates:
                existing.save(update_fields=updates)
            self.stdout.write(
                f"  channel: {'updated ' + ','.join(updates) if updates else 'ok'}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"provision_channel completado para {org.name}"
        ))
