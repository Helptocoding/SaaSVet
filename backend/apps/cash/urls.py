from django.urls import path

from . import views

# Rutas fijas (open/current) ANTES del patrón con <str:pk> para evitar colisión.
urlpatterns = [
    path('cash/sessions/', views.CashSessionListView.as_view()),
    path('cash/sessions/open/', views.open_session),
    path('cash/sessions/current/', views.current_session),
    path('cash/sessions/<str:pk>/close/', views.close_session),
    path('cash/movements/', views.CashMovementListCreateView.as_view()),
]
