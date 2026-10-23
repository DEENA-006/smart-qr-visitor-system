"""Unit and integration tests for visitor request approval subsystem (Milestone 3, Step 2)."""
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from app import create_app
from app.extensions import db
from app.models.user import User, UserRole
from app.models.visitor import Visitor
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    ApprovalDecision,
    ApprovalDecisionType,
)
from app.models.visit_type import VisitType
from app.models.audit_log import AuditLog, AuditAction, AuditOutcome
from app.services.approval_service import ApprovalService
from app.services.form_service import FormService
from app.services.rate_limiter import limiter


@pytest.fixture
def other_faculty_user(db):
    """Creates a second faculty user for IDOR testing."""
    user = User(
        username='otherfaculty',
        email='otherfaculty@test.edu',
        full_name='Dr. Other Faculty',
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
    """Creates and publishes a basic registration form for requests."""
    form, _ = FormService.create_form(
        name="Campus Visit Request Form",
        visit_type=VisitType.GENERAL,
        description="General visit registration",
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, actor_user=admin_user)
    return form


def create_test_request(db, form, host_user, full_name="John Visitor", email="john@example.com", status=VisitRequestStatus.PENDING_APPROVAL):
    """Helper to create a visitor and associated visit request."""
    visitor = Visitor(
        public_reference=Visitor.generate_reference(),
        full_name=full_name,
        email=email,
        phone="555-010-1234",
        organization="Tech Corp"
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
        purpose="Industry Collaboration",
        status=status
    )
    db.session.add(req)
    db.session.commit()
    return req


# 1. Administrator can approve an eligible request
def test_admin_can_approve_eligible_request(client, admin_user, faculty_user, base_published_form):
    """Admin can approve any eligible PENDING_APPROVAL request via POST /admin/visits/<id>/approve."""
    req = create_test_request(db, base_published_form, faculty_user)

    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
    res = client.post(f'/admin/visits/{req.id}/approve', follow_redirects=True)
    assert res.status_code == 200
    assert b"has been approved" in res.data

    db.session.refresh(req)
    assert req.status == VisitRequestStatus.APPROVED
    assert req.approved_at is not None
    assert req.decided_by_id == admin_user.id
    assert req.rejection_reason is None

    # Verify ApprovalDecision
    decision = req.decisions.first()
    assert decision is not None
    assert decision.decision == ApprovalDecisionType.APPROVED
    assert decision.actor_user_id == admin_user.id
    assert decision.reason is None

    # Verify AuditLog
    log = AuditLog.query.filter_by(
        action=AuditAction.VISIT_APPROVED,
        entity_reference=req.public_reference
    ).first()
    assert log is not None
    assert log.actor_user_id == admin_user.id
    assert log.outcome == AuditOutcome.SUCCESS


# 2. Administrator can reject an eligible request
def test_admin_can_reject_eligible_request(client, admin_user, faculty_user, base_published_form):
    """Admin can reject an eligible PENDING_APPROVAL request with a valid reason."""
    req = create_test_request(db, base_published_form, faculty_user)

    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
    res = client.post(
        f'/admin/visits/{req.id}/reject',
        data={'reason': 'Facility under scheduled maintenance.'},
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b"has been rejected" in res.data

    db.session.refresh(req)
    assert req.status == VisitRequestStatus.REJECTED
    assert req.rejected_at is not None
    assert req.decided_by_id == admin_user.id
    assert req.rejection_reason == 'Facility under scheduled maintenance.'

    # Verify ApprovalDecision
    decision = req.decisions.first()
    assert decision is not None
    assert decision.decision == ApprovalDecisionType.REJECTED
    assert decision.actor_user_id == admin_user.id
    assert decision.reason == 'Facility under scheduled maintenance.'

    # Verify AuditLog
    log = AuditLog.query.filter_by(
        action=AuditAction.VISIT_REJECTED,
        entity_reference=req.public_reference
    ).first()
    assert log is not None
    assert log.actor_user_id == admin_user.id
    assert log.reason == 'Facility under scheduled maintenance.'


# 3. Faculty can approve and reject requests hosted by themselves
def test_faculty_can_approve_and_reject_own_requests(client, faculty_user, base_published_form):
    """Faculty member can approve and reject requests assigned to them as host."""
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    # Approve request 1
    req1 = create_test_request(db, base_published_form, faculty_user, full_name="Visitor One")
    res1 = client.post(f'/faculty/requests/{req1.id}/approve', follow_redirects=True)
    assert res1.status_code == 200
    assert b"has been approved" in res1.data

    db.session.refresh(req1)
    assert req1.status == VisitRequestStatus.APPROVED
    assert req1.decided_by_id == faculty_user.id

    # Reject request 2
    req2 = create_test_request(db, base_published_form, faculty_user, full_name="Visitor Two")
    res2 = client.post(
        f'/faculty/requests/{req2.id}/reject',
        data={'reason': 'Host unavailable due to conference attendance.'},
        follow_redirects=True
    )
    assert res2.status_code == 200
    assert b"has been rejected" in res2.data

    db.session.refresh(req2)
    assert req2.status == VisitRequestStatus.REJECTED
    assert req2.decided_by_id == faculty_user.id
    assert req2.rejection_reason == 'Host unavailable due to conference attendance.'


# 4. Faculty cannot decide requests hosted by another faculty member
def test_faculty_cannot_decide_other_faculty_requests(client, faculty_user, other_faculty_user, base_published_form):
    """Faculty cannot approve or reject requests where host_user_id != authenticated faculty user ID (IDOR blocked)."""
    req = create_test_request(db, base_published_form, other_faculty_user, full_name="Other Host Guest")

    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    # Attempt to approve other faculty's request via POST -> 403 Forbidden
    res_approve = client.post(f'/faculty/requests/{req.id}/approve')
    assert res_approve.status_code == 403

    # Attempt to reject other faculty's request via POST -> 403 Forbidden
    res_reject = client.post(f'/faculty/requests/{req.id}/reject', data={'reason': 'Should not work'})
    assert res_reject.status_code == 403

    # Test service directly
    can_review, auth_err = ApprovalService.can_user_review_request(faculty_user, req)
    assert can_review is False
    assert "only authorized to review visitor requests assigned to you" in auth_err

    svc_req, svc_err = ApprovalService.approve_request(req.id, faculty_user)
    assert svc_req is None
    assert "only authorized to review visitor requests assigned to you" in svc_err

    # Ensure status remained pending
    db.session.refresh(req)
    assert req.status == VisitRequestStatus.PENDING_APPROVAL
    assert req.decisions.count() == 0

    # Ensure UNAUTHORIZED_ACCESS audit log logged
    unauth_log = AuditLog.query.filter_by(
        action=AuditAction.UNAUTHORIZED_ACCESS,
        entity_reference=req.public_reference
    ).first()
    assert unauth_log is not None
    assert unauth_log.actor_user_id == faculty_user.id


# 5. Security staff cannot approve or reject requests
def test_security_staff_cannot_approve_or_reject_requests(client, security_user, faculty_user, base_published_form):
    """Security staff cannot approve or reject requests on faculty or admin routes or via service."""
    req = create_test_request(db, base_published_form, faculty_user)

    client.post('/login', data={'identifier': 'testsecurity', 'password': 'Security@123'})

    # Route access blocked with 403
    assert client.post(f'/faculty/requests/{req.id}/approve').status_code == 403
    assert client.post(f'/faculty/requests/{req.id}/reject', data={'reason': 'test'}).status_code == 403
    assert client.post(f'/admin/visits/{req.id}/approve').status_code == 403
    assert client.post(f'/admin/visits/{req.id}/reject', data={'reason': 'test'}).status_code == 403

    # Service-level authorization check
    can_review, auth_err = ApprovalService.can_user_review_request(security_user, req)
    assert can_review is False
    assert "not authorized to review visitor requests" in auth_err

    svc_req, svc_err = ApprovalService.approve_request(req.id, security_user)
    assert svc_req is None
    assert "not authorized to review visitor requests" in svc_err

    db.session.refresh(req)
    assert req.status == VisitRequestStatus.PENDING_APPROVAL
    assert req.decisions.count() == 0


# 6. Unauthenticated users cannot access protected review actions
def test_unauthenticated_users_cannot_access_review_actions(client, faculty_user, base_published_form):
    """Unauthenticated users are redirected to login and rejected by service."""
    req = create_test_request(db, base_published_form, faculty_user)

    for url in [
        '/faculty/requests',
        '/admin/visits',
        f'/faculty/requests/{req.id}/approve',
        f'/faculty/requests/{req.id}/reject',
        f'/admin/visits/{req.id}/approve',
        f'/admin/visits/{req.id}/reject',
    ]:
        res = client.post(url) if 'approve' in url or 'reject' in url else client.get(url)
        assert res.status_code == 302
        assert '/login' in res.headers['Location']

    # Service check for None or unauthenticated user
    can_review, err = ApprovalService.can_user_review_request(None, req)
    assert can_review is False
    assert "Authentication required" in err


# 7. Requests that are pending can be decided only once
def test_pending_request_decided_only_once(admin_user, faculty_user, base_published_form):
    """Once a request is decided, subsequent decision attempts are rejected without overwriting."""
    req = create_test_request(db, base_published_form, faculty_user)

    # First decision: Approved
    approved_req, err = ApprovalService.approve_request(req.id, admin_user)
    assert err is None
    assert approved_req.status == VisitRequestStatus.APPROVED
    original_approved_at = approved_req.approved_at

    # Second decision attempt: Approve again -> Rejected
    dup_approved, dup_err = ApprovalService.approve_request(req.id, admin_user)
    assert dup_approved is None
    assert "already been approved" in dup_err

    # Conflicting decision attempt: Reject after approval -> Rejected
    conflict_req, conflict_err = ApprovalService.reject_request(req.id, admin_user, reason="Changing my mind")
    assert conflict_req is None
    assert "already been approved and cannot be rejected" in conflict_err

    # Confirm original state and single decision record preserved
    db.session.refresh(req)
    assert req.status == VisitRequestStatus.APPROVED
    assert req.approved_at == original_approved_at
    assert req.rejection_reason is None
    assert req.decisions.count() == 1


# 8. Already approved, rejected, or otherwise ineligible requests cannot be decided again
def test_already_rejected_or_ineligible_request_cannot_be_decided(admin_user, faculty_user, base_published_form):
    """Rejected or non-pending status requests cannot transition again."""
    req = create_test_request(db, base_published_form, faculty_user)

    # First decision: Reject
    rejected_req, err = ApprovalService.reject_request(req.id, admin_user, reason="Initial rejection")
    assert err is None
    assert rejected_req.status == VisitRequestStatus.REJECTED

    # Attempt to approve rejected request
    app_res, app_err = ApprovalService.approve_request(req.id, admin_user)
    assert app_res is None
    assert "already been rejected and cannot be approved" in app_err

    # Attempt to reject again
    rej_res, rej_err = ApprovalService.reject_request(req.id, admin_user, reason="Second rejection")
    assert rej_res is None
    assert "already been rejected" in rej_err

    # Ineligible statuses (e.g. CANCELLED, EXPIRED)
    req.status = VisitRequestStatus.CANCELLED
    db.session.commit()

    c_app, c_app_err = ApprovalService.approve_request(req.id, admin_user)
    assert c_app is None
    assert "Cannot approve visit request in status 'CANCELLED'" in c_app_err

    c_rej, c_rej_err = ApprovalService.reject_request(req.id, admin_user, reason="Cancel test")
    assert c_rej is None
    assert "Cannot reject visit request in status 'CANCELLED'" in c_rej_err


# 9. Invalid and excessively long rejection reasons are handled safely
def test_rejection_reason_validation(admin_user, faculty_user, base_published_form):
    """Rejection reasons must be non-empty, stripped, and at most 255 characters."""
    req = create_test_request(db, base_published_form, faculty_user)

    # Empty string
    r1, err1 = ApprovalService.reject_request(req.id, admin_user, reason="")
    assert r1 is None
    assert "rejection reason is required" in err1.lower()

    # Whitespace only
    r2, err2 = ApprovalService.reject_request(req.id, admin_user, reason="   \t\n  ")
    assert r2 is None
    assert "rejection reason is required" in err2.lower()

    # None
    r3, err3 = ApprovalService.reject_request(req.id, admin_user, reason=None)
    assert r3 is None
    assert "rejection reason is required" in err3.lower()

    # Over 255 characters (256 characters)
    too_long = "X" * 256
    r4, err4 = ApprovalService.reject_request(req.id, admin_user, reason=too_long)
    assert r4 is None
    assert "must not exceed 255 characters" in err4

    # Exact boundary (255 characters) succeeds
    exact_limit = "A" * 255
    r5, err5 = ApprovalService.reject_request(req.id, admin_user, reason=exact_limit)
    assert err5 is None
    assert r5.status == VisitRequestStatus.REJECTED
    assert r5.rejection_reason == exact_limit


# 10. Approval fields, decision history, and audit logs remain consistent
def test_approval_fields_decision_history_and_audit_consistency(admin_user, faculty_user, base_published_form):
    """Verifies complete consistency across VisitRequest, ApprovalDecision, and AuditLog."""
    # Test approval consistency
    req_a = create_test_request(db, base_published_form, faculty_user, full_name="Audited Approved")
    res_a, _ = ApprovalService.approve_request(req_a.id, admin_user, actor_ip="10.0.0.1")

    db.session.refresh(req_a)
    assert req_a.status == VisitRequestStatus.APPROVED
    assert req_a.approved_at is not None
    assert req_a.rejected_at is None
    assert req_a.decided_by_id == admin_user.id
    assert req_a.rejection_reason is None

    dec_a = req_a.decisions.first()
    assert dec_a.decision == ApprovalDecisionType.APPROVED
    assert dec_a.actor_user_id == admin_user.id
    assert dec_a.reason is None
    assert dec_a.created_at is not None

    log_a = AuditLog.query.filter_by(
        action=AuditAction.VISIT_APPROVED,
        entity_reference=req_a.public_reference
    ).first()
    assert log_a is not None
    assert log_a.actor_user_id == admin_user.id
    assert log_a.ip_address == "10.0.0.1"
    assert log_a.outcome == AuditOutcome.SUCCESS

    # Test rejection consistency
    req_r = create_test_request(db, base_published_form, faculty_user, full_name="Audited Rejected")
    res_r, _ = ApprovalService.reject_request(req_r.id, admin_user, reason="Lab capacity reached", actor_ip="10.0.0.2")

    db.session.refresh(req_r)
    assert req_r.status == VisitRequestStatus.REJECTED
    assert req_r.rejected_at is not None
    assert req_r.approved_at is None
    assert req_r.decided_by_id == admin_user.id
    assert req_r.rejection_reason == "Lab capacity reached"

    dec_r = req_r.decisions.first()
    assert dec_r.decision == ApprovalDecisionType.REJECTED
    assert dec_r.actor_user_id == admin_user.id
    assert dec_r.reason == "Lab capacity reached"

    log_r = AuditLog.query.filter_by(
        action=AuditAction.VISIT_REJECTED,
        entity_reference=req_r.public_reference
    ).first()
    assert log_r is not None
    assert log_r.actor_user_id == admin_user.id
    assert log_r.reason == "Lab capacity reached"
    assert log_r.ip_address == "10.0.0.2"


# 11. Database changes roll back if the transaction fails
def test_database_rollback_on_transaction_failure(admin_user, faculty_user, base_published_form):
    """If db.session.commit fails, changes to VisitRequest, ApprovalDecision, and AuditLog roll back."""
    req = create_test_request(db, base_published_form, faculty_user)

    with patch.object(db.session, 'commit', side_effect=Exception("Database lock failure")):
        res, err = ApprovalService.approve_request(req.id, admin_user)
        assert res is None
        assert "A database error occurred" in err

    # Expire and refresh session to verify database state
    db.session.expire_all()
    reloaded_req = db.session.get(VisitRequest, req.id)
    assert reloaded_req.status == VisitRequestStatus.PENDING_APPROVAL
    assert reloaded_req.approved_at is None
    assert reloaded_req.decided_by_id is None
    assert reloaded_req.decisions.count() == 0

    # Ensure no approval audit log was committed
    log = AuditLog.query.filter_by(
        action=AuditAction.VISIT_APPROVED,
        entity_reference=reloaded_req.public_reference
    ).first()
    assert log is None


# 12. CSRF and rate-limiting behavior
def test_rate_limiting_on_approval_endpoints(client, admin_user, faculty_user, base_published_form, app):
    """Verify that approval endpoints enforce sliding-window rate limiting when enabled."""
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_APPROVAL'] = '2/minute'
    limiter.reset()

    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})

    req1 = create_test_request(db, base_published_form, faculty_user, full_name="Guest 1")
    req2 = create_test_request(db, base_published_form, faculty_user, full_name="Guest 2")
    req3 = create_test_request(db, base_published_form, faculty_user, full_name="Guest 3")

    try:
        # First 2 requests within limit
        r1 = client.post(f'/admin/visits/{req1.id}/approve', follow_redirects=True)
        assert r1.status_code == 200

        r2 = client.post(f'/admin/visits/{req2.id}/approve', follow_redirects=True)
        assert r2.status_code == 200

        # 3rd request exceeds limit -> 429 Too Many Requests
        r3 = client.post(f'/admin/visits/{req3.id}/approve')
        assert r3.status_code == 429
        assert 'Retry-After' in r3.headers
    finally:
        app.config['RATE_LIMIT_ENABLED'] = False
        limiter.reset()


