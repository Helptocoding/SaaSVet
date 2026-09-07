from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notifications.models import Notification, NotificationReceipt


class Command(BaseCommand):
    help = "Poda receipts vistos >90d y notificaciones stale >30d (retención centro de notificaciones)."

    def handle(self, *args, **options):
        now = timezone.now()
        old_seen = now - timedelta(days=90)
        stale = now - timedelta(days=30)
        receipts = NotificationReceipt.objects.filter(seen_at__lt=old_seen).delete()[0]
        notifs = Notification.objects.filter(occurred_at__lt=stale).exclude(
            receipts__seen_at__isnull=True,
        ).delete()[0]
        self.stdout.write(self.style.SUCCESS(
            f"prune_notifications: receipts={receipts} notifications={notifs}"
        ))
