"""
Tests for RBAC decorators and mixins.

All test views and URLs are defined within this module.
No test routes are added to shipping urlconfs.
"""

from django.test import TestCase, override_settings
from django.http import HttpResponse
from django.urls import path
from django.views import View
from django.contrib.auth import get_user_model

from accounts.permissions import (
    admin_required,
    manager_required,
    staff_required,
    AdminRequiredMixin,
    ManagerRequiredMixin,
    StaffRequiredMixin,
)

CustomUser = get_user_model()


# -----------------------------------------------------------------------------
# Test-only views (FBV)
# -----------------------------------------------------------------------------

@staff_required
def staff_protected_view(request):
    return HttpResponse('staff_ok')


@manager_required
def manager_protected_view(request):
    return HttpResponse('manager_ok')


@admin_required
def admin_protected_view(request):
    return HttpResponse('admin_ok')


# -----------------------------------------------------------------------------
# Test-only views (CBV)
# -----------------------------------------------------------------------------

class StaffProtectedCBV(StaffRequiredMixin, View):
    def get(self, request):
        return HttpResponse('staff_cbv_ok')


class ManagerProtectedCBV(ManagerRequiredMixin, View):
    def get(self, request):
        return HttpResponse('manager_cbv_ok')


class AdminProtectedCBV(AdminRequiredMixin, View):
    def get(self, request):
        return HttpResponse('admin_cbv_ok')


# -----------------------------------------------------------------------------
# Test-only URL configuration
# -----------------------------------------------------------------------------

from django.urls import include

urlpatterns = [
    path('test/staff/', staff_protected_view, name='test_staff'),
    path('test/manager/', manager_protected_view, name='test_manager'),
    path('test/admin/', admin_protected_view, name='test_admin'),
    path('test/staff-cbv/', StaffProtectedCBV.as_view(), name='test_staff_cbv'),
    path('test/manager-cbv/', ManagerProtectedCBV.as_view(), name='test_manager_cbv'),
    path('test/admin-cbv/', AdminProtectedCBV.as_view(), name='test_admin_cbv'),
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('waste/', include('waste.urls')),
]


# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------

