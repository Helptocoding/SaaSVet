from django.urls import path

from .views import notification_feed, notification_seen, notification_seen_all

urlpatterns = [
    path('v1/notifications/feed/', notification_feed),
    path('v1/notifications/<str:key>/seen/', notification_seen),
    path('v1/notifications/seen-all/', notification_seen_all),
]
