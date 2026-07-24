"""
Waste service layer for StockEasy.

All waste recording MUST go through these service functions.
Each waste record creates a corresponding WASTE StockMovement atomically.

Valued wastage analytics (read-only aggregation) is also provided here.
"""

from inventory.services import (
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
)
from .recording import (
    _quantize_money,
    record_waste,
    record_dish_waste,
)
from .analytics import (
    K_ANON_MIN,
    ALLOWED_DIMENSIONS,
    _suppress_small_cells,
    valued_waste_by,
    valued_waste_summary,
)

__all__ = [
    # Re-exported from inventory.services
    'StockValidationError',
    'InsufficientStockError',
    'UnitTypeMismatchError',
    # Recording
    '_quantize_money',
    'record_waste',
    'record_dish_waste',
    # Analytics
    'K_ANON_MIN',
    'ALLOWED_DIMENSIONS',
    '_suppress_small_cells',
    'valued_waste_by',
    'valued_waste_summary',
]
