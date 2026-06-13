"""
Role-based access control decorators and mixins for StockEasy.

Uses the hierarchical role properties defined on CustomUser:
- is_admin: Admin role or superuser
- is_manager: Manager role or is_admin
- is_staff_role: Staff role or is_manager

Note: CustomUser.is_staff is Django's admin-site flag, NOT the business role.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render


def _check_role(user, role_property):
    """Check if user has the required role property."""
    return getattr(user, role_property, False)


def _render_403(request):
    """Render 403.html with HTTP 403 status."""
    return render(request, '403.html', status=403)


def role_required(*role_properties):
    """
    Decorator that requires the user to have at least one of the specified
    role properties (is_admin, is_manager, is_staff_role).

    Anonymous users are redirected to login.
    Authenticated users without the required role get HTTP 403.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())

            for role_prop in role_properties:
                if _check_role(request.user, role_prop):
                    return view_func(request, *args, **kwargs)

            return _render_403(request)
        return _wrapped_view
    return decorator


def admin_required(view_func):
    """
    Decorator that requires Admin role.
    Uses CustomUser.is_admin property (Admin role or superuser).
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        if not request.user.is_admin:
            return _render_403(request)

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def manager_required(view_func):
    """
    Decorator that requires Manager role or above.
    Uses CustomUser.is_manager property (Manager, Admin, or superuser).
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        if not request.user.is_manager:
            return _render_403(request)

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def staff_required(view_func):
    """
    Decorator that requires Staff role or above.
    Uses CustomUser.is_staff_role property (Staff, Manager, Admin, or superuser).
    This is the minimum business-user access level.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        if not request.user.is_staff_role:
            return _render_403(request)

        return view_func(request, *args, **kwargs)
    return _wrapped_view


class RoleRequiredMixin(LoginRequiredMixin):
    """
    CBV mixin that requires specific role properties.
    Set role_properties as a list of property names to check.

    Anonymous users are redirected to login.
    Authenticated users without the required role get HTTP 403.
    """
    role_properties = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        for role_prop in self.role_properties:
            if _check_role(request.user, role_prop):
                return super().dispatch(request, *args, **kwargs)

        return _render_403(request)


class AdminRequiredMixin(LoginRequiredMixin):
    """
    CBV mixin that requires Admin role.
    Uses CustomUser.is_admin property (Admin role or superuser).
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_admin:
            return _render_403(request)

        return super().dispatch(request, *args, **kwargs)


class ManagerRequiredMixin(LoginRequiredMixin):
    """
    CBV mixin that requires Manager role or above.
    Uses CustomUser.is_manager property (Manager, Admin, or superuser).
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_manager:
            return _render_403(request)

        return super().dispatch(request, *args, **kwargs)


class StaffRequiredMixin(LoginRequiredMixin):
    """
    CBV mixin that requires Staff role or above.
    Uses CustomUser.is_staff_role property (Staff, Manager, Admin, or superuser).
    This is the minimum business-user access level.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_staff_role:
            return _render_403(request)

        return super().dispatch(request, *args, **kwargs)
