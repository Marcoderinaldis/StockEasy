from django.contrib import messages
from django.shortcuts import render, redirect

from accounts.permissions import staff_required, manager_required
from .forms import WasteRecordForm, ValuedWasteFilterForm
from .services import (
    record_waste,
    valued_waste_summary,
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
)


@staff_required
def record_waste_view(request):
    """
    Record a waste entry.

    Staff can record waste (managers/admins pass via hierarchy).
    GET renders the form; POST validates then calls the service.
    No direct stock mutation in the view - the service owns all writes.
    """
    if request.method == 'POST':
        form = WasteRecordForm(request.POST)
        if form.is_valid():
            try:
                waste_record = record_waste(
                    product=form.cleaned_data['product'],
                    quantity=form.cleaned_data['quantity'],
                    unit=form.cleaned_data['unit'],
                    waste_category=form.cleaned_data['waste_category'],
                    user=request.user,
                    notes=form.cleaned_data.get('notes') or None,
                )
                messages.success(
                    request,
                    f'Waste recorded: {waste_record.quantity_wasted} '
                    f'{waste_record.product.unit.name} of {waste_record.product.name}.'
                )
                return redirect('waste:record_waste')
            except InsufficientStockError as e:
                form.add_error(None, str(e))
            except UnitTypeMismatchError as e:
                form.add_error('unit', str(e))
            except StockValidationError as e:
                form.add_error(None, str(e))
    else:
        form = WasteRecordForm()

    return render(request, 'waste/record_waste.html', {'form': form})


@manager_required
def valued_waste_analytics(request):
    """
    Manager/admin-only valued wastage analytics.

    Displays aggregate-only, k-anonymised waste data grouped by product and
    reason category. No per-person breakdown — staff cannot reach this view
    (403). Rows with no price snapshot are surfaced separately as unvalued
    waste so loss is never understated.
    """
    form = ValuedWasteFilterForm(request.GET or None)

    # Extract filters if form is valid (or empty = no filters)
    date_from = None
    date_to = None
    category = None
    product = None

    if form.is_valid():
        date_from = form.cleaned_data.get('date_from')
        date_to = form.cleaned_data.get('date_to')
        category = form.cleaned_data.get('category') or None
        product = form.cleaned_data.get('product')

    # Get aggregated summary
    summary = valued_waste_summary(
        date_from=date_from,
        date_to=date_to,
        category=category,
        product=product,
    )

    return render(request, 'waste/valued_waste_analytics.html', {
        'form': form,
        'summary': summary,
    })
