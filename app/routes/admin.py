from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, Response
from flask_login import current_user
from app.extensions import db
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog, AuditAction, AuditOutcome
from app.models.visit import VisitRequest, VisitRequestStatus, VisitSession, VisitSessionStatus
from app.models.visit_type import VisitType
from app.services.auth_service import role_required
from app.services.approval_service import ApprovalService
from app.services.gate_service import GateService
from app.services.report_service import ReportService
from app.services.rate_limiter import rate_limit

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/dashboard')
@role_required(UserRole.ADMIN)
def dashboard():
    """Admin operational command center dashboard."""
    # Query real database records
    total_staff = User.query.count()
    active_staff = User.query.filter_by(is_active=True).count()
    recent_audits = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()
    
    total_requests = VisitRequest.query.count()
    pending_approvals = VisitRequest.query.filter_by(status=VisitRequestStatus.PENDING_APPROVAL).count()
    approved_visits = VisitRequest.query.filter_by(status=VisitRequestStatus.APPROVED).count()

    kpis = {
        'total_requests': total_requests,
        'pending_approvals': pending_approvals,
        'approved_visits': approved_visits,
        'active_occupancy': GateService.get_current_occupancy(),
        'total_staff': total_staff,
        'active_staff': active_staff
    }

    recent_requests = VisitRequest.query.order_by(VisitRequest.submitted_at.desc()).limit(6).all()

    return render_template(
        'admin/dashboard.html',
        kpis=kpis,
        recent_audits=recent_audits,
        recent_requests=recent_requests,
        title="Admin Overview"
    )


@admin_bp.route('/staff', methods=['GET', 'POST'])
@role_required(UserRole.ADMIN)
def staff_list():
    """List staff accounts or create a new staff account."""
    from flask import request, redirect, url_for, flash
    from app.services.user_service import UserService

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        role = request.form.get('role')
        department = request.form.get('department')
        password = request.form.get('password')

        user, err = UserService.create_staff_user(
            username=username,
            email=email,
            full_name=full_name,
            role=role,
            department=department,
            password=password,
            actor_user=current_user
        )
        if err:
            flash(err, 'danger')
        else:
            flash(f"Staff account '{user.username}' created successfully.", 'success')
            return redirect(url_for('admin.staff_list'))

    role_filter = request.args.get('role')
    status_filter = request.args.get('status')
    search_query = request.args.get('q')

    is_active = None
    if status_filter == 'active':
        is_active = True
    elif status_filter == 'inactive':
        is_active = False

    staff_members = UserService.list_users(role=role_filter, is_active=is_active, search=search_query)

    kpis = {
        'total': User.query.count(),
        'admins': User.query.filter_by(role=UserRole.ADMIN).count(),
        'faculty': User.query.filter_by(role=UserRole.FACULTY).count(),
        'security': User.query.filter_by(role=UserRole.SECURITY).count(),
    }

    return render_template(
        'admin/staff.html',
        staff_members=staff_members,
        kpis=kpis,
        roles=UserRole.ALL,
        role_filter=role_filter,
        status_filter=status_filter,
        search_query=search_query,
        title="Staff Management"
    )


@admin_bp.route('/staff/<int:user_id>', methods=['GET', 'POST'])
@role_required(UserRole.ADMIN)
def staff_edit(user_id):
    """Edit existing staff account details."""
    from flask import request, redirect, url_for, flash, abort
    from app.services.user_service import UserService

    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        department = request.form.get('department')
        role = request.form.get('role')
        is_active = request.form.get('is_active') == '1'

        updated_user, err = UserService.update_staff_user(
            user_id=user.id,
            full_name=full_name,
            email=email,
            department=department,
            role=role,
            is_active=is_active,
            actor_user=current_user
        )
        if err:
            flash(err, 'danger')
        else:
            flash(f"Staff account '{updated_user.username}' updated successfully.", 'success')
            return redirect(url_for('admin.staff_list'))

    return render_template(
        'admin/staff_edit.html',
        target_user=user,
        roles=UserRole.ALL,
        title=f"Edit Staff: {user.username}"
    )


