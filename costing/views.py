"""
Costing section views.

- costing_home: List all products with current prices (all authenticated users)
- price_history: View price history for a product (all authenticated users)
- update_price: Add a new price for a product (manager/admin only)
- recipe_costing: Recipe costing overview (placeholder - F11)
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from accounts.permissions import manager_required
from inventory.models import Product, PurchasePrice
from recipes.models import Recipe

from .forms import UpdatePriceForm
from .services import set_product_price, PriceValidationError


@login_required
def costing_home(request):
    """
    Display all products with their current prices.

    Visible to all authenticated users (staff see costs for transparency).
    Manager/admin see "Update price" buttons.
    """
    products = Product.objects.filter(is_active=True).select_related('unit', 'category')

    product_data = []
    for product in products:
        current = product.current_price
        product_data.append({
            'product': product,
            'current_price': current,
            'unit_price': current.unit_price if current else None,
        })

    return render(request, 'costing/costing_home.html', {
        'product_data': product_data,
    })


@login_required
def price_history(request, product_id):
    """
    Display price history for a specific product.

    Shows all PurchasePrice records (active and closed), newest first.
    Visible to all authenticated users.
    """
    product = get_object_or_404(Product, pk=product_id)
    prices = product.prices.select_related('created_by').order_by('-effective_from')

    return render(request, 'costing/price_history.html', {
        'product': product,
        'prices': prices,
    })


@manager_required
def update_price(request, product_id=None):
    """
    Add a new price for a product.

    Manager/admin only. Staff get 403.
    Uses set_product_price service - no direct PurchasePrice manipulation.
    """
    product = None
    if product_id:
        product = get_object_or_404(Product, pk=product_id)

    if request.method == 'POST':
        form = UpdatePriceForm(request.POST)
        if form.is_valid():
            selected_product = form.cleaned_data['product']
            unit_price = form.cleaned_data['unit_price']

            try:
                new_price = set_product_price(
                    product=selected_product,
                    unit_price=unit_price,
                    user=request.user,
                )
                messages.success(
                    request,
                    f"Price updated for {selected_product.name}: "
                    f"£{new_price.unit_price} per {selected_product.unit.name}"
                )
                return redirect('costing:costing_home')
            except PriceValidationError as e:
                form.add_error('unit_price', str(e))
    else:
        initial = {}
        if product:
            initial['product'] = product
        form = UpdatePriceForm(initial=initial)

    # Get current price for reference if product is pre-selected
    current_price = None
    if product:
        current_price = product.current_price

    return render(request, 'costing/update_price.html', {
        'form': form,
        'product': product,
        'current_price': current_price,
    })


@login_required
def recipe_costing(request):
    """
    Display recipe costing overview.

    Note: Full costing calculations will be implemented in Sprint 4 (F11).
    """
    recipes = Recipe.objects.prefetch_related('ingredients__product').all()

    costing_data = []
    for recipe in recipes:
        costing_data.append({
            'recipe': recipe,
            'total_cost': None,  # To be implemented in F11
            'cost_per_portion': None,  # To be implemented in F11
            'suggested_price': None,  # To be implemented in F11
        })

    return render(request, 'costing/recipe_costing.html', {'costing_data': costing_data})