@override_settings(ROOT_URLCONF=__name__)
class RBACDecoratorTests(TestCase):
    """Tests for FBV decorators: staff_required, manager_required, admin_required."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        cls.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        cls.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )

    # -------------------------------------------------------------------------
    # staff_required tests
    # -------------------------------------------------------------------------

    def test_staff_required_anonymous_redirects_to_login(self):
        response = self.client.get('/test/staff/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_required_allows_staff(self):
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get('/test/staff/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'staff_ok')

    def test_staff_required_allows_manager(self):
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get('/test/staff/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'staff_ok')

    def test_staff_required_allows_admin(self):
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get('/test/staff/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'staff_ok')

    # -------------------------------------------------------------------------
    # manager_required tests
    # -------------------------------------------------------------------------

    def test_manager_required_anonymous_redirects_to_login(self):
        response = self.client.get('/test/manager/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_manager_required_denies_staff(self):
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get('/test/manager/')
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_manager_required_allows_manager(self):
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get('/test/manager/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'manager_ok')

    def test_manager_required_allows_admin(self):
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get('/test/manager/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'manager_ok')

    # -------------------------------------------------------------------------
    # admin_required tests
    # -------------------------------------------------------------------------

    def test_admin_required_anonymous_redirects_to_login(self):
        response = self.client.get('/test/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_admin_required_denies_staff(self):
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get('/test/admin/')
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_admin_required_denies_manager(self):
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get('/test/admin/')
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_admin_required_allows_admin(self):
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get('/test/admin/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'admin_ok')


@override_settings(ROOT_URLCONF=__name__)
class RBACMixinTests(TestCase):
    """Tests for CBV mixins: StaffRequiredMixin, ManagerRequiredMixin, AdminRequiredMixin."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = CustomUser.objects.create_user(
            username='staffuser_cbv',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        cls.manager_user = CustomUser.objects.create_user(
            username='manageruser_cbv',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        cls.admin_user = CustomUser.objects.create_user(
            username='adminuser_cbv',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )

    # -------------------------------------------------------------------------
    # StaffRequiredMixin tests
    # -------------------------------------------------------------------------

    def test_staff_mixin_anonymous_redirects_to_login(self):
        response = self.client.get('/test/staff-cbv/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_mixin_allows_staff(self):
        self.client.login(username='staffuser_cbv', password='testpass123')
        response = self.client.get('/test/staff-cbv/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'staff_cbv_ok')

    def test_staff_mixin_allows_manager(self):
        self.client.login(username='manageruser_cbv', password='testpass123')
        response = self.client.get('/test/staff-cbv/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'staff_cbv_ok')

    def test_staff_mixin_allows_admin(self):
        self.client.login(username='adminuser_cbv', password='testpass123')
        response = self.client.get('/test/staff-cbv/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'staff_cbv_ok')

    # -------------------------------------------------------------------------
    # ManagerRequiredMixin tests
    # -------------------------------------------------------------------------

    def test_manager_mixin_anonymous_redirects_to_login(self):
        response = self.client.get('/test/manager-cbv/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_manager_mixin_denies_staff(self):
        self.client.login(username='staffuser_cbv', password='testpass123')
        response = self.client.get('/test/manager-cbv/')
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_manager_mixin_allows_manager(self):
        self.client.login(username='manageruser_cbv', password='testpass123')
        response = self.client.get('/test/manager-cbv/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'manager_cbv_ok')

    def test_manager_mixin_allows_admin(self):
        self.client.login(username='adminuser_cbv', password='testpass123')
        response = self.client.get('/test/manager-cbv/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'manager_cbv_ok')

    # -------------------------------------------------------------------------
    # AdminRequiredMixin tests
    # -------------------------------------------------------------------------

    def test_admin_mixin_anonymous_redirects_to_login(self):
        response = self.client.get('/test/admin-cbv/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_admin_mixin_denies_staff(self):
        self.client.login(username='staffuser_cbv', password='testpass123')
        response = self.client.get('/test/admin-cbv/')
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_admin_mixin_denies_manager(self):
        self.client.login(username='manageruser_cbv', password='testpass123')
        response = self.client.get('/test/admin-cbv/')
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_admin_mixin_allows_admin(self):
        self.client.login(username='adminuser_cbv', password='testpass123')
        response = self.client.get('/test/admin-cbv/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'admin_cbv_ok')


@override_settings(ROOT_URLCONF=__name__)
class SuperuserBypassTests(TestCase):
    """Tests that superuser triggers is_admin and cascades to all roles."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(
            username='superuser',
            password='testpass123',
            email='super@test.local',
        )

    def test_superuser_triggers_is_admin(self):
        self.assertTrue(self.superuser.is_admin)

    def test_superuser_triggers_is_manager(self):
        self.assertTrue(self.superuser.is_manager)

    def test_superuser_triggers_is_staff_role(self):
        self.assertTrue(self.superuser.is_staff_role)

    def test_superuser_accesses_admin_protected(self):
        self.client.login(username='superuser', password='testpass123')
        response = self.client.get('/test/admin/')
        self.assertEqual(response.status_code, 200)

    def test_superuser_accesses_manager_protected(self):
        self.client.login(username='superuser', password='testpass123')
        response = self.client.get('/test/manager/')
        self.assertEqual(response.status_code, 200)

    def test_superuser_accesses_staff_protected(self):
        self.client.login(username='superuser', password='testpass123')
        response = self.client.get('/test/staff/')
        self.assertEqual(response.status_code, 200)


@override_settings(ROOT_URLCONF=__name__)
class RolePropertyHierarchyTests(TestCase):
    """Tests that role properties are correctly hierarchical."""

    def test_admin_role_has_is_admin(self):
        user = CustomUser(role=CustomUser.Role.ADMIN)
        self.assertTrue(user.is_admin)

    def test_admin_role_has_is_manager(self):
        user = CustomUser(role=CustomUser.Role.ADMIN)
        self.assertTrue(user.is_manager)

    def test_admin_role_has_is_staff_role(self):
        user = CustomUser(role=CustomUser.Role.ADMIN)
        self.assertTrue(user.is_staff_role)

    def test_manager_role_does_not_have_is_admin(self):
        user = CustomUser(role=CustomUser.Role.MANAGER)
        self.assertFalse(user.is_admin)

    def test_manager_role_has_is_manager(self):
        user = CustomUser(role=CustomUser.Role.MANAGER)
        self.assertTrue(user.is_manager)

    def test_manager_role_has_is_staff_role(self):
        user = CustomUser(role=CustomUser.Role.MANAGER)
        self.assertTrue(user.is_staff_role)

    def test_staff_role_does_not_have_is_admin(self):
        user = CustomUser(role=CustomUser.Role.STAFF)
        self.assertFalse(user.is_admin)

    def test_staff_role_does_not_have_is_manager(self):
        user = CustomUser(role=CustomUser.Role.STAFF)
        self.assertFalse(user.is_manager)

    def test_staff_role_has_is_staff_role(self):
        user = CustomUser(role=CustomUser.Role.STAFF)
        self.assertTrue(user.is_staff_role)
