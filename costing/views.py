"""
Costing section views.

- costing_home: List all products with current prices (all authenticated users)
- price_history: View price history for a product (all authenticated users)
- update_price: Add a new price for a product (manager/admin only)
- recipe_costing: Recipe costing overview with food-cost % and GP %
- set_selling_price: Set a recipe's selling price (manager/admin only)
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from accounts.permissions import manager_required, staff_required
from inventory.models import Product, PurchasePrice
from recipes.models import Recipe

from .forms import UpdatePriceForm, SetSellingPriceForm
from .services import (
    set_product_price,
    PriceValidationError,
    calculate_recipe_cost,
    calculate_recipe_margin,
    suggest_selling_price,
)


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


@staff_required
def recipe_costing(request):
    """
    Display recipe costing overview with food-cost % and GP %.

    Visible to all staff (read-only). Managers see inline controls to set
    selling prices.
    """
    recipes = Recipe.objects.select_related('yields_unit').prefetch_related(
        'ingredients__product__unit',
        'ingredients__unit',
    ).all()

    costing_data = []
    for recipe in recipes:
        cost = calculate_recipe_cost(recipe)
        margin = calculate_recipe_margin(recipe)

        # Get suggested price at 70% GP as a hint (if cost is complete)
        suggested = suggest_selling_price(recipe, Decimal('70'))
        suggested_price = suggested.suggested_price if suggested.status == 'ok' else None

        costing_data.append({
            'recipe': recipe,
            'cost': cost,
            'margin': margin,
            'suggested_price': suggested_price,
            'form': SetSellingPriceForm(initial={
                'selling_price': recipe.selling_price
            }) if request.user.is_manager else None,
        })

    return render(request, 'costing/recipe_costing.html', {
        'costing_data': costing_data,
    })


@manager_required
def set_selling_price(request, recipe_id):
    """
    Set a recipe's selling price.

    Manager/admin only. Staff get 403.

    Unlike PurchasePrice (append-only historical data), selling_price is the
    current menu price and is simply updated in place on the Recipe model.
    This is intentional: menu prices are a business decision that can change,
    while purchase price history is an immutable audit trail.
    """
    recipe = get_object_or_404(Recipe, pk=recipe_id)

    if request.method == 'POST':
        form = SetSellingPriceForm(request.POST)
        if form.is_valid():
            recipe.selling_price = form.cleaned_data['selling_price']
            recipe.save(update_fields=['selling_price', 'updated_at'])
            messages.success(
                request,
                f"Selling price set for {recipe.name}: "
                f"£{recipe.selling_price} per {recipe.yields_unit.name}"
            )
        else:
            messages.error(request, "Invalid selling price.")

    return redirect('costing:recipe_costing')
