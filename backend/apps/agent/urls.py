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
    path('settings/', views.agent_settings_view, name='inbox-settings'),
    path('metrics/', views.metrics_view, name='inbox-metrics'),
]
