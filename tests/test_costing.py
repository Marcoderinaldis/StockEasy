"""
Tests for the Costing section (Feature 8).

Tests cover:
- Product.current_price property
- set_product_price service (append-only, closing old prices, validation)
- Costing views (RBAC, listing, history, update)
- Service-only price mutation (no direct model manipulation in views)
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from inventory.models import Product, Category, Unit, PurchasePrice
from costing.services import set_product_price, PriceValidationError

CustomUser = get_user_model()


class ProductCurrentPricePropertyTests(TestCase):
    """Tests for Product.current_price property."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )

    def test_current_price_returns_active_price(self):
        """current_price returns the price with effective_to=null."""
        price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        self.assertEqual(self.product.current_price, price)

    def test_current_price_returns_none_when_no_price(self):
        """current_price returns None if no active price exists."""
        self.assertIsNone(self.product.current_price)

    def test_current_price_returns_none_when_all_closed(self):
        """current_price returns None if all prices are closed."""
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=timezone.now(),  # Closed
        )

        self.assertIsNone(self.product.current_price)

    def test_current_price_returns_latest_when_multiple_active(self):
        """If multiple active prices exist, return the latest by effective_from."""
        # Create older price
        older_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # Create newer price (auto_now_add will make it newer)
        newer_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('3.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # The newer one should be returned
        self.assertEqual(self.product.current_price, newer_price)


class SetProductPriceServiceTests(TransactionTestCase):
    """Tests for the set_product_price service function."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )

    def test_set_price_creates_new_active_price(self):
        """set_product_price creates a new active price."""
        new_price = set_product_price(
            product=self.product,
            unit_price=Decimal('5.00'),
            user=self.user,
        )

        self.assertIsNotNone(new_price)
        self.assertEqual(new_price.unit_price, Decimal('5.00'))
        self.assertEqual(new_price.product, self.product)
        self.assertEqual(new_price.created_by, self.user)
        self.assertIsNone(new_price.effective_to)  # Active
        self.assertEqual(new_price.currency, 'GBP')

    def test_set_price_closes_old_active_price(self):
        """Adding a new price closes the old active price."""
        # Create initial price
        old_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # Set new price
        new_price = set_product_price(
            product=self.product,
            unit_price=Decimal('3.00'),
            user=self.user,
        )

        # Old price should be closed
        old_price.refresh_from_db()
        self.assertIsNotNone(old_price.effective_to)

        # New price should be active
        self.assertIsNone(new_price.effective_to)

    def test_set_price_leaves_only_one_active(self):
        """After setting a price, exactly one active price remains."""
        # Create two initial active prices (edge case)
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )

        # Set new price
        set_product_price(
            product=self.product,
            unit_price=Decimal('3.00'),
            user=self.user,
        )

        # Only one active price should exist
        active_prices = PurchasePrice.objects.filter(
            product=self.product,
            effective_to__isnull=True
        )
        self.assertEqual(active_prices.count(), 1)
        self.assertEqual(active_prices.first().unit_price, Decimal('3.00'))

    def test_set_price_does_not_modify_old_unit_price(self):
        """Old price's unit_price is never modified (append-only)."""
        old_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )
        original_unit_price = old_price.unit_price

        # Set new price
        set_product_price(
            product=self.product,
            unit_price=Decimal('3.00'),
            user=self.user,
        )

        # Old price's unit_price unchanged
        old_price.refresh_from_db()
        self.assertEqual(old_price.unit_price, original_unit_price)

    def test_set_price_validates_positive_price(self):
        """Zero or negative price raises PriceValidationError."""
        with self.assertRaises(PriceValidationError):
            set_product_price(
                product=self.product,
                unit_price=Decimal('0'),
                user=self.user,
            )

        with self.assertRaises(PriceValidationError):
            set_product_price(
                product=self.product,
                unit_price=Decimal('-1.00'),
                user=self.user,
            )

    def test_set_price_validates_numeric_input(self):
        """Invalid price input raises PriceValidationError."""
        with self.assertRaises(PriceValidationError):
            set_product_price(
                product=self.product,
                unit_price='not_a_number',
                user=self.user,
            )

    def test_set_price_quantizes_to_two_decimal_places(self):
        """Price is quantized to 2 decimal places."""
        new_price = set_product_price(
            product=self.product,
            unit_price=Decimal('2.567'),
            user=self.user,
        )

        self.assertEqual(new_price.unit_price, Decimal('2.57'))

    def test_set_price_accepts_string_input(self):
        """Price can be provided as a string."""
        new_price = set_product_price(
            product=self.product,
            unit_price='5.99',
            user=self.user,
        )

        self.assertEqual(new_price.unit_price, Decimal('5.99'))

    def test_set_price_accepts_float_input(self):
        """Price can be provided as a float."""
        new_price = set_product_price(
            product=self.product,
            unit_price=5.99,
            user=self.user,
        )

        self.assertEqual(new_price.unit_price, Decimal('5.99'))


