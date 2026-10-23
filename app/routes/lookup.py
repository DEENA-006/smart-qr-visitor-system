from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user
from app.models.user import UserRole
from app.services.auth_service import role_required
from app.services.rate_limiter import rate_limit
from app.services.lookup_service import LookupService

lookup_bp = Blueprint('lookup', __name__, url_prefix='/lookup')


@lookup_bp.route('', methods=['GET'])
@role_required(UserRole.ADMIN, UserRole.FACULTY)
def scan():
    """Authorized visitor lookup interface for Administrators and Faculty."""
    return render_template(
        'lookup/scan.html',
        title="Visitor Credential Lookup"
    )


@lookup_bp.route('/verify', methods=['POST'])
@role_required(UserRole.ADMIN, UserRole.FACULTY)
@rate_limit('RATE_LIMIT_GATE', methods=['POST'])
def verify():
    """
    API endpoint: Looks up visitor details by scanned QR token or manual reference code.
    View-only. Does NOT check in the visitor, check out, or alter credential state.
    """
    if request.is_json:
        data = request.get_json() or {}
        raw_input = data.get('credential') or data.get('reference') or ''
    else:
        raw_input = request.form.get('credential') or request.form.get('reference') or ''

    result, status_code = LookupService.lookup_visitor(raw_input, current_user)
    return jsonify(result), status_code
