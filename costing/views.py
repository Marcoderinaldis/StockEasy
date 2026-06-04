from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from recipes.models import Recipe
from .services import calculate_recipe_cost, calculate_cost_per_portion, suggest_selling_price


@login_required
def index(request):
    recipes = Recipe.objects.prefetch_related('recipe_ingredients__ingredient').all()
    DEFAULT_MARGIN = 70

    costing_data = []
    for recipe in recipes:
        try:
            total_cost = calculate_recipe_cost(recipe)
            cost_per_portion = calculate_cost_per_portion(recipe)
            suggested_price = suggest_selling_price(recipe, DEFAULT_MARGIN)
        except (ValueError, ZeroDivisionError):
            total_cost = None
            cost_per_portion = None
            suggested_price = None

        costing_data.append({
            'recipe': recipe,
            'total_cost': total_cost,
            'cost_per_portion': cost_per_portion,
            'suggested_price': suggested_price,
            'margin': DEFAULT_MARGIN,
        })

    return render(request, 'costing/index.html', {'costing_data': costing_data})
