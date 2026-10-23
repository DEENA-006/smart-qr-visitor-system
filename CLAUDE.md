# CLAUDE.md — Smart QR Visitor Management System

## 1. Project Overview

Build a professional, secure, responsive web application called **Smart QR Visitor Management System**.

**Tagline:** Secure Entry. Smarter Access.

The system replaces manual visitor registers with digital registration, configurable forms, approval workflows, QR-based verification, photo verification, electronic check-in/check-out, and reports.

The application is intended for a college or institutional campus where visitors must be registered and their entry and exit must be traceable.

## 2. Primary Objectives

- Replace paper-based visitor registration.
- Allow administrators to manage visitor registration forms.
- Allow authorized faculty members to customize permitted form fields.
- Verify visitor identity using the submitted passport-size photo.
- Generate secure, visit-specific QR codes.
- Prevent unauthorized entry and QR code reuse.
- Record accurate check-in and check-out events.
- Provide searchable visitor records, reports, and emergency lists.
- Protect personal information through appropriate access controls.
- Provide a professional, responsive user interface.

## 3. Technology Stack

Use the following stack unless an existing project constraint requires a documented change.

- Backend: Python with Flask
- Database: SQLite for the initial version
- ORM: SQLAlchemy
- Database migrations: Flask-Migrate
- Authentication: Flask-Login or an equivalent secure session-based implementation
- Frontend: HTML5, CSS3, JavaScript, and Jinja2 templates
- QR generation: A maintained Python QR-code library
- Forms and security: Server-side validation, CSRF protection, and secure session handling
- Testing: pytest

Use a modular, maintainable architecture. Do not place the entire application in one Python file.

## 4. User Roles and Permissions

### Administrator

- Log in securely.
- Create, edit, activate, deactivate, and publish registration forms.
- Configure form fields, validation rules, and required fields.
- Manage staff accounts and role permissions.
- Configure approval workflows and QR validity rules.
- View visitor records and system-wide reports.
- Review audit logs and authorized corrections.
- View current occupancy and emergency visitor lists.

### Faculty / Host

- Log in securely.
- View visit requests assigned to them.
- Approve or reject requests when authorized.
- Customize only the form fields and rules permitted by the administrator.
- View relevant visitor information and visit status.
- Review assigned visit history.

### Security Staff

- Log in securely.
- Scan and validate visitor QR codes.
- View the registered visitor's photo and relevant approved details.
- Compare the visitor with the submitted photo.
- Confirm physical entry only after successful verification.
- Record check-out when the visitor leaves.
- View current occupancy and authorized emergency lists.
- Report mismatches, invalid QR codes, and suspicious activity.

### Visitor

- Complete the currently published registration form.
- Upload a passport-size photo in an accepted image format.
- Submit a visit request.
- View the request status where supported.
- Receive or access the QR code only when the required approval conditions are satisfied.

Enforce permissions on the server for every protected operation. Hiding a button in the interface is not sufficient authorization.

## 5. Dynamic Registration Form Builder

The registration form must not be hardcoded for every visit type.

Administrators should be able to configure fields such as:

- Full name
- Mobile number
- Email address, where required
- Organization or institution
- Purpose of visit
- Faculty member or host
- Visit date and expected time
- Passport-size photo
- Additional institution-specific fields

Support appropriate field types, required/optional settings, validation rules, field ordering, and form publication.

Faculty members may customize only the fields and settings explicitly permitted by the administrator.

Visitors must see the currently published form.

Store form versions so that historical submissions remain understandable even after a form is changed.

Validate all submitted fields on the server. Never trust client-side validation alone.

## 6. Visitor Registration and Duplicate Detection

- Validate submitted information.
- Validate uploaded image types and file sizes.
- Generate unique visitor and visit-request identifiers.
- Detect possible duplicate registrations using appropriate fields and configurable time windows.
- Do not automatically reject two different people merely because they share a name or phone number.
- Allow authorized staff to review possible duplicates.
- Store registration status and timestamps.
- Preserve historical visit records.

## 7. Approval Workflow

Support the following general workflow:

1. Visitor submits the registration form.
2. The system validates the request.
3. The system identifies the appropriate faculty member, host, or administrator.
4. The authorized person approves or rejects the request.
5. The system records the decision, decision-maker, time, and optional reason.
6. An eligible approved request receives a QR credential.
7. Security verifies the QR code and visitor identity before entry.

Do not issue an active entry credential before the configured approval requirements are satisfied.

## 8. QR Code Security

QR codes must be visit-specific, unpredictable, and subject to expiry and revocation.

Requirements:

- Generate a cryptographically secure random token.
- Store a hash of the token instead of storing the raw token where practical.
- Avoid placing personal information directly inside the QR code.
- Check token validity, expiry, revocation, approval status, and visit status on the server.
- Prevent repeated check-in using the same visit credential.
- Support credential revocation when a visit is cancelled or otherwise invalidated.
- Use HTTPS in production.
- Apply reasonable rate limits to QR validation endpoints.
- Record invalid scans and suspicious activity in appropriate security logs.

