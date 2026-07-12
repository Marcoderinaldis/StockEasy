from django.db import models
from django.conf import settings


class Recipe(models.Model):
    """Recipe definition with yield information."""

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True, null=True)
    yields_quantity = models.DecimalField(max_digits=10, decimal_places=4)
    yields_unit = models.ForeignKey(
        'inventory.Unit',
        on_delete=models.PROTECT,
        related_name='recipes',
    )
    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Menu selling price per yield unit. Null if not yet set; '
                  'food-cost percent is not computed without it.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='recipes_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class RecipeIngredient(models.Model):
    """
    Individual ingredient in a recipe.

    Unit can differ from product.unit; validation happens in service layer.
    """

    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name='ingredients',
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        related_name='recipe_ingredients',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=4)
    unit = models.ForeignKey(
        'inventory.Unit',
        on_delete=models.PROTECT,
        related_name='recipe_ingredients',
    )
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['recipe', 'product']

    def __str__(self):
        return f"{self.recipe.name}: {self.product.name} x {self.quantity}"
