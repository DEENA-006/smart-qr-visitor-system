from flask import Blueprint, redirect, url_for
from flask_login import current_user
from app.services.auth_service import AuthService

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Root endpoint: redirects authenticated users to their dashboard, otherwise to login."""
    if current_user.is_authenticated:
        return redirect(url_for(AuthService.get_dashboard_endpoint(current_user)))
    return redirect(url_for('auth.login'))