A QR code is a reference to a visit credential. Possessing the QR code alone does not prove the holder's identity or physical presence.

## 9. Mandatory Photo Verification and Physical Entry

The visitor must upload a passport-size photo during registration.

When security staff scans the QR code, display:

- Visitor's registered photo
- Visitor's name
- Relevant visit details
- Host or faculty member
- Approval status
- QR validity status
- Current visit/check-in status

Security staff must compare the person physically present with the registered photo.

**Mandatory rule:** The application must not automatically mark the visitor as checked in merely because a QR code was scanned.

The workflow must be:

1. Scan QR code.
2. Validate the credential on the server.
3. Confirm approval and visit eligibility.
4. Display the visitor's registered photo.
5. Security staff compares the photo with the person present.
6. Security staff explicitly confirms entry.
7. The system records the successful check-in.

If the photo does not match, the QR code is invalid, or approval is missing, do not record a successful check-in. Provide an appropriate warning and an authorized review procedure.

For higher-security deployments, support optional official-ID verification according to institutional policy. Do not introduce automatic facial recognition unless separately approved and properly designed for privacy, accuracy, and legal requirements.

## 10. Check-In and Check-Out

Maintain a clear distinction between a registration request, an approved visit, and an actual physical visit session.

For check-in:

- Require a valid, approved, unexpired credential.
- Require the security staff member to confirm photo verification.
- Record the authoritative server timestamp.
- Record the responsible staff account.
- Prevent duplicate active sessions for the same visit.

For check-out:

- Allow authorized security staff to record the visitor's exit.
- Record the server timestamp and responsible staff account.
- Prevent duplicate or invalid checkout operations.
- Update current occupancy accurately.

If checkout is missing, flag the session for review. Do not assume that the visitor is physically inside solely because the record lacks a checkout timestamp.

Authorized corrections must require a reason and create an audit entry. Never silently overwrite historical events.

## 11. Live Occupancy and Emergency Management

Provide an authorized dashboard showing:

- Visitors currently recorded as checked in
- Visitor name and registered photo where necessary
- Host or faculty member
- Check-in timestamp
- Visit status
- Missing-checkout or exception flags

Provide an emergency visitor list that can be accessed quickly by authorized personnel.

Clearly label the list as based on recorded system events. It must not claim to prove the physical presence of every listed visitor.

Protect emergency lists and visitor data from unauthorized access.

## 12. Search, Reports, and Audit Logs

Support search and filtering by appropriate fields, including:

- Visitor name
- Mobile number, where permitted
- Date range
- Visit purpose
- Host or faculty member
- Approval status
- Check-in/check-out status

Provide useful reports and CSV exports for authorized users.

Record important security and business events, including:

- Login successes and failures where appropriate
- Registration and approval decisions
- QR generation, revocation, and invalid scan attempts
- Check-in and check-out
- Authorized record corrections
- Form publication and configuration changes
- Permission-sensitive administrative actions

Audit logs should include the event type, relevant record identifier, actor where applicable, timestamp, and reason for corrections.

Do not log passwords, raw QR tokens, session secrets, or unnecessary personal information.

## 13. Security and Privacy

- Hash passwords with a suitable password-hashing algorithm.
- Use secure session settings and appropriate cookie flags.
- Protect state-changing forms and requests against CSRF.
- Validate and normalize input on the server.
- Use parameterized database operations through SQLAlchemy.
- Escape untrusted output to reduce XSS risk.
- Restrict file uploads by size, type, and safe storage strategy.
- Do not expose uploaded photos through unrestricted public URLs.
- Enforce role-based access on every protected route and operation.
- Keep secrets in environment variables.
- Never commit real credentials or production secrets.
- Apply data minimization and a documented retention policy.
- Avoid displaying sensitive information unless it is needed for the user's role.

## 14. Network and Server Failure Handling

The first release should be online-first.

If the server or network is unavailable:

- Do not show a successful check-in unless the server confirms it.
- Display a clear failure or pending status.
- Prevent accidental duplicate submissions during retries.
- Provide a documented manual contingency procedure for authorized security staff.
- Record manual fallback events for later reconciliation when supported.

Full offline QR validation and synchronization may be implemented as a later milestone. Do not claim that offline validation is secure or synchronized unless it has actually been implemented and tested.

If offline operation is introduced, distinguish pending offline events from server-confirmed events and define conflict resolution, token expiry, revocation, replay protection, and timestamp handling.

## 15. Timestamp and Data Integrity Rules

- Use server-generated timestamps as the authoritative time for online operations.
- Store timestamps consistently, preferably in UTC.
- Display timestamps in the configured institutional timezone, initially Asia/Kolkata.
- Preserve the original event history.
- Make check-in and check-out updates transactional.
- Prevent concurrent requests from creating duplicate active sessions.
- Use unique constraints and indexes where appropriate.
- Do not trust visitor-device time as the authoritative entry time.

