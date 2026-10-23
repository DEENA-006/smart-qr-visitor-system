"""Unit and integration tests for secure QR token generation, delivery, and lifecycle (Milestone 3, Step 3)."""
from datetime import datetime, timezone, timedelta
import hashlib
import io
from unittest.mock import patch
import pytest
from PIL import Image
import zxingcpp

from app import create_app
from app.extensions import db
from app.models.user import User, UserRole
from app.models.visitor import Visitor
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    QRCredential,
    QRCredentialStatus,
)
from app.models.visit_type import VisitType
from app.models.audit_log import AuditLog, AuditAction, AuditOutcome
from app.services.qr_service import QRService
from app.services.approval_service import ApprovalService
from app.services.form_service import FormService
from app.services.rate_limiter import limiter


@pytest.fixture
def other_faculty_user(db):
    """Creates second faculty user for host-isolation and IDOR testing."""
    user = User(
        username='otherfaculty_qr',
        email='otherfaculty_qr@test.edu',
        full_name='Dr. Other Host',
        role=UserRole.FACULTY,
        department='Physics',
        is_active=True
    )
    user.set_password('Faculty@123')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def base_published_form(db, admin_user):
    """Creates and publishes a registration form for visit requests."""
    form, _ = FormService.create_form(
        name="Campus Visit Request Form",
        visit_type=VisitType.GENERAL,
        description="General visit registration",
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, actor_user=admin_user)
    return form


def create_test_request(
    db,
    form,
    host_user,
    full_name="Alice Visitor",
    email="alice@testcorp.com",
    phone="555-010-9999",
    status=VisitRequestStatus.PENDING_APPROVAL,
    planned_start_at=None,
    planned_end_at=None
):
    """Helper to create a visitor and associated visit request."""
    visitor = Visitor(
        public_reference=Visitor.generate_reference(),
        full_name=full_name,
        email=email,
        phone=phone,
        organization="Test Corporation"
    )
    db.session.add(visitor)
    db.session.commit()

    req = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=visitor.id,
        form_version_id=form.published_version.id,
        visit_type=VisitType.GENERAL,
        host_user_id=host_user.id if host_user else None,
        department=host_user.department if host_user else "General",
        purpose="Academic Collaboration Discussion",
        planned_start_at=planned_start_at,
        planned_end_at=planned_end_at,
        status=status
    )
    db.session.add(req)
    db.session.commit()
    return req


# 1. Token entropy/format and opaque payload
def test_token_entropy_format_and_opaque_payload():
    """Verify QR tokens use VMS: prefix, have 256-bit URL-safe entropy, and leak no PII."""
    token1 = QRService.generate_token()
    token2 = QRService.generate_token()

    assert token1.startswith("VMS:")
    assert token2.startswith("VMS:")
    assert token1 != token2
    assert len(token1) >= 47  # 'VMS:' (4) + 43 chars for urlsafe 32 bytes

    # Verify high randomness: repeated generation never duplicates
    tokens_set = {QRService.generate_token() for _ in range(50)}
    assert len(tokens_set) == 50

    # Ensure no PII substrings
    for sensitive in ["@example.com", "555-", "REQ-", "Alice", "testadmin"]:
        assert sensitive not in token1


# 2. Only eligible approved visits receive credentials
def test_only_eligible_approved_visits_receive_credentials(faculty_user, base_published_form):
    """Credentials cannot be issued for PENDING_APPROVAL, REJECTED, or CANCELLED requests."""
    # Pending request
    pending_req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.PENDING_APPROVAL)
    cred_p, token_p, err_p = QRService.issue_credential(pending_req.id, faculty_user)
    assert cred_p is None
    assert token_p is None
    assert "Request must be APPROVED" in err_p

    # Rejected request
    rejected_req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.REJECTED)
    cred_r, token_r, err_r = QRService.issue_credential(rejected_req.id, faculty_user)
    assert cred_r is None
    assert "Request must be APPROVED" in err_r

    # Approved request succeeds
    approved_req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred_a, token_a, err_a = QRService.issue_credential(approved_req.id, faculty_user)
    assert err_a is None
    assert cred_a is not None
    assert token_a is not None
    assert cred_a.status == QRCredentialStatus.ACTIVE