@admin_bp.route('/staff/<int:user_id>/toggle', methods=['POST'])
@role_required(UserRole.ADMIN)
def staff_toggle(user_id):
    """Toggle staff account active status."""
    from flask import redirect, url_for, flash
    from app.services.user_service import UserService

    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    new_status = not user.is_active

    updated_user, err = UserService.update_staff_user(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        department=user.department,
        role=user.role,
        is_active=new_status,
        actor_user=current_user
    )
    if err:
        flash(err, 'danger')
    else:
        status_word = "activated" if new_status else "deactivated"
        flash(f"Account '{user.username}' {status_word} successfully.", 'success')

    return redirect(url_for('admin.staff_list'))


@admin_bp.route('/forms', methods=['GET', 'POST'])
@role_required(UserRole.ADMIN)
def forms_list():
    """List registration forms or create a new registration form."""
    import json
    from flask import request, redirect, url_for, flash
    from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
    from app.models.visit_type import VisitType
    from app.services.form_service import FormService

    if request.method == 'POST':
        name = request.form.get('name')
        visit_type = request.form.get('visit_type')
        description = request.form.get('description')
        allow_custom = request.form.get('allow_faculty_customization') == '1'

        form, err = FormService.create_form(
            name=name,
            visit_type=visit_type,
            description=description,
            allow_faculty_customization=allow_custom,
            creator_user=current_user
        )
        if err:
            flash(err, 'danger')
        else:
            flash(f"Form '{form.name}' created with initial Draft Version 1.", 'success')
            v1 = form.versions.first()
            return redirect(url_for('admin.form_builder', form_id=form.id, version_id=v1.id))

    forms = RegistrationForm.query.order_by(RegistrationForm.created_at.desc()).all()

    return render_template(
        'admin/forms.html',
        forms=forms,
        visit_types=VisitType.ALL,
        title="Form Builder Manager"
    )


@admin_bp.route('/forms/<int:form_id>/versions/<int:version_id>', methods=['GET'])
@role_required(UserRole.ADMIN)
def form_builder(form_id, version_id):
    """Visual form schema builder for a specific form version."""
    import json
    from flask import render_template
    from app.models.registration_form import RegistrationForm, FormVersion
    from app.services.form_service import ALLOWED_FIELD_TYPES

    form = db.session.get(RegistrationForm, form_id)
    if not form:
        abort(404)
    version = FormVersion.query.filter_by(id=version_id, form_id=form.id).first()
    if not version:
        abort(404)

    return render_template(
        'admin/form_builder.html',
        form=form,
        version=version,
        schema=version.get_schema(),
        faculty_permissions=version.get_faculty_permissions(),
        schema_json_pretty=json.dumps(version.get_schema(), indent=2),
        faculty_permissions_pretty=json.dumps(version.get_faculty_permissions(), indent=2),
        allowed_field_types=ALLOWED_FIELD_TYPES,
        title=f"Builder: {form.name} (v{version.version_number})"
    )


@admin_bp.route('/forms/<int:form_id>/versions/<int:version_id>/save', methods=['POST'])
@role_required(UserRole.ADMIN)
def form_save(form_id, version_id):
    """Save schema updates. Automatically forks a new draft if target version was published."""
    import json
    from flask import request, redirect, url_for, flash
    from app.services.form_service import FormService

    schema_json_raw = request.form.get('schema_json')
    faculty_perms_raw = request.form.get('faculty_permissions_json')

    try:
        schema_data = json.loads(schema_json_raw) if schema_json_raw else []
    except Exception as e:
        flash(f"Invalid schema JSON format: {str(e)}", 'danger')
        return redirect(url_for('admin.form_builder', form_id=form_id, version_id=version_id))

    faculty_perms = None
    if faculty_perms_raw and faculty_perms_raw.strip():
        try:
            faculty_perms = json.loads(faculty_perms_raw)
        except Exception as e:
            flash(f"Invalid faculty permissions JSON format: {str(e)}", 'danger')
            return redirect(url_for('admin.form_builder', form_id=form_id, version_id=version_id))

    saved_version, err = FormService.update_draft_schema(
        form_id=form_id,
        version_id=version_id,
        schema_data=schema_data,
        faculty_permissions=faculty_perms,
        actor_user=current_user
    )
    if err:
        flash(err, 'danger')
        return redirect(url_for('admin.form_builder', form_id=form_id, version_id=version_id))

    if saved_version.id != version_id:
        flash(f"Historical version preserved. Created new Draft Version {saved_version.version_number}.", 'info')
    else:
        flash("Draft schema saved successfully.", 'success')

    return redirect(url_for('admin.form_builder', form_id=form_id, version_id=saved_version.id))


