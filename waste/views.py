from django.contrib import messages
from django.shortcuts import render, redirect

from accounts.permissions import staff_required
from .forms import WasteRecordForm
from .services import (
    record_waste,
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
