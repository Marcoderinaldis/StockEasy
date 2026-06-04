# StockEasy

A web-based stock and recipe costing management system for single-venue hospitality businesses.

## Features

- Ingredient and unit of measure management
- Recipe creation with ingredient composition
- Automatic recipe cost calculation
- Cost per portion and suggested selling price
- Role-based access: Admin, Manager, Staff
- Containerised development environment

## Technology stack

| Component | Technology |
|---|---|
| Backend | Django 5.2.14 |
| Database | PostgreSQL 17 |
| Cache | Redis 7 |
| Frontend | Bootstrap 5.3 |
| Containerisation | Docker |

## Getting started

### Prerequisites

- Docker Desktop installed and running
- Git

### Setup

1. Clone the repository:
   ```
   git clone https://github.com/YOUR_USERNAME/stockeasy.git
   cd stockeasy
   ```

2. Copy the environment file and configure it:
   ```
   cp .env.example .env
   ```
   Edit `.env` and set a real `SECRET_KEY` and your preferred database credentials.

3. Build and start the containers:
   ```
   docker compose up --build -d
   ```

4. Run migrations:
   ```
   docker compose exec web python manage.py makemigrations accounts
   docker compose exec web python manage.py makemigrations inventory
   docker compose exec web python manage.py makemigrations recipes
   docker compose exec web python manage.py migrate
   ```

5. Create a superuser:
   ```
   docker compose exec web python manage.py createsuperuser
   ```

6. Access the application at `http://localhost:8000`

### Admin interface

Available at `http://localhost:8000/admin`

### Health check

Available at `http://localhost:8000/health/`

## Project structure

```
stockeasy/
├── config/         Django project settings and routing
├── accounts/       Authentication and user roles
├── core/           Dashboard and shared views
├── inventory/      Ingredients and units of measure
├── recipes/        Recipe definitions and composition
├── costing/        Cost calculation services
├── templates/      Global HTML templates
├── static/         CSS and static assets
├── docs/           Project documentation and evidence
└── tests/          Automated test suite
```

## Documentation

All development decisions, testing evidence, and report mapping are maintained under `docs/`.
See `docs/report-draft/REPORT_EVIDENCE_MAP.md` for report structure guidance.
