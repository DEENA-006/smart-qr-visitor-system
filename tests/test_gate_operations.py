import pytest
import re
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.user import User, UserRole
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    QRCredential,
    QRCredentialStatus,
    VisitSession,
    VisitSessionStatus,
    VisitEvent,
    VisitEventType
)
from app.models.visitor import Visitor
from app.models.registration_form import RegistrationForm, FormVersion
from app.models.visit_type import VisitType
from app.models.audit_log import AuditLog, AuditAction, AuditOutcome
from app.services.qr_service import QRService
from app.services.gate_service import GateService


def extract_csrf_token(html_text: str) -> str:
    """Helper to extract csrf_token from rendered HTML forms."""
    match = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html_text)
    if not match:
        match = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']csrf_token["\']', html_text)
    return match.group(1) if match else ''


@pytest.fixture
def approved_visit(db, admin_user, faculty_user):
    """Creates a published form, approved visit request, and active QR credential."""
    form = RegistrationForm(name="General Campus Visit", visit_type=VisitType.OFFICIAL, is_active=True)
    db.session.add(form)
    db.session.flush()

    version = FormVersion(
        form_id=form.id,
        version_number=1,
        status='PUBLISHED',
        published_at=datetime.now(timezone.utc),
        created_by_id=admin_user.id
    )
    version.set_schema([
        {'id': 'purpose_detail', 'label': 'Detail', 'type': 'text', 'required': False}
    ])
    db.session.add(version)
    db.session.flush()

    visitor = Visitor(
        public_reference=Visitor.generate_reference(),
        full_name="Grace Hopper",
        email="grace@navy.mil",
        phone="+12025550199",
        organization="US Navy"
    )
    db.session.add(visitor)
    db.session.flush()

    now_utc = datetime.now(timezone.utc)
    req = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=visitor.id,
        form_version_id=version.id,
        visit_type=VisitType.OFFICIAL,
        host_user_id=faculty_user.id,
        department=faculty_user.department,
        purpose="Keynote Lecture on Compilers",
        planned_start_at=now_utc - timedelta(minutes=15),
        planned_end_at=now_utc + timedelta(hours=3),
        photo_filename="grace_hopper_verified.jpg",
        status=VisitRequestStatus.APPROVED,
        approved_at=now_utc,
        decided_by_id=faculty_user.id
    )
    db.session.add(req)
    db.session.flush()

    cred, raw_token, _ = QRService.issue_credential(req.id, admin_user, commit=True)
    return req, cred, raw_token


def test_verify_valid_credential_and_manual_reference(app, db, security_user, approved_visit):
    """Test 1: Verification succeeds for both valid QR token payload and manual reference lookup."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        # A. Verify via raw token payload (VMS:<token>)
        res_token = GateService.verify_credential_or_reference(f"VMS:{raw_token}", security_user)
        assert res_token['valid'] is True
        assert res_token['status'] == 'VALID'
        assert res_token['can_check_in'] is True
        assert res_token['can_check_out'] is False
        assert res_token['visitor_details']['full_name'] == "Grace Hopper"
        assert res_token['visitor_details']['reference'] == req.public_reference
        assert res_token['visitor_details']['photo_filename'] == "grace_hopper_verified.jpg"

        # B. Verify via manual public reference lookup (REQ-...)
        res_ref = GateService.verify_credential_or_reference(req.public_reference, security_user)
        assert res_ref['valid'] is True
        assert res_ref['status'] == 'VALID'
        assert res_ref['can_check_in'] is True
        assert res_ref['visitor_details']['full_name'] == "Grace Hopper"


def test_verify_tampered_and_unknown_token_rejected(app, db, security_user, approved_visit):
    """Test 2: Tampered or invalid token returns INVALID_TOKEN."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        # Tamper last 5 characters
        tampered = raw_token[:-5] + "XXXXX"
        res = GateService.verify_credential_or_reference(f"VMS:{tampered}", security_user)
        assert res['valid'] is False
        assert res['status'] == 'INVALID_TOKEN'

        # Completely unknown token
        res_unknown = GateService.verify_credential_or_reference("VMS:completely_fake_token_value_here", security_user)
        assert res_unknown['valid'] is False
        assert res_unknown['status'] == 'INVALID_TOKEN'


