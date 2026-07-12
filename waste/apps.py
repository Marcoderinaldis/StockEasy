from django.apps import AppConfig


class WasteConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'waste'

    def ready(self):
        from auditlog.registry import auditlog
        from .models import WasteRecord

        auditlog.register(WasteRecord)
