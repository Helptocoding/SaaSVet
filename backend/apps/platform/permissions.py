"""
Permission classes for cross-tenant platform operations.

Distinct from tenant-scoped RBAC (`apps.core.permissions.HybridPermission`).
Platform endpoints orchestrate SaaS infra (org provisioning, lifecycle,
support tooling) — no tenant context applies.
"""
import logging

from rest_framework.permissions import BasePermission


logger = logging.getLogger('platform.events')


class IsPlatformOperator(BasePermission):
    """
    SaaS platform operator predicate.

    Requires:
      - authenticated
      - is_superuser=True
      - is_staff=True
      - role='ADMIN_SAAS'

    Semantically distinct from `_is_platform_superuser` in
    `apps.users.apps` (bootstrap predicate). Bootstrap validates env-driven
    identity (email match); operator only validates current session.
    Keeping these separate avoids drift when future operator workflows
    diverge (impersonation, billing, support tooling).
    """

    message = "Solo operadores de plataforma."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        ok = (
            bool(user.is_superuser)
            and bool(user.is_staff)
            and getattr(user, 'role', None) == 'ADMIN_SAAS'
        )
        if not ok:
            logger.warning("PLATFORM_ACCESS_DENIED", extra={
                "event": "PLATFORM_ACCESS_DENIED",
                "actor_id": getattr(user, 'pk', None),
                "actor_username": getattr(user, 'username', None),
                "actor_role": getattr(user, 'role', None),
                "actor_is_superuser": bool(getattr(user, 'is_superuser', False)),
                "actor_is_staff": bool(getattr(user, 'is_staff', False)),
                "path": request.path,
                "method": request.method,
            })
        return ok
