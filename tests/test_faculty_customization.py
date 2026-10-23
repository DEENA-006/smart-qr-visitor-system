"""Unit and route tests for Property-Level Faculty Customization and security guards."""
import json
import pytest
from app import db
from app.models.user import User, UserRole
from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
from app.models.visit_type import VisitType
from app.services.form_service import FormService


@pytest.fixture
def customizable_form(db, admin_user):
    """Creates a form allowing faculty customization with specific property permissions."""
    form, err = FormService.create_form(
        name="Guest Lecture Form",
        visit_type=VisitType.ACADEMIC,
        description="Department guest speaker registrations",
        allow_faculty_customization=True,
        creator_user=admin_user
    )
    v1 = form.versions.first()

    schema = [
        {"field_key": "topic", "field_label": "Original Topic Label", "field_type": "text", "is_required": True, "help_text": "Original Help"},
        {"field_key": "honorarium", "field_label": "Honorarium Details", "field_type": "text", "is_required": False, "help_text": "Admin only"}
    ]
    # Faculty is ONLY permitted to edit 'help_text' and 'field_label' for 'topic'. 'honorarium' is strictly locked.
    perms = {
        "topic": ["field_label", "help_text"]
    }

    FormService.update_draft_schema(form.id, v1.id, schema, perms, actor_user=admin_user)
    FormService.publish_version(form.id, v1.id, actor_user=admin_user)
    return form


def test_faculty_can_view_customizable_forms(client, faculty_user, customizable_form):
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    res = client.get('/faculty/forms')
    assert res.status_code == 200
    assert b"Guest Lecture Form" in res.data
    assert b"Customize Preferences" in res.data


def test_faculty_can_view_customization_page(client, faculty_user, customizable_form):
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    res = client.get(f'/faculty/forms/{customizable_form.id}/customize')
    assert res.status_code == 200
    assert b"Original Topic Label" in res.data
    assert b"topic" in res.data


def test_faculty_successful_permitted_property_update(client, faculty_user, customizable_form):
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    # Update permitted field 'topic' with new label and help_text
    res = client.post(
        f'/faculty/forms/{customizable_form.id}/customize',
        json={
            "topic": {
                "field_label": "Department Seminar Topic",
                "help_text": "Please provide the exact abstract title"
            }
        }
    )
    assert res.status_code == 302 or res.status_code == 200

    # Verify that the schema was updated in the latest version
    db.session.refresh(customizable_form)
    latest_ver = customizable_form.versions.order_by(FormVersion.version_number.desc()).first()
    fields = {f['field_key']: f for f in latest_ver.get_schema()}
    assert fields['topic']['field_label'] == "Department Seminar Topic"
    assert fields['topic']['help_text'] == "Please provide the exact abstract title"
    # Ensure is_required was untouched
    assert fields['topic']['is_required'] is True


def test_faculty_forbidden_from_modifying_protected_properties(client, faculty_user, customizable_form):
    """Faculty attempting to change protected properties (is_required, field_type, field_key) is rejected with 403."""
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    # Attempt to change is_required from True to False
    res = client.post(
        f'/faculty/forms/{customizable_form.id}/customize',
        json={
            "topic": {
                "is_required": False
            }
        }
    )
    assert res.status_code == 403

    # Attempt to change field_type
    res_type = client.post(
        f'/faculty/forms/{customizable_form.id}/customize',
        json={
            "topic": {
                "field_type": "textarea"
            }
        }
    )
    assert res_type.status_code == 403


def test_faculty_forbidden_from_modifying_unpermitted_fields(client, faculty_user, customizable_form):
    """Faculty attempting to modify fields not in faculty_permitted_fields_json is rejected with 403."""
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})

    # 'honorarium' is not in faculty_permissions
    res = client.post(
        f'/faculty/forms/{customizable_form.id}/customize',
        json={
            "honorarium": {
                "field_label": "Faculty Changed Honorarium"
            }
        }
    )
    assert res.status_code == 403


def test_customization_disabled_form_rejects_faculty(client, faculty_user, db, admin_user):
    """Forms with allow_faculty_customization=False reject faculty customization with 403."""
    form, _ = FormService.create_form(
        name="Locked Admin Form",
        visit_type=VisitType.OFFICIAL,
        allow_faculty_customization=False,
        creator_user=admin_user
    )

    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
    res = client.post(
        f'/faculty/forms/{form.id}/customize',
        json={
            "purpose_detail": {"help_text": "Trying to bypass"}
        }
    )
    assert res.status_code == 403 or res.status_code == 302


def test_default_form_faculty_customization_succeeds(client, faculty_user, db, admin_user):
    """Verify default initial form has consistent 'purpose_detail' permission key and faculty can update permitted properties."""
    form, _ = FormService.create_form(
        name="Academic Seminar",
        visit_type=VisitType.ACADEMIC,
        allow_faculty_customization=True,
        creator_user=admin_user
    )
    v1 = form.versions.first()
    # Check default permissions key matches schema key
    perms = v1.get_faculty_permissions()
    assert "purpose_detail" in perms
    assert "help_text" in perms["purpose_detail"]["allowed_properties"]

    # Test faculty updating purpose_detail help_text
    client.post('/login', data={'identifier': 'testfaculty', 'password': 'Faculty@123'})
    res = client.post(
        f'/faculty/forms/{form.id}/customize',
        json={
            "purpose_detail": {
                "help_text": "Please provide the seminar paper title and session room."
            }
        }
    )
    assert res.status_code in (200, 302)

    db.session.refresh(form)
    latest_ver = form.versions.order_by(FormVersion.version_number.desc()).first()
    fields = {f['field_key']: f for f in latest_ver.get_schema()}
    assert fields['purpose_detail']['help_text'] == "Please provide the seminar paper title and session room."

