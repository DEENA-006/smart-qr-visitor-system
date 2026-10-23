import pytest
from sqlalchemy.exc import IntegrityError
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog, AuditAction, AuditOutcome
from app.services.audit_service import AuditService


def test_user_creation_and_password_hashing(db):
    """Test user creation, password hashing, and verification."""
    user = User(
        username='johndoe',
        email='john@campus.edu',
        full_name='John Doe',
        role=UserRole.FACULTY
    )
    user.set_password('Secret@123')
    db.session.add(user)
    db.session.commit()

    assert user.id is not None
    assert user.password_hash != 'Secret@123'
    assert user.check_password('Secret@123') is True
    assert user.check_password('WrongPass') is False
    assert user.check_password('') is False


def test_user_role_properties(db):
    """Test user role checking methods."""
    admin = User(username='admin_test', full_name='Admin', role=UserRole.ADMIN)
    admin.set_password('Pass@123')
    assert admin.is_admin is True
    assert admin.is_faculty is False
    assert admin.is_security is False
    assert admin.has_role(UserRole.ADMIN) is True
    assert admin.has_role(UserRole.FACULTY, UserRole.SECURITY) is False


def test_unique_username_constraint(db):
    """Test that duplicate usernames violate uniqueness constraints."""
    u1 = User(username='duplicate', full_name='User 1', role=UserRole.FACULTY)
    u1.set_password('Pass@123')
    db.session.add(u1)
    db.session.commit()

    u2 = User(username='duplicate', full_name='User 2', role=UserRole.FACULTY)
    u2.set_password('Pass@456')
    db.session.add(u2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_unique_email_constraint(db):
    """Test that duplicate emails violate uniqueness constraints."""
    u1 = User(username='user1', email='same@campus.edu', full_name='User 1', role=UserRole.FACULTY)
    u1.set_password('Pass@123')
    db.session.add(u1)
    db.session.commit()

    u2 = User(username='user2', email='same@campus.edu', full_name='User 2', role=UserRole.FACULTY)
    u2.set_password('Pass@456')
    db.session.add(u2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_audit_log_creation_and_metadata(db):
    """Test creating audit logs and storing sanitized metadata."""
    log = AuditService.log_event(
        action=AuditAction.SECURITY_CHECK,
        entity_type='SYSTEM',
        outcome=AuditOutcome.SUCCESS,
        reason='Routine health inspection',
        metadata={'check_type': 'database', 'password': 'omit-this-secret'},
        ip_address='127.0.0.1'
    )
    assert log.id is not None
    assert log.outcome == AuditOutcome.SUCCESS
    metadata = log.get_metadata()
    assert metadata.get('check_type') == 'database'
    assert 'password' not in metadata


def test_utc_datetime_roundtrip(db):
    """Test that datetimes are stored in UTC and retrieved as timezone-aware UTC objects."""
    from datetime import datetime, timezone

    user = User(
        username='tz_user',
        email='tz@campus.edu',
        full_name='Timezone User',
        role=UserRole.FACULTY
    )
    user.set_password('Pass@123')
    db.session.add(user)
    db.session.commit()

    # Query back from DB
    loaded_user = db.session.get(User, user.id)
    assert loaded_user.created_at is not None
    assert loaded_user.created_at.tzinfo == timezone.utc

    # Verify direct comparison with datetime.now(timezone.utc) does not raise TypeError
    current_utc = datetime.now(timezone.utc)
    assert loaded_user.created_at <= current_utc

    # Also test AuditLog created_at
    log = AuditService.log_event(
        action=AuditAction.SECURITY_CHECK,
        entity_type='USER',
        actor_user_id=loaded_user.id
    )
    loaded_log = db.session.get(AuditLog, log.id)
    assert loaded_log.created_at.tzinfo == timezone.utc
    assert loaded_log.created_at <= datetime.now(timezone.utc)


def test_production_seed_protection(runner, monkeypatch):
    """Test that seed-users command refuses to run in production mode."""
    from run import seed_users

    # Simulate production environment
    monkeypatch.setenv('APP_ENV', 'production')

    result = runner.invoke(seed_users)
    assert "SECURITY REFUSAL" in result.output
    assert "restricted to local development environments" in result.output


def test_single_published_version_partial_unique_index(db):
    """Test that the database-level partial unique index rejects a second PUBLISHED version for the same form."""
    from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
    from app.models.visit_type import VisitType

    form = RegistrationForm(name='Unique Published Test', visit_type=VisitType.GENERAL)
    db.session.add(form)
    db.session.commit()

    # Two drafts for the same form are allowed
    v1 = FormVersion(form_id=form.id, version_number=1, status=FormVersionStatus.DRAFT, schema_json='[]')
    v2 = FormVersion(form_id=form.id, version_number=2, status=FormVersionStatus.DRAFT, schema_json='[]')
    db.session.add_all([v1, v2])
    db.session.commit()

    # Setting v1 to PUBLISHED succeeds
    v1.status = FormVersionStatus.PUBLISHED
    db.session.commit()

    # Setting v2 to PUBLISHED without archiving v1 must raise IntegrityError at database engine level
    v2.status = FormVersionStatus.PUBLISHED
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_approval_decision_model_and_relationships(db):
    """Test ApprovalDecision model creation, relationship to VisitRequest and User, and UTCDateTime handling."""
    from datetime import datetime, timezone
    from app.models.visit import VisitRequest, VisitRequestStatus, ApprovalDecision, ApprovalDecisionType
    from app.models.visitor import Visitor
    from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
    from app.models.visit_type import VisitType

    faculty = User(username='hostprof', email='host@prof.edu', full_name='Host Prof', role=UserRole.FACULTY)
    faculty.set_password('Prof@123')
    visitor = Visitor(public_reference='VIS-TEST-M3', full_name='M3 Guest')
    form = RegistrationForm(name='Approval Test Form', visit_type=VisitType.ACADEMIC)
    db.session.add_all([faculty, visitor, form])
    db.session.commit()

    v1 = FormVersion(form_id=form.id, version_number=1, status=FormVersionStatus.PUBLISHED, schema_json='[]')
    db.session.add(v1)
    db.session.commit()

    req = VisitRequest(
        public_reference='REQ-M3-APP-1',
        visitor_id=visitor.id,
        form_version_id=v1.id,
        visit_type=VisitType.ACADEMIC,
        host_user_id=faculty.id,
        purpose='Research Discussion',
        status=VisitRequestStatus.PENDING_APPROVAL
    )
    db.session.add(req)
    db.session.commit()

    # Record approval decision
    now_utc = datetime.now(timezone.utc)
    decision = ApprovalDecision(
        visit_request_id=req.id,
        actor_user_id=faculty.id,
        decision=ApprovalDecisionType.APPROVED,
        reason='Academic seminar verified'
    )
    req.status = VisitRequestStatus.APPROVED
    req.approved_at = now_utc
    req.decided_by_id = faculty.id
    db.session.add(decision)
    db.session.commit()

    # Verify relationships and attributes
    loaded_req = db.session.get(VisitRequest, req.id)
    assert loaded_req.decided_by.id == faculty.id
    assert loaded_req.decisions.count() == 1
    d = loaded_req.decisions.first()
    assert d.decision == ApprovalDecisionType.APPROVED
    assert d.actor_user.id == faculty.id
    assert d.created_at.tzinfo == timezone.utc


def test_qr_credential_model_and_lifecycle(db):
    """Test QRCredential model, SHA-256 token hash uniqueness, and is_valid_now() checks."""
    import hashlib
    from datetime import datetime, timezone, timedelta
    from app.models.visit import VisitRequest, VisitRequestStatus, QRCredential, QRCredentialStatus
    from app.models.visitor import Visitor
    from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
    from app.models.visit_type import VisitType

    visitor = Visitor(public_reference='VIS-QR-M3', full_name='QR Visitor')
    form = RegistrationForm(name='QR Form', visit_type=VisitType.GENERAL)
    db.session.add_all([visitor, form])
    db.session.commit()

    v1 = FormVersion(form_id=form.id, version_number=1, status=FormVersionStatus.PUBLISHED, schema_json='[]')
    db.session.add(v1)
    db.session.commit()

    req = VisitRequest(
        public_reference='REQ-QR-M3-1',
        visitor_id=visitor.id,
        form_version_id=v1.id,
        visit_type=VisitType.GENERAL,
        purpose='Inspection',
        status=VisitRequestStatus.APPROVED
    )
    db.session.add(req)
    db.session.commit()

    # Generate token hash
    token_str = "test-token-secret-12345"
    token_hash = hashlib.sha256(token_str.encode('utf-8')).hexdigest()

    cred = QRCredential(
        visit_request_id=req.id,
        token_hash=token_hash,
        status=QRCredentialStatus.ACTIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db.session.add(cred)
    db.session.commit()

    assert cred.id is not None
    assert cred.is_valid_now() is True
    assert req.active_credential.id == cred.id

    # Duplicate token_hash must fail
    dup_cred = QRCredential(
        visit_request_id=req.id,
        token_hash=token_hash,
        status=QRCredentialStatus.ACTIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db.session.add(dup_cred)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_single_active_visit_session_partial_unique_index(db):
    """Test database-level partial unique index uq_visit_sessions_single_active preventing multiple ACTIVE sessions."""
    from datetime import datetime, timezone
    from app.models.visit import VisitRequest, VisitRequestStatus, VisitSession, VisitSessionStatus
    from app.models.visitor import Visitor
    from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
    from app.models.visit_type import VisitType

    sec_user = User(username='gateofficer', email='gate@campus.edu', full_name='Gate Officer', role=UserRole.SECURITY)
    sec_user.set_password('Gate@123')
    visitor = Visitor(public_reference='VIS-SESS-M3', full_name='Session Visitor')
    form = RegistrationForm(name='Session Form', visit_type=VisitType.OFFICIAL)
    db.session.add_all([sec_user, visitor, form])
    db.session.commit()

    v1 = FormVersion(form_id=form.id, version_number=1, status=FormVersionStatus.PUBLISHED, schema_json='[]')
    db.session.add(v1)
    db.session.commit()

    req = VisitRequest(
        public_reference='REQ-SESS-M3-1',
        visitor_id=visitor.id,
        form_version_id=v1.id,
        visit_type=VisitType.OFFICIAL,
        purpose='Campus Audit',
        status=VisitRequestStatus.APPROVED
    )
    db.session.add(req)
    db.session.commit()

    # Session 1: Check-in as ACTIVE
    now_utc = datetime.now(timezone.utc)
    sess1 = VisitSession(
        visit_request_id=req.id,
        status=VisitSessionStatus.ACTIVE,
        checked_in_at=now_utc,
        checked_in_by_id=sec_user.id
    )
    db.session.add(sess1)
    db.session.commit()
    assert req.active_session.id == sess1.id

    # Attempt Session 2 as ACTIVE for the same visit request -> MUST fail at DB level
    sess2 = VisitSession(
        visit_request_id=req.id,
        status=VisitSessionStatus.ACTIVE,
        checked_in_at=now_utc,
        checked_in_by_id=sec_user.id
    )
    db.session.add(sess2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    # Complete session 1
    sess1 = db.session.get(VisitSession, sess1.id)
    sess1.status = VisitSessionStatus.COMPLETED
    sess1.checked_out_at = datetime.now(timezone.utc)
    sess1.checked_out_by_id = sec_user.id
    db.session.commit()

    # Now a second session can be created and completed
    sess2 = VisitSession(
        visit_request_id=req.id,
        status=VisitSessionStatus.ACTIVE,
        checked_in_at=datetime.now(timezone.utc),
        checked_in_by_id=sec_user.id
    )
    db.session.add(sess2)
    db.session.commit()

    sess2.status = VisitSessionStatus.COMPLETED
    sess2.checked_out_at = datetime.now(timezone.utc)
    sess2.checked_out_by_id = sec_user.id
    db.session.commit()

    # Multiple historical COMPLETED sessions are preserved
    db.session.refresh(req)
    completed_sessions = req.sessions.filter_by(status=VisitSessionStatus.COMPLETED).all()
    assert len(completed_sessions) == 2


def test_visit_event_model_and_session_relationship(db):
    """Test VisitEvent model, relationship with VisitSession, and metadata JSON handling."""
    from datetime import datetime, timezone
    from app.models.visit import VisitRequest, VisitSession, VisitEvent, VisitEventType
    from app.models.visitor import Visitor
    from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
    from app.models.visit_type import VisitType

    visitor = Visitor(public_reference='VIS-EV-M3', full_name='Event Visitor')
    form = RegistrationForm(name='Event Form', visit_type=VisitType.GENERAL)
    db.session.add_all([visitor, form])
    db.session.commit()

    v1 = FormVersion(form_id=form.id, version_number=1, status=FormVersionStatus.PUBLISHED, schema_json='[]')
    db.session.add(v1)
    db.session.commit()

    req = VisitRequest(
        public_reference='REQ-EV-M3-1',
        visitor_id=visitor.id,
        form_version_id=v1.id,
        visit_type=VisitType.GENERAL,
        purpose='Event Testing'
    )
    db.session.add(req)
    db.session.commit()

    sess = VisitSession(visit_request_id=req.id, status='ACTIVE', checked_in_at=datetime.now(timezone.utc))
    db.session.add(sess)
    db.session.commit()

    ev = VisitEvent(
        visit_session_id=sess.id,
        event_type=VisitEventType.CHECK_IN,
        correction_reason=None
    )
    ev.set_metadata({'gate_number': 'Gate 1', 'scanner_type': 'camera'})
    db.session.add(ev)
    db.session.commit()

    assert ev.id is not None
    assert ev.occurred_at.tzinfo == timezone.utc
    assert ev.get_metadata() == {'gate_number': 'Gate 1', 'scanner_type': 'camera'}
    assert sess.events.count() == 1



