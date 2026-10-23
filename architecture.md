
# System Architecture
## Smart QR Visitor Management System

## 1. Architecture Overview
Use a modular, server-rendered Flask application with SQLite persistence.

Architecture layers:
1. Presentation layer: HTML, CSS, JavaScript, Jinja2 templates.
2. Routing layer: Flask blueprints and request handling.
3. Service layer: business rules and workflow logic.
4. Data layer: SQLAlchemy models and database transactions.
5. Infrastructure layer: configuration, logging, QR generation, and optional notifications.

The browser must not directly access the SQLite database. All data operations must pass through the backend.

## 2. Recommended Folder Structure

smart-visitor-management/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── visitor.py
│   │   ├── visit.py
│   │   ├── registration_form.py
│   │   ├── qr_credential.py
│   │   └── audit_log.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── admin.py
│   │   ├── faculty.py
│   │   ├── security.py
│   │   ├── visitors.py
│   │   ├── forms.py
│   │   └── reports.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── registration_service.py
│   │   ├── approval_service.py
│   │   ├── form_service.py
│   │   ├── qr_service.py
│   │   ├── visit_service.py
│   │   ├── report_service.py
│   │   └── audit_service.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── auth/
│   │   ├── admin/
│   │   ├── faculty/
│   │   ├── security/
│   │   ├── visitors/
│   │   ├── forms/
│   │   ├── reports/
│   │   └── errors/
│   └── static/
│       ├── css/
│       ├── js/
│       └── images/
├── migrations/
├── tests/
├── instance/
├── requirements.txt
├── run.py
├── .env
├── .env.example
├── .gitignore
├── .cursorrules
├── context.md
├── prd.md
├── architecture.md
├── ui-guidelines.md
└── database-schema.md

This is the target structure, not a requirement to create every empty file immediately. Build modules incrementally and keep them consistent with the actual implementation.

## 3. Application Initialization
- Create the Flask application through an application factory.
- Load configuration from environment variables.
- Initialize SQLAlchemy, migrations, login management, CSRF protection, and other approved extensions.
- Register blueprints.
- Configure safe error handlers.
- Initialize logging.
- Never create production administrator credentials from hard-coded defaults.
- Provide an explicit development-only bootstrap or CLI command for initial setup.

## 4. Authentication Flow
1. Staff opens the login page.
2. Backend validates credentials.
3. Backend verifies that the account is active.
4. The session is established securely.
5. User is redirected to the appropriate dashboard.
6. Each protected request verifies authentication and authorization.
7. Logout invalidates the session.

Use password hashes. Never store plaintext passwords.

## 5. Dynamic Form Architecture
The form builder should store form definitions in the database.

A form configuration contains:
- Name and visit type
- Version
- Publication status
- Field definitions
- Field ordering
- Required flags
- Allowed options
- Supported validation settings
- Creator and publication timestamps

Suggested lifecycle:

Draft → Published → Superseded or Archived

A published form version should be immutable for historical interpretation. Publishing changes should create a new version.

At registration time:
1. Load the active form for the selected visit type.
2. Render its supported fields.
3. Receive the submitted values.
4. Validate the form version and every field on the server.
5. Reject unknown or unauthorized fields.
6. Persist the response against the selected form version.
7. Create the visit request.

Never interpret form configuration as executable code or arbitrary SQL.

## 6. Approval Architecture
A registration request begins in PENDING_APPROVAL when approval is required.

The approval service must:
- Verify the actor's role.
- Verify that the actor is an authorized approver.
- Verify that the request can transition from its current status.
- Record the decision and timestamp.
- Create or authorize QR credential issuance only after approval.
- Write an audit event within the same transaction when possible.

Use explicit state transitions instead of allowing arbitrary status updates.

## 7. QR Credential Architecture
QR codes contain an opaque random token or a secure reference that cannot reveal personal details.

Recommended flow:
1. Generate a cryptographically random token.
2. Store its secure hash with the visit association and expiry.
3. Encode the raw token in the QR code.
4. Deliver or display the QR code through an approved channel.
5. On scan, submit the token to the backend over HTTPS.
6. Hash the submitted token and locate the credential.
7. Check validity, expiry, revocation, approval, visit date, and visit state.
8. Proceed to identity verification and check-in.
9. Atomically mark the entry credential as consumed or the visit as checked in.

