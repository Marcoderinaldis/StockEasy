from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import staff_required, manager_required
from .models import Product, Category, Unit, StockMovement
from .forms import StockMovementForm, MovementFilterForm, VoidMovementForm, VoidDashboardFilterForm, CorrectMovementForm
from .services import (
    record_movement,
    void_movement,
    correct_movement,
    is_voided,
    is_corrected,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
    VOIDABLE_MOVEMENT_TYPES,
    CORRECTABLE_MOVEMENT_TYPES,
    products_below_reorder_level,
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


@staff_required
def movements_list(request):
    """
    Read-only paginated list of stock movements with filters.

    Filters: product, movement_type, date_from, date_to.
    NO user/recorded_by filter — per-person filtering is prohibited.

    The 'recorded by' column is visible to managers/admins only.
    Staff see the ledger without the recorder column.

    The 'Actions' column (Void button) is visible to managers/admins only.
    """
    # Prefetch voided_by and corrected_by to avoid N+1 when checking status
    queryset = StockMovement.objects.select_related(
        'product', 'product__unit', 'recorded_by', 'voided_by'
    ).prefetch_related(
        'corrected_by'
    )

    form = MovementFilterForm(request.GET or None)

    if form.is_valid():
        product = form.cleaned_data.get('product')
        movement_type = form.cleaned_data.get('movement_type')
        date_from = form.cleaned_data.get('date_from')
        date_to = form.cleaned_data.get('date_to')

        if product:
            queryset = queryset.filter(product=product)

        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)

        if date_from:
            queryset = queryset.filter(recorded_at__date__gte=date_from)

        if date_to:
            queryset = queryset.filter(recorded_at__date__lte=date_to)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    show_recorder_column = request.user.is_manager
    show_actions = request.user.is_manager

    return render(request, 'inventory/movements_list.html', {
        'form': form,
        'page_obj': page_obj,
        'show_recorder_column': show_recorder_column,
        'show_actions': show_actions,
        'voidable_types': VOIDABLE_MOVEMENT_TYPES,
    })


@manager_required
def void_movement_view(request, pk):
    """
    Void a stock movement.

    Manager-only. GET shows a confirmation form with the movement details.
    POST validates justification and calls the service.
    No direct stock mutation in this view — service only.
    """
    movement = get_object_or_404(
        StockMovement.objects.select_related('product', 'product__unit', 'recorded_by'),
        pk=pk
    )

    # Check if movement can be voided (for display purposes)
    movement_is_voided = is_voided(movement)
    can_void = (
        movement.movement_type in VOIDABLE_MOVEMENT_TYPES
        and not movement_is_voided
    )

    if request.method == 'POST':
        form = VoidMovementForm(request.POST)
        if form.is_valid():
            try:
                void_record = void_movement(
                    movement=movement,
                    reason_notes=form.cleaned_data['justification'],
                    user=request.user,
                )
                messages.success(
                    request,
                    f'Movement voided: {movement.get_movement_type_display()} of '
                    f'{movement.quantity} {movement.product.unit.name} '
                    f'{movement.product.name} has been reversed.'
                )
                return redirect('inventory:movements_list')
            except InsufficientStockError as e:
                form.add_error(None, str(e))
            except StockValidationError as e:
                form.add_error(None, str(e))
    else:
        form = VoidMovementForm()

    return render(request, 'inventory/void_movement.html', {
        'form': form,
        'movement': movement,
        'can_void': can_void,
        'movement_is_voided': movement_is_voided,
    })


