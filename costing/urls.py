from django.urls import path
from . import views

app_name = 'costing'

urlpatterns = [
    path('', views.costing_home, name='costing_home'),
    path('prices/', views.costing_home, name='index'),  # Alias for backward compatibility
    path('prices/<int:product_id>/history/', views.price_history, name='price_history'),
    path('prices/update/', views.update_price, name='update_price'),
    path('prices/<int:product_id>/update/', views.update_price, name='update_price_for_product'),
    path('recipes/', views.recipe_costing, name='recipe_costing'),
    path('recipes/<int:recipe_id>/set-price/', views.set_selling_price, name='set_selling_price'),
]
