from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('categories/', views.category_list, name='category_list'),
    path('units/', views.unit_list, name='unit_list'),
    path('stock/record/', views.stock_movement_create, name='stock_movement_create'),
    path('movements/', views.movements_list, name='movements_list'),
    path('movements/<int:pk>/void/', views.void_movement_view, name='void_movement'),
    path('movements/<int:pk>/correct/', views.correct_movement_view, name='correct_movement'),
    path('void-dashboard/', views.void_dashboard, name='void_dashboard'),
]
