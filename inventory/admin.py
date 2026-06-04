from django.contrib import admin
from .models import Unit, Ingredient


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation')
    search_fields = ('name',)


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', 'cost_per_unit', 'stock_quantity', 'updated_at')
    list_filter = ('unit',)
    search_fields = ('name',)
