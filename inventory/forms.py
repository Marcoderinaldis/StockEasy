"""
Stock movement forms for StockEasy.

Staff can record IN and OUT movements only.
WASTE, VOID, and ADJUSTMENT types are not exposed in this form.
"""

from decimal import Decimal, InvalidOperation
from datetime import date

from django import forms

from .models import Product, Unit, StockMovement


class MovementFilterForm(forms.Form):
    """
    Filter form for the movements list view.

    Filters by product, movement_type, and date range.
    NO user/recorded_by filter — per-person filtering is prohibited.
    """

    MOVEMENT_TYPE_FILTER_CHOICES = [
        ('', 'All types'),
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
    ]

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True).order_by('name'),
        required=False,
        empty_label='All products',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    movement_type = forms.ChoiceField(
        choices=MOVEMENT_TYPE_FILTER_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
        }),
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
        }),
    )

    def clean(self):
        """Validate date range is sensible."""
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError('Date from cannot be after date to.')

        return cleaned_data


class StockMovementForm(forms.Form):
    """
    Form for recording stock IN and OUT movements.

    Rules:
    - movement_type limited to IN and OUT only
    - reason_category required for OUT, not required for IN
    - quantity must be positive
    - unit must match product's unit_type
    - note max 200 chars, optional
    """

    STAFF_MOVEMENT_CHOICES = [
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
    ]

    REASON_CHOICES = [
        ('', '---------'),
        ('Product expired', 'Product Expired'),
        ('Delivery damaged', 'Delivery Damaged'),
        ('Counting error', 'Counting Error'),
        ('Spillage/accidental waste', 'Spillage/Accidental Waste'),
        ('Void—entered in error', 'Void—Entered in Error'),
        ('Other', 'Other'),
    ]

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True).select_related('unit'),
        empty_label='Select a product',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    movement_type = forms.ChoiceField(
        choices=STAFF_MOVEMENT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_movement_type'}),
    )

    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal('0.0001'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.0001',
            'min': '0.0001',
            'placeholder': 'Enter quantity',
        }),
    )

    unit = forms.ModelChoiceField(
        queryset=Unit.objects.all(),
        empty_label='Select unit',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    reason_category = forms.ChoiceField(
        choices=REASON_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_reason_category'}),
    )

    note = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional operational note. Do not include staff names unless necessary.',
        }),
    )

    def clean_quantity(self):
        """Ensure quantity is positive."""
        quantity = self.cleaned_data.get('quantity')
        if quantity is None:
            raise forms.ValidationError('Quantity is required.')
        if quantity <= Decimal('0'):
            raise forms.ValidationError('Quantity must be positive.')
        return quantity

    def clean(self):
        """
        Cross-field validation:
        - unit_type must match product's unit_type
        - reason_category required for OUT movements
        """
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        unit = cleaned_data.get('unit')
        movement_type = cleaned_data.get('movement_type')
        reason_category = cleaned_data.get('reason_category')

        if product and unit:
            if product.unit.unit_type != unit.unit_type:
                raise forms.ValidationError(
                    f'Unit type mismatch: {unit.name} ({unit.unit_type}) '
                    f'cannot be used with {product.name} ({product.unit.unit_type}).'
                )

        if movement_type == 'OUT' and not reason_category:
            self.add_error('reason_category', 'Reason is required for Stock Out movements.')

        return cleaned_data


class VoidMovementForm(forms.Form):
    """
    Form for voiding a stock movement.

    Justification is mandatory — managers must explain why they are voiding.
    """

    justification = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Explain why this movement is being voided (required).',
        }),
        error_messages={'required': 'Justification is required when voiding a movement.'},
    )

    def clean_justification(self):
        """Ensure justification is not blank."""
        justification = self.cleaned_data.get('justification')
        if not justification or not justification.strip():
            raise forms.ValidationError('Justification is required when voiding a movement.')
        return justification.strip()


class VoidDashboardFilterForm(forms.Form):
    """
    Filter form for the void dashboard.

    Filters by product and date range.
    NO user/recorded_by filter — per-person filtering is prohibited.
    """

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True).order_by('name'),
        required=False,
        empty_label='All products',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
        }),
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
        }),
    )

    def clean(self):
        """Validate date range is sensible."""
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError('Date from cannot be after date to.')

        return cleaned_data