@manager_required
def correct_movement_view(request, pk):
    """
    Correct a stock movement.

    Manager-only. GET shows a correction form with the original movement details.
    POST validates and calls the correct_movement service.
    No direct stock mutation in this view — service only.
    """
    movement = get_object_or_404(
        StockMovement.objects.select_related('product', 'product__unit', 'recorded_by'),
        pk=pk
    )

    # Check if movement can be corrected (for display purposes)
    movement_is_voided = is_voided(movement)
    movement_is_corrected = is_corrected(movement)
    can_correct = (
        movement.movement_type in CORRECTABLE_MOVEMENT_TYPES
        and not movement_is_voided
        and not movement_is_corrected
    )

    if request.method == 'POST':
        form = CorrectMovementForm(request.POST, product=movement.product)
        if form.is_valid():
            try:
                replacement = correct_movement(
                    original=movement,
                    corrected_quantity=form.cleaned_data['corrected_quantity'],
                    corrected_unit=form.cleaned_data['corrected_unit'],
                    corrected_reason_category=form.cleaned_data.get('corrected_reason_category') or None,
                    corrected_notes=form.cleaned_data.get('corrected_notes') or None,
                    justification=form.cleaned_data['justification'],
                    user=request.user,
                )
                messages.success(
                    request,
                    f'Movement corrected: {movement.get_movement_type_display()} of '
                    f'{movement.quantity} {movement.product.unit.name} '
                    f'{movement.product.name} corrected to {replacement.quantity} '
                    f'{replacement.product.unit.name}.'
                )
                return redirect('inventory:void_dashboard')
            except InsufficientStockError as e:
                form.add_error(None, str(e))
            except UnitTypeMismatchError as e:
                form.add_error('corrected_unit', str(e))
            except StockValidationError as e:
                form.add_error(None, str(e))
    else:
        # Pre-fill with original values
        form = CorrectMovementForm(
            product=movement.product,
            initial={
                'corrected_quantity': movement.quantity,
                'corrected_unit': movement.product.unit,
                'corrected_reason_category': movement.reason_category or '',
                'corrected_notes': movement.reason_notes or '',
            }
        )

    return render(request, 'inventory/correct_movement.html', {
        'form': form,
        'movement': movement,
        'can_correct': can_correct,
        'movement_is_voided': movement_is_voided,
        'movement_is_corrected': movement_is_corrected,
    })


@manager_required
def void_dashboard(request):
    """
    Void/correction dashboard for managers.

    Two sections:
    1. Voidable/Correctable worklist — movements that CAN still be voided/corrected
       (IN, OUT, WASTE not yet voided or corrected)
    2. Void & Correction History — VOID movements with labels for pure void vs correction

    Manager-only (staff get 403).
    NO user/recorded_by filter — per-person filtering is prohibited.
    """
    form = VoidDashboardFilterForm(request.GET or None)

    # Base querysets with prefetch to avoid N+1
    # Exclude movements that are already voided OR already corrected
    voidable_base = StockMovement.objects.select_related(
        'product', 'product__unit', 'recorded_by'
    ).prefetch_related(
        'corrected_by'  # Prefetch to check is_corrected efficiently
    ).filter(
        movement_type__in=VOIDABLE_MOVEMENT_TYPES
    ).exclude(
        voided_by__isnull=False  # Exclude already voided
    ).exclude(
        corrected_by__isnull=False  # Exclude already corrected
    )

    # History shows VOID movements; we determine correction vs pure-void
    # by whether a replacement (corrects=original) exists
    void_history_base = StockMovement.objects.select_related(
        'product', 'product__unit', 'recorded_by', 'voids', 'voids__product'
    ).prefetch_related(
        'voids__corrected_by'  # To check if original has a replacement
    ).filter(
        movement_type='VOID'
    )

    # Apply filters
    if form.is_valid():
        product = form.cleaned_data.get('product')
        date_from = form.cleaned_data.get('date_from')
        date_to = form.cleaned_data.get('date_to')

        if product:
            voidable_base = voidable_base.filter(product=product)
            void_history_base = void_history_base.filter(product=product)

        if date_from:
            voidable_base = voidable_base.filter(recorded_at__date__gte=date_from)
            void_history_base = void_history_base.filter(recorded_at__date__gte=date_from)

        if date_to:
            voidable_base = voidable_base.filter(recorded_at__date__lte=date_to)
            void_history_base = void_history_base.filter(recorded_at__date__lte=date_to)

    # Paginate voidable worklist (newest first)
    voidable_paginator = Paginator(voidable_base.order_by('-recorded_at'), 25)
    voidable_page_number = request.GET.get('voidable_page')
    voidable_page = voidable_paginator.get_page(voidable_page_number)

    # Paginate void history (newest first)
    history_paginator = Paginator(void_history_base.order_by('-recorded_at'), 25)
    history_page_number = request.GET.get('history_page')
    history_page = history_paginator.get_page(history_page_number)

    return render(request, 'inventory/void_dashboard.html', {
        'form': form,
        'voidable_page': voidable_page,
        'history_page': history_page,
    })


@login_required
def low_stock(request):
    """
    Products at or below their reorder level — what needs reordering.

    Read-only list showing active products whose stock has fallen to or below
    their configured reorder threshold. Products with reorder_level of 0 are
    not tracked for reordering and are excluded.

    Accessible to all authenticated users (staff need to know what to reorder).
    """
    products = products_below_reorder_level()
    return render(request, 'inventory/low_stock.html', {
        'products': products,
        'count': products.count(),
    })
