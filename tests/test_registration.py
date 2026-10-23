"""Unit and integration tests for public visitor registration, host validation, and photo serving."""
import io
import os
from datetime import datetime, timezone, timedelta
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
from app import db
from app.models.user import User, UserRole
from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
from app.models.visit_type import VisitType
from app.models.visit import VisitRequest, VisitResponse, VisitRequestStatus
from app.models.visitor import Visitor
from app.services.form_service import FormService
from app.services.registration_service import RegistrationService
from app.services.upload_service import UploadService


@pytest.fixture
def published_academic_form(db, admin_user):
    form, _ = FormService.create_form(
        name="Guest Lecture Form",
        visit_type=VisitType.ACADEMIC,
        description="Academic guest registration",
        creator_user=admin_user
    )
    v1 = form.versions.first()
    schema = [
        {"field_key": "lecture_topic", "field_label": "Topic", "field_type": "text", "is_required": True},
        {"field_key": "department_choice", "field_label": "Dept", "field_type": "select", "options": ["CS", "EE", "ME"], "is_required": True}
    ]
    FormService.update_draft_schema(form.id, v1.id, schema, actor_user=admin_user)
    FormService.publish_version(form.id, v1.id, actor_user=admin_user)
    return form


def test_public_registration_hub_renders(client):
    res = client.get('/register')
    assert res.status_code == 200
    assert b"Visitor Registration" in res.data
    assert b"General Campus Visitor" in res.data


def test_register_form_renders_published_schema(client, published_academic_form, faculty_user):
    res = client.get(f'/register/{VisitType.ACADEMIC}')
    assert res.status_code == 200
    assert b"Guest Lecture Form" in res.data
    assert b"dyn__lecture_topic" in res.data
    assert b"Test Faculty" in res.data  # Eligible host in dropdown


def test_register_rejects_nonexistent_host(db, published_academic_form):
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Bob Visitor",
        email="bob@example.com",
        phone="5551234567",
        organization="MIT",
        host_user_id=999999,  # Non-existent
        purpose="Keynote Lecture",
        planned_start_at=None,
        planned_end_at=None,
        dynamic_responses={"lecture_topic": "AI", "department_choice": "CS"}
    )
    assert req is None
    assert "does not exist" in err


def test_register_rejects_inactive_host(db, published_academic_form, inactive_user):
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Bob Visitor",
        email="bob@example.com",
        phone="5551234567",
        organization="MIT",
        host_user_id=inactive_user.id,
        purpose="Keynote Lecture",
        planned_start_at=None,
        planned_end_at=None,
        dynamic_responses={"lecture_topic": "AI", "department_choice": "CS"}
    )
    assert req is None
    assert "currently inactive" in err


def test_register_rejects_security_role_host(db, published_academic_form, security_user):
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Bob Visitor",
        email="bob@example.com",
        phone="5551234567",
        organization="MIT",
        host_user_id=security_user.id,
        purpose="Keynote Lecture",
        planned_start_at=None,
        planned_end_at=None,
        dynamic_responses={"lecture_topic": "AI", "department_choice": "CS"}
    )
    assert req is None
    assert "cannot be assigned as visit hosts" in err


def test_register_rejects_missing_required_dynamic_field(db, published_academic_form, faculty_user):
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Bob Visitor",
        email="bob@example.com",
        phone="5551234567",
        organization="MIT",
        host_user_id=faculty_user.id,
        purpose="Keynote Lecture",
        planned_start_at=None,
        planned_end_at=None,
        dynamic_responses={"department_choice": "CS"}  # Missing lecture_topic
    )
    assert req is None
    assert "Required field 'Topic' was not provided" in err


def test_register_rejects_invalid_select_option(db, published_academic_form, faculty_user):
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Bob Visitor",
        email="bob@example.com",
        phone="5551234567",
        organization="MIT",
        host_user_id=faculty_user.id,
        purpose="Keynote Lecture",
        planned_start_at=None,
        planned_end_at=None,
        dynamic_responses={"lecture_topic": "AI", "department_choice": "CIVIL_ENG"}  # Not in allowed options
    )
    assert req is None
    assert "not an allowed option" in err


