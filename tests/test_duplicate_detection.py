"""Unit tests for non-blocking duplicate visitor detection."""
from datetime import datetime, timedelta, timezone
import pytest
from app import db
from app.models.visitor import Visitor
from app.models.visit import VisitRequest, VisitRequestStatus
from app.models.registration_form import RegistrationForm
from app.models.visit_type import VisitType
from app.services.duplicate_service import DuplicateService
from app.services.form_service import FormService


@pytest.fixture
def base_visit(db, admin_user):
    form, _ = FormService.create_form(
        name="General Visit Form",
        visit_type=VisitType.GENERAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    FormService.publish_version(form.id, v1.id, actor_user=admin_user)

    visitor = Visitor(
        public_reference="VIS-TEST-001",
        full_name="Alice Smith",
        phone="+1 (555) 019-2834",
        normalized_phone=DuplicateService.normalize_phone("+1 (555) 019-2834"),
        email="alice.smith@example.com"
    )
    db.session.add(visitor)
    db.session.commit()

    scheduled_time = datetime.now(timezone.utc) + timedelta(days=1)
    req = VisitRequest(
        public_reference="REQ-TEST-001",
        visitor_id=visitor.id,
        form_version_id=v1.id,
        visit_type=VisitType.GENERAL,
        purpose="Campus tour",
        planned_start_at=scheduled_time,
        status=VisitRequestStatus.PENDING_APPROVAL
    )
    db.session.add(req)
    db.session.commit()
    return visitor, req


def test_first_time_visitor_not_duplicate(db):
    is_dup, reason = DuplicateService.check_duplicate(
        phone="5559998888",
        email="new.visitor@domain.com",
        planned_start_at=datetime.now(timezone.utc)
    )
    assert is_dup is False
    assert reason is None


def test_same_phone_within_24h_flagged_as_duplicate(db, base_visit):
    visitor, req = base_visit

    # Attempt to register with slightly different phone formatting within 2 hours of existing visit
    is_dup, reason = DuplicateService.check_duplicate(
        phone="555-019-2834",  # Same normalized digits
        email="different.email@domain.com",
        planned_start_at=req.planned_start_at + timedelta(hours=2)
    )
    assert is_dup is True
    assert "REQ-TEST-001" in reason
    assert "phone match" in reason


def test_same_email_within_24h_flagged_as_duplicate(db, base_visit):
    visitor, req = base_visit

    is_dup, reason = DuplicateService.check_duplicate(
        phone="1234567890",
        email="ALICE.SMITH@EXAMPLE.COM",  # Case-insensitive match
        planned_start_at=req.planned_start_at - timedelta(hours=3)
    )
    assert is_dup is True
    assert "REQ-TEST-001" in reason
    assert "email match" in reason


def test_legitimate_repeat_visit_outside_window_not_flagged(db, base_visit):
    visitor, req = base_visit

    # Same visitor visiting 2 weeks later
    future_time = req.planned_start_at + timedelta(days=14)
    is_dup, reason = DuplicateService.check_duplicate(
        phone="+1 555 019 2834",
        email="alice.smith@example.com",
        planned_start_at=future_time
    )
    assert is_dup is False
    assert reason is None