def test_csrf_protection_on_approval_endpoints(faculty_user, base_published_form):
    """Verify that POST requests to approval endpoints without CSRF token return 400 when CSRF is enabled."""
    csrf_app = create_app('testing')
    csrf_app.config['WTF_CSRF_ENABLED'] = True
    client = csrf_app.test_client()

    # Even unauthenticated, CSRF check executes on POST before view
    r_fac_app = client.post('/faculty/requests/1/approve')
    assert r_fac_app.status_code == 400
    assert b"CSRF" in r_fac_app.data or b"Bad Request" in r_fac_app.data

    r_admin_app = client.post('/admin/visits/1/approve')
    assert r_admin_app.status_code == 400
    assert b"CSRF" in r_admin_app.data or b"Bad Request" in r_admin_app.data


# 13. UI and list view rendering
def test_faculty_requests_page_renders(client, faculty_user, base_published_form):
    """Faculty review interface renders their hosted requests with status counts."""
    req = create_test_request(db, base_published_form, faculty_user, full_name="UI Guest")

    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
    res = client.get('/faculty/requests')
    assert res.status_code == 200
    assert b"Visitor Requests Review" in res.data
    assert b"UI Guest" in res.data
    assert req.public_reference.encode() in res.data
    assert b"Approve" in res.data
    assert b"Reject" in res.data


