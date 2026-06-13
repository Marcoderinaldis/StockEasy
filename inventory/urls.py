from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('categories/', views.category_list, name='category_list'),
    path('units/', views.unit_list, name='unit_list'),
    path('stock/record/', views.stock_movement_create, name='stock_movement_create'),
]