@admin_bp.route('/forms/<int:form_id>/versions/<int:version_id>/publish', methods=['POST'])
@role_required(UserRole.ADMIN)
def form_publish(form_id, version_id):
    """Atomically publish form version."""
    from flask import redirect, url_for, flash
    from app.services.form_service import FormService

    published_ver, err = FormService.publish_version(
        form_id=form_id,
        version_id=version_id,
        actor_user=current_user
    )
    if err:
        flash(err, 'danger')
    else:
        flash(f"Version {published_ver.version_number} is now active and published for public registration.", 'success')

    return redirect(url_for('admin.form_builder', form_id=form_id, version_id=version_id))


@admin_bp.route('/forms/<int:form_id>/versions/<int:version_id>/unpublish', methods=['POST'])
@role_required(UserRole.ADMIN)
def form_unpublish(form_id, version_id):
    """Unpublish an active form version."""
    from flask import redirect, url_for, flash
    from app.services.form_service import FormService

    unpub_ver, err = FormService.unpublish_version(
        form_id=form_id,
        version_id=version_id,
        actor_user=current_user
    )
    if err:
        flash(err, 'danger')
    else:
        flash(f"Version {unpub_ver.version_number} has been unpublished. Public registrations for this category are now paused.", 'info')

    return redirect(url_for('admin.form_builder', form_id=form_id, version_id=version_id))


@admin_bp.route('/forms/<int:form_id>/versions/<int:version_id>/preview', methods=['GET'])
@role_required(UserRole.ADMIN)
def form_preview(form_id, version_id):
    """Full-page live preview of a registration form version with submissions disabled."""
    from app.models.registration_form import RegistrationForm, FormVersion
    from app.models.user import UserRole

    form = db.session.get(RegistrationForm, form_id)
    if not form:
        abort(404)
    version = FormVersion.query.filter_by(id=version_id, form_id=form.id).first()
    if not version:
        abort(404)

    eligible_hosts = User.query.filter(
        User.role.in_([UserRole.FACULTY, UserRole.ADMIN]),
        User.is_active == True
    ).order_by(User.full_name.asc()).all()

    return render_template(
        'visitors/register.html',
        form=form,
        version=version,
        schema=version.get_schema(),
        visit_type=form.visit_type,
        hosts=eligible_hosts,
        is_preview=True,
        title=f"Preview: {form.name} (v{version.version_number})"
    )


@admin_bp.route('/visits', methods=['GET'])
@admin_bp.route('/requests', methods=['GET'])
@role_required(UserRole.ADMIN)
def visits_list():
    """List visitor requests across all campus hosts with filtering."""
    status_filter = request.args.get('status', '').strip().upper() or None
    visit_type_filter = request.args.get('visit_type', '').strip().upper() or None
    host_id_raw = request.args.get('host_id', '').strip()
    host_id = int(host_id_raw) if host_id_raw.isdigit() else None

    requests = ApprovalService.get_admin_requests(
        status_filter=status_filter,
        visit_type_filter=visit_type_filter,
        host_user_id=host_id
    )

    counts = {
        'all': VisitRequest.query.count(),
        'pending': VisitRequest.query.filter_by(status=VisitRequestStatus.PENDING_APPROVAL).count(),
        'approved': VisitRequest.query.filter_by(status=VisitRequestStatus.APPROVED).count(),
        'rejected': VisitRequest.query.filter_by(status=VisitRequestStatus.REJECTED).count(),
    }

    eligible_hosts = User.query.filter(
        User.role.in_([UserRole.FACULTY, UserRole.ADMIN]),
        User.is_active == True
    ).order_by(User.full_name.asc()).all()

    return render_template(
        'admin/visits.html',
        requests=requests,
        counts=counts,
        current_status=status_filter,
        current_visit_type=visit_type_filter,
        current_host_id=host_id,
        eligible_hosts=eligible_hosts,
        visit_types=VisitType.ALL,
        title="Campus Visitor Requests"
    )


