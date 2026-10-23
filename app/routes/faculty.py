from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user
from app.extensions import db
from app.models.user import UserRole
from app.models.visit import VisitRequest, VisitRequestStatus
from app.models.audit_log import AuditAction, AuditOutcome
from app.services.auth_service import role_required
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.rate_limiter import rate_limit

faculty_bp = Blueprint('faculty', __name__, url_prefix='/faculty')


@faculty_bp.route('/dashboard')
@role_required(UserRole.FACULTY)
def dashboard():
    """Faculty workspace for review and upcoming visits."""
    pending_count = VisitRequest.query.filter_by(
        host_user_id=current_user.id,
        status=VisitRequestStatus.PENDING_APPROVAL
    ).count()
    approved_count = VisitRequest.query.filter_by(
        host_user_id=current_user.id,
        status=VisitRequestStatus.APPROVED
    ).count()
    total_hosted = VisitRequest.query.filter_by(
        host_user_id=current_user.id
    ).count()

    kpis = {
        'pending_requests': pending_count,
        'approved_upcoming': approved_count,
        'total_hosted': total_hosted
    }

    recent_requests = VisitRequest.query.filter_by(
        host_user_id=current_user.id
    ).order_by(VisitRequest.submitted_at.desc()).limit(5).all()

    return render_template(
        'faculty/dashboard.html',
        kpis=kpis,
        recent_requests=recent_requests,
        title="Faculty Workspace"
    )


@faculty_bp.route('/forms', methods=['GET'])
@role_required(UserRole.FACULTY)
def forms_list():
    """List registration forms that permit faculty customization."""
    from app.models.registration_form import RegistrationForm

    forms = RegistrationForm.query.filter_by(
        is_active=True,
        allow_faculty_customization=True
    ).order_by(RegistrationForm.created_at.desc()).all()

    return render_template(
        'faculty/forms.html',
        forms=forms,
        title="Customizable Registration Forms"
    )


@faculty_bp.route('/forms/<int:form_id>/customize', methods=['GET', 'POST'])
@role_required(UserRole.FACULTY)
def form_customize(form_id):
    """View and update permitted form properties."""
    import json
    from flask import request, redirect, url_for, flash, abort
    from app.extensions import db
    from app.models.registration_form import RegistrationForm, FormVersion
    from app.services.form_service import FormService

    form = db.session.get(RegistrationForm, form_id)
    if not form:
        abort(404)

    if not form.allow_faculty_customization:
        flash("Faculty customization is not permitted for this registration form.", "danger")
        return redirect(url_for('faculty.forms_list'))

    version = form.published_version or form.versions.order_by(FormVersion.version_number.desc()).first()
    if not version:
        abort(404)

    schema = version.get_schema()
    faculty_perms = version.get_faculty_permissions()

    if request.method == 'POST':
        # Accept either JSON body or form submission
        if request.is_json:
            customizations = request.get_json() or {}
        else:
            # Parse form fields: custom__{field_key}__{prop}
            customizations = {}
            for key, val in request.form.items():
                if key.startswith('custom__'):
                    parts = key.split('__')
                    if len(parts) == 3:
                        _, f_key, prop = parts
                        if f_key not in customizations:
                            customizations[f_key] = {}
                        customizations[f_key][prop] = val.strip()

        saved_version, err, status_code = FormService.update_faculty_customization(
            form_id=form.id,
            customizations=customizations,
            actor_user=current_user
        )

        if status_code == 403:
            abort(403, description=err or "Forbidden property modification.")

        if err:
            flash(err, 'danger')
            return redirect(url_for('faculty.form_customize', form_id=form.id))

        flash("Your customizations have been saved successfully.", "success")
        return redirect(url_for('faculty.forms_list'))

    return render_template(
        'faculty/form_customize.html',
        form=form,
        version=version,
        schema=schema,
        faculty_permissions=faculty_perms,
        title=f"Customize Form: {form.name}"
    )


@faculty_bp.route('/requests', methods=['GET'])
@role_required(UserRole.FACULTY)
def requests_list():
    """List visitor requests assigned to the logged-in faculty member."""
    status_filter = request.args.get('status', '').strip().upper() or None
    requests = ApprovalService.get_faculty_requests(current_user, status_filter=status_filter)

    counts = {
        'all': VisitRequest.query.filter_by(host_user_id=current_user.id).count(),
        'pending': VisitRequest.query.filter_by(host_user_id=current_user.id, status=VisitRequestStatus.PENDING_APPROVAL).count(),
        'approved': VisitRequest.query.filter_by(host_user_id=current_user.id, status=VisitRequestStatus.APPROVED).count(),
        'rejected': VisitRequest.query.filter_by(host_user_id=current_user.id, status=VisitRequestStatus.REJECTED).count(),
    }

    return render_template(
        'faculty/requests.html',
        requests=requests,
        counts=counts,
        current_status=status_filter,
        title="Visitor Requests Review"
    )




