
# Database Schema
## Smart QR Visitor Management System

## 1. Database Technology
Use SQLite with SQLAlchemy ORM and Flask-Migrate.

Requirements:
- Use migrations for schema changes.
- Use foreign keys and database constraints.
- Enable SQLite foreign-key enforcement.
- Use transactions for state-changing operations.
- Store timestamps in UTC.
- Add indexes for common searches.
- Never commit a database containing real visitor data.
- Use synthetic data for development and tests.

## 2. Entity Relationships

- A User can create or review many VisitRequests.
- A Visitor can have many VisitRequests.
- A VisitRequest belongs to one Visitor.
- A VisitRequest may be assigned to a Faculty approver.
- A VisitRequest may have multiple approval decisions over time.
- A VisitRequest may have multiple QR credentials over its lifecycle.
- A VisitRequest can have at most one active visit session at a time.
- A VisitSession has an entry event and, when completed, an exit event.
- A RegistrationForm has multiple versioned FormVersions.
- A FormVersion contains multiple FormFields.
- A VisitRequest references the form version used during submission.
- An AuditLog records important actions by users or system processes.

Use stable primary keys, preferably UUIDs or another non-guessable public reference strategy where appropriate. Internal database IDs may be used, but must not be treated as authorization credentials.

## 3. Users Table

Table: users

Fields:
- id: primary key
- username: unique, required
- email: unique when supplied, according to account policy
- password_hash: required
- full_name: required
- role: ADMIN, FACULTY, or SECURITY
- is_active: boolean, default true
- created_at: UTC timestamp
- updated_at: UTC timestamp
- last_login_at: nullable UTC timestamp

Rules:
- Never store plaintext passwords.
- Restrict role assignment to authorized administrators or a controlled bootstrap process.
- Prevent unauthorized privilege escalation.
- Do not permanently delete users referenced by historical audit records; deactivate them instead.

## 4. Visitors Table

Table: visitors

Fields:
- id: primary key
- public_reference: unique visitor reference, if required
- full_name: required
- normalized_contact: nullable, stored only when necessary and authorized
- phone: nullable, according to form policy
- email: nullable, according to form policy
- organization: nullable
- created_at: UTC timestamp
- updated_at: UTC timestamp

Rules:
- Do not require every possible contact field.
- Collect only the minimum information needed.
- Avoid using contact information as a public identifier.
- Define retention and deletion policies.
- Use normalized contact values only for permitted matching operations.

If a visitor record can be created only through a visit request, ensure that the registration workflow does not create unnecessary permanent visitor profiles.

## 5. Registration Forms Table

Table: registration_forms

Fields:
- id: primary key
- name: required
- visit_type: required
- description: nullable
- is_active: boolean
- created_by: foreign key to users
- created_at: UTC timestamp
- updated_at: UTC timestamp

Rules:
- A form may have multiple versions.
- Only authorized administrators can publish global form configurations.
- Faculty customization must be permission-controlled.
- Prevent accidental removal of a form needed for historical records.

## 6. Form Versions Table

Table: form_versions

Fields:
- id: primary key
- form_id: foreign key to registration_forms
- version_number: required
- status: DRAFT, PUBLISHED, or ARCHIVED
- schema_json: validated JSON containing supported field definitions
- created_by: foreign key to users
- created_at: UTC timestamp
- published_at: nullable UTC timestamp

Constraints:
- Unique combination of form_id and version_number.
- Only one active published version per form, where required by the application policy.
- Published versions must not be silently edited.
- Creating changes to a published form must produce a new version.

The JSON schema must contain only supported field types and validated settings. Never execute code contained in this JSON.

## 7. Form Fields Table (Optional Normalized Design)

Table: form_fields

Fields:
- id: primary key
- form_version_id: foreign key to form_versions
- field_key: required
- label: required
- field_type: required
- is_required: boolean
- display_order: integer
- help_text: nullable
- options_json: nullable validated JSON
- validation_json: nullable validated JSON

Constraints:
- Unique field_key within a form version.
- Supported field types only.
- Reject unsafe or unsupported validation settings.

