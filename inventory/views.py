from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Product, Category, Unit


@login_required
def product_list(request):
    """Display all products with their categories and units."""
    products = Product.objects.select_related('category', 'unit').filter(is_active=True)
    return render(request, 'inventory/product_list.html', {'products': products})


@login_required
def category_list(request):
    """Display all active categories."""
    categories = Category.objects.filter(is_active=True)
    return render(request, 'inventory/category_list.html', {'categories': categories})


@login_required
def unit_list(request):
    """Display all units."""
    units = Unit.objects.all()
    return render(request, 'inventory/unit_list.html', {'units': units})
