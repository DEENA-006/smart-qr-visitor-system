
# Product Requirements Document (PRD)
## Smart QR Visitor Management System

## 1. Product Summary
Build a full-stack web application that manages visitor registration, approval, QR credential validation, check-in, checkout, and reporting.

Primary users are Admin, Faculty/Host, and Security Staff. Visitors can use a public registration page when enabled.

## 2. Functional Requirements

### FR-01: Authentication
- Staff must log in with valid credentials.
- Passwords must be stored as secure hashes.
- Users must be able to log out.
- Disabled accounts must not be able to log in.
- Login failures must produce safe, understandable messages.
- Login attempts should be rate-limited.
- Password reset must use a secure process if implemented.
- Public registration must not expose staff dashboard routes.

Acceptance criteria:
- Valid staff credentials open the appropriate dashboard.
- Invalid credentials do not create a session.
- Disabled users cannot access protected pages.
- Logging out invalidates the session.

### FR-02: Role-Based Authorization
- Admin, Faculty, and Security must have separate permissions.
- Backend routes and service methods must enforce permissions.
- Users must not access records simply by changing an ID in the URL.
- Faculty can access only assigned or explicitly authorized visits.
- Security can access operational information required for gate duties.
- Only authorized administrators can assign privileged roles.

Acceptance criteria:
- Unauthorized requests return an appropriate 403 or safe redirect.
- A Faculty user cannot access Admin settings by manually entering a URL.
- Security cannot change global form policies.
- Authorization is checked for every sensitive operation.

### FR-03: User Management
Admin can:
- Create staff accounts.
- Edit permitted staff details.
- Assign approved roles.
- Activate or deactivate accounts.
- View account status.

Prevent unauthorized self-promotion and role escalation.

Record important account and role changes in the audit log.

### FR-04: Dynamic Registration Form Builder
Admin can:
- Create and edit form configurations.
- Add, remove, activate, deactivate, and reorder fields.
- Define labels, help text, field types, required status, and options.
- Configure validation rules within supported limits.
- Associate a form with a visit type.
- Publish a new form version.
- Preview the visitor-facing form.

Faculty may customize only explicitly permitted settings.

Supported field types should include:
- Short text
- Long text
- Telephone
- Email
- Date
- Time
- Select/dropdown
- Checkbox
- Vehicle registration, if enabled by policy

System-controlled fields, authorization rules, and security policies cannot be overridden through custom form fields.

Acceptance criteria:
- Publishing a form configuration changes the public form.
- Required fields are checked by the backend.
- Invalid options are rejected.
- Old submissions remain associated with their original form version.
- A visitor cannot bypass validation by editing browser requests.

### FR-05: Visitor Registration
The form may include, according to organizational policy:
- Full name
- Contact number
- Email
- Organization
- Visit purpose
- Visit type
- Host/faculty member
- Department
- Planned visit date and time
- Vehicle number
- Additional authorized fields

Do not require every field by default. The administrator decides which fields are needed.

The backend must:
- Validate submitted data.
- Reject malformed or unauthorized fields.
- Normalize appropriate values.
- Store the selected form version.
- Generate a unique reference number.
- Create a pending request when approval is required.
- Apply rate limits to public registration.

Acceptance criteria:
- A valid registration creates a persistent request.
- Invalid data does not create an approved visit.
- Repeated submissions are handled safely.
- Registration does not automatically imply approval.

### FR-06: Duplicate Detection
- Detect likely duplicate requests using configured fields and a relevant time window.
- Use normalized contact details where permitted.
- Provide a warning or review workflow instead of automatically blocking every matching name.
- Avoid treating two different people with the same name as identical.
- Log relevant duplicate-review decisions.

Acceptance criteria:
- A repeated submission can be flagged for review.
- A false-positive match does not automatically merge separate people.
- Existing records are not overwritten silently.

### FR-07: Approval Workflow
- Route requests to the correct faculty/host or authorized approver.
- Display pending, approved, rejected, cancelled, and expired states as applicable.
- Allow authorized approvers to approve or reject.
- Capture decision time and decision-maker.
- Allow a rejection reason.
- Prevent approval by unauthorized staff.
- Notify the visitor only if a notification mechanism is configured.

Acceptance criteria:
- A pending request cannot be checked in as an approved visit.
- Rejected requests cannot receive a usable visit credential.
- Every decision records the responsible user and timestamp.
- Concurrent approval attempts do not create inconsistent states.

### FR-08: QR Credential Generation
- Generate a unique, unpredictable token for each approved visit.
- Use an opaque token; never encode personal information directly.
- Associate the credential with a visit, expiry time, and status.
- Support revocation and reissue.
- Use a configurable validity period.
- Display or deliver the QR code through an approved method.

Acceptance criteria:
- Each credential is unique.
- An expired or revoked credential is rejected.
- A QR credential for a rejected visit cannot be used.
- Reissuing a credential invalidates the old one where required.
- QR secrets are not written to application logs.

### FR-09: QR Scanning and Validation
- Provide a security scanning page that uses a supported device camera when available.
- Provide a manual reference lookup as an authorized fallback.
- Send the credential to the server for validation.
- Check approval status, expiry, revocation, visit date, and existing check-in state.
- Display a clear result without exposing unnecessary personal information.
- Require staff identity verification steps according to policy.

