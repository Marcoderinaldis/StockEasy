from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('waste/', include('waste.urls')),
    path('recipes/', include('recipes.urls')),
    path('costing/', include('costing.urls')),
    path('', include('core.urls')),
]