## 16. User Interface Requirements

Build a premium, modern, professional SaaS-style interface.

Use the existing `ui-guidelines.md` as the primary design reference.

The interface should include:

- A clean login page
- Role-specific dashboards
- A clear navigation sidebar and top bar
- A responsive layout for desktop, tablet, and mobile
- A dynamic form builder
- A simple visitor registration page
- A security QR scanning and photo-verification screen
- Searchable visitor tables
- Approval and rejection screens
- Check-in/check-out status indicators
- Reports and emergency lists
- Loading, empty, success, validation-error, and server-error states
- Accessible labels, keyboard navigation, and readable contrast

Use consistent design tokens, typography, spacing, cards, tables, buttons, badges, and form controls.

Do not use fake visitor data in production-facing functionality. Demo data must be clearly identified as demo data.

## 17. Database Design

Use SQLAlchemy models and database migrations.

Design the database to support at least:

- Users and roles
- Visitor profiles
- Registration forms and form versions
- Configurable form fields
- Visit requests and submitted responses
- Approval decisions
- QR credentials
- Visit sessions
- Check-in/check-out events
- Audit logs
- Optional notifications

Use foreign keys, indexes, appropriate constraints, and transactions.

Keep visitor identity, visit requests, QR credentials, and physical visit sessions conceptually separate.

## 18. Testing Requirements

Write automated tests for important business and security rules.

At minimum, test:

- Login and logout
- Password handling
- Role-based route authorization
- Dynamic form validation
- Registration and duplicate detection
- Approval and rejection
- QR token validity and expiry
- Revoked and reused QR credentials
- QR scans without approval
- Photo-verification confirmation requirement
- Check-in and checkout
- Duplicate active sessions
- Missing-checkout flags
- Audit logging
- Unauthorized access to visitor photos
- Search, reports, and exports
- Server failure and retry behavior

Tests must verify that a QR scan alone cannot create a successful physical check-in.

## 19. Development Workflow

Do not implement the entire project in one unreviewed step.

Follow these milestones:

### Milestone 1 — Foundation
- Project structure
- Environment configuration
- Database setup and migrations
- Authentication and logout
- Role-based authorization
- Role-specific dashboard skeletons
- Basic automated tests
- Setup instructions

### Milestone 2 — Dynamic Forms and Registration
- Admin form builder
- Form versions and publication
- Faculty permissions
- Visitor registration
- Photo upload validation
- Duplicate detection

### Milestone 3 — Approval and QR Security
- Approval workflow
- QR token generation
- Expiry and revocation
- QR validation endpoint
- QR security tests

### Milestone 4 — Security Desk
- QR scanning interface
- Registered photo display
- Mandatory staff photo comparison
- Explicit entry confirmation
- Check-in/check-out records
- Missing-checkout flags

### Milestone 5 — Dashboard and Reports
- Live recorded occupancy
- Search and filtering
- Reports and CSV export
- Emergency list
- Audit log interface

### Milestone 6 — Hardening and Delivery
- Responsive UI refinement
- Accessibility checks
- Security review
- Automated test completion
- Error handling
- Documentation
- Local setup and deployment instructions

Do not begin the next milestone until the current milestone is implemented, tested, and reviewed.

## 20. Coding Rules

- Use clear, descriptive names.
- Keep routes, models, business logic, and templates separated.
- Avoid duplicated business logic.
- Use reusable functions and templates.
- Add comments where logic is not obvious.
- Handle errors explicitly.
- Avoid hardcoded secrets and environment-specific paths.
- Do not leave core functionality as a placeholder while claiming it is complete.
- Do not remove existing working functionality without explaining why.
- Follow the existing project files and preserve architectural consistency.
- Update tests and documentation when requirements change.

## 21. Existing Project Instructions

Before writing code, read:

1. `context.md`
2. `prd.md`
3. `architecture.md`
4. `database-schema.md`
5. `ui-guidelines.md`
6. `.env.example`
7. `.cursorrules`
8. `feature-traceability.md`, if present

Treat the PRD as the functional requirements source, the architecture document as the implementation guide, and the UI guidelines as the design reference.

If two files conflict, identify the conflict and propose a resolution instead of silently choosing one.

## 22. Definition of Done

A feature is complete only when:

- Its intended behavior is implemented.
- Its role permissions are enforced on the server.
- Input validation and failure handling are present.
- Relevant automated tests pass.
- The interface reflects real backend state.
- Security-sensitive actions are logged where appropriate.
- Documentation is updated.
- No critical functionality is represented only by a visual mockup or placeholder.

At the end of every milestone, report:

1. Files created or modified.
2. Features implemented.
3. Commands required to run the application.
4. Tests executed and their actual results.
5. Known limitations.
6. The next recommended milestone.

**Start by inspecting the existing workspace and reading all available project requirement files. Then propose the Milestone 1 implementation plan before changing files.**