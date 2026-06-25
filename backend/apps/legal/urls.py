from django.urls import path

from .views import AcceptLegalView, CurrentLegalView

urlpatterns = [
    path('legal/current/', CurrentLegalView.as_view(), name='legal-current'),
    path('legal/accept/', AcceptLegalView.as_view(), name='legal-accept'),
]