@admin_bp.route('/visits/<int:request_id>/approve', methods=['POST'])
@role_required(UserRole.ADMIN)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def visit_approve(request_id):
    """Approve a pending visitor request as Administrator."""
    req, err = ApprovalService.approve_request(
        request_id=request_id,
        actor_user=current_user,
        actor_ip=request.remote_addr
    )
    if err:
        flash(err, 'danger')
    else:
        flash(f"Visit request for {req.visitor.full_name if req.visitor else 'visitor'} has been approved.", "success")
    return redirect(url_for('admin.visits_list'))


@admin_bp.route('/visits/<int:request_id>/reject', methods=['POST'])
@role_required(UserRole.ADMIN)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def visit_reject(request_id):
    """Reject a pending visitor request as Administrator."""
    reason = request.form.get('reason')
    req, err = ApprovalService.reject_request(
        request_id=request_id,
        actor_user=current_user,
        reason=reason,
        actor_ip=request.remote_addr
    )
    if err:
        flash(err, 'danger')
    else:
        flash(f"Visit request for {req.visitor.full_name if req.visitor else 'visitor'} has been rejected.", "info")
    return redirect(url_for('admin.visits_list'))


@admin_bp.route('/visits/<int:request_id>/reissue-qr', methods=['POST'])
@role_required(UserRole.ADMIN)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def visit_reissue_qr(request_id):
    """Reissue QR credential for an approved visit request as Administrator."""
    from app.services.qr_service import QRService

    reason = request.form.get('reason', 'Administrative reissue')
    cred, raw_token, err = QRService.reissue_credential(
        request_id=request_id,
        actor_user=current_user,
        reason=reason
    )
    if err:
        flash(err, 'danger')
    else:
        flash("A replacement QR credential has been generated and the previous credential was revoked.", "success")
    return redirect(url_for('admin.visits_list'))


@admin_bp.route('/visits/<int:request_id>/revoke-qr', methods=['POST'])
@role_required(UserRole.ADMIN)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def visit_revoke_qr(request_id):
    """Revoke active QR credential for a visit request as Administrator."""
    from app.services.qr_service import QRService

    req = db.session.get(VisitRequest, request_id)
    if not req or not req.active_credential:
        flash("No active credential found to revoke.", "warning")
        return redirect(url_for('admin.visits_list'))

    reason = request.form.get('reason', 'Administrative revocation')
    cred, err = QRService.revoke_credential(
        credential_id=req.active_credential.id,
        actor_user=current_user,
        reason=reason
    )
    if err:
        flash(err, 'danger')
    else:
        flash("The visitor's active QR credential has been revoked.", "info")
    return redirect(url_for('admin.visits_list'))


@admin_bp.route('/reports')
@role_required(UserRole.ADMIN)
def reports():
    """Administrative visitor analytics and filtered reporting center."""
    start_str = request.args.get('start_date', '')
    end_str = request.args.get('end_date', '')
    status = request.args.get('status', '')
    visit_type = request.args.get('visit_type', '')
    host_id = request.args.get('host_id', type=int)
    session_status = request.args.get('session_status', '')
    page = request.args.get('page', 1, type=int)

    start_dt = ReportService.parse_date(start_str)
    end_dt = ReportService.parse_date(end_str)

    summary = ReportService.get_summary_metrics(
        start_date=start_dt,
        end_date=end_dt,
        visit_type=visit_type,
        host_id=host_id
    )

    query = ReportService.get_filtered_query(
        start_date=start_dt,
        end_date=end_dt,
        status=status,
        visit_type=visit_type,
        host_id=host_id,
        session_status=session_status
    )

    visits_paginated = query.paginate(page=page, per_page=20, error_out=False)

    hosts = User.query.filter_by(role=UserRole.FACULTY, is_active=True).order_by(User.full_name).all()
    visit_types = VisitType.ALL

    return render_template(
        'admin/reports.html',
        summary=summary,
        visits=visits_paginated,
        hosts=hosts,
        visit_types=visit_types,
        selected_start=start_str,
        selected_end=end_str,
        selected_status=status,
        selected_visit_type=visit_type,
        selected_host_id=host_id,
        selected_session_status=session_status,
        title="Visitor Analytics & Reports"
    )


