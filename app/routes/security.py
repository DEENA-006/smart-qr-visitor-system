from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import current_user
from app.extensions import db
from app.models.user import UserRole
from app.models.audit_log import AuditLog, AuditAction, AuditOutcome
from app.services.auth_service import role_required
from app.services.rate_limiter import rate_limit
from app.services.gate_service import GateService

security_bp = Blueprint('security', __name__, url_prefix='/security')


@security_bp.route('/dashboard')
@role_required(UserRole.SECURITY)
def dashboard():
    """Security operations dashboard for scanning and gate verification."""
    kpis = GateService.get_security_kpis()
    recent_active = GateService.get_active_sessions(limit=5)

    return render_template(
        'security/dashboard.html',
        kpis=kpis,
        recent_active=recent_active,
        title="Security Operations Desk"
    )


@security_bp.route('/scan')
@role_required(UserRole.SECURITY, UserRole.ADMIN)
def scan():
    """Gate scanner interface for optical QR reading and manual fallback entry."""
    kpis = GateService.get_security_kpis()
    return render_template(
        'security/scan.html',
        kpis=kpis,
        title="Gate Credential Scanner"
    )


@security_bp.route('/verify', methods=['POST'])
@role_required(UserRole.SECURITY, UserRole.ADMIN)
@rate_limit('RATE_LIMIT_GATE', methods=['POST'])
def verify_credential():
    """
    API endpoint: Verifies a scanned QR token or manual reference code.
    Does NOT alter session state or check in the visitor.
    Returns JSON verification response.
    """
    # Accept either JSON body or form post
    if request.is_json:
        data = request.get_json() or {}
        raw_input = data.get('credential') or data.get('reference') or ''
    else:
        raw_input = request.form.get('credential') or request.form.get('reference') or ''

    result = GateService.verify_credential_or_reference(raw_input, current_user)
    
    # HTTP status code
    status_code = 200 if result.get('valid') else 400
    if result.get('status') == 'UNAUTHORIZED':
        status_code = 403
    elif result.get('status') == 'NOT_FOUND':
        status_code = 404

    return jsonify(result), status_code


@security_bp.route('/check-in', methods=['POST'])
@role_required(UserRole.SECURITY, UserRole.ADMIN)
@rate_limit('RATE_LIMIT_GATE', methods=['POST'])
def check_in():
    """
    Confirms physical identity match and checks visitor into the campus.
    Consumes the single-use QR credential and creates an active VisitSession.
    """
    if request.is_json:
        data = request.get_json() or {}
        request_id = data.get('request_id')
        notes = data.get('notes')
    else:
        request_id = request.form.get('request_id', type=int)
        notes = request.form.get('notes')

    if not request_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Missing request_id.'}), 400
        flash("Invalid request identifier.", "danger")
        return redirect(url_for('security.scan'))

    session, err = GateService.check_in(
        request_id=int(request_id),
        actor_user=current_user,
        notes=notes,
        client_ip=request.remote_addr
    )

    if err:
        if request.is_json:
            return jsonify({'success': False, 'message': err}), 400
        flash(err, "danger")
        return redirect(url_for('security.scan'))

    msg = f"Check-in confirmed for {session.visit_request.visitor.full_name if (session.visit_request and session.visit_request.visitor) else 'visitor'}. Session #{session.id} active."
    if request.is_json:
        return jsonify({
            'success': True,
            'message': msg,
            'session_id': session.id,
            'checked_in_at': session.checked_in_at.isoformat()
        }), 200

    flash(msg, "success")
    return redirect(url_for('security.occupancy'))


@security_bp.route('/check-out', methods=['POST'])
@role_required(UserRole.SECURITY, UserRole.ADMIN)
@rate_limit('RATE_LIMIT_GATE', methods=['POST'])
def check_out():
    """
    Checks visitor out of campus and marks VisitSession as COMPLETED.
    """
    if request.is_json:
        data = request.get_json() or {}
        session_id = data.get('session_id')
        notes = data.get('notes')
    else:
        session_id = request.form.get('session_id', type=int)
        notes = request.form.get('notes')

    if not session_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Missing session_id.'}), 400
        flash("Invalid session identifier.", "danger")
        return redirect(url_for('security.occupancy'))

    session, err = GateService.check_out(
        session_id=int(session_id),
        actor_user=current_user,
        notes=notes,
        client_ip=request.remote_addr
    )

    if err:
        if request.is_json:
            return jsonify({'success': False, 'message': err}), 400
        flash(err, "danger")
        return redirect(url_for('security.occupancy'))

    msg = f"Check-out confirmed for {session.visit_request.visitor.full_name if (session.visit_request and session.visit_request.visitor) else 'visitor'}. Session #{session.id} completed."
    if request.is_json:
        return jsonify({
            'success': True,
            'message': msg,
            'session_id': session.id,
            'checked_out_at': session.checked_out_at.isoformat()
        }), 200

    flash(msg, "info")
    return redirect(url_for('security.occupancy'))


@security_bp.route('/requests/<int:request_id>/edit-details', methods=['POST'])
@role_required(UserRole.SECURITY, UserRole.ADMIN)
@rate_limit('RATE_LIMIT_GATE', methods=['POST'])
def edit_visitor_details(request_id):
    """
    Corrects permitted visitor details (name, phone, email, organization, purpose)
    from the security scanner panel.
    Preserves audit logging and does not trigger check-in/out or approval modifications.
    """
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    notes = data.get('notes')

    req, err = GateService.update_visitor_details(
        request_id=request_id,
        actor_user=current_user,
        data=data,
        notes=notes,
        client_ip=request.remote_addr
    )

    if err:
        if request.is_json:
            return jsonify({'success': False, 'message': err}), 400
        flash(err, "danger")
        return redirect(url_for('security.scan'))

    msg = f"Visitor details for {req.visitor.full_name} ({req.public_reference}) updated successfully."
    if request.is_json:
        return jsonify({
            'success': True,
            'message': msg,
            'visitor_details': GateService._extract_visitor_details(req)
        }), 200

    flash(msg, "success")
    return redirect(url_for('security.scan', q=req.public_reference))


@security_bp.route('/occupancy')
@role_required(UserRole.SECURITY, UserRole.ADMIN)
def occupancy():
    """Live on-campus visitor headcount and active session management."""
    active_sessions = GateService.get_active_sessions(limit=200)
    current_occupancy = len(active_sessions)
    kpis = GateService.get_security_kpis()

    return render_template(
        'security/occupancy.html',
        active_sessions=active_sessions,
        current_occupancy=current_occupancy,
        kpis=kpis,
        title="Live Campus Occupancy"
    )


@security_bp.route('/emergency-list')
@role_required(UserRole.SECURITY, UserRole.ADMIN)
def emergency_list():
    """
    Real-time campus emergency evacuation muster roll.
    Derives strictly from active on-campus visit sessions.
    """
    # Log emergency list viewing for compliance
    AuditLog.query.session.add(
        AuditLog(
            actor_user_id=current_user.id,
            action=AuditAction.EMERGENCY_LIST_VIEWED,
            entity_type='REPORT',
            entity_reference='Live Campus Emergency Muster Roll',
            outcome=AuditOutcome.SUCCESS,
            ip_address=request.remote_addr
        )
    )
    AuditLog.query.session.commit()

    active_sessions = GateService.get_active_sessions(limit=1000)
    generated_at_utc = datetime.now(timezone.utc)

    return render_template(
        'security/emergency_list.html',
        active_sessions=active_sessions,
        headcount=len(active_sessions),
        generated_at=generated_at_utc,
        title="Campus Emergency Visitor Evacuation List"
    )
