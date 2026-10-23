import json
import re
from datetime import datetime, timezone
from app.extensions import db
from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
from app.models.visit_type import VisitType
from app.models.user import User
from app.models.audit_log import AuditAction, AuditOutcome
from app.services.audit_service import AuditService


ALLOWED_FIELD_TYPES = ('text', 'textarea', 'tel', 'email', 'select', 'date', 'time', 'checkbox', 'image', 'file')


class FormService:
    @staticmethod
    def validate_schema(schema_data: list) -> tuple[bool, str | None]:
        """Validates that form schema definitions meet format and type constraints."""
        if not isinstance(schema_data, list):
            return False, "Schema must be a list of field definitions."

        seen_keys = set()
        for idx, field in enumerate(schema_data):
            if not isinstance(field, dict):
                return False, f"Field at index {idx} must be a dictionary."

            field_key = field.get('field_key')
            label = field.get('label') or field.get('field_label')
            field_type = field.get('field_type')
            if field_type == 'dropdown':
                field_type = 'select'
                field['field_type'] = 'select'

            if not field_key:
                return False, f"Field at index {idx} is missing required property 'field_key'."
            if not re.match(r'^[a-z0-9_]{2,32}$', field_key):
                return False, f"Field key '{field_key}' is invalid (must be 2-32 lowercase letters, numbers, underscores)."
            if field_key in seen_keys:
                return False, f"Duplicate field key '{field_key}' detected."
            seen_keys.add(field_key)

            if not label or not str(label).strip():
                return False, f"Field '{field_key}' requires a readable label."

            if field_type not in ALLOWED_FIELD_TYPES:
                return False, f"Field '{field_key}' has unsupported field_type '{field_type}'. Allowed types: {', '.join(ALLOWED_FIELD_TYPES)}."

            if field_type == 'select':
                options = field.get('options', [])
                if not isinstance(options, list) or len(options) == 0:
                    return False, f"Dropdown field '{field_key}' requires at least one option."

        return True, None

    @staticmethod
    def create_form(
        name: str,
        visit_type: str,
        description: str | None = None,
        allow_faculty_customization: bool = False,
        creator_user: User = None
    ) -> tuple[RegistrationForm | None, str | None]:
        """Creates a registration form and initializes its version 1 in DRAFT status."""
        name = (name or '').strip()
        if not name:
            return None, "Form name is required."
        if not VisitType.is_valid(visit_type):
            return None, f"Invalid visit type '{visit_type}'. Allowed: {', '.join(VisitType.ALL)}."

        default_schema = [
            {
                "field_key": "purpose_detail",
                "label": "Detailed Agenda / Purpose",
                "field_type": "textarea",
                "is_required": True,
                "display_order": 1,
                "help_text": "Please provide details regarding the purpose of your visit.",
                "options": []
            }
        ]

        default_faculty_perms = {
            "purpose_detail": {
                "field_key": "purpose_detail",
                "allowed_properties": ["help_text", "label", "field_label"],
                "forbidden_properties": ["field_key", "field_type", "is_required"]
            }
        } if allow_faculty_customization else {}

        form = RegistrationForm(
            public_token=RegistrationForm.generate_public_token(),
            name=name,
            visit_type=visit_type,
            description=description.strip() if description else None,
            allow_faculty_customization=allow_faculty_customization,
            created_by_id=creator_user.id if creator_user else None
        )

        try:
            db.session.add(form)
            db.session.flush()

            v1 = FormVersion(
                form_id=form.id,
                version_number=1,
                status=FormVersionStatus.DRAFT,
                created_by_id=creator_user.id if creator_user else None
            )
            v1.set_schema(default_schema)
            v1.set_faculty_permissions(default_faculty_perms)

            db.session.add(v1)
            db.session.commit()

            AuditService.log_event(
                action='FORM_CREATE',
                entity_type='REGISTRATION_FORM',
                outcome=AuditOutcome.SUCCESS,
                actor_user_id=creator_user.id if creator_user else None,
                entity_reference=form.name,
                reason=f"Created form for visit type {visit_type}"
            )
            return form, None
        except Exception as e:
            db.session.rollback()
            return None, f"Error creating form: {str(e)}"

    @staticmethod
    def update_draft_schema(
        form_id: int,
        version_id: int,
        schema_data: list,
        faculty_permissions: dict | None = None,
        actor_user: User = None
    ) -> tuple[FormVersion | None, str | None]:
        """
        Updates a form schema. If the target version is already PUBLISHED,
        immutability is preserved by automatically branching a new DRAFT version.
        """
        valid, err = FormService.validate_schema(schema_data)
        if not valid:
            return None, err

        version = FormVersion.query.filter_by(id=version_id, form_id=form_id).first()
        if not version:
            return None, "Form version not found."

        try:
            if version.status in (FormVersionStatus.PUBLISHED, FormVersionStatus.ARCHIVED):
                # Immutability guarantee: fork into a new DRAFT version
                latest_num = db.session.query(db.func.max(FormVersion.version_number)).filter_by(form_id=form_id).scalar() or 1
                new_version = FormVersion(
                    form_id=form_id,
                    version_number=latest_num + 1,
                    status=FormVersionStatus.DRAFT,
                    created_by_id=actor_user.id
                )
                new_version.set_schema(schema_data)
                new_version.set_faculty_permissions(faculty_permissions if faculty_permissions is not None else version.get_faculty_permissions())
                db.session.add(new_version)
                db.session.commit()
                return new_version, None
            else:
                # Version is currently DRAFT
                version.set_schema(schema_data)
                if faculty_permissions is not None:
                    version.set_faculty_permissions(faculty_permissions)
                db.session.commit()
                return version, None
        except Exception as e:
            db.session.rollback()
            return None, f"Error saving schema: {str(e)}"

    @staticmethod
    def publish_version(form_id: int, version_id: int, actor_user: User) -> tuple[FormVersion | None, str | None]:
        """
        Atomically publishes a form version in a single transaction:
        1. Transitions any currently PUBLISHED versions for form_id to ARCHIVED.
        2. Sets target version to PUBLISHED with current UTC timestamp.
        3. Rolls back completely if any failure occurs, preserving existing published state.
        """
        form = db.session.get(RegistrationForm, form_id)
        if not form:
            return None, "Registration form not found."

        target_version = FormVersion.query.filter_by(id=version_id, form_id=form_id).first()
        if not target_version:
            return None, "Form version not found."

        if target_version.status == FormVersionStatus.PUBLISHED:
            return target_version, None  # Already active

        try:
            # 1. Archive previously published version(s) atomically
            currently_published = FormVersion.query.filter_by(
                form_id=form_id,
                status=FormVersionStatus.PUBLISHED
            ).all()

            for prev in currently_published:
                prev.status = FormVersionStatus.ARCHIVED

            # 2. Transition target version to PUBLISHED
            target_version.status = FormVersionStatus.PUBLISHED
            target_version.published_at = datetime.now(timezone.utc)

            db.session.commit()

            AuditService.log_event(
                action='FORM_PUBLISH',
                entity_type='FORM_VERSION',
                outcome=AuditOutcome.SUCCESS,
                actor_user_id=actor_user.id if actor_user else None,
                entity_reference=f"{form.name} (v{target_version.version_number})",
                reason=f"Published version {target_version.version_number}"
            )
            return target_version, None

        except Exception as e:
            db.session.rollback()
            return None, f"Atomic publish failed: {str(e)}"

    @staticmethod
    def unpublish_version(form_id: int, version_id: int, actor_user: User) -> tuple[FormVersion | None, str | None]:
        """
        Unpublishes a form version by transitioning it from PUBLISHED to DRAFT.
        When unpublished, public registrations using this form are denied until re-published.
        """
        form = db.session.get(RegistrationForm, form_id)
        if not form:
            return None, "Registration form not found."

        target_version = FormVersion.query.filter_by(id=version_id, form_id=form_id).first()
        if not target_version:
            return None, "Form version not found."

        if target_version.status != FormVersionStatus.PUBLISHED:
            return target_version, None

        try:
            target_version.status = FormVersionStatus.DRAFT
            db.session.commit()

            AuditService.log_event(
                action='FORM_UNPUBLISH',
                entity_type='FORM_VERSION',
                outcome=AuditOutcome.SUCCESS,
                actor_user_id=actor_user.id,
                entity_reference=f"{form.name} (v{target_version.version_number})",
                reason=f"Unpublished version {target_version.version_number}"
            )
            return target_version, None
        except Exception as e:
            db.session.rollback()
            return None, f"Unpublish failed: {str(e)}"

    @staticmethod
    def get_active_published_form(visit_type: str, auto_create_default: bool = True) -> tuple[RegistrationForm | None, FormVersion | None]:
        """Returns the active form and its active published version for a visit type."""
        forms = RegistrationForm.query.filter_by(
            visit_type=visit_type,
            is_active=True
        ).order_by(RegistrationForm.updated_at.desc(), RegistrationForm.id.desc()).all()

        for form in forms:
            pub_ver = form.published_version
            if pub_ver and pub_ver.status == FormVersionStatus.PUBLISHED:
                return form, pub_ver

        if auto_create_default and visit_type in VisitType.ALL:
            return FormService.ensure_default_published_form(visit_type)

        return None, None

    @staticmethod
    def ensure_default_published_form(visit_type: str) -> tuple[RegistrationForm | None, FormVersion | None]:
        """Ensures an active published form exists for a standard visit type."""
        if visit_type not in VisitType.ALL:
            return None, None

        # Re-check if any form for this visit_type already has a published version
        for form in RegistrationForm.query.filter_by(visit_type=visit_type, is_active=True).all():
            pub_ver = form.published_version
            if pub_ver and pub_ver.status == FormVersionStatus.PUBLISHED:
                return form, pub_ver

        admin_user = User.query.filter(User.role == 'ADMIN', User.is_active == True).first()
        if not admin_user:
            admin_user = User.query.first()

        defaults = {
            VisitType.GENERAL: (
                "General Campus Visitor Registration",
                "Online registration for prospective students, alumni, family members, and campus visitors.",
                [
                    {"field_key": "purpose_detail", "field_label": "Specific Department or Facility to Visit", "field_type": "text", "is_required": False, "help_text": "e.g., Admissions Office, Main Library, Computer Center"}
                ]
            ),
            VisitType.ACADEMIC: (
                "Academic & Seminar Guest Registration",
                "Registration for guest lecturers, visiting professors, workshop speakers, and academic researchers.",
                [
                    {"field_key": "academic_institution", "field_label": "Institution / University Affiliation", "field_type": "text", "is_required": True, "help_text": "Name of your university, institute, or lab"},
                    {"field_key": "host_department", "field_label": "Inviting Department", "field_type": "select", "options": ["Computer Science & Engineering", "Electrical & Electronics Engineering", "Mechanical Engineering", "Civil Engineering", "Biotechnology", "Business & Management", "Basic Sciences"], "is_required": True}
                ]
            ),
            VisitType.OFFICIAL: (
                "Official College Business Registration",
                "Registration for university officials, government delegations, accreditation auditors, and corporate recruiters.",
                [
                    {"field_key": "official_ref_number", "field_label": "Official Delegation / Invitation Ref", "field_type": "text", "is_required": False, "help_text": "Reference number from your invitation or appointment letter"}
                ]
            ),
            VisitType.CONTRACTOR: (
                "Vendor & Contractor Access Registration",
                "Registration for service technicians, maintenance crews, delivery drivers, and facilities contractors.",
                [
                    {"field_key": "contractor_company", "field_label": "Contractor / Vendor Agency Name", "field_type": "text", "is_required": True},
                    {"field_key": "work_permit_zone", "field_label": "Designated Work Zone", "field_type": "select", "options": ["Campus Grounds & Facilities", "Hostel Blocks", "Electrical Substation", "Academic Labs", "Sports Complex", "Administrative Block"], "is_required": True}
                ]
            ),
            VisitType.VIP: (
                "VIP & Distinguished Guest Registration",
                "Priority registration for distinguished dignitaries, keynote delegates, board trustees, and VIP guests.",
                [
                    {"field_key": "vip_designation", "field_label": "Official Title / Designation", "field_type": "text", "is_required": True, "help_text": "e.g., Keynote Speaker, Board of Governors, Government Dignitary"},
                    {"field_key": "vehicle_access", "field_label": "Campus Vehicle Gate Pass Needed", "field_type": "checkbox", "is_required": False}
                ]
            )
        }

        if visit_type not in defaults:
            return None, None

        name, desc, schema = defaults[visit_type]
        new_form, err = FormService.create_form(
            name=name,
            visit_type=visit_type,
            description=desc,
            allow_faculty_customization=(visit_type == VisitType.ACADEMIC),
            creator_user=admin_user
        )
        if err or not new_form:
            return None, None

        v1 = new_form.versions.first()
        if schema and v1:
            FormService.update_draft_schema(new_form.id, v1.id, schema, actor_user=admin_user)

        pub_ver, pub_err = FormService.publish_version(new_form.id, v1.id, actor_user=admin_user)
        if pub_err or not pub_ver:
            return new_form, v1

        return new_form, pub_ver

    @staticmethod
    def get_form_by_token_or_type(token_or_type: str) -> tuple[RegistrationForm | None, FormVersion | None]:
        """
        Resolves a registration form and its active published version by public form token or visit type.
        Returns: (form, published_version). If form is not found or unpublished, returns (form, None) or (None, None).
        """
        if not token_or_type:
            return None, None

        token_str = str(token_or_type).strip()

        # 1. First check if it matches a public_token (e.g. FORM-...)
        if token_str.startswith('FORM-'):
            form = RegistrationForm.query.filter_by(public_token=token_str, is_active=True).first()
            if form:
                return form, form.published_version
            return None, None

        # 2. Check if it matches a known visit type (e.g. OFFICIAL, GENERAL)
        if token_str in VisitType.ALL:
            return FormService.get_active_published_form(token_str)

        # 3. Fallback search by public_token in case prefix differs
        form = RegistrationForm.query.filter_by(public_token=token_str, is_active=True).first()
        if form:
            return form, form.published_version

        return None, None

    @staticmethod
    def is_faculty_property_allowed(faculty_permissions: dict, field_key: str, property_name: str) -> bool:
        """
        Validates whether a specific property on a field is permitted for faculty modification.
        Protected properties (field_key, field_type, is_required) are unconditionally forbidden.
        """
        FORBIDDEN_PROPERTIES = {'field_key', 'field_type', 'is_required'}
        if property_name in FORBIDDEN_PROPERTIES:
            return False

        if not isinstance(faculty_permissions, dict):
            return False

        field_perm = None
        if field_key in faculty_permissions:
            field_perm = faculty_permissions[field_key]
        else:
            # Fallback search if any entry in dictionary has matching 'field_key'
            for val in faculty_permissions.values():
                if isinstance(val, dict) and val.get('field_key') == field_key:
                    field_perm = val
                    break

        if not field_perm:
            return False

        # Support alias: 'label' and 'field_label' refer to the display label
        canonical_prop = 'label' if property_name in ('label', 'field_label') else property_name

        if isinstance(field_perm, list):
            props = set(field_perm)
            if 'field_label' in props:
                props.add('label')
            if 'label' in props:
                props.add('field_label')
            return property_name in props or canonical_prop in props
        elif isinstance(field_perm, dict):
            allowed = set(field_perm.get('allowed_properties', []))
            forbidden = set(field_perm.get('forbidden_properties', []))
            if 'field_label' in allowed:
                allowed.add('label')
            if 'label' in allowed:
                allowed.add('field_label')
            if property_name in forbidden or canonical_prop in forbidden:
                return False
            return property_name in allowed or canonical_prop in allowed

        return False

    @staticmethod
    def update_faculty_customization(
        form_id: int,
        customizations: dict,
        actor_user: User
    ) -> tuple[FormVersion | None, str | None, int]:
        """
        Validates and applies faculty customization to a registration form.
        Enforces property-level validation against faculty_permitted_fields_json.
        Rejects forbidden properties and unauthorized field changes with 403.
        Returns: (version, error_message, status_code)
        """
        form = db.session.get(RegistrationForm, form_id)
        if not form:
            return None, "Form not found.", 404

        if not form.allow_faculty_customization:
            AuditService.log_event(
                action='UNAUTHORIZED_ACCESS',
                entity_type='REGISTRATION_FORM',
                outcome=AuditOutcome.FAILURE,
                actor_user_id=actor_user.id,
                entity_reference=form.name,
                reason="Faculty attempted to customize form with customization disabled"
            )
            return None, "Faculty customization is not permitted for this form.", 403

        # Use published version or latest draft
        version = form.published_version or form.versions.order_by(FormVersion.version_number.desc()).first()
        if not version:
            return None, "No form version available to customize.", 404

        schema = version.get_schema()
        faculty_perms = version.get_faculty_permissions()

        if not isinstance(customizations, dict):
            return None, "Invalid customizations payload format.", 400

        # Check each requested change
        for field_key, props in customizations.items():
            if not isinstance(props, dict):
                return None, f"Customization for '{field_key}' must be a dictionary.", 400

            for prop_name, prop_val in props.items():
                if not FormService.is_faculty_property_allowed(faculty_perms, field_key, prop_name):
                    AuditService.log_event(
                        action='UNAUTHORIZED_ACCESS',
                        entity_type='FORM_VERSION',
                        outcome=AuditOutcome.FAILURE,
                        actor_user_id=actor_user.id,
                        entity_reference=f"{form.name} (v{version.version_number})",
                        reason=f"Forbidden modification to property '{prop_name}' on field '{field_key}'"
                    )
                    return None, f"Modifying property '{prop_name}' on field '{field_key}' is forbidden.", 403

        # Apply valid modifications to schema copy
        new_schema = []
        for field in schema:
            f_copy = dict(field)
            f_key = f_copy.get('field_key')
            if f_key in customizations:
                for prop_name, prop_val in customizations[f_key].items():
                    if prop_name in ('label', 'field_label'):
                        f_copy['field_label'] = prop_val
                        f_copy['label'] = prop_val
                    else:
                        f_copy[prop_name] = prop_val
            new_schema.append(f_copy)

        saved_version, err = FormService.update_draft_schema(
            form_id=form.id,
            version_id=version.id,
            schema_data=new_schema,
            faculty_permissions=faculty_perms,
            actor_user=actor_user
        )
        if err:
            return None, err, 400

        AuditService.log_event(
            action='FACULTY_FORM_CUSTOMIZE',
            entity_type='FORM_VERSION',
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user.id,
            entity_reference=f"{form.name} (v{saved_version.version_number})",
            reason=f"Faculty applied customizations to version {saved_version.version_number}"
        )
        return saved_version, None, 200