@admin_bp.route('/reports/export.csv')
@role_required(UserRole.ADMIN)
def reports_export_csv():
    """Generates and downloads a formula-injection-safe CSV export of filtered visit records."""
    start_str = request.args.get('start_date', '')
    end_str = request.args.get('end_date', '')
    status = request.args.get('status', '')
    visit_type = request.args.get('visit_type', '')
    host_id = request.args.get('host_id', type=int)
    session_status = request.args.get('session_status', '')

    start_dt = ReportService.parse_date(start_str)
    end_dt = ReportService.parse_date(end_str)

    csv_data = ReportService.export_visits_to_csv(
        start_date=start_dt,
        end_date=end_dt,
        status=status,
        visit_type=visit_type,
        host_id=host_id,
        session_status=session_status
    )

    # Log CSV export audit event
    log = AuditLog(
        actor_user_id=current_user.id,
        action=AuditAction.REPORT_EXPORTED,
        entity_type='REPORT',
        entity_reference='Visitor Management CSV Export',
        outcome=AuditOutcome.SUCCESS,
        ip_address=request.remote_addr
    )
    log.set_metadata({
        'start_date': start_str,
        'end_date': end_str,
        'status': status,
        'visit_type': visit_type,
        'host_id': host_id
    })
    db.session.add(log)
    db.session.commit()

    filename = f"visitor_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"
        }
    )


@admin_bp.route('/emergency-list')
@role_required(UserRole.ADMIN)
def emergency_list():
    """Admin view of current campus emergency evacuation muster roll."""
    return redirect(url_for('security.emergency_list'))


@admin_bp.route('/audit')
@role_required(UserRole.ADMIN)
def audit_trail():
    """Administrative security and compliance audit log viewer."""
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action', '')
    user_filter = request.args.get('user_id', type=int)

    query = AuditLog.query

    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if user_filter:
        query = query.filter(AuditLog.actor_user_id == user_filter)

    logs_paginated = query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    users = User.query.order_by(User.full_name).all()

    return render_template(
        'admin/audit.html',
        logs=logs_paginated,
        users=users,
        selected_action=action_filter,
        selected_user=user_filter,
        title="Security Audit Trail"
    )


@admin_bp.route('/sessions/<int:session_id>/edit', methods=['POST'])
@role_required(UserRole.ADMIN)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def session_edit(session_id):
    """Administratively edit/correct a visitor check-in/out session."""
    import zoneinfo
    from flask import current_app

    status = request.form.get('status', '').strip().upper()
    checked_in_raw = request.form.get('checked_in_at', '').strip()
    checked_out_raw = request.form.get('checked_out_at', '').strip()
    reason = request.form.get('reason', '').strip()
    redirect_target = request.form.get('redirect_to') or url_for('admin.reports')

    app_tz_name = current_app.config.get('APP_TIMEZONE', 'Asia/Kolkata')
    try:
        local_tz = zoneinfo.ZoneInfo(app_tz_name)
    except Exception:
        local_tz = timezone.utc

    checked_in_dt = None
    if checked_in_raw:
        try:
            naive_in = datetime.fromisoformat(checked_in_raw)
            checked_in_dt = naive_in.replace(tzinfo=local_tz).astimezone(timezone.utc)
        except Exception:
            flash("Invalid format for check-in timestamp.", "danger")
            return redirect(redirect_target)

    checked_out_dt = None
    if checked_out_raw and status == VisitSessionStatus.COMPLETED:
        try:
            naive_out = datetime.fromisoformat(checked_out_raw)
            checked_out_dt = naive_out.replace(tzinfo=local_tz).astimezone(timezone.utc)
        except Exception:
            flash("Invalid format for check-out timestamp.", "danger")
            return redirect(redirect_target)

    sess, err = GateService.correct_session(
        session_id=session_id,
        actor_user=current_user,
        checked_in_at=checked_in_dt,
        checked_out_at=checked_out_dt,
        status=status,
        reason=reason,
        client_ip=request.remote_addr
    )

    if err:
        flash(err, 'danger')
    else:
        flash(f"Visit session #{session_id} successfully updated with audit record.", 'success')

    return redirect(redirect_target)




