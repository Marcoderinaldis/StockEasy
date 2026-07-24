from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            Unit, Category, Product, PurchasePrice, StockMovement,
            Order, OrderLine, StockTake, StockTakeLine,
        )

        auditlog.register(Unit)
        auditlog.register(Category)
        auditlog.register(Product)
        auditlog.register(PurchasePrice)
        auditlog.register(StockMovement)
        auditlog.register(Order)
        auditlog.register(OrderLine)
        auditlog.register(StockTake)
        auditlog.register(StockTakeLine)