Implementation note:
Use either normalized form_fields records or a validated schema_json representation as the source of truth. Do not maintain two independently editable definitions that can become inconsistent.

## 8. Visit Requests Table

Table: visit_requests

Fields:
- id: primary key
- public_reference: unique request reference
- visitor_id: foreign key to visitors
- form_version_id: foreign key to form_versions
- visit_type: required
- host_user_id: nullable foreign key to users
- department: nullable
- purpose: required when configured by policy
- planned_start_at: nullable UTC timestamp
- planned_end_at: nullable UTC timestamp
- status: PENDING_APPROVAL, APPROVED, REJECTED, CANCELLED, or EXPIRED
- submitted_at: UTC timestamp
- approved_at: nullable UTC timestamp
- rejected_at: nullable UTC timestamp
- decided_by: nullable foreign key to users
- rejection_reason: nullable
- created_at: UTC timestamp
- updated_at: UTC timestamp

Rules:
- Enforce valid state transitions in the service layer.
- A pending request cannot be checked in.
- Record approval decisions with actor and timestamp.
- Validate that the planned visit period is sensible.
- Never trust a client-submitted approval status.
- Store form responses separately so dynamic fields do not require schema changes for every new field.

## 9. Visit Responses Table

Table: visit_responses

Fields:
- id: primary key
- visit_request_id: foreign key to visit_requests
- form_version_id: foreign key to form_versions
- response_json: validated JSON
- created_at: UTC timestamp
- updated_at: UTC timestamp

Rules:
- Store only fields permitted by the referenced form version.
- Reject unexpected keys.
- Validate field types and required values on the server.
- Do not store executable HTML, JavaScript, or SQL.
- Apply access controls when reading or exporting responses.
- Preserve enough version information to interpret historical responses.

## 10. Approval Decisions Table

Table: approval_decisions

Fields:
- id: primary key
- visit_request_id: foreign key to visit_requests
- actor_user_id: foreign key to users
- decision: APPROVED or REJECTED
- reason: nullable
- created_at: UTC timestamp

Rules:
- Keep the decision history.
- Validate that the actor is authorized for that request.
- Prevent unauthorized repeated or conflicting decisions.
- Use a transaction when updating request status and recording a decision.
- Do not silently rewrite past decisions.

## 11. QR Credentials Table

Table: qr_credentials

Fields:
- id: primary key
- visit_request_id: foreign key to visit_requests
- token_hash: unique, required
- status: ACTIVE, CONSUMED, REVOKED, or EXPIRED
- issued_at: UTC timestamp
- expires_at: UTC timestamp
- revoked_at: nullable UTC timestamp
- revoked_by: nullable foreign key to users
- consumed_at: nullable UTC timestamp

Rules:
- Generate tokens using a cryptographically secure random generator.
- Store the hash of the raw token, not the raw token itself.
- Do not include personal details in the QR payload.
- Enforce expiry and revocation on the server.
- Reissue by generating a new token and invalidating the old credential when appropriate.
- Ensure only one credential can successfully authorize entry for a visit.
- Perform credential validation and consumption atomically.
- Do not store raw QR secrets in audit logs.

A consumed entry credential does not mean the visit is completed. Checkout must be represented separately.

## 12. Visit Sessions Table

Table: visit_sessions

Fields:
- id: primary key
- visit_request_id: foreign key to visit_requests
- status: ACTIVE or COMPLETED
- checked_in_at: UTC timestamp
- checked_in_by: foreign key to users
- checked_out_at: nullable UTC timestamp
- checked_out_by: nullable foreign key to users
- created_at: UTC timestamp
- updated_at: UTC timestamp

Constraints and rules:
- Enforce at most one ACTIVE session per visit request.
- Use a suitable SQLite partial unique index or equivalent transactional protection.
- A session must have an entry timestamp.
- An ACTIVE session must not have a checkout timestamp.
- A COMPLETED session must have a checkout timestamp.
- Checkout must not occur before check-in.
- Recheck the current state inside the transaction.
- A correction must use a controlled, audited workflow.

## 13. Visit Events Table (Recommended)

Table: visit_events

