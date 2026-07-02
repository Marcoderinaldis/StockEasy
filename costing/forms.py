"""
Forms for the Costing section.
"""

from decimal import Decimal

from django import forms

from inventory.models import Product


class UpdatePriceForm(forms.Form):
    """
    Form for updating a product's price.

    Manager/admin use only. Accepts a positive unit price with up to 2 decimal places.
    """

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True).order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Select the product to update",
    )
    unit_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.01',
            'placeholder': '0.00',
        }),
        help_text="Enter the new price per unit",
    )

    def clean_unit_price(self):
        """Ensure price is positive."""
        price = self.cleaned_data.get('unit_price')
        if price is not None and price <= 0:
            raise forms.ValidationError("Price must be positive.")
        return price
