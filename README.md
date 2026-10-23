# Smart QR Visitor Management System

> **Tagline:** Secure Entry. Smarter Access.

A secure, enterprise-grade visitor management web application engineered for college campuses, universities, and institutions. Features dynamic multi-category registration forms, host/faculty review workflows, high-entropy cryptographic QR pass issuance, mandatory physical photograph verification at the gate, real-time campus occupancy tracking, emergency evacuation muster lists, and formula-injection-safe administrative reporting.

---

## Table of Contents

1. [Architecture & Technology Stack](#1-architecture--technology-stack)
2. [Project Structure](#2-project-structure)
3. [Windows Installation & Setup Guide](#3-windows-installation--setup-guide)
4. [Environment Configuration & Variables](#4-environment-configuration--variables)
5. [Default User Accounts & Initial Setup](#5-default-user-accounts--initial-setup)
6. [Core Workflows & Features](#6-core-workflows--features)
   - [A. Visitor Registration & Photo Protection](#a-visitor-registration--photo-protection)
   - [B. Faculty & Administrative Approvals](#b-faculty--administrative-approvals)
   - [C. Cryptographic QR Pass Delivery & Lifecycle](#c-cryptographic-qr-pass-delivery--lifecycle)
   - [D. Gate Security & Physical Photo Verification](#d-gate-security--physical-photo-verification)
   - [E. Live Campus Occupancy & Emergency Muster Roll](#e-live-campus-occupancy--emergency-muster-roll)
   - [F. Administrative Reports & Safe CSV Export](#f-administrative-reports--safe-csv-export)
7. [Database Migrations & Backup Procedures](#7-database-migrations--backup-procedures)
8. [Automated Testing & Quality Assurance](#8-automated-testing--quality-assurance)
9. [Production Deployment Checklist & Security Architecture](#9-production-deployment-checklist--security-architecture)
10. [Known Limitations & Troubleshooting](#10-known-limitations--troubleshooting)

---

## 1. Architecture & Technology Stack

- **Application Core:** Python 3.11+ with Flask 3 application factory pattern (`app/`).
- **ORM & Database:** SQLAlchemy 2 with SQLite (supporting PostgreSQL / SQLite in production).
- **Timezone Architecture:** Timezone-aware UTC timestamps stored in database via `UTCDateTime`; localized to `Asia/Kolkata` (IST) on UI display via Jinja context filter `format_dt`.
- **Database Migrations:** Flask-Migrate (Alembic) with partial unique indexes (`uq_form_versions_single_published`, `uq_visit_sessions_single_active`).
- **Authentication & Authorization:** Flask-Login with secure HTTP-only cookies, password hashing via Werkzeug (`scrypt`), and strict server-side role enforcement via `@role_required(UserRole...)`.
- **Cryptographic Security:** High-entropy QR tokens (`secrets.token_urlsafe(32)`), stored exclusively as SHA-256 hashes (`token_hash`), never stored or logged in plaintext. Constant-time verification (`hmac.compare_digest`).
- **Form Security:** Flask-WTF CSRF protection, Pillow-based re-encoding of uploaded visitor photographs (stripping EXIF metadata), and configurable sliding-window rate limiting on login, registration, approvals, and gate endpoints.
- **Reporting Security:** Formula injection (CSV injection) mitigation prepending `'` to trigger characters (`=`, `+`, `-`, `@`, `\t`, `\r`).
- **Frontend:** Semantic HTML5, Vanilla CSS3 (custom responsive SaaS design system with dark/light variables), ES6+ JavaScript, optical QR scanning (HTML5 video stream with camera switcher and manual fallback).
- **Testing Suite:** 125 automated unit, integration, and security tests run via `pytest`.

---

## 2. Project Structure

```text
SPRINIT/
├── app/
│   ├── __init__.py               # Flask application factory (create_app)
│   ├── config.py                 # Configuration classes (Dev, Testing, Prod)
│   ├── extensions.py             # db, migrate, login_manager, csrf, foreign_keys pragma
│   ├── models/
│   │   ├── __init__.py           # Re-exports models
│   │   ├── user.py               # User model & roles (ADMIN, FACULTY, SECURITY)
│   │   ├── visitor.py            # Visitor master records
│   │   ├── visit.py              # VisitRequest, ApprovalDecision, QRCredential, VisitSession, VisitEvent
│   │   ├── registration_form.py  # RegistrationForm, FormVersion, schema validation
│   │   ├── visit_type.py         # Standardized categories (GENERAL, ACADEMIC, OFFICIAL, CONTRACTOR, VIP)
│   │   ├── audit_log.py          # Immutable audit trail with sanitized metadata
│   │   └── types.py              # UTCDateTime custom SQLAlchemy TypeDecorator
│   ├── routes/
│   │   ├── main.py               # Root index redirection
│   │   ├── auth.py               # Login, logout, session management
│   │   ├── visitors.py           # Public registration, confirmation, pass delivery, protected photo serving
│   │   ├── faculty.py            # Host workspace, approval review, dynamic form customization
│   │   ├── admin.py              # Command center, staff management, reports, audit trail
│   │   └── security.py           # Gate scanner, photo check, check-in, check-out, occupancy, emergency roll
│   ├── services/
│   │   ├── auth_service.py       # Authentication & role_required decorator
│   │   ├── user_service.py       # Staff CRUD & admin protection
│   │   ├── registration_service.py # Visitor registration & duplicate detection
│   │   ├── form_service.py       # Dynamic schema management & version immutability
│   │   ├── approval_service.py   # Multi-role review workflow & atomic QR issuance
│   │   ├── qr_service.py         # Cryptographic token generation, hashing, rendering, revocation & reissue
│   │   ├── gate_service.py       # Gate scanner verification, check-in/out, live occupancy & KPIs
│   │   ├── report_service.py     # Analytics aggregation & formula-injection-safe CSV export
│   │   ├── upload_service.py     # Image verification & sanitize upload
│   │   ├── duplicate_service.py  # 24h sliding duplicate detection
│   │   ├── audit_service.py      # Immutable security audit logging
│   │   └── rate_limiter.py       # IP-based sliding window rate limiter
│   └── templates/                # Jinja2 templates (SaaS responsive design system)
├── migrations/                   # Alembic database migration scripts
├── tests/                        # 125 comprehensive pytest suites
├── run.py                        # Entry point & CLI management commands
├── pytest.ini                    # Test runner configuration
├── requirements.txt              # Production and testing dependencies
├── .env.example                  # Environment configuration template
└── .env                          # Local environment variables
```

---

## 3. Windows Installation & Setup Guide

Execute the following commands in **PowerShell** or **Command Prompt** from the repository root:

### Step 1: Open Directory
```powershell
cd D:\SPRINIT
```

### Step 2: Create & Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 3: Install Required Dependencies
```powershell
pip install -r requirements.txt
```

### Step 4: Environment Configuration
Copy the template configuration if `.env` does not already exist:
```powershell
copy .env.example .env
```
*(Ensure `SECRET_KEY` is configured with a secure random key before production deployment).*

### Step 5: Run Database Migrations
Initialize or upgrade the SQLite database schema:
```powershell
flask db upgrade
```

### Step 6: Seed Default Accounts
Provision development staff accounts for Admin, Faculty, and Security roles:
```powershell
flask seed-users
```

### Step 7: Launch the Application
```powershell
python run.py
```
*(Or alternatively: `flask run --port 5000`)*

Access the application in your web browser at: **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 4. Environment Configuration & Variables

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `SECRET_KEY` | *Insecure default* | **Mandatory:** Cryptographic secret for signing session cookies and CSRF tokens. |
| `DATABASE_URL` | `sqlite:///visitor_management.db` | Database connection URI (SQLite or PostgreSQL). |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` in production to mandate HTTPS cookies. |
| `SESSION_COOKIE_HTTPONLY` | `true` | Prevents client-side script access to session cookies. |
| `SESSION_COOKIE_SAMESITE` | `Lax` | Protects against Cross-Site Request Forgery (CSRF). |
| `APP_TIMEZONE` | `Asia/Kolkata` | Local timezone for UI display; database remains strictly UTC. |
| `QR_VALIDITY_MINUTES` | `120` | Credential validity buffer (in minutes) past visit arrival time. |
| `RATE_LIMIT_ENABLED` | `true` | Activates IP-based sliding-window rate limiting. |
| `RATE_LIMIT_LOGIN` | `10/minute` | Rate limit on `/login`. |
| `RATE_LIMIT_REGISTER` | `5/minute` | Rate limit on public visitor registration submissions. |
| `RATE_LIMIT_APPROVAL` | `30/minute` | Rate limit on staff approval/rejection and QR reissue actions. |
| `RATE_LIMIT_GATE` | `60/minute` | Rate limit on gate scanner verification and check-in/out endpoints. |
| `BEHIND_PROXY` | `false` | Set to `true` when deployed behind Nginx / AWS ALB. |
| `TRUSTED_PROXIES` | `127.0.0.1` | Explicit whitelist of proxy IP addresses allowed to set `X-Forwarded-For`. |

---

## 5. Default User Accounts & Initial Setup

The database seed provides initial staff accounts:

| Role | Username | Email | Password | Landing Workspace |
| :--- | :--- | :--- | :--- | :--- |
| **Administrator** | `admin` | `admin@campus.edu` | `Admin@123` | `/admin/dashboard` |
| **Faculty / Host** | `faculty` | `faculty@campus.edu` | `Faculty@123` | `/faculty/dashboard` |
| **Security Staff** | `security` | `security@campus.edu` | `Security@123` | `/security/dashboard` |

> *Tip:* The sign-in page (`/login`) includes quick demo fill buttons for rapid development testing.

---

## 6. Core Workflows & Features

### A. Visitor Registration & Photo Protection
- Visitors register via the public portal (`/register`), choosing their visit category (`OFFICIAL`, `ACADEMIC`, `CONTRACTOR`, `GENERAL`, `VIP`) and selecting their host faculty member.
- Uploaded visitor photographs are verified with Pillow, stripped of EXIF metadata, re-encoded as JPEG, and saved with a randomized UUID filename.
- Protected photos (`/visitors/photo/<filename>`) are never served publicly; they strictly require authentication and authorization (accessible only by Administrators, Security staff, or the specific Faculty host).

### B. Faculty & Administrative Approvals
- Host faculty review incoming requests for their department (`/faculty/requests`). Administrators can review requests institution-wide (`/admin/requests`).
- Approving a request atomically transitions the request status to `APPROVED` and generates a secure QR credential within the same database transaction.
- If a request is rejected, a reason must be provided, no credential is generated, and audit logs record the decision.

### C. Cryptographic QR Pass Delivery & Lifecycle
- **Opaque Token Generation:** Uses `secrets.token_urlsafe(32)` (256 bits of entropy) with payload format `VMS:<token>`.
- **Zero Plaintext Storage:** Plaintext tokens are never stored in the database or written to log files; only the SHA-256 hash (`token_hash`) is persisted.
- **Visitor Pass Page (`/visitors/pass/<public_reference>`):** Displays visitor name, category, host, scheduled arrival window, and QR image. Sensitive PII (email, phone number, dynamic form fields) and raw tokens are strictly stripped from the public pass.
- **Cache Control:** Pass pages and dynamic QR code images (`/visitors/pass/<ref>/qr.png`) send `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` to prevent shared-cache leakage.
- **Reissue & Revocation:** Authorized staff can revoke an active credential or reissue a replacement. Reissuing atomically revokes the prior credential and purges old QR images from disk.

### D. Gate Security & Physical Photo Verification
- **Dual-Mode Scanner (`/security/scan`):** Supports live browser camera feed (with permission handling and camera switching) and a manual reference lookup fallback (`REQ-...` or `VMS:...`).
- **Server-Side Credential Verification:** The server verifies cryptographic hash, visit approval status, visit time window, and revocation state.
- **Mandatory Physical Identity Verification Policy:** Scanning alone does NOT check in a visitor. The scanner displays the registered photograph on screen for security personnel to visually confirm the physical visitor's identity before clicking **Confirm Physical Identity & Check-In**.
- **Atomic Check-In:** Consumes the single-use QR credential (`CONSUMED`), creates an active `VisitSession`, and emits a `CHECK_IN` event. Duplicate admissions are prevented by database-level partial unique indexes.
- **Check-Out:** Departure check-out completes the active session (`COMPLETED`) and emits a `CHECK_OUT` audit event.

### E. Live Campus Occupancy & Emergency Muster Roll
- **Live Occupancy (`/security/occupancy`):** Real-time headcount of visitors currently inside the campus perimeter, calculated from active sessions (`status == ACTIVE`). Completed sessions are never counted.
- **Emergency Muster Roll (`/security/emergency-list`):** Evacuation manifest listing all unaccounted external visitors on campus, with check-in timestamp, host details, and emergency contact numbers. Optimized for print output (`@media print`) and compliant with audit tracking (`EMERGENCY_LIST_VIEWED`).

### F. Administrative Reports & Safe CSV Export
- **Operational Metrics (`/admin/reports`):** Authoritative counts for total requests, pending, approved, rejected, total admissions, current occupancy, completed visits, and overstay visits (>12h on campus).
- **Interactive Multi-Criteria Filtering:** Filter by date range, request status, visit category, host staff, and gate session status.
- **Formula Injection Mitigation:** When exporting visit logs to CSV (`/admin/reports/export.csv`), all cell values are sanitized (`sanitize_csv_cell`) by prepending a single quote (`'`) to any string starting with `=`, `+`, `-`, `@`, `\t`, or `\r`.

---

## 7. Database Migrations & Backup Procedures

### Applying Migrations
Alembic migrations track all database schema changes:
```powershell
flask db upgrade
```

### Creating New Migrations
When adding models or columns:
```powershell
flask db migrate -m "Description of changes"
flask db upgrade
```

### Production Backup & Restore
1. **SQLite Database Backup:**
   ```powershell
   # Create a timestamped copy while service is idle
   copy visitor_management.db "backups\visitor_management_%date:~-4,4%%date:~-10,2%%date:~-7,2%.db"
   ```
2. **Protected Uploads Backup:**
   ```powershell
   # Back up photo uploads and generated QR codes
   xcopy /E /I instance\uploads backups\uploads_backup
   ```
3. **Database Rollback:**
   ```powershell
   flask db downgrade
   ```

---

## 8. Automated Testing & Quality Assurance

Run the comprehensive pytest suite:
```powershell
.venv\Scripts\python.exe -m pytest -v
```

### Test Coverage Summary (125 Passing Tests)
- `test_auth.py` (13 tests): Login, logout, CSRF token validation, inactive accounts, password hashing.
- `test_authorization.py` (5 tests): Strict server-side role enforcement (Admin, Faculty, Security) and 403 handling.
- `test_database.py` (12 tests): Models, partial unique indexes, foreign keys, and UTCDateTime roundtrip.
- `test_registration.py` (13 tests): Dynamic form rendering, validation, host selection, date window checks.
- `test_photo_upload.py` (6 tests): Pillow image validation, size limits, format conversion, disguised files.
- `test_duplicate_detection.py` (4 tests): Sliding 24-hour duplicate phone/email detection.
- `test_form_builder.py` (9 tests): Dynamic schema updates, version archiving, and version immutability.
- `test_faculty_customization.py` (7 tests): Faculty field permissions and forbidden property bypass protection.
- `test_staff_management.py` (7 tests): Staff CRUD, role demotion protection, and last active admin protection.
- `test_approvals.py` (9 tests): Faculty and Admin review workflows, IDOR protection, and decision audit logs.
- `test_qr_credentials.py` (14 tests): Cryptographic token generation, hashing, expiry, revocation, reissue, and barcode decoding.
- `test_gate_operations.py` (13 tests): Scanner verification, check-in, check-out, occupancy, and emergency lists.
- `test_reports_analytics.py` (7 tests): Reporting metrics, date filtering, formula injection mitigation, and audit trails.
- `test_rate_limiter.py` (4 tests): In-memory sliding window rate limiting.

---

## 9. Production Deployment Checklist & Security Architecture

1. **Mandate HTTPS:**
   - In production, set `SESSION_COOKIE_SECURE=true` in `.env`.
   - Browser camera access for optical scanning requires a secure context (`https://` or `localhost`).
2. **Generate Cryptographic Secret Key:**
   - Replace development `SECRET_KEY` with a 64-character random key generated via `python -c "import secrets; print(secrets.token_hex(32))"`.
3. **Reverse Proxy Configuration:**
   - Deploy behind Nginx, Caddy, or an AWS Application Load Balancer.
   - Configure proxy IP headers: Set `BEHIND_PROXY=true` and specify `TRUSTED_PROXIES=127.0.0.1` so `request.remote_addr` accurately reflects visitor IPs without trusting arbitrary forged `X-Forwarded-For` headers.
4. **Persistent Storage:**
   - Mount persistent volumes for the SQLite database (`visitor_management.db`) and uploaded visitor photos (`instance/uploads/`).
5. **Multi-Worker Rate Limiting:**
   - The default rate limiter uses an in-memory sliding window suitable for single-process deployments. For multi-worker deployments (e.g. Gunicorn with multiple workers), configure a shared backend (e.g. Redis).
6. **WSGI Production Server:**
   - Do not use `flask run` in production. Use a production WSGI server such as Waitress (on Windows) or Gunicorn (on Linux):
     ```powershell
     pip install waitress
     waitress-serve --port=5000 run:app
     ```

---

## 10. Known Limitations & Troubleshooting

- **Camera Permissions in Chrome/Edge:** Browsers require HTTPS to grant camera access (`getUserMedia`) on non-localhost domains. If testing across local LAN devices, use HTTPS or access via `localhost`.
- **Physical Access Control Hardware:** The system manages software verification and logging; physical turnstiles, RFID barriers, or automated gate relays are external hardware integrations not covered by this web application.
- **Single-Process Rate Limiter:** The built-in rate limiter runs in-process memory. If scaled across multiple server processes without sticky sessions or a shared Redis cache, rate limit counters are tracked per-worker.

---

**Campus Security & Visitor Management System** &middot; Developed for institutional campus perimeter security.
