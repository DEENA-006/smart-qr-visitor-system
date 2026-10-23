import json
from datetime import datetime, timezone, timedelta
import pytest
from app.models.user import User, UserRole
from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
from app.models.visit_type import VisitType
from app.models.visit import VisitRequest, VisitRequestStatus, QRCredentialStatus
from app.services.form_service import FormService
from app.services.duplicate_service import DuplicateService, DuplicateRiskLevel
from app.services.registration_service import RegistrationService
from app.services.approval_service import ApprovalService
from app.services.qr_service import QRService
from app.services.lookup_service import LookupService
from app.services.gate_service import GateService


@pytest.fixture
def other_faculty_user(db):
    """Creates a second faculty user for cross-authorization tests."""
    user = User(
        username='otherfaculty',
        email='otherfaculty@test.edu',
        full_name='Other Faculty Member',
        role=UserRole.FACULTY,
        department='Physics',
        is_active=True
    )
    user.set_password('Faculty@123')
    db.session.add(user)
    db.session.commit()
    return user


def test_admin_creates_publishes_unpublishes_and_previews_form(client, auth_client, admin_user):
    """Test 1: Admin creates, publishes, unpublishes, previews form, and verifies public token."""
    auth_client.login('testadmin', 'Admin@123')

    # Create new form
    res = client.post('/admin/forms', data={
        'name': 'Special Campus Visitor Form',
        'visit_type': VisitType.OFFICIAL,
        'description': 'Form for visiting researchers'
    }, follow_redirects=True)
    assert res.status_code == 200

    form = RegistrationForm.query.filter_by(name='Special Campus Visitor Form').first()
    assert form is not None
    assert form.public_token is not None
    assert form.public_token.startswith('FORM-')

    v1 = form.versions.first()
    assert v1.status == FormVersionStatus.DRAFT

    # Publish form version
    res = client.post(f'/admin/forms/{form.id}/versions/{v1.id}/publish', follow_redirects=True)
    assert res.status_code == 200
    assert v1.status == FormVersionStatus.PUBLISHED

    # Preview form
    preview_res = client.get(f'/admin/forms/{form.id}/versions/{v1.id}/preview')
    assert preview_res.status_code == 200
    assert b"Form Preview Mode" in preview_res.data
    assert b"Preview Mode (Submissions Disabled)" in preview_res.data

    # Unpublish form version
    unpub_res = client.post(f'/admin/forms/{form.id}/versions/{v1.id}/unpublish', follow_redirects=True)
    assert unpub_res.status_code == 200
    assert v1.status == FormVersionStatus.DRAFT