class CostingHomeViewTests(TestCase):
    """Tests for the costing home view."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )
        self.url = reverse('costing:costing_home')

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_can_view(self):
        """Staff user can view costing home."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product Prices')

    def test_manager_can_view(self):
        """Manager user can view costing home."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_view(self):
        """Admin user can view costing home."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_lists_products_with_current_price(self):
        """View lists products with their current prices."""
        price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=None,
        )

        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, 'Tomatoes')
        self.assertContains(response, '2.50')

    def test_staff_does_not_see_update_button(self):
        """Staff user does not see Update Price button."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertNotContains(response, 'Update Price')

    def test_manager_sees_update_button(self):
        """Manager user sees Update Price button."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, 'Update Price')


class PriceHistoryViewTests(TestCase):
    """Tests for the price history view."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )
        self.url = reverse('costing:price_history', args=[self.product.pk])

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_can_view(self):
        """Staff user can view price history."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Price History')
        self.assertContains(response, 'Tomatoes')

    def test_shows_active_and_closed_prices(self):
        """View shows both active and closed prices."""
        # Create closed price
        closed_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=timezone.now(),
        )

        # Create active price
        active_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=None,
        )

        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, '2.00')
        self.assertContains(response, '2.50')
        self.assertContains(response, 'Current')
        self.assertContains(response, 'Closed')


class UpdatePriceViewTests(TestCase):
    """Tests for the update price view."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        self.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )
        self.url = reverse('costing:update_price')

    def test_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_staff_get_403(self):
        """Staff user gets 403 on GET."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_post_403(self):
        """Staff user gets 403 on POST."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'unit_price': '5.00',
        })
        self.assertEqual(response.status_code, 403)

    def test_manager_can_access(self):
        """Manager user can access update price view."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Update Product Price')

    def test_admin_can_access(self):
        """Admin user can access update price view."""
        self.client.login(username='adminuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_successful_post_creates_price_via_service(self):
        """Successful POST creates a new price using the service."""
        # Create initial price
        old_price = PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.50'),
            currency='GBP',
            created_by=self.admin_user,
            effective_to=None,
        )

        self.client.login(username='manageruser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'unit_price': '3.99',
        })

        # Redirects on success
        self.assertEqual(response.status_code, 302)

        # Old price is closed
        old_price.refresh_from_db()
        self.assertIsNotNone(old_price.effective_to)

        # New price is active
        new_price = self.product.current_price
        self.assertIsNotNone(new_price)
        self.assertEqual(new_price.unit_price, Decimal('3.99'))
        self.assertEqual(new_price.created_by, self.manager_user)

    def test_post_with_preselected_product(self):
        """POST to product-specific URL works."""
        url = reverse('costing:update_price_for_product', args=[self.product.pk])

        self.client.login(username='adminuser', password='testpass123')
        response = self.client.post(url, {
            'product': self.product.pk,
            'unit_price': '4.50',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.current_price.unit_price, Decimal('4.50'))

    def test_invalid_price_shows_error(self):
        """Invalid price shows form error."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.post(self.url, {
            'product': self.product.pk,
            'unit_price': '0',  # Invalid
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ensure this value is greater than or equal to 0.01')


class ServiceOnlyPriceMutationTests(TestCase):
    """Tests to ensure price mutation only happens via service."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        self.admin_user = CustomUser.objects.create_user(
            username='adminuser',
            password='testpass123',
            role=CustomUser.Role.ADMIN,
        )
        self.url = reverse('costing:update_price')

    def test_view_uses_service_for_price_creation(self):
        """View uses set_product_price service, not direct model creation."""
        with patch('costing.views.set_product_price') as mock_service:
            mock_service.return_value = PurchasePrice(
                product=self.product,
                unit_price=Decimal('5.00'),
                currency='GBP',
            )

            self.client.login(username='adminuser', password='testpass123')
            self.client.post(self.url, {
                'product': self.product.pk,
                'unit_price': '5.00',
            })

            mock_service.assert_called_once()
            call_args = mock_service.call_args
            self.assertEqual(call_args.kwargs['product'], self.product)
            self.assertEqual(call_args.kwargs['unit_price'], Decimal('5.00'))
            self.assertEqual(call_args.kwargs['user'], self.admin_user)


