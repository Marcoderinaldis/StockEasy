# Testing Log

This file records all testing activity including manual tests and automated tests.
Each entry documents what was tested, how, and the result.

---

## Template

**Feature tested:**
**Test type:** manual / automated
**Steps performed:**
**Expected result:**
**Actual result:**
**Pass / Fail:**
**Screenshot required:** yes / no
**Bug reference:** (if applicable)

---

## TEST-001 — Docker services start correctly

**Feature tested:** Docker Compose startup — web, db, redis
**Test type:** Manual
**Steps performed:**
1. Run `docker compose up --build -d`
2. Run `docker compose ps`
3. Verify all three containers show status Up
**Expected result:** web, db, and redis containers all running with no exit codes
**Actual result:** [To be completed]
**Pass / Fail:** [To be completed]
**Screenshot required:** Yes
**Bug reference:** —

---

## TEST-002 — Database migration completes without errors

**Feature tested:** Django migrations — accounts, inventory, recipes
**Test type:** Manual
**Steps performed:**
1. Run `docker compose exec web python manage.py migrate`
2. Check terminal output for errors
**Expected result:** All migrations applied with OK status
**Actual result:** [To be completed]
**Pass / Fail:** [To be completed]
**Screenshot required:** Yes
**Bug reference:** —

---

## TEST-003 — Django admin accessible and CustomUser visible

**Feature tested:** Django admin — CustomUser with role field
**Test type:** Manual
**Steps performed:**
1. Navigate to http://localhost:8000/admin
2. Log in with superuser credentials
3. Confirm CustomUser model is listed with role column
**Expected result:** Admin accessible, CustomUser visible with role field
**Actual result:** [To be completed]
**Pass / Fail:** [To be completed]
**Screenshot required:** Yes
**Bug reference:** —

---

## TEST-004 — Login view renders and authenticates

**Feature tested:** accounts login view
**Test type:** Manual
**Steps performed:**
1. Navigate to http://localhost:8000/accounts/login/
2. Enter valid credentials
3. Confirm redirect to home dashboard
**Expected result:** Successful login redirects to /
**Actual result:** [To be completed]
**Pass / Fail:** [To be completed]
**Screenshot required:** Yes
**Bug reference:** —

---

## TEST-005 — Health check endpoint returns 200

**Feature tested:** core health_check view
**Test type:** Manual
**Steps performed:**
1. Navigate to http://localhost:8000/health/
2. Confirm JSON response with status ok
**Expected result:** {"status": "ok"}
**Actual result:** [To be completed]
**Pass / Fail:** [To be completed]
**Screenshot required:** No
**Bug reference:** —
