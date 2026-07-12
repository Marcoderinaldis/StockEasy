from django.apps import AppConfig


class RecipesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recipes'

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Recipe, RecipeIngredient

        auditlog.register(Recipe)
        auditlog.register(RecipeIngredient)
