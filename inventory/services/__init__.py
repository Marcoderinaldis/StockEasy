"""
Inventory service layer for StockEasy.

All stock mutations MUST go through these service functions.
Direct model updates to Product.stock_quantity are NEVER allowed.
StockMovement is append-only; no updates or deletes ever.
"""

from .exceptions import (
    StockValidationError,
    InsufficientStockError,
    UnitTypeMismatchError,
    OrderError,
)
from .helpers import (
    QUANTITY_PRECISION,
    _quantize_quantity,
    convert_quantity_between_units,
    _snapshot_unit_cost,
)
from .movements import (
    record_movement,
    record_stock_in,
    record_stock_out,
    record_adjustment_in,
    record_adjustment_out,
)
from .corrections import (
    VOIDABLE_MOVEMENT_TYPES,
    CORRECTABLE_MOVEMENT_TYPES,
    is_voided,
    void_movement,
    is_corrected,
    correct_movement,
)
from .orders import place_order
from .stock_take import (
    StockTakeLinePreview,
    StockTakePreview,
    start_stock_take,
    record_count,
    record_counts,
    preview_stock_take,
    apply_stock_take,
)
from .analytics import (
    K_ANON_MIN,
    ALLOWED_VARIANCE_DIMENSIONS,
    usage_variance_by,
    usage_variance_summary,
    products_below_reorder_level,
)

__all__ = [
    # Exceptions
    'StockValidationError',
    'InsufficientStockError',
    'UnitTypeMismatchError',
    'OrderError',
    # Helpers
    'QUANTITY_PRECISION',
    '_quantize_quantity',
    'convert_quantity_between_units',
    '_snapshot_unit_cost',
    # Movements
    'record_movement',
    'record_stock_in',
    'record_stock_out',
    'record_adjustment_in',
    'record_adjustment_out',
    # Corrections
    'VOIDABLE_MOVEMENT_TYPES',
    'CORRECTABLE_MOVEMENT_TYPES',
    'is_voided',
    'void_movement',
    'is_corrected',
    'correct_movement',
    # Orders
    'place_order',
    # Stock Take
    'StockTakeLinePreview',
    'StockTakePreview',
    'start_stock_take',
    'record_count',
    'record_counts',
    'preview_stock_take',
    'apply_stock_take',
    # Variance Analytics
    'K_ANON_MIN',
    'ALLOWED_VARIANCE_DIMENSIONS',
    'usage_variance_by',
    'usage_variance_summary',
    # Stock Level Queries
    'products_below_reorder_level',
]
