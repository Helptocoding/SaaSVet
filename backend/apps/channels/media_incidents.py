"""Persistent purge deadlines and bounded delivery through the existing ops hook."""
from datetime import timedelta
import logging
from uuid import uuid4

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Least

from .media_clock import media_now
from .models import MediaPurgeIncident, MessageMedia

logger = logging.getLogger('agent.events')
PURGE_WINDOW = timedelta(days=7)
ESCALATION_DELAY = timedelta(hours=24)


def purge_deadline(row):
    stamps = [value for value in (row.expires_at, row.expired_at) if value is not None]
    return min(stamps) + PURGE_WINDOW if stamps else None


def observe_purge(row, *, failed=False):
    now = media_now()
    deadline = purge_deadline(row)
    if deadline is None:
        # Abandoned uploads also need incident tracking; no retention was begun.
        deadline = now + PURGE_WINDOW
    overdue = now >= deadline and row.purge_verified_at is None
    if not failed and not overdue:
        return
    with transaction.atomic():
        issue, _ = MediaPurgeIncident.objects.for_organization(row.organization_id).get_or_create(
            media=row, defaults=dict(organization_id=row.organization_id, opened_at=now, deadline_at=deadline))
        issue = MediaPurgeIncident.objects.for_organization(row.organization_id).select_for_update().get(pk=issue.pk)
        if failed:
            issue.first_failed_at = issue.first_failed_at or now
            issue.last_failed_at = now
            issue.failure_count += 1
        if overdue and issue.breached_at is None:
            issue.breached_at = now
            issue.notification_pending, issue.notice_next_at = True, now
            logger.error('MEDIA_PURGE_COMPLIANCE_BREACH', extra=dict(event='MEDIA_PURGE_COMPLIANCE_BREACH',
                incident_public_id=str(issue.public_id), media_public_id=str(row.public_id), organization_id=row.organization_id))
        issue.save()


def audit_purge_deadlines(batch=100):
    now = media_now()
    overdue = Q(expires_at__lte=now-PURGE_WINDOW) | Q(status='expired', expired_at__lte=now-PURGE_WINDOW)
    # Background enumeration only; observe_purge resolves each issue with org scope.
    rows = MessageMedia.objects.filter(overdue, purge_verified_at__isnull=True).exclude(file='')
    for row in rows.filter(purge_incident__isnull=True).annotate(_due=Least('expires_at', 'expired_at')).order_by('_due', 'pk')[:batch]:
        observe_purge(row)
    issues = MediaPurgeIncident.objects.filter(closed_at__isnull=True, media__purge_verified_at__isnull=True)
    newly_due = Q(deadline_at__lte=now, breached_at__isnull=True) | Q(
        first_failed_at__lte=now-ESCALATION_DELAY, escalated_at__isnull=True)
    for candidate in issues.filter(newly_due).order_by('deadline_at', 'pk').values(
            'pk', 'organization_id')[:batch]:
        with transaction.atomic():
            issue = MediaPurgeIncident.objects.for_organization(candidate['organization_id']).select_for_update().get(pk=candidate['pk'])
            if issue.first_failed_at and now >= issue.first_failed_at + ESCALATION_DELAY:
                if issue.escalated_at is None:
                    issue.escalated_at = now
                    issue.notification_pending, issue.notice_next_at = True, now
                    logger.error('MEDIA_PURGE_ESCALATED', extra=dict(event='MEDIA_PURGE_ESCALATED',
                        incident_public_id=str(issue.public_id), organization_id=issue.organization_id))
            if now >= issue.deadline_at and issue.breached_at is None:
                issue.breached_at = now
                issue.notification_pending, issue.notice_next_at = True, now
            issue.save()
    return rows.count()


