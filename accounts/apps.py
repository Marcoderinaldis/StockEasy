from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        from auditlog.registry import auditlog
        from .models import CustomUser

        # Exclude sensitive fields from audit logging
        auditlog.register(CustomUser, exclude_fields=['password', 'last_login'])
