from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.ingredient_list, name='ingredient_list'),
]