def test_admin_visits_page_renders(client, admin_user, faculty_user, base_published_form):
    """Admin review interface renders cross-campus requests with status and host filters."""
    req = create_test_request(db, base_published_form, faculty_user, full_name="Admin UI Guest")

    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
    res = client.get('/admin/visits')
    assert res.status_code == 200
    assert b"Campus Visitor Requests" in res.data
    assert b"Admin UI Guest" in res.data
    assert req.public_reference.encode() in res.data
    assert b"All Statuses" in res.data
    assert b"All Categories" in res.data
    assert b"All Campus Hosts" in res.data


def test_admin_visits_page_renders_with_visitor_photo(client, admin_user, faculty_user, base_published_form):
    """Admin review interface correctly renders visitor records that include an uploaded photo without BuildError."""
    req = create_test_request(db, base_published_form, faculty_user, full_name="Photo Visitor Guest")
    req.photo_filename = 'photo_abc123.jpg'
    db.session.commit()

    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})

    # Test both /admin/visits and /admin/requests aliases
    res1 = client.get('/admin/visits')
    assert res1.status_code == 200
    assert b"Photo Visitor Guest" in res1.data
    assert b"photo_abc123.jpg" in res1.data

    res2 = client.get('/admin/requests')
    assert res2.status_code == 200
    assert b"Photo Visitor Guest" in res2.data
    assert b"photo_abc123.jpg" in res2.data


def test_faculty_requests_page_renders_with_visitor_photo(client, faculty_user, base_published_form):
    """Faculty review interface correctly renders visitor records that include an uploaded photo without BuildError."""
    req = create_test_request(db, base_published_form, faculty_user, full_name="Faculty Photo Guest")
    req.photo_filename = 'faculty_photo_xyz.jpg'
    db.session.commit()

    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
    res = client.get('/faculty/requests')
    assert res.status_code == 200
    assert b"Faculty Photo Guest" in res.data
    assert b"faculty_photo_xyz.jpg" in res.data
