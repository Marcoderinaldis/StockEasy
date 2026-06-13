"""
Seed data management command for StockEasy.

Creates initial data for development and testing:
- 5 Units (kg, g, litres, ml, items)
- 3 Categories (Produce, Dairy, Proteins)
- 3 Products (one per category)
- Initial PurchasePrice for each product
- Default staff user with ADMIN role

StockMovement and WasteRecord are NOT seeded (start empty for test phase).
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from inventory.models import Unit, Category, Product, PurchasePrice

CustomUser = get_user_model()


class Command(BaseCommand):
    help = 'Seed the database with initial data for development'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database...')

        # Create or get admin user
        admin_user, created = CustomUser.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@stockeasy.local',
                'role': 'ADMIN',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write(self.style.SUCCESS('Created admin user'))
        else:
            self.stdout.write('Admin user already exists')

        # Create Manager user for role testing
        manager_user, created = CustomUser.objects.get_or_create(
            username='manager',
            defaults={
                'email': 'manager@stockeasy.local',
                'role': 'MANAGER',
                'is_staff': False,
                'is_superuser': False,
            }
        )
        if created:
            manager_user.set_password('manager123')
            manager_user.save()
            self.stdout.write(self.style.SUCCESS('Created manager user'))
        else:
            self.stdout.write('Manager user already exists')

        # Create Staff user for role testing
        staff_user, created = CustomUser.objects.get_or_create(
            username='staff',
            defaults={
                'email': 'staff@stockeasy.local',
                'role': 'STAFF',
                'is_staff': False,
                'is_superuser': False,
            }
        )
        if created:
            staff_user.set_password('staff123')
            staff_user.save()
            self.stdout.write(self.style.SUCCESS('Created staff user'))
        else:
            self.stdout.write('Staff user already exists')

        # Create Units
        units_data = [
            {
                'name': 'Kilograms',
                'unit_type': 'WEIGHT',
                'conversion_to_base': Decimal('1000.0000'),
                'base_unit_name': 'grams',
            },
            {
                'name': 'Grams',
                'unit_type': 'WEIGHT',
                'conversion_to_base': Decimal('1.0000'),
                'base_unit_name': 'grams',
            },
            {
                'name': 'Litres',
                'unit_type': 'VOLUME',
                'conversion_to_base': Decimal('1000.0000'),
                'base_unit_name': 'millilitres',
            },
            {
                'name': 'Millilitres',
                'unit_type': 'VOLUME',
                'conversion_to_base': Decimal('1.0000'),
                'base_unit_name': 'millilitres',
            },
            {
                'name': 'Items',
                'unit_type': 'COUNT',
                'conversion_to_base': Decimal('1.0000'),
                'base_unit_name': 'units',
            },
        ]

        units = {}
        for unit_data in units_data:
            unit, created = Unit.objects.get_or_create(
                name=unit_data['name'],
                defaults=unit_data
            )
            units[unit_data['name']] = unit
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created unit: {unit.name}'))
            else:
                self.stdout.write(f'Unit already exists: {unit.name}')

        # Create Categories
        categories_data = [
            {
                'name': 'Produce',
                'description': 'Fresh fruits and vegetables',
                'is_active': True,
            },
            {
                'name': 'Dairy',
                'description': 'Milk, cheese, butter, and other dairy products',
                'is_active': True,
            },
            {
                'name': 'Proteins',
                'description': 'Meat, poultry, fish, and other protein sources',
                'is_active': True,
            },
        ]

        categories = {}
        for cat_data in categories_data:
            category, created = Category.objects.get_or_create(
                name=cat_data['name'],
                defaults=cat_data
            )
            categories[cat_data['name']] = category
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created category: {category.name}'))
            else:
                self.stdout.write(f'Category already exists: {category.name}')

        # Create Products
        products_data = [
            {
                'name': 'Tomatoes',
                'category': categories['Produce'],
                'unit': units['Kilograms'],
                'stock_quantity': Decimal('0.0000'),
                'reorder_level': Decimal('5.0000'),
                'is_active': True,
            },
            {
                'name': 'Whole Milk',
                'category': categories['Dairy'],
                'unit': units['Litres'],
                'stock_quantity': Decimal('0.0000'),
                'reorder_level': Decimal('10.0000'),
                'is_active': True,
            },
            {
                'name': 'Chicken Breast',
                'category': categories['Proteins'],
                'unit': units['Kilograms'],
                'stock_quantity': Decimal('0.0000'),
                'reorder_level': Decimal('3.0000'),
                'is_active': True,
            },
        ]

        products = []
        for prod_data in products_data:
            product, created = Product.objects.get_or_create(
                name=prod_data['name'],
                category=prod_data['category'],
                defaults=prod_data
            )
            products.append(product)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created product: {product.name}'))
            else:
                self.stdout.write(f'Product already exists: {product.name}')

        # Create initial PurchasePrices
        prices_data = [
            {'product_name': 'Tomatoes', 'unit_price': Decimal('2.50')},
            {'product_name': 'Whole Milk', 'unit_price': Decimal('1.20')},
            {'product_name': 'Chicken Breast', 'unit_price': Decimal('8.99')},
        ]

        for price_data in prices_data:
            product = Product.objects.get(name=price_data['product_name'])
            # Only create if no active price exists
            active_price = PurchasePrice.objects.filter(
                product=product,
                effective_to__isnull=True
            ).first()

            if not active_price:
                price = PurchasePrice.objects.create(
                    product=product,
                    unit_price=price_data['unit_price'],
                    currency='GBP',
                    created_by=admin_user,
                )
                self.stdout.write(self.style.SUCCESS(
                    f'Created price for {product.name}: £{price.unit_price}'
                ))
            else:
                self.stdout.write(
                    f'Active price already exists for {product.name}: £{active_price.unit_price}'
                )

        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Seed data complete:'))
        self.stdout.write(f'  - Units: {Unit.objects.count()}')
        self.stdout.write(f'  - Categories: {Category.objects.count()}')
        self.stdout.write(f'  - Products: {Product.objects.count()}')
        self.stdout.write(f'  - Purchase Prices: {PurchasePrice.objects.count()}')
        self.stdout.write(f'  - Users: {CustomUser.objects.count()}')
        self.stdout.write('')
        self.stdout.write('StockMovement and WasteRecord tables are empty (ready for testing)')
