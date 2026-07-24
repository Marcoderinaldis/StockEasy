"""
Costing service exceptions.
"""


class PriceValidationError(Exception):
    """Raised when price validation fails."""
    pass


class MissingPriceError(Exception):
    """Raised when a product has no active price."""

    def __init__(self, product):
        self.product = product
        super().__init__(f'No active price for product: {product}')
