"""Automated tests for Premium Visitor QR Pass UI/UX and Security Panel Visitor Editing."""
from datetime import datetime, timezone, timedelta
import io
import os
import pytest
from PIL import Image

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
from app.models.audit_log import AuditLog, AuditAction
from app.services.qr_service import QRService
from app.services.form_service import FormService
from app.services.upload_service import UploadService


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


def create_sample_request(
    db,
    form,
    host_user,
    full_name="Samantha Reed",
    email="samantha@techcorp.io",
    phone="+1 (555) 234-5678",
    organization="TechCorp Global",
    purpose="Strategic AI Partnership Review",
    status=VisitRequestStatus.APPROVED,
    photo_filename=None
):
    """Creates a synthetic visitor and visit request for testing."""
    visitor = Visitor(
        public_reference=Visitor.generate_reference(),
        full_name=full_name,
        email=email,
        phone=phone,
        organization=organization
    )
    db.session.add(visitor)
    db.session.commit()

    now = datetime.now(timezone.utc)
    req = VisitRequest(
        public_reference=VisitRequest.generate_reference(),
        visitor_id=visitor.id,
        form_version_id=form.published_version.id,
        visit_type=VisitType.GENERAL,
        host_user_id=host_user.id if host_user else None,
        department=host_user.department if host_user else "Engineering",
        purpose=purpose,
        planned_start_at=now - timedelta(hours=1),
        planned_end_at=now + timedelta(hours=6),
        status=status,
        photo_filename=photo_filename
    )
    db.session.add(req)
    db.session.commit()
    return req


# =========================================================================
# Part 1: Visitor QR Pass UI/UX Tests
# =========================================================================

def test_visitor_pass_redesign_elements(client, faculty_user, base_published_form):
    """Visitor pass renders professional identity pass elements, branding, and verification notice."""
    req = create_sample_request(db, base_published_form, faculty_user)
    QRService.issue_credential(req.id, faculty_user)

    res = client.get(f'/visitors/pass/{req.public_reference}')
    assert res.status_code == 200

    # 1. Header branding & heading
    assert b"VISITOR PASS" in res.data
    assert b"Smart Visitor Management" in res.data or b"Campus" in res.data

    # 2. Key visitor metadata displayed
    assert b"Samantha Reed" in res.data
    assert req.public_reference.encode() in res.data
    assert b"TechCorp Global" in res.data
    assert b"Strategic AI Partnership Review" in res.data
    assert faculty_user.full_name.encode() in res.data

    # 3. Security verification instructions
    assert b"Present this pass at the security desk for identity verification" in res.data

    # 4. QR image container rendered
    assert f"/visitors/pass/{req.public_reference}/qr.png".encode() in res.data

    # 5. Privacy headers
    assert "no-store" in res.headers.get('Cache-Control', '')
    assert "no-cache" in res.headers.get('Cache-Control', '')


def test_visitor_pass_photo_endpoint(client, faculty_user, base_published_form, app):
    """Pass photo endpoint securely serves registered photo without staff login."""
    # Create fake photo file in upload dir
    photos_dir = UploadService.get_upload_dir()
    os.makedirs(photos_dir, exist_ok=True)
    fake_filename = "test_pass_photo_123.jpg"
    fake_path = os.path.join(photos_dir, fake_filename)

    # Write a tiny valid JPEG image
    img = Image.new('RGB', (60, 80), color='blue')
    img.save(fake_path, format='JPEG')

    try:
        req = create_sample_request(
            db, base_published_form, faculty_user,
            photo_filename=fake_filename
        )

        res = client.get(f'/visitors/pass/{req.public_reference}/photo.jpg')
        assert res.status_code == 200
        assert res.content_type == 'image/jpeg'
        assert "no-store" in res.headers.get('Cache-Control', '')
        res.close()

        # Invalid reference should 404
        assert client.get('/visitors/pass/NONEXISTENT-REF/photo.jpg').status_code == 404
    finally:
        try:
            if os.path.exists(fake_path):
                os.remove(fake_path)
        except Exception:
            pass


