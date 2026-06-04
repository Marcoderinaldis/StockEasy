from django.db import models
from django.conf import settings
from inventory.models import Ingredient


class Recipe(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    portions = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recipes',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='recipe_ingredients')
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name='recipe_ingredients')
    quantity = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        unique_together = ('recipe', 'ingredient')

    def __str__(self):
        return f'{self.recipe.name} — {self.ingredient.name} x{self.quantity}'
