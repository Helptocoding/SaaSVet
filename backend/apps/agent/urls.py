"""
agent/urls.py — Bandeja del agente (montado en /api/inbox/, É-F0 PR-6).
"""
from django.urls import path

from . import views
from .inbox_media import inbox_media_view

urlpatterns = [
    path('media/<uuid:public_id>/', inbox_media_view, name='inbox-media'),
    path('assignable-users/', views.assignable_users_view, name='inbox-assignable-users'),
    path('conversations/', views.list_conversations,
         name='inbox-conversations'),
    path('conversations/<str:pk>/messages/', views.conversation_messages,
         name='inbox-messages'),
    path('conversations/<str:pk>/send/', views.send_message,
         name='inbox-send'),
    path('conversations/<str:pk>/messages/<int:message_id>/retry/', views.retry_message,
         name='inbox-message-retry'),
    path('conversations/<str:pk>/claim/', views.claim_conversation,
         name='inbox-claim'),
    path('conversations/<uuid:pk>/assign/', views.assign_conversation_view,
         name='inbox-assign'),
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
    # Bandeja AGRUPADA por persona (plan de continuidad, §4). La ruta es
    # COMPUESTA porque la fila es por `(contacto, cuenta)`: con solo el contacto,
    # una clínica con dos números tendría dos filas colisionando en un id.
    path('threads/', views.list_threads, name='inbox-threads'),
    path('threads/<str:contact_pid>/<str:account_pid>/sessions/',
         views.thread_sessions, name='inbox-thread-sessions'),
    path('threads/<str:contact_pid>/<str:account_pid>/messages/',
         views.thread_messages, name='inbox-thread-messages'),
    path('threads/<str:contact_pid>/<str:account_pid>/read/',
         views.thread_read, name='inbox-thread-read'),
    path('threads/<str:contact_pid>/<str:account_pid>/context/',
         views.thread_context_view, name='inbox-thread-context'),
    path('settings/', views.agent_settings_view, name='inbox-settings'),
    path('metrics/', views.metrics_view, name='inbox-metrics'),
    path('whatsapp-token/', views.whatsapp_token_view, name='inbox-whatsapp-token'),
]
