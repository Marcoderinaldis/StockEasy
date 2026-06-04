from django.db import models


class Unit(models.Model):
    name = models.CharField(max_length=100, unique=True)
    abbreviation = models.CharField(max_length=10, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.abbreviation})'


class Ingredient(models.Model):
    name = models.CharField(max_length=200, unique=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='ingredients')
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=4)
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.unit.abbreviation})'
