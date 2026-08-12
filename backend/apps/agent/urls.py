"""
agent/urls.py — Bandeja del agente (montado en /api/inbox/, É-F0 PR-6).
"""
from django.urls import path

from . import views

urlpatterns = [
    path('conversations/', views.list_conversations,
         name='inbox-conversations'),
    path('conversations/<str:pk>/messages/', views.conversation_messages,
         name='inbox-messages'),
    path('conversations/<str:pk>/send/', views.send_message,
         name='inbox-send'),
    path('conversations/<str:pk>/claim/', views.claim_conversation,
         name='inbox-claim'),
    path('conversations/<str:pk>/close/', views.close_conversation,
         name='inbox-close'),
    path('conversations/<str:pk>/release/', views.release_conversation,
         name='inbox-release'),
    path('conversations/<str:pk>/unlink-family/', views.unlink_family,
         name='inbox-unlink-family'),
    path('conversations/<str:pk>/reset-identity/', views.reset_contact_identity,
         name='inbox-reset-identity'),
    # FLUJO-C (ADR p57 §5.5): verificar y autorizar son DOS acciones, no una
    # con un booleano — la primera registra un juicio humano, la segunda
    # ejecuta su consecuencia.
    path('conversations/<str:pk>/verify-identity/', views.verify_contact_identity,
         name='inbox-verify-identity'),
    path('conversations/<str:pk>/authorize-identity/', views.authorize_identity_link,
         name='inbox-authorize-identity'),
    path('settings/', views.agent_settings_view, name='inbox-settings'),
    path('metrics/', views.metrics_view, name='inbox-metrics'),
    path('whatsapp-token/', views.whatsapp_token_view, name='inbox-whatsapp-token'),
]
