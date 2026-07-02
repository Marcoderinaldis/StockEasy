"""
Waste recording forms for StockEasy.

Staff can record waste, which always decreases stock.
"""

from decimal import Decimal

from django import forms

from inventory.models import Product, Unit, StockMovement


class WasteRecordForm(forms.Form):
    """
    Form for recording waste.

    Rules:
    - waste_category is REQUIRED
    - quantity must be positive
    - unit must match product's unit_type
    - notes max 200 chars, optional
    - no movement_type selector (waste is always an outflow)
    """

    # Build choices from canonical source with empty option
    WASTE_CATEGORY_CHOICES = [
        ('', '---------'),
    ] + list(StockMovement.REASON_CATEGORY_CHOICES)

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True).select_related('unit'),
        empty_label='Select a product',
        widget=forms.Select(attrs={'class': 'form-select'}),
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

    waste_category = forms.ChoiceField(
        choices=WASTE_CATEGORY_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
        error_messages={'required': 'Waste category is required.'},
    )

    notes = forms.CharField(
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

    def clean_waste_category(self):
        """Ensure waste_category is provided."""
        waste_category = self.cleaned_data.get('waste_category')
        if not waste_category or not waste_category.strip():
            raise forms.ValidationError('Waste category is required.')
        return waste_category

    def clean(self):
        """
        Cross-field validation:
        - unit_type must match product's unit_type
        """
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        unit = cleaned_data.get('unit')

        if product and unit:
            if product.unit.unit_type != unit.unit_type:
                raise forms.ValidationError(
                    f'Unit type mismatch: {unit.name} ({unit.unit_type}) '
                    f'cannot be used with {product.name} ({product.unit.unit_type}).'
                )

        return cleaned_data