@faculty_bp.route('/requests/<int:request_id>/approve', methods=['POST'])
@role_required(UserRole.FACULTY)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def request_approve(request_id):
    """Approve a pending visitor request."""
    req = db.session.get(VisitRequest, request_id)
    if not req:
        flash("Visit request not found.", "danger")
        return redirect(url_for('faculty.requests_list'))

    if req.host_user_id != current_user.id:
        AuditService.log_event(
            action=AuditAction.UNAUTHORIZED_ACCESS,
            entity_type='VISIT_REQUEST',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=current_user.id,
            reason=f"Faculty user {current_user.username} attempted to approve request belonging to host {req.host_user_id}",
            ip_address=request.remote_addr
        )
        abort(403, description="You are only authorized to review visitor requests assigned to you.")

    req, err = ApprovalService.approve_request(
        request_id=request_id,
        actor_user=current_user,
        actor_ip=request.remote_addr
    )
    if err:
        flash(err, 'danger')
    else:
        flash(f"Visit request for {req.visitor.full_name if req.visitor else 'visitor'} has been approved.", "success")
    return redirect(url_for('faculty.requests_list'))


@faculty_bp.route('/requests/<int:request_id>/reject', methods=['POST'])
@role_required(UserRole.FACULTY)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def request_reject(request_id):
    """Reject a pending visitor request with a reason."""
    req = db.session.get(VisitRequest, request_id)
    if not req:
        flash("Visit request not found.", "danger")
        return redirect(url_for('faculty.requests_list'))

    if req.host_user_id != current_user.id:
        AuditService.log_event(
            action=AuditAction.UNAUTHORIZED_ACCESS,
            entity_type='VISIT_REQUEST',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=current_user.id,
            reason=f"Faculty user {current_user.username} attempted to reject request belonging to host {req.host_user_id}",
            ip_address=request.remote_addr
        )
        abort(403, description="You are only authorized to review visitor requests assigned to you.")

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
    return redirect(url_for('faculty.requests_list'))


@faculty_bp.route('/requests/<int:request_id>/reissue-qr', methods=['POST'])
@role_required(UserRole.FACULTY)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def request_reissue_qr(request_id):
    """Reissue QR credential for a hosted approved visit request."""
    from app.services.qr_service import QRService

    req = db.session.get(VisitRequest, request_id)
    if not req:
        flash("Visit request not found.", "danger")
        return redirect(url_for('faculty.requests_list'))

    if req.host_user_id != current_user.id:
        AuditService.log_event(
            action=AuditAction.UNAUTHORIZED_ACCESS,
            entity_type='VISIT_REQUEST',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=current_user.id,
            reason=f"Faculty {current_user.username} attempted to reissue QR for foreign request {req.id}",
            ip_address=request.remote_addr
        )
        abort(403, description="You are only authorized to manage visitor requests assigned to you.")

    reason = request.form.get('reason', 'Host requested reissue')
    cred, raw_token, err = QRService.reissue_credential(
        request_id=request_id,
        actor_user=current_user,
        reason=reason
    )
    if err:
        flash(err, 'danger')
    else:
        flash("A replacement QR credential has been generated and the previous credential was revoked.", "success")
    return redirect(url_for('faculty.requests_list'))


@faculty_bp.route('/requests/<int:request_id>/revoke-qr', methods=['POST'])
@role_required(UserRole.FACULTY)
@rate_limit('RATE_LIMIT_APPROVAL', methods=['POST'])
def request_revoke_qr(request_id):
    """Revoke active QR credential for a hosted visit request."""
    from app.services.qr_service import QRService

    req = db.session.get(VisitRequest, request_id)
    if not req:
        flash("Visit request not found.", "danger")
        return redirect(url_for('faculty.requests_list'))

    if req.host_user_id != current_user.id:
        AuditService.log_event(
            action=AuditAction.UNAUTHORIZED_ACCESS,
            entity_type='VISIT_REQUEST',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=current_user.id,
            reason=f"Faculty {current_user.username} attempted to revoke QR for foreign request {req.id}",
            ip_address=request.remote_addr
        )
        abort(403, description="You are only authorized to manage visitor requests assigned to you.")

    if not req.active_credential:
        flash("No active credential found to revoke.", "warning")
        return redirect(url_for('faculty.requests_list'))

    reason = request.form.get('reason', 'Host requested revocation')
    cred, err = QRService.revoke_credential(
        credential_id=req.active_credential.id,
        actor_user=current_user,
        reason=reason
    )
    if err:
        flash(err, 'danger')
    else:
        flash("The visitor's active QR credential has been revoked.", "info")
    return redirect(url_for('faculty.requests_list'))


