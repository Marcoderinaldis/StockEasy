"""
Inventory service exceptions.
"""


class StockValidationError(Exception):
    """Raised when stock operation validation fails."""
    pass


class InsufficientStockError(StockValidationError):
    """Raised when OUT would make stock negative."""
    pass


class UnitTypeMismatchError(StockValidationError):
    """Raised when unit types do not match."""
    pass


class OrderError(StockValidationError):
    """Raised when order placement validation fails."""
    pass
