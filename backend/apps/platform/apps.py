"""
Cross-tenant SaaS platform operations.

Contains privileged infrastructure workflows:
  - tenant provisioning (create organization + initial admin)
  - tenant lifecycle (future: suspend, reactivate, billing state)
  - platform-wide administration (future: health dashboard, impersonation,
    metrics, support tooling)

Boundary rule
-------------
This app must NEVER contain tenant-scoped business logic. Tenant-scoped
work belongs in `apps/organizations/` (settings), `apps/users/` (staff),
`apps/medical_records/`, `apps/billing/`, etc.

Conversely, those tenant apps must NEVER reach into `apps/platform/`.

Auth model
----------
All endpoints require `IsPlatformOperator` (predicate: is_superuser +
is_staff + role='ADMIN_SAAS'). Distinct from tenant-side ADMIN.

ADR
---
See ADR-16 (2026-05-22) in CLAUDE.md for the architectural decision to
isolate platform operations from tenant domain.
"""
from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.platform'
    verbose_name = 'Platform Operations'

    def ready(self):
        from . import deletion_guards  # noqa: F401
