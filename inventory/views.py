from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse

from accounts.permissions import staff_required
from .models import Product, Category, Unit
from .forms import StockMovementForm
from .services import (
    record_movement,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
)


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


@staff_required
def stock_movement_create(request):
    """
    Record a stock movement (IN or OUT).

    Staff can record IN and OUT movements only.
    The view validates the form, then delegates to the service layer.
    No direct stock mutations happen in this view.
    """
    if request.method == 'POST':
        form = StockMovementForm(request.POST)
        if form.is_valid():
            try:
                movement = record_movement(
                    product=form.cleaned_data['product'],
                    movement_type=form.cleaned_data['movement_type'],
                    quantity=form.cleaned_data['quantity'],
                    unit=form.cleaned_data['unit'],
                    reason_category=form.cleaned_data.get('reason_category') or None,
                    reason_notes=form.cleaned_data.get('note') or None,
                    user=request.user,
                )
                messages.success(
                    request,
                    f'Stock movement recorded: {movement.get_movement_type_display()} '
                    f'{movement.quantity} {movement.product.unit.name} of {movement.product.name}.'
                )
                return redirect('inventory:stock_movement_create')
            except InsufficientStockError as e:
                form.add_error(None, str(e))
            except UnitTypeMismatchError as e:
                form.add_error('unit', str(e))
            except StockValidationError as e:
                form.add_error(None, str(e))
    else:
        form = StockMovementForm()

    return render(request, 'inventory/stock_movement_form.html', {'form': form})
