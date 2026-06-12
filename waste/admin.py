from django.contrib import admin
from .models import WasteRecord


@admin.register(WasteRecord)
class WasteRecordAdmin(admin.ModelAdmin):
    list_display = ('product', 'waste_category', 'quantity_wasted', 'recorded_by', 'recorded_at')
    list_filter = ('waste_category', 'recorded_at')
    search_fields = ('product__name', 'notes')
    readonly_fields = ('recorded_at',)
