# Decision Log

This file records all significant architectural and design decisions made during the development of StockEasy.
Each entry follows a fixed structure to support traceability and future report writing.

---

## Template

**Decision title:**
**Date:**
**Context:**
**Decision:**
**Reason:**
**Alternatives considered:**
**Consequences:**

---

## DEC-001 — Django selected as application framework

**Date:** 2026-06-03
**Context:** StockEasy requires a web-based application with role-based authentication, database integration, and a template-rendered frontend. The project must be completed within a single academic semester with a solo developer.
**Decision:** Use Django 5.2.14 as the primary web framework.
**Reason:** Django provides built-in authentication, ORM, admin interface, and migration management out of the box. These reduce boilerplate and allow the semester to focus on domain logic rather than infrastructure.
**Alternatives considered:** Flask (too minimal, would require assembling many separate libraries); FastAPI (API-first, not suited for template-based MVP).
**Consequences:** Project is tightly coupled to Django conventions. Future API layer would require Django REST Framework addition.

---

## DEC-002 — PostgreSQL selected as database

**Date:** 2026-06-03
**Context:** The application requires a relational database capable of enforcing referential integrity across ingredients, recipes, and costing data.
**Decision:** Use PostgreSQL 17 running as a Docker service.
**Reason:** PostgreSQL is production-grade, supports Django natively, and is well-supported with psycopg 3. SQLite was rejected because it does not support concurrent writes and is not suitable for a containerised multi-service setup.
**Alternatives considered:** SQLite (rejected — not production-suitable); MySQL (rejected — psycopg 3 is the preferred modern adapter and targets PostgreSQL).
**Consequences:** Requires Docker to be running for local development. Database volume is persisted via Docker named volume.

---

## DEC-003 — CustomUser created before first migration

**Date:** 2026-06-03
**Context:** Django requires AUTH_USER_MODEL to be set before any migration is run. Changing it after the first migration requires a full database reset.
**Decision:** accounts.CustomUser extending AbstractUser is the first app migrated. AUTH_USER_MODEL = 'accounts.CustomUser' is set in base settings before any migrate command is executed.
**Reason:** Prevents the need to reset the database during development and ensures all foreign keys to the user model resolve correctly from the start.
**Alternatives considered:** Using the default Django User model (rejected — role field cannot be added cleanly without a separate Profile model).
**Consequences:** All future foreign keys referencing the user must use settings.AUTH_USER_MODEL, not a direct import of CustomUser.

---

## DEC-004 — Redis included from the first skeleton

**Date:** 2026-06-03
**Context:** The application may benefit from caching as recipe and costing queries grow. Introducing Redis after the fact would require reconfiguring settings and Docker.
**Decision:** Redis 7 is included as a Docker service from the first skeleton. Django cache backend is configured to use django-redis pointing at the Redis container.
**Reason:** Infrastructure is cheaper to add early than to retrofit. Redis is configured only as a cache backend in MVP; no Celery or background workers are introduced.
**Alternatives considered:** Memcached (less flexible, no persistence option); local memory cache (not suitable for multi-container setup).
**Consequences:** Docker Compose starts three services: web, db, redis. Redis is not actively used in MVP beyond cache configuration.

---

## DEC-005 — config/ used as Django project package name

**Date:** 2026-06-03
**Context:** Using stockeasy/ as both the repository root and the Django project package creates import ambiguity and confuses tooling.
**Decision:** The Django project package is named config/. The repository root remains stockeasy/.
**Reason:** Separates repository identity from Django project identity. config/ is a widely adopted convention for this pattern.
**Alternatives considered:** Keeping stockeasy/ as the package name (rejected — naming collision with the repository root directory).
**Consequences:** DJANGO_SETTINGS_MODULE must reference config.settings.development. All imports must use config.urls, config.wsgi, config.asgi.

---

## DEC-006 — reports app excluded from first skeleton

**Date:** 2026-06-03
**Context:** Reports require real data and stable costing logic to be meaningful. Adding a reports app in the skeleton would produce empty views with no domain value.
**Decision:** No reports app in the first skeleton. Reports will be added in a later sprint after inventory, recipes, and costing are functional.
**Reason:** Avoids premature abstraction. The first skeleton must demonstrate working domain logic, not placeholder structure.
**Alternatives considered:** Including reports as an empty app (rejected — adds no value and misleads the examiner about MVP scope).
**Consequences:** CSV export and aggregated reporting are deferred to a later milestone.

---

## DEC-007 — Sprint 2 models complete with append-only StockMovement

**Date:** 2026-06-12
**Context:** StockEasy requires robust stock tracking with full audit trail. Stock movements must be immutable to ensure data integrity and GDPR compliance.
**Decision:** Sprint 2 models complete. All 9 models created: Unit, Category, Product, PurchasePrice, StockMovement, WasteRecord, Recipe, RecipeIngredient. AuditLog via django-auditlog for automatic change tracking.
**Reason:**
- StockMovement is append-only — no updates or deletes ever allowed
- Double-void prevention enforced in service layer (5-minute window check)
- Unit conversion validation points defined at all quantity entry points
- Service layer stubs ready for Sprint 3 implementation
**Alternatives considered:** Mutable stock records with soft-delete (rejected — violates audit requirements and GDPR principles).
**Consequences:**
- All stock mutations must go through service layer functions
- Direct Product.stock_quantity updates are never allowed
- VOID movements reverse effects by creating new records, not modifying existing ones

---

## DEC-008 — Standardised waste categories across models

**Date:** 2026-06-12
**Context:** WasteRecord and StockMovement both need reason categorisation. Using different categories would complicate reporting and analysis.
**Decision:** Six standardised waste/reason categories used across both models:
1. Product expired
2. Delivery damaged
3. Counting error
4. Spillage/accidental waste
5. Void—entered in error
6. Other
**Reason:** Consistent categories enable unified waste reporting and trend analysis. Categories align with hospitality industry standards.
**Alternatives considered:** Separate category lists for waste vs movements (rejected — complicates reporting).
**Consequences:** Category changes require updating both StockMovement.REASON_CATEGORY_CHOICES and WasteRecord.WASTE_CATEGORY_CHOICES.
