from django.urls import path
from .views import StockEasyLoginView, StockEasyLogoutView

app_name = 'accounts'

urlpatterns = [
    path('login/', StockEasyLoginView.as_view(), name='login'),
    path('logout/', StockEasyLogoutView.as_view(), name='logout'),
]
