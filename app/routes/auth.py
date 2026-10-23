from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from app.services.auth_service import AuthService
from app.services.rate_limiter import rate_limit

auth_bp = Blueprint('auth', __name__)


def is_safe_url(target: str) -> bool:
    """Ensures redirect target is an internal relative URL to prevent open redirect vulnerabilities."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    return test_url.scheme in ('', 'http', 'https') and ref_url.netloc == test_url.netloc or not test_url.netloc


@auth_bp.route('/login', methods=['GET', 'POST'])
@rate_limit('RATE_LIMIT_LOGIN', methods=['POST'])
def login():
    """Login view supporting both GET presentation and POST authentication."""
    if current_user.is_authenticated:
        return redirect(url_for(AuthService.get_dashboard_endpoint(current_user)))

    next_page = request.args.get('next')

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        
        user, error = AuthService.authenticate_user(identifier, password)
        if error:
            flash(error, 'danger')
            return render_template('auth/login.html', identifier=identifier, next=next_page), 401

        flash(f"Welcome back, {user.full_name}!", 'success')
        
        # Verify next_page redirect
        if next_page and is_safe_url(next_page) and next_page != url_for('auth.login'):
            return redirect(next_page)
        
        return redirect(url_for(AuthService.get_dashboard_endpoint(user)))

    return render_template('auth/login.html', next=next_page)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logs out user and invalidates session. Strictly requires POST."""
    AuthService.logout_current_user()
    flash("You have been signed out safely.", "info")
    return redirect(url_for('auth.login'))