def test_visitor_pass_status_states(client, faculty_user, base_published_form):
    """Pass reflects actual system status for pending, approved, rejected, and expired passes."""
    # A. Active approved pass
    req_active = create_sample_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    QRService.issue_credential(req_active.id, faculty_user)
    res_active = client.get(f'/visitors/pass/{req_active.public_reference}')
    assert b"Authorized Visitor Pass" in res_active.data or b"Authorized" in res_active.data
    assert b"qr.png" in res_active.data

    # B. Pending pass
    req_pending = create_sample_request(db, base_published_form, faculty_user, status=VisitRequestStatus.PENDING_APPROVAL)
    res_pending = client.get(f'/visitors/pass/{req_pending.public_reference}')
    assert b"Pending Review" in res_pending.data
    assert b"qr.png" not in res_pending.data

    # C. Rejected pass
    req_rejected = create_sample_request(db, base_published_form, faculty_user, status=VisitRequestStatus.REJECTED)
    res_rejected = client.get(f'/visitors/pass/{req_rejected.public_reference}')
    assert b"Request Rejected" in res_rejected.data
    assert b"qr.png" not in res_rejected.data


# =========================================================================
# Part 2: Security Panel Visitor Editing Tests
# =========================================================================

def test_edit_visitor_details_role_enforcement(client, auth_client, faculty_user, security_user, base_published_form):
    """Only authorized SECURITY and ADMIN roles can access the edit visitor details endpoint."""
    req = create_sample_request(db, base_published_form, faculty_user)

    # 1. Unauthenticated -> 302 to login
    res_unauth = client.post(f'/security/requests/{req.id}/edit-details', json={'full_name': 'Hacker'})
    assert res_unauth.status_code in (302, 401)

    # 2. Authenticated as FACULTY -> 403 Forbidden
    auth_client.login('testfaculty', 'Faculty@123')
    res_faculty = client.post(f'/security/requests/{req.id}/edit-details', json={'full_name': 'Dr. Edit'})
    assert res_faculty.status_code == 403
    auth_client.logout()

    # 3. Authenticated as SECURITY -> Permitted (200 OK)
    auth_client.login('testsecurity', 'Security@123')
    res_sec = client.post(
        f'/security/requests/{req.id}/edit-details',
        json={
            'full_name': 'Samantha Reed Corrected',
            'phone': '555-444-3333',
            'email': 'samantha.corrected@techcorp.io',
            'organization': 'TechCorp Systems',
            'purpose': 'Corrected Purpose per Passport'
        }
    )
    assert res_sec.status_code == 200
    data = res_sec.get_json()
    assert data['success'] is True
    assert data['visitor_details']['full_name'] == 'Samantha Reed Corrected'
    auth_client.logout()