def test_verify_expired_and_revoked_credentials_rejected(app, db, admin_user, security_user, approved_visit):
    """Test 3: Expired and revoked credentials fail gate verification."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        # A. Revoke credential
        QRService.revoke_credential(cred.id, admin_user, reason="Security review revoked")
        res_revoked = GateService.verify_credential_or_reference(f"VMS:{raw_token}", security_user)
        assert res_revoked['valid'] is False
        assert res_revoked['status'] == 'REVOKED'

        # B. Manually set expired credential
        cred_obj = db.session.get(QRCredential, cred.id)
        cred_obj.status = QRCredentialStatus.EXPIRED
        db.session.commit()

        res_expired = GateService.verify_credential_or_reference(f"VMS:{raw_token}", security_user)
        assert res_expired['valid'] is False
        assert res_expired['status'] == 'EXPIRED'


def test_verify_unapproved_visits_rejected(app, db, admin_user, security_user, approved_visit):
    """Test 4: Visits that are pending, rejected, or cancelled fail verification."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        req_obj = db.session.get(VisitRequest, req.id)
        
        # Rejected
        req_obj.status = VisitRequestStatus.REJECTED
        db.session.commit()
        res_rejected = GateService.verify_credential_or_reference(f"VMS:{raw_token}", security_user)
        assert res_rejected['valid'] is False
        assert res_rejected['status'] == VisitRequestStatus.REJECTED

        # Pending approval
        req_obj.status = VisitRequestStatus.PENDING_APPROVAL
        db.session.commit()
        res_pending = GateService.verify_credential_or_reference(f"VMS:{raw_token}", security_user)
        assert res_pending['valid'] is False
        assert res_pending['status'] == VisitRequestStatus.PENDING_APPROVAL


def test_atomic_check_in_consumes_credential_and_creates_session(app, db, security_user, approved_visit):
    """Test 5: Check-in atomically consumes credential, creates VisitSession, VisitEvent, and AuditLog."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        # Pre-condition: 0 active occupancy
        assert GateService.get_current_occupancy() == 0

        # Perform Check-In
        session, err = GateService.check_in(
            request_id=req.id,
            actor_user=security_user,
            notes="ID verified, temporary campus badge #42 issued",
            client_ip="192.168.1.100"
        )

        assert err is None
        assert session is not None
        assert session.status == VisitSessionStatus.ACTIVE
        assert session.checked_in_by_id == security_user.id
        assert session.checked_in_at is not None

        # Credential consumed
        cred_db = db.session.get(QRCredential, cred.id)
        assert cred_db.status == QRCredentialStatus.CONSUMED
        assert cred_db.consumed_at is not None

        # Event logged
        events = VisitEvent.query.filter_by(visit_session_id=session.id).all()
        assert len(events) == 1
        assert events[0].event_type == VisitEventType.CHECK_IN
        assert events[0].recorded_by_id == security_user.id
        assert events[0].get_metadata().get('notes') == "ID verified, temporary campus badge #42 issued"

        # AuditLog emitted
        audit = AuditLog.query.filter_by(action=AuditAction.CHECK_IN).first()
        assert audit is not None
        assert audit.actor_user_id == security_user.id
        assert audit.outcome == AuditOutcome.SUCCESS

        # Occupancy increased
        assert GateService.get_current_occupancy() == 1


def test_duplicate_check_in_rejected(app, db, security_user, approved_visit):
    """Test 6: Duplicate check-in while an active session exists is strictly rejected."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        # First check-in
        sess1, err1 = GateService.check_in(req.id, security_user)
        assert err1 is None

        # Second check-in attempt
        sess2, err2 = GateService.check_in(req.id, security_user)
        assert sess2 is None
        assert "already" in err2.lower()
        assert GateService.get_current_occupancy() == 1


def test_atomic_check_out_completes_session(app, db, security_user, approved_visit):
    """Test 7: Check-out completes the active session, creates event, and decrements occupancy."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        session, _ = GateService.check_in(req.id, security_user)
        assert GateService.get_current_occupancy() == 1

        # Check-out
        sess_out, err = GateService.check_out(
            session_id=session.id,
            actor_user=security_user,
            notes="Badge #42 returned",
            client_ip="192.168.1.100"
        )

        assert err is None
        assert sess_out.status == VisitSessionStatus.COMPLETED
        assert sess_out.checked_out_at is not None
        assert sess_out.checked_out_by_id == security_user.id

        # Occupancy returns to 0
        assert GateService.get_current_occupancy() == 0

        # Check-out event logged
        events = VisitEvent.query.filter_by(visit_session_id=session.id).all()
        event_types = [e.event_type for e in events]
        assert VisitEventType.CHECK_IN in event_types
        assert VisitEventType.CHECK_OUT in event_types

        # Check-out AuditLog
        audit = AuditLog.query.filter_by(action=AuditAction.CHECK_OUT).first()
        assert audit is not None
        assert audit.actor_user_id == security_user.id


def test_check_out_non_active_session_rejected(app, db, security_user, approved_visit):
    """Test 8: Checking out an already completed session fails safely."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        session, _ = GateService.check_in(req.id, security_user)
        GateService.check_out(session.id, security_user)

        # Re-check out
        sess_again, err = GateService.check_out(session.id, security_user)
        assert sess_again is None
        assert "Cannot check out session with status: COMPLETED" in err