class NavbarCostingLinkTests(TestCase):
    """Tests for the Costing link in the navbar."""

    def setUp(self):
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.url = reverse('core:home')

    def test_costing_link_visible_to_authenticated_users(self):
        """Costing link is visible to authenticated users."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, 'Costing')
        self.assertContains(response, reverse('costing:costing_home'))


# ---------------------------------------------------------------------------
# F14: Recipe Margin and Selling Price Tests
# ---------------------------------------------------------------------------

from recipes.models import Recipe, RecipeIngredient
from costing.services import (
    calculate_recipe_margin,
    suggest_selling_price,
    calculate_recipe_cost,
)


class CalculateRecipeMarginTests(TransactionTestCase):
    """Tests for calculate_recipe_margin service function."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        # Set a price for the product: £2.00 per kg
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )
        # Create a recipe: 5kg tomatoes yields 10 portions
        # Total cost = 5kg × £2/kg = £10
        # Cost per portion = £10 / 10 = £1.00
        self.recipe = Recipe.objects.create(
            name='Tomato Soup',
            yields_quantity=Decimal('10.0000'),
            yields_unit=self.kg_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.product,
            quantity=Decimal('5.0000'),
            unit=self.kg_unit,
        )

    def test_food_cost_percent_correct_for_known_recipe(self):
        """Food-cost % is correctly calculated for a known recipe."""
        # Cost per portion = £1.00, selling price = £4.00
        # Food-cost % = (1.00 / 4.00) × 100 = 25.0%
        # GP % = 100 - 25 = 75.0%
        self.recipe.selling_price = Decimal('4.00')
        self.recipe.save()

        margin = calculate_recipe_margin(self.recipe)

        self.assertEqual(margin.status, 'ok')
        self.assertEqual(margin.food_cost_pct, Decimal('25.0'))
        self.assertEqual(margin.gp_pct, Decimal('75.0'))
        self.assertEqual(margin.cost_per_yield_unit, Decimal('1.00'))

    def test_selling_price_none_returns_no_selling_price_status(self):
        """selling_price=None returns status='no_selling_price', no % computed."""
        self.recipe.selling_price = None
        self.recipe.save()

        margin = calculate_recipe_margin(self.recipe)

        self.assertEqual(margin.status, 'no_selling_price')
        self.assertIsNone(margin.food_cost_pct)
        self.assertIsNone(margin.gp_pct)

    def test_incomplete_cost_returns_cost_incomplete_status(self):
        """Incomplete cost (missing price) returns status='cost_incomplete'."""
        # Add a second ingredient without a price
        unpriced_product = Product.objects.create(
            name='Basil',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=unpriced_product,
            quantity=Decimal('0.1000'),
            unit=self.kg_unit,
        )

        self.recipe.selling_price = Decimal('5.00')
        self.recipe.save()

        margin = calculate_recipe_margin(self.recipe)

        self.assertEqual(margin.status, 'cost_incomplete')
        self.assertIsNone(margin.food_cost_pct)
        self.assertIsNone(margin.gp_pct)
        self.assertIn('Basil', margin.missing_price_products)

    def test_selling_price_zero_returns_invalid_selling_price_status(self):
        """selling_price=0 returns status='invalid_selling_price' (no divide-by-zero)."""
        self.recipe.selling_price = Decimal('0')
        self.recipe.save()

        margin = calculate_recipe_margin(self.recipe)

        self.assertEqual(margin.status, 'invalid_selling_price')
        self.assertIsNone(margin.food_cost_pct)
        self.assertIsNone(margin.gp_pct)

    def test_selling_price_negative_returns_invalid_selling_price_status(self):
        """selling_price<0 returns status='invalid_selling_price'."""
        self.recipe.selling_price = Decimal('-1.00')
        self.recipe.save()

        margin = calculate_recipe_margin(self.recipe)

        self.assertEqual(margin.status, 'invalid_selling_price')
        self.assertIsNone(margin.food_cost_pct)
        self.assertIsNone(margin.gp_pct)

    def test_invalid_yield_returns_invalid_yield_status(self):
        """yields_quantity=0 returns status='invalid_yield'."""
        self.recipe.yields_quantity = Decimal('0')
        self.recipe.selling_price = Decimal('5.00')
        self.recipe.save()

        margin = calculate_recipe_margin(self.recipe)

        self.assertEqual(margin.status, 'invalid_yield')
        self.assertIsNone(margin.food_cost_pct)
        self.assertIsNone(margin.gp_pct)