def test_edit_visitor_details_data_integrity_and_audit(client, auth_client, security_user, faculty_user, base_published_form):
    """Editing visitor updates permitted fields, preserves approval status, and creates audit log."""
    req = create_sample_request(db, base_published_form, faculty_user, status=VisitRequestStatus.APPROVED)
    cred, _, _ = QRService.issue_credential(req.id, faculty_user)

    auth_client.login('testsecurity', 'Security@123')
    res = client.post(
        f'/security/requests/{req.id}/edit-details',
        json={
            'full_name': 'Jonathan Swift',
            'phone': '+1 (555) 987-6543',
            'email': 'jswift@acme.org',
            'organization': 'Acme Academic Corp',
            'purpose': 'Keynote Speech and Seminar',
            'notes': 'Corrected name spelling and mobile phone per physical driving license'
        }
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    # 1. Verify DB Visitor model updated
    db.session.refresh(req)
    assert req.visitor.full_name == 'Jonathan Swift'
    assert req.visitor.phone == '+1 (555) 987-6543'
    assert req.visitor.email == 'jswift@acme.org'
    assert req.visitor.organization == 'Acme Academic Corp'
    assert req.purpose == 'Keynote Speech and Seminar'

    # 2. Verify visit approval and credentials remain untouched
    assert req.status == VisitRequestStatus.APPROVED
    assert req.active_credential is not None
    assert req.active_credential.status == QRCredentialStatus.ACTIVE
    assert req.active_session is None  # Editing NEVER triggers check-in

    # 3. Verify audit log entry
    audit = AuditLog.query.filter_by(
        action=AuditAction.VISITOR_DETAILS_EDITED,
        entity_reference=req.public_reference
    ).first()
    assert audit is not None
    assert audit.actor_user_id == security_user.id
    meta = audit.get_metadata()
    assert 'full_name' in meta.get('changed_fields', [])
    assert 'phone' in meta.get('changed_fields', [])
    assert 'organization' in meta.get('changed_fields', [])


def test_edit_visitor_details_validation_and_mass_assignment(client, auth_client, security_user, faculty_user, base_published_form):
    """Endpoint validates required fields, prevents mass assignment, and rejects invalid inputs."""
    req = create_sample_request(db, base_published_form, faculty_user)
    auth_client.login('testsecurity', 'Security@123')

    # A. Empty name rejected
    res_empty_name = client.post(
        f'/security/requests/{req.id}/edit-details',
        json={'full_name': '   ', 'phone': '5551234567', 'purpose': 'Valid Purpose'}
    )
    assert res_empty_name.status_code == 400
    assert "full name" in res_empty_name.get_json()['message'].lower()

    # B. Missing phone rejected
    res_no_phone = client.post(
        f'/security/requests/{req.id}/edit-details',
        json={'full_name': 'Valid Name', 'phone': '', 'purpose': 'Valid Purpose'}
    )
    assert res_no_phone.status_code == 400
    assert "Phone number is required" in res_no_phone.get_json()['message']

    # C. Missing purpose rejected
    res_no_purpose = client.post(
        f'/security/requests/{req.id}/edit-details',
        json={'full_name': 'Valid Name', 'phone': '5551234567', 'purpose': ''}
    )
    assert res_no_purpose.status_code == 400
    assert "Visit purpose is required" in res_no_purpose.get_json()['message']

    # D. Mass assignment attempt: changing role, status, host_user_id
    res_mass_assign = client.post(
        f'/security/requests/{req.id}/edit-details',
        json={
            'full_name': 'Secure Visitor',
            'phone': '555-888-9999',
            'purpose': 'Legitimate Purpose',
            'status': 'REJECTED',
            'host_user_id': 9999,
            'role': 'ADMIN'
        }
    )
    assert res_mass_assign.status_code == 200
    db.session.refresh(req)
    assert req.visitor.full_name == 'Secure Visitor'
    assert req.status == VisitRequestStatus.APPROVED  # Did NOT change to REJECTED
    assert req.host_user_id == faculty_user.id      # Did NOT change host


def test_security_verify_credential_returns_editable_fields(client, auth_client, security_user, faculty_user, base_published_form):
    """The credential verification endpoint returns phone, email, and organization for desk display and editing."""
    req = create_sample_request(
        db, base_published_form, faculty_user,
        organization="Apex Dynamics",
        phone="555-321-4321",
        email="apex@example.com"
    )
    cred, raw_token, _ = QRService.issue_credential(req.id, faculty_user)

    auth_client.login('testsecurity', 'Security@123')
    res = client.post('/security/verify', json={'credential': raw_token})
    assert res.status_code == 200
    data = res.get_json()
    assert data['valid'] is True
    details = data['visitor_details']
    assert details['full_name'] == req.visitor.full_name
    assert details['organization'] == 'Apex Dynamics'
    assert details['phone'] == '555-321-4321'
    assert details['email'] == 'apex@example.com'
    assert details['request_id'] == req.id