def test_visitor_public_form_token_access_and_submission(client, db, faculty_user, admin_user):
    """Test 2: Visitor accesses published form via public token and successfully submits."""
    form, err = FormService.create_form(
        name='Public Research Lecture',
        visit_type=VisitType.GENERAL,
        description='Register for public seminar',
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    public_token = form.public_token
    assert public_token is not None

    # Visitor opens form using public token
    res = client.get(f'/register/{public_token}')
    assert res.status_code == 200
    assert b"Public Research Lecture" in res.data

    # Visitor submits registration
    now = datetime.now(timezone.utc)
    arrival = (now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
    departure = (now + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M')

    post_res = client.post(f'/register/{public_token}', data={
        'full_name': 'Alice Wonder',
        'email': 'alice@example.com',
        'phone': '1234567890',
        'organization': 'Wonderland Tech',
        'host_user_id': faculty_user.id,
        'purpose': 'Attending research seminar',
        'planned_start_at': arrival,
        'planned_end_at': departure,
        'dyn__purpose_detail': 'Interested in quantum computing'
    }, follow_redirects=True)

    assert post_res.status_code == 200
    assert b"Registration Request Submitted!" in post_res.data
    assert b"Submitted" in post_res.data


def test_validation_failures(client, db, admin_user, faculty_user):
    """Test 3: Required field and server-side validation failures."""
    form, _ = FormService.create_form(
        name='Validation Test Form',
        visit_type=VisitType.GENERAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    # Missing full name (less than 2 chars)
    res = client.post(f'/register/{form.public_token}', data={
        'full_name': 'A',
        'host_user_id': faculty_user.id,
        'purpose': 'Test'
    }, follow_redirects=True)
    assert b"Full name is required" in res.data

    # Missing host
    res = client.post(f'/register/{form.public_token}', data={
        'full_name': 'Alice Smith',
        'purpose': 'Test'
    }, follow_redirects=True)
    assert b"A host must be selected" in res.data


def test_unpublished_and_nonexistent_form_tokens_denied(client, db, admin_user):
    """Test 4: Unpublished and nonexistent form tokens are denied (404)."""
    # Nonexistent token
    res = client.get('/register/FORM-nonexistent_token_12345')
    assert res.status_code == 404

    # Unpublished draft form
    form, _ = FormService.create_form(
        name='Draft Only Form',
        visit_type=VisitType.CONTRACTOR,
        creator_user=admin_user
    )
    res = client.get(f'/register/{form.public_token}')
    assert res.status_code == 404


def test_duplicate_detection_evaluation(db, admin_user, faculty_user):
    """Test 5 & 6: 4-tier duplicate risk policy evaluates duplicates properly."""
    form, _ = FormService.create_form(
        name='Duplicate Check Form',
        visit_type=VisitType.OFFICIAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    now = datetime.now(timezone.utc)
    arrival = now + timedelta(hours=3)

    # Initial submission
    req1, err = RegistrationService.register_visitor(
        visit_type=VisitType.OFFICIAL,
        full_name='Bob Duplicate',
        email='bob@example.com',
        phone='9876543210',
        host_user_id=faculty_user.id,
        purpose='Initial Project Discussion',
        planned_start_at=arrival,
        dynamic_responses={'purpose_detail': 'Discussion'}
    )
    assert err is None
    assert req1.is_possible_duplicate is False

    # Second submission with exact same phone and email (High-confidence duplicate)
    eval_result = DuplicateService.evaluate_registration(
        phone='9876543210',
        email='bob@example.com',
        full_name='Bob Duplicate',
        planned_start_at=arrival
    )
    assert eval_result['risk_level'] == DuplicateRiskLevel.HIGH_CONFIDENCE_DUPLICATE
    assert eval_result['is_flagged'] is True

    # Third submission with only phone match (Possible duplicate)
    eval_possible = DuplicateService.evaluate_registration(
        phone='9876543210',
        email='different_bob@example.com',
        full_name='Different Bob',
        planned_start_at=arrival
    )
    assert eval_possible['risk_level'] == DuplicateRiskLevel.POSSIBLE_DUPLICATE
    assert eval_possible['is_flagged'] is True

    # Legitimate non-duplicate
    eval_clean = DuplicateService.evaluate_registration(
        phone='5551234567',
        email='clean@example.com',
        full_name='Clean Visitor',
        planned_start_at=arrival
    )
    assert eval_clean['risk_level'] == DuplicateRiskLevel.NONE
    assert eval_clean['is_flagged'] is False


def test_suspicious_submission_flagging(db, admin_user, faculty_user):
    """Test 7: Suspicious submissions (recent rejection within 7 days) are flagged."""
    form, _ = FormService.create_form(
        name='Suspicious Test Form',
        visit_type=VisitType.GENERAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    now = datetime.now(timezone.utc)

    # Create a rejected request for this visitor
    req, _ = RegistrationService.register_visitor(
        visit_type=VisitType.GENERAL,
        full_name='Suspicious Visitor',
        email='suspicious@test.com',
        phone='1112223333',
        host_user_id=faculty_user.id,
        purpose='Will be rejected',
        planned_start_at=now + timedelta(hours=2),
        dynamic_responses={'purpose_detail': 'Test'}
    )
    ApprovalService.reject_request(req.id, faculty_user, reason='Security policy denial')

    # Evaluate a new submission from the same phone
    eval_res = DuplicateService.evaluate_registration(
        phone='1112223333',
        email='other_email@test.com',
        full_name='Suspicious Visitor',
        planned_start_at=now + timedelta(hours=5)
    )
    assert eval_res['risk_level'] == DuplicateRiskLevel.SUSPICIOUS
    assert eval_res['is_flagged'] is True
    assert "previously rejected" in eval_res['reason']


def test_qr_issuance_and_eligibility(db, admin_user, faculty_user):
    """Test 8 & 9: Only eligible approved registrations receive active QR credentials."""
    form, _ = FormService.create_form(
        name='Approval Form',
        visit_type=VisitType.OFFICIAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    now = datetime.now(timezone.utc)
    req, _ = RegistrationService.register_visitor(
        visit_type=VisitType.OFFICIAL,
        full_name='Charlie Pass',
        email='charlie@example.com',
        phone='4445556666',
        host_user_id=faculty_user.id,
        purpose='Faculty Collaboration',
        planned_start_at=now + timedelta(hours=1),
        dynamic_responses={'purpose_detail': 'Meeting'}
    )

    # Pending request has no active credential
    assert req.status == VisitRequestStatus.PENDING_APPROVAL
    assert req.active_credential is None

    # Approve request
    approved_req, err = ApprovalService.approve_request(req.id, faculty_user)
    assert err is None
    assert approved_req.status == VisitRequestStatus.APPROVED
    assert approved_req.active_credential is not None
    assert approved_req.active_credential.is_valid_now() is True


def test_qr_lookup_role_authorization_admin_and_faculty(client, db, admin_user, faculty_user, other_faculty_user):
    """Test 11, 12, 13, 14: QR scan lookup authorization and view-only behavior."""
    form, _ = FormService.create_form(
        name='Lookup Test Form',
        visit_type=VisitType.OFFICIAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    now = datetime.now(timezone.utc)
    req, _ = RegistrationService.register_visitor(
        visit_type=VisitType.OFFICIAL,
        full_name='David Hosted',
        email='david@example.com',
        phone='7778889999',
        host_user_id=faculty_user.id,
        purpose='Hosted by Test Faculty',
        planned_start_at=now + timedelta(hours=1),
        dynamic_responses={'purpose_detail': 'Collab'}
    )
    approved_req, _ = ApprovalService.approve_request(req.id, faculty_user)
    cred = approved_req.active_credential

    # Lookup by Admin — succeeds for any record
    res, status_code = LookupService.lookup_visitor(approved_req.public_reference, admin_user)
    assert status_code == 200
    assert res['valid'] is True
    assert res['status'] == 'VALID'
    assert res['visitor_details']['full_name'] == 'David Hosted'

    # Lookup by authorized Faculty (host_user_id matches) — succeeds
    res_fac, status_fac = LookupService.lookup_visitor(approved_req.public_reference, faculty_user)
    assert status_fac == 200
    assert res_fac['valid'] is True
    assert res_fac['visitor_details']['full_name'] == 'David Hosted'

    # Lookup by UNRELATED Faculty (host_user_id does NOT match) — strict 403 Forbidden!
    res_denied, status_denied = LookupService.lookup_visitor(approved_req.public_reference, other_faculty_user)
    assert status_denied == 403
    assert res_denied['status'] == 'FORBIDDEN'

    # View-only guarantee: Lookup did NOT check in the visitor, did NOT consume the credential
    db.session.refresh(cred)
    db.session.refresh(approved_req)
    assert cred.status == QRCredentialStatus.ACTIVE
    assert approved_req.active_session is None


def test_gate_scanner_and_checkin_checkout_preserved(db, admin_user, security_user, faculty_user):
    """Test 15, 16, 17: Security gate scanner, physical photo check, check-in and check-out preserved."""
    form, _ = FormService.create_form(
        name='Gate Gate Operations Form',
        visit_type=VisitType.GENERAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, admin_user)

    now = datetime.now(timezone.utc)
    req, _ = RegistrationService.register_visitor(
        visit_type=VisitType.GENERAL,
        full_name='Eva GateCheck',
        email='eva@example.com',
        phone='3334445555',
        host_user_id=faculty_user.id,
        purpose='Campus visit',
        planned_start_at=now + timedelta(minutes=10),
        dynamic_responses={'purpose_detail': 'Gate test'}
    )
    ApprovalService.approve_request(req.id, faculty_user)

    # Gate verification by security staff
    verify_res = GateService.verify_credential_or_reference(req.public_reference, security_user)
    assert verify_res['valid'] is True
    assert verify_res['can_check_in'] is True
    assert verify_res['status'] == 'VALID'

    # Physical Check-In by security
    session, err = GateService.check_in(req.id, security_user, notes='Physical ID verified')
    assert err is None
    assert session is not None
    assert session.status == 'ACTIVE'

    # Check occupancy calculation
    assert GateService.get_current_occupancy() >= 1

    # Check-out by security
    session_out, out_err = GateService.check_out(session.id, security_user, notes='Exit verified')
    assert out_err is None
    assert session_out.status == 'COMPLETED'
