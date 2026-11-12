from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'

    def ready(self):
        # El superusuario de plataforma ya no se crea en `post_migrate`: lo hace el
        # comando explícito `bootstrap_superuser` (deuda B5, orden 6).
        import apps.users.signals  # noqa: registra post_save en User
