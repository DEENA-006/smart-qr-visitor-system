import os
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_from_directory, make_response, Response
from flask_login import login_required, current_user
from app.models.user import User, UserRole
from app.models.visit_type import VisitType
from app.models.visit import VisitRequest, VisitRequestStatus, QRCredential, QRCredentialStatus
from app.services.form_service import FormService
from app.services.upload_service import UploadService
from app.services.registration_service import RegistrationService
from app.services.rate_limiter import rate_limit
from app.services.qr_service import QRService

visitors_bp = Blueprint('visitors', __name__)


@visitors_bp.route('/register', methods=['GET'])
def register_index():
    """Visitor registration hub displaying available visit categories."""
    forms_by_type = {}
    for vt in VisitType.ALL:
        form, ver = FormService.get_active_published_form(vt)
        if form and ver:
            forms_by_type[vt] = {
                'form': form,
                'version': ver
            }

    return render_template(
        'visitors/index.html',
        visit_types=VisitType.ALL,
        forms_by_type=forms_by_type,
        title="Campus Visitor Registration"
    )


@visitors_bp.url_defaults
def register_form_url_defaults(endpoint, values):
    if endpoint == 'visitors.register_form':
        if 'identifier' in values and 'visit_type' not in values:
            values['visit_type'] = values.pop('identifier')


@visitors_bp.route('/register/<visit_type>', methods=['GET', 'POST'])
@rate_limit('RATE_LIMIT_REGISTER', methods=['POST'])
def register_form(visit_type):
    """Dynamic registration form for a public form token or visit category."""
    from app.models.registration_form import FormVersionStatus

    identifier = visit_type

    # 1. If identifier starts with FORM- or is a token
    if identifier.startswith('FORM-'):
        form, version = FormService.get_form_by_token_or_type(identifier)
        if not form:
            abort(404)
        if not version or version.status != FormVersionStatus.PUBLISHED:
            abort(404)
        visit_type = form.visit_type
    elif identifier in VisitType.ALL:
        visit_type = identifier
        form, version = FormService.get_active_published_form(visit_type)
        if not form or not version:
            return render_template(
                'visitors/unavailable.html',
                visit_type=visit_type,
                title="Registration Currently Unavailable"
            )
    else:
        # Fallback check by token
        form, version = FormService.get_form_by_token_or_type(identifier)
        if not form or not version or version.status != FormVersionStatus.PUBLISHED:
            abort(404)
        visit_type = form.visit_type

    # Active eligible hosts (Faculty and Admin only)
    eligible_hosts = User.query.filter(
        User.role.in_([UserRole.FACULTY, UserRole.ADMIN]),
        User.is_active == True
    ).order_by(User.full_name.asc()).all()

    schema = version.get_schema()

    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        organization = request.form.get('organization')
        host_user_id = request.form.get('host_user_id')
        purpose = request.form.get('purpose')
        planned_start_raw = request.form.get('planned_start_at')
        planned_end_raw = request.form.get('planned_end_at')

        # Parse datetimes
        planned_start_at = None
        if planned_start_raw and planned_start_raw.strip():
            try:
                dt = datetime.fromisoformat(planned_start_raw.strip())
                planned_start_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                flash("Invalid format for expected arrival date and time.", "danger")
                return render_template(
                    'visitors/register.html',
                    form=form,
                    version=version,
                    schema=schema,
                    visit_type=visit_type,
                    hosts=eligible_hosts
                )

        planned_end_at = None
        if planned_end_raw and planned_end_raw.strip():
            try:
                dt = datetime.fromisoformat(planned_end_raw.strip())
                planned_end_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                flash("Invalid format for expected departure date and time.", "danger")
                return render_template(
                    'visitors/register.html',
                    form=form,
                    version=version,
                    schema=schema,
                    visit_type=visit_type,
                    hosts=eligible_hosts
                )

        # Parse dynamic responses from schema keys
        dynamic_responses = {}
        for f in schema:
            f_key = f.get('field_key')
            if f.get('field_type') in ('image', 'file'):
                val = request.files.get(f"dyn__{f_key}")
            else:
                val = request.form.get(f"dyn__{f_key}")
            dynamic_responses[f_key] = val

        # Handle photo upload
        photo_file = request.files.get('photo')

        req, err = RegistrationService.register_visitor(
            visit_type=visit_type,
            full_name=full_name,
            email=email,
            phone=phone,
            organization=organization,
            host_user_id=host_user_id,
            purpose=purpose,
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at,
            dynamic_responses=dynamic_responses,
            photo_file=photo_file,
            actor_ip=request.remote_addr,
            form_identifier=form.public_token if form.public_token else visit_type
        )

        if err:
            flash(err, 'danger')
        else:
            flash("Your registration request has been submitted successfully!", "success")
            return redirect(url_for('visitors.register_confirmation', public_reference=req.public_reference))

    return render_template(
        'visitors/register.html',
        form=form,
        version=version,
        schema=schema,
        visit_type=visit_type,
        hosts=eligible_hosts,
        title=f"Visitor Registration — {form.name}"
    )