Fields:
- id: primary key
- visit_session_id: foreign key to visit_sessions
- event_type: CHECK_IN, CHECK_OUT, or APPROVED_CORRECTION
- occurred_at: authoritative UTC timestamp assigned by the server
- recorded_by: nullable foreign key to users
- correction_reason: nullable
- metadata_json: nullable, restricted non-sensitive metadata
- created_at: UTC timestamp

Purpose:
Maintain a history of visit events rather than relying exclusively on a mutable status field.

Rules:
- Preserve historical events.
- Record corrections as additional events.
- Do not silently replace original timestamps.
- Keep event creation and related state changes transactionally consistent.
- If offline synchronization is implemented, store client-reported event time separately from server receipt time.

## 14. Audit Logs Table

Table: audit_logs

Fields:
- id: primary key
- actor_user_id: nullable foreign key to users
- action: required
- entity_type: required
- entity_reference: nullable
- outcome: required
- reason: nullable
- metadata_json: nullable, restricted metadata
- created_at: UTC timestamp
- request_id: nullable correlation reference

Rules:
- Record security-relevant actions and administrative changes.
- Avoid passwords, raw QR tokens, and unnecessary personal information.
- Restrict access to audit logs.
- Prevent ordinary users from editing or deleting audit entries.
- Do not claim tamper-proof storage unless a suitable tamper-evident or external audit mechanism exists.

## 15. Notifications Table (Optional)

Table: notifications

Fields:
- id: primary key
- visit_request_id: nullable foreign key to visit_requests
- recipient_reference: restricted recipient reference
- channel: EMAIL or SMS
- status: PENDING, SENT, FAILED, or UNKNOWN
- provider_reference: nullable
- created_at: UTC timestamp
- sent_at: nullable UTC timestamp

Rules:
- Do not store unnecessary message content or secrets.
- Do not claim delivery without provider confirmation.
- Keep notification credentials in environment variables or a secret manager.
- This table is optional until notification functionality is approved.

## 16. Indexes
Consider indexes for:
- users.username
- users.email
- visitors.public_reference
- visit_requests.public_reference
- visit_requests.status
- visit_requests.host_user_id
- visit_requests.submitted_at
- visit_requests.planned_start_at
- qr_credentials.token_hash
- qr_credentials.expires_at
- visit_sessions.status
- visit_sessions.checked_in_at
- visit_events.occurred_at
- audit_logs.created_at
- audit_logs.actor_user_id

Add indexes based on actual query patterns and inspect query performance before adding excessive indexes.

## 17. Transactions and Concurrency
Use database transactions for:
- Approval and decision-history updates.
- QR issuance and revocation.
- Check-in and credential consumption.
- Checkout and session completion.
- Administrative corrections and audit entries.

Concurrent requests must not create duplicate active sessions.

SQLite has concurrency limitations. Keep write transactions short and configure locking/busy-timeout behavior appropriately.

## 18. Data Retention
Define an institutional retention policy before production use.

The system should support:
- Controlled deletion or anonymization when appropriate.
- Retention of required audit records.
- Protection of backups.
- Restrictions on report exports.
- Documented handling of legal or institutional retention obligations.

Do not invent a universal retention period without organizational approval.

## 19. Migration and Integrity
- Use version-controlled migrations.
- Never modify an existing production database manually as a normal deployment method.
- Test migrations against a backup or test database.
- Use foreign-key constraints and unique constraints.
- Verify data integrity after migrations.
- Never run destructive schema changes without an explicit migration plan.

## 20. Seed Data
Provide a development-only seed process using clearly fictional records.

Never:
- Seed real visitor data.
- Hard-code production passwords.
- Create a publicly known production administrator credential.
- Run development seed routines automatically in production.

## 21. Schema Acceptance Criteria
- Foreign keys and constraints are enabled.
- Dynamic form versions are preserved.
- QR credentials are unique and stored securely.
- A visit cannot have duplicate active sessions.
- Entry and exit history can be audited.
- Unauthorized access to records is prevented by backend authorization.
- Reports use persisted data.
- Migrations can be applied and tested consistently.