# 3. Raw tokens are not stored in the database
def test_raw_tokens_never_stored_in_database(faculty_user, base_published_form):
    """Database must store only the SHA-256 hash. The plaintext raw token must never be in DB."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred, raw_token, err = QRService.issue_credential(req.id, faculty_user)
    assert err is None

    # Inspect persisted QRCredential row
    db.session.refresh(cred)
    expected_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    assert cred.token_hash == expected_hash

    # Verify raw token is absent from database text columns
    assert raw_token not in repr(cred)
    audit_log = AuditLog.query.filter_by(action=AuditAction.QR_ISSUED, entity_reference=req.public_reference).first()
    assert audit_log is not None
    assert raw_token not in (audit_log.metadata_json or "")
    assert raw_token not in (audit_log.reason or "")


# 4. Correct token succeeds and tampered/unknown token fails
def test_token_validation_with_constant_time_comparison(faculty_user, base_published_form):
    """Valid raw token succeeds; tampered and unknown tokens are rejected."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred, raw_token, err = QRService.issue_credential(req.id, faculty_user)
    assert err is None

    # Exact token succeeds
    valid_cred, val_err = QRService.validate_token(raw_token)
    assert val_err is None
    assert valid_cred.id == cred.id

    # Tampered token fails
    tampered_char = 'X' if raw_token[-1] != 'X' else 'Y'
    tampered_token = raw_token[:-1] + tampered_char
    t_cred, t_err = QRService.validate_token(tampered_token)
    assert t_cred is None
    assert "Invalid or unrecognized" in t_err

    # Random unknown token fails
    u_cred, u_err = QRService.validate_token("VMS:completely_unknown_token_value_here_123456")
    assert u_cred is None
    assert "Invalid or unrecognized" in u_err

    # Empty and invalid format tokens fail
    assert QRService.validate_token("")[0] is None
    assert QRService.validate_token("INVALID_PREFIX:abc")[0] is None


# 5. Expiry and allowed visit-window enforcement
def test_expiry_and_visit_window_enforcement(faculty_user, base_published_form):
    """Credentials cannot be used after expires_at or before the allowed arrival window."""
    now = datetime.now(timezone.utc)
    future_start = now + timedelta(hours=3)
    future_end = now + timedelta(hours=6)

    req = create_test_request(
        db, base_published_form, faculty_user,
        status=VisitRequestStatus.APPROVED,
        planned_start_at=future_start,
        planned_end_at=future_end
    )
    cred, raw_token, err = QRService.issue_credential(req.id, faculty_user)
    assert err is None
    assert cred.expires_at == future_end

    # Early check: current time is 3 hours before start (> 60m buffer) -> Rejected
    early_usable, early_err = QRService.is_credential_usable(cred, target_time=now)
    assert early_usable is False
    assert "not started yet" in early_err.lower()

    # Within window: 30 minutes before start -> Allowed
    valid_time = future_start - timedelta(minutes=30)
    window_usable, window_err = QRService.is_credential_usable(cred, target_time=valid_time)
    assert window_usable is True
    assert window_err is None

    # After expiry: 1 minute past future_end -> Rejected
    after_expiry = future_end + timedelta(minutes=1)
    exp_usable, exp_err = QRService.is_credential_usable(cred, target_time=after_expiry)
    assert exp_usable is False
    assert "expired" in exp_err.lower()


# 6. Revoked credentials fail validation
def test_revoked_credentials_fail_validation(admin_user, faculty_user, base_published_form):
    """Revoking credential updates status to REVOKED and blocks subsequent validation."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred, raw_token, _ = QRService.issue_credential(req.id, faculty_user)

    # Revoke as Admin
    rev_cred, rev_err = QRService.revoke_credential(cred.id, actor_user=admin_user, reason="Security policy audit")
    assert rev_err is None
    assert rev_cred.status == QRCredentialStatus.REVOKED
    assert rev_cred.revoked_at is not None
    assert rev_cred.revoked_by_id == admin_user.id

    # Validation must now fail
    v_cred, v_err = QRService.validate_token(raw_token)
    assert v_cred is None
    assert "status: REVOKED" in v_err

    # Repeating revocation fails
    _, dup_err = QRService.revoke_credential(cred.id, actor_user=admin_user)
    assert "already been revoked" in dup_err


# 7. Reissue invalidates the prior credential
def test_reissue_invalidates_prior_credential(admin_user, faculty_user, base_published_form):
    """Reissuing revokes previous credential and issues a distinct usable new credential."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred1, token1, _ = QRService.issue_credential(req.id, faculty_user)

    # Reissue
    cred2, token2, err2 = QRService.reissue_credential(req.id, actor_user=admin_user, reason="Visitor lost QR pass")
    assert err2 is None
    assert cred2.id != cred1.id
    assert cred2.status == QRCredentialStatus.ACTIVE
    assert token2 != token1

    # Old credential is revoked
    db.session.refresh(cred1)
    assert cred1.status == QRCredentialStatus.REVOKED

    # Old token fails validation; new token passes
    assert QRService.validate_token(token1)[0] is None
    v_cred2, _ = QRService.validate_token(token2)
    assert v_cred2 is not None
    assert v_cred2.id == cred2.id

    # Verify only ONE active credential exists on request
    active_count = QRCredential.query.filter_by(visit_request_id=req.id, status=QRCredentialStatus.ACTIVE).count()
    assert active_count == 1


