from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from recipes.models import Recipe


@login_required
def index(request):
    """
    Display recipe costing overview.

    Note: Full costing calculations will be implemented in Sprint 3.
    """
    recipes = Recipe.objects.prefetch_related('ingredients__product').all()

    costing_data = []
    for recipe in recipes:
        costing_data.append({
            'recipe': recipe,
            'total_cost': None,  # To be implemented in Sprint 3
            'cost_per_yield': None,  # To be implemented in Sprint 3
            'suggested_price': None,  # To be implemented in Sprint 3
        })

    return render(request, 'costing/index.html', {'costing_data': costing_data})
