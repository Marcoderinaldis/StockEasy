from django.contrib import admin
from .models import Recipe, RecipeIngredient


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1
    readonly_fields = ('created_at',)


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ('name', 'yields_quantity', 'yields_unit', 'created_by', 'created_at', 'updated_at')
    list_filter = ('created_at', 'yields_unit')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [RecipeIngredientInline]


@admin.register(RecipeIngredient)
class RecipeIngredientAdmin(admin.ModelAdmin):
    list_display = ('recipe', 'product', 'quantity', 'unit', 'created_at')
    list_filter = ('recipe',)
    search_fields = ('recipe__name', 'product__name')
    readonly_fields = ('created_at',)