Acceptance criteria:
- Valid credentials proceed to the required verification step.
- Invalid, expired, revoked, or unapproved credentials are rejected.
- Repeated scans cannot create duplicate check-in events.
- Camera denial or unsupported browsers show a helpful fallback.

### FR-10: Check-In
- Confirm the visit is eligible for entry.
- Require the necessary identity-verification confirmation.
- Record the server timestamp, visit ID, and staff identity.
- Prevent duplicate active check-ins.
- Update the current occupancy calculation.

Acceptance criteria:
- Successful check-in creates one active visit.
- A second concurrent check-in does not create another active visit.
- Failed check-in attempts do not appear as successful entries.
- The result is shown only after the server confirms it.

### FR-11: Check-Out
- Allow checkout of an active visit using QR scanning or authorized lookup.
- Record the server timestamp and responsible staff identity.
- Reject checkout when no active check-in exists.
- Update occupancy after successful checkout.
- Record corrections and overrides with a reason.

Acceptance criteria:
- Checkout closes the active visit.
- Duplicate checkout does not create inconsistent records.
- A completed visit is no longer counted in occupancy.
- Any authorized correction remains auditable.

### FR-12: Live Occupancy
Display:
- Current number of active visitors.
- Visitor list permitted for the signed-in role.
- Check-in time and visit status.
- Host or department when authorized.
- Visits with unusually long stays, if configured.

Calculate occupancy from confirmed active visits, not from submitted registrations or QR-generation counts.

If records may be incomplete, clearly label the list as recorded occupancy rather than guaranteed physical presence.

### FR-13: Search and Filters
Authorized users can search using permitted fields, such as:
- Visitor name
- Reference number
- Contact number, when authorized
- Host/faculty
- Department
- Visit status
- Date range

Use pagination and avoid exposing sensitive data to unauthorized roles.

### FR-14: Reports and Export
Provide reports for:
- Visits by date range
- Approved, rejected, and pending requests
- Check-in and checkout history
- Current active visitors
- Visits by host or department
- Missing checkout records
- QR validation failures, where appropriate

Allow authorized CSV export.

Exports must use permission checks, safe filenames, and appropriate CSV escaping. Protect against spreadsheet formula injection.

### FR-15: Emergency Visitor List
Provide an emergency view showing recorded active visits and the minimum information needed to identify and account for visitors.

Include:
- Visitor name
- Reference number
- Host/department, if available
- Recorded entry time
- Recorded status
- Last relevant update

Highlight missing checkout information and stale or uncertain records. Do not claim that the report guarantees every person physically present has been captured.

Access must be restricted and audited.

### FR-16: Audit Log
Record important events:
- Login failures and relevant security events
- User and role changes
- Form configuration changes
- Registration decisions
- QR creation, revocation, and reissue
- Check-in and checkout
- Administrative corrections
- Exports and sensitive report access where appropriate

Each audit event should contain:
- Event type
- Timestamp
- Actor, if known
- Affected record reference
- Outcome
- Reason or metadata where appropriate

Do not store passwords, raw QR tokens, or unnecessary sensitive data in audit logs. Audit records must not be silently editable through normal application screens.

### FR-17: Notifications
Notification support is optional in the first release.

If enabled:
- Send notifications only through configured providers.
- Avoid including sensitive personal details in messages.
- Record delivery status where supported.
- Do not report a message as delivered without confirmation from the provider.

### FR-18: Failure and Offline Handling
- Handle network interruptions and server errors.
- Show pending status when a request has not been confirmed.
- Do not assume that a browser submission succeeded.
- If offline scan queuing is added, label events as unverified until the server accepts them.
- Resolve synchronization conflicts without duplicate entries.
- Document the manual fallback procedure.

## 3. Non-Functional Requirements

### Security
- Server-side role authorization.
- Password hashing.
- CSRF protection.
- Secure sessions.
- SQL injection protection.
- Input validation.
- Rate limiting for sensitive endpoints.
- HTTPS in production.
- Secrets outside source control.

### Reliability
- Use database transactions for state-changing workflows.
- Enforce database constraints where possible.
- Back up the database.
- Provide understandable failure messages.
- Avoid duplicate events during retries.

### Usability
- Responsive layout.
- Clear labels and validation errors.
- Accessible keyboard controls.
- Readable contrast and typography.
- Fast security desk workflow.

### Maintainability
- Modular application structure.
- Automated tests.
- Version-controlled database migrations.
- Documented setup and deployment.
- Centralized configuration.

### Privacy
- Collect only necessary data.
- Restrict records by role.
- Establish retention and deletion rules.
- Protect exported data and backups.
- Follow applicable data-protection requirements and institutional policy.

## 4. Out of Scope for the First Release
Unless explicitly approved:
- Facial recognition.
- Biometric identity collection.
- Automatic integration with government identity databases.
- Payment processing.
- Mandatory third-party messaging services.
- Claims of guaranteed physical-presence detection from QR scanning alone.

## 5. Release Milestones
Milestone 1: Project setup, database, login, roles, and dashboards.

Milestone 2: Staff management and dynamic registration forms.

Milestone 3: Visitor submission, duplicate review, and approval.

Milestone 4: QR creation, validation, check-in, and checkout.

Milestone 5: Occupancy, search, reports, emergency list, and audit logs.

Milestone 6: Security testing, automated tests, documentation, and deployment preparation.

## 6. Final Acceptance
The application is ready for demonstration only after the critical workflows work end-to-end, permissions are tested, records persist correctly, and known limitations are documented.