def test_unauthorized_user_cannot_perform_gate_operations(app, db, faculty_user, approved_visit):
    """Test 9: Non-security/non-admin staff (e.g. Faculty) cannot check in or check out visitors."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        sess, err = GateService.check_in(req.id, faculty_user)
        assert sess is None
        assert "Unauthorized" in err

        res = GateService.verify_credential_or_reference(f"VMS:{raw_token}", faculty_user)
        assert res['valid'] is False
        assert res['status'] == 'UNAUTHORIZED'


def test_verification_detects_already_checked_in_state(app, db, security_user, approved_visit):
    """Test 10: Scanning credential for an already checked-in visitor flags ALREADY_CHECKED_IN with can_check_out=True."""
    req, cred, raw_token = approved_visit

    with app.app_context():
        # Check visitor in
        session, _ = GateService.check_in(req.id, security_user)

        # Scan credential again
        res = GateService.verify_credential_or_reference(f"VMS:{raw_token}", security_user)
        assert res['valid'] is True
        assert res['status'] == 'ALREADY_CHECKED_IN'
        assert res['can_check_in'] is False
        assert res['can_check_out'] is True
        assert res['session_id'] == session.id


def test_security_routes_authentication_and_authorization(client, security_user, faculty_user, approved_visit):
    """Test 11: Security endpoints enforce authentication and reject unauthorized roles with 403."""
    # 1. Unauthenticated redirect
    resp = client.get('/security/dashboard')
    assert resp.status_code == 302
    assert '/login' in resp.headers.get('Location', '')

    # 2. Faculty role rejected (403 Forbidden)
    client.post('/login', data={'identifier': faculty_user.username, 'password': 'Faculty@123'})
    resp = client.get('/security/dashboard')
    assert resp.status_code == 403

    resp = client.get('/security/scan')
    assert resp.status_code == 403

    resp = client.get('/security/occupancy')
    assert resp.status_code == 403

    # Logout faculty before logging in security
    client.post('/logout')

    # 3. Security role allowed (200 OK)
    client.post('/login', data={'identifier': security_user.username, 'password': 'Security@123'})
    resp = client.get('/security/dashboard')
    assert resp.status_code == 200

    resp = client.get('/security/scan')
    assert resp.status_code == 200

    resp = client.get('/security/occupancy')
    assert resp.status_code == 200

    resp = client.get('/security/emergency-list')
    assert resp.status_code == 200


def test_security_api_verify_and_check_in_endpoints(client, security_user, approved_visit):
    """Test 12: End-to-end HTTP verification and check-in via security endpoints."""
    req, cred, raw_token = approved_visit

    client.post('/login', data={'identifier': security_user.username, 'password': 'Security@123'})

    # 1. Get scan page and extract CSRF
    scan_page = client.get('/security/scan')
    csrf_token = extract_csrf_token(scan_page.data.decode('utf-8'))

    # 2. POST /security/verify
    verify_resp = client.post(
        '/security/verify',
        json={'credential': f"VMS:{raw_token}"},
        headers={'X-CSRFToken': csrf_token}
    )
    assert verify_resp.status_code == 200
    data = verify_resp.get_json()
    assert data['valid'] is True
    assert data['request_id'] == req.id
    assert data['visitor_details']['full_name'] == "Grace Hopper"

    # 3. POST /security/check-in
    check_in_resp = client.post(
        '/security/check-in',
        json={'request_id': req.id, 'notes': 'Gate 1 verified'},
        headers={'X-CSRFToken': csrf_token}
    )
    assert check_in_resp.status_code == 200
    ci_data = check_in_resp.get_json()
    assert ci_data['success'] is True
    assert 'session_id' in ci_data
    session_id = ci_data['session_id']

    # 4. Verify occupancy reflects active visitor
    occ_resp = client.get('/security/occupancy')
    assert occ_resp.status_code == 200
    assert b"Grace Hopper" in occ_resp.data

    # 5. POST /security/check-out
    check_out_resp = client.post(
        '/security/check-out',
        json={'session_id': session_id, 'notes': 'Gate 1 departure'},
        headers={'X-CSRFToken': csrf_token}
    )
    assert check_out_resp.status_code == 200
    co_data = check_out_resp.get_json()
    assert co_data['success'] is True


def test_emergency_list_logs_audit_and_shows_only_active_visitors(client, security_user, approved_visit):
    """Test 13: Emergency list renders active visitors, excludes completed visits, and emits audit event."""
    req, cred, raw_token = approved_visit

    client.post('/login', data={'identifier': security_user.username, 'password': 'Security@123'})

    # Check in Grace Hopper
    GateService.check_in(req.id, security_user)

    # View Emergency List
    resp = client.get('/security/emergency-list')
    assert resp.status_code == 200
    assert b"Grace Hopper" in resp.data
    assert b"Campus Emergency Visitor Evacuation List" in resp.data

    # Verify EMERGENCY_LIST_VIEWED audit log
    audit = AuditLog.query.filter_by(action=AuditAction.EMERGENCY_LIST_VIEWED).first()
    assert audit is not None
    assert audit.actor_user_id == security_user.id

    # Check out Grace Hopper
    active_sess = req.active_session
    GateService.check_out(active_sess.id, security_user)

    # Emergency list after check-out should exclude departed visitor
    resp2 = client.get('/security/emergency-list')
    assert resp2.status_code == 200
    assert b"Zero Active Visitors On Campus" in resp2.data