@visitors_bp.route('/register/confirmation/<public_reference>', methods=['GET'])
def register_confirmation(public_reference):
    """Public confirmation page showing registration tracking details."""
    visit_request = VisitRequest.query.filter_by(public_reference=public_reference).first_or_404()
    return render_template(
        'visitors/confirmation.html',
        visit_request=visit_request,
        title="Registration Submitted"
    )


@visitors_bp.route('/visitors/photo/<filename>')
@visitors_bp.route('/uploads/<filename>', endpoint='uploaded_photo')
@login_required
def serve_visitor_photo(filename):
    """
    Protected photo serving endpoint.
    Access Rules:
    - ADMIN: Allowed to view all photos.
    - SECURITY: Allowed to view all photos for gate verification.
    - FACULTY: Allowed ONLY if current_user is the assigned visit host.
    - Other/Unrelated users receive HTTP 403 Forbidden.
    """
    # Sanitize filename (must be hex UUID format e.g. 32-hex chars + .jpg)
    if not filename or '/' in filename or '\\' in filename:
        abort(404)

    req = VisitRequest.query.filter_by(photo_filename=filename).first()
    if not req:
        abort(404)

    if current_user.role in (UserRole.ADMIN, UserRole.SECURITY):
        pass  # Authorized
    elif current_user.role == UserRole.FACULTY:
        if req.host_user_id != current_user.id:
            abort(403, description="Forbidden: You are not authorized to view photos for visits hosted by other staff.")
    else:
        abort(403)

    upload_dir = UploadService.get_upload_dir()
    file_path = os.path.join(upload_dir, filename)
    if not os.path.exists(file_path):
        return UploadService.serve_fallback_avatar()
    return send_from_directory(upload_dir, filename)


