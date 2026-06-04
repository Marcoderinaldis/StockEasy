from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Recipe


@login_required
def recipe_list(request):
    recipes = Recipe.objects.select_related('created_by').all()
    return render(request, 'recipes/recipe_list.html', {'recipes': recipes})
