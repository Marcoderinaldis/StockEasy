from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        MANAGER = 'MANAGER', 'Manager'
        STAFF = 'STAFF', 'Staff'

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.STAFF,
    )

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER or self.is_admin

    @property
    def is_staff_role(self):
        return self.role == self.Role.STAFF or self.is_manager