class SuggestSellingPriceTests(TransactionTestCase):
    """Tests for suggest_selling_price service function."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        self.user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        # Set a price: £3.00 per kg
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('3.00'),
            currency='GBP',
            created_by=self.user,
            effective_to=None,
        )
        # Recipe: 10kg yields 10 portions
        # Cost = 10kg × £3/kg = £30, cost per portion = £3.00
        self.recipe = Recipe.objects.create(
            name='Tomato Soup',
            yields_quantity=Decimal('10.0000'),
            yields_unit=self.kg_unit,
            created_by=self.user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.product,
            quantity=Decimal('10.0000'),
            unit=self.kg_unit,
        )

    def test_suggest_selling_price_at_70_percent_gp(self):
        """Target 70% GP on known cost returns expected price."""
        # Cost per portion = £3.00
        # For 70% GP: price = cost / (1 - 0.70) = 3.00 / 0.30 = £10.00
        result = suggest_selling_price(self.recipe, Decimal('70'))

        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.suggested_price, Decimal('10.00'))
        self.assertEqual(result.cost_per_yield_unit, Decimal('3.00'))

    def test_suggest_selling_price_back_computes_to_target_gp(self):
        """Suggested price back-computes to approximately the target GP."""
        result = suggest_selling_price(self.recipe, Decimal('70'))

        # Verify: GP% = (price - cost) / price × 100
        # GP% = (10 - 3) / 10 × 100 = 70%
        suggested = result.suggested_price
        cost = result.cost_per_yield_unit
        gp_pct = ((suggested - cost) / suggested) * 100

        self.assertAlmostEqual(float(gp_pct), 70.0, places=1)

    def test_target_margin_100_or_more_raises(self):
        """Target margin >= 100 raises PriceValidationError."""
        with self.assertRaises(PriceValidationError) as ctx:
            suggest_selling_price(self.recipe, Decimal('100'))
        self.assertIn('less than 100', str(ctx.exception))

        with self.assertRaises(PriceValidationError):
            suggest_selling_price(self.recipe, Decimal('150'))

    def test_target_margin_negative_raises(self):
        """Target margin < 0 raises PriceValidationError."""
        with self.assertRaises(PriceValidationError) as ctx:
            suggest_selling_price(self.recipe, Decimal('-5'))
        self.assertIn('negative', str(ctx.exception))

    def test_incomplete_cost_cannot_suggest(self):
        """Incomplete cost returns status='cost_incomplete'."""
        # Add an unpriced ingredient
        unpriced = Product.objects.create(
            name='Basil',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('10.0000'),
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=unpriced,
            quantity=Decimal('0.1000'),
            unit=self.kg_unit,
        )

        result = suggest_selling_price(self.recipe, Decimal('70'))

        self.assertEqual(result.status, 'cost_incomplete')
        self.assertIsNone(result.suggested_price)
        self.assertIn('Basil', result.missing_price_products)


class RecipeCostingViewTests(TestCase):
    """Tests for the recipe_costing view RBAC."""

    def setUp(self):
        self.kg_unit = Unit.objects.create(
            name='Kilograms',
            unit_type='WEIGHT',
            conversion_to_base=Decimal('1000.0000'),
            base_unit_name='grams',
        )
        self.category = Category.objects.create(name='Produce', is_active=True)
        self.product = Product.objects.create(
            name='Tomatoes',
            category=self.category,
            unit=self.kg_unit,
            stock_quantity=Decimal('100.0000'),
        )
        self.staff_user = CustomUser.objects.create_user(
            username='staffuser',
            password='testpass123',
            role=CustomUser.Role.STAFF,
        )
        self.manager_user = CustomUser.objects.create_user(
            username='manageruser',
            password='testpass123',
            role=CustomUser.Role.MANAGER,
        )
        # Price for product
        PurchasePrice.objects.create(
            product=self.product,
            unit_price=Decimal('2.00'),
            currency='GBP',
            created_by=self.staff_user,
            effective_to=None,
        )
        self.recipe = Recipe.objects.create(
            name='Tomato Soup',
            yields_quantity=Decimal('10.0000'),
            yields_unit=self.kg_unit,
            created_by=self.staff_user,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            product=self.product,
            quantity=Decimal('5.0000'),
            unit=self.kg_unit,
        )
        self.url = reverse('costing:recipe_costing')
        self.set_price_url = reverse('costing:set_selling_price', args=[self.recipe.pk])

    def test_staff_get_recipe_costing_200(self):
        """Staff user can GET recipe costing page (200)."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recipe Costing')
        self.assertContains(response, 'Tomato Soup')

    def test_manager_get_recipe_costing_200(self):
        """Manager user can GET recipe costing page (200)."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_staff_post_set_selling_price_403(self):
        """Staff user POST to set selling price gets 403."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.post(self.set_price_url, {
            'selling_price': '5.00',
        })
        self.assertEqual(response.status_code, 403)

        # Price not set
        self.recipe.refresh_from_db()
        self.assertIsNone(self.recipe.selling_price)

    def test_manager_post_set_selling_price_succeeds(self):
        """Manager user POST to set selling price succeeds."""
        self.client.login(username='manageruser', password='testpass123')
        response = self.client.post(self.set_price_url, {
            'selling_price': '5.00',
        })

        # Redirects on success
        self.assertEqual(response.status_code, 302)

        # Price is set
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.selling_price, Decimal('5.00'))

    def test_anonymous_recipe_costing_redirects_to_login(self):
        """Anonymous user is redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_page_shows_food_cost_and_gp_when_complete(self):
        """Page shows food-cost % and GP % when cost and selling price are set."""
        self.recipe.selling_price = Decimal('4.00')
        self.recipe.save()

        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        # Cost per portion = £1.00, selling = £4.00
        # Food-cost = 25%, GP = 75%
        self.assertContains(response, '25.0%')
        self.assertContains(response, '75.0%')

    def test_page_shows_no_price_set_when_selling_price_missing(self):
        """Page shows 'No price set' when selling_price is None."""
        self.client.login(username='staffuser', password='testpass123')
        response = self.client.get(self.url)

        self.assertContains(response, 'No price set')
        self.assertContains(response, 'Not set')
