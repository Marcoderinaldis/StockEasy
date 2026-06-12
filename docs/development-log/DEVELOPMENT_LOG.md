# Development Log

This file records every development session chronologically.
Each entry documents what was built, what commands were run, what problems were encountered, and what the next step is.

---

## Template

**Date:**
**Objective:**
**Files created / changed:**
**Commands run:**
**Outcome:**
**Problems encountered:**
**Fix applied:**
**Next step:**

---

## DEV-001 — Initial skeleton

**Date:** 2026-06-03
**Objective:** Create the full project skeleton including Django apps, Docker services, settings structure, and documentation files.
**Files created / changed:**
- config/__init__.py, settings/base.py, settings/development.py, settings/production.py
- config/urls.py, config/wsgi.py, config/asgi.py
- accounts/models.py, admin.py, views.py, urls.py, apps.py, templates/accounts/login.html
- core/views.py, urls.py, apps.py, templates/core/home.html
- inventory/models.py, admin.py, views.py, urls.py, apps.py, templates/inventory/ingredient_list.html
- recipes/models.py, admin.py, views.py, urls.py, apps.py, templates/recipes/recipe_list.html
- costing/services.py, views.py, urls.py, apps.py, templates/costing/index.html
- templates/base.html
- static/css/main.css
- manage.py, requirements.txt, Dockerfile, docker-compose.yml, .env.example, .gitignore, .dockerignore
- All docs/ files initialised

**Commands run:**
```
docker compose up --build -d
docker compose exec web python manage.py makemigrations accounts
docker compose exec web python manage.py makemigrations inventory
docker compose exec web python manage.py makemigrations recipes
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

**Outcome:** [To be completed after execution]
**Problems encountered:** [To be completed after execution]
**Fix applied:** [To be completed after execution]
**Next step:** Verify admin interface, confirm all three Docker services running, take first screenshots.

---

## DEV-002 — Sprint 2: Core Models and Migrations

**Date:** 2026-06-12
**Objective:** Create all 9 core models with append-only StockMovement, double-void prevention, unit conversion validation, and service layer stubs.

**Files created / changed:**
- inventory/models.py — Unit, Category, Product, PurchasePrice, StockMovement (9 models total)
- waste/models.py — WasteRecord with standardised waste categories
- recipes/models.py — Recipe, RecipeIngredient with unit validation support
- inventory/services.py — Stubs: record_stock_in(), record_stock_out(), record_waste(), void_movement(), record_adjustment_in(), record_adjustment_out()
- waste/services.py — Stub: record_waste_via_movement()
- recipes/services.py — Stub: calculate_recipe_cost(), calculate_cost_per_yield()
- costing/services.py — Stubs: calculate_product_cost(), get_price_history(), suggest_selling_price()
- inventory/management/commands/seed_data.py — Seed script for initial data

**Model counts:**
- 9 models across 4 apps (inventory, waste, recipes, accounts)
- 6 hardcoded waste/reason categories (matching across WasteRecord and StockMovement)
- 3 roles via CustomUser (Admin, Manager, Staff)

**Seed data produces:**
- 5 Units: Kilograms, Grams, Litres, Millilitres, Items
- 3 Categories: Produce, Dairy, Proteins
- 3 Products: Tomatoes, Whole Milk, Chicken Breast
- 3 PurchasePrices: Initial pricing for each product
- 1 Admin user (username: admin, password: admin123)

**StockMovement and WasteRecord start empty** — ready for test phase.

**Commands to run:**
```bash
docker compose up -d
docker compose exec web python manage.py makemigrations inventory waste recipes
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_data
docker compose exec web python manage.py check
```

**Outcome:** Models created and ready for migration. Service layer stubs documented.
**Problems encountered:** Docker not running on development machine during initial creation.
**Fix applied:** Model files validated via code review. Migrations to be run when Docker is available.
**Next step:** Run migrations, execute seed_data command, verify via Django admin, proceed to Sprint 3 service implementation.