def test_successful_registration_and_confirmation(client, published_academic_form, faculty_user):
    res = client.post(
        f'/register/{VisitType.ACADEMIC}',
        data={
            "full_name": "Dr. Alan Turing",
            "email": "alan@turing.org",
            "phone": "555-019-9999",
            "organization": "Cambridge University",
            "host_user_id": faculty_user.id,
            "purpose": "Computing Lecture",
            "dyn__lecture_topic": "Morphogenesis",
            "dyn__department_choice": "CS"
        },
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b"Registration Request Submitted!" in res.data
    assert b"Dr. Alan Turing" in res.data
    assert b"REQ-" in res.data

    # Verify records in database
    visitor = Visitor.query.filter_by(full_name="Dr. Alan Turing").first()
    assert visitor is not None
    assert visitor.email == "alan@turing.org"

    req = VisitRequest.query.filter_by(visitor_id=visitor.id).first()
    assert req is not None
    assert req.form_version_id == published_academic_form.published_version.id
    assert req.status == VisitRequestStatus.PENDING_APPROVAL

    resp = VisitResponse.query.filter_by(visit_request_id=req.id).first()
    assert resp is not None
    answers = resp.get_responses()
    assert answers["lecture_topic"] == "Morphogenesis"
    assert answers["department_choice"] == "CS"


def test_authorized_photo_serving(client, app, db, admin_user, faculty_user, security_user):
    # 1. Create a dummy photo file in upload dir
    upload_dir = UploadService.get_upload_dir()
    photo_filename = "test_photo_uuid_123.jpg"
    photo_path = os.path.join(upload_dir, photo_filename)
    img = Image.new('RGB', (80, 80), color='green')
    img.save(photo_path, format='JPEG')

    # 2. Create visit request with this photo hosted by faculty_user
    visitor = Visitor(public_reference="VIS-PHOTO-1", full_name="Photo Visitor")
    db.session.add(visitor)
    db.session.commit()

    form, _ = FormService.create_form(name="General", visit_type=VisitType.GENERAL, creator_user=admin_user)
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, actor_user=admin_user)

    req = VisitRequest(
        public_reference="REQ-PHOTO-1",
        visitor_id=visitor.id,
        form_version_id=v1.id,
        visit_type=VisitType.GENERAL,
        host_user_id=faculty_user.id,
        purpose="Meeting",
        photo_filename=photo_filename,
        status=VisitRequestStatus.PENDING_APPROVAL
    )
    db.session.add(req)
    db.session.commit()

    # Create a second faculty user who is NOT the host
    other_faculty = User(username="otherfaculty", email="other@test.edu", full_name="Other Faculty", role=UserRole.FACULTY, is_active=True)
    other_faculty.set_password("Faculty@456")
    db.session.add(other_faculty)
    db.session.commit()

    try:
        # A. Unauthenticated request -> redirect to login (302)
        res_unauth = client.get(f'/visitors/photo/{photo_filename}')
        assert res_unauth.status_code == 302

        # B. Admin -> Allowed (200)
        client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})
        res_admin = client.get(f'/visitors/photo/{photo_filename}')
        assert res_admin.status_code == 200
        res_admin.close()
        client.post('/logout')

        # C. Security Officer -> Allowed (200)
        client.post('/login', data={'identifier': 'testsecurity', 'password': 'Security@123'})
        res_sec = client.get(f'/visitors/photo/{photo_filename}')
        assert res_sec.status_code == 200
        res_sec.close()
        client.post('/logout')

        # D. Host Faculty -> Allowed (200)
        client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
        res_host = client.get(f'/visitors/photo/{photo_filename}')
        assert res_host.status_code == 200
        res_host.close()
        client.post('/logout')

        # E. Unrelated Faculty -> Forbidden (403)
        client.post('/login', data={'identifier': 'otherfaculty', 'password': 'Faculty@456'})
        res_other = client.get(f'/visitors/photo/{photo_filename}')
        assert res_other.status_code == 403
        res_other.close()

    finally:
        try:
            if os.path.exists(photo_path):
                os.remove(photo_path)
        except Exception:
            pass


def test_register_rejects_past_arrival_date(db, published_academic_form, faculty_user):
    """Verify registration rejects planned arrival time in the past beyond allowed grace period."""
    past_time = datetime.now(timezone.utc) - timedelta(hours=2)
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Past Visitor",
        host_user_id=faculty_user.id,
        purpose="Guest Lecture",
        planned_start_at=past_time,
        dynamic_responses={"purpose_detail": "Sample Paper Presentation"}
    )
    assert req is None
    assert err == "Expected arrival date and time cannot be in the past."


def test_register_rejects_departure_before_arrival(db, published_academic_form, faculty_user):
    """Verify departure time earlier than arrival time is rejected."""
    arrival_time = datetime.now(timezone.utc) + timedelta(days=1, hours=2)
    departure_time = datetime.now(timezone.utc) + timedelta(days=1, hours=1)
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Invalid Range Visitor",
        host_user_id=faculty_user.id,
        purpose="Guest Lecture",
        planned_start_at=arrival_time,
        planned_end_at=departure_time,
        dynamic_responses={"purpose_detail": "Sample Paper Presentation"}
    )
    assert req is None
    assert err == "Expected departure date and time cannot be earlier than arrival time."


def test_register_rejects_malformed_arrival_date_string(db, published_academic_form, faculty_user):
    """Verify malformed date strings are caught with clear error."""
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Malformed Date Visitor",
        host_user_id=faculty_user.id,
        purpose="Guest Lecture",
        planned_start_at="invalid-date-string-123",
        dynamic_responses={"purpose_detail": "Sample Paper Presentation"}
    )
    assert req is None
    assert err == "Invalid format for expected arrival date and time."


def test_register_accepts_valid_future_arrival_and_departure(db, published_academic_form, faculty_user):
    """Verify valid future dates are accepted and stored with UTC timezone."""
    arrival_time = datetime.now(timezone.utc) + timedelta(days=2, hours=10)
    departure_time = datetime.now(timezone.utc) + timedelta(days=2, hours=16)
    req, err = RegistrationService.register_visitor(
        visit_type=VisitType.ACADEMIC,
        full_name="Valid Date Visitor",
        host_user_id=faculty_user.id,
        purpose="Guest Lecture",
        planned_start_at=arrival_time,
        planned_end_at=departure_time,
        dynamic_responses={"lecture_topic": "Quantum Computing", "department_choice": "CS"}
    )
    assert err is None
    assert req is not None
    assert req.planned_start_at == arrival_time
    assert req.planned_end_at == departure_time

