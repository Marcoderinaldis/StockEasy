from django.urls import path

from . import views

app_name = 'waste'

urlpatterns = [
    path('record/', views.record_waste_view, name='record_waste'),
]
