from django.apps import AppConfig


class AgentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.agent'
    verbose_name = 'Agente conversacional'

    def ready(self):
        # El agente escucha a `patients`; `patients` no sabe que existe. Ver
        # `signals.py`: un vínculo de identidad derivado del teléfono no puede
        # sobrevivir a un cambio de ese teléfono.
        from . import signals  # noqa: F401