def dispatch_purge_alerts(batch=100):
    """HTTP acceptance is recorded separately from the operator's acknowledgment.

    Recipient/channel absent is the user's accepted non-blocking ops debt. No
    webhook request is attempted until both the owner and existing hook exist.
    """
    if not settings.INBOX_MEDIA_OPS_OWNER or not settings.DISCORD_WEBHOOK_URL:
        return dict(accepted=0, pending_configuration=True)
    now = media_now()
    accepted = 0
    free = Q(notice_lease_until__isnull=True) | Q(notice_lease_until__lte=now)
    due = Q(notice_next_at__isnull=True) | Q(notice_next_at__lte=now)
    for candidate in MediaPurgeIncident.objects.filter(free, due, notification_pending=True, closed_at__isnull=True,
            media__purge_verified_at__isnull=True).order_by('opened_at').values('pk', 'organization_id')[:batch]:
        with transaction.atomic():
            issue = MediaPurgeIncident.objects.for_organization(candidate['organization_id']).select_for_update(skip_locked=True).filter(free, due, notification_pending=True, pk=candidate['pk']).first()
            if issue is None:
                continue
            kinds = [kind for kind, due in (('failure', issue.first_failed_at),
                ('escalation', issue.escalated_at), ('breach', issue.breached_at)) if due]
            pending = [kind for kind in kinds if not issue.notification_receipts.get(kind, {}).get('accepted_at')]
            # Each kind has a 15-minute retry interval, independent of daily purge.
            if not pending:
                issue.notification_pending = False
                issue.save(update_fields=['notification_pending'])
                continue
            token = uuid4()
            issue.notice_token, issue.notice_lease_until = token, now+timedelta(seconds=60)
            issue.save(update_fields=['notice_token', 'notice_lease_until'])
        results = {}
        for kind in pending:
            # Internal IDs only. No patient data, names, binary URLs or secrets.
            payload = {'content': f'MEDIA_PURGE_{kind.upper()} org={issue.organization_id} incident={issue.public_id} media={issue.media_id}'}
            try:
                response = requests.post(settings.DISCORD_WEBHOOK_URL, json=payload, timeout=5, allow_redirects=False)
                ok = 200 <= response.status_code < 300
                response.close()
            except requests.RequestException:
                ok = False
            stamp = media_now().isoformat()
            previous = issue.notification_receipts.get(kind, {})
            results[kind] = dict(attempted_at=stamp, accepted_at=stamp if ok else None,
                attempts=previous.get('attempts', 0)+1)
            accepted += int(ok)
        with transaction.atomic():
            current = MediaPurgeIncident.objects.for_organization(issue.organization_id).select_for_update().filter(pk=issue.pk, notice_token=token).first()
            if current is not None:
                current.notification_receipts = {**current.notification_receipts, **results}
                # A deadline may have become due while HTTP was in flight. Do not
                # overwrite that newly queued stage with the older claim's result.
                kinds_now = [kind for kind, stamp in (('failure', current.first_failed_at),
                    ('escalation', current.escalated_at), ('breach', current.breached_at)) if stamp]
                current.notification_pending = any(not current.notification_receipts.get(kind, {}).get('accepted_at')
                    for kind in kinds_now)
                current.notice_next_at = media_now()+timedelta(minutes=15) if current.notification_pending else None
                current.notice_token = current.notice_lease_until = None
                current.save(update_fields=['notification_receipts', 'notification_pending', 'notice_next_at', 'notice_token', 'notice_lease_until'])
    return dict(accepted=accepted, pending_configuration=False)


def incident_counts():
    active = MediaPurgeIncident.objects.filter(closed_at__isnull=True)
    return dict(open_incidents=active.count(), compliance_incidents=active.filter(breached_at__isnull=False).count(),
        unresolved_failures=active.filter(first_failed_at__isnull=False, media__purge_verified_at__isnull=True).count())


def purge_backlog():
    now = media_now()
    expired = Q(status='expired') | Q(status__in=['ready', 'failed'], expires_at__lte=now)
    abandoned = Q(status='failed', attempts__gte=5, persisted_at__isnull=True)
    rows = MessageMedia.objects.filter(expired | abandoned).exclude(file='')
    due = rows.filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now),
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
    return dict(purge_pending=rows.count(), remaining_due=due.count())
