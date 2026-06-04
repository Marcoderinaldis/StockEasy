from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Ingredient


@login_required
def ingredient_list(request):
    ingredients = Ingredient.objects.select_related('unit').all()
    return render(request, 'inventory/ingredient_list.html', {'ingredients': ingredients})
