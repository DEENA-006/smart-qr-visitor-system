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
from app.services.gate_service import GateService
from app.services.qr_service import QRService


def extract_csrf_token(html_text: str) -> str:
    """Helper to extract csrf_token from rendered HTML forms."""
    match = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html_text)
    if not match:
        match = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']csrf_token["\']', html_text)
    return match.group(1) if match else ''


@pytest.fixture
def active_session_setup(app, db, admin_user, faculty_user, security_user):
    """Sets up an active visit session for testing Check Out operations."""
    form = RegistrationForm(name="Campus Access Form", visit_type=VisitType.GENERAL, is_active=True)
    db.session.add(form)
    db.session.flush()

    version = FormVersion(
        form_id=form.id,
        version_number=1,
        status='PUBLISHED',
        published_at=datetime.now(timezone.utc),
        created_by_id=admin_user.id
    )
    version.set_schema([])
    db.session.add(version)
    db.session.flush()

    visitor = Visitor(
        public_reference=Visitor.generate_reference(),
        full_name="Ada Lovelace",
        email="ada@analytical.org",
        phone="+12025550188",
        organization="Babbage Engine Labs"
    )
    db.session.add(visitor)
    db.session.flush()

    now_utc = datetime.now(timezone.utc)
    req = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=visitor.id,
        form_version_id=version.id,
        visit_type=VisitType.GENERAL,
        host_user_id=faculty_user.id,
        department=faculty_user.department,
        purpose="Computational Architecture Review",
        planned_start_at=now_utc - timedelta(hours=1),
        planned_end_at=now_utc + timedelta(hours=2),
        photo_filename="ada_lovelace.jpg",
        status=VisitRequestStatus.APPROVED,
        approved_at=now_utc,
        decided_by_id=faculty_user.id
    )
    db.session.add(req)
    db.session.flush()

    cred, raw_token, err = QRService.issue_credential(req.id, faculty_user, commit=False)
    assert err is None
    db.session.commit()

    # Check in to establish active session
    session, check_in_err = GateService.check_in(req.id, security_user)
    assert check_in_err is None
    assert session.status == VisitSessionStatus.ACTIVE

    return req, session, raw_token


def test_main_js_contains_non_blocking_protection_and_safety_mechanisms():
    """Verify that main.js contains the essential bug-prevention patterns."""
    with open('app/static/js/main.js', 'r', encoding='utf-8') as f:
        content = f.read()

    # Must check e.defaultPrevented so cancelled confirmations do not lock buttons
    assert 'e.defaultPrevented' in content
    # Must use non-blocking asynchronous disablement so the browser sends the POST request
    assert 'setTimeout(' in content
    # Must have resetSubmitButton helper
    assert 'window.resetSubmitButton' in content
    # Must support pageshow bfcache restoration
    assert 'pageshow' in content
    # Must ignore GET forms (idempotent search/filter)
    assert "form.method.toUpperCase() === 'GET'" in content


def test_scan_templates_have_data_no_disable_attribute():
    """Verify that manual AJAX forms have data-no-disable and robust button management."""
    with open('app/templates/security/scan.html', 'r', encoding='utf-8') as f:
        scan_content = f.read()
    assert 'id="manualVerifyForm" data-no-disable' in scan_content
    assert 'originalVerifyBtnText' in scan_content

    with open('app/templates/lookup/scan.html', 'r', encoding='utf-8') as f:
        lookup_content = f.read()
    assert 'id="lookupManualForm" data-no-disable' in lookup_content
    assert 'originalLookupBtnText' in lookup_content


def test_html_form_checkout_flow(client, security_user, active_session_setup):
    """Regression Test: Standard HTML form POST to /security/check-out successfully completes session."""
    req, session, raw_token = active_session_setup

    client.post('/login', data={'identifier': security_user.username, 'password': 'Security@123'})

    # 1. Fetch occupancy page and check session exists
    occ_page = client.get('/security/occupancy')
    assert occ_page.status_code == 200
    assert b"Ada Lovelace" in occ_page.data
    csrf_token = extract_csrf_token(occ_page.data.decode('utf-8'))
    assert csrf_token != ''

    # 2. Simulate standard HTML form submission from Occupancy page
    post_resp = client.post(
        '/security/check-out',
        data={'csrf_token': csrf_token, 'session_id': session.id, 'notes': 'Departure verified'},
        follow_redirects=True
    )
    assert post_resp.status_code == 200
    assert b"Check-out confirmed for Ada Lovelace" in post_resp.data

    # 3. Verify session in DB is now COMPLETED
    db.session.refresh(session)
    assert session.status == VisitSessionStatus.COMPLETED
    assert session.checked_out_at is not None
    assert session.checked_out_by_id == security_user.id

    # 4. Occupancy count decreased
    assert GateService.get_current_occupancy() == 0


def test_html_form_checkout_missing_or_invalid_session_handled_safely(client, security_user):
    """Regression Test: Submitting an invalid session_id flashes an error and does not crash."""
    client.post('/login', data={'identifier': security_user.username, 'password': 'Security@123'})

    occ_page = client.get('/security/occupancy')
    csrf_token = extract_csrf_token(occ_page.data.decode('utf-8'))

    post_resp = client.post(
        '/security/check-out',
        data={'csrf_token': csrf_token, 'session_id': 999999},
        follow_redirects=True
    )
    assert post_resp.status_code == 200
    assert b"Active visit session not found." in post_resp.data


def test_security_verify_credential_empty_input_handled_safely(client, security_user):
    """Regression Test: Empty or whitespace credential verification returns failure without server error."""
    client.post('/login', data={'identifier': security_user.username, 'password': 'Security@123'})

    scan_page = client.get('/security/scan')
    csrf_token = extract_csrf_token(scan_page.data.decode('utf-8'))

    resp = client.post(
        '/security/verify',
        json={'credential': ''},
        headers={'X-CSRFToken': csrf_token}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['valid'] is False