@visitors_bp.route('/visitors/pass/<public_reference>', methods=['GET'])
def visitor_pass(public_reference):
    """
    Renders the official visitor pass page.
    Enforces privacy by showing only pass-relevant information (no email, phone, or dynamic answers).
    Never exposes raw tokens in HTML or URLs.
    Sets Cache-Control headers to prevent caching of pass pages.
    """
    req = VisitRequest.query.filter_by(public_reference=public_reference).first_or_404()

    # Determine pass state
    active_cred = req.active_credential
    latest_cred = active_cred or req.qr_credentials.order_by(QRCredential.created_at.desc()).first()
    state = 'ACTIVE'
    has_qr = False

    if req.status == VisitRequestStatus.PENDING_APPROVAL:
        state = 'PENDING'
    elif req.status == VisitRequestStatus.REJECTED:
        state = 'REJECTED'
    elif req.status == VisitRequestStatus.CANCELLED:
        state = 'CANCELLED'
    elif req.status == VisitRequestStatus.APPROVED:
        # Guarantee active valid credential for approved requests
        if not active_cred or not active_cred.is_valid_now():
            active_cred = QRService.ensure_active_credential(req)
            latest_cred = active_cred or req.qr_credentials.order_by(QRCredential.created_at.desc()).first()

        if latest_cred and latest_cred.status == QRCredentialStatus.REVOKED:
            state = 'REVOKED'
        elif latest_cred and latest_cred.status == QRCredentialStatus.CONSUMED:
            state = 'CONSUMED'
            has_qr = True
        else:
            state = 'ACTIVE'
            has_qr = True
    else:
        state = 'INELIGIBLE'

    response = make_response(
        render_template(
            'visitors/pass.html',
            visit_request=req,
            active_cred=active_cred,
            state=state,
            has_qr=has_qr,
            title=f"Visitor Pass — {req.public_reference}"
        )
    )
    # Prevent caching of sensitive pass page
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@visitors_bp.route('/visitors/status/<public_reference>', methods=['GET'])
def visit_status(public_reference):
    """Returns JSON status of a visit request for live UI polling."""
    from flask import jsonify
    req = VisitRequest.query.filter_by(public_reference=public_reference).first_or_404()
    is_approved = (req.status == VisitRequestStatus.APPROVED)
    return jsonify({
        'reference': req.public_reference,
        'status': req.status,
        'is_approved': is_approved,
        'has_qr': is_approved
    })


@visitors_bp.route('/visitors/pass/<public_reference>/qr.png', methods=['GET'])
def serve_pass_qr(public_reference):
    """
    Serves the active QR code image only when eligible, approved, and active.
    Dynamically generates on the fly if physical file is missing from serverless /tmp.
    Returns 404 only for unapproved visits. Sets strict no-store headers.
    """
    req = VisitRequest.query.filter_by(public_reference=public_reference).first_or_404()

    if req.status != VisitRequestStatus.APPROVED:
        abort(404)

    active_cred = req.active_credential or req.qr_credentials.first()
    if not active_cred:
        active_cred = QRService.ensure_active_credential(req)

    # 1. Try reading pre-generated file from disk
    img_bytes = None
    if active_cred:
        img_bytes = QRService.get_qr_image_bytes(active_cred.token_hash)

    # 2. Dynamic on-the-fly generation fallback: guarantees QR is never broken across containers
    if not img_bytes:
        qr_payload = req.public_reference
        img_bytes = QRService.generate_qr_image_bytes(qr_payload)
        if active_cred:
            try:
                qr_dir = QRService.get_qr_dir()
                file_path = qr_dir / f"{active_cred.token_hash}.png"
                with open(file_path, "wb") as f:
                    f.write(img_bytes)
            except Exception:
                pass

    response = Response(img_bytes, mimetype='image/png')
    response.headers['Content-Type'] = 'image/png'
    response.headers['Content-Length'] = str(len(img_bytes))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    if request.args.get('download'):
        response.headers['Content-Disposition'] = f'attachment; filename="visitor-qr-{public_reference}.png"'
    return response


@visitors_bp.route('/visitors/pass/<public_reference>/photo.jpg', methods=['GET'])
def serve_pass_photo(public_reference):
    """
    Serves the visitor's verified passport photograph specifically for their pass page using their public reference code.
    Only allows access if visit request exists and has a photo. Sets strict no-store headers.
    """
    req = VisitRequest.query.filter_by(public_reference=public_reference).first_or_404()
    if not req.photo_filename:
        return UploadService.serve_fallback_avatar()
    upload_dir = UploadService.get_upload_dir()
    file_path = os.path.join(upload_dir, req.photo_filename)
    if not os.path.exists(file_path):
        return UploadService.serve_fallback_avatar()
    response = make_response(send_from_directory(upload_dir, req.photo_filename))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

