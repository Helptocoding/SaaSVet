"""
URL routes for cross-tenant platform operations.

Mounted at `/api/platform/` in `config/urls.py`. All routes require
`IsPlatformOperator` permission — distinct from tenant-scoped `/api/`.
"""
from django.urls import path

from apps.platform.views import PlatformOrgCreateView


urlpatterns = [
    path(
        'organizations/',
        PlatformOrgCreateView.as_view(),
        name='platform-org-create',
    ),
]
