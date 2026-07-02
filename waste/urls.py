from django.urls import path

from . import views

app_name = 'waste'

urlpatterns = [
    path('record/', views.record_waste_view, name='record_waste'),
    path('analytics/valued-waste/', views.valued_waste_analytics, name='valued_waste_analytics'),
]
