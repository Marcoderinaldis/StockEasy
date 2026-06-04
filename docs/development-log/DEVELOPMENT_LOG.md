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