# 8. Failed transactions do not leave unintended usable credentials
def test_failed_reissue_transaction_rollback(admin_user, faculty_user, base_published_form):
    """If db.session.commit fails during reissue, all changes roll back safely."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred1, token1, _ = QRService.issue_credential(req.id, faculty_user)

    with patch.object(db.session, 'commit', side_effect=Exception("Database lock error")):
        cred2, token2, err2 = QRService.reissue_credential(req.id, actor_user=admin_user)
        assert cred2 is None
        assert "A database error occurred" in err2

    # Verify state rolled back: cred1 remains ACTIVE
    db.session.expire_all()
    reloaded_c1 = db.session.get(QRCredential, cred1.id)
    assert reloaded_c1.status == QRCredentialStatus.ACTIVE
    assert reloaded_c1.is_valid_now() is True


# 9. Duplicate issuance and retry behavior
def test_duplicate_issuance_prevented_when_active_exists(faculty_user, base_published_form):
    """Attempting to issue a credential when one is already active is safely rejected."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred1, token1, err1 = QRService.issue_credential(req.id, faculty_user)
    assert err1 is None

    # Second issuance attempt on same request
    cred2, token2, err2 = QRService.issue_credential(req.id, faculty_user)
    assert cred2 is None
    assert token2 is None
    assert "already exists" in err2


# 10. Unauthorized revocation or reissue is denied
def test_unauthorized_revocation_and_reissue_denied(
    client, faculty_user, other_faculty_user, security_user, base_published_form
):
    """Faculty cannot revoke/reissue other hosts' passes; security and public users cannot revoke/reissue."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred, _, _ = QRService.issue_credential(req.id, faculty_user)

    # 1. Foreign faculty member via service
    _, err_fac = QRService.revoke_credential(cred.id, actor_user=other_faculty_user)
    assert "not authorized" in err_fac

    _, _, err_fac_reissue = QRService.reissue_credential(req.id, actor_user=other_faculty_user)
    assert "not authorized" in err_fac_reissue

    # 2. Foreign faculty via route -> 403 Forbidden
    client.post('/login', data={'identifier': 'otherfaculty_qr', 'password': 'Faculty@123'})
    res_fac_post = client.post(f'/faculty/requests/{req.id}/revoke-qr')
    assert res_fac_post.status_code == 403

    # 3. Security user via route -> 403 Forbidden
    client.post('/login', data={'identifier': 'testsecurity', 'password': 'Security@123'})
    res_sec_post = client.post(f'/faculty/requests/{req.id}/reissue-qr')
    assert res_sec_post.status_code == 403
    res_sec_admin = client.post(f'/admin/visits/{req.id}/reissue-qr')
    assert res_sec_admin.status_code == 403

    # 4. Unauthenticated user -> redirected to login
    client.post('/logout')
    res_unauth = client.post(f'/admin/visits/{req.id}/revoke-qr')
    assert res_unauth.status_code == 302
    assert '/login' in res_unauth.headers['Location']


# 11. Visitor pass privacy, response headers, and unavailable states
def test_visitor_pass_privacy_headers_and_unavailable_states(client, faculty_user, base_published_form):
    """Pass page enforces no-store headers, excludes PII, and handles all lifecycle states cleanly."""
    # A. Approved visit with active pass
    req_active = create_test_request(
        db, base_published_form, faculty_user,
        full_name="Bob Visitor",
        email="bob.private@domain.com",
        phone="555-999-8888",
        status=VisitRequestStatus.APPROVED
    )
    cred, raw_token, _ = QRService.issue_credential(req_active.id, faculty_user)

    res_active = client.get(f'/visitors/pass/{req_active.public_reference}')
    assert res_active.status_code == 200

    # Strict Cache-Control headers
    assert "no-store" in res_active.headers.get('Cache-Control', '')
    assert "no-cache" in res_active.headers.get('Cache-Control', '')

    # Privacy: Name is shown, but email, phone, and raw token are NOT in HTML
    assert b"Bob Visitor" in res_active.data
    assert b"bob.private@domain.com" not in res_active.data
    assert b"555-999-8888" not in res_active.data
    assert raw_token.encode() not in res_active.data
    assert b"Authorized" in res_active.data
    assert b"qr.png" in res_active.data

    # Test dynamic QR image serving
    res_qr_img = client.get(f'/visitors/pass/{req_active.public_reference}/qr.png')
    assert res_qr_img.status_code == 200
    assert res_qr_img.content_type == 'image/png'
    assert "no-store" in res_qr_img.headers.get('Cache-Control', '')

    # B. Pending visit: No QR code, shows pending notice
    req_pending = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.PENDING_APPROVAL)
    res_pending = client.get(f'/visitors/pass/{req_pending.public_reference}')
    assert res_pending.status_code == 200
    assert b"Pending Review" in res_pending.data
    assert b"qr.png" not in res_pending.data
    # Direct QR image request must 404
    assert client.get(f'/visitors/pass/{req_pending.public_reference}/qr.png').status_code == 404

    # C. Rejected visit: No QR code, shows rejected notice
    req_rejected = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.REJECTED)
    res_rejected = client.get(f'/visitors/pass/{req_rejected.public_reference}')
    assert res_rejected.status_code == 200
    assert b"Request Rejected" in res_rejected.data
    assert client.get(f'/visitors/pass/{req_rejected.public_reference}/qr.png').status_code == 404


# 12. QR image decoding reproduces expected payload
def test_qr_image_decoding_reproduces_expected_payload(faculty_user, base_published_form):
    """The rendered QR PNG image must be fully decodable back to the exact raw token payload."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred, raw_token, _ = QRService.issue_credential(req.id, faculty_user)

    # Retrieve generated image bytes
    img_bytes = QRService.get_qr_image_bytes(cred.token_hash)
    assert img_bytes is not None
    assert img_bytes[:8] == b'\x89PNG\r\n\x1a\n'

    # Decode with zxingcpp
    pil_image = Image.open(io.BytesIO(img_bytes))
    decoded_barcodes = zxingcpp.read_barcodes(pil_image)
    assert len(decoded_barcodes) >= 1
    assert decoded_barcodes[0].text == raw_token