If tokens are stored as hashes, the raw token cannot be recovered from the database. Reissuing requires generating a new token.

Do not log raw tokens.

## 8. Check-In and Checkout Transactions
Check-in must be handled as a transaction:
- Lock or otherwise safely serialize the relevant state change.
- Recheck credential validity and approval status.
- Ensure the visit has no active check-in.
- Create the entry event.
- Update the visit state.
- Consume or update the entry credential.
- Write an audit event.

Commit only if all required operations succeed.

Checkout must:
- Find the active visit.
- Confirm that checkout is allowed.
- Create the exit event.
- Update visit status.
- Record the responsible staff member.
- Write an audit event.

Use database constraints and transactions to prevent duplicate active visits. Do not rely solely on frontend checks.

## 9. Time Handling
- Store authoritative event timestamps in UTC.
- Generate event times on the server.
- Convert timestamps to the configured local timezone for display.
- Use consistent UTC handling for expiry comparisons.
- Store planned visit times with an explicit timezone policy.
- Never trust a visitor's browser clock as the authoritative check-in time.

## 10. Error Handling
Provide consistent error handling for:
- Invalid form submissions
- Unauthorized actions
- Missing records
- Expired QR credentials
- Duplicate check-ins
- Invalid checkout attempts
- Database errors
- Camera permission failures
- Unexpected application errors

Display safe messages to users and log diagnostic information on the server. Do not expose stack traces or secrets.

## 11. API and Routing Conventions
Prefer resource-oriented URLs and clear HTTP methods.

Illustrative routes:
- GET /login
- POST /login
- POST /logout
- GET /register
- POST /register
- GET /admin/dashboard
- GET /admin/forms
- POST /admin/forms
- GET /faculty/requests
- POST /faculty/requests/<request_id>/approve
- POST /faculty/requests/<request_id>/reject
- GET /security/scan
- POST /security/validate-qr
- POST /security/check-in
- POST /security/check-out
- GET /security/occupancy
- GET /reports/visits

These are proposed routes. Follow one consistent routing convention throughout the implementation.

All state-changing endpoints must use appropriate CSRF protection, authentication, authorization, validation, and transaction handling.

## 12. Reporting Architecture
Reports must query persisted database records, not frontend-generated sample data.

Apply:
- Server-side filtering
- Pagination for large result sets
- Role-based data restrictions
- Date-range validation
- Safe CSV generation
- Audit logging for sensitive exports

Emergency reports must clearly distinguish recorded active visits from verified physical occupancy.

## 13. Offline Strategy
The initial release should be online-first.

If offline support is added:
- Store queued events as pending and unverified.
- Avoid storing raw QR secrets unnecessarily in browser storage.
- Synchronize through authenticated endpoints.
- Apply idempotency keys or equivalent duplicate protection.
- Revalidate every event on the server.
- Record the original client event time separately from the authoritative server receipt time.
- Do not backdate authoritative server timestamps.
- Document conflicts and rejected synchronization events.

If safe offline validation cannot be implemented, use a documented manual fallback rather than pretending the scan was verified.

## 14. Deployment
Development:
- Flask development server.
- Local SQLite database.
- Local environment variables.

Production:
- Production WSGI server.
- HTTPS.
- Secure session settings.
- Restricted file permissions.
- Protected database and backups.
- Configured logging and monitoring.
- Database migrations.
- Secret management outside source control.

SQLite is suitable for the initial single-instance project. If simultaneous use across multiple servers or higher concurrency becomes a requirement, evaluate a production database migration.

## 15. Testing Architecture
Use pytest for:
- Model and service tests
- Route tests
- Authorization tests
- Form validation tests
- QR lifecycle tests
- Check-in/checkout transaction tests
- Report filtering tests
- Failure and duplicate-request tests

Use a separate test database. Never run automated tests against real visitor data.

## 16. Implementation Order
1. Project setup and configuration.
2. Database models and migrations.
3. Authentication and authorization.
4. Role-based dashboards.
5. User management.
6. Dynamic form builder.
7. Visitor registration.
8. Approval workflow.
9. QR credential lifecycle.
10. Check-in and checkout.
11. Occupancy and reporting.
12. Audit logging and emergency list.
13. Security hardening and end-to-end testing.
