from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy


class StockEasyLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


class StockEasyLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:login')
