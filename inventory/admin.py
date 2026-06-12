from django.contrib import admin
from .models import Unit, Category, Product, PurchasePrice, StockMovement


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit_type', 'conversion_to_base', 'base_unit_name', 'created_at')
    list_filter = ('unit_type',)
    search_fields = ('name', 'base_unit_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')


class PurchasePriceInline(admin.TabularInline):
    model = PurchasePrice
    extra = 0
    readonly_fields = ('effective_from', 'created_by', 'created_at')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'unit', 'stock_quantity', 'reorder_level', 'is_active', 'updated_at')
    list_filter = ('category', 'is_active', 'unit')
    search_fields = ('name',)
    readonly_fields = ('stock_quantity', 'created_at', 'updated_at')
    inlines = [PurchasePriceInline]


@admin.register(PurchasePrice)
class PurchasePriceAdmin(admin.ModelAdmin):
    list_display = ('product', 'unit_price', 'currency', 'effective_from', 'effective_to', 'created_by')
    list_filter = ('currency', 'effective_from')
    search_fields = ('product__name',)
    readonly_fields = ('effective_from', 'created_at')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """
    StockMovement is append-only. No add/change/delete allowed via admin.
    All operations must go through the service layer.
    """
    list_display = ('product', 'movement_type', 'quantity', 'reason_category', 'recorded_by', 'recorded_at')
    list_filter = ('movement_type', 'reason_category', 'recorded_at')
    search_fields = ('product__name', 'reason_notes', 'reference_id')
    readonly_fields = (
        'product', 'quantity', 'movement_type', 'reason_category',
        'reason_notes', 'recorded_by', 'recorded_at', 'reference_id'
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
