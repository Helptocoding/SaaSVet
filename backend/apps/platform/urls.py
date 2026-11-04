"""
URL routes for cross-tenant platform operations.

Mounted at `/api/platform/` in `config/urls.py`. All routes require
`IsPlatformOperator` permission — distinct from tenant-scoped `/api/`.
"""
from django.urls import path

from apps.platform.views import (PlatformOrgCreateView, PlatformStaffResetPasswordView,
                                 PlatformOrgStateView, PlatformSubjectArchiveView,
                                 PhysicalDeletionPreviewView, PhysicalDeletionExecuteView,
                                 PlatformOrganizationHistoryView)


urlpatterns = [
    path('organizations/<uuid:pk>/history/', PlatformOrganizationHistoryView.as_view(),
         name='platform-org-history'),
    path('physical-deletions/preview/', PhysicalDeletionPreviewView.as_view(),
         name='physical-deletion-preview'),
    path('physical-deletions/execute/', PhysicalDeletionExecuteView.as_view(),
         name='physical-deletion-execute'),
    path('organizations/<uuid:pk>/<str:action>/', PlatformOrgStateView.as_view(),
         name='platform-org-state'),
    path('organizations/<uuid:organization_id>/<str:kind>/<uuid:pk>/<str:action>/',
         PlatformSubjectArchiveView.as_view(), name='platform-subject-archive'),
    path(
        'organizations/',
        PlatformOrgCreateView.as_view(),
        name='platform-org-create',
    ),
    path(
        'staff/<str:pk>/reset-password/',
        PlatformStaffResetPasswordView.as_view(),
        name='platform-staff-reset-password',
    ),
]
