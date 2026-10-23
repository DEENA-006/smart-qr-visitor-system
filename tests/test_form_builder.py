"""Unit and integration tests for Form Builder backend, schemas, and routes."""
import json
import pytest
from app import db
from app.models.user import User, UserRole
from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
from app.models.visit_type import VisitType
from app.services.form_service import FormService


def test_create_form_and_initial_draft_version(db, admin_user):
    form, err = FormService.create_form(
        name="Official Guest Registration",
        visit_type=VisitType.OFFICIAL,
        description="Form for official visitors",
        allow_faculty_customization=True,
        creator_user=admin_user
    )
    assert err is None
    assert form is not None
    assert form.name == "Official Guest Registration"
    assert form.visit_type == VisitType.OFFICIAL
    assert form.versions.count() == 1

    v1 = form.versions.first()
    assert v1.version_number == 1
    assert v1.status == FormVersionStatus.DRAFT
    schema = v1.get_schema()
    assert len(schema) >= 1
    assert schema[0]["field_key"] == "purpose_detail"


def test_create_form_rejects_invalid_visit_type(db, admin_user):
    form, err = FormService.create_form(
        name="Invalid Visit Type Form",
        visit_type="SPACE_TOURISM",
        creator_user=admin_user
    )
    assert form is None
    assert "Invalid visit type" in err


def test_update_draft_schema_and_permissions(db, admin_user):
    form, _ = FormService.create_form(
        name="Academic Guest Form",
        visit_type=VisitType.ACADEMIC,
        creator_user=admin_user
    )
    v1 = form.versions.first()

    new_schema = [
        {"field_key": "topic", "field_label": "Lecture Topic", "field_type": "text", "is_required": True},
        {"field_key": "audience", "field_label": "Intended Audience", "field_type": "dropdown", "is_required": False, "options": ["UG", "PG", "Faculty"]}
    ]
    new_perms = {
        "topic": ["label", "help_text"]
    }

    updated_version, err = FormService.update_draft_schema(
        form_id=form.id,
        version_id=v1.id,
        schema_data=new_schema,
        faculty_permissions=new_perms,
        actor_user=admin_user
    )
    assert err is None
    assert updated_version.id == v1.id
    assert len(updated_version.get_schema()) == 2
    assert updated_version.get_faculty_permissions() == new_perms


def test_schema_validation_rejects_malformed_fields(db, admin_user):
    form, _ = FormService.create_form(
        name="Validation Form",
        visit_type=VisitType.GENERAL,
        creator_user=admin_user
    )
    v1 = form.versions.first()

    # Missing field_key
    bad_schema = [{"field_label": "No Key", "field_type": "text"}]
    _, err = FormService.update_draft_schema(form.id, v1.id, bad_schema, actor_user=admin_user)
    assert "missing required property 'field_key'" in err

    # Unsupported field_type
    bad_type_schema = [{"field_key": "script_field", "field_label": "X", "field_type": "executable_script"}]
    _, err = FormService.update_draft_schema(form.id, v1.id, bad_type_schema, actor_user=admin_user)
    assert "unsupported field_type 'executable_script'" in err


def test_atomic_publish_and_version_archiving(db, admin_user):
    form, _ = FormService.create_form(
        name="Contractor Pass",
        visit_type=VisitType.CONTRACTOR,
        creator_user=admin_user
    )
    v1 = form.versions.first()

    # Publish Version 1
    pub_v1, err = FormService.publish_version(form.id, v1.id, actor_user=admin_user)
    assert err is None
    assert pub_v1.status == FormVersionStatus.PUBLISHED

    # Modify published v1 -> should fork Version 2 as DRAFT
    forked_v2, err = FormService.update_draft_schema(
        form_id=form.id,
        version_id=v1.id,
        schema_data=[{"field_key": "contractor_badge", "field_label": "Badge Number", "field_type": "text", "is_required": True}],
        actor_user=admin_user
    )
    assert err is None
    assert forked_v2.id != v1.id
    assert forked_v2.version_number == 2
    assert forked_v2.status == FormVersionStatus.DRAFT

    # Ensure v1 remains PUBLISHED
    db.session.refresh(v1)
    assert v1.status == FormVersionStatus.PUBLISHED

    # Now publish Version 2 -> v1 must be archived, v2 must be published atomically
    pub_v2, err = FormService.publish_version(form.id, forked_v2.id, actor_user=admin_user)
    assert err is None
    assert pub_v2.status == FormVersionStatus.PUBLISHED

    db.session.refresh(v1)
    assert v1.status == FormVersionStatus.ARCHIVED


def test_admin_form_builder_routes(client, admin_user):
    # Log in as admin via /login
    client.post('/login', data={'identifier': 'testadmin', 'password': 'Admin@123'})

    # Create form via POST
    resp = client.post("/admin/forms", data={
        "name": "VIP Delegation Form",
        "visit_type": "VIP",
        "description": "High-security VIP visitors",
        "allow_faculty_customization": "1"
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"VIP Delegation Form" in resp.data

    form = RegistrationForm.query.filter_by(name="VIP Delegation Form").first()
    assert form is not None
    v1 = form.versions.first()

    # Load builder page
    builder_res = client.get(f"/admin/forms/{form.id}/versions/{v1.id}")
    assert builder_res.status_code == 200
    assert b"Visual Overview" in builder_res.data

    # Publish v1
    pub_res = client.post(f"/admin/forms/{form.id}/versions/{v1.id}/publish", follow_redirects=True)
    assert pub_res.status_code == 200
    assert b"is now active and published" in pub_res.data


def test_faculty_forbidden_from_admin_form_builder(client, faculty_user):
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
    resp = client.get("/admin/forms")
    assert resp.status_code == 403


def test_archived_form_version_immutability(db, admin_user):
    """Verify editing an ARCHIVED form version creates a new DRAFT version and leaves ARCHIVED schema untouched."""
    form, _ = FormService.create_form(
        name="Contractor Security Protocol",
        visit_type=VisitType.CONTRACTOR,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    v1.set_schema([{"field_key": "badge_id", "field_label": "Badge ID", "field_type": "text", "is_required": True}])
    db.session.commit()
    # Publish v1
    pub_v1, _ = FormService.publish_version(form.id, v1.id, actor_user=admin_user)
    assert pub_v1.status == FormVersionStatus.PUBLISHED

    # Fork and publish v2 to archive v1
    v2, _ = FormService.update_draft_schema(
        form_id=form.id,
        version_id=v1.id,
        schema_data=[{"field_key": "badge_id", "field_label": "Badge ID", "field_type": "text", "is_required": True},
                     {"field_key": "tools", "field_label": "Tool List", "field_type": "text", "is_required": False}],
        actor_user=admin_user
    )
    pub_v2, _ = FormService.publish_version(form.id, v2.id, actor_user=admin_user)
    assert pub_v2.status == FormVersionStatus.PUBLISHED

    db.session.refresh(v1)
    assert v1.status == FormVersionStatus.ARCHIVED
    original_v1_schema = v1.get_schema()

    # Now attempt to edit archived v1
    v3, err = FormService.update_draft_schema(
        form_id=form.id,
        version_id=v1.id,
        schema_data=[{"field_key": "badge_id", "field_label": "Modified Badge", "field_type": "text", "is_required": True}],
        actor_user=admin_user
    )
    assert err is None
    assert v3.id != v1.id
    assert v3.version_number == 3
    assert v3.status == FormVersionStatus.DRAFT

    # Confirm v1 was NOT mutated
    db.session.refresh(v1)
    assert v1.status == FormVersionStatus.ARCHIVED
    assert v1.get_schema() == original_v1_schema