# 13. Approval workflow automatically issues valid QR credential
def test_approval_workflow_automatically_issues_qr_credential(client, admin_user, faculty_user, base_published_form):
    """Approving a request via ApprovalService.approve_request atomically issues an active QR credential."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.PENDING_APPROVAL)

    approved_req, err = ApprovalService.approve_request(req.id, actor_user=admin_user)
    assert err is None
    assert approved_req.status == VisitRequestStatus.APPROVED

    # Verify active credential created automatically
    db.session.refresh(req)
    active_cred = req.active_credential
    assert active_cred is not None
    assert active_cred.status == QRCredentialStatus.ACTIVE
    assert active_cred.is_valid_now() is True

    # Verify QR image file exists on disk
    img_bytes = QRService.get_qr_image_bytes(active_cred.token_hash)
    assert img_bytes is not None

    # Verify both VISIT_APPROVED and QR_ISSUED audit logs were emitted
    audit_approval = AuditLog.query.filter_by(action=AuditAction.VISIT_APPROVED, entity_reference=req.public_reference).first()
    audit_qr = AuditLog.query.filter_by(action=AuditAction.QR_ISSUED, entity_reference=req.public_reference).first()
    assert audit_approval is not None
    assert audit_qr is not None


# 14. CSRF and rate limiting on staff QR management endpoints
def test_csrf_and_rate_limiting_on_qr_endpoints(client, admin_user, faculty_user, base_published_form, app):
    """CSRF tokens required and sliding-window rate limiting enforced on QR reissue/revoke."""
    req = create_test_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred, _, _ = QRService.issue_credential(req.id, faculty_user)

    # CSRF protection when enabled
    csrf_app = create_app('testing')
    csrf_app.config['WTF_CSRF_ENABLED'] = True
    csrf_client = csrf_app.test_client()

    r_post_no_csrf = csrf_client.post(f'/admin/visits/{req.id}/reissue-qr')
    assert r_post_no_csrf.status_code == 400
    assert b"CSRF" in r_post_no_csrf.data or b"Bad Request" in r_post_no_csrf.data

    # Rate limiting on POST endpoints
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_APPROVAL'] = '2/minute'
    limiter.reset()

    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})

    try:
        # First 2 requests within limit
        r1 = client.post(f'/admin/visits/{req.id}/reissue-qr', follow_redirects=True)
        assert r1.status_code == 200

        r2 = client.post(f'/admin/visits/{req.id}/reissue-qr', follow_redirects=True)
        assert r2.status_code == 200

        # 3rd request exceeds limit -> 429
        r3 = client.post(f'/admin/visits/{req.id}/reissue-qr')
        assert r3.status_code == 429
        assert 'Retry-After' in r3.headers
    finally:
        app.config['RATE_LIMIT_ENABLED'] = False
        limiter.reset()
